"""Varredura opcional das redes de gerência (desligada por padrão).

Encontra equipamentos que ninguém anuncia com um IP alcançável: para cada endereço das sub-redes
configuradas em ``varredura`` testa as portas de gerência e o SNMP, respeitando escopo e rate limit.
Só os endereços que respondem viram alvos de coleta.
"""

from __future__ import annotations

import asyncio
import inspect
import ipaddress
from typing import Any

from nettopo.config import Settings
from nettopo.discovery.fingerprint import PORTS, scan_ports
from nettopo.discovery.scope import Target
from nettopo.utils import is_usable_ip


def sweep_hosts(settings: Settings) -> list[str]:
    hosts: list[str] = []
    for cidr in settings.varredura:
        try:
            net = ipaddress.IPv4Network(cidr, strict=False)
        except ValueError:
            continue
        for ip in (net.hosts() if net.prefixlen < 31 else net):
            s = str(ip)
            if is_usable_ip(s) and settings.scope.allows_ip(s) and s not in hosts:
                hosts.append(s)
            if len(hosts) >= settings.varredura_max_hosts:
                return hosts
    return hosts


async def sweep(settings: Settings, collector: Any, known: dict[str, list[str]] | None = None,
                progress: Any = None) -> list[Target]:
    hosts = sweep_hosts(settings)
    if not hosts:
        return []
    known_ips = {ip for ips in (known or {}).values() for ip in ips}
    hosts = [h for h in hosts if h not in known_ips]  # conhecidos já passam pela revalidação
    sem = asyncio.Semaphore(max(1, min(settings.concurrency, settings.carga.concurrency) * 4))
    snmp = getattr(collector, "snmp", None)
    snmp_creds = settings.creds("snmp") if "snmp" in settings.methods else []
    found: list[Target] = []

    async def no_snmp() -> None:
        return None

    async def probe(ip: str) -> None:
        async with sem:
            # portas e SNMP em paralelo: um IP vazio custa o maior dos dois timeouts, não a soma
            ports, probed = await asyncio.gather(
                scan_ports(ip, [PORTS["ssh"], PORTS["netconf"], PORTS["https"], PORTS["http"]], timeout=1.0),
                snmp.probe(ip, snmp_creds) if snmp is not None and snmp_creds else no_snmp())
            name = None
            if probed:
                from nettopo.collectors.snmp import to_text

                name = to_text(probed[1].get("name"))
            if ports or name:
                found.append(Target(candidates=[(ip, "varredura")], hostname=name))

    await asyncio.gather(*(probe(h) for h in hosts))
    found.sort(key=lambda t: ipaddress.IPv4Address(t.candidates[0][0]))
    if progress is not None:
        r = progress({"type": "sweep", "tested": len(hosts), "found": len(found)})
        if inspect.isawaitable(r):
            await r
    return found
