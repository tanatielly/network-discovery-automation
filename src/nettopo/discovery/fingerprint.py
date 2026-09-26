"""Identificação de vendor/SO de um alvo: SNMP sysObjectID/sysDescr -> autodetect SSH -> portas."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from nettopo.config import Credential
from nettopo.vendors.registry import VendorProfile

PORTS = {"ssh": 22, "netconf": 830, "https": 443, "http": 80, "mikrotik_api": 8728}


@dataclass
class Fingerprint:
    target: str
    profile: VendorProfile | None = None
    method: str | None = None  # como o perfil foi identificado
    snmp_cred: Credential | None = None
    system: dict[str, Any] | None = None
    ssh_cred: Credential | None = None
    open_ports: set[int] = field(default_factory=set)


async def port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    return True


async def scan_ports(host: str, ports: list[int], timeout: float = 2.0) -> set[int]:
    results = await asyncio.gather(*(port_open(host, p, timeout) for p in ports))
    return {p for p, ok in zip(ports, results, strict=True) if ok}
