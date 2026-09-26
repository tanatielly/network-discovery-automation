"""Normaliza linhas parseadas (TextFSM/ntc-templates ou parsers próprios) no modelo comum.

Os templates do ntc-templates usam nomes de campos diferentes por plataforma
(``NEIGHBOR_NAME``, ``DESTINATION_HOST``, ``SYSTEM_NAME``...). Aqui cada campo do
modelo tem uma lista de candidatos, o que permite reaproveitar o mesmo código para
qualquer vendor.
"""

from __future__ import annotations

import re
from typing import Any

from nettopo.models import ArpEntry, Device, MacEntry, Neighbor, Route, Vlan
from nettopo.utils import (
    canonical_ifname,
    extract_ipv4s,
    ip_with_prefix,
    normalize_mac,
    parse_ipv4,
    parse_speed_mbps,
    to_int,
    truthy_status,
)

Row = dict[str, Any]


def pick(row: Row, *keys: str, default: Any = None) -> Any:
    for k in keys:
        v = row.get(k)
        if isinstance(v, list):
            v = next((x for x in v if x not in (None, "")), None)
        if isinstance(v, str):
            v = v.strip()
        if v not in (None, "", "N/A", "n/a", "--", "-", "not advertised", "Not Advertised"):
            return v
    return default


def pick_list(row: Row, *keys: str) -> list[Any]:
    for k in keys:
        v = row.get(k)
        if v in (None, "", []):
            continue
        return v if isinstance(v, list) else [v]
    return []


def lower_keys(rows: list[Row]) -> list[Row]:
    return [{str(k).lower(): v for k, v in r.items()} for r in rows]


# --------------------------------------------------------------------------- campos

HOSTNAME = ("hostname", "host_name", "sysname", "system_name", "switch_name", "name", "identity")
VERSION = ("version", "os_version", "software_version", "sw_version", "running_image_version",
           "junos_version", "os", "firmware_version", "release", "software_revision", "sw-version")
SERIAL = ("serial", "serial_number", "serialnum", "chassis_serial", "serial_num", "system_serial_number",
          "serial-number", "sn", "serialno")
MODEL = ("hardware", "model", "platform", "chassis", "hardware_model", "product_model", "board_name",
         "board-name", "model_name", "chassis_type", "product", "system_type", "device_model")
UPTIME = ("uptime", "up_time", "system_uptime", "uptime_string")
MAC = ("mac_address", "mac", "hw_address", "hwaddr", "macaddress", "address", "bia", "mac-address",
       "hardware_address", "physical_address", "base_mac")

IF_NAME = ("interface", "name", "intf", "port", "interface_name", "port_name", "ifname")
LLDP_LOCAL = ("local_interface", "local_port", "local_intf", "localport", "local_port_id", "port",
              "local_interface_id", "interface", "local_intf_id", "local_if")
LLDP_NAME = ("neighbor_name", "neighbor", "system_name", "remote_system_name", "neighbor_sysname",
             "chassis_name", "destination_host", "device_id", "sysname", "remote_sysname", "identity")
LLDP_PORT = ("neighbor_interface", "neighbor_port_id", "port_id", "remote_port", "neighbor_port",
             "remote_port_id", "port_description", "neighbor_port_description", "remote_interface",
             "interface_name")
LLDP_MGMT = ("mgmt_address", "management_ip", "mgmt_ip", "management_address", "neighbor_mgmt_address",
             "management_addresses", "remote_management_address", "mgmt_addr", "address", "ip_address",
             "neighbor_ip", "address4")
LLDP_PLATFORM = ("platform", "neighbor_description", "system_description", "system_descr",
                 "remote_system_desc", "software_version", "board", "neighbor_platform")
LLDP_CHASSIS = ("chassis_id", "neighbor_chassis_id", "remote_chassis_id", "mac_address", "mac-address")
LLDP_CAPS = ("capabilities", "system_capabilities", "enabled_capabilities", "capability",
             "neighbor_capabilities", "system_caps_enabled", "system-caps-enabled")


