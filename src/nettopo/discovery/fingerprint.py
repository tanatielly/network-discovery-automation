"""Identificação de vendor/SO de um alvo: SNMP sysObjectID/sysDescr -> autodetect SSH -> portas."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from nettopo import ratelimit
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
    ssh_banner: str | None = None
    open_ports: set[int] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)


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


async def read_ssh_banner(host: str, port: int = 22, timeout: float = 3.0) -> str | None:
    """Lê a linha de versão do servidor SSH (RFC 4253), antes de qualquer autenticação."""
    await ratelimit.pace()
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except (OSError, asyncio.TimeoutError):
        return None
    try:
        for _ in range(5):  # alguns servidores mandam linhas de aviso antes da versão
            line = await asyncio.wait_for(reader.readline(), timeout)
            if not line:
                break
            text = line.decode("utf-8", "replace").strip()
            if text.startswith("SSH-"):
                return text
    except (OSError, asyncio.TimeoutError):
        return None
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
    return None


async def scan_ports(host: str, ports: list[int], timeout: float = 2.0) -> set[int]:
    await ratelimit.pace()
    results = await asyncio.gather(*(port_open(host, p, timeout) for p in ports))
    return {p for p, ok in zip(ports, results, strict=True) if ok}
