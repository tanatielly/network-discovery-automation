"""Controle de carga por equipamento (rate limit).

Equipamentos antigos ou com CPU modesta podem sofrer com rajadas de SNMP/SSH. Este módulo aplica,
por equipamento:

- no máximo ``sessoes_por_equipamento`` coletas simultâneas;
- intervalo mínimo entre requisições (PDU SNMP, comando SSH, chamada REST/NETCONF);
- tamanho de lote SNMP (``max-repetitions``) e quantas colunas são lidas em paralelo;
- atraso extra entre comandos SSH;
- teto de falhas de autenticação, para não bloquear contas em servidores AAA (TACACS/RADIUS).

O controle do equipamento corrente viaja num ``ContextVar``: vale tanto no código assíncrono
quanto nas threads de Netmiko/ncclient (``asyncio.to_thread`` copia o contexto).
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import threading
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any, Literal

from pydantic import BaseModel, Field


class LoadProfile(BaseModel):
    sessoes_por_equipamento: int = 1
    intervalo_min_ms: int = 100
    snmp_max_repetitions: int = 25
    snmp_walks_paralelos: int = 2
    ssh_atraso_comando_s: float = 0.2
    max_falhas_autenticacao: int = 3
    concorrencia_max: int = 16  # equipamentos coletados ao mesmo tempo (global)


PRESETS: dict[str, LoadProfile] = {
    "conservador": LoadProfile(sessoes_por_equipamento=1, intervalo_min_ms=500, snmp_max_repetitions=10,
                               snmp_walks_paralelos=1, ssh_atraso_comando_s=1.0, max_falhas_autenticacao=2,
                               concorrencia_max=4),
    "equilibrado": LoadProfile(),
    "rapido": LoadProfile(sessoes_por_equipamento=2, intervalo_min_ms=0, snmp_max_repetitions=50,
                          snmp_walks_paralelos=4, ssh_atraso_comando_s=0.0, max_falhas_autenticacao=5,
                          concorrencia_max=64),
}

PresetName = Literal["conservador", "equilibrado", "rapido"]


class LoadOverride(BaseModel):
    """Ajuste para um grupo de equipamentos. Critérios combinam com E; campos vazios não restringem."""

    cidr: str | None = None
    fabricante: str | None = None  # id do perfil de fabricante (ex.: hp_procurve) ou regex
    hostname: str | None = None  # regex
    perfil: PresetName | None = None
    sessoes_por_equipamento: int | None = None
    intervalo_min_ms: int | None = None
    snmp_max_repetitions: int | None = None
    snmp_walks_paralelos: int | None = None
    ssh_atraso_comando_s: float | None = None
    max_falhas_autenticacao: int | None = None

    def matches(self, ip: str | None, profile_id: str | None, hostname: str | None) -> bool:
        if self.cidr:
            try:
                if not ip or ipaddress.ip_address(ip) not in ipaddress.ip_network(self.cidr, strict=False):
                    return False
            except ValueError:
                return False
        if self.fabricante and not (profile_id and re.fullmatch(self.fabricante, profile_id)):
            return False
        if self.hostname and not (hostname and re.search(self.hostname, hostname, re.I)):
            return False
        return bool(self.cidr or self.fabricante or self.hostname)


class LoadSettings(BaseModel):
    perfil: PresetName = "equilibrado"
    overrides: list[LoadOverride] = Field(default_factory=list)

    def resolve(self, ip: str | None = None, profile_id: str | None = None,
                hostname: str | None = None) -> tuple[str, LoadProfile]:
        name: str = self.perfil
        values = PRESETS[name].model_dump()
        for ov in self.overrides:
            if not ov.matches(ip, profile_id, hostname):
                continue
            if ov.perfil:
                name = ov.perfil
                values = PRESETS[ov.perfil].model_dump()
            for k, v in ov.model_dump(exclude={"cidr", "fabricante", "hostname", "perfil"}).items():
                if v is not None:
                    values[k] = v
                    name = f"{name}+ajuste"
        return name, LoadProfile.model_validate(values)

    @property
    def concurrency(self) -> int:
        return PRESETS[self.perfil].concorrencia_max


class DeviceThrottle:
    """Ritmo e sessões de um equipamento."""

    def __init__(self, key: str, name: str, profile: LoadProfile):
        self.key = key
        self.name = name
        self.profile = profile
        self._lock = threading.Lock()
        self._next = 0.0
        self._last: float | None = None
        self._sessions: asyncio.Semaphore | None = None
        self.requests = 0
        self.waited = 0.0
        self.min_gap: float | None = None
        self.active = 0
        self.max_active = 0
        self.auth_failures = 0

    def update(self, name: str, profile: LoadProfile) -> None:
        """Troca o perfil depois que o fabricante é identificado (ajustes por fabricante)."""
        self.name, self.profile = name, profile

    # ----------------------------------------------------------------- ritmo
    def _reserve(self, extra_s: float = 0.0) -> float:
        interval = max(self.profile.intervalo_min_ms / 1000.0, extra_s)
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next)
            self._next = slot + interval
            if self._last is not None:
                gap = slot - self._last
                self.min_gap = gap if self.min_gap is None else min(self.min_gap, gap)
            self._last = slot
            self.requests += 1
            delay = slot - now
            self.waited += delay
            return delay

    async def pace(self, extra_s: float = 0.0) -> None:
        delay = self._reserve(extra_s)
        if delay > 0:
            await asyncio.sleep(delay)

    def pace_sync(self, extra_s: float = 0.0) -> None:
        delay = self._reserve(extra_s)
        if delay > 0:
            time.sleep(delay)

    # ----------------------------------------------------------------- sessões
    @asynccontextmanager
    async def session(self):  # noqa: ANN201
        if self._sessions is None:
            self._sessions = asyncio.Semaphore(max(1, self.profile.sessoes_por_equipamento))
        async with self._sessions:
            with self._lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            try:
                yield self
            finally:
                with self._lock:
                    self.active -= 1

    # ----------------------------------------------------------------- autenticação
    def can_try_auth(self) -> bool:
        return self.auth_failures < self.profile.max_falhas_autenticacao

    def auth_failed(self) -> None:
        with self._lock:
            self.auth_failures += 1

    def stats(self) -> dict[str, Any]:
        return {
            "perfil": self.name,
            "requisicoes": self.requests,
            "espera_aplicada_s": round(self.waited, 2),
            "menor_intervalo_ms": None if self.min_gap is None else round(self.min_gap * 1000),
            "intervalo_configurado_ms": self.profile.intervalo_min_ms,
            "max_sessoes_simultaneas": self.max_active,
            "falhas_autenticacao": self.auth_failures,
        }


class ThrottleRegistry:
    def __init__(self, settings: LoadSettings):
        self.settings = settings
        self._items: dict[str, DeviceThrottle] = {}
        self._lock = threading.Lock()

    def get(self, ip: str, profile_id: str | None = None, hostname: str | None = None) -> DeviceThrottle:
        name, profile = self.settings.resolve(ip, profile_id, hostname)
        with self._lock:
            t = self._items.get(ip)
            if t is None:
                t = self._items[ip] = DeviceThrottle(ip, name, profile)
            elif profile_id or hostname:
                t.update(name, profile)
            return t


_current: ContextVar[DeviceThrottle | None] = ContextVar("nettopo_throttle", default=None)


def current() -> DeviceThrottle | None:
    return _current.get()


def use(throttle: DeviceThrottle | None) -> Any:
    """Define o controle do equipamento corrente; devolve o token para ``reset``."""
    return _current.set(throttle)


def reset(token: Any) -> None:
    _current.reset(token)


async def pace(extra_s: float = 0.0) -> None:
    t = _current.get()
    if t is not None:
        await t.pace(extra_s)


def pace_sync(extra_s: float = 0.0) -> None:
    t = _current.get()
    if t is not None:
        t.pace_sync(extra_s)


def auth_allowed() -> bool:
    t = _current.get()
    return t is None or t.can_try_auth()


def auth_failed() -> None:
    t = _current.get()
    if t is not None:
        t.auth_failed()


def snmp_params() -> tuple[int, int]:
    """(max-repetitions, walks em paralelo) do equipamento corrente."""
    t = _current.get()
    p = t.profile if t is not None else PRESETS["equilibrado"]
    return p.snmp_max_repetitions, max(1, p.snmp_walks_paralelos)


def ssh_command_delay() -> float:
    t = _current.get()
    return t.profile.ssh_atraso_comando_s if t is not None else 0.0
