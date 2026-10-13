"""Decide quais vizinhos entram na fila de descoberta."""

from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from typing import Protocol

from nettopo.config import Settings
from nettopo.models import L2_PROTOCOLS, ROUTING_PROTOCOLS, Device
from nettopo.utils import is_usable_ip, parse_ipv4, short_hostname


def followed_protocols(settings: Settings) -> set[str]:
    f = settings.follow
    protos: set[str] = set()
    if f.lldp:
        protos.add("lldp")
    if f.cdp:
        protos.add("cdp")
    if f.other_l2:
        protos |= L2_PROTOCOLS - {"lldp", "cdp"}
    if f.routing:
        protos |= ROUTING_PROTOCOLS
    return protos


async def resolve_hostname(name: str, timeout: float = 3.0) -> str | None:
    ip = parse_ipv4(name)
    if ip:
        return ip
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(loop.getaddrinfo(name, None, family=socket.AF_INET), timeout)
    except (OSError, asyncio.TimeoutError, UnicodeError):
        return None
    for info in infos:
        ip = parse_ipv4(info[4][0])
        if ip:
            return ip
    return None


@dataclass
class Target:
    """Um equipamento a coletar e os IPs candidatos para alcançá-lo, em ordem de preferência."""

    candidates: list[tuple[str, str]]  # (ip, origem): memoria | anunciado | dns | arp | semente | varredura
    hostname: str | None = None
    chassis: str | None = None
    macs: tuple[str, ...] = ()  # MACs anunciados (chassis/porta) para busca tardia nas tabelas ARP
    depth: int = 0
    parent: str | None = None

    @property
    def label(self) -> str:
        return self.hostname or (self.candidates[0][0] if self.candidates else "?")


class TargetHints(Protocol):
    """Fontes extras de IP de gerência (memória persistente, varredura, tabelas ARP coletadas)."""

    def ips_for_host(self, hostname: str | None) -> list[str]: ...

    def ips_for_mac(self, mac: str | None) -> list[str]: ...


async def next_targets(device: Device, settings: Settings, hints: TargetHints | None = None) -> list[Target]:
    """Alvos a partir dos vizinhos do equipamento, cada um com IPs candidatos.

    Candidatos imediatos: IP de gerência já conhecido (memória/varredura) e IP anunciado. DNS do hostname
    e IP pelo MAC nas tabelas ARP são resolvidos pelo engine só se esses falharem (evita consultas DNS
    desnecessárias). Equipamentos que anunciam um IP de interface de trânsito, não roteável para o
    servidor, continuam alcançáveis pelos candidatos tardios.
    """
    protos = followed_protocols(settings)
    out: list[Target] = []
    seen_ips: set[str] = set()
    seen_hosts: set[str] = set()
    # Vizinhos L2 primeiro (trazem IP de gerência e hostname); depois os de roteamento,
    # que são ignorados se o router-id apontar para um vizinho já enfileirado.
    ordered = sorted(device.neighbors, key=lambda n: n.protocol in ROUTING_PROTOCOLS)
    for n in ordered:
        if n.protocol not in protos:
            continue
        if n.protocol == "bgp" and n.state and "establish" not in n.state.lower() and not n.state.isdigit():
            continue  # sessão BGP inativa
        if not settings.scope.allows_hostname(n.remote_hostname):
            continue
        host = short_hostname(n.remote_hostname)
        if host and host in seen_hosts:
            continue
        router_id = parse_ipv4(n.remote_chassis_id) if n.protocol in ROUTING_PROTOCOLS else None
        if router_id and router_id in seen_ips:
            continue

        candidates: list[tuple[str, str]] = []

        def add(ip: str | None, origin: str, candidates: list[tuple[str, str]] = candidates) -> None:
            if ip and is_usable_ip(ip) and settings.scope.allows_ip(ip) and ip not in {c[0] for c in candidates}:
                candidates.append((ip, origin))

        if hints is not None and host:
            for ip in hints.ips_for_host(host):
                add(ip, "memoria")
        advertised = parse_ipv4(n.remote_mgmt_ip)
        if advertised and is_usable_ip(advertised) and not settings.scope.allows_ip(advertised) and not candidates:
            continue  # anuncia IP fora do escopo: não seguir
        add(advertised, "anunciado")
        macs = tuple(m for m in (n.remote_chassis_id, n.remote_interface) if m)
        if not candidates and not host:
            continue
        if any(ip in seen_ips for ip, _ in candidates):
            continue
        seen_ips.update(ip for ip, _ in candidates)
        if host:
            seen_hosts.add(host)
        if router_id:
            seen_ips.add(router_id)
        out.append(Target(candidates=candidates, hostname=n.remote_hostname, chassis=n.remote_chassis_id,
                          macs=macs))
    if settings.follow.arp:
        for a in device.arp:
            if a.ip not in seen_ips and is_usable_ip(a.ip) and settings.scope.allows_ip(a.ip):
                seen_ips.add(a.ip)
                out.append(Target(candidates=[(a.ip, "arp")]))
    return out
