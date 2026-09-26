"""Coletor via APIs REST/JSON-RPC dos fabricantes.

Drivers: Arista eAPI, Cisco NX-API, Cisco IOS-XE RESTCONF, MikroTik REST (v7) e
FortiOS REST. Cada driver separa a busca (``fetch``) da interpretação (``parse``),
que é pura e testável com JSON de exemplo.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from nettopo.collectors.base import MethodResult
from nettopo.config import Credential, Settings
from nettopo.models import ArpEntry, Device, Neighbor, Route, Vlan
from nettopo.utils import (
    canonical_ifname,
    ip_with_prefix,
    normalize_mac,
    parse_ipv4,
    to_int,
    truthy_status,
)
from nettopo.vendors.registry import VendorProfile, VendorRegistry

log = logging.getLogger(__name__)

Raw = dict[str, Any]


def _as_list(v: Any) -> list[Any]:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _rows(body: Any, table: str, row: str) -> list[dict[str, Any]]:
    """Extrai linhas no formato NX-API ``TABLE_x`` / ``ROW_x`` (dict ou lista)."""
    if not isinstance(body, dict):
        return []
    out: list[dict[str, Any]] = []
    for t in _as_list(body.get(table)):
        if isinstance(t, dict):
            out.extend(r for r in _as_list(t.get(row)) if isinstance(r, dict))
    return out


# =========================================================================== Arista eAPI

class EapiDriver:
    commands = ["show version", "show hostname", "show interfaces", "show lldp neighbors detail",
                "show ip arp", "show vlan", "show ip route"]

    async def fetch(self, client: httpx.AsyncClient, base: str, cred: Credential) -> Raw:
        raw: Raw = {}
        for i, cmd in enumerate(self.commands):
            payload = {"jsonrpc": "2.0", "method": "runCmds", "id": i,
                       "params": {"version": 1, "cmds": [cmd], "format": "json"}}
            r = await client.post(f"{base}/command-api", json=payload,
                                  auth=(cred.username or "", cred.secret("password") or ""))
            if r.status_code in (401, 403):
                raise PermissionError("eAPI: autenticação negada")
            r.raise_for_status()
            data = r.json()
            if "result" in data:
                raw[cmd] = data["result"][0]
        return raw

    @staticmethod
    def parse(raw: Raw, dev: Device) -> None:
        ver = raw.get("show version") or {}
        host = raw.get("show hostname") or {}
        dev.hostname = host.get("hostname") or dev.hostname
        dev.model = ver.get("modelName")
        dev.os_version = ver.get("version")
        dev.serial = ver.get("serialNumber")
        dev.chassis_id = normalize_mac(ver.get("systemMacAddress"))
        for name, i in (raw.get("show interfaces") or {}).get("interfaces", {}).items():
            itf = dev.upsert_interface(name)
            itf.description = i.get("description") or None
            itf.mac = normalize_mac(i.get("physicalAddress"))
            itf.mtu = i.get("mtu")
            bw = i.get("bandwidth")
            itf.speed_mbps = int(bw / 1_000_000) if bw else None
            itf.oper_up = truthy_status(i.get("lineProtocolStatus"))
            itf.admin_up = i.get("interfaceStatus") != "disabled"
            for a in i.get("interfaceAddress", []) or []:
                p = a.get("primaryIp") or {}
                if p.get("address") and p.get("address") != "0.0.0.0":
                    itf.ipv4.append(f"{p['address']}/{p.get('maskLen')}")
            if i.get("interfaceMembership"):
                itf.parent = canonical_ifname(str(i["interfaceMembership"]).split()[-1])
        lldp = (raw.get("show lldp neighbors detail") or {}).get("lldpNeighbors", {})
        for local, info in lldp.items():
            for n in info.get("lldpNeighborInfo", []):
                nif = n.get("neighborInterfaceInfo") or {}
                port = nif.get("interfaceId_v2") or str(nif.get("interfaceId", "")).strip('"')
                if normalize_mac(port) and nif.get("interfaceDescription"):
                    port = nif["interfaceDescription"]
                mgmt = next((m.get("address") for m in n.get("managementAddresses", [])
                             if m.get("addressType", "ipv4").lower() == "ipv4"), None)
                caps = [k.lower() for k, v in (n.get("systemCapabilities") or {}).items() if v]
                dev.neighbors.append(Neighbor(
                    protocol="lldp", local_interface=canonical_ifname(local),
                    remote_hostname=n.get("systemName"), remote_interface=port,
                    remote_mgmt_ip=parse_ipv4(mgmt), remote_chassis_id=normalize_mac(n.get("chassisId")),
                    remote_description=n.get("systemDescription"),
                    remote_platform=(n.get("systemDescription") or "")[:120] or None,
                    remote_capabilities=["wlan" if c == "wlanaccesspoint" else c for c in caps],
                ))
        for a in (raw.get("show ip arp") or {}).get("ipV4Neighbors", []):
            dev.arp.append(ArpEntry(ip=a.get("address"), mac=normalize_mac(a.get("hwAddress")),
                                    interface=canonical_ifname(a.get("interface"))))
        for vid, v in (raw.get("show vlan") or {}).get("vlans", {}).items():
            if str(vid).isdigit():
                dev.vlans.append(Vlan(id=int(vid), name=v.get("name"),
                                      interfaces=[canonical_ifname(x) or x for x in (v.get("interfaces") or {})]))
        for vrf, vdata in (raw.get("show ip route") or {}).get("vrfs", {}).items():
            for prefix, r in (vdata.get("routes") or {}).items():
                for via in r.get("vias") or [{}]:
                    dev.routes.append(Route(prefix=prefix, next_hop=parse_ipv4(via.get("nexthopAddr")),
                                            interface=canonical_ifname(via.get("interface")),
                                            protocol=r.get("routeType"), vrf=vrf))


# =========================================================================== Cisco NX-API

class NxapiDriver:
    commands = ["show version", "show hostname", "show interface", "show lldp neighbors detail",
                "show cdp neighbors detail", "show ip arp", "show vlan brief"]

    async def fetch(self, client: httpx.AsyncClient, base: str, cred: Credential) -> Raw:
        raw: Raw = {}
        for i, cmd in enumerate(self.commands, start=1):
            payload = [{"jsonrpc": "2.0", "method": "cli", "params": {"cmd": cmd, "version": 1}, "id": i}]
            r = await client.post(f"{base}/ins", json=payload, headers={"content-type": "application/json-rpc"},
                                  auth=(cred.username or "", cred.secret("password") or ""))
            if r.status_code in (401, 403):
                raise PermissionError("NX-API: autenticação negada")
            if r.status_code >= 400:
                continue
            data = r.json()
            data = data[0] if isinstance(data, list) else data
            body = (data.get("result") or {}).get("body")
            if body:
                raw[cmd] = body
        return raw

    @staticmethod
    def parse(raw: Raw, dev: Device) -> None:
        ver = raw.get("show version") or {}
        dev.hostname = (raw.get("show hostname") or {}).get("hostname") or ver.get("host_name") or dev.hostname
        dev.model = ver.get("chassis_id")
        dev.os_version = ver.get("nxos_ver_str") or ver.get("sys_ver_str") or ver.get("kickstart_ver_str")
        dev.serial = ver.get("proc_board_id")
        for r in _rows(raw.get("show interface"), "TABLE_interface", "ROW_interface"):
            name = r.get("interface")
            if not name:
                continue
            itf = dev.upsert_interface(name)
            itf.description = r.get("desc") or r.get("svi_desc")
            itf.mac = normalize_mac(r.get("eth_hw_addr") or r.get("svi_mac"))
            itf.mtu = to_int(r.get("eth_mtu") or r.get("svi_mtu"))
            bw = to_int(r.get("eth_bw") or r.get("svi_bw"))
            itf.speed_mbps = bw // 1000 if bw else None
            itf.oper_up = truthy_status(r.get("state") or r.get("svi_line_proto"))
            itf.admin_up = truthy_status(r.get("admin_state") or r.get("svi_admin_state"))
            ip = r.get("eth_ip_addr") or r.get("svi_ip_addr")
            mask = r.get("eth_ip_mask") or r.get("svi_ip_mask")
            cidr = ip_with_prefix(ip, mask)
            if cidr:
                itf.ipv4.append(cidr)
            if r.get("eth_bundle"):
                itf.parent = canonical_ifname(f"Port-channel{r['eth_bundle']}")
        for r in _rows(raw.get("show lldp neighbors detail"), "TABLE_nbor_detail", "ROW_nbor_detail"):
            dev.neighbors.append(Neighbor(
                protocol="lldp", local_interface=canonical_ifname(r.get("l_port_id")),
                remote_hostname=r.get("sys_name"), remote_interface=r.get("port_id"),
                remote_mgmt_ip=parse_ipv4(r.get("mgmt_addr")), remote_chassis_id=normalize_mac(r.get("chassis_id")),
                remote_description=r.get("sys_desc"), remote_platform=(r.get("sys_desc") or "")[:120] or None,
            ))
        for r in _rows(raw.get("show cdp neighbors detail"), "TABLE_cdp_neighbor_detail_info",
                       "ROW_cdp_neighbor_detail_info"):
            mgmt = r.get("v4mgmtaddr") or r.get("v4addr")
            if isinstance(mgmt, dict):
                mgmt = next(iter(mgmt.values()), None)
            dev.neighbors.append(Neighbor(
                protocol="cdp", local_interface=canonical_ifname(r.get("intf_id")),
                remote_hostname=r.get("device_id"), remote_interface=r.get("port_id"),
                remote_mgmt_ip=parse_ipv4(mgmt), remote_platform=r.get("platform_id"),
                remote_description=r.get("version"),
                remote_capabilities=[str(c).lower() for c in _as_list(r.get("capability"))],
            ))
        arp_body = raw.get("show ip arp") or {}
        for vrf in _rows(arp_body, "TABLE_vrf", "ROW_vrf"):
            for a in _rows(vrf, "TABLE_adj", "ROW_adj"):
                ip = parse_ipv4(a.get("ip-addr-out"))
                if ip:
                    dev.arp.append(ArpEntry(ip=ip, mac=normalize_mac(a.get("mac")),
                                            interface=canonical_ifname(a.get("intf-out"))))
        for v in _rows(raw.get("show vlan brief"), "TABLE_vlanbriefxbrief", "ROW_vlanbriefxbrief"):
            vid = to_int(v.get("vlanshowbr-vlanid"))
            if vid:
                ports = str(v.get("vlanshowplist-ifidx") or "")
                dev.vlans.append(Vlan(id=vid, name=v.get("vlanshowbr-vlanname"),
                                      interfaces=[canonical_ifname(p.strip()) or p for p in ports.split(",") if p.strip()]))


# =========================================================================== IOS-XE RESTCONF

class RestconfIosxeDriver:
    paths = {
        "hostname": "Cisco-IOS-XE-native:native/hostname",
        "version": "Cisco-IOS-XE-native:native/version",
        "interfaces": "Cisco-IOS-XE-interfaces-oper:interfaces",
        "lldp": "Cisco-IOS-XE-lldp-oper:lldp-entries",
        "cdp": "Cisco-IOS-XE-cdp-oper:cdp-neighbor-details",
        "arp": "Cisco-IOS-XE-arp-oper:arp-data",
        "hardware": "Cisco-IOS-XE-device-hardware-oper:device-hardware-data",
    }

    async def fetch(self, client: httpx.AsyncClient, base: str, cred: Credential) -> Raw:
        raw: Raw = {}
        for key, path in self.paths.items():
            r = await client.get(f"{base}/restconf/data/{path}",
                                 headers={"Accept": "application/yang-data+json"},
                                 auth=(cred.username or "", cred.secret("password") or ""))
            if r.status_code in (401, 403):
                raise PermissionError("RESTCONF: autenticação negada")
            if r.status_code == 200 and r.content:
                raw[key] = r.json()
        return raw

    @staticmethod
    def _unwrap(d: Any) -> Any:
        if isinstance(d, dict) and len(d) == 1:
            return next(iter(d.values()))
        return d

    @classmethod
    def parse(cls, raw: Raw, dev: Device) -> None:
        dev.hostname = cls._unwrap(raw.get("hostname")) or dev.hostname
        ver = cls._unwrap(raw.get("version"))
        dev.os_version = str(ver) if ver else None
        hw = cls._unwrap(raw.get("hardware")) or {}
        for item in _as_list((hw.get("device-hardware") or {}).get("device-inventory")):
            if item.get("hw-type") == "hw-type-chassis":
                dev.serial = item.get("serial-number")
                dev.model = item.get("part-number")
                break
        for i in _as_list((cls._unwrap(raw.get("interfaces")) or {}).get("interface")):
            itf = dev.upsert_interface(i.get("name", ""))
            itf.description = i.get("description") or None
            itf.mac = normalize_mac(i.get("phys-address"))
            itf.mtu = to_int(i.get("mtu"))
            speed = to_int(i.get("speed"))
            itf.speed_mbps = speed // 1_000_000 if speed else None
            itf.admin_up = truthy_status(str(i.get("admin-status", "")).replace("if-state-", ""))
            itf.oper_up = truthy_status(str(i.get("oper-status", "")).replace("if-oper-state-", "").replace("ready", "up"))
            cidr = ip_with_prefix(i.get("ipv4"), i.get("ipv4-subnet-mask"))
            if cidr and not cidr.startswith("0.0.0.0"):
                itf.ipv4.append(cidr)
        for e in _as_list((cls._unwrap(raw.get("lldp")) or {}).get("lldp-entry")):
            dev.neighbors.append(Neighbor(protocol="lldp", local_interface=canonical_ifname(e.get("local-interface")),
                                          remote_hostname=e.get("device-id"),
                                          remote_interface=e.get("connecting-interface")))
        for e in _as_list((cls._unwrap(raw.get("cdp")) or {}).get("cdp-neighbor-detail")):
            dev.neighbors.append(Neighbor(
                protocol="cdp", local_interface=canonical_ifname(e.get("local-intf-name")),
                remote_hostname=e.get("device-name"), remote_interface=e.get("port-id"),
                remote_mgmt_ip=parse_ipv4(e.get("mgmt-address") or e.get("ip-address")),
                remote_platform=e.get("platform-name"), remote_description=e.get("version"),
            ))
        for vrf in _as_list((cls._unwrap(raw.get("arp")) or {}).get("arp-vrf")):
            for a in _as_list(vrf.get("arp-oper")):
                ip = parse_ipv4(a.get("address"))
                if ip:
                    dev.arp.append(ArpEntry(ip=ip, mac=normalize_mac(a.get("hardware")),
                                            interface=canonical_ifname(a.get("interface"))))


# =========================================================================== MikroTik REST

class MikrotikRestDriver:
    paths = {
        "identity": "system/identity", "resource": "system/resource", "routerboard": "system/routerboard",
        "interfaces": "interface", "addresses": "ip/address", "neighbors": "ip/neighbor", "arp": "ip/arp",
        "routes": "ip/route", "vlans": "interface/vlan",
    }

    async def fetch(self, client: httpx.AsyncClient, base: str, cred: Credential) -> Raw:
        raw: Raw = {}
        for key, path in self.paths.items():
            r = await client.get(f"{base}/rest/{path}", auth=(cred.username or "", cred.secret("password") or ""))
            if r.status_code in (401, 403):
                raise PermissionError("MikroTik REST: autenticação negada")
            if r.status_code == 200:
                raw[key] = r.json()
        return raw

    @staticmethod
    def parse(raw: Raw, dev: Device) -> None:
        dev.hostname = (raw.get("identity") or {}).get("name") or dev.hostname
        res = raw.get("resource") or {}
        rb = raw.get("routerboard") or {}
        dev.model = rb.get("model") or res.get("board-name")
        dev.os_version = res.get("version")
        dev.serial = rb.get("serial-number")
        dev.uptime = res.get("uptime")
        for i in _as_list(raw.get("interfaces")):
            itf = dev.upsert_interface(i.get("name", ""))
            itf.mac = normalize_mac(i.get("mac-address"))
            itf.mtu = to_int(i.get("actual-mtu") or i.get("mtu"))
            itf.oper_up = truthy_status(i.get("running"))
            itf.admin_up = not truthy_status(i.get("disabled")) if i.get("disabled") is not None else None
            itf.description = i.get("comment")
            itf.if_type = i.get("type")
        for a in _as_list(raw.get("addresses")):
            if a.get("interface") and a.get("address"):
                dev.upsert_interface(a["interface"]).ipv4.append(a["address"])
        for n in _as_list(raw.get("neighbors")):
            by = str(n.get("discovered-by", "mndp")).lower()
            proto = "lldp" if "lldp" in by else "cdp" if "cdp" in by else "mndp"
            dev.neighbors.append(Neighbor(
                protocol=proto, local_interface=str(n.get("interface", "")).split(",")[0] or None,
                remote_hostname=n.get("identity"), remote_interface=n.get("interface-name"),
                remote_mgmt_ip=parse_ipv4(n.get("address4") or n.get("address")),
                remote_chassis_id=normalize_mac(n.get("mac-address")),
                remote_platform=" ".join(x for x in (n.get("platform"), n.get("board")) if x) or None,
                remote_description=n.get("system-description"),
                remote_capabilities=[c for c in str(n.get("system-caps-enabled", "")).split(",") if c],
            ))
        for a in _as_list(raw.get("arp")):
            ip = parse_ipv4(a.get("address"))
            if ip:
                dev.arp.append(ArpEntry(ip=ip, mac=normalize_mac(a.get("mac-address")), interface=a.get("interface")))
        for r in _as_list(raw.get("routes")):
            gw = r.get("gateway") or ""
            proto = next((p for p in ("ospf", "bgp", "static", "connect", "rip") if truthy_status(r.get(p))), None)
            dev.routes.append(Route(prefix=r.get("dst-address", ""), next_hop=parse_ipv4(gw),
                                    interface=None if parse_ipv4(gw) else gw or None,
                                    protocol="connected" if proto == "connect" else proto,
                                    vrf=r.get("routing-table")))
        for v in _as_list(raw.get("vlans")):
            vid = to_int(v.get("vlan-id"))
            if vid:
                dev.vlans.append(Vlan(id=vid, name=v.get("name"), interfaces=[v.get("interface")] if v.get("interface") else []))


# =========================================================================== FortiOS REST

class FortiosDriver:
    paths = {
        "status": "monitor/system/status", "interfaces": "cmdb/system/interface",
        "lldp": "monitor/network/lldp/neighbors", "arp": "monitor/network/arp", "routes": "monitor/router/ipv4",
    }

    async def fetch(self, client: httpx.AsyncClient, base: str, cred: Credential) -> Raw:
        headers = {"Authorization": f"Bearer {cred.secret('token')}"} if cred.token else {}
        raw: Raw = {}
        for key, path in self.paths.items():
            r = await client.get(f"{base}/api/v2/{path}", headers=headers)
            if r.status_code in (401, 403):
                raise PermissionError("FortiOS: token inválido")
            if r.status_code == 200:
                raw[key] = r.json()
        return raw

    @staticmethod
    def parse(raw: Raw, dev: Device) -> None:
        st = raw.get("status") or {}
        res = st.get("results") or {}
        dev.hostname = res.get("hostname") or dev.hostname
        dev.model = res.get("model_name") and f"{res.get('model_name')} {res.get('model_number', '')}".strip() or res.get("model")
        dev.serial = st.get("serial")
        dev.os_version = st.get("version")
        for i in _as_list((raw.get("interfaces") or {}).get("results")):
            itf = dev.upsert_interface(i.get("name", ""))
            itf.description = i.get("description") or i.get("alias") or None
            itf.mac = normalize_mac(i.get("macaddr"))
            itf.admin_up = truthy_status(i.get("status"))
            cidr = ip_with_prefix(i.get("ip"))
            if cidr and not cidr.startswith("0.0.0.0"):
                itf.ipv4.append(cidr)
            itf.vrf = i.get("vdom")
            if i.get("vlanid"):
                itf.access_vlan = to_int(i.get("vlanid"))
                itf.parent = i.get("interface")
        for n in _as_list((raw.get("lldp") or {}).get("results")):
            addrs = n.get("addresses") or n.get("management_addresses") or []
            mgmt = next((a.get("address") for a in addrs if isinstance(a, dict)), None) or n.get("management_address")
            dev.neighbors.append(Neighbor(
                protocol="lldp", local_interface=n.get("port") or n.get("port_name") or n.get("interface"),
                remote_hostname=n.get("system_name"), remote_interface=n.get("port_id") or n.get("port_description"),
                remote_mgmt_ip=parse_ipv4(mgmt), remote_chassis_id=normalize_mac(n.get("chassis_id")),
                remote_description=n.get("system_description"),
            ))
        for a in _as_list((raw.get("arp") or {}).get("results")):
            ip = parse_ipv4(a.get("ip"))
            if ip:
                dev.arp.append(ArpEntry(ip=ip, mac=normalize_mac(a.get("mac")), interface=a.get("interface")))
        for r in _as_list((raw.get("routes") or {}).get("results")):
            dev.routes.append(Route(prefix=r.get("ip_mask", ""), next_hop=parse_ipv4(r.get("gateway")),
                                    interface=r.get("interface"), protocol=r.get("type")))


DRIVERS: dict[str, Any] = {
    "eapi": EapiDriver,
    "nxapi": NxapiDriver,
    "restconf_iosxe": RestconfIosxeDriver,
    "mikrotik": MikrotikRestDriver,
    "fortios": FortiosDriver,
}


class RestCollector:
    name = "rest"

    def __init__(self, settings: Settings, registry: VendorRegistry):
        self.settings = settings
        self.registry = registry

    async def collect(self, target: str, profile: VendorProfile | None,
                      credentials: list[Credential]) -> MethodResult:
        res = MethodResult(method=self.name)
        if not profile or not profile.rest or profile.rest not in DRIVERS:
            res.errors.append("rest: perfil sem driver de API")
            return res
        if not credentials:
            res.errors.append("rest: nenhuma credencial")
            return res
        driver = DRIVERS[profile.rest]()
        for cred in credentials:
            scheme = "https" if cred.https else "http"
            port = f":{cred.port}" if cred.port else ""
            base = f"{scheme}://{target}{port}"
            try:
                async with httpx.AsyncClient(verify=cred.verify_ssl, timeout=self.settings.timeout) as client:
                    raw = await driver.fetch(client, base, cred)
            except PermissionError as exc:
                res.errors.append(f"rest[{cred.display}]: {exc}")
                continue
            except (httpx.HTTPError, ValueError) as exc:
                res.errors.append(f"rest[{cred.display}]: {type(exc).__name__}: {str(exc)[:160]}")
                continue
            if not raw:
                res.errors.append(f"rest[{cred.display}]: API sem dados")
                continue
            dev = Device(mgmt_ip=target, vendor=profile.vendor, os=profile.os, profile=profile.id,
                         collected_via=["rest"])
            try:
                driver.parse(raw, dev)
            except Exception as exc:  # resposta inesperada
                res.errors.append(f"rest: erro ao interpretar resposta: {exc}")
                continue
            res.device = dev
            res.credential = cred
            return res
        return res
