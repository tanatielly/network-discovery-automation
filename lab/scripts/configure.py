"""Espera o laboratório subir, garante a configuração dos MikroTik e registra o estado real dos equipamentos.

Saídas em ``lab-results/lab-state/``: tempos de boot, respostas da configuração e o que cada
equipamento enxerga (vizinhos LLDP/MNDP, OSPF, BGP) — usado para validar o gabarito.
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common import CREDS, LAB_DIR, LINUX, MIKROTIK, NODES, SRLINUX, docker_exec, wait_ssh_banner, write_json

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "lab-results") / "lab-state"


def mikrotik_session(ip: str):  # noqa: ANN201
    from netmiko import ConnectHandler

    c = CREDS["ssh_mikrotik"]
    return ConnectHandler(device_type="mikrotik_routeros", host=ip, username=c["username"],
                          password=c["password"], timeout=30, conn_timeout=30, fast_cli=False)


def ensure_mikrotik(node: str) -> dict[str, str]:
    """Reaplica o .rsc via SSH (idempotente: linhas repetidas só geram aviso)."""
    ip = NODES[node]
    lines = [ln.strip() for ln in (LAB_DIR / "configs" / f"{node}.rsc").read_text().splitlines()
             if ln.strip() and not ln.startswith("#")]
    log: dict[str, str] = {}
    conn = mikrotik_session(ip)
    try:
        before = conn.send_command("/system identity print")
        log["_identity_before"] = before
        if node not in before:  # startup-config não foi aplicado: aplica tudo
            for ln in lines:
                log[ln] = conn.send_command(ln, read_timeout=30)
        else:
            log["_status"] = "startup-config aplicado pelo containerlab"
        log["_identity_after"] = conn.send_command("/system identity print")
        log["_addresses"] = conn.send_command("/ip address print terse without-paging")
    finally:
        conn.disconnect()
    return log


def dump_state() -> dict[str, dict[str, str]]:
    state: dict[str, dict[str, str]] = {}
    for node in MIKROTIK:
        conn = mikrotik_session(NODES[node])
        try:
            state[node] = {cmd: conn.send_command(cmd, read_timeout=30) for cmd in (
                "/ip neighbor print detail without-paging", "/routing ospf neighbor print detail without-paging",
                "/routing bgp session print detail without-paging", "/snmp print", "/ip service print")}
        finally:
            conn.disconnect()
    for node in SRLINUX:
        state[node] = {cmd: docker_exec(node, "sr_cli", cmd) for cmd in (
            "show version", "show system lldp neighbor", "show interface brief")}
    for node in LINUX + ["isp-pe"]:
        state[node] = {
            "lldpcli show neighbors": docker_exec(node, "lldpcli", "show", "neighbors"),
            "ip -br addr": docker_exec(node, "ip", "-br", "addr"),
        }
        if node in ("isp-pe", "dist-frr1"):
            state[node]["vtysh show bgp summary"] = docker_exec(node, "vtysh", "-c", "show bgp summary")
    return state


def lldp_neighbors_srl(node: str) -> int:
    out = docker_exec(node, "sr_cli", "show system lldp neighbor")
    return sum(1 for ln in out.splitlines() if "ethernet-1/" in ln)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=len(NODES)) as ex:
        boot = dict(zip(NODES, ex.map(lambda ip: round(wait_ssh_banner(ip), 1), NODES.values()), strict=True))
    print("SSH pronto:", boot, flush=True)

    config_log = {}
    for node in MIKROTIK:
        for attempt in range(1, 6):
            try:
                config_log[node] = ensure_mikrotik(node)
                break
            except Exception as exc:  # CHR ainda inicializando serviços
                print(f"{node}: tentativa {attempt} falhou: {exc}", flush=True)
                time.sleep(20)
    write_json(OUT / "config-mikrotik.json", config_log)

    # Convergência LLDP (SR Linux deve ver 3 ou 4 vizinhos)
    deadline = time.time() + 240
    while time.time() < deadline:
        counts = {n: lldp_neighbors_srl(n) for n in SRLINUX}
        print("vizinhos LLDP SR Linux:", counts, flush=True)
        if counts["core-srl1"] >= 3 and counts["core-srl2"] >= 4:
            break
        time.sleep(15)
    time.sleep(30)  # BGP/OSPF e MNDP estabilizam

    write_json(OUT / "boot.json", {"ssh_ready_s": boot, "total_ready_s": round(time.time() - t0, 1)})
    write_json(OUT / "device-state.json", dump_state())
    print(f"laboratório pronto em {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
