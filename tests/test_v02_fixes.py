"""Regressão dos defeitos D1-D14 encontrados no laboratório (saídas reais em tests/fixtures/real)."""

import asyncio
import random
from pathlib import Path

from nettopo.config import Settings
from nettopo.discovery.engine import DiscoveryEngine
from nettopo.discovery.identity import IdentityIndex
from nettopo.discovery.scope import next_targets
from nettopo.models import Device, DiscoveryMeta, Interface, Neighbor
from nettopo.topology.builder import build_topology
from nettopo.vendors.parsers import parse_output
from nettopo.vendors.parsers.frr import frr_bgp_json, frr_ospf_json
from nettopo.vendors.parsers.linux import linux_facts
from nettopo.vendors.parsers.mikrotik import mikrotik_bgp, mikrotik_interfaces, mikrotik_ospf, mikrotik_routes
from nettopo.vendors.parsers.normalize import apply_rows
from nettopo.vendors.registry import default_registry

REAL = Path(__file__).parent / "fixtures" / "real"


def read(rel: str) -> str:
    return (REAL / rel).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- D1 identidade

def _dev(host: str, ip: str, serial: str | None = None, mac: str | None = None) -> Device:
    return Device(hostname=host, mgmt_ip=ip, serial=serial, chassis_id=mac)


def test_d1_generic_serials_do_not_merge():
    idx = IdentityIndex()
    for host, ip in (("dist-frr1", "172.20.20.31"), ("srv1", "172.20.20.41"), ("srv2", "172.20.20.42")):
        idx.add(_dev(host, ip, serial="Virtual Machine"))
    idx.add(_dev("core-srl1", "172.20.20.21", serial="Sim Serial No."))
    idx.add(_dev("core-srl2", "172.20.20.22", serial="Sim Serial No."))
    assert sorted(idx.devices) == ["core-srl1", "core-srl2", "dist-frr1", "srv1", "srv2"]


def test_d1_repeated_unknown_serial_becomes_ambiguous():
    idx = IdentityIndex()
    idx.add(_dev("sw-a", "10.0.0.1", serial="ABC12345"))
    idx.add(_dev("sw-b", "10.0.0.2", serial="ABC12345"))  # placeholder não listado, mesmo valor
    assert len(idx.devices) == 2 and "ABC12345" in idx.ambiguous_serials
    idx.add(_dev(None, "10.0.0.9", serial="ABC12345"))  # série ambígua não identifica mais ninguém
    assert len(idx.devices) == 3


def test_d1_same_device_twice_still_merges():
    idx = IdentityIndex()
    idx.add(_dev("edge-mk2", "172.20.20.12", serial="9KJ8-ABCD"))
    idx.add(_dev("edge-mk2", "10.255.0.2", serial="9KJ8-ABCD"))
    assert len(idx.devices) == 1


def test_d1_linux_facts_never_uses_product_name_as_serial():
    assert "serial" not in linux_facts(read("linux/facts_srv1.txt"))[0]
    row = linux_facts("NT_OS=Debian 12\nNT_KERNEL=6.1\nNT_SERIAL=\nNT_PRODUCT=Virtual Machine\nNT_ROUTING=bgpd,zebra,")[0]
    assert "serial" not in row and row["routing_daemons"] == ["bgpd", "zebra"]


# --------------------------------------------------------------------------- D7, D10 RouterOS

def test_d7_routeros7_routes_without_index():
    routes = mikrotik_routes(read("routeros/ip_route_print_terse.txt"))
    assert len(routes) == 6
    assert [r["protocol"] for r in routes].count("connected") == 4
    assert {"static", "bgp"} <= {r["protocol"] for r in routes}


def test_routeros_interface_comments():
    rows = {r["interface"]: r["description"] for r in mikrotik_interfaces(read("routeros/interface_print_detail.txt"))}
    assert rows["ether2"] == "Uplink operadora" and rows["ether4"] == "Core SRL1"


