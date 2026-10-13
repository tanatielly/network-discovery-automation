"""Compara cada descoberta com o gabarito (``lab/ground_truth.yaml``) e conta erros.

Uso: ``python score.py <resultados> [--strict]`` -> ``metrics.json`` e ``summary.md``.
Com ``--strict`` o processo termina com código 1 se qualquer cenário tiver erro (usado no CI).
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


def expectation(truth: dict[str, Any], sid: str) -> dict[str, Any]:
    scen = truth.get("scenarios") or {}
    exp = dict(scen.get("padrao") or {"coletados": "todos", "nao_coletados": [], "links": "todos",
                                      "roteamento": "todos"})
    exp.update(scen.get(sid) or {})
    return exp


def _nodes(spec: Any, truth: dict[str, Any]) -> set[str]:
    collectable = {n for n, v in truth["nodes"].items() if v["collectable"]}
    if spec == "todos":
        return collectable
    if isinstance(spec, dict) and "todos_exceto" in spec:
        return collectable - set(spec["todos_exceto"])
    return set(spec or [])


def _links(spec: Any, truth: dict[str, Any]) -> list[list[str]]:
    all_links = truth["links"]
    if spec == "todos":
        return list(all_links)
    if isinstance(spec, dict) and "todos_exceto" in spec:
        return [lk for i, lk in enumerate(all_links) if i not in set(spec["todos_exceto"])]
    return [all_links[i] for i in spec or []]


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


def signature(topo: Topology) -> dict[str, Any]:
    mapping = {d.id: short_hostname(d.hostname) or d.id for d in topo.devices.values()}
    links = sorted(sorted([f"{mapping[lk.source]}:{ifname_key(lk.source_interface)}",
                           f"{mapping[lk.target]}:{ifname_key(lk.target_interface)}"]) + [lk.kind]
                   for lk in topo.links)
    return {"coletados": sorted(mapping[d.id] for d in topo.devices.values() if not d.stub), "links": links}


def score(sid: str, topo: Topology, truth: dict[str, Any], timing: dict[str, Any], events: list[dict[str, Any]],
          results: Path) -> dict[str, Any]:
    exp = expectation(truth, sid)
    errors: list[str] = []
    mapping = map_devices(topo, truth)
    nodes = truth["nodes"]
    by_name: dict[str, Any] = {}
    for d in topo.devices.values():
        if d.id in mapping:
            if mapping[d.id] in by_name:
                errors.append(f"equipamento duplicado no grafo: {mapping[d.id]}")
            by_name[mapping[d.id]] = d

    want_collected = _nodes(exp.get("coletados", "todos"), truth)
    want_stub = set(exp.get("nao_coletados") or [])
    collected = {n for n, d in by_name.items() if not d.stub}
    for n in sorted(want_collected - collected):
        d = by_name.get(n)
        why = (d.extra.get("motivo") if d else None) or "não aparece no grafo"
        errors.append(f"deveria ser coletado: {n} ({str(why)[:160]})")
    for n in sorted(collected - want_collected):
        errors.append(f"não deveria ser coletado: {n}")
    for n in sorted(want_stub):
        d = by_name.get(n)
        if d is None:
            errors.append(f"deveria aparecer como não coletado: {n}")
        elif not d.stub:
            errors.append(f"deveria estar como não coletado: {n}")
    for n, snippet in (exp.get("motivo") or {}).items():
        d = by_name.get(n)
        if d is None or snippet not in str(d.extra.get("motivo") or ""):
            errors.append(f"motivo de {n} sem '{snippet}': {(d.extra.get('motivo') if d else None)!r}")
    for n, status in (exp.get("status") or {}).items():
        d = by_name.get(n)
        if d is None or d.extra.get("status") != status:
            errors.append(f"status de {n} deveria ser {status}: {(d.extra.get('status') if d else None)!r}")
    unexpected = [d.label for d in topo.devices.values() if d.id not in mapping]
    errors += [f"equipamento inesperado: {u}" for u in unexpected]

    vendor_ok = role_ok = 0
    for n in sorted(collected):
        d = by_name[n]
        if not (d.vendor or "").lower().startswith(nodes[n]["vendor"].lower()):
            errors.append(f"fabricante de {n}: {d.vendor}")
        else:
            vendor_ok += 1
        if d.role not in nodes[n]["roles"]:
            errors.append(f"papel de {n}: {d.role} (esperado {nodes[n]['roles']})")
        else:
            role_ok += 1

    # links físicos
    want_links = _links(exp.get("links", "todos"), truth)
    want = {frozenset(((a, ifname_key(ai)), (b, ifname_key(bi)))) for a, ai, b, bi in want_links}
    want_pairs = Counter(frozenset((a, b)) for a, _, b, _ in want_links)
    seen_pairs: Counter[frozenset[str]] = Counter()
    exact = 0
    phys = [lk for lk in topo.links if lk.kind == "physical"]
    for lk in phys:
        a, b = mapping.get(lk.source), mapping.get(lk.target)
        desc = f"{a or lk.source}:{lk.source_interface} <-> {b or lk.target}:{lk.target_interface}"
        pair = frozenset((a, b)) if a and b else None
        if pair is None or pair not in want_pairs:
            errors.append(f"link que não deveria existir: {desc}")
            continue
        seen_pairs[pair] += 1
        if seen_pairs[pair] > want_pairs[pair]:
            errors.append(f"link duplicado: {desc}")
            continue
        key = frozenset(((a, ifname_key(lk.source_interface)), (b, ifname_key(lk.target_interface))))
        if key in want:
            exact += 1
        else:
            errors.append(f"porta errada: {desc}")
    for a, ai, b, bi in want_links:
        if seen_pairs[frozenset((a, b))] == 0:
            errors.append(f"link faltando: {a}:{ai} <-> {b}:{bi}")

    # roteamento
    spec = exp.get("roteamento", "todos")
    expected_routing = [r for r in truth.get("routing", []) if spec == "todos" or (isinstance(spec, list) and r[2] in spec)]
    routing_found = 0
    for a, b, proto in expected_routing:
        ok = any(proto in lk.protocols and {mapping.get(lk.source), mapping.get(lk.target)} == {a, b}
                 for lk in topo.links)
        routing_found += ok
        if not ok:
            errors.append(f"adjacência {proto} {a} <-> {b} não detectada")

    # coletas repetidas
    done = [e for e in events if e.get("type") == "device_done"]
    repeats = {h: c for h, c in Counter(short_hostname(e.get("hostname")) or e.get("target") for e in done).items()
               if c > 1}
    errors += [f"coletado {c} vezes: {h}" for h, c in repeats.items()]

    # memória e eventos
    mem = timing.get("memoria") or topo.meta.stats.get("memoria") or {}
    for k, v in (exp.get("memoria") or {}).items():
        if mem.get(k) != v:
            errors.append(f"memória: {k}={mem.get(k)} (esperado {v})")
    evs = mem.get("eventos") or []
    for want_ev in exp.get("eventos") or []:
        if not any(e.get("kind") == want_ev["kind"] and (not want_ev.get("device") or e.get("device") == want_ev["device"])
                   for e in evs):
            errors.append(f"evento esperado ausente: {want_ev}")
    for kind in exp.get("eventos_ausentes") or []:
        bad = [e for e in evs if e.get("kind") == kind]
        if bad:
            errors.append(f"evento inesperado {kind}: {bad[:3]}")

    # carga (rate limit)
    if exp.get("carga"):
        lim = exp["carga"]
        for n in sorted(collected):
            cg = by_name[n].extra.get("carga") or {}
            if not cg:
                errors.append(f"carga: sem telemetria em {n}")
                continue
            gap = cg.get("menor_intervalo_ms")
            if gap is not None and cg.get("requisicoes", 0) > 1 and gap < lim["intervalo_min_ms"] - 15:
                errors.append(f"carga: intervalo de {gap} ms em {n} (mínimo {lim['intervalo_min_ms']})")
            if cg.get("max_sessoes_simultaneas", 0) > lim["max_sessoes"]:
                errors.append(f"carga: {cg['max_sessoes_simultaneas']} sessões simultâneas em {n}")

    # determinismo
    if exp.get("igual_a"):
        ref = results / "scenarios" / exp["igual_a"] / "topology.json"
        if ref.exists() and signature(Topology.load(str(ref))) != signature(topo):
            errors.append(f"resultado diferente de {exp['igual_a']} (não determinístico)")

    n_links = len(want_links)
    return {
        "errors": errors,
        "error_count": len(errors),
        "nodes_expected_collected": len(want_collected),
        "nodes_collected": len(collected & want_collected),
        "links_expected": n_links,
        "links_found": sum(1 for p in want_pairs if seen_pairs[p] > 0),
        "link_precision": round(exact / max(1, len(phys)), 3),
        "interface_accuracy": round(exact / max(1, sum(min(seen_pairs[p], want_pairs[p]) for p in want_pairs)), 3),
        "vendor_accuracy": round(vendor_ok / max(1, len(collected)), 3),
        "role_accuracy": round(role_ok / max(1, len(collected)), 3),
        "routing_expected": len(expected_routing),
        "routing_found": routing_found,
        "collections": len(done),
        "repeat_collections": repeats,
        "memoria": {k: v for k, v in mem.items() if k != "eventos"},
        "eventos": evs,
        "failed_targets": topo.meta.failed_targets,
        "per_node": {n: {"collected": not d.stub, "vendor": d.vendor, "role": d.role, "tier": d.tier,
                         "via": d.collected_via, "profile": d.profile, "status": d.extra.get("status"),
                         "reutilizado": bool(d.extra.get("reutilizado")), "motivo": d.extra.get("motivo"),
                         "carga": d.extra.get("carga"), "fingerprint": d.extra.get("fingerprint")}
                     for n, d in sorted(by_name.items())},
    }


def score_extras(results: Path) -> dict[str, Any]:
    """API/UI e CLI: verificações binárias."""
    out: dict[str, Any] = {}
    api = results / "scenarios" / "16-api-ui" / "timing.json"
    if api.exists():
        info = json.loads(api.read_text(encoding="utf-8"))
        errs = []
        if info.get("status") != "finished":
            errs.append(f"descoberta pela API: {info.get('status')}")
        if (info.get("verify") or {}).get("status") != "finished":
            errs.append("verificação pela API não concluiu")
        if info.get("secrets_in_data_dir"):
            errs.append("segredo encontrado no diretório de dados")
        errs += [f"exportação {f}: HTTP {v['status']}" for f, v in (info.get("exports") or {}).items()
                 if v["status"] != 200]
        out["16-api-ui"] = {"errors": errs, "error_count": len(errs), "duration_s": info.get("duration_s"),
                            "title": info.get("title"), "status": info.get("status")}
    cli = results / "scenarios" / "cli" / "cli.json"
    if cli.exists():
        checks = json.loads(cli.read_text(encoding="utf-8"))
        errs = [f"nettopo {k}: código {v['exit_code']}" for k, v in checks.items() if v["exit_code"] != 0]
        out["cli"] = {"errors": errs, "error_count": len(errs), "title": "Comandos da CLI", "status": "ok"}
    return out


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    strict = "--strict" in sys.argv
    results = Path(args[0] if args else "lab-results")
    truth = load_truth()
    scenarios = results / "scenarios"
    metrics: dict[str, Any] = {}
    if not scenarios.is_dir():
        results.mkdir(parents=True, exist_ok=True)
        msg = "# Simulação NetTopo\n\nNenhum cenário executado (falha antes da simulação; veja os logs do job).\n"
        (results / "summary.md").write_text(msg, encoding="utf-8")
        print("nenhum cenário encontrado")
        sys.exit(1 if strict else 0)
    for d in sorted(scenarios.iterdir()):
        topo_file = d / "topology.json"
        if not d.is_dir() or not topo_file.exists():
            continue
        timing = json.loads((d / "timing.json").read_text(encoding="utf-8")) if (d / "timing.json").exists() else {}
        events = [json.loads(ln) for ln in (d / "events.jsonl").read_text(encoding="utf-8").splitlines()
                  if ln.strip()] if (d / "events.jsonl").exists() else []
        m = score(d.name, Topology.load(str(topo_file)), truth, timing, events, results)
        m.update({"title": timing.get("title", d.name), "status": timing.get("status"),
                  "duration_s": timing.get("duration_s")})
        if timing.get("status") != "ok":
            m["errors"].insert(0, f"cenário terminou com {timing.get('status')}")
            m["error_count"] += 1
        metrics[d.name] = m
    metrics.update(score_extras(results))
    total = sum(m["error_count"] for m in metrics.values())
    summary_file = scenarios / "summary.json"
    suite = json.loads(summary_file.read_text(encoding="utf-8")) if summary_file.exists() else {}
    if not isinstance(suite, dict):  # formato antigo (lista de cenários)
        suite = {}
    report = {"suite": suite.get("suite"), "scenarios_duration_s": suite.get("duration_s"), "total_errors": total,
              "scenarios": metrics}
    (results / "metrics.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str),
                                          encoding="utf-8")

    lines = [f"# Simulação NetTopo — suíte {suite.get('suite', '?')}", "",
             f"**Erros: {total}** · cenários: {len(metrics)} · tempo dos cenários: {suite.get('duration_s')} s", "",
             "| Cenário | Erros | Tempo (s) | Coletados | Links | Precisão | Portas | Roteamento | Memória |",
             "|---|---|---|---|---|---|---|---|---|"]
    for sid, m in metrics.items():
        if "nodes_collected" not in m:
            lines.append(f"| {sid} | {m['error_count']} | {m.get('duration_s', '')} | | | | | | |")
            continue
        mem = m.get("memoria") or {}
        mem_txt = f"{mem.get('reaproveitados', 0)} conf./{mem.get('recoletados', 0)} recol." if mem else ""
        lines.append(
            f"| {sid} | {m['error_count']} | {m['duration_s']} | {m['nodes_collected']}/{m['nodes_expected_collected']} "
            f"| {m['links_found']}/{m['links_expected']} | {m['link_precision']:.0%} | {m['interface_accuracy']:.0%} "
            f"| {m['routing_found']}/{m['routing_expected']} | {mem_txt} |")
    errs = [(sid, e) for sid, m in metrics.items() for e in m["errors"]]
    if errs:
        lines += ["", "## Erros", ""] + [f"- **{sid}**: {e}" for sid, e in errs]
    (results / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    if strict and total:
        sys.exit(1)


if __name__ == "__main__":
    main()
