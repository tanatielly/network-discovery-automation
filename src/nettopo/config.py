"""Configuração da descoberta: sementes, escopo, credenciais e opções."""

from __future__ import annotations

import ipaddress
import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, SecretStr, field_validator

from nettopo.utils import parse_ipv4

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

DEFAULT_PRIVATE_RANGES = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10"]


def _secret(v: SecretStr | None) -> str | None:
    return v.get_secret_value() if v is not None else None


class Credential(BaseModel):
    """Credencial de acesso. Várias podem ser informadas; são testadas em ordem."""

    name: str = ""
    type: Literal["ssh", "snmp", "netconf", "rest"]
    username: str | None = None
    password: SecretStr | None = None
    enable_secret: SecretStr | None = None
    port: int | None = None
    # SNMP
    version: Literal["1", "2c", "3"] = "2c"
    community: SecretStr | None = None
    auth_protocol: str | None = "sha"
    auth_key: SecretStr | None = None
    priv_protocol: str | None = "aes"
    priv_key: SecretStr | None = None
    context: str | None = None
    # REST
    token: SecretStr | None = None
    verify_ssl: bool = False
    https: bool = True

    @field_validator("version", mode="before")
    @classmethod
    def _v(cls, v: Any) -> Any:
        return str(v).lower().lstrip("v") if v is not None else v

    def secret(self, field: str) -> str | None:
        return _secret(getattr(self, field))

    @property
    def display(self) -> str:
        who = self.username or ("community" if self.community else "")
        return self.name or f"{self.type}:{who}"


class Scope(BaseModel):
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    hostname_exclude: list[str] = Field(default_factory=list)  # regex

    def _nets(self, items: list[str]) -> list[ipaddress.IPv4Network]:
        nets = []
        for c in items:
            try:
                nets.append(ipaddress.IPv4Network(c, strict=False))
            except ValueError:
                continue
        return nets

    def allows_ip(self, ip: str | None, extra_allowed: set[str] | None = None) -> bool:
        ip = parse_ipv4(ip)
        if not ip:
            return False
        if extra_allowed and ip in extra_allowed:
            return True
        addr = ipaddress.IPv4Address(ip)
        if any(addr in n for n in self._nets(self.exclude)):
            return False
        include = self._nets(self.include or DEFAULT_PRIVATE_RANGES)
        return any(addr in n for n in include)

    def allows_hostname(self, hostname: str | None) -> bool:
        if not hostname:
            return True
        return not any(re.search(p, hostname, re.IGNORECASE) for p in self.hostname_exclude)


class FollowOptions(BaseModel):
    """Quais fontes de vizinhança alimentam a fila de descoberta."""

    lldp: bool = True
    cdp: bool = True
    other_l2: bool = True  # MNDP (MikroTik), EDP (Extreme), FDP (Brocade/Ruckus)
    routing: bool = True  # vizinhos OSPF/BGP/IS-IS
    arp: bool = False  # varrer a tabela ARP (agressivo)


class CollectOptions(BaseModel):
    interfaces: bool = True
    arp: bool = True
    routes: bool = True
    vlans: bool = True
    mac_table: bool = False
    routing_neighbors: bool = True
    route_limit: int = 5000


class Settings(BaseModel):
    name: str | None = None
    seeds: list[str] = Field(default_factory=list)
    scope: Scope = Field(default_factory=Scope)
    max_depth: int = 6
    max_devices: int = 2000
    concurrency: int = 16
    timeout: int = 15
    snmp_retries: int = 1
    methods: list[Literal["rest", "netconf", "ssh", "snmp"]] = Field(
        default_factory=lambda: ["rest", "netconf", "ssh", "snmp"]
    )
    snmp_complement: bool = True  # usa SNMP para completar dados mesmo com SSH/API ok
    dns_resolve: bool = True
    infer_l3_links: bool = True
    credentials: list[Credential] = Field(default_factory=list)
    follow: FollowOptions = Field(default_factory=FollowOptions)
    collect: CollectOptions = Field(default_factory=CollectOptions)

    def creds(self, kind: str) -> list[Credential]:
        return [c for c in self.credentials if c.type == kind]

    def sanitized(self) -> dict[str, Any]:
        """Configuração sem segredos (para relatórios/persistência)."""
        data = self.model_dump(mode="json")
        for c in data.get("credentials", []):
            for k in ("password", "enable_secret", "community", "auth_key", "priv_key", "token"):
                if c.get(k):
                    c[k] = "***"
        return data


def _expand_env(obj: Any) -> Any:
    if isinstance(obj, str):
        return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), obj)
    if isinstance(obj, list):
        return [_expand_env(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _expand_env(v) for k, v in obj.items()}
    return obj


def load_settings(path: str | Path | None = None, **overrides: Any) -> Settings:
    data: dict[str, Any] = {}
    if path:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        data = _expand_env(raw)
    for k, v in overrides.items():
        if v is not None:
            data[k] = v
    return Settings.model_validate(data)
