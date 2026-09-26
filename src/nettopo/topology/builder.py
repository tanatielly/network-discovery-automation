"""Constrói o grafo (nós + links) a partir dos equipamentos coletados."""

from __future__ import annotations

from collections import defaultdict

from nettopo.config import Settings
from nettopo.models import L2_PROTOCOLS, Device, DiscoveryMeta, Link, Neighbor, Topology
from nettopo.utils import (
    canonical_ifname,
    ifname_key,
    is_default_hostname,
    normalize_mac,
    short_hostname,
    slugify,
)
from nettopo.vendors.registry import VendorRegistry, default_registry


class NeighborResolver:
    """Resolve um vizinho anunciado (LLDP/CDP/OSPF...) para um nó do grafo."""

    def __init__(self, devices: dict[str, Device]):
        self.devices = devices
        self.by_ip: dict[str, str] = {}
        self.by_host: dict[str, str] = {}
        self.by_mac: dict[str, str] = {}
        for d in devices.values():
            self.index(d)

    def index(self, d: Device) -> None:
        for ip in d.ip_addresses():
            self.by_ip.setdefault(ip, d.id)
        host = short_hostname(d.hostname)
        if host:
            self.by_host.setdefault(host, d.id)
        for mac in [normalize_mac(d.chassis_id)] + [normalize_mac(i.mac) for i in d.interfaces]:
            if mac:
                self.by_mac.setdefault(mac, d.id)
        # identificadores alternativos (ex.: router-id OSPF anunciado como chassis)
        for alias in d.extra.get("aliases", []):
            self.by_ip.setdefault(alias, d.id)

    def resolve(self, n: Neighbor) -> str | None:
        if n.remote_mgmt_ip and n.remote_mgmt_ip in self.by_ip:
            return self.by_ip[n.remote_mgmt_ip]
        mac = normalize_mac(n.remote_chassis_id)
        if mac and mac in self.by_mac:
            return self.by_mac[mac]
        if n.remote_chassis_id and n.remote_chassis_id in self.by_ip:  # router-id
            return self.by_ip[n.remote_chassis_id]
        host = short_hostname(n.remote_hostname)
        if host and host in self.by_host:
            return self.by_host[host]
        return None


def _stub_role(n: Neighbor) -> str:
    caps = set(n.remote_capabilities)
    if "wlan" in caps:
        return "ap"
    if "telephone" in caps:
        return "phone"
    if "router" in caps and "bridge" in caps:
        return "l3switch"
    if "router" in caps:
        return "router"
    if "bridge" in caps:
        return "switch"
    if "station" in caps:
        return "server"
    return "unknown"


def create_stub(n: Neighbor, devices: dict[str, Device], resolver: NeighborResolver,
                registry: VendorRegistry) -> str:
    name = n.remote_hostname or n.remote_mgmt_ip or n.remote_chassis_id or "desconhecido"
    base = "stub-" + slugify(short_hostname(name) or name)
    sid, i = base, 2
    while sid in devices:
        sid = f"{base}-{i}"
        i += 1
    profile = registry.match_snmp(None, " ".join(x for x in (n.remote_platform, n.remote_description) if x))
    hostname = n.remote_hostname
    if hostname and "(" in hostname:
        hostname = hostname.split("(")[0]
    stub = Device(
        id=sid, hostname=hostname, mgmt_ip=n.remote_mgmt_ip, reachable=False, stub=True,
        model=n.remote_platform, sys_description=n.remote_description,
        chassis_id=normalize_mac(n.remote_chassis_id), vendor=profile.vendor if profile else None,
        os=profile.os if profile else None, profile=profile.id if profile else None,
        collected_via=[f"visto via {n.protocol}"], role=_stub_role(n),
    )
    stub.extra["capabilities"] = list(n.remote_capabilities)
    if n.remote_asn:
        stub.extra["asn"] = n.remote_asn
    if n.remote_interface:
        stub.upsert_interface(n.remote_interface)
    devices[sid] = stub
    resolver.index(stub)
    return sid


def _link_key(a: str, ai: str | None, b: str, bi: str | None) -> tuple:
    ea, eb = (a, ifname_key(ai)), (b, ifname_key(bi))
    return (ea, eb) if ea <= eb else (eb, ea)


def _orient(ref: Link, lk: Link) -> tuple[str | None, str | None]:
    """Interfaces de ``lk`` na mesma orientação de ``ref``."""
    if lk.source == ref.source:
        return lk.source_interface, lk.target_interface
    return lk.target_interface, lk.source_interface


