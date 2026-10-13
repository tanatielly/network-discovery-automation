"""Parsers da saída JSON do FRR (``vtysh -c "... json"``) em hosts Linux roteadores."""

from __future__ import annotations

import json
from typing import Any

Row = dict[str, object]


def _load(text: str) -> Any:
    start = (text or "").find("{")
    if start < 0:
        return None
    try:
        return json.loads(text[start:])
    except ValueError:
        return None


def frr_bgp_json(text: str) -> list[Row]:
    """``show bgp summary json``: peers por família (``ipv4Unicast``...) ou na raiz (versões antigas)."""
    data = _load(text)
    if not isinstance(data, dict):
        return []
    tables = [v for v in data.values() if isinstance(v, dict) and "peers" in v]
    if "peers" in data:
        tables.append(data)
    rows: list[Row] = []
    seen: set[str] = set()
    for table in tables:
        for peer, info in (table.get("peers") or {}).items():
            if peer in seen or not isinstance(info, dict):
                continue
            seen.add(peer)
            rows.append({"neighbor": peer, "remote_as": info.get("remoteAs"),
                         "state": info.get("state") or info.get("peerState")})
    return rows


def frr_ospf_json(text: str) -> list[Row]:
    """``show ip ospf neighbor json``: ``{"neighbors": {router_id: [ {address, ifaceName, nbrState} ]}}``."""
    data = _load(text)
    if not isinstance(data, dict):
        return []
    rows: list[Row] = []
    for rid, entries in (data.get("neighbors") or {}).items():
        for e in entries if isinstance(entries, list) else [entries]:
            if not isinstance(e, dict):
                continue
            iface = str(e.get("ifaceName") or e.get("interfaceName") or "").split(":")[0] or None
            rows.append({"neighbor_id": rid, "address": e.get("address") or e.get("ifaceAddress"),
                         "interface": iface, "state": e.get("nbrState") or e.get("state")})
    return rows
