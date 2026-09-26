"""Interpretação de dados SNMP, REST e NETCONF (sem acesso à rede)."""

from nettopo.collectors.netconf import parse_junos_lldp, parse_openconfig_interfaces, parse_openconfig_lldp
from nettopo.collectors.rest import EapiDriver, MikrotikRestDriver, NxapiDriver
from nettopo.collectors.snmp import build_device
from nettopo.models import Device
from nettopo.vendors.registry import default_registry


def test_snmp_build_device():
    system = {"descr": b"Cisco IOS Software, C3900 Software, Version 15.7(3)M5", "object_id": "1.3.6.1.4.1.9.1.1041",
              "name": b"R1.corp", "uptime": 8640000, "location": b"DC1"}
    walks = {
        "ifDescr": {(1,): b"GigabitEthernet0/0", (2,): b"GigabitEthernet0/1"},
        "ifName": {(1,): b"Gi0/0", (2,): b"Gi0/1"},
        "ifHighSpeed": {(1,): 1000, (2,): 1000},
        "ifOperStatus": {(1,): 1, (2,): 2},
        "ifAdminStatus": {(1,): 1, (2,): 1},
        "ifPhysAddress": {(1,): b"\x00\x11\x22\x33\x44\x55"},
        "ipAdEntIfIndex": {(10, 0, 0, 1): 1},
        "ipAdEntNetMask": {(10, 0, 0, 1): b"\xff\xff\xff\xfc"},
        "entPhysicalClass": {(1,): 3},
        "entPhysicalSerialNum": {(1,): b"FTX1234"},
        "entPhysicalModelName": {(1,): b"CISCO3945-CHASSIS"},
        "lldpLocPortIdSubtype": {(1,): 5},
        "lldpLocPortId": {(1,): b"Gi0/0"},
        "lldpRemChassisIdSubtype": {(0, 1, 1): 4},
        "lldpRemChassisId": {(0, 1, 1): b"\xaa\xbb\xcc\xdd\xee\xff"},
        "lldpRemPortIdSubtype": {(0, 1, 1): 5},
        "lldpRemPortId": {(0, 1, 1): b"Ethernet1"},
        "lldpRemSysName": {(0, 1, 1): b"CORE-SW-01"},
        "lldpRemSysCapEnabled": {(0, 1, 1): b"\x28\x00"},  # bridge + router
        "lldpRemManAddrIfSubtype": {(0, 1, 1, 1, 4, 10, 0, 0, 2): 2},
        "cdpCacheDeviceId": {(2, 5): b"SW2(FOC123)"},
        "cdpCacheAddress": {(2, 5): b"\x0a\x00\x00\x03"},
        "cdpCacheDevicePort": {(2, 5): b"GigabitEthernet1/0/1"},
        "cdpCachePlatform": {(2, 5): b"cisco WS-C2960X-48FPD-L"},
        "cdpCacheCapabilities": {(2, 5): b"\x00\x00\x00\x28"},
        "ipNetToMediaPhysAddress": {(1, 10, 0, 0, 2): b"\xaa\xbb\xcc\xdd\xee\xff"},
        "ospfNbrRtrId": {(10, 0, 0, 2, 0): b"\x0a\x00\x00\x02"},
        "ospfNbrState": {(10, 0, 0, 2, 0): 8},
        "bgpPeerState": {(200, 1, 1, 1): 6},
        "bgpPeerRemoteAs": {(200, 1, 1, 1): 64500},
    }
    d = build_device("10.0.0.1", system, walks, registry=default_registry())
    assert d.hostname == "R1.corp" and d.profile == "cisco_ios" and d.vendor == "Cisco"
    assert d.serial == "FTX1234" and d.model == "CISCO3945-CHASSIS"
    assert d.os_version == "15.7(3)M5"
    gi0 = d.get_interface("Gi0/0")
    assert gi0.ipv4 == ["10.0.0.1/30"] and gi0.mac == "00:11:22:33:44:55" and gi0.oper_up
    lldp = [n for n in d.neighbors if n.protocol == "lldp"][0]
    assert (lldp.local_interface, lldp.remote_hostname, lldp.remote_interface, lldp.remote_mgmt_ip) == (
        "GigabitEthernet0/0", "CORE-SW-01", "Ethernet1", "10.0.0.2")
    assert set(lldp.remote_capabilities) == {"bridge", "router"}
    cdp = [n for n in d.neighbors if n.protocol == "cdp"][0]
    assert cdp.remote_mgmt_ip == "10.0.0.3" and cdp.local_interface == "GigabitEthernet0/1"
    assert "router" in cdp.remote_capabilities or "bridge" in cdp.remote_capabilities
    assert d.arp[0].ip == "10.0.0.2" and d.arp[0].interface == "GigabitEthernet0/0"
    ospf = [n for n in d.neighbors if n.protocol == "ospf"][0]
    assert ospf.remote_mgmt_ip == "10.0.0.2" and ospf.state == "full"
    bgp = [n for n in d.neighbors if n.protocol == "bgp"][0]
    assert bgp.remote_asn == 64500 and bgp.state == "established"


