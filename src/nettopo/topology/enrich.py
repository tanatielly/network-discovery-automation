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


def _skip_interface(name: str, settings: Settings | None) -> bool:
    from nettopo.topology.builder import is_mgmt_interface

    low = name.lower()
    return low.startswith(("lo", "loopback", "vlanif", "null", "tunnel")) or is_mgmt_interface(
        name, settings.ignore_interfaces if settings else None)


def infer_l3_links(topo: Topology, settings: Settings | None = None) -> None:
    """Sub-redes /30 e /31 com exatamente dois equipamentos e dois IPs distintos viram links L3.

    Ignora interfaces de gerência/loopback e endereços repetidos (ex.: rede interna NAT de VMs, VRRP),
    que não indicam um enlace ponto a ponto.
    """
    nets: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for d in sorted(topo.devices.values(), key=lambda x: x.id):
        if d.stub:
            continue
        for itf in d.interfaces:
            if _skip_interface(itf.name, settings) or itf.oper_up is False:  # enlace caído não é link
                continue
            for cidr in itf.ipv4:
                net = network_of(cidr)
                if net is None or net.prefixlen not in (30, 31):
                    continue
                ip = ipaddress.IPv4Address(cidr.split("/")[0])
                if net.prefixlen == 30 and ip in (net.network_address, net.broadcast_address):
                    continue
                nets[str(net)].append((d.id, itf.name, str(ip)))
    for subnet, members in sorted(nets.items()):
        if len({m[0] for m in members}) != 2 or len({m[2] for m in members}) != 2 or len(members) != 2:
            continue
        (a, ai, _), (b, bi, _) = members
        matched = False
        for lk in _pair_links(topo, a, b):
            ends = {(lk.source, ifname_key(lk.source_interface)), (lk.target, ifname_key(lk.target_interface))}
            if (a, ifname_key(ai)) in ends or (b, ifname_key(bi)) in ends:
                lk.subnet = lk.subnet or subnet
                matched = True
                break
        if not matched:
            topo.links.append(Link(source=a, source_interface=ai, target=b, target_interface=bi,
                                   protocols=["subnet"], kind="l3", subnet=subnet))


def _local_interface_for(dev: Device, ip: str | None) -> str | None:
    if not ip:
        return None
    try:
        addr = ipaddress.IPv4Address(ip)
    except ValueError:
        return None
    for itf in dev.interfaces:
        for cidr in itf.ipv4:
            net = network_of(cidr)
            if net is not None and net.prefixlen < 32 and addr in net:
                return itf.name
    return None


def _peer_on_link(topo: Topology, dev_id: str, local_if: str | None) -> str | None:
    """Equipamento do outro lado do link físico que sai por ``local_if``."""
    if not local_if:
        return None
    key = ifname_key(local_if)
    for lk in topo.links:
        if lk.kind != "physical":
            continue
        if lk.source == dev_id and ifname_key(lk.source_interface) == key:
            return lk.target
        if lk.target == dev_id and ifname_key(lk.target_interface) == key:
            return lk.source
    return None


def routing_adjacencies(topo: Topology, resolver: NeighborResolver, registry: VendorRegistry) -> None:
    from nettopo.topology.builder import create_stub

    for dev in sorted(list(topo.devices.values()), key=lambda x: x.id):
        for n in dev.neighbors:
            if n.protocol not in ROUTING_PROTOCOLS:
                continue
            local_if = n.local_interface or _local_interface_for(dev, n.remote_mgmt_ip)
            rid = resolver.resolve(n)
            if rid is None:
                # O par está do outro lado de um link físico já conhecido? (ex.: PE da operadora visto
                # por LLDP com o IP de gerência e por BGP com o IP do enlace)
                rid = _peer_on_link(topo, dev.id, local_if)
                if rid is not None and n.remote_mgmt_ip:
                    peer = topo.devices[rid]
                    aliases = peer.extra.setdefault("aliases", [])
                    if n.remote_mgmt_ip not in aliases:
                        aliases.append(n.remote_mgmt_ip)
                    if n.remote_asn and not peer.extra.get("asn"):
                        peer.extra["asn"] = n.remote_asn
                    resolver.index(peer)
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
        infer_l3_links(topo, settings)
    routing_adjacencies(topo, resolver, registry)
    annotate_links(topo)