def test_d10_routeros_ospf_bgp_cli():
    assert mikrotik_ospf(read("routeros/routing_ospf_neighbor_print_detail.txt")) == [
        {"address": "10.255.0.2", "neighbor_id": "10.255.255.2", "state": "Full", "interface": None}]
    assert mikrotik_bgp(read("routeros/routing_bgp_session_print_detail.txt")) == [
        {"neighbor": "200.200.10.1", "remote_as": "64500", "state": "Established"}]


def test_d10_frr_json():
    bgp = frr_bgp_json('{"ipv4Unicast":{"peers":{"200.200.10.2":{"remoteAs":65001,"state":"Established"}}}}')
    ospf = frr_ospf_json('{"neighbors":{"10.255.255.2":[{"address":"10.255.0.2","ifaceName":"eth1:10.255.0.1",'
                         '"nbrState":"Full/DR"}]}}')
    d = Device()
    apply_rows(d, "bgp", bgp)
    apply_rows(d, "ospf", ospf)
    assert [(n.protocol, n.remote_mgmt_ip) for n in d.neighbors] == [("bgp", "200.200.10.2"), ("ospf", "10.255.0.2")]


# --------------------------------------------------------------------------- D8 SR Linux CLI

def test_d8_srlinux_tables():
    d = Device()
    for kind, cmd, f in (("lldp", "show system lldp neighbor", "show_system_lldp_neighbor.txt"),
                         ("ip_interfaces", "show interface brief", "show_interface_brief.txt"),
                         ("arp", "show arpnd arp-entries", "show_arpnd_arp_entries.txt"),
                         ("facts", "show version", "show_version.txt")):
        rows, _ = parse_output(kind, cmd, read(f"srlinux/{f}"), "nokia_srl")
        assert apply_rows(d, kind, rows) > 0, kind
    assert {(n.local_interface, n.remote_hostname) for n in d.neighbors} >= {("ethernet-1/1", "edge-mk1"),
                                                                              ("ethernet-1/3", "dist-frr1")}
    assert d.get_interface("ethernet-1/1").description == "to edge-mk1 ether4"
    assert d.chassis_id == "1a:97:00:ff:00:00" and d.model == "7220 IXR-D2L"


# --------------------------------------------------------------------------- D2, D5, determinismo

def _lab_pair() -> dict[str, Device]:
    mk = Device(id="edge-mk1", hostname="edge-mk1", mgmt_ip="172.20.20.11",
                interfaces=[Interface(name="ether4", ipv4=["10.10.1.1/30"])],
                neighbors=[Neighbor(protocol="lldp", local_interface="ether4", remote_hostname="core-srl1",
                                    remote_interface="to edge-mk1 ether4", remote_mgmt_ip="172.20.20.21")])
    srl = Device(id="core-srl1", hostname="core-srl1", mgmt_ip="172.20.20.21",
                 interfaces=[Interface(name="ethernet-1/1", description="to edge-mk1 ether4", ipv4=["10.10.1.2/30"]),
                             Interface(name="mgmt0", ipv4=["172.20.20.21/24"])],
                 neighbors=[Neighbor(protocol="lldp", local_interface="ethernet-1/1", remote_hostname="edge-mk1",
                                     remote_interface="ether4"),
                            Neighbor(protocol="lldp", local_interface="mgmt0", remote_hostname="core-srl2",
                                     remote_interface="mgmt0", remote_mgmt_ip="172.20.20.22")])
    return {"edge-mk1": mk, "core-srl1": srl}


def test_d2_d5_one_link_with_own_port_names_and_no_mgmt_link():
    topo = build_topology(_lab_pair())
    phys = [lk for lk in topo.links if lk.kind == "physical"]
    assert len(phys) == 1
    lk = phys[0]
    assert {(lk.source, lk.source_interface), (lk.target, lk.target_interface)} == {
        ("core-srl1", "ethernet-1/1"), ("edge-mk1", "ether4")}
    assert "stub-core-srl2" not in topo.devices  # visto só pela gerência: ignorado
    assert topo.meta.stats["ignored_mgmt_neighbors"] == 1


