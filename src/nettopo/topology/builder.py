"""Constrói o grafo (nós + links) a partir dos equipamentos coletados."""

from __future__ import annotations

import re
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


# --------------------------------------------------------------------------- portas e links

def resolve_port(device: Device, announced: str | None) -> str | None:
    """Converte a porta anunciada por um vizinho no nome real da interface do ``device``.

    Vizinhos anunciam o port-id de formas diferentes: nome (``ether4``), descrição configurada
    (``to edge-mk1 ether4``) ou MAC. Só devolve nome se o equipamento foi coletado e a interface existe.
    """
    if not announced or device.stub:
        return None
    key = ifname_key(announced)
    for itf in device.interfaces:
        if ifname_key(itf.name) == key:
            return itf.name
    text = announced.strip().lower()
    for itf in device.interfaces:
        if itf.description and itf.description.strip().lower() == text:
            return itf.name
    mac = normalize_mac(announced)
    if mac:
        hits = [itf.name for itf in device.interfaces if normalize_mac(itf.mac) == mac]
        if len(hits) == 1:
            return hits[0]
    return None


DEFAULT_MGMT_INTERFACES = r"^(mgmt|management|fxp0|me0|em0$|ma\d|bmc|ipmi|oob)"


def is_mgmt_interface(name: str | None, pattern: str | None = None) -> bool:
    """Interface de gerência fora de banda: LLDP recebido nela não descreve a rede de dados."""
    if not name:
        return False
    return bool(re.search(pattern or DEFAULT_MGMT_INTERFACES, name.strip(), re.IGNORECASE))


class _Half:
    """Uma observação de vizinhança vista de um lado (o lado local é autoritativo)."""

    __slots__ = ("a", "a_if", "b", "b_if", "b_verified", "protocol")

    def __init__(self, a: str, a_if: str | None, b: str, b_if: str | None, b_verified: bool, protocol: str):
        self.a, self.a_if, self.b, self.b_if = a, a_if, b, b_if
        self.b_verified, self.protocol = b_verified, protocol


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[tuple, tuple] = {}

    def find(self, x: tuple) -> tuple:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, x: tuple, y: tuple) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self.parent[max(rx, ry)] = min(rx, ry)


def links_from_halves(halves: list[_Half]) -> list[Link]:
    """Une as observações dos dois lados de cada cabo em um único link.

    Cada ponta é um nó ``(equipamento, interface)`` e cada observação liga as duas pontas. Uma porta
    anunciada que não foi verificada no equipamento remoto ganha uma chave própria da observação, então
    só se junta a outro link pelo lado verificado. Assim um cabo visto pelos dois lados vira exatamente
    um link, mesmo quando um deles anuncia a porta pela descrição ou pelo MAC.
    """
    uf = _UnionFind()
    ends: list[tuple] = []
    for i, h in enumerate(halves):
        ea = (h.a, ifname_key(h.a_if) or f"?{i}")
        eb = (h.b, ifname_key(h.b_if) if h.b_verified and h.b_if else f"?{i}")
        uf.union(ea, eb)
        ends.append(ea)
    groups: dict[tuple, list[int]] = defaultdict(list)
    for i, ea in enumerate(ends):
        groups[uf.find(ea)].append(i)

    links: list[Link] = []
    for idxs in groups.values():
        obs = [halves[i] for i in idxs]
        members = sorted({h.a for h in obs} | {h.b for h in obs})
        if len(members) != 2:  # segmento compartilhado (hub, mídia comum): um link por observação
            for h in obs:
                links.append(Link(source=h.a, source_interface=h.a_if, target=h.b,
                                  target_interface=h.b_if, protocols=[h.protocol], kind="physical"))
            continue
        x, y = members
        names: dict[str, str | None] = {x: None, y: None}
        for h in sorted(obs, key=lambda o: (o.a, o.a_if or "")):  # nome dado pelo próprio equipamento
            names[h.a] = names[h.a] or h.a_if
        for h in obs:
            if names[h.b] is None and h.b_if:
                names[h.b] = h.b_if
        links.append(Link(source=x, source_interface=names[x], target=y, target_interface=names[y],
                          protocols=sorted({h.protocol for h in obs}), kind="physical"))
    return links


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
    """Funde links equivalentes (mesmo par e mesmas portas) e numera de forma determinística."""
    by_pair: dict[frozenset, list[Link]] = defaultdict(list)
    for lk in links:
        by_pair[frozenset((lk.source, lk.target))].append(lk)
    out: list[Link] = []
    for pair in sorted(by_pair, key=lambda p: sorted(p)):
        group = by_pair[pair]
        group.sort(key=lambda x: (-(bool(x.source_interface) + bool(x.target_interface)), x.kind,
                                  x.source, x.source_interface or "", x.target_interface or ""))
        merged: list[Link] = []
        for lk in group:
            for m in merged:
                if m.kind == lk.kind and _same_link(m, lk):
                    _absorb(m, lk)
                    break
            else:
                merged.append(lk)
        out.extend(merged)
    for lk in out:  # orientação canônica: menor id na origem
        if lk.source > lk.target:
            lk.source, lk.target = lk.target, lk.source
            lk.source_interface, lk.target_interface = lk.target_interface, lk.source_interface
        lk.protocols = sorted(set(lk.protocols))
    kind_order = {"physical": 0, "l3": 1, "logical": 2}
    out.sort(key=lambda lk: (kind_order.get(lk.kind, 9), lk.source, ifname_key(lk.source_interface),
                             lk.target, ifname_key(lk.target_interface)))
    for i, lk in enumerate(out, start=1):
        lk.id = f"L{i}"
    return out