def _caps(value: Any) -> list[str]:
    if not value:
        return []
    text = " ".join(value) if isinstance(value, list) else str(value)
    mapping = {
        "router": "router", "r": "router", "bridge": "bridge", "b": "bridge", "switch": "bridge",
        "s": "bridge", "trans-bridge": "bridge", "t": "bridge", "wlan": "wlan", "w": "wlan",
        "wlan-access-point": "wlan", "wlan access point": "wlan", "access point": "wlan",
        "telephone": "telephone", "phone": "telephone", "p": "telephone", "station": "station",
        "host": "station", "h": "station", "repeater": "repeater", "docsis": "docsis",
    }
    out: list[str] = []
    for tok in re.split(r"[,\s/;]+", text.strip().lower()):
        cap = mapping.get(tok)
        if cap and cap not in out:
            out.append(cap)
    return out


# --------------------------------------------------------------------------- aplicação

def apply_rows(device: Device, kind: str, rows: list[Row], protocol: str | None = None) -> int:
    """Aplica as linhas ao ``device``; retorna quantos registros foram incorporados."""
    rows = lower_keys(rows)
    handler = _HANDLERS.get(kind)
    if not handler or not rows:
        return 0
    if kind in ("lldp", "cdp", "other_l2"):
        return handler(device, rows, protocol or ("mndp" if kind == "other_l2" else kind))
    return handler(device, rows)


def _facts(device: Device, rows: list[Row]) -> int:
    row: Row = {}
    for r in rows:  # alguns templates retornam várias linhas (uma por módulo)
        for k, v in r.items():
            row.setdefault(k, v)
    device.hostname = device.hostname or pick(row, *HOSTNAME)
    device.os_version = device.os_version or pick(row, *VERSION)
    device.serial = device.serial or pick(row, *SERIAL)
    device.model = device.model or pick(row, *MODEL)
    device.uptime = device.uptime or pick(row, *UPTIME)
    mac = normalize_mac(pick(row, *MAC))
    device.chassis_id = device.chassis_id or mac
    return 1


def _hostname(device: Device, rows: list[Row]) -> int:
    for r in rows:
        h = pick(r, *HOSTNAME)
        if h:
            h = re.sub(r"^(sysname|hostname)\s+", "", str(h), flags=re.I).strip()
            device.hostname = h
            return 1
    return 0


def _interfaces(device: Device, rows: list[Row]) -> int:
    n = 0
    for r in rows:
        name = pick(r, *IF_NAME)
        if not name:
            continue
        itf = device.upsert_interface(str(name))
        itf.description = itf.description or pick(r, "description", "desc", "alias", "comment", "port_description")
        itf.mac = itf.mac or normalize_mac(pick(r, "mac_address", "address", "hw_address", "bia", "mac",
                                                "mac-address", "hardware_address", "physical_address"))
        itf.mtu = itf.mtu or to_int(pick(r, "mtu", "actual-mtu", "actual_mtu"))
        speed = pick(r, "bandwidth", "speed", "bw", "port_speed")
        itf.speed_mbps = itf.speed_mbps or parse_speed_mbps(speed)
        link = pick(r, "link_status", "status", "oper_status", "line_status", "link", "state", "running",
                    "protocol_status", "proto", "protocol", "physical")
        admin = pick(r, "admin_state", "admin_status", "admin", "enabled")
        if itf.oper_up is None:
            itf.oper_up = truthy_status(link)
        if itf.admin_up is None:
            if admin is not None:
                itf.admin_up = truthy_status(admin)
            elif link is not None and "admin" in str(link).lower():
                itf.admin_up = False
            elif pick(r, "disabled") is not None:
                itf.admin_up = not truthy_status(pick(r, "disabled"))
        ips = pick_list(r, "ip_address", "ipaddr", "ip", "ipv4_address", "ip_address_mask", "ipv4",
                        "primary_ip", "address_ip")
        pfx = pick_list(r, "prefix_length", "mask", "prefix", "ip_mask", "netmask", "subnet_mask", "mask_length")
        for i, ip in enumerate(ips):
            if not ip or str(ip).lower() in ("unassigned", "unnumbered", "n/a"):
                continue
            p = pfx[i] if i < len(pfx) else (pfx[0] if len(pfx) == 1 else None)
            cidr = ip_with_prefix(ip, p)
            if cidr and not any(a.split("/")[0] == cidr.split("/")[0] for a in itf.ipv4):
                itf.ipv4.append(cidr)
            elif cidr and "/" in cidr:  # completa prefixo desconhecido
                itf.ipv4 = [cidr if a == cidr.split("/")[0] else a for a in itf.ipv4]
        vlan = pick(r, "access_vlan", "vlan", "pvid", "native_vlan")
        if vlan and str(vlan).isdigit():
            itf.access_vlan = itf.access_vlan or int(vlan)
        mode = pick(r, "mode", "switchport_mode", "port_mode")
        if mode:
            itf.mode = itf.mode or str(mode).lower()
        parent = pick(r, "members_of", "lag", "port_channel", "parent", "bundle", "aggregated_interface")
        if parent:
            itf.parent = itf.parent or canonical_ifname(str(parent))
        itype = pick(r, "hardware_type", "type", "if_type", "media_type")
        if itype:
            itf.if_type = itf.if_type or str(itype)
        vrf = pick(r, "vrf")
        if vrf:
            itf.vrf = itf.vrf or str(vrf)
        n += 1
    return n


