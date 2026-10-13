"""Parsers para MikroTik RouterOS (formato ``print terse`` / ``print detail``)."""

from __future__ import annotations

import re

from nettopo.vendors.parsers.generic import parse_kv_colon

Row = dict[str, object]

_KV = re.compile(r'([\w\-.]+)=("(?:[^"\\]|\\.)*"|\S*)')
_REC_START = re.compile(r"^\s*(\d+)\s+(.*)$")


def _head(body: str) -> tuple[str, str | None]:
    """Separa flags (``R``, ``DAc``, ``X``...) e comentário ``;;; texto`` do início do registro."""
    first_kv = _KV.search(body)
    head = body[: first_kv.start()] if first_kv else body
    comment = None
    if ";;;" in head:
        head, _, comment = head.partition(";;;")
        comment = comment.strip() or None
    flags = "".join(t for t in head.split() if re.fullmatch(r"[A-Za-z*+]+", t) and len(t) <= 5)
    return flags, comment


def parse_records(text: str, terse: bool = False) -> list[Row]:
    """Extrai registros ``chave=valor`` + flags de saídas ``print``.

    ``terse=True``: cada linha com ``chave=valor`` é um registro. No RouterOS 7 as linhas de registros
    dinâmicos não trazem índice (ex.: rotas ``DAc``), então o índice não pode ser o delimitador.
    ``terse=False`` (``print detail``): o registro começa na linha com índice e continua nas linhas
    recuadas seguintes.
    """
    records: list[Row] = []
    cur: Row | None = None
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("Flags:", "Columns:")):
            continue
        if stripped.startswith(";;;"):
            if cur is not None and not terse:
                cur["comment"] = stripped[3:].strip()
            continue
        m = _REC_START.match(line)
        if terse:
            if "=" not in line:
                continue
            body = m.group(2) if m else stripped
            flags, comment = _head(body)
            cur = {"_index": m.group(1) if m else None, "_flags": flags}
            if comment:
                cur["comment"] = comment
            records.append(cur)
        elif m:
            body = m.group(2)
            flags, comment = _head(body)
            cur = {"_index": m.group(1), "_flags": flags}
            if comment:
                cur["comment"] = comment
            records.append(cur)
        else:
            body = line
        if cur is None:
            continue
        prefix = ""
        for k, v in _KV.findall(body):
            if k.startswith(".") and prefix:
                k = prefix + k
            elif "." in k:
                prefix = k.split(".", 1)[0]
            cur[k] = v.strip('"')
    return records


# Flags de protocolo de rota: minúsculas no RouterOS 7 (c, s, o, b...), maiúsculas C/S no RouterOS 6.
# "D" maiúsculo é "dinâmico" e "A" é "ativo"; não indicam protocolo.
_ROUTE_FLAGS = [("o", "ospf"), ("b", "bgp"), ("r", "rip"), ("c", "connected"), ("C", "connected"),
                ("s", "static"), ("S", "static"), ("d", "dhcp"), ("v", "vpn"), ("m", "modem")]


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
            for r in parse_records(text, terse=True) if r.get("address")]


def mikrotik_arp(text: str) -> list[Row]:
    return [{"ip_address": r.get("address"), "mac_address": r.get("mac-address"), "interface": r.get("interface")}
            for r in parse_records(text, terse=True) if r.get("address")]


def mikrotik_routes(text: str) -> list[Row]:
    out = []
    for r in parse_records(text, terse=True):
        dst = r.get("dst-address")
        if not dst:
            continue
        flags = str(r.get("_flags", ""))
        proto = next((name for ch, name in _ROUTE_FLAGS if ch in flags), None)
        gw = str(r.get("gateway") or "")
        imm = str(r.get("immediate-gw") or "")
        itf = imm.split("%", 1)[1] if "%" in imm else (gw if gw and not re.match(r"\d", gw) else None)
        out.append({"network": dst, "nexthop_ip": gw if re.match(r"\d", gw) else None,
                    "nexthop_if": itf, "protocol": proto, "vrf": r.get("routing-table") or r.get("vrf")})
    return out


def mikrotik_ospf(text: str) -> list[Row]:
    """``/routing ospf neighbor print detail`` (RouterOS 7)."""
    return [{"address": r.get("address"), "neighbor_id": r.get("router-id"), "state": r.get("state"),
             "interface": r.get("interface")}
            for r in parse_records(text) if r.get("address")]


def mikrotik_bgp(text: str) -> list[Row]:
    """``/routing bgp session print detail`` (RouterOS 7): flag ``E`` = estabelecida."""
    out = []
    for r in parse_records(text):
        peer = r.get("remote.address")
        if not peer:
            continue
        established = "E" in str(r.get("_flags", "")) or str(r.get("established", "")).lower() == "true"
        out.append({"neighbor": str(peer).split("/")[0], "remote_as": r.get("remote.as"),
                    "state": "Established" if established else "Idle"})
    return out


def mikrotik_vlans(text: str) -> list[Row]:
    return [{"vlan_id": r.get("vlan-id"), "name": r.get("name"), "interfaces": [r.get("interface")]}
            for r in parse_records(text, terse=True) if r.get("vlan-id")]
