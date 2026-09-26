"""Integração SNMP real (pysnmp) contra um agente simulado pelo snmpsim.

Pulado automaticamente se o snmpsim não estiver instalado (``pip install snmpsim pysmi``).
"""

import asyncio
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from nettopo.config import Settings
from nettopo.discovery.engine import discover

pytest.importorskip("snmpsim")
pytest.importorskip("pysmi")

FIXTURES = Path(__file__).parent / "fixtures" / "snmp"


def _free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def agent(tmp_path_factory):
    exe = shutil.which("snmpsim-command-responder", path=str(Path(sys.executable).parent))
    if not exe:
        pytest.skip("snmpsim-command-responder não encontrado")
    port = _free_udp_port()
    cache = tmp_path_factory.mktemp("snmpcache")
    proc = subprocess.Popen([exe, f"--data-dir={FIXTURES}", f"--agent-udpv4-endpoint=127.0.0.1:{port}",
                             f"--cache-dir={cache}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(4)
    yield port
    proc.terminate()
    proc.wait(timeout=10)


def test_discovery_over_real_snmp(agent):
    settings = Settings.model_validate({
        "seeds": ["127.0.0.1"], "timeout": 2, "max_depth": 1,
        "scope": {"include": ["10.0.0.0/8"]},
        "credentials": [{"type": "snmp", "version": "2c", "community": "errada", "port": agent},
                        {"type": "snmp", "version": "2c", "community": "public", "port": agent}],
    })
    topo = asyncio.run(discover(settings))
    pe = topo.devices["pe-huawei-01"]
    assert pe.profile == "huawei_vrp" and pe.serial == "2102351931P0K8000123" and pe.model == "NE40E-X8A"
    assert pe.get_interface("GE0/0/1").ipv4 == ["10.0.0.9/30"]
    link = topo.links[0]
    assert {link.source_interface, link.target_interface} == {"GigabitEthernet0/0/1", "Ethernet1"}
    stub = topo.devices["stub-core-sw-01"]
    assert stub.stub and stub.vendor == "Arista" and stub.mgmt_ip == "10.0.0.10"