def build_topology(devices: dict[str, Device], settings: Settings | None = None,
                   meta: DiscoveryMeta | None = None, registry: VendorRegistry | None = None) -> Topology:
    from nettopo.topology.enrich import enrich
    from nettopo.topology.roles import classify

    settings = settings or Settings()
    registry = registry or default_registry()
    meta = meta or DiscoveryMeta()
    devices = {k: devices[k] for k in sorted(devices)}
    resolver = NeighborResolver(devices)
    halves: list[_Half] = []
    ignored = 0

    for dev in [devices[k] for k in sorted(devices)]:
        for n in dev.neighbors:
            if n.protocol not in L2_PROTOCOLS:
                continue
            local_if = canonical_ifname(n.local_interface)
            if is_mgmt_interface(local_if, settings.ignore_interfaces):
                ignored += 1
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
            remote = devices[rid]
            if remote.stub:
                if n.remote_mgmt_ip and n.remote_mgmt_ip in meta.failed_targets:
                    remote.extra.setdefault("motivo", meta.failed_targets[n.remote_mgmt_ip])
                elif n.remote_mgmt_ip and not settings.scope.allows_ip(n.remote_mgmt_ip):
                    remote.extra.setdefault("motivo", f"IP anunciado {n.remote_mgmt_ip} fora do escopo")
                elif not n.remote_mgmt_ip:
                    remote.extra.setdefault("motivo", "vizinho não anunciou IP de gerência")
            caps = remote.extra.setdefault("capabilities", [])
            for c in n.remote_capabilities:
                if c not in caps:
                    caps.append(c)
            announced = canonical_ifname(n.remote_interface)
            resolved = resolve_port(remote, n.remote_interface)
            if remote.stub and announced:
                remote.upsert_interface(announced)
            halves.append(_Half(dev.id, local_if, rid, resolved or announced, bool(resolved) or remote.stub,
                                n.protocol))

    topo = Topology(meta=meta, devices=devices, links=merge_links(links_from_halves(halves)))
    enrich(topo, settings, resolver, registry)
    classify(topo, registry)
    topo.links = merge_links(topo.links)
    _stats(topo)
    topo.meta.stats["ignored_mgmt_neighbors"] = ignored
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
