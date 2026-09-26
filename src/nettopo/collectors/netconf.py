"""Coletor NETCONF (ncclient): modelos OpenConfig + RPCs nativos do Junos."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from nettopo.collectors.base import MethodResult
from nettopo.config import Credential, Settings
from nettopo.models import ArpEntry, Device, Neighbor
from nettopo.utils import canonical_ifname, normalize_mac, parse_ipv4, to_int, truthy_status
from nettopo.vendors.registry import VendorProfile, VendorRegistry

log = logging.getLogger(__name__)

OC_LLDP = '<lldp xmlns="http://openconfig.net/yang/lldp"/>'
OC_INTERFACES = '<interfaces xmlns="http://openconfig.net/yang/interfaces"/>'
OC_SYSTEM = '<system xmlns="http://openconfig.net/yang/system"><state/><config/></system>'


# --------------------------------------------------------------------------- helpers XML

def _root(xml: Any) -> Any:
    from lxml import etree

    if isinstance(xml, (str, bytes)):
        data = xml.encode() if isinstance(xml, str) else xml
        return etree.fromstring(data, parser=etree.XMLParser(recover=True, huge_tree=True))
    return xml


def _children(el: Any, name: str) -> list[Any]:
    return [c for c in el if isinstance(c.tag, str) and c.tag.split("}")[-1] == name]


def _all(el: Any, name: str) -> list[Any]:
    return el.xpath(f".//*[local-name()='{name}']")


def _path(el: Any, *names: str) -> Any:
    cur = el
    for n in names:
        found = _children(cur, n)
        if not found:
            return None
        cur = found[0]
    return cur


def _text(el: Any, *paths: tuple[str, ...] | str) -> str | None:
    for p in paths:
        names = (p,) if isinstance(p, str) else p
        node = _path(el, *names)
        if node is not None and node.text and node.text.strip():
            return node.text.strip()
    return None


def _oc_speed(value: str | None) -> int | None:
    """``openconfig-if-ethernet:SPEED_10GB`` -> 10000."""
    if not value:
        return None
    tail = value.split(":")[-1].replace("SPEED_", "")
    num = to_int(tail)
    if num is None:
        return None
    return num * 1000 if tail.endswith("GB") else num


# --------------------------------------------------------------------------- parsers

def parse_openconfig_system(xml: Any) -> dict[str, str | None]:
    root = _root(xml)
    for sys in _all(root, "system"):
        host = _text(sys, ("state", "hostname"), ("config", "hostname"))
        if host:
            return {"hostname": host, "version": _text(sys, ("state", "software-version"))}
    return {}


def parse_openconfig_lldp(xml: Any) -> list[Neighbor]:
    root = _root(xml)
    out: list[Neighbor] = []
    for itf in _all(root, "interface"):
        local = _text(itf, "name", ("state", "name"))
        neighbors = _path(itf, "neighbors")
        if neighbors is None:
            continue
        for nb in _children(neighbors, "neighbor"):
            st = _path(nb, "state")
            st = nb if st is None else st
            caps = [(_text(c, "name", ("state", "name")) or "").split(":")[-1].lower()
                    for c in _all(nb, "capability")
                    if (_text(c, ("state", "enabled")) or "true") == "true"]
            chassis = _text(st, "chassis-id")
            out.append(Neighbor(
                protocol="lldp",
                local_interface=canonical_ifname(local),
                remote_hostname=_text(st, "system-name"),
                remote_interface=_text(st, "port-id") if not normalize_mac(_text(st, "port-id"))
                else (_text(st, "port-description") or _text(st, "port-id")),
                remote_mgmt_ip=parse_ipv4(_text(st, "management-address")),
                remote_description=_text(st, "system-description"),
                remote_platform=(_text(st, "system-description") or "")[:120] or None,
                remote_chassis_id=normalize_mac(chassis) or chassis,
                remote_capabilities=[c.replace("mac_bridge", "bridge").replace("wlan_access_point", "wlan")
                                     for c in caps if c],
            ))
    return out


def parse_openconfig_interfaces(xml: Any, device: Device) -> None:
    root = _root(xml)
    container = _all(root, "interfaces")
    if not container:
        return
    for itf in _children(container[0], "interface"):
        name = _text(itf, "name")
        if not name:
            continue
        st = _path(itf, "state")
        obj = device.upsert_interface(name)
        if st is not None:
            obj.description = obj.description or _text(st, "description")
            obj.mtu = obj.mtu or to_int(_text(st, "mtu"))
            obj.admin_up = truthy_status(_text(st, "admin-status")) if obj.admin_up is None else obj.admin_up
            obj.oper_up = truthy_status(_text(st, "oper-status")) if obj.oper_up is None else obj.oper_up
            obj.if_index = obj.if_index or to_int(_text(st, "ifindex"))
        eth = _path(itf, "ethernet", "state")
        if eth is not None:
            obj.mac = obj.mac or normalize_mac(_text(eth, "mac-address") or _text(eth, "hw-mac-address"))
            obj.speed_mbps = obj.speed_mbps or _oc_speed(_text(eth, "port-speed"))
        for addr in _all(itf, "address"):
            ip = _text(addr, "ip", ("state", "ip"), ("config", "ip"))
            pfx = _text(addr, ("state", "prefix-length"), ("config", "prefix-length"))
            if parse_ipv4(ip):
                cidr = f"{ip}/{pfx}" if pfx else ip
                if cidr not in obj.ipv4:
                    obj.ipv4.append(cidr)


def parse_junos_lldp(xml: Any) -> list[Neighbor]:
    root = _root(xml)
    out = []
    for nb in _all(root, "lldp-neighbor-information"):
        port = _text(nb, "lldp-remote-port-id")
        desc = _text(nb, "lldp-remote-port-description")
        chassis = _text(nb, "lldp-remote-chassis-id")
        out.append(Neighbor(
            protocol="lldp",
            local_interface=canonical_ifname(_text(nb, "lldp-local-port-id", "lldp-local-interface")),
            remote_hostname=_text(nb, "lldp-remote-system-name"),
            remote_interface=desc if (port and normalize_mac(port) and desc) else (port or desc),
            remote_mgmt_ip=parse_ipv4(_text(nb, "lldp-remote-management-address")),
            remote_chassis_id=normalize_mac(chassis) or chassis,
            remote_description=_text(nb, "lldp-system-description"),
        ))
    return out


def parse_junos_software(xml: Any) -> dict[str, str | None]:
    root = _root(xml)
    info: dict[str, str | None] = {}
    for si in _all(root, "software-information"):
        info["hostname"] = info.get("hostname") or _text(si, "host-name")
        info["model"] = info.get("model") or _text(si, "product-model")
        info["version"] = info.get("version") or _text(si, "junos-version")
        if not info["version"]:
            for pkg in _children(si, "package-information"):
                comment = _text(pkg, "comment") or ""
                if "[" in comment:
                    info["version"] = comment.split("[")[1].split("]")[0]
                    break
    return info


def parse_junos_interfaces(xml: Any, device: Device) -> None:
    root = _root(xml)
    for phy in _all(root, "physical-interface"):
        name = _text(phy, "name")
        if not name:
            continue
        itf = device.upsert_interface(name)
        itf.admin_up = truthy_status(_text(phy, "admin-status"))
        itf.oper_up = truthy_status(_text(phy, "oper-status"))
        itf.description = _text(phy, "description")
        itf.mac = normalize_mac(_text(phy, "current-physical-address", "hardware-physical-address"))
        for log_if in _children(phy, "logical-interface"):
            for af in _all(log_if, "interface-address"):
                local = _text(af, "ifa-local")
                dest = _text(af, "ifa-destination") or ""
                pfx = dest.split("/")[1] if "/" in dest else None
                if parse_ipv4(local):
                    cidr = f"{local}/{pfx}" if pfx else local
                    if cidr not in itf.ipv4:
                        itf.ipv4.append(cidr)


def parse_junos_arp(xml: Any) -> list[ArpEntry]:
    root = _root(xml)
    out = []
    for e in _all(root, "arp-table-entry"):
        ip = parse_ipv4(_text(e, "ip-address"))
        if ip:
            out.append(ArpEntry(ip=ip, mac=normalize_mac(_text(e, "mac-address")),
                                interface=_text(e, "interface-name")))
    return out


# --------------------------------------------------------------------------- coletor

class NetconfCollector:
    name = "netconf"

    def __init__(self, settings: Settings, registry: VendorRegistry):
        self.settings = settings
        self.registry = registry

    async def collect(self, target: str, profile: VendorProfile | None,
                      credentials: list[Credential]) -> MethodResult:
        res = MethodResult(method=self.name)
        if profile is not None and not profile.netconf:
            res.errors.append("netconf: perfil sem suporte")
            return res
        if not credentials:
            res.errors.append("netconf: nenhuma credencial")
            return res
        return await asyncio.to_thread(self._collect_sync, target, profile, credentials, res)

    def _collect_sync(self, target: str, profile: VendorProfile | None, credentials: list[Credential],
                      res: MethodResult) -> MethodResult:
        try:
            from ncclient import manager
        except ImportError:  # pragma: no cover
            res.errors.append("netconf: ncclient não instalado")
            return res
        handler = (profile.netconf if profile else None) or "default"
        for cred in credentials:
            try:
                with manager.connect(host=target, port=cred.port or 830, username=cred.username,
                                     password=cred.secret("password"), hostkey_verify=False,
                                     allow_agent=False, look_for_keys=False, timeout=self.settings.timeout,
                                     device_params={"name": handler}) as m:
                    dev = Device(mgmt_ip=target, collected_via=["netconf"])
                    if profile:
                        dev.vendor, dev.os, dev.profile = profile.vendor, profile.os, profile.id
                    if handler == "junos":
                        self._junos(m, dev)
                    else:
                        self._openconfig(m, dev)
                    res.device = dev
                    res.credential = cred
                    return res
            except Exception as exc:
                res.errors.append(f"netconf[{cred.display}]: {type(exc).__name__}: {str(exc)[:160]}")
                if "timed out" in str(exc).lower() or "refused" in str(exc).lower():
                    break
        return res

    def _get(self, m: Any, subtree: str) -> str | None:
        try:
            return m.get(filter=("subtree", subtree)).data_xml
        except Exception as exc:
            log.debug("netconf get %s: %s", subtree[:40], exc)
            return None

    def _openconfig(self, m: Any, dev: Device) -> None:
        xml = self._get(m, OC_SYSTEM)
        if xml:
            info = parse_openconfig_system(xml)
            dev.hostname = info.get("hostname")
            dev.os_version = info.get("version")
        xml = self._get(m, OC_INTERFACES)
        if xml:
            parse_openconfig_interfaces(xml, dev)
        xml = self._get(m, OC_LLDP)
        if xml:
            dev.neighbors.extend(parse_openconfig_lldp(xml))
        if not (dev.hostname or dev.interfaces or dev.neighbors):
            raise RuntimeError("equipamento não suporta modelos OpenConfig")

    def _junos(self, m: Any, dev: Device) -> None:
        from ncclient.xml_ import new_ele, sub_ele

        def rpc(name: str, **children: bool) -> Any:
            ele = new_ele(name)
            for child in children:
                sub_ele(ele, child.replace("_", "-"))
            try:
                return m.rpc(ele)
            except Exception as exc:
                log.debug("junos rpc %s: %s", name, exc)
                return None

        r = rpc("get-software-information")
        if r is not None:
            info = parse_junos_software(r.xml if hasattr(r, "xml") else str(r))
            dev.hostname, dev.model, dev.os_version = info.get("hostname"), info.get("model"), info.get("version")
        r = rpc("get-chassis-inventory")
        if r is not None:
            root = _root(r.xml if hasattr(r, "xml") else str(r))
            chassis = _all(root, "chassis")
            if chassis:
                dev.serial = _text(chassis[0], "serial-number")
        r = rpc("get-interface-information", terse=True)
        if r is not None:
            parse_junos_interfaces(r.xml if hasattr(r, "xml") else str(r), dev)
        r = rpc("get-lldp-neighbors-information")
        if r is not None:
            dev.neighbors.extend(parse_junos_lldp(r.xml if hasattr(r, "xml") else str(r)))
        if self.settings.collect.arp:
            r = rpc("get-arp-table-information", no_resolve=True)
            if r is not None:
                dev.arp.extend(parse_junos_arp(r.xml if hasattr(r, "xml") else str(r)))
