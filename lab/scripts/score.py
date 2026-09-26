"""Compara cada descoberta com o gabarito (``lab/ground_truth.yaml``) e gera métricas objetivas.

Uso: ``python score.py lab-results``  -> ``lab-results/metrics.json`` e ``lab-results/summary.md``.
Roda no CI e também localmente sobre os artefatos baixados.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

LAB_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_DIR.parent / "src"))

from nettopo.models import Topology  # noqa: E402
from nettopo.utils import ifname_key, short_hostname  # noqa: E402


def load_truth() -> dict[str, Any]:
    return yaml.safe_load((LAB_DIR / "ground_truth.yaml").read_text(encoding="utf-8"))


def map_devices(topo: Topology, truth: dict[str, Any]) -> dict[str, str]:
    """id do NetTopo -> nome no gabarito (por hostname; senão pelo IP de gerência)."""
    by_ip = {v["mgmt_ip"]: k for k, v in truth["nodes"].items()}
    out: dict[str, str] = {}
    for d in topo.devices.values():
        host = short_hostname(d.hostname)
        if host in truth["nodes"]:
            out[d.id] = host
        elif d.mgmt_ip in by_ip:
            out[d.id] = by_ip[d.mgmt_ip]
    return out


def score(topo: Topology, truth: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    mapping = map_devices(topo, truth)
    nodes = truth["nodes"]
    collectable = {n for n, v in nodes.items() if v["collectable"]}
    found_collected = {mapping[d.id] for d in topo.devices.values() if d.id in mapping and not d.stub}
    found_any = set(mapping.values())
    unmapped = [d.label for d in topo.devices.values() if d.id not in mapping]
    duplicates = [n for n, c in Counter(mapping.values()).items() if c > 1]

    vendor_ok = role_ok = 0
    per_node: dict[str, Any] = {}
    for d in topo.devices.values():
        name = mapping.get(d.id)
        if not name:
            continue
        exp = nodes[name]
        v_ok = (d.vendor or "").lower().startswith(exp["vendor"].lower())
        r_ok = d.role in exp["roles"]
        if not d.stub:
            vendor_ok += v_ok
            role_ok += r_ok
        per_node[name] = {"collected": not d.stub, "vendor": d.vendor, "vendor_ok": v_ok, "role": d.role,
                          "role_ok": r_ok, "tier": d.tier, "via": d.collected_via, "profile": d.profile,
                          "interfaces": len(d.interfaces), "neighbors": len(d.neighbors),
                          "errors": d.errors[:5]}

    truth_links = {frozenset(((a, ifname_key(ai)), (b, ifname_key(bi)))) for a, ai, b, bi in truth["links"]}
    truth_pairs = {frozenset((a, b)) for a, _, b, _ in truth["links"]}
    phys = [lk for lk in topo.links if lk.kind == "physical"]
    pair_hits, exact_hits, false_links = set(), set(), []
    for lk in phys:
        a, b = mapping.get(lk.source), mapping.get(lk.target)
        if not a or not b or frozenset((a, b)) not in truth_pairs:
            false_links.append(f"{a or lk.source}:{lk.source_interface} <-> {b or lk.target}:{lk.target_interface}")
            continue
        pair_hits.add(frozenset((a, b)))
        key = frozenset(((a, ifname_key(lk.source_interface)), (b, ifname_key(lk.target_interface))))
        if key in truth_links:
            exact_hits.add(key)
    missing_links = [f"{a}:{ai} <-> {b}:{bi}" for a, ai, b, bi in truth["links"]
                     if frozenset((a, b)) not in pair_hits]
    routing = []
    for a, b, proto in truth.get("routing", []):
        ok = any(proto in lk.protocols and {mapping.get(lk.source), mapping.get(lk.target)} == {a, b}
                 for lk in topo.links)
        routing.append({"adjacency": f"{a} <-> {b} ({proto})", "found": ok})

    done = [e for e in events if e.get("type") == "device_done"]
    collected_per_host = Counter(short_hostname(e.get("hostname")) or e.get("target") for e in done)
    n_links = len(truth["links"])
    return {
        "nodes_expected_collected": len(collectable),
        "nodes_collected": len(found_collected & collectable),
        "node_recall": round(len(found_collected & collectable) / len(collectable), 3),
        "nodes_seen_including_stubs": len(found_any),
        "stub_expected_ok": all((not per_node.get(n, {}).get("collected", True)) and n in found_any
                                for n, v in nodes.items() if not v["collectable"]),
        "unexpected_nodes": unmapped,
        "duplicate_nodes": duplicates,
        "vendor_accuracy": round(vendor_ok / max(1, len(found_collected)), 3),
        "role_accuracy": round(role_ok / max(1, len(found_collected)), 3),
        "links_expected": n_links,
        "links_found": len(pair_hits),
        "link_recall": round(len(pair_hits) / n_links, 3),
        "link_precision": round(len(pair_hits) / max(1, len(pair_hits) + len(false_links)), 3),
        "interface_accuracy": round(len(exact_hits) / max(1, len(pair_hits)), 3),
        "missing_links": missing_links,
        "false_links": false_links,
        "routing_adjacencies": routing,
        "collections": len(done),
        "repeat_collections": {h: c for h, c in collected_per_host.items() if c > 1},
        "failed_targets": topo.meta.failed_targets,
        "per_node": per_node,
    }


def main() -> None:
    results = Path(sys.argv[1] if len(sys.argv) > 1 else "lab-results")
    truth = load_truth()
    metrics: dict[str, Any] = {}
    for d in sorted((results / "scenarios").iterdir()):
        topo_file = d / "topology.json"
        if not d.is_dir() or not topo_file.exists():
            continue
        timing = json.loads((d / "timing.json").read_text(encoding="utf-8")) if (d / "timing.json").exists() else {}
        events = [json.loads(ln) for ln in (d / "events.jsonl").read_text(encoding="utf-8").splitlines()
                  if ln.strip()] if (d / "events.jsonl").exists() else []
        m = score(Topology.load(str(topo_file)), truth, events)
        m.update({"title": timing.get("title", d.name), "status": timing.get("status"),
                  "duration_s": timing.get("duration_s")})
        metrics[d.name] = m
    (results / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = ["# Simulação NetTopo — resultados", "",
             "| Cenário | Status | Tempo (s) | Nós coletados | Links | Interfaces corretas | Fabricante | Papel | Coletas repetidas |",
             "|---|---|---|---|---|---|---|---|---|"]
    for sid, m in metrics.items():
        lines.append(
            f"| {sid} | {m['status']} | {m['duration_s']} | {m['nodes_collected']}/{m['nodes_expected_collected']} "
            f"| {m['links_found']}/{m['links_expected']} | {m['interface_accuracy']:.0%} | {m['vendor_accuracy']:.0%} "
            f"| {m['role_accuracy']:.0%} | {sum(m['repeat_collections'].values())} |")
    lines += ["", "Detalhes por cenário em `metrics.json`."]
    (results / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
