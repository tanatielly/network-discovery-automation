"""Coletor simulado: responde como uma rede real a partir de um laboratório em YAML.

Usado por ``nettopo demo``, pela UI (botão "Demo") e pelos testes do motor de
descoberta — exercita exatamente o mesmo pipeline (BFS, dedup, grafo, saídas).
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
from pathlib import Path
from typing import Any

import yaml

from nettopo.config import Scope, Settings
from nettopo.models import ArpEntry, Device, Interface, Neighbor, Route, Vlan
from nettopo.utils import canonical_ifname, ip_only, network_of
from nettopo.vendors.registry import VendorRegistry, default_registry

DEMO_LAB = Path(__file__).with_name("demo_lab.yaml")
DEMO_VLANS = [(1, "default"), (10, "USUARIOS"), (20, "VOZ"), (30, "WIFI"), (99, "GERENCIA")]


def _mac(seed: str) -> str:
    h = hashlib.md5(seed.encode()).hexdigest()[:10]
    return "02:" + ":".join(h[i : i + 2] for i in range(0, 10, 2))


class SimulatedCollector:
    def __init__(self, lab: dict[str, Any] | str | Path | None = None, registry: VendorRegistry | None = None,
                 delay: float = 0.0):
        if lab is None:
            lab = DEMO_LAB
        if isinstance(lab, (str, Path)):
            lab = yaml.safe_load(Path(lab).read_text(encoding="utf-8"))
        self.lab: dict[str, Any] = lab
        self.registry = registry or default_registry()
        self.delay = delay
        self.devices: dict[str, Device] = {}
        self.reachable: dict[str, bool] = {}
        self._build()

    @property
    def name(self) -> str:
        return str(self.lab.get("name") or "Demo")

    def seeds(self) -> list[str]:
        first = next(iter(self.devices.values()))
        return [first.mgmt_ip or ""]

    # ------------------------------------------------------------------ construção
    def _build(self) -> None:
        specs: dict[str, dict[str, Any]] = self.lab.get("devices", {})
        for host, spec in specs.items():
            profile = self.registry.get(spec.get("profile"))
            dev = Device(
                hostname=host, mgmt_ip=spec.get("mgmt_ip"), vendor=profile.vendor if profile else None,
                os=profile.os if profile else None, profile=profile.id if profile else None,
                model=spec.get("model"), os_version=str(spec["version"]) if spec.get("version") else None,
                serial=str(spec["serial"]) if spec.get("serial") else None, chassis_id=_mac(host),
                sys_description=spec.get("description") or (
                    f"{profile.vendor} {profile.os} {spec.get('version', '')}".strip() if profile else None),
                uptime="42d 7h 13m", collected_via=["simulado"],
            )
            dev.extra["caps"] = spec.get("caps") or self._default_caps(profile.category if profile else "")
            for ifname, cidr in (spec.get("interfaces") or {}).items():
                dev.upsert_interface(ifname).ipv4.append(cidr)
            for ifname, lag in (spec.get("lags") or {}).items():
                itf = dev.upsert_interface(ifname)
                itf.parent = canonical_ifname(lag)
                dev.upsert_interface(lag).if_type = "lag"
            if dev.mgmt_ip and not any(ip_only(a) == dev.mgmt_ip for i in dev.interfaces for a in i.ipv4):
                dev.interfaces.append(Interface(name="mgmt0", ipv4=[f"{dev.mgmt_ip}/24"], oper_up=True,
                                                admin_up=True, speed_mbps=1000, description="Gerência"))
            self.devices[host] = dev
            self.reachable[host] = spec.get("reachable", True)

        for a_end, b_end, protos, speed in self.lab.get("links", []):
            a_host, a_if = a_end.split(":", 1)
            b_host, b_if = b_end.split(":", 1)
            for (h1, i1), (h2, i2) in (((a_host, a_if), (b_host, b_if)), ((b_host, b_if), (a_host, a_if))):
                d1, d2 = self.devices[h1], self.devices[h2]
                itf = d1.upsert_interface(i1)
                itf.speed_mbps, itf.oper_up, itf.admin_up, itf.mac = speed, True, True, _mac(h1 + i1)
                itf.description = itf.description or f"Uplink {h2} {i2}"
                for p in protos:
                    d1.neighbors.append(Neighbor(
                        protocol=p, local_interface=canonical_ifname(i1), remote_hostname=h2, remote_interface=i2,
                        remote_mgmt_ip=d2.mgmt_ip, remote_platform=d2.model,
                        remote_description=d2.sys_description, remote_chassis_id=d2.chassis_id,
                        remote_capabilities=list(d2.extra["caps"]),
                    ))

        for r in self.lab.get("routing", []):
            for side, other in (("a", "b"), ("b", "a")):
                d = self.devices[r[side]]
                d.neighbors.append(Neighbor(protocol=r["protocol"], local_interface=canonical_ifname(r[f"{side}_if"]),
                                            remote_mgmt_ip=r[f"{other}_ip"], state="full",
                                            remote_chassis_id=self.devices[r[other]].mgmt_ip))
        for host, spec in specs.items():
            d = self.devices[host]
            for peer in spec.get("bgp") or []:
                d.neighbors.append(Neighbor(protocol="bgp", remote_mgmt_ip=peer["peer"], remote_asn=peer["asn"],
                                            state="Established"))
            self._tables(d)

    @staticmethod
    def _default_caps(category: str) -> list[str]:
        return {"router": ["router"], "firewall": ["router"], "switch": ["bridge"], "server": ["station"]}.get(
            category, ["bridge", "router"])

    def _tables(self, d: Device) -> None:
        """Gera ARP, rotas conectadas e VLANs coerentes com as interfaces."""
        all_ips = {ip_only(a): (h, i.name) for h, dd in self.devices.items() for i in dd.interfaces for a in i.ipv4}
        for itf in d.interfaces:
            for cidr in itf.ipv4:
                net = network_of(cidr)
                if net is None:
                    continue
                d.routes.append(Route(prefix=str(net), interface=itf.name, protocol="connected"))
                for ip, (host, _) in all_ips.items():
                    if host != d.hostname and ipaddress.IPv4Address(ip) in net:
                        d.arp.append(ArpEntry(ip=ip, mac=self.devices[host].chassis_id, interface=itf.name))
        if d.profile and self.registry.get(d.profile) and self.registry.get(d.profile).category in ("router", "firewall"):
            d.routes.append(Route(prefix="0.0.0.0/0", next_hop=next((a.ip for a in d.arp), None), protocol="static"))
        if "bridge" in d.extra.get("caps", []) and d.profile:
            d.vlans = [Vlan(id=v, name=n) for v, n in DEMO_VLANS]

    # ------------------------------------------------------------------ DeviceCollector
    async def collect(self, target: str) -> Device:
        if self.delay:
            await asyncio.sleep(self.delay)
        for host, dev in self.devices.items():
            if target == dev.mgmt_ip or target in dev.ip_addresses():
                if not self.reachable[host]:
                    break
                out = dev.model_copy(deep=True)
                out.extra.pop("caps", None)
                return out
        return Device(mgmt_ip=target, reachable=False, errors=["simulado: sem resposta (timeout)"])

    async def close(self) -> None:
        return None


def demo_settings(collector: SimulatedCollector, **overrides: Any) -> Settings:
    data: dict[str, Any] = {"name": collector.name, "seeds": collector.seeds(), "concurrency": 8,
                            "scope": Scope(include=["10.0.0.0/8", "172.16.0.0/12"])}
    data.update({k: v for k, v in overrides.items() if v is not None})
    return Settings.model_validate(data)
