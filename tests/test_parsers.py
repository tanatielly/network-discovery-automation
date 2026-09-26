from nettopo.collectors.ssh import hostname_from_prompt, parse_cli_outputs
from nettopo.models import Device
from nettopo.vendors.parsers import parse_output
from nettopo.vendors.parsers.generic import parse_arp_generic, parse_kv_colon, parse_lldp_blocks
from nettopo.vendors.parsers.linux import lldpctl_keyvalue
from nettopo.vendors.parsers.mikrotik import mikrotik_neighbors, mikrotik_routes
from nettopo.vendors.parsers.normalize import apply_rows
from nettopo.vendors.registry import default_registry

IOS_CDP = """
-------------------------
Device ID: CORE-SW-01.corp.local
Entry address(es):
  IP address: 10.0.0.10
Platform: cisco WS-C3850-48P,  Capabilities: Router Switch IGMP
Interface: GigabitEthernet0/1,  Port ID (outgoing port): GigabitEthernet1/0/48
Holdtime : 150 sec

Version :
Cisco IOS Software, IOS-XE Software, Catalyst L3 Switch Software (CAT3K_CAA-UNIVERSALK9-M), Version 16.12.4
advertisement version: 2
Management address(es):
  IP address: 10.0.0.10

-------------------------
Device ID: AP-01
Entry address(es):
  IP address: 10.0.3.21
Platform: cisco AIR-AP2802I-E-K9,  Capabilities: Trans-Bridge Source-Route-Bridge IGMP
Interface: GigabitEthernet0/2,  Port ID (outgoing port): GigabitEthernet0
Holdtime : 120 sec

Version :
Cisco AP Software, ap3g3-k9w8 Version: 8.10.130.0

advertisement version: 2
"""

HUAWEI_LLDP = """
GigabitEthernet0/0/1 has 1 neighbor(s):

Neighbor index :1
Chassis type   :macAddress
Chassis ID     :00e0-fc12-3456
Port ID type   :interfaceName
Port ID        :GigabitEthernet0/0/2
Port description    :to-core
System name         :CORE-01
System description  :Huawei Versatile Routing Platform Software
System capabilities supported   :bridge router
System capabilities enabled     :bridge router
Management address type  :ipV4
Management address     :10.1.1.2

GigabitEthernet0/0/2 has 1 neighbor(s):

Neighbor index :1
Chassis ID     :00e0-fc12-9999
Port ID        :Ethernet1/1
System name         :ACC-02
Management address     :10.1.1.3
"""


def test_textfsm_cisco_cdp_normalizes():
    reg = default_registry()
    dev = Device(mgmt_ip="10.0.0.1")
    parse_cli_outputs(dev, reg.get("cisco_ios"), {"cdp": ("show cdp neighbors detail", IOS_CDP)})
    assert len(dev.neighbors) == 2
    n = dev.neighbors[0]
    assert n.protocol == "cdp"
    assert n.remote_hostname.startswith("CORE-SW-01")
    assert n.remote_mgmt_ip == "10.0.0.10"
    assert n.local_interface == "GigabitEthernet0/1"
    assert n.remote_interface == "GigabitEthernet1/0/48"


def test_generic_lldp_blocks_cdp_format():
    rows = parse_lldp_blocks(IOS_CDP)
    assert [r["neighbor_name"] for r in rows] == ["CORE-SW-01.corp.local", "AP-01"]
    assert rows[0]["local_interface"] == "GigabitEthernet0/1"
    assert rows[0]["neighbor_interface"] == "GigabitEthernet1/0/48"
    assert rows[1]["mgmt_address"] == "10.0.3.21"


def test_generic_lldp_blocks_huawei():
    rows = parse_lldp_blocks(HUAWEI_LLDP)
    assert len(rows) == 2
    dev = Device()
    apply_rows(dev, "lldp", rows)
    n1, n2 = dev.neighbors
    assert (n1.local_interface, n1.remote_hostname, n1.remote_interface, n1.remote_mgmt_ip) == (
        "GigabitEthernet0/0/1", "CORE-01", "GigabitEthernet0/0/2", "10.1.1.2")
    assert n1.remote_chassis_id == "00:e0:fc:12:34:56"
    assert set(n1.remote_capabilities) == {"bridge", "router"}
    assert n2.remote_hostname == "ACC-02" and n2.local_interface == "GigabitEthernet0/0/2"


