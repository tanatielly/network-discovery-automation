"""Executa, em cada equipamento, os comandos do perfil de fabricante do NetTopo e mede o parsing.

Para cada (equipamento, tipo de dado) registra a saída bruta e qual parser a interpretou
(custom / textfsm / generic / none) e quantos registros viraram dados. Isso mostra exatamente
onde os parsers funcionam com saídas reais e onde falham. Saída: ``lab-results/raw/``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from common import COLLECTABLE, CREDS, NODES, PROFILE_OF, SSH_BY_PROFILE, write_json
from nettopo.collectors.ssh import _ERROR_MARKERS, hostname_from_prompt
from nettopo.models import Device
from nettopo.vendors.parsers import parse_output
from nettopo.vendors.parsers.normalize import apply_rows
from nettopo.vendors.registry import COMMAND_KINDS, default_registry

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "lab-results") / "raw"


def main() -> None:
    from netmiko import ConnectHandler

    reg = default_registry()
    matrix: dict[str, dict[str, dict[str, object]]] = {}
    for node in COLLECTABLE:
        profile = reg.get(PROFILE_OF[node])
        cred = CREDS[SSH_BY_PROFILE[profile.id]]
        matrix[node] = {}
        try:
            conn = ConnectHandler(device_type=profile.netmiko, host=NODES[node], username=cred["username"],
                                  password=cred["password"], timeout=30, conn_timeout=30)
        except Exception as exc:
            matrix[node]["_connect"] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        matrix[node]["_prompt"] = {"prompt": conn.find_prompt(),
                                   "hostname": hostname_from_prompt(conn.find_prompt())}
        for kind in COMMAND_KINDS:
            for cmd in profile.commands_for(kind):
                try:
                    out = conn.send_command(cmd, read_timeout=60)
                except Exception as exc:
                    matrix[node][kind] = {"command": cmd, "error": f"{type(exc).__name__}: {exc}"}
                    continue
                safe = kind + "__" + "".join(ch if ch.isalnum() else "_" for ch in cmd)[:60]
                (OUT / node).mkdir(parents=True, exist_ok=True)
                (OUT / node / f"{safe}.txt").write_text(out, encoding="utf-8")
                rows, source = parse_output(kind, cmd, out, profile.textfsm_platform, profile.parsers.get(kind))
                applied = apply_rows(Device(), kind, rows)
                matrix[node][kind] = {
                    "command": cmd, "lines": len(out.splitlines()), "parser": source, "rows": len(rows),
                    "records": applied, "rejected_by_tool": bool(_ERROR_MARKERS.search(out[:300])),
                }
                if not matrix[node][kind]["rejected_by_tool"] and out.strip():
                    break  # mesmo critério do coletor SSH: usa o primeiro comando aceito
        conn.disconnect()
    write_json(OUT / "parse-matrix.json", matrix)
    for node, kinds in matrix.items():
        print(node, {k: (v.get("parser"), v.get("records")) for k, v in kinds.items() if not k.startswith("_")})


if __name__ == "__main__":
    main()