def _neighbors(device: Device, rows: list[Row], protocol: str) -> int:
    n = 0
    for r in rows:
        proto = str(pick(r, "protocol_name", default=protocol)).lower()
        name = pick(r, *LLDP_NAME)
        port = pick(r, *LLDP_PORT)
        chassis = pick(r, *LLDP_CHASSIS)
        if not (name or port or chassis):
            continue
        mgmt_raw = pick_list(r, *LLDP_MGMT)
        mgmt = None
        for cand in mgmt_raw:
            ips = extract_ipv4s(str(cand))
            if ips:
                mgmt = ips[0]
                break
        platform = pick(r, *LLDP_PLATFORM)
        chassis_mac = normalize_mac(chassis)
        nb = Neighbor(
            protocol=proto,
            local_interface=canonical_ifname(pick(r, *LLDP_LOCAL)),
            remote_hostname=str(name).strip() if name else None,
            remote_interface=str(port).strip() if port else None,
            remote_mgmt_ip=parse_ipv4(mgmt),
            remote_platform=str(platform)[:200] if platform else None,
            remote_description=pick(r, "system_description", "neighbor_description", "system_descr"),
            remote_chassis_id=chassis_mac or (str(chassis) if chassis else None),
            remote_capabilities=_caps(pick(r, *LLDP_CAPS)),
        )
        # Se o port-id é um MAC e há descrição da porta, usa a descrição como nome
        if nb.remote_interface and normalize_mac(nb.remote_interface):
            desc = pick(r, "port_description", "neighbor_port_description", "remote_port_description")
            if desc:
                nb.remote_interface = str(desc)
        device.neighbors.append(nb)
        n += 1
    return n


def _arp(device: Device, rows: list[Row]) -> int:
    n = 0
    for r in rows:
        ip = parse_ipv4(pick(r, "ip_address", "address", "ip", "ipaddr", "ip_addr", "ip-address", "ipv4_address"))
        if not ip:
            continue
        mac = normalize_mac(pick(r, "mac_address", "mac", "hardware_addr", "hwaddr", "mac_addr", "mac-address",
                                 "hardware_address", "lladdr"))
        itf = pick(r, "interface", "port", "intf", "interface_name", "dev", "vlan_interface", "vlan")
        device.arp.append(ArpEntry(ip=ip, mac=mac, interface=canonical_ifname(str(itf)) if itf else None))
        n += 1
    return n


