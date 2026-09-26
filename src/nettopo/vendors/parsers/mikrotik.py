"""Parsers para MikroTik RouterOS (formato ``print terse`` / ``print detail``)."""

from __future__ import annotations

import re

from nettopo.vendors.parsers.generic import parse_kv_colon

Row = dict[str, object]

_KV = re.compile(r'([\w\-.]+)=("(?:[^"\\]|\\.)*"|\S*)')
_REC_START = re.compile(r"^\s*(\d+)\s+(.*)$")


def parse_records(text: str) -> list[Row]:
    """Agrupa registros numerados e extrai ``chave=valor`` + flags (ex.: ``R``, ``X``, ``DAC``)."""
    records: list[Row] = []
    cur: Row | None = None
    for line in (text or "").splitlines():
        if not line.strip() or line.lstrip().startswith(("Flags:", "Columns:", ";;;")):
            if line.lstrip().startswith(";;;") and cur is not None:
                cur["comment"] = line.split(";;;", 1)[1].strip()
            continue
        m = _REC_START.match(line)
        body = line
        if m:
            cur = {"_index": m.group(1)}
            records.append(cur)
            body = m.group(2)
            first_kv = _KV.search(body)
            head = body[: first_kv.start()] if first_kv else body
            flags = "".join(t for t in head.split() if re.fullmatch(r"[A-Za-z*+]+", t) and len(t) <= 5)
            cur["_flags"] = flags
        if cur is None:
            continue
        for k, v in _KV.findall(body):
            cur[k] = v.strip('"')
    return records


def mikrotik_identity(text: str) -> list[Row]:
    rows = parse_kv_colon(text)
    return [{"hostname": rows[0].get("name")}] if rows and rows[0].get("name") else []


def mikrotik_facts(text: str) -> list[Row]:
    rows = parse_kv_colon(text)
    if not rows:
        return []
    r = rows[0]
    return [{
        "version": r.get("version"),
        "model": r.get("board_name") or r.get("model"),
        "uptime": r.get("uptime"),
        "serial": r.get("serial_number"),
    }]


def mikrotik_neighbors(text: str) -> list[Row]:
    out = []
    for r in parse_records(text):
        out.append({
            "local_interface": str(r.get("interface", "")).split(",")[0] or None,
            "neighbor_name": r.get("identity"),
            "neighbor_interface": r.get("interface-name"),
            "mgmt_address": r.get("address4") or r.get("address"),
            "platform": (f"{r.get('platform', '')} {r.get('board', '')}".strip() or None),
            "system_description": r.get("system-description"),
            "chassis_id": r.get("mac-address"),
            "capabilities": r.get("system-caps-enabled") or r.get("system-caps"),
            "protocol_name": _discovery_proto(r.get("discovered-by")),
        })
    return out


def _discovery_proto(value: object) -> str:
    v = str(value or "").lower()
    if "lldp" in v:
        return "lldp"
    if "cdp" in v:
        return "cdp"
    return "mndp"


def mikrotik_interfaces(text: str) -> list[Row]:
    out = []
    for r in parse_records(text):
        flags = str(r.get("_flags", ""))
        out.append({
            "interface": r.get("name"),
            "description": r.get("comment"),
            "mac_address": r.get("mac-address"),
            "mtu": r.get("actual-mtu") or r.get("mtu"),
            "type": r.get("type"),
            "link_status": "up" if "R" in flags else "down",
            "admin_state": "down" if "X" in flags else "up",
        })
    return out


def mikrotik_ip_address(text: str) -> list[Row]:
    return [{"interface": r.get("interface"), "ip_address": r.get("address")}
            for r in parse_records(text) if r.get("address")]


def mikrotik_arp(text: str) -> list[Row]:
    return [{"ip_address": r.get("address"), "mac_address": r.get("mac-address"), "interface": r.get("interface")}
            for r in parse_records(text) if r.get("address")]


def mikrotik_routes(text: str) -> list[Row]:
    out = []
    for r in parse_records(text):
        dst = r.get("dst-address")
        if not dst:
            continue
        flags = str(r.get("_flags", ""))
        proto = None
        for ch, name in (("o", "ospf"), ("b", "bgp"), ("r", "rip"), ("c", "connected"), ("s", "static")):
            if ch in flags.lower():
                proto = name
                break
        gw = str(r.get("gateway") or "")
        imm = str(r.get("immediate-gw") or "")
        itf = imm.split("%", 1)[1] if "%" in imm else (gw if gw and not re.match(r"\d", gw) else None)
        out.append({"network": dst, "nexthop_ip": gw if re.match(r"\d", gw) else None,
                    "nexthop_if": itf, "protocol": proto, "vrf": r.get("routing-table") or r.get("vrf")})
    return out


def mikrotik_vlans(text: str) -> list[Row]:
    return [{"vlan_id": r.get("vlan-id"), "name": r.get("name"), "interfaces": [r.get("interface")]}
            for r in parse_records(text) if r.get("vlan-id")]
