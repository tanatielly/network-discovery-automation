"""Layout hierárquico por camadas (usado no HTML e no draw.io)."""

from __future__ import annotations

from collections import defaultdict

from nettopo.models import Topology
from nettopo.topology.roles import TIERS


def compute_layout(topo: Topology, x_gap: float = 190, y_gap: float = 170, max_per_row: int = 14,
                   sweeps: int = 6) -> dict[str, tuple[float, float]]:
    """Distribui os nós em linhas por camada e reduz cruzamentos com heurística de baricentro."""
    rows_by_tier: dict[str, list[str]] = defaultdict(list)
    for d in sorted(topo.devices.values(), key=lambda x: (x.label or "").lower()):
        tier = d.tier if d.tier in TIERS else "endpoint"
        rows_by_tier[tier].append(d.id)

    adj: dict[str, set[str]] = defaultdict(set)
    for lk in topo.links:
        adj[lk.source].add(lk.target)
        adj[lk.target].add(lk.source)

    rows: list[list[str]] = []
    for tier in TIERS:
        nodes = rows_by_tier.get(tier, [])
        for i in range(0, len(nodes), max_per_row):
            rows.append(nodes[i : i + max_per_row])
    if not rows:
        return {}

    def order_pos() -> dict[str, float]:
        pos: dict[str, float] = {}
        for row in rows:
            n = len(row)
            for i, node in enumerate(row):
                pos[node] = i - (n - 1) / 2
        return pos

    for sweep in range(sweeps):
        rng = range(1, len(rows)) if sweep % 2 == 0 else range(len(rows) - 2, -1, -1)
        for r in rng:
            pos = order_pos()
            ref = rows[r - 1] if sweep % 2 == 0 else rows[r + 1]
            ref_set = set(ref)

            def bary(node: str, ref_set: set[str] = ref_set, pos: dict[str, float] = pos) -> float:
                ns = [pos[n] for n in adj[node] if n in ref_set]
                if not ns:
                    ns = [pos[n] for n in adj[node] if n in pos]
                return sum(ns) / len(ns) if ns else pos[node]

            rows[r].sort(key=bary)

    out: dict[str, tuple[float, float]] = {}
    for ri, row in enumerate(rows):
        n = len(row)
        for i, node in enumerate(row):
            out[node] = ((i - (n - 1) / 2) * x_gap, ri * y_gap)
    return out
