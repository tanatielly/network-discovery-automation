"""Classificação de papel (router, switch, firewall...) e camada hierárquica (core, distribuição, acesso)."""

from __future__ import annotations

import re
from collections import defaultdict, deque

from nettopo.models import Device, Topology
from nettopo.vendors.registry import VendorRegistry

ROLES = ["external", "firewall", "router", "l3switch", "switch", "wireless_controller", "ap", "server", "phone",
         "unknown"]
TIERS = ["external", "edge", "security", "core", "distribution", "access", "endpoint"]

_RX = {
    "firewall": r"fortigate|firewall|\basa\s?\d|adaptive security|palo ?alto|\bpa-\d|\bsrx\d|check ?point|sonicwall|"
                r"\bfw\b|^fw[-_]|[-_]fw[-_\d]|firepower|pfsense|opnsense",
    "wireless_controller": r"wireless lan controller|\bwlc\b|air-ct\d|mobility controller|c9800",
    "ap": r"\bap\b|access ?point|aironet|air-ap|air-cap|\buap\b|\bu6\b|unifi ap|^ap[-_\d]|[-_]ap\d|cambium|ruckus r\d",
    "phone": r"ip phone|polycom|yealink|grandstream|\bsep[0-9a-f]{12}|cisco cp-\d|avaya",
    "server": r"linux|ubuntu|debian|centos|red hat|windows|vmware|esxi|proxmox|hyper-v|\bserver\b|^srv[-_\d]",
    "router": r"\brouter\b|\bisr\d|\basr\d|\bmx\d{2,}|\bccr\d|\bne\d{2}|\brtr\b|^rtr[-_]|[-_]rtr[-_\d]|7750|"
              r"\bsr-\d|edge ?router|vyos|csr1000|\bc8\d{3}|ios.xr|routeros|\bptx\d|\bacx\d",
    "switch": r"switch|catalyst|\bc9[23]\d{2}|ws-c|nexus|\bn\dk|dcs-\d|\bex\d{4}|\bqfx|\bs\d{4}|\bce\d{4}|procurve|"
              r"aruba ?\d{4}|aos-cx|\bcrs\d|\bicx\d|\bx\d{3}|\bdm\d{4}|dmos|\bsw\b|^sw[-_]|[-_]sw[-_\d]|os10|"
              r"powerswitch|jetstream|edgeswitch|usw|comware|\bvsp",
}


def _text(d: Device) -> str:
    return " ".join(x for x in (d.model, d.sys_description, d.hostname, d.os, d.vendor) if x).lower()


def base_role(d: Device, registry: VendorRegistry | None = None) -> str:
    if d.role == "external":
        return "external"
    profile = registry.get(d.profile) if registry else None
    category = profile.category if profile else None
    text = _text(d)
    caps = set(d.extra.get("capabilities", []))
    has_routes = any(r.protocol in ("ospf", "bgp", "isis", "eigrp") for r in d.routes) or any(
        n.protocol in ("ospf", "bgp", "isis") for n in d.neighbors)

    if category == "firewall" or re.search(_RX["firewall"], text):
        return "firewall"
    if re.search(_RX["wireless_controller"], text):
        return "wireless_controller"
    if "wlan" in caps or re.search(_RX["ap"], text):
        return "ap"
    if "telephone" in caps or re.search(_RX["phone"], text):
        return "phone"
    # Decide switch x roteador: modelo/hostname > descrição > categoria do perfil > capacidades LLDP
    kind = None
    for src in (" ".join(x for x in (d.model, d.hostname) if x).lower(), (d.sys_description or "").lower()):
        sw, rt = bool(re.search(_RX["switch"], src)), bool(re.search(_RX["router"], src))
        if sw != rt:
            kind = "switch" if sw else "router"
            break
    if kind is None and category in ("switch", "router"):
        kind = category
    if kind is None and caps & {"bridge", "router"}:
        kind = "switch" if "bridge" in caps else "router"
    if kind == "switch":
        routed_ifs = sum(1 for i in d.interfaces if i.ipv4 and not i.name.lower().startswith(
            ("vlan", "loopback", "mgmt", "management")))
        if "router" in caps or has_routes or routed_ifs >= 2:
            return "l3switch"
        return "switch"
    if kind == "router":
        return "router"
    if category == "server" or "station" in caps or re.search(_RX["server"], text):
        return "server"
    if d.role not in ("", "unknown"):
        return d.role
    return "unknown"


def assign_tiers(topo: Topology) -> None:
    adj: dict[str, set[str]] = defaultdict(set)
    for lk in topo.links:
        adj[lk.source].add(lk.target)
        adj[lk.target].add(lk.source)
    devs = topo.devices
    switching = {i for i, d in devs.items() if d.role in ("switch", "l3switch")}

    for d in devs.values():
        if d.role == "external":
            d.tier = "external"
        elif d.role == "router":
            d.tier = "edge"
        elif d.role == "firewall":
            d.tier = "security"
        elif d.role in ("ap", "phone", "server", "unknown", "wireless_controller"):
            d.tier = "endpoint"

    if not switching:
        return
    # Núcleo: switches adjacentes a roteadores/firewalls; senão, os de maior grau entre switches
    core = {s for s in switching if any(devs[n].role in ("router", "firewall") for n in adj[s])
            and adj[s] & switching}
    if not core:
        deg = {s: len(adj[s] & switching) for s in switching}
        top = max(deg.values())
        core = {s for s, v in deg.items() if v == top} if top > 0 else set()
    level: dict[str, int] = {s: 0 for s in core}
    q = deque(core)
    while q:
        cur = q.popleft()
        for n in adj[cur] & switching:
            if n not in level:
                level[n] = level[cur] + 1
                q.append(n)
    for s in switching:
        lv = level.get(s)
        if lv is None:
            devs[s].tier = "access"
        elif lv == 0:
            devs[s].tier = "core"
        else:
            downstream = [n for n in adj[s] & switching if level.get(n, 99) > lv]
            devs[s].tier = "distribution" if downstream else "access"


def _external_stubs(topo: Topology) -> None:
    """Roteadores não coletados pendurados na borda (ex.: PE da operadora) vão para a camada externa."""
    adj: dict[str, set[str]] = defaultdict(set)
    for lk in topo.links:
        adj[lk.source].add(lk.target)
        adj[lk.target].add(lk.source)
    for d in topo.devices.values():
        if d.stub and d.role == "router" and len(adj[d.id]) == 1:
            (peer,) = adj[d.id]
            if topo.devices[peer].role in ("router", "firewall"):
                d.tier = "external"


def classify(topo: Topology, registry: VendorRegistry | None = None) -> None:
    for d in topo.devices.values():
        d.role = base_role(d, registry)
    assign_tiers(topo)
    _external_stubs(topo)