def test_d2_port_announced_as_mac_resolves():
    devs = _lab_pair()
    devs["edge-mk1"].interfaces[0].mac = "0c:00:ee:b3:0d:03"
    devs["core-srl1"].neighbors[0].remote_interface = "0C:00:EE:B3:0D:03"
    phys = [lk for lk in build_topology(devs).links if lk.kind == "physical"]
    assert len(phys) == 1 and {phys[0].source_interface, phys[0].target_interface} == {"ether4", "ethernet-1/1"}


def test_graph_is_deterministic():
    from nettopo.collectors.simulated import SimulatedCollector

    sim = SimulatedCollector()
    sigs = set()
    for seed in range(3):
        items = list(sim.devices.items())
        random.Random(seed).shuffle(items)
        devs = {}
        for host, d in items:
            c = d.model_copy(deep=True)
            c.id = host.lower()
            c.extra.pop("caps", None)
            if sim.reachable[host]:
                devs[c.id] = c
        topo = build_topology(devs)
        sigs.add(tuple((lk.id, lk.source, lk.source_interface, lk.target, lk.target_interface) for lk in topo.links))
    assert len(sigs) == 1


# --------------------------------------------------------------------------- D6, D12

def test_d6_identical_ips_do_not_create_l3_link():
    a = Device(id="a", hostname="a", interfaces=[Interface(name="ether1", ipv4=["172.31.255.30/30"])])
    b = Device(id="b", hostname="b", interfaces=[Interface(name="ether1", ipv4=["172.31.255.30/30"])])
    assert not build_topology({"a": a, "b": b}).links


def test_d12_bgp_peer_joins_lldp_neighbor():
    mk = Device(id="edge-mk1", hostname="edge-mk1", mgmt_ip="172.20.20.11",
                interfaces=[Interface(name="ether2", ipv4=["200.200.10.2/30"])],
                neighbors=[Neighbor(protocol="lldp", local_interface="ether2", remote_hostname="isp-pe",
                                    remote_interface="eth1", remote_mgmt_ip="172.20.20.2"),
                           Neighbor(protocol="bgp", remote_mgmt_ip="200.200.10.1", remote_asn=64500,
                                    state="Established")])
    topo = build_topology({"edge-mk1": mk})
    assert sorted(topo.devices) == ["edge-mk1", "stub-isp-pe"]
    assert topo.links[0].protocols == ["bgp", "lldp"]
    assert topo.devices["stub-isp-pe"].extra["asn"] == 64500


# --------------------------------------------------------------------------- papéis

def test_linux_router_needs_routing_software():
    srv = Device(id="srv1", hostname="srv1", profile="linux", interfaces=[Interface(name="eth1", ipv4=["10.0.0.1/24"])])
    frr = Device(id="frr", hostname="frr", profile="linux", extra={"routing_daemons": ["zebra", "bgpd"]})
    topo = build_topology({"srv1": srv, "frr": frr})
    topo.devices["srv1"].extra["capabilities"] = ["router"]  # lldpd com ip_forward ligado
    from nettopo.topology.roles import classify

    classify(topo, default_registry())
    assert topo.devices["srv1"].role == "server" and topo.devices["frr"].role == "router"


# --------------------------------------------------------------------------- D3, D9 candidatos

