"""Constantes do laboratório (IPs de gerência, credenciais de LABORATÓRIO) e utilitários comuns."""

from __future__ import annotations

import copy
import json
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

LAB_DIR = Path(__file__).resolve().parents[1]
ROOT = LAB_DIR.parent
LAB_NAME = "nettopo"

NODES: dict[str, str] = {
    "isp-pe": "172.20.20.2",
    "edge-mk1": "172.20.20.11",
    "edge-mk2": "172.20.20.12",
    "core-srl1": "172.20.20.21",
    "core-srl2": "172.20.20.22",
    "dist-frr1": "172.20.20.31",
    "srv1": "172.20.20.41",
    "srv2": "172.20.20.42",
}
MIKROTIK = ["edge-mk1", "edge-mk2"]
SRLINUX = ["core-srl1", "core-srl2"]
LINUX = ["dist-frr1", "srv1", "srv2"]
COLLECTABLE = MIKROTIK + SRLINUX + LINUX
PROFILE_OF = {**{n: "mikrotik_routeros" for n in MIKROTIK}, **{n: "nokia_srl" for n in SRLINUX},
              **{n: "linux" for n in LINUX}}

# Credenciais padrão de laboratório (containerlab / imagens do lab). Não são segredos.
CREDS: dict[str, dict[str, Any]] = {
    "ssh_mikrotik": {"type": "ssh", "name": "ssh-mikrotik", "username": "admin", "password": "admin"},
    "ssh_srlinux": {"type": "ssh", "name": "ssh-srlinux", "username": "admin", "password": "NokiaSrl1!"},
    "ssh_linux": {"type": "ssh", "name": "ssh-linux", "username": "nettopo", "password": "NetTopo#2026"},
    "snmp_v2c": {"type": "snmp", "name": "snmp-v2c", "version": "2c", "community": "public"},
    "snmp_v3": {"type": "snmp", "name": "snmp-v3", "version": "3", "username": "nettopo", "auth_protocol": "sha",
                "auth_key": "authpass2026", "priv_protocol": "aes", "priv_key": "privpass2026"},
    "netconf_srlinux": {"type": "netconf", "name": "netconf-srlinux", "username": "admin",
                        "password": "NokiaSrl1!", "port": 830},
    "rest_mikrotik": {"type": "rest", "name": "rest-mikrotik", "username": "admin", "password": "admin",
                      "https": False, "port": 80},
}
WRONG_CREDS: list[dict[str, Any]] = [
    {"type": "ssh", "name": "ssh-errada", "username": "operador", "password": "senha-errada"},
    {"type": "snmp", "name": "snmp-errada", "version": "2c", "community": "comunidade-errada"},
    {"type": "rest", "name": "rest-errada", "username": "api", "password": "errada", "https": False, "port": 80},
]
SSH_BY_PROFILE = {"mikrotik_routeros": "ssh_mikrotik", "nokia_srl": "ssh_srlinux", "linux": "ssh_linux"}


def all_creds(*keys: str) -> list[dict[str, Any]]:
    keys = keys or tuple(CREDS)
    return [copy.deepcopy(CREDS[k]) for k in keys]


def base_settings(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": "Lab NetTopo - Containerlab",
        "seeds": [NODES["edge-mk1"]],
        "scope": {"include": ["172.20.20.0/24", "10.0.0.0/8", "192.168.0.0/16"]},
        "max_depth": 6,
        "concurrency": 16,
        "timeout": 8,
        "credentials": all_creds(),
    }
    data.update(overrides)
    return data


def wait_ssh_banner(ip: str, timeout: float = 900, port: int = 22) -> float:
    """Espera o banner SSH (não só a porta TCP, pois o vrnetlab aceita conexões antes da VM subir)."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((ip, port), timeout=3) as s:
                s.settimeout(5)
                if s.recv(64).startswith(b"SSH-"):
                    return time.time() - start
        except OSError:
            pass
        time.sleep(3)
    raise TimeoutError(f"SSH de {ip} não respondeu em {timeout}s")


def sh(cmd: list[str] | str, check: bool = False, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, check=check,
                          timeout=timeout)


def docker_exec(node: str, *cmd: str, timeout: int = 60) -> str:
    r = sh(["docker", "exec", f"clab-{LAB_NAME}-{node}", *cmd], timeout=timeout)
    return (r.stdout or "") + (r.stderr or "")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
