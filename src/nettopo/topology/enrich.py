"""Enriquecimento: links L3 inferidos por sub-rede, adjacências de roteamento, LAG e velocidades."""

from __future__ import annotations

import ipaddress
from collections import defaultdict
from typing import TYPE_CHECKING

from nettopo.config import Settings
from nettopo.models import ROUTING_PROTOCOLS, Device, Link, Neighbor, Topology
from nettopo.utils import ifname_key, network_of
from nettopo.vendors.registry import VendorRegistry

if TYPE_CHECKING:
    from nettopo.topology.builder import NeighborResolver


def _pair_links(topo: Topology, a: str, b: str) -> list[Link]:
    return [lk for lk in topo.links if {lk.source, lk.target} == {a, b}]


def _iface_of(dev: Device, ip: str) -> str | None:
    for itf in dev.interfaces:
        if any(a.split("/")[0] == ip for a in itf.ipv4):
            return itf.name
    return None


def infer_l3_links(topo: Topology) -> None:
    """Sub-redes /30 e /31 compartilhadas por exatamente dois equipamentos viram links L3."""
    nets: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for d in topo.devices.values():
        if d.stub:
            continue
        for itf in d.interfaces:
            for cidr in itf.ipv4:
                net = network_of(cidr)
                if net is not None and net.prefixlen in (30, 31):
                    nets[str(net)].append((d.id, itf.name))
    for subnet, members in nets.items():
        ids = {m[0] for m in members}
        if len(ids) != 2:
            continue
        (a, ai), (b, bi) = members[0], next(m for m in members if m[0] != members[0][0])
        existing = _pair_links(topo, a, b)
        matched = False
        for lk in existing:
            ends = {(lk.source, ifname_key(lk.source_interface)), (lk.target, ifname_key(lk.target_interface))}
            if (a, ifname_key(ai)) in ends or (b, ifname_key(bi)) in ends or lk.kind == "physical":
                lk.subnet = lk.subnet or subnet
                matched = True
                break
        if not matched:
            topo.links.append(Link(source=a, source_interface=ai, target=b, target_interface=bi,
                                   protocols=["subnet"], kind="l3", subnet=subnet))


def routing_adjacencies(topo: Topology, resolver: NeighborResolver, registry: VendorRegistry) -> None:
    from nettopo.topology.builder import create_stub

    for dev in list(topo.devices.values()):
        for n in dev.neighbors:
            if n.protocol not in ROUTING_PROTOCOLS:
                continue
            rid = resolver.resolve(n)
            if rid is None:
                label = n.remote_mgmt_ip or n.remote_chassis_id
                if not label:
                    continue
                stub_n = Neighbor(protocol=n.protocol, remote_hostname=(f"AS{n.remote_asn} {label}" if n.remote_asn
                                                                       else label),
                                  remote_mgmt_ip=n.remote_mgmt_ip, remote_asn=n.remote_asn,
                                  remote_capabilities=["router"])
                rid = create_stub(stub_n, topo.devices, resolver, registry)
                topo.devices[rid].role = "external" if n.protocol == "bgp" else "router"
            if rid == dev.id:
                continue
            existing = _pair_links(topo, dev.id, rid)
            if existing:
                for lk in existing:
                    if n.protocol not in lk.protocols:
                        lk.protocols.append(n.protocol)
                continue
            local_if = n.local_interface
            if not local_if and n.remote_mgmt_ip:
                # interface local = a que está na mesma sub-rede do vizinho
                for itf in dev.interfaces:
                    for cidr in itf.ipv4:
                        net = network_of(cidr)
                        if net is not None and ipaddress.IPv4Address(n.remote_mgmt_ip) in net:
                            local_if = itf.name
            remote = topo.devices[rid]
            topo.links.append(Link(source=dev.id, source_interface=local_if, target=rid,
                                   target_interface=_iface_of(remote, n.remote_mgmt_ip or ""),
                                   protocols=[n.protocol], kind="logical"))


def annotate_links(topo: Topology) -> None:
    for lk in topo.links:
        a, b = topo.devices.get(lk.source), topo.devices.get(lk.target)
        ia = a.get_interface(lk.source_interface) if a else None
        ib = b.get_interface(lk.target_interface) if b else None
        speeds = [i.speed_mbps for i in (ia, ib) if i and i.speed_mbps]
        lk.speed_mbps = min(speeds) if speeds else lk.speed_mbps
        parents = [i.parent for i in (ia, ib) if i and i.parent]
        lk.lag = lk.lag or (" / ".join(dict.fromkeys(parents)) if parents else None)
        if not lk.subnet:
            for i in (ia, ib):
                for cidr in (i.ipv4 if i else []):
                    net = network_of(cidr)
                    if net is not None:
                        lk.subnet = str(net)
                        break
                if lk.subnet:
                    break


def enrich(topo: Topology, settings: Settings, resolver: NeighborResolver, registry: VendorRegistry) -> None:
    if settings.infer_l3_links:
        infer_l3_links(topo)
    routing_adjacencies(topo, resolver, registry)
    annotate_links(topo)