def test_eapi_parse():
    raw = {
        "show version": {"modelName": "DCS-7280SR3-48YC8", "version": "4.31.2F", "serialNumber": "JPE1",
                         "systemMacAddress": "00:1c:73:aa:bb:cc"},
        "show hostname": {"hostname": "CORE-SW-01"},
        "show interfaces": {"interfaces": {"Ethernet1": {
            "description": "to FW", "physicalAddress": "00:1c:73:00:00:01", "mtu": 9214, "bandwidth": 10_000_000_000,
            "lineProtocolStatus": "up", "interfaceStatus": "connected",
            "interfaceAddress": [{"primaryIp": {"address": "10.10.0.3", "maskLen": 29}}]}}},
        "show lldp neighbors detail": {"lldpNeighbors": {"Ethernet1": {"lldpNeighborInfo": [{
            "systemName": "FW-01", "chassisId": "0009.0f00.0001",
            "neighborInterfaceInfo": {"interfaceId_v2": "port2"},
            "managementAddresses": [{"address": "10.0.0.3", "addressType": "ipv4"}],
            "systemCapabilities": {"router": True}}]}}},
    }
    d = Device()
    EapiDriver.parse(raw, d)
    assert d.hostname == "CORE-SW-01" and d.serial == "JPE1"
    assert d.interfaces[0].ipv4 == ["10.10.0.3/29"] and d.interfaces[0].speed_mbps == 10000
    n = d.neighbors[0]
    assert (n.remote_hostname, n.remote_interface, n.remote_mgmt_ip) == ("FW-01", "port2", "10.0.0.3")


def test_nxapi_parse():
    raw = {
        "show version": {"host_name": "N9K", "nxos_ver_str": "10.3(4a)", "chassis_id": "Nexus9000 C93180YC-FX",
                         "proc_board_id": "FDO1"},
        "show lldp neighbors detail": {"TABLE_nbor_detail": {"ROW_nbor_detail": [
            {"l_port_id": "Eth1/1", "sys_name": "FW-02", "port_id": "ethernet1/2", "mgmt_addr": "10.0.0.4"}]}},
        "show cdp neighbors detail": {"TABLE_cdp_neighbor_detail_info": {"ROW_cdp_neighbor_detail_info": {
            "intf_id": "Ethernet1/3", "device_id": "DIST(FOX1)", "port_id": "1/1/2", "v4mgmtaddr": "10.0.1.2",
            "platform_id": "Aruba 8360", "capability": ["router", "switch"]}}},
    }
    d = Device()
    NxapiDriver.parse(raw, d)
    assert d.hostname == "N9K" and d.serial == "FDO1"
    assert d.neighbors[0].local_interface == "Ethernet1/1"
    assert d.neighbors[1].protocol == "cdp" and d.neighbors[1].remote_mgmt_ip == "10.0.1.2"


def test_mikrotik_rest_parse():
    raw = {"identity": {"name": "BR-01"}, "resource": {"board-name": "CCR2004", "version": "7.14.3"},
           "interfaces": [{"name": "ether1", "mac-address": "48:8F:5A:00:00:01", "running": "true", "disabled": "false"}],
           "addresses": [{"address": "172.16.0.2/30", "interface": "ether1"}],
           "neighbors": [{"interface": "ether1", "identity": "EDGE", "address4": "172.16.0.1",
                          "interface-name": "Gi0/0/3", "discovered-by": "cdp"}]}
    d = Device()
    MikrotikRestDriver.parse(raw, d)
    assert d.hostname == "BR-01" and d.interfaces[0].ipv4 == ["172.16.0.2/30"]
    assert d.neighbors[0].protocol == "cdp" and d.neighbors[0].remote_interface == "Gi0/0/3"


OC_LLDP = """<data><lldp xmlns="http://openconfig.net/yang/lldp"><interfaces><interface><name>ethernet-1/1</name>
<neighbors><neighbor><id>1</id><state><system-name>leaf2</system-name><port-id>ethernet-1/49</port-id>
<chassis-id>1A:2B:3C:4D:5E:6F</chassis-id><management-address>10.0.9.2</management-address></state>
</neighbor></neighbors></interface></interfaces></lldp></data>"""

OC_IFS = """<data><interfaces xmlns="http://openconfig.net/yang/interfaces"><interface><name>ethernet-1/1</name>
<state><admin-status>UP</admin-status><oper-status>UP</oper-status><mtu>9232</mtu></state>
<subinterfaces><subinterface><index>0</index><ipv4><addresses><address><ip>10.9.0.1</ip>
<state><ip>10.9.0.1</ip><prefix-length>31</prefix-length></state></address></addresses></ipv4></subinterface>
</subinterfaces></interface></interfaces></data>"""

JUNOS_LLDP = """<lldp-neighbors-information><lldp-neighbor-information>
<lldp-local-port-id>xe-0/1/2</lldp-local-port-id><lldp-remote-chassis-id>00:11:22:33:44:55</lldp-remote-chassis-id>
<lldp-remote-port-id>Gi0/0/2</lldp-remote-port-id><lldp-remote-system-name>EDGE-RTR-01</lldp-remote-system-name>
</lldp-neighbor-information></lldp-neighbors-information>"""


def test_netconf_parsers():
    nbs = parse_openconfig_lldp(OC_LLDP)
    assert len(nbs) == 1 and nbs[0].remote_hostname == "leaf2" and nbs[0].remote_mgmt_ip == "10.0.9.2"
    d = Device()
    parse_openconfig_interfaces(OC_IFS, d)
    assert d.interfaces[0].ipv4 == ["10.9.0.1/31"] and d.interfaces[0].oper_up is True
    j = parse_junos_lldp(JUNOS_LLDP)
    assert j[0].local_interface == "xe-0/1/2" and j[0].remote_hostname == "EDGE-RTR-01"
