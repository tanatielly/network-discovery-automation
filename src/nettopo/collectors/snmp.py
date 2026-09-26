"""Coletor SNMP v1/v2c/v3 (vendor-agnóstico) usando MIBs padrão.

MIBs: SNMPv2-MIB, IF-MIB, IP-MIB, LLDP-MIB, CISCO-CDP-MIB, ENTITY-MIB, OSPF-MIB,
BGP4-MIB, Q-BRIDGE-MIB, BRIDGE-MIB e CISCO-VTP-MIB. Os OIDs são numéricos para
não depender de compilação de MIBs.

A E/S (pysnmp) fica em :class:`SnmpSession`; a interpretação dos dados fica em
:func:`build_device`, uma função pura testável com dados sintéticos.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from nettopo.collectors.base import MethodResult
from nettopo.config import CollectOptions, Credential, Settings
from nettopo.models import ArpEntry, Device, Interface, MacEntry, Neighbor, Route, Vlan
from nettopo.utils import canonical_ifname, mask_to_prefix, normalize_mac, parse_ipv4
from nettopo.vendors.registry import VendorProfile, VendorRegistry

log = logging.getLogger(__name__)

Walk = dict[tuple[int, ...], Any]

SYS = {
    "descr": "1.3.6.1.2.1.1.1.0",
    "object_id": "1.3.6.1.2.1.1.2.0",
    "uptime": "1.3.6.1.2.1.1.3.0",
    "contact": "1.3.6.1.2.1.1.4.0",
    "name": "1.3.6.1.2.1.1.5.0",
    "location": "1.3.6.1.2.1.1.6.0",
}

COLUMNS: dict[str, str] = {
    # IF-MIB
    "ifDescr": "1.3.6.1.2.1.2.2.1.2",
    "ifType": "1.3.6.1.2.1.2.2.1.3",
    "ifMtu": "1.3.6.1.2.1.2.2.1.4",
    "ifSpeed": "1.3.6.1.2.1.2.2.1.5",
    "ifPhysAddress": "1.3.6.1.2.1.2.2.1.6",
    "ifAdminStatus": "1.3.6.1.2.1.2.2.1.7",
    "ifOperStatus": "1.3.6.1.2.1.2.2.1.8",
    "ifName": "1.3.6.1.2.1.31.1.1.1.1",
    "ifHighSpeed": "1.3.6.1.2.1.31.1.1.1.15",
    "ifAlias": "1.3.6.1.2.1.31.1.1.1.18",
    # IP-MIB
    "ipAdEntIfIndex": "1.3.6.1.2.1.4.20.1.2",
    "ipAdEntNetMask": "1.3.6.1.2.1.4.20.1.3",
    "ipNetToMediaPhysAddress": "1.3.6.1.2.1.4.22.1.2",
    "ipCidrRouteIfIndex": "1.3.6.1.2.1.4.24.4.1.5",
    "ipCidrRouteProto": "1.3.6.1.2.1.4.24.4.1.7",
    "ipRouteIfIndex": "1.3.6.1.2.1.4.21.1.2",
    "ipRouteNextHop": "1.3.6.1.2.1.4.21.1.7",
    "ipRouteProto": "1.3.6.1.2.1.4.21.1.9",
    "ipRouteMask": "1.3.6.1.2.1.4.21.1.11",
    # LLDP-MIB
    "lldpLocChassisId": "1.0.8802.1.1.2.1.3.2",
    "lldpLocPortIdSubtype": "1.0.8802.1.1.2.1.3.7.1.2",
    "lldpLocPortId": "1.0.8802.1.1.2.1.3.7.1.3",
    "lldpLocPortDesc": "1.0.8802.1.1.2.1.3.7.1.4",
    "lldpRemChassisIdSubtype": "1.0.8802.1.1.2.1.4.1.1.4",
    "lldpRemChassisId": "1.0.8802.1.1.2.1.4.1.1.5",
    "lldpRemPortIdSubtype": "1.0.8802.1.1.2.1.4.1.1.6",
    "lldpRemPortId": "1.0.8802.1.1.2.1.4.1.1.7",
    "lldpRemPortDesc": "1.0.8802.1.1.2.1.4.1.1.8",
    "lldpRemSysName": "1.0.8802.1.1.2.1.4.1.1.9",
    "lldpRemSysDesc": "1.0.8802.1.1.2.1.4.1.1.10",
    "lldpRemSysCapEnabled": "1.0.8802.1.1.2.1.4.1.1.12",
    "lldpRemManAddrIfSubtype": "1.0.8802.1.1.2.1.4.2.1.3",
    # CISCO-CDP-MIB
    "cdpCacheAddressType": "1.3.6.1.4.1.9.9.23.1.2.1.1.3",
    "cdpCacheAddress": "1.3.6.1.4.1.9.9.23.1.2.1.1.4",
    "cdpCacheVersion": "1.3.6.1.4.1.9.9.23.1.2.1.1.5",
    "cdpCacheDeviceId": "1.3.6.1.4.1.9.9.23.1.2.1.1.6",
    "cdpCacheDevicePort": "1.3.6.1.4.1.9.9.23.1.2.1.1.7",
    "cdpCachePlatform": "1.3.6.1.4.1.9.9.23.1.2.1.1.8",
    "cdpCacheCapabilities": "1.3.6.1.4.1.9.9.23.1.2.1.1.9",
    # ENTITY-MIB
    "entPhysicalDescr": "1.3.6.1.2.1.47.1.1.1.1.2",
    "entPhysicalClass": "1.3.6.1.2.1.47.1.1.1.1.5",
    "entPhysicalSoftwareRev": "1.3.6.1.2.1.47.1.1.1.1.10",
    "entPhysicalSerialNum": "1.3.6.1.2.1.47.1.1.1.1.11",
    "entPhysicalModelName": "1.3.6.1.2.1.47.1.1.1.1.13",
    # OSPF-MIB / BGP4-MIB
    "ospfNbrRtrId": "1.3.6.1.2.1.14.10.1.3",
    "ospfNbrState": "1.3.6.1.2.1.14.10.1.6",
    "bgpPeerState": "1.3.6.1.2.1.15.3.1.2",
    "bgpPeerRemoteAs": "1.3.6.1.2.1.15.3.1.9",
    # VLANs
    "dot1qVlanStaticName": "1.3.6.1.2.1.17.7.1.4.3.1.1",
    "vtpVlanName": "1.3.6.1.4.1.9.9.46.1.3.1.1.4",
    # Tabela MAC
    "dot1qTpFdbPort": "1.3.6.1.2.1.17.7.1.2.2.1.2",
    "dot1dBasePortIfIndex": "1.3.6.1.2.1.17.1.4.1.2",
    "dot1dTpFdbPort": "1.3.6.1.2.1.17.4.3.1.2",
}

GROUPS: dict[str, list[str]] = {
    "interfaces": ["ifDescr", "ifType", "ifMtu", "ifSpeed", "ifPhysAddress", "ifAdminStatus", "ifOperStatus",
                   "ifName", "ifHighSpeed", "ifAlias", "ipAdEntIfIndex", "ipAdEntNetMask"],
    "entity": ["entPhysicalClass", "entPhysicalSerialNum", "entPhysicalModelName", "entPhysicalSoftwareRev",
               "entPhysicalDescr"],
    "lldp": ["lldpLocChassisId", "lldpLocPortIdSubtype", "lldpLocPortId", "lldpLocPortDesc",
             "lldpRemChassisIdSubtype", "lldpRemChassisId", "lldpRemPortIdSubtype", "lldpRemPortId",
             "lldpRemPortDesc", "lldpRemSysName", "lldpRemSysDesc", "lldpRemSysCapEnabled",
             "lldpRemManAddrIfSubtype"],
    "cdp": ["cdpCacheAddressType", "cdpCacheAddress", "cdpCacheVersion", "cdpCacheDeviceId",
            "cdpCacheDevicePort", "cdpCachePlatform", "cdpCacheCapabilities"],
    "arp": ["ipNetToMediaPhysAddress"],
    "routes": ["ipCidrRouteIfIndex", "ipCidrRouteProto"],
    "routes_legacy": ["ipRouteIfIndex", "ipRouteNextHop", "ipRouteProto", "ipRouteMask"],
    "routing_neighbors": ["ospfNbrRtrId", "ospfNbrState", "bgpPeerState", "bgpPeerRemoteAs"],
    "vlans": ["dot1qVlanStaticName", "vtpVlanName"],
    "mac_table": ["dot1qTpFdbPort", "dot1dBasePortIfIndex", "dot1dTpFdbPort"],
}

ROUTE_PROTO = {1: "other", 2: "connected", 3: "static", 4: "icmp", 5: "egp", 8: "rip", 9: "isis",
               11: "igrp", 13: "ospf", 14: "bgp", 16: "eigrp"}
OSPF_STATE = {1: "down", 2: "attempt", 3: "init", 4: "2way", 5: "exstart", 6: "exchange", 7: "loading",
              8: "full"}
BGP_STATE = {1: "idle", 2: "connect", 3: "active", 4: "opensent", 5: "openconfirm", 6: "established"}
LLDP_CAPS = ["other", "repeater", "bridge", "wlan", "router", "telephone", "docsis", "station"]
CDP_CAPS = {0x01: "router", 0x02: "bridge", 0x04: "bridge", 0x08: "bridge", 0x10: "station",
            0x40: "repeater", 0x80: "telephone"}


# --------------------------------------------------------------------------- conversões

def to_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value).rstrip(b"\x00")
        try:
            s = raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.hex(":")
        if s and all(c.isprintable() or c in "\r\n\t" for c in s):
            return s.strip()
        return raw.hex(":") if raw else None
    return str(value).strip()


def id_value(subtype: int | None, value: Any) -> str | None:
    """Interpreta LldpChassisId/LldpPortId conforme o subtipo."""
    if isinstance(value, (bytes, bytearray)):
        if subtype in (4, 3) or (len(value) == 6 and not to_text(value)):
            mac = normalize_mac(bytes(value)) if len(value) == 6 else None
            if mac:
                return mac
        if subtype == 5 and len(value) in (5, 17):  # networkAddress: 1 byte de família + IP
            ip = parse_ipv4(bytes(value[1:5])) if len(value) == 5 else None
            if ip:
                return ip
    txt = to_text(value)
    if txt and len(txt) == 17 and normalize_mac(txt):
        return normalize_mac(txt)
    return txt


def bits_to_caps(value: Any) -> list[str]:
    if not isinstance(value, (bytes, bytearray)) or not value:
        return []
    out = []
    b = value[0]
    for i, name in enumerate(LLDP_CAPS):
        if b & (0x80 >> i):
            out.append(name)
    return out


def cdp_caps(value: Any) -> list[str]:
    if isinstance(value, (bytes, bytearray)):
        num = int.from_bytes(bytes(value), "big") if value else 0
    else:
        try:
            num = int(value)
        except (TypeError, ValueError):
            return []
    out: list[str] = []
    for bit, name in CDP_CAPS.items():
        if num & bit and name not in out:
            out.append(name)
    return out


def _ip_from_index(idx: tuple[int, ...]) -> str | None:
    if len(idx) < 4:
        return None
    return ".".join(str(x) for x in idx[:4])


def _format_uptime(ticks: Any) -> str | None:
    try:
        secs = int(ticks) // 100
    except (TypeError, ValueError):
        return None
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    return f"{d}d {h}h {m}m"


# --------------------------------------------------------------------------- montagem

def build_device(target: str, system: dict[str, Any], walks: dict[str, Walk],
                 opts: CollectOptions | None = None, registry: VendorRegistry | None = None,
                 profile: VendorProfile | None = None) -> Device:
    """Transforma os dados crus do SNMP em :class:`Device`."""
    opts = opts or CollectOptions()
    w = lambda name: walks.get(name) or {}  # noqa: E731

    descr = to_text(system.get("descr"))
    oid = to_text(system.get("object_id"))
    if registry and not profile:
        profile = registry.match_snmp(oid, descr)
    dev = Device(
        hostname=to_text(system.get("name")) or None,
        mgmt_ip=target,
        sys_description=descr,
        sys_object_id=oid,
        location=to_text(system.get("location")) or None,
        contact=to_text(system.get("contact")) or None,
        uptime=_format_uptime(system.get("uptime")),
        vendor=profile.vendor if profile else None,
        os=profile.os if profile else None,
        profile=profile.id if profile else None,
        collected_via=["snmp"],
    )
    if registry:
        dev.os_version = registry.extract_version(profile, descr)

    # ENTITY-MIB: primeiro chassis
    classes = w("entPhysicalClass")
    chassis_idx = sorted(i for i, v in classes.items() if _int(v) == 3)
    for idx in chassis_idx:
        serial = to_text(w("entPhysicalSerialNum").get(idx))
        model = to_text(w("entPhysicalModelName").get(idx)) or to_text(w("entPhysicalDescr").get(idx))
        if serial or model:
            dev.serial = dev.serial or serial or None
            dev.model = dev.model or model or None
            dev.os_version = dev.os_version or to_text(w("entPhysicalSoftwareRev").get(idx)) or None
            break

    # Interfaces
    ifnames: dict[int, str] = {}
    for idx, v in w("ifDescr").items():
        ifindex = idx[0]
        name = to_text(w("ifName").get(idx)) or to_text(v) or f"ifIndex{ifindex}"
        ifnames[ifindex] = canonical_ifname(name) or name
        if not opts.interfaces:
            continue
        high = _int(w("ifHighSpeed").get(idx))
        speed = high if high else (_int(w("ifSpeed").get(idx)) or 0) // 1_000_000 or None
        dev.interfaces.append(Interface(
            name=ifnames[ifindex],
            description=to_text(w("ifAlias").get(idx)) or None,
            mac=normalize_mac(w("ifPhysAddress").get(idx)),
            mtu=_int(w("ifMtu").get(idx)),
            speed_mbps=speed,
            admin_up=_int(w("ifAdminStatus").get(idx)) == 1 if idx in w("ifAdminStatus") else None,
            oper_up=_int(w("ifOperStatus").get(idx)) == 1 if idx in w("ifOperStatus") else None,
            if_index=ifindex,
            if_type=str(_int(w("ifType").get(idx))) if idx in w("ifType") else None,
        ))
    by_index = {i.if_index: i for i in dev.interfaces if i.if_index is not None}

    for idx, ifindex in w("ipAdEntIfIndex").items():
        ip = _ip_from_index(idx)
        itf = by_index.get(_int(ifindex))
        if not ip or itf is None:
            continue
        mask = w("ipAdEntNetMask").get(idx)
        pfx = mask_to_prefix(parse_ipv4(mask)) if mask is not None else None
        itf.ipv4.append(f"{ip}/{pfx}" if pfx is not None else ip)

    # LLDP
    loc_chassis = w("lldpLocChassisId")
    if loc_chassis:
        dev.chassis_id = id_value(4, next(iter(loc_chassis.values())))
    loc_port_name: dict[int, str] = {}
    for idx, pid in w("lldpLocPortId").items():
        port = idx[0]
        subtype = _int(w("lldpLocPortIdSubtype").get(idx))
        if subtype in (5, 7, 1):
            name = to_text(pid)
        elif port in ifnames:
            name = ifnames[port]
        else:
            name = to_text(w("lldpLocPortDesc").get(idx)) or to_text(pid)
        if name:
            loc_port_name[port] = canonical_ifname(name) or name
    mgmt_by_rem: dict[tuple[int, int, int], str] = {}
    for idx in w("lldpRemManAddrIfSubtype"):
        if len(idx) >= 9 and idx[3] == 1 and idx[4] == 4:
            mgmt_by_rem.setdefault(idx[:3], ".".join(str(x) for x in idx[5:9]))
    rem_keys = set(w("lldpRemSysName")) | set(w("lldpRemChassisId")) | set(w("lldpRemPortId"))
    for idx in sorted(rem_keys):
        if len(idx) < 3:
            continue
        local_port = idx[1]
        port_sub = _int(w("lldpRemPortIdSubtype").get(idx))
        port = id_value(port_sub, w("lldpRemPortId").get(idx))
        port_desc = to_text(w("lldpRemPortDesc").get(idx))
        if port and normalize_mac(port) and port_desc:
            port = port_desc
        dev.neighbors.append(Neighbor(
            protocol="lldp",
            local_interface=loc_port_name.get(local_port) or ifnames.get(local_port),
            remote_hostname=to_text(w("lldpRemSysName").get(idx)) or None,
            remote_interface=port,
            remote_mgmt_ip=mgmt_by_rem.get(idx[:3]),
            remote_description=to_text(w("lldpRemSysDesc").get(idx)) or None,
            remote_platform=(to_text(w("lldpRemSysDesc").get(idx)) or "")[:120] or None,
            remote_chassis_id=id_value(_int(w("lldpRemChassisIdSubtype").get(idx)),
                                       w("lldpRemChassisId").get(idx)),
            remote_capabilities=bits_to_caps(w("lldpRemSysCapEnabled").get(idx)),
        ))

    # CDP
    for idx, dev_id in w("cdpCacheDeviceId").items():
        addr = w("cdpCacheAddress").get(idx)
        mgmt = parse_ipv4(bytes(addr)) if isinstance(addr, (bytes, bytearray)) and len(addr) == 4 else None
        dev.neighbors.append(Neighbor(
            protocol="cdp",
            local_interface=ifnames.get(idx[0]),
            remote_hostname=to_text(dev_id),
            remote_interface=to_text(w("cdpCacheDevicePort").get(idx)),
            remote_mgmt_ip=mgmt,
            remote_platform=to_text(w("cdpCachePlatform").get(idx)),
            remote_description=(to_text(w("cdpCacheVersion").get(idx)) or "")[:300] or None,
            remote_capabilities=cdp_caps(w("cdpCacheCapabilities").get(idx)),
        ))

    # ARP
    for idx, mac in w("ipNetToMediaPhysAddress").items():
        ip = _ip_from_index(idx[1:])
        if ip:
            dev.arp.append(ArpEntry(ip=ip, mac=normalize_mac(mac), interface=ifnames.get(idx[0])))

    # Rotas
    if w("ipCidrRouteIfIndex"):
        for idx, ifindex in list(w("ipCidrRouteIfIndex").items())[: opts.route_limit]:
            if len(idx) < 13:
                continue
            dest, mask, nh = _ip_from_index(idx[0:4]), _ip_from_index(idx[4:8]), _ip_from_index(idx[9:13])
            pfx = mask_to_prefix(mask)
            dev.routes.append(Route(
                prefix=f"{dest}/{pfx}", next_hop=nh if nh != "0.0.0.0" else None,
                interface=ifnames.get(_int(ifindex) or -1),
                protocol=ROUTE_PROTO.get(_int(w("ipCidrRouteProto").get(idx)) or 0),
            ))
    else:
        for idx, nh in list(w("ipRouteNextHop").items())[: opts.route_limit]:
            dest = _ip_from_index(idx)
            pfx = mask_to_prefix(parse_ipv4(w("ipRouteMask").get(idx)))
            nh_ip = parse_ipv4(nh)
            dev.routes.append(Route(
                prefix=f"{dest}/{pfx if pfx is not None else 32}",
                next_hop=nh_ip if nh_ip != "0.0.0.0" else None,
                interface=ifnames.get(_int(w("ipRouteIfIndex").get(idx)) or -1),
                protocol=ROUTE_PROTO.get(_int(w("ipRouteProto").get(idx)) or 0),
            ))

    # Vizinhos de roteamento
    for idx, rid in w("ospfNbrRtrId").items():
        addr = _ip_from_index(idx)
        dev.neighbors.append(Neighbor(protocol="ospf", remote_mgmt_ip=addr, remote_chassis_id=parse_ipv4(rid),
                                      state=OSPF_STATE.get(_int(w("ospfNbrState").get(idx)) or 0)))
    for idx, state in w("bgpPeerState").items():
        peer = _ip_from_index(idx)
        dev.neighbors.append(Neighbor(protocol="bgp", remote_mgmt_ip=peer,
                                      remote_asn=_int(w("bgpPeerRemoteAs").get(idx)),
                                      state=BGP_STATE.get(_int(state) or 0)))

    # VLANs
    for idx, name in w("dot1qVlanStaticName").items():
        dev.vlans.append(Vlan(id=idx[-1], name=to_text(name)))
    if not dev.vlans:
        for idx, name in w("vtpVlanName").items():
            vid = idx[-1]
            if vid < 1002 or vid > 1005:  # ignora VLANs legadas FDDI/TR
                dev.vlans.append(Vlan(id=vid, name=to_text(name)))

    # Tabela MAC
    bridge_if = {idx[0]: _int(v) for idx, v in w("dot1dBasePortIfIndex").items()}
    for idx, bport in w("dot1qTpFdbPort").items():
        if len(idx) >= 7:
            mac = normalize_mac(bytes(idx[1:7]))
            ifidx = bridge_if.get(_int(bport) or -1)
            if mac:
                dev.mac_table.append(MacEntry(mac=mac, vlan=idx[0], interface=ifnames.get(ifidx or -1)))
    if not dev.mac_table:
        for idx, bport in w("dot1dTpFdbPort").items():
            if len(idx) >= 6:
                mac = normalize_mac(bytes(idx[:6]))
                ifidx = bridge_if.get(_int(bport) or -1)
                if mac:
                    dev.mac_table.append(MacEntry(mac=mac, interface=ifnames.get(ifidx or -1)))
    return dev


def _int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        if isinstance(value, (bytes, bytearray)) and value:
            return int.from_bytes(bytes(value), "big")
        return None


# --------------------------------------------------------------------------- E/S pysnmp

def _py(value: Any) -> Any:
    """Converte tipos pysnmp para tipos Python."""
    cls = value.__class__.__name__
    if cls in ("NoSuchObject", "NoSuchInstance", "EndOfMibView", "Null"):
        return None
    if cls in ("ObjectIdentifier", "ObjectIdentity", "ObjectName"):
        return str(value)
    if hasattr(value, "asOctets"):
        return bytes(value.asOctets())
    try:
        return int(value)
    except (TypeError, ValueError):
        return str(value.prettyPrint()) if hasattr(value, "prettyPrint") else str(value)


_AUTH = {
    "md5": "usmHMACMD5AuthProtocol", "sha": "usmHMACSHAAuthProtocol", "sha1": "usmHMACSHAAuthProtocol",
    "sha224": "usmHMAC128SHA224AuthProtocol", "sha256": "usmHMAC192SHA256AuthProtocol",
    "sha384": "usmHMAC256SHA384AuthProtocol", "sha512": "usmHMAC384SHA512AuthProtocol",
}
_PRIV = {
    "des": "usmDESPrivProtocol", "3des": "usm3DESEDEPrivProtocol", "aes": "usmAesCfb128Protocol",
    "aes128": "usmAesCfb128Protocol", "aes192": "usmAesCfb192Protocol", "aes256": "usmAesCfb256Protocol",
}


def new_engine() -> Any:
    """Cria um SnmpEngine (custa ~1 s de CPU: compartilhe entre sessões)."""
    from pysnmp.hlapi.v3arch import asyncio as hl

    return hl.SnmpEngine()


def close_engine(engine: Any) -> None:
    closer = getattr(engine, "close_dispatcher", None) or getattr(engine, "closeDispatcher", None)
    try:
        if closer:
            closer()
    except Exception:  # pragma: no cover
        pass


class SnmpSession:
    def __init__(self, target: str, cred: Credential, timeout: int = 5, retries: int = 1, engine: Any = None):
        self.target = target
        self.cred = cred
        self.timeout = timeout
        self.retries = retries
        self._hl: Any = None
        self._engine: Any = engine
        self._own_engine = engine is None
        self._transport: Any = None
        self._auth: Any = None

    async def open(self) -> None:
        from pysnmp.hlapi.v3arch import asyncio as hl

        self._hl = hl
        if self._engine is None:
            self._engine = new_engine()
        self._transport = await hl.UdpTransportTarget.create(
            (self.target, self.cred.port or 161), timeout=self.timeout, retries=self.retries)
        c = self.cred
        if c.version == "3":
            auth_key = c.secret("auth_key")
            priv_key = c.secret("priv_key")
            kwargs: dict[str, Any] = {}
            if auth_key:
                kwargs["authKey"] = auth_key
                kwargs["authProtocol"] = getattr(hl, _AUTH.get((c.auth_protocol or "sha").lower(),
                                                               "usmHMACSHAAuthProtocol"))
            if priv_key:
                kwargs["privKey"] = priv_key
                kwargs["privProtocol"] = getattr(hl, _PRIV.get((c.priv_protocol or "aes").lower(),
                                                               "usmAesCfb128Protocol"))
            self._auth = hl.UsmUserData(c.username or "", **kwargs)
        else:
            self._auth = hl.CommunityData(c.secret("community") or "public",
                                          mpModel=0 if c.version == "1" else 1)

    def _context(self) -> Any:
        return self._hl.ContextData(contextName=self.cred.context or "")

    async def get(self, oids: dict[str, str]) -> dict[str, Any]:
        hl = self._hl
        names = list(oids)
        err, status, _, binds = await hl.get_cmd(
            self._engine, self._auth, self._transport, self._context(),
            *[hl.ObjectType(hl.ObjectIdentity(oids[n])) for n in names], lookupMib=False)
        if err:
            raise TimeoutError(str(err))
        if status:
            raise RuntimeError(status.prettyPrint())
        return {n: _py(vb[1]) for n, vb in zip(names, binds, strict=False)}

    async def walk(self, oid: str, limit: int = 20000) -> Walk:
        hl = self._hl
        base = tuple(int(x) for x in oid.split("."))
        out: Walk = {}
        if self.cred.version == "1":
            gen = hl.walk_cmd(self._engine, self._auth, self._transport, self._context(),
                              hl.ObjectType(hl.ObjectIdentity(oid)), lexicographicMode=False, lookupMib=False)
        else:
            gen = hl.bulk_walk_cmd(self._engine, self._auth, self._transport, self._context(), 0, 25,
                                   hl.ObjectType(hl.ObjectIdentity(oid)), lexicographicMode=False, lookupMib=False)
        async for err, status, _, binds in gen:
            if err or status:
                break
            for name, value in binds:
                t = tuple(name)
                if t[: len(base)] != base:
                    return out
                v = _py(value)
                if v is not None:
                    out[t[len(base):]] = v
            if len(out) >= limit:
                break
        return out

    def close(self) -> None:
        if self._engine is not None and self._own_engine:
            close_engine(self._engine)


class SnmpCollector:
    name = "snmp"

    def __init__(self, settings: Settings, registry: VendorRegistry):
        self.settings = settings
        self.registry = registry
        self._engine: Any = None

    def engine(self) -> Any:
        """Engine único por coletor (evita recriar a cada equipamento)."""
        if self._engine is None:
            self._engine = new_engine()
        return self._engine

    def close(self) -> None:
        if self._engine is not None:
            close_engine(self._engine)
            self._engine = None

    async def probe(self, target: str, credentials: list[Credential]) -> tuple[Credential, dict[str, Any]] | None:
        """Testa as credenciais SNMP e retorna a primeira que responde + grupo system."""
        for cred in credentials:
            sess = SnmpSession(target, cred, timeout=min(self.settings.timeout, 5),
                               retries=self.settings.snmp_retries, engine=self.engine())
            try:
                await sess.open()
                system = await sess.get(SYS)
                if system.get("descr") is not None or system.get("name") is not None:
                    return cred, system
            except Exception as exc:
                log.debug("SNMP %s via %s falhou: %s", target, cred.display, exc)
            finally:
                sess.close()
        return None

    async def collect(self, target: str, profile: VendorProfile | None, credentials: list[Credential],
                      system: dict[str, Any] | None = None) -> MethodResult:
        res = MethodResult(method=self.name)
        if not credentials:
            res.errors.append("snmp: nenhuma credencial")
            return res
        if system is None:
            probed = await self.probe(target, credentials)
            if not probed:
                res.errors.append("snmp: sem resposta/credencial inválida")
                return res
            cred, system = probed
        else:
            cred = credentials[0]
        opts = self.settings.collect
        groups = ["interfaces", "entity", "lldp", "cdp"]
        if opts.arp:
            groups.append("arp")
        if opts.routes:
            groups.append("routes")
        if opts.routing_neighbors:
            groups.append("routing_neighbors")
        if opts.vlans:
            groups.append("vlans")
        if opts.mac_table:
            groups.append("mac_table")
        columns = [c for g in groups for c in GROUPS[g]]
        sess = SnmpSession(target, cred, timeout=self.settings.timeout, retries=self.settings.snmp_retries,
                           engine=self.engine())
        walks: dict[str, Walk] = {}
        try:
            await sess.open()
            sem = asyncio.Semaphore(4)

            async def one(col: str) -> None:
                async with sem:
                    try:
                        walks[col] = await sess.walk(COLUMNS[col])
                    except Exception as exc:  # coluna não suportada
                        log.debug("walk %s em %s: %s", col, target, exc)

            await asyncio.gather(*(one(c) for c in columns))
            if opts.routes and not walks.get("ipCidrRouteIfIndex"):
                await asyncio.gather(*(one(c) for c in GROUPS["routes_legacy"]))
        finally:
            sess.close()
        res.device = build_device(target, system, walks, opts, self.registry, profile)
        res.credential = cred
        return res