def _routes(device: Device, rows: list[Row]) -> int:
    n = 0
    for r in rows:
        net = pick(r, "network", "prefix", "destination", "dest", "dst-address", "route", "ip_mask", "dst")
        if not net:
            continue
        mask = pick(r, "prefix_length", "mask", "netmask", "prefix_len", "cidr", "mask_length")
        prefix = ip_with_prefix(net, mask)
        if not prefix:
            if str(net).lower() == "default":
                prefix = "0.0.0.0/0"
            else:
                continue
        nh = pick_list(r, "nexthop_ip", "next_hop", "nexthop", "gateway", "next_hop_ip", "via", "nexthop_addr")
        itf = pick_list(r, "nexthop_if", "interface", "outgoing_interface", "nexthop_interface", "dev",
                        "next_hop_interface", "exit_interface")
        proto = pick(r, "protocol", "proto", "type", "route_type", "source")
        vrf = pick(r, "vrf", "routing_instance", "table", "vpn_instance")
        nhs = nh or [None]
        for i, hop in enumerate(nhs):
            iface = itf[i] if i < len(itf) else (itf[0] if itf else None)
            device.routes.append(Route(prefix=prefix, next_hop=parse_ipv4(hop) if hop else None,
                                       interface=canonical_ifname(str(iface)) if iface else None,
                                       protocol=str(proto) if proto else None, vrf=str(vrf) if vrf else None))
            n += 1
    return n


def _vlans(device: Device, rows: list[Row]) -> int:
    n = 0
    known = {v.id for v in device.vlans}
    for r in rows:
        vid = to_int(pick(r, "vlan_id", "vlan", "id", "vlanid", "vlan-id", "tag"))
        if vid is None or not (1 <= vid <= 4094) or vid in known:
            continue
        ifs = pick_list(r, "interfaces", "ports", "members", "member_ports", "tagged_ports", "untagged_ports")
        if len(ifs) == 1 and isinstance(ifs[0], str) and "," in ifs[0]:
            ifs = [x.strip() for x in ifs[0].split(",")]
        device.vlans.append(Vlan(id=vid, name=pick(r, "vlan_name", "name", "description"),
                                 interfaces=[canonical_ifname(str(i)) or str(i) for i in ifs if i]))
        known.add(vid)
        n += 1
    return n


def _mac_table(device: Device, rows: list[Row]) -> int:
    n = 0
    for r in rows:
        mac = normalize_mac(pick(r, "destination_address", "mac_address", "mac", "mac-address", "macaddress"))
        if not mac:
            continue
        port = pick(r, "destination_port", "port", "interface", "ports", "outgoing_interface")
        device.mac_table.append(MacEntry(mac=mac, vlan=to_int(pick(r, "vlan", "vlan_id")),
                                         interface=canonical_ifname(str(port)) if port else None))
        n += 1
    return n


def _ospf(device: Device, rows: list[Row]) -> int:
    n = 0
    for r in rows:
        addr = parse_ipv4(pick(r, "address", "ip_address", "neighbor_address", "neighbor_ipaddr", "nbr_address",
                               "interface_address", "neighbor_ip"))
        rid = parse_ipv4(pick(r, "neighbor_id", "router_id", "neighbor", "neighbor_router_id", "nbr_id"))
        if not (addr or rid):
            continue
        device.neighbors.append(Neighbor(
            protocol="ospf", local_interface=canonical_ifname(pick(r, "interface", "intf", "local_interface")),
            remote_mgmt_ip=addr or rid, remote_chassis_id=rid, state=pick(r, "state", "status"),
        ))
        n += 1
    return n


def _bgp(device: Device, rows: list[Row]) -> int:
    n = 0
    for r in rows:
        peer = parse_ipv4(pick(r, "bgp_neigh", "neighbor", "peer", "neighbor_ip", "remote_ip", "peer_ip",
                               "neighbor_address", "peer_address"))
        if not peer:
            continue
        device.neighbors.append(Neighbor(
            protocol="bgp", remote_mgmt_ip=peer,
            remote_asn=to_int(pick(r, "neigh_as", "remote_as", "asn", "peer_as", "as", "neighbor_as")),
            state=str(pick(r, "state_pfxrcd", "state", "status", "session_state", default="")) or None,
        ))
        n += 1
    return n


_HANDLERS = {
    "facts": _facts,
    "hostname": _hostname,
    "interfaces": _interfaces,
    "ip_interfaces": _interfaces,
    "lldp": _neighbors,
    "cdp": _neighbors,
    "other_l2": _neighbors,
    "arp": _arp,
    "routes": _routes,
    "vlans": _vlans,
    "mac_table": _mac_table,
    "ospf": _ospf,
    "bgp": _bgp,
}
