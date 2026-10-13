"""Executa os cenários da simulação contra o laboratório e salva tudo em ``<resultados>/scenarios/``.

Suítes: ``rapida`` (a cada push) e ``completa`` (diária/manual). Uso:
    python run_scenarios.py <resultados> [rapida|completa]

Cada cenário grava ``settings.json`` (sem segredos), ``topology.json``, ``events.jsonl``, ``timing.json``,
``nettopo.log`` e, nos principais, os relatórios. Cenários com memória usam um inventário persistente em
``<resultados>/memoria/<nome>`` (o mesmo da ferramenta real).
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
from nettopo.inventory.revalidate import discover_with_memory
from nettopo.inventory.store import InventoryStore
from nettopo.models import Topology
from nettopo.output import export_all
from nettopo.topology.diff import diff_topologies

RESULTS = Path(sys.argv[1] if len(sys.argv) > 1 else "lab-results")
SUITE = (sys.argv[2] if len(sys.argv) > 2 else os.environ.get("NETTOPO_SUITE", "rapida")).lower()
OUT = RESULTS / "scenarios"
MEMORY = RESULTS / "memoria"
MGMT_NET = "172.20.20.0/24"
INVENTORY = [NODES[n] for n in NODES]  # todos os IPs de gerência (inclui a operadora, que deve falhar)
FULL_EXPORTS = ["json", "html", "drawio", "xlsx", "md"]
SSH_CREDS = ("ssh_mikrotik", "ssh_srlinux", "ssh_linux")
API_CREDS = ("rest_mikrotik", "rest_srlinux", "netconf_srlinux", "snmp_v2c")


def S(sid: str, title: str, settings: dict[str, Any], suites: tuple[str, ...] = ("rapida", "completa"),
      **kw: Any) -> dict[str, Any]:
    return {"id": sid, "title": title, "settings": settings, "suites": suites, **kw}


SCENARIOS: list[dict[str, Any]] = [
    S("01-semente-unica", "Semente única, todos os métodos, sem DNS nem memória", base_settings(),
      exports=FULL_EXPORTS),
    S("02-varredura", "Semente única + varredura da rede de gerência (cria a memória)",
      base_settings(varredura=[MGMT_NET]), memory="lab", fresh_memory=True, exports=FULL_EXPORTS),
    S("03-memoria", "Segunda execução: semente única usando a memória", base_settings(), memory="lab"),
    S("04-ssh", "Somente SSH (identificação por banner/prompt, sem SNMP)",
      base_settings(methods=["ssh"], credentials=all_creds(*SSH_CREDS), seeds=INVENTORY)),
    S("05-snmp", "Somente SNMP v2c + varredura", base_settings(methods=["snmp"], credentials=all_creds("snmp_v2c"),
                                                                varredura=[MGMT_NET])),
    S("06-apis", "APIs (REST, JSON-RPC, NETCONF); SNMP só para identificar",
      base_settings(methods=["rest", "netconf", "snmp"], snmp_complement=False, credentials=all_creds(*API_CREDS),
                    varredura=[MGMT_NET])),
    S("07-dns", "Semente única com DNS (hostnames resolvem para a gerência)", base_settings(), hosts=True,
      suites=("completa",)),
    S("08-credenciais-mistas", "Credenciais erradas testadas primeiro",
      base_settings(credentials=WRONG_CREDS + all_creds(), seeds=INVENTORY), suites=("completa",)),
    S("09-escopo", "Profundidade 1 e exclusão da rede dos servidores",
      base_settings(max_depth=1, scope={"include": ["172.20.20.0/24", "10.0.0.0/8", "192.168.0.0/16"],
                                        "exclude": ["172.20.20.40/29"]}), suites=("completa",)),
    S("10-sequencial", "Inventário com 1 coleta por vez", base_settings(seeds=INVENTORY, concurrency=1),
      suites=("completa",)),
    S("11-snmpv3", "Somente SNMPv3 (authPriv SHA/AES) a partir do inventário",
      base_settings(methods=["snmp"], credentials=all_creds("snmp_v3"), seeds=INVENTORY), suites=("completa",)),
    S("12-carga-conservadora", "Perfil de carga conservador (500 ms entre requisições, 1 sessão)",
      base_settings(seeds=INVENTORY, carga={"perfil": "conservador"}), suites=("completa",)),
    S("13-determinismo", "Repetição do cenário 02 sem memória (mesmo resultado?)",
      base_settings(varredura=[MGMT_NET]), suites=("completa",)),
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
    store = None
    if sc.get("memory"):
        mem_dir = MEMORY / sc["memory"]
        if sc.get("fresh_memory") and mem_dir.exists():
            shutil.rmtree(mem_dir)
        store = InventoryStore(mem_dir)
    events: list[dict[str, Any]] = []
    handler = setup_logging(d / "nettopo.log")
    t0 = time.time()
    status = "ok"
    topo = None
    try:
        topo = asyncio.run(discover_with_memory(
            settings, store=store, full=bool(sc.get("full")), verify_only=bool(sc.get("verify_only")),
            progress=lambda e: events.append({**e, "t": round(time.time() - t0, 2)})))
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
    info = {"id": sc["id"], "title": sc["title"], "status": status, "duration_s": elapsed, "suite": SUITE,
            "memoria": (topo.meta.stats.get("memoria") if topo else None)}
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
    data = d / "dados"
    results = {}
    for name, args in {
        "vendors": ["nettopo", "vendors"],
        "discover": ["nettopo", "discover", "-c", str(cfg), "-o", str(d / "out"), "-f", "json,html", "--dados",
                     str(data)],
        "verificar": ["nettopo", "verificar", "-c", str(cfg), "--dados", str(data)],
        "inventario": ["nettopo", "inventario", "--dados", str(data)],
        "report": ["nettopo", "report", str(OUT / "02-varredura" / "topology.json"), "-o", str(d / "report"),
                   "-f", "html,drawio,xlsx,md"],
        "diff": ["nettopo", "diff", str(OUT / "02-varredura" / "topology.json"),
                 str(OUT / "14-falha-verificar" / "topology.json")],
    }.items():
        t0 = time.time()
        r = sh(args, timeout=600)
        (d / f"{name}.log").write_text((r.stdout or "") + (r.stderr or ""), encoding="utf-8")
        results[name] = {"exit_code": r.returncode, "duration_s": round(time.time() - t0, 1)}
    write_json(d / "cli.json", results)
    return results


def run_api_ui() -> dict[str, Any]:
    """Sobe a API, usa o cofre, dispara descoberta e verificação, baixa exportações e tira screenshots."""
    import httpx
    from websockets.sync.client import connect

    d = OUT / "16-api-ui"
    d.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "NETTOPO_DATA": str(d / "data"), "NETTOPO_VAULT_BACKEND": "arquivo",
           "NETTOPO_VAULT_PASSWORD": "lab-vault-2026"}
    server = subprocess.Popen(["nettopo", "serve", "--port", "8765"], env=env, stdout=(d / "server.log").open("w"),
                              stderr=subprocess.STDOUT)
    info: dict[str, Any] = {"id": "16-api-ui", "title": "API REST + WebSocket + cofre + UI web"}
    base = "http://127.0.0.1:8765"
    try:
        for _ in range(60):
            try:
                if httpx.get(f"{base}/api/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(1)
        for c in all_creds():  # credenciais guardadas no cofre e usadas por referência
            httpx.post(f"{base}/api/credentials", json=c, timeout=10).raise_for_status()
        body = base_settings(seeds=INVENTORY, name="Lab via API", credentials=[], usar_cofre=True)
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
        st: dict[str, Any] = {}
        for _ in range(30):
            st = httpx.get(f"{base}/api/discoveries/{rid}", timeout=10).json()
            if st["status"] in ("finished", "failed"):
                break
            time.sleep(1)
        info["status"] = st.get("status")
        info["stats"] = st.get("stats")
        vr = httpx.post(f"{base}/api/verify", timeout=30).json()["id"]
        vst: dict[str, Any] = {}
        for _ in range(120):
            vst = httpx.get(f"{base}/api/discoveries/{vr}", timeout=10).json()
            if vst["status"] in ("finished", "failed"):
                break
            time.sleep(1)
        info["verify"] = {"status": vst.get("status"), "memoria": (vst.get("stats") or {}).get("memoria")}
        info["inventory_counts"] = httpx.get(f"{base}/api/inventory", timeout=10).json()["counts"]
        info["exports"] = {}
        for fmt in ("html", "drawio", "xlsx", "md", "json"):
            r = httpx.get(f"{base}/api/discoveries/{rid}/export/{fmt}", timeout=120)
            info["exports"][fmt] = {"status": r.status_code, "bytes": len(r.content)}
        secrets = ("NokiaSrl1!", "NetTopo#2026", "authpass2026", "privpass2026")
        stored = b"".join(p.read_bytes() for p in (d / "data").rglob("*") if p.is_file())
        info["secrets_in_data_dir"] = any(s.encode() in stored for s in secrets)
        shots = d / "screenshots"
        shots.mkdir(exist_ok=True)
        chrome = shutil.which("google-chrome") or shutil.which("chromium") or "google-chrome"
        report = (OUT / "02-varredura" / "topology.html").resolve()
        for name, url, size in [
            ("ui-resultado", f"{base}/#{rid}", "1600,1000"),
            ("ui-inventario", f"{base}/#inventario", "1600,1000"),
            ("ui-formulario", f"{base}/#nova", "1500,1300"),
            ("relatorio-diagrama", f"file://{report}", "1600,1000"),
            ("relatorio-inventario", f"file://{report}#tab=inventory", "1600,900"),
            ("relatorio-equipamento", f"file://{report}#device=core-srl1", "1600,1000"),
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
    print(f"[16-api-ui] {info.get('status')} em {info.get('duration_s')}s", flush=True)
    return info


LLDP_TTL_S = 20  # LLDP do laboratório: anúncio a cada 5 s, validade 5 s x 4


def inject_failure() -> dict[str, Any]:
    """Congela o srv2 (gerência e LLDP param de responder) e derruba o link core-srl2 <-> dist-frr1."""
    actions = {
        "docker pause srv2": sh(["docker", "pause", "clab-nettopo-srv2"]).returncode,
        "dist-frr1 eth2 down": docker_exec("dist-frr1", "ip", "link", "set", "eth2", "down"),
    }
    time.sleep(LLDP_TTL_S + 5)  # o vizinho congelado expira por TTL; o link derrubado some na hora
    actions["lldp core-srl2 após falha"] = docker_exec("core-srl2", "sr_cli", "show system lldp neighbor")
    return actions


def restore() -> dict[str, Any]:
    actions = {
        "docker unpause srv2": sh(["docker", "unpause", "clab-nettopo-srv2"]).returncode,
        "dist-frr1 eth2 up": docker_exec("dist-frr1", "ip", "link", "set", "eth2", "up"),
    }
    time.sleep(15)  # 3 anúncios de 5 s
    actions["lldp core-srl2 após restaurar"] = docker_exec("core-srl2", "sr_cli", "show system lldp neighbor")
    return actions


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    summary: list[dict[str, Any]] = []
    t_suite = time.time()
    for sc in SCENARIOS:
        if SUITE not in sc["suites"]:
            continue
        set_hosts(bool(sc.get("hosts")))
        summary.append(run_discovery(sc))
    set_hosts(False)
    if SUITE == "completa":
        summary.append(run_api_ui())
    write_json(OUT / "falha-injetada.json", inject_failure())
    summary.append(run_discovery(S("14-falha-verificar", "Verificação após falha: srv2 congelado e link derrubado",
                                   base_settings(), memory="lab", verify_only=True)))
    write_json(OUT / "falha-restaurada.json", restore())
    summary.append(run_discovery(S("15-restaurado", "Verificação após restaurar srv2 e o link",
                                   base_settings(), memory="lab", verify_only=True)))
    try:
        before = Topology.load(str(OUT / "02-varredura" / "topology.json"))
        after = Topology.load(str(OUT / "14-falha-verificar" / "topology.json"))
        write_json(OUT / "14-falha-verificar" / "diff.json", diff_topologies(before, after))
    except Exception as exc:
        write_json(OUT / "14-falha-verificar" / "diff.json", {"erro": str(exc)})
    if SUITE == "completa":
        summary.append({"id": "cli", "title": "Comandos da CLI", "checks": run_cli_checks()})
    write_json(OUT / "summary.json", {"suite": SUITE, "duration_s": round(time.time() - t_suite, 1),
                                      "scenarios": summary})


if __name__ == "__main__":
    main()
