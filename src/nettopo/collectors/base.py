"""Contratos comuns dos coletores."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from nettopo.config import Credential
from nettopo.models import Device
from nettopo.vendors.registry import VendorProfile


class CollectorError(Exception):
    """Falha de coleta (autenticação, timeout, protocolo indisponível...)."""


class AuthError(CollectorError):
    pass


class UnreachableError(CollectorError):
    pass


@dataclass
class MethodResult:
    method: str
    device: Device | None = None
    credential: Credential | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.device is not None


class MethodCollector(Protocol):
    """Coletor de um protocolo (SNMP, SSH, NETCONF, REST)."""

    name: str

    async def collect(self, target: str, profile: VendorProfile | None,
                      credentials: list[Credential]) -> MethodResult: ...


class DeviceCollector(Protocol):
    """Coleta um equipamento completo a partir de um IP/hostname.

    Implementado pelo :class:`~nettopo.collectors.orchestrator.Orchestrator` (rede real)
    e pelo :class:`~nettopo.collectors.simulated.SimulatedCollector` (demo/testes).
    """

    async def collect(self, target: str) -> Device: ...

    async def close(self) -> None: ...
