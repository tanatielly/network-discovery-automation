"""Parsers do Nokia SR Linux para saídas ``| as json`` da CLI (mesmo modelo do JSON-RPC)."""

from __future__ import annotations

import json
from typing import Any

Row = dict[str, object]


def _load(text: str) -> Any:
    start = min((i for i in ((text or "").find("{"), (text or "").find("[")) if i >= 0), default=-1)
    if start < 0:
        return None
    try:
        return json.loads(text[start:])
    except ValueError:
        return None


def _walk(obj: Any):  # noqa: ANN202
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _key(d: dict[str, Any], name: str) -> Any:
    """Busca chave ignorando prefixo de módulo YANG (``srl_nokia-lldp:neighbor``)."""
    for k, v in d.items():
        if str(k).split(":")[-1] == name:
            return v
    return None


def srl_json_lldp(text: str) -> list[Row]:
    """``info from state /system lldp interface * neighbor * | as json``.

    Retorna as linhas no formato esperado pelo normalize (com IP de gerência, que a tabela de
    ``show system lldp neighbor`` não mostra). Saída que não é JSON devolve ``[]`` para o próximo parser.
    """
    data = _load(text)
    if data is None:
        return []
    rows: list[Row] = []
    for node in _walk(data):
        neighbors = _key(node, "neighbor")
        local = _key(node, "name")
        if not isinstance(neighbors, list) or not local:
            continue
        for nb in neighbors:
            if not isinstance(nb, dict):
                continue
            mgmt = None
            for m in _key(nb, "management-address") or []:
                addr = m.get("address") if isinstance(m, dict) else m
                if addr and "." in str(addr):
                    mgmt = addr
                    break
            rows.append({
                "local_interface": local,
                "neighbor_name": _key(nb, "system-name"),
                "neighbor_interface": _key(nb, "port-id"),
                "port_description": _key(nb, "port-description"),
                "chassis_id": _key(nb, "chassis-id"),
                "system_description": _key(nb, "system-description"),
                "mgmt_address": mgmt,
            })
    return rows