def _same_link(m: Link, lk: Link) -> bool:
    si, ti = _orient(m, lk)
    ends = [(ifname_key(m.source_interface), ifname_key(si)), (ifname_key(m.target_interface), ifname_key(ti))]
    if any(a and b and a != b for a, b in ends):
        return False
    return any(a and b and a == b for a, b in ends) or all(not a or not b for a, b in ends)


def _absorb(m: Link, lk: Link) -> None:
    si, ti = _orient(m, lk)
    m.source_interface = m.source_interface or si
    m.target_interface = m.target_interface or ti
    for p in lk.protocols:
        if p not in m.protocols:
            m.protocols.append(p)
    m.subnet = m.subnet or lk.subnet


def merge_links(links: list[Link]) -> list[Link]:
    by_pair: dict[frozenset, list[Link]] = defaultdict(list)
    for lk in links:
        by_pair[frozenset((lk.source, lk.target))].append(lk)
    out: list[Link] = []
    for group in by_pair.values():
        # links com interfaces completas primeiro, para servirem de referência
        group.sort(key=lambda x: -(bool(x.source_interface) + bool(x.target_interface)))
        merged: list[Link] = []
        for lk in group:
            for m in merged:
                if m.kind == lk.kind and _same_link(m, lk):
                    _absorb(m, lk)
                    break
            else:
                merged.append(lk)
        out.extend(merged)
    for i, lk in enumerate(out, start=1):
        lk.id = f"L{i}"
    return out


def build_topology(devices: dict[str, Device], settings: Settings | None = None,
                   meta: DiscoveryMeta | None = None, registry: VendorRegistry | None = None) -> Topology:
    from nettopo.topology.enrich import enrich
    from nettopo.topology.roles import classify

    settings = settings or Settings()
    registry = registry or default_registry()
    devices = dict(devices)
    resolver = NeighborResolver(devices)
    raw: dict[tuple, Link] = {}

    # Capacidades anunciadas pelos vizinhos ajudam a classificar o papel dos nós
    for dev in list(devices.values()):
        for n in dev.neighbors:
            if n.protocol not in L2_PROTOCOLS:
                continue
            rid = resolver.resolve(n)
            if rid is None:
                if not (n.remote_hostname or n.remote_mgmt_ip or n.remote_chassis_id):
                    continue
                if is_default_hostname(n.remote_hostname) and not (n.remote_mgmt_ip or n.remote_chassis_id):
                    continue
                rid = create_stub(n, devices, resolver, registry)
            if rid == dev.id:
                continue
            caps = devices[rid].extra.setdefault("capabilities", [])
            for c in n.remote_capabilities:
                if c not in caps:
                    caps.append(c)
            local_if = canonical_ifname(n.local_interface)
            remote_if = canonical_ifname(n.remote_interface)
            if remote_if and devices[rid].stub:
                devices[rid].upsert_interface(remote_if)
            key = _link_key(dev.id, local_if, rid, remote_if)
            if key in raw:
                if n.protocol not in raw[key].protocols:
                    raw[key].protocols.append(n.protocol)
                continue
            raw[key] = Link(source=dev.id, source_interface=local_if, target=rid, target_interface=remote_if,
                            protocols=[n.protocol], kind="physical")

    topo = Topology(meta=meta or DiscoveryMeta(), devices=devices, links=merge_links(list(raw.values())))
    enrich(topo, settings, resolver, registry)
    classify(topo, registry)
    topo.links = merge_links(topo.links)
    _stats(topo)
    return topo


def _stats(topo: Topology) -> None:
    devs = list(topo.devices.values())
    by_vendor: dict[str, int] = defaultdict(int)
    by_role: dict[str, int] = defaultdict(int)
    for d in devs:
        by_vendor[d.vendor or "Desconhecido"] += 1
        by_role[d.role] += 1
    topo.meta.stats = {
        "devices": len(devs),
        "collected": sum(1 for d in devs if not d.stub),
        "stubs": sum(1 for d in devs if d.stub),
        "links": len(topo.links),
        "physical_links": sum(1 for lk in topo.links if lk.kind == "physical"),
        "l3_links": sum(1 for lk in topo.links if lk.kind == "l3"),
        "logical_links": sum(1 for lk in topo.links if lk.kind == "logical"),
        "interfaces": sum(len(d.interfaces) for d in devs if not d.stub),
        "failed_targets": len(topo.meta.failed_targets),
        "by_vendor": dict(sorted(by_vendor.items(), key=lambda kv: -kv[1])),
        "by_role": dict(sorted(by_role.items(), key=lambda kv: -kv[1])),
    }
    if topo.meta.finished_at and topo.meta.started_at:
        topo.meta.stats["duration_s"] = round((topo.meta.finished_at - topo.meta.started_at).total_seconds(), 1)
