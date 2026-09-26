"""Executa os cenários da simulação contra o laboratório e salva tudo em ``lab-results/scenarios/``.

Cada cenário grava: ``settings.json`` (sem segredos), ``topology.json``, ``events.jsonl``,
``timing.json``, ``nettopo.log`` e, nos principais, os relatórios (HTML, draw.io, Excel, Markdown).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from common import (
    NODES,
    WRONG_CREDS,
    all_creds,
    base_settings,
    docker_exec,
    sh,
    write_json,
)
from nettopo.config import Settings
from nettopo.discovery.engine import discover
from nettopo.models import Topology
from nettopo.output import export_all
from nettopo.topology.diff import diff_topologies

RESULTS = Path(sys.argv[1] if len(sys.argv) > 1 else "lab-results")
OUT = RESULTS / "scenarios"
INVENTORY = [NODES[n] for n in NODES]  # todos os IPs de gerência (inclui a operadora, que deve falhar)
FULL_EXPORTS = ["json", "html", "drawio", "xlsx", "md"]

SCENARIOS: list[dict[str, Any]] = [
    {"id": "01-completo", "title": "Completo (REST > NETCONF > SSH + SNMP), semente única, sem DNS",
     "settings": base_settings(), "exports": FULL_EXPORTS},
    {"id": "02-completo-dns", "title": "Completo com DNS (hostnames resolvem para a gerência)",
     "settings": base_settings(), "hosts": True},
    {"id": "03-inventario", "title": "Sementes = inventário de IPs de gerência",
     "settings": base_settings(seeds=INVENTORY), "exports": FULL_EXPORTS},
    {"id": "04-snmp-v2c", "title": "Somente SNMP v2c", "settings": base_settings(
        methods=["snmp"], credentials=all_creds("snmp_v2c"))},
    {"id": "05-snmp-v3", "title": "Somente SNMPv3 (authPriv SHA/AES) a partir do inventário",
     "settings": base_settings(methods=["snmp"], credentials=all_creds("snmp_v3"), seeds=INVENTORY)},
    {"id": "06-ssh", "title": "Somente SSH/CLI", "settings": base_settings(
        methods=["ssh"], credentials=all_creds("ssh_mikrotik", "ssh_srlinux", "ssh_linux"))},
    {"id": "07-apis", "title": "APIs (REST/NETCONF); SNMP só para identificar o fabricante",
     "settings": base_settings(methods=["rest", "netconf", "snmp"], snmp_complement=False,
                               credentials=all_creds("rest_mikrotik", "netconf_srlinux", "snmp_v2c"))},
    {"id": "08-credenciais-mistas", "title": "Credenciais erradas testadas primeiro",
     "settings": base_settings(credentials=WRONG_CREDS + all_creds())},
    {"id": "09-escopo", "title": "Profundidade 1 e exclusão da rede dos servidores",
     "settings": base_settings(max_depth=1, scope={"include": ["172.20.20.0/24", "10.0.0.0/8", "192.168.0.0/16"],
                                                   "exclude": ["172.20.20.40/29"]})},
    {"id": "10-concorrencia-1", "title": "Inventário com concorrência 1 (sequencial)",
     "settings": base_settings(seeds=INVENTORY, concurrency=1)},
]


def setup_logging(path: Path) -> logging.Handler:
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.WARNING)
    root.addHandler(handler)
    logging.getLogger("nettopo").setLevel(logging.DEBUG)
    return handler


def set_hosts(enable: bool) -> None:
    """Simula DNS corporativo: hostnames dos equipamentos -> IP de gerência."""
    marker = "# nettopo-lab"
    current = Path("/etc/hosts").read_text()
    lines = [ln for ln in current.splitlines() if marker not in ln]
    if enable:
        lines += [f"{ip} {name} {marker}" for name, ip in NODES.items()]
    subprocess.run(["sudo", "tee", "/etc/hosts"], input="\n".join(lines) + "\n", text=True,
                   capture_output=True, check=True)


def run_discovery(sc: dict[str, Any]) -> dict[str, Any]:
    d = OUT / sc["id"]
    d.mkdir(parents=True, exist_ok=True)
    settings = Settings.model_validate(sc["settings"])
    write_json(d / "settings.json", settings.sanitized())
    events: list[dict[str, Any]] = []
    handler = setup_logging(d / "nettopo.log")
    t0 = time.time()
    status = "ok"
    try:
        topo = asyncio.run(discover(settings, progress=lambda e: events.append({**e, "t": round(time.time() - t0, 2)})))
        export_all(topo, sc.get("exports", ["json"]), d, "topology")
    except Exception as exc:
        status = f"erro: {type(exc).__name__}: {exc}"
        (d / "traceback.txt").write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()
    elapsed = round(time.time() - t0, 1)
    with (d / "events.jsonl").open("w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e, ensure_ascii=False, default=str) + "\n")
    info = {"id": sc["id"], "title": sc["title"], "status": status, "duration_s": elapsed}
    write_json(d / "timing.json", info)
    print(f"[{sc['id']}] {status} em {elapsed}s", flush=True)
    return info


def run_cli_checks() -> dict[str, Any]:
    """Valida a interface de linha de comando com a mesma instalação."""
    d = OUT / "cli"
    d.mkdir(parents=True, exist_ok=True)
    import yaml

    cfg = d / "config.yaml"
    cfg.write_text(yaml.safe_dump(base_settings(max_depth=0), allow_unicode=True), encoding="utf-8")
    results = {}
    for name, args in {
        "vendors": ["nettopo", "vendors"],
        "discover": ["nettopo", "discover", "-c", str(cfg), "-o", str(d / "out"), "-f", "json,html"],
        "report": ["nettopo", "report", str(OUT / "03-inventario" / "topology.json"), "-o", str(d / "report"),
                   "-f", "html,drawio,xlsx,md"],
        "diff": ["nettopo", "diff", str(OUT / "03-inventario" / "topology.json"),
                 str(OUT / "11-falha-injetada" / "topology.json")],
    }.items():
        t0 = time.time()
        r = sh(args, timeout=600)
        (d / f"{name}.log").write_text((r.stdout or "") + (r.stderr or ""), encoding="utf-8")
        results[name] = {"exit_code": r.returncode, "duration_s": round(time.time() - t0, 1)}
    write_json(d / "cli.json", results)
    return results


def run_api_ui() -> dict[str, Any]:
    """Sobe a API, dispara uma descoberta, acompanha pelo WebSocket, baixa exportações e tira screenshots."""
    import httpx
    from websockets.sync.client import connect

    d = OUT / "12-api-ui"
    d.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "NETTOPO_DATA": str(d / "data")}
    server = subprocess.Popen(["nettopo", "serve", "--port", "8765"], env=env, stdout=(d / "server.log").open("w"),
                              stderr=subprocess.STDOUT)
    info: dict[str, Any] = {"id": "12-api-ui", "title": "API REST + WebSocket + UI web"}
    base = "http://127.0.0.1:8765"
    try:
        for _ in range(60):
            try:
                if httpx.get(f"{base}/api/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(1)
        body = base_settings(seeds=INVENTORY, name="Lab via API")
        t0 = time.time()
        rid = httpx.post(f"{base}/api/discoveries", json=body, timeout=30).json()["id"]
        types: dict[str, int] = {}
        with connect(f"ws://127.0.0.1:8765/api/discoveries/{rid}/events", open_timeout=30) as ws:
            while True:
                ev = json.loads(ws.recv(timeout=900))
                types[ev["type"]] = types.get(ev["type"], 0) + 1
                if ev["type"] == "closed":
                    break
        info["duration_s"] = round(time.time() - t0, 1)
        info["ws_events"] = types
        for _ in range(30):
            st = httpx.get(f"{base}/api/discoveries/{rid}", timeout=10).json()
            if st["status"] in ("finished", "failed"):
                break
            time.sleep(1)
        info["status"] = st["status"]
        info["stats"] = st.get("stats")
        info["exports"] = {}
        for fmt in ("html", "drawio", "xlsx", "md", "json"):
            r = httpx.get(f"{base}/api/discoveries/{rid}/export/{fmt}", timeout=120)
            info["exports"][fmt] = {"status": r.status_code, "bytes": len(r.content)}
        stored = (d / "data" / "nettopo.db").read_bytes()
        info["secrets_in_db"] = any(s.encode() in stored for s in ("NokiaSrl1!", "NetTopo#2026", "authpass2026"))
        shots = d / "screenshots"
        shots.mkdir(exist_ok=True)
        chrome = shutil.which("google-chrome") or shutil.which("chromium") or "google-chrome"
        report = (OUT / "03-inventario" / "topology.html").resolve()
        for name, url, size in [
            ("ui-resultado", f"{base}/#{rid}", "1600,1000"),
            ("relatorio-diagrama", f"file://{report}", "1600,1000"),
            ("relatorio-inventario", f"file://{report}#tab=inventory", "1600,900"),
            ("relatorio-equipamento", f"file://{report}#device=core-srl1", "1600,1000"),
            ("relatorio-links", f"file://{report}#tab=links", "1600,900"),
        ]:
            sh([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", f"--window-size={size}",
                "--virtual-time-budget=10000", f"--screenshot={shots / (name + '.png')}", url], timeout=120)
        info["screenshots"] = sorted(p.name for p in shots.glob("*.png"))
    except Exception as exc:
        info["status"] = f"erro: {type(exc).__name__}: {exc}"
        (d / "traceback.txt").write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        server.terminate()
        server.wait(timeout=30)
    write_json(d / "timing.json", info)
    print(f"[12-api-ui] {info.get('status')} em {info.get('duration_s')}s", flush=True)
    return info


def inject_failure() -> dict[str, Any]:
    """Desliga srv2 e derruba o link core-srl2 <-> dist-frr1; espera o LLDP expirar."""
    actions = {
        "docker stop srv2": sh(["docker", "stop", "clab-nettopo-srv2"]).returncode,
        "dist-frr1 eth2 down": docker_exec("dist-frr1", "ip", "link", "set", "eth2", "down"),
    }
    time.sleep(150)  # TTL LLDP padrão = 120 s
    actions["lldp core-srl2 após falha"] = docker_exec("core-srl2", "sr_cli", "show system lldp neighbor")
    return actions


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    summary: list[dict[str, Any]] = []
    for sc in SCENARIOS:
        set_hosts(bool(sc.get("hosts")))
        summary.append(run_discovery(sc))
    set_hosts(False)
    summary.append(run_api_ui())
    failure = inject_failure()
    write_json(OUT / "falha-injetada.json", failure)
    summary.append(run_discovery({"id": "11-falha-injetada",
                                  "title": "Após falha: srv2 desligado e link core-srl2/dist-frr1 derrubado",
                                  "settings": base_settings(seeds=INVENTORY)}))
    try:
        before = Topology.load(str(OUT / "03-inventario" / "topology.json"))
        after = Topology.load(str(OUT / "11-falha-injetada" / "topology.json"))
        write_json(OUT / "11-falha-injetada" / "diff.json", diff_topologies(before, after))
    except Exception as exc:
        write_json(OUT / "11-falha-injetada" / "diff.json", {"erro": str(exc)})
    summary.append({"id": "cli", "title": "Comandos da CLI", "checks": run_cli_checks()})
    write_json(OUT / "summary.json", summary)


if __name__ == "__main__":
    main()
