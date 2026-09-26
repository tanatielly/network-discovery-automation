"""Converte a topologia em elementos Cytoscape.js (HTML e UI web)."""

from __future__ import annotations

from typing import Any

from nettopo.models import Topology
from nettopo.output.icons import ROLE_COLORS, ROLE_LABELS, TIER_LABELS, all_icons
from nettopo.topology.layout import compute_layout
from nettopo.utils import short_ifname


def _speed_label(mbps: int | None) -> str:
    if not mbps:
        return ""
    return f"{mbps // 1000}G" if mbps >= 1000 else f"{mbps}M"


def to_cytoscape(topo: Topology) -> dict[str, Any]:
    pos = compute_layout(topo)
    icons = all_icons()
    nodes = []
    for d in topo.devices.values():
        x, y = pos.get(d.id, (0.0, 0.0))
        sub = d.mgmt_ip or ""
        nodes.append({
            "data": {
                "id": d.id, "label": f"{d.label}\n{sub}".strip(), "hostname": d.hostname, "ip": d.mgmt_ip,
                "role": d.role, "roleLabel": ROLE_LABELS.get(d.role, d.role), "tier": d.tier,
                "vendor": d.vendor or "", "model": d.model or "", "stub": d.stub, "icon": icons.get(d.role, icons["unknown"]),
                "color": ROLE_COLORS.get(d.role, ROLE_COLORS["unknown"]),
            },
            "position": {"x": x, "y": y},
            "classes": " ".join(c for c in (d.role, "stub" if d.stub else "") if c),
        })
    edges = []
    for lk in topo.links:
        edges.append({
            "data": {
                "id": lk.id, "source": lk.source, "target": lk.target,
                "sourceLabel": short_ifname(lk.source_interface), "targetLabel": short_ifname(lk.target_interface),
                "kind": lk.kind, "protocols": ", ".join(lk.protocols), "subnet": lk.subnet or "",
                "speed": lk.speed_mbps or 0, "speedLabel": _speed_label(lk.speed_mbps), "lag": lk.lag or "",
                "sourceInterface": lk.source_interface or "", "targetInterface": lk.target_interface or "",
            },
            "classes": lk.kind,
        })
    return {
        "elements": {"nodes": nodes, "edges": edges},
        "legend": {"roles": {r: {"label": ROLE_LABELS[r], "color": ROLE_COLORS[r], "icon": icons[r]}
                             for r in ROLE_LABELS}, "tiers": TIER_LABELS},
    }


def device_summaries(topo: Topology) -> dict[str, Any]:
    """Dados completos dos equipamentos para o painel de detalhes."""
    return {did: d.model_dump(mode="json") for did, d in topo.devices.items()}