def test_d3_candidates_and_scope():
    s = Settings(scope={"include": ["172.20.20.0/24", "10.0.0.0/8"]}, dns_resolve=False)
    d = Device(neighbors=[
        Neighbor(protocol="lldp", remote_hostname="edge-mk2", remote_mgmt_ip="10.255.0.2", remote_chassis_id="0c:00:aa:bb:cc:02"),
        Neighbor(protocol="lldp", remote_hostname="isp", remote_mgmt_ip="200.200.10.1"),  # fora do escopo
    ])

    class Hints:
        def ips_for_host(self, h):
            return ["172.20.20.12"] if h == "edge-mk2" else []

        def ips_for_mac(self, m):
            return []

    targets = asyncio.run(next_targets(d, s, Hints()))
    assert [t.candidates for t in targets] == [[("172.20.20.12", "memoria"), ("10.255.0.2", "anunciado")]]


class _FlakyCollector:
    """Simula um equipamento que só responde pelo IP de gerência, não pelo IP anunciado."""

    def __init__(self):
        self.calls = []

    async def collect(self, target):
        self.calls.append(target)
        if target == "172.20.20.11":
            return Device(hostname="edge-mk1", mgmt_ip=target, neighbors=[
                Neighbor(protocol="lldp", local_interface="ether3", remote_hostname="edge-mk2",
                         remote_interface="ether3", remote_mgmt_ip="10.255.0.2")])
        if target == "172.20.20.12":
            return Device(hostname="edge-mk2", mgmt_ip=target, interfaces=[Interface(name="ether3")],
                          neighbors=[Neighbor(protocol="lldp", local_interface="ether3", remote_hostname="edge-mk1",
                                              remote_interface="ether3", remote_mgmt_ip="10.255.0.1")])
        return Device(mgmt_ip=target, reachable=False, errors=["sem resposta"])

    async def close(self):
        return None


def test_d3_unreachable_advertised_ip_falls_back_and_explains():
    s = Settings(seeds=["172.20.20.11"], scope={"include": ["172.20.20.0/24", "10.0.0.0/8"]}, dns_resolve=False)
    # sem memória: edge-mk2 vira "não coletado" com motivo explícito
    topo = asyncio.run(DiscoveryEngine(s, collector=_FlakyCollector()).run())
    stub = topo.devices["stub-edge-mk2"]
    assert "IP anunciado 10.255.0.2" in stub.extra["motivo"] and "nenhum outro IP" in stub.extra["motivo"]
    # com memória (execução anterior): coleta pelo IP de gerência, sem tentar o IP anunciado
    col = _FlakyCollector()
    topo = asyncio.run(DiscoveryEngine(s, collector=col, known_hosts={"edge-mk2": ["172.20.20.12"]}).run())
    assert {d.hostname for d in topo.devices.values() if not d.stub} == {"edge-mk1", "edge-mk2"}
    assert "10.255.0.2" not in col.calls and not topo.meta.failed_targets
    assert len([lk for lk in topo.links if lk.kind == "physical"]) == 1


def test_meta_has_no_extraneous_failures():
    assert DiscoveryMeta().failed_targets == {}


# --------------------------------------------------------------------------- D4 identificação por SSH

def test_d4_ssh_banner_and_prompt_identification():
    reg = default_registry()
    assert [p.id for p in reg.match_banner("SSH-2.0-ROSSSH")] == ["mikrotik_routeros"]
    assert {p.id for p in reg.match_prompt("A:core-srl1#")} == {"nokia_srl", "nokia_sros"}
    assert reg.match_snmp(None, read("srlinux/show_version.txt")).id == "nokia_srl"
    assert reg.match_snmp(None, "Linux srv1 6.17.0 #22-Ubuntu SMP x86_64 GNU/Linux").id == "linux"


def test_l3_inference_ignores_interfaces_down():
    a = Device(id="a", hostname="a", interfaces=[Interface(name="e1", ipv4=["10.10.4.1/30"], oper_up=True)])
    b = Device(id="b", hostname="b", interfaces=[Interface(name="eth2", ipv4=["10.10.4.2/30"], oper_up=False)])
    assert not build_topology({"a": a, "b": b}).links
    b.interfaces[0].oper_up = True
    assert [lk.kind for lk in build_topology({"a": a, "b": b}).links] == ["l3"]
