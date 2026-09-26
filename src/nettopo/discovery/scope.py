"""Decide quais vizinhos entram na fila de descoberta."""

from __future__ import annotations

import asyncio
import socket

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


async def next_targets(device: Device, settings: Settings) -> list[tuple[str, str | None]]:
    """Retorna ``[(ip, hostname_anunciado)]`` a partir dos vizinhos do equipamento."""
    protos = followed_protocols(settings)
    out: list[tuple[str, str | None]] = []
    seen: set[str] = set()
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
        if router_id and router_id in seen:
            continue
        ip = n.remote_mgmt_ip
        if not ip and n.remote_hostname and settings.dns_resolve:
            ip = await resolve_hostname(n.remote_hostname)
        if ip and is_usable_ip(ip) and ip not in seen and settings.scope.allows_ip(ip):
            seen.add(ip)
            if host:
                seen_hosts.add(host)
            if router_id:
                seen.add(router_id)
            out.append((ip, n.remote_hostname))
    if settings.follow.arp:
        for a in device.arp:
            if a.ip not in seen and is_usable_ip(a.ip) and settings.scope.allows_ip(a.ip):
                seen.add(a.ip)
                out.append((a.ip, None))
    return out
