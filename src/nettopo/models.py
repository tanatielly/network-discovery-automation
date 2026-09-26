"""Modelo de dados normalizado (independente de vendor)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from nettopo.utils import canonical_ifname, ifname_key, ip_only


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Protocolos de descoberta de vizinhança L2 (geram links físicos)
L2_PROTOCOLS = {"lldp", "cdp", "mndp", "edp", "fdp", "ndp", "lnp", "sonmp", "static"}
# Protocolos de roteamento (geram adjacências lógicas)
ROUTING_PROTOCOLS = {"ospf", "bgp", "isis", "eigrp", "rip"}


class Interface(BaseModel):
    name: str
    description: str | None = None
    mac: str | None = None
    ipv4: list[str] = Field(default_factory=list)  # "10.0.0.1/30" (ou sem prefixo, se desconhecido)
    speed_mbps: int | None = None
    mtu: int | None = None
    admin_up: bool | None = None
    oper_up: bool | None = None
    if_index: int | None = None
    if_type: str | None = None
    mode: str | None = None  # access | trunk | routed
    access_vlan: int | None = None
    trunk_vlans: str | None = None
    parent: str | None = None  # agregação (Port-channel / LAG) a que pertence
    vrf: str | None = None


class Neighbor(BaseModel):
    protocol: str  # lldp, cdp, mndp, edp, fdp, ospf, bgp...
    local_interface: str | None = None
    remote_hostname: str | None = None
    remote_interface: str | None = None
    remote_mgmt_ip: str | None = None
    remote_platform: str | None = None
    remote_description: str | None = None
    remote_chassis_id: str | None = None
    remote_capabilities: list[str] = Field(default_factory=list)
    remote_asn: int | None = None
    state: str | None = None


class Vlan(BaseModel):
    id: int
    name: str | None = None
    interfaces: list[str] = Field(default_factory=list)


class ArpEntry(BaseModel):
    ip: str
    mac: str | None = None
    interface: str | None = None


class Route(BaseModel):
    prefix: str
    next_hop: str | None = None
    interface: str | None = None
    protocol: str | None = None
    vrf: str | None = None


class MacEntry(BaseModel):
    mac: str
    vlan: int | None = None
    interface: str | None = None


class Device(BaseModel):
    id: str = ""
    hostname: str | None = None
    mgmt_ip: str | None = None
    vendor: str | None = None
    os: str | None = None
    profile: str | None = None
    model: str | None = None
    os_version: str | None = None
    serial: str | None = None
    uptime: str | None = None
    chassis_id: str | None = None
    sys_object_id: str | None = None
    sys_description: str | None = None
    location: str | None = None
    contact: str | None = None
    role: str = "unknown"
    tier: str | None = None
    reachable: bool = True
    stub: bool = False  # conhecido apenas pelo que os vizinhos anunciam
    collected_via: list[str] = Field(default_factory=list)
    interfaces: list[Interface] = Field(default_factory=list)
    neighbors: list[Neighbor] = Field(default_factory=list)
    vlans: list[Vlan] = Field(default_factory=list)
    arp: list[ArpEntry] = Field(default_factory=list)
    routes: list[Route] = Field(default_factory=list)
    mac_table: list[MacEntry] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    discovered_from: str | None = None
    depth: int = 0
    extra: dict[str, Any] = Field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.hostname or self.mgmt_ip or self.id

    def ip_addresses(self) -> set[str]:
        ips = {ip_only(a) for i in self.interfaces for a in i.ipv4}
        if self.mgmt_ip:
            ips.add(self.mgmt_ip)
        return ips

    def get_interface(self, name: str | None) -> Interface | None:
        key = ifname_key(name)
        if not key:
            return None
        for itf in self.interfaces:
            if ifname_key(itf.name) == key:
                return itf
        return None

    def upsert_interface(self, name: str) -> Interface:
        itf = self.get_interface(name)
        if itf is None:
            itf = Interface(name=canonical_ifname(name) or name)
            self.interfaces.append(itf)
        return itf


class Link(BaseModel):
    id: str = ""
    source: str
    source_interface: str | None = None
    target: str
    target_interface: str | None = None
    protocols: list[str] = Field(default_factory=list)
    kind: Literal["physical", "l3", "logical"] = "physical"
    subnet: str | None = None
    speed_mbps: int | None = None
    lag: str | None = None


class DiscoveryMeta(BaseModel):
    name: str | None = None
    seeds: list[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    tool_version: str = ""
    max_depth: int | None = None
    stats: dict[str, Any] = Field(default_factory=dict)
    failed_targets: dict[str, str] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)  # configuração sem segredos


class Topology(BaseModel):
    meta: DiscoveryMeta = Field(default_factory=DiscoveryMeta)
    devices: dict[str, Device] = Field(default_factory=dict)
    links: list[Link] = Field(default_factory=list)

    def links_of(self, device_id: str) -> list[Link]:
        return [lk for lk in self.links if device_id in (lk.source, lk.target)]

    def to_networkx(self):  # noqa: ANN201 - networkx é importado sob demanda
        import networkx as nx

        g = nx.MultiGraph()
        for d in self.devices.values():
            g.add_node(d.id, role=d.role, tier=d.tier, stub=d.stub)
        for lk in self.links:
            g.add_edge(lk.source, lk.target, key=lk.id, kind=lk.kind)
        return g

    def save(self, path: str) -> None:
        from pathlib import Path

        Path(path).write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str) -> Topology:
        from pathlib import Path

        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