def test_parse_output_falls_back_to_generic():
    rows, source = parse_output("lldp", "display lldp neighbor", HUAWEI_LLDP, "platform_without_templates")
    assert source == "generic" and len(rows) == 2


def test_mikrotik_neighbors_and_routes():
    text = (' 0 interface=ether1 address=10.0.0.2 address4=10.0.0.2 mac-address=00:0C:42:11:22:33 identity="R2" '
            'platform="MikroTik" version="7.12 (stable)"\n   board="CCR2004-1G-12S+2XS" interface-name="ether5" '
            'system-caps-enabled=bridge,router discovered-by=lldp,mndp\n'
            ' 1 interface=ether2,bridge address=10.0.0.3 identity="SW3" platform="MikroTik" board="CRS326"\n')
    rows = mikrotik_neighbors(text)
    assert len(rows) == 2
    dev = Device()
    apply_rows(dev, "other_l2", rows)
    assert dev.neighbors[0].protocol == "lldp"
    assert dev.neighbors[0].remote_interface == "ether5"
    assert dev.neighbors[0].remote_chassis_id == "00:0c:42:11:22:33"
    assert dev.neighbors[1].protocol == "mndp"
    assert dev.neighbors[1].local_interface == "ether2"
    routes = mikrotik_routes(" 0 ADS dst-address=0.0.0.0/0 gateway=10.0.0.1 immediate-gw=10.0.0.1%ether1 distance=1\n"
                             " 1 ADC dst-address=10.0.0.0/24 gateway=ether1 distance=0\n"
                             " 2 ADo dst-address=10.20.0.0/24 gateway=172.16.0.1 distance=110\n")
    assert [r["protocol"] for r in routes] == ["static", "connected", "ospf"]
    assert routes[0]["nexthop_if"] == "ether1"


def test_lldpctl_keyvalue():
    rows = lldpctl_keyvalue("lldp.eno1.chassis.name=ACC-SW-04\nlldp.eno1.chassis.mgmt-ip=10.0.2.4\n"
                            "lldp.eno1.port.ifname=ether2\nlldp.eno1.chassis.Bridge.enabled=on\n")
    assert rows == [{"local_interface": "eno1", "neighbor_name": "ACC-SW-04", "mgmt_address": "10.0.2.4",
                     "neighbor_interface": "ether2", "capabilities": ["Bridge"]}]


def test_arp_generic_and_kv():
    arp = parse_arp_generic("10.0.0.2   0011-2233-4455  1   D-0  GE0/0/1  VLAN10\n"
                            "Internet  10.0.0.3   5   aabb.ccdd.eeff  ARPA   Vlan10\n")
    assert arp[0]["mac_address"] == "00:11:22:33:44:55" and arp[0]["interface"] == "GE0/0/1"
    assert arp[1]["interface"] == "Vlan10"
    kv = parse_kv_colon("Version: FortiGate-600E v7.2.8,build1639\nSerial-Number: FG6H0E5819900001\n"
                        "Hostname: FW-01\n")
    assert kv[0]["hostname"] == "FW-01" and kv[0]["serial"] == "FG6H0E5819900001"


def test_hostname_from_prompt():
    assert hostname_from_prompt("R1#") == "R1"
    assert hostname_from_prompt("<HUAWEI-01>") == "HUAWEI-01"
    assert hostname_from_prompt("admin@mx204-01>") == "mx204-01"
    assert hostname_from_prompt("[admin@CCR-01] >") == "CCR-01"
    assert hostname_from_prompt("FW-01 (root) #") == "FW-01"
    assert hostname_from_prompt("A:PE-01#") == "PE-01"
    assert hostname_from_prompt("SW-01(config)#") == "SW-01"
