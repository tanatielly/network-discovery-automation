"""Deduplicação de equipamentos e merge de dados vindos de fontes diferentes."""

from __future__ import annotations

from typing import Any

from nettopo.models import Device
from nettopo.utils import ifname_key, is_default_hostname, normalize_mac, short_hostname, slugify

_JUNK_SERIALS = {"", "none", "n/a", "na", "unknown", "0", "123456789", "default", "not available"}


def _fill(dst: Any, src: Any, fields: list[str]) -> None:
    for f in fields:
        if getattr(dst, f) in (None, "", []) and getattr(src, f) not in (None, "", []):
            setattr(dst, f, getattr(src, f))


def merge_device(dst: Device, src: Device) -> Device:
    """Incorpora ``src`` em ``dst`` preenchendo lacunas e unindo listas sem duplicar."""
    _fill(dst, src, ["hostname", "mgmt_ip", "vendor", "os", "profile", "model", "os_version", "serial", "uptime",
                     "chassis_id", "sys_object_id", "sys_description", "location", "contact", "discovered_from"])
    for m in src.collected_via:
        if m not in dst.collected_via:
            dst.collected_via.append(m)
    for e in src.errors:
        if e not in dst.errors:
            dst.errors.append(e)
    dst.extra = {**src.extra, **dst.extra}

    for itf in src.interfaces:
        cur = dst.get_interface(itf.name)
        if cur is None:
            dst.interfaces.append(itf.model_copy(deep=True))
            continue
        _fill(cur, itf, ["description", "mac", "speed_mbps", "mtu", "admin_up", "oper_up", "if_index", "if_type",
                         "mode", "access_vlan", "trunk_vlans", "parent", "vrf"])
        for ip in itf.ipv4:
            bare = ip.split("/")[0]
            existing = [a for a in cur.ipv4 if a.split("/")[0] == bare]
            if not existing:
                cur.ipv4.append(ip)
            elif "/" in ip and "/" not in existing[0]:
                cur.ipv4[cur.ipv4.index(existing[0])] = ip

    def nkey(n: Any) -> tuple:
        remote = short_hostname(n.remote_hostname) or n.remote_chassis_id or n.remote_mgmt_ip or ""
        return (n.protocol, ifname_key(n.local_interface), remote)

    known = {nkey(n): n for n in dst.neighbors}
    for n in src.neighbors:
        k = nkey(n)
        if k in known:
            _fill(known[k], n, ["remote_hostname", "remote_interface", "remote_mgmt_ip", "remote_platform",
                                "remote_description", "remote_chassis_id", "remote_asn", "state"])
            if not known[k].remote_capabilities:
                known[k].remote_capabilities = list(n.remote_capabilities)
        else:
            dst.neighbors.append(n.model_copy(deep=True))
            known[k] = dst.neighbors[-1]

    vl = {v.id for v in dst.vlans}
    dst.vlans += [v for v in src.vlans if v.id not in vl]
    arp = {(a.ip, a.mac) for a in dst.arp}
    dst.arp += [a for a in src.arp if (a.ip, a.mac) not in arp]
    rt = {(r.prefix, r.next_hop, r.vrf) for r in dst.routes}
    dst.routes += [r for r in src.routes if (r.prefix, r.next_hop, r.vrf) not in rt]
    mt = {(m.mac, m.vlan) for m in dst.mac_table}
    dst.mac_table += [m for m in src.mac_table if (m.mac, m.vlan) not in mt]
    return dst


def device_keys(device: Device) -> list[str]:
    """Chaves fortes de identidade (serial, MAC do chassis, hostname não-padrão)."""
    keys = []
    if device.serial and device.serial.strip().lower() not in _JUNK_SERIALS:
        keys.append(f"serial:{device.serial.strip().upper()}")
    mac = normalize_mac(device.chassis_id)
    if mac and mac not in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"):
        keys.append(f"mac:{mac}")
    host = short_hostname(device.hostname)
    if host and not is_default_hostname(host):
        keys.append(f"host:{host}")
    return keys


def _conflict(a: Device, b: Device) -> bool:
    """Dois equipamentos com seriais diferentes nunca são o mesmo."""
    sa, sb = (a.serial or "").strip().upper(), (b.serial or "").strip().upper()
    return bool(sa and sb and sa.lower() not in _JUNK_SERIALS and sb.lower() not in _JUNK_SERIALS and sa != sb)


class IdentityIndex:
    def __init__(self) -> None:
        self.devices: dict[str, Device] = {}
        self._by_key: dict[str, str] = {}
        self._by_ip: dict[str, str] = {}

    def match(self, device: Device) -> Device | None:
        for k in device_keys(device):
            did = self._by_key.get(k)
            if did and not _conflict(self.devices[did], device):
                return self.devices[did]
        if device.mgmt_ip and device.mgmt_ip in self._by_ip:
            existing = self.devices[self._by_ip[device.mgmt_ip]]
            if not _conflict(existing, device):
                return existing
        return None

    def lookup_ip(self, ip: str | None) -> Device | None:
        did = self._by_ip.get(ip or "")
        return self.devices.get(did) if did else None

    def lookup_hostname(self, hostname: str | None) -> Device | None:
        host = short_hostname(hostname)
        if not host or is_default_hostname(host):
            return None
        did = self._by_key.get(f"host:{host}")
        return self.devices.get(did) if did else None

    def new_id(self, device: Device) -> str:
        base = slugify(short_hostname(device.hostname) or device.mgmt_ip or "device")
        did, n = base, 2
        while did in self.devices:
            did = f"{base}-{n}"
            n += 1
        return did

    def add(self, device: Device) -> Device:
        """Adiciona (ou funde com existente) e retorna o registro canônico."""
        existing = self.match(device)
        if existing is not None:
            merge_device(existing, device)
            device = existing
        else:
            device.id = device.id if device.id and device.id not in self.devices else self.new_id(device)
            self.devices[device.id] = device
        self.reindex(device)
        return device

    def reindex(self, device: Device) -> None:
        for k in device_keys(device):
            self._by_key.setdefault(k, device.id)
        for ip in device.ip_addresses():
            self._by_ip.setdefault(ip, device.id)
