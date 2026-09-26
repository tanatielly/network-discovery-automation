import pytest

from nettopo.config import Scope, load_settings
from nettopo.utils import (
    canonical_ifname,
    ifname_key,
    ip_with_prefix,
    normalize_mac,
    parse_speed_mbps,
    short_hostname,
    short_ifname,
    slugify,
)
from nettopo.vendors.registry import default_registry


@pytest.mark.parametrize("raw", ["aabb.ccdd.eeff", "AA-BB-CC-DD-EE-FF", "aabb-ccdd-eeff", "aa:bb:cc:dd:ee:ff",
                                 b"\xaa\xbb\xcc\xdd\xee\xff", "0xAABBCCDDEEFF"])
def test_normalize_mac(raw):
    assert normalize_mac(raw) == "aa:bb:cc:dd:ee:ff"


def test_normalize_mac_invalid():
    assert normalize_mac("GigabitEthernet0/1") is None
    assert normalize_mac("0:1c:2:3:4:5") == "00:1c:02:03:04:05"


@pytest.mark.parametrize("a,b", [("Gi0/1", "GigabitEthernet0/1"), ("Te1/0/1", "TenGigabitEthernet1/0/1"),
                                 ("Et1", "Ethernet1"), ("Eth1/1", "Ethernet1/1"), ("Po10", "Port-channel10"),
                                 ("GE0/0/1", "GigabitEthernet0/0/1"), ("XGE0/0/1", "XGigabitEthernet0/0/1")])
def test_interface_names(a, b):
    assert canonical_ifname(a) == b
    assert ifname_key(a) == ifname_key(b)


def test_interface_names_untouched():
    assert canonical_ifname("ge-0/0/0") == "ge-0/0/0"
    assert canonical_ifname("eth0") == "eth0"
    assert canonical_ifname("ether1") == "ether1"
    assert short_ifname("GigabitEthernet0/0/1") == "Gi0/0/1"


def test_ip_helpers():
    assert ip_with_prefix("10.0.0.1", "255.255.255.252") == "10.0.0.1/30"
    assert ip_with_prefix("10.0.0.1 255.255.255.0") == "10.0.0.1/24"
    assert ip_with_prefix("10.0.0.1/31") == "10.0.0.1/31"
    assert ip_with_prefix("unassigned") is None
    assert parse_speed_mbps("1000000 Kbit") == 1000
    assert parse_speed_mbps("10G") == 10000


def test_hostnames_and_slug():
    assert short_hostname("SW1.corp.local") == "sw1"
    assert short_hostname("SW1(FOX1234)") == "sw1"
    assert short_hostname("10.0.0.1") == "10.0.0.1"
    assert slugify("Demo - Campus") == "demo-campus"


def test_scope_defaults_to_private():
    s = Scope()
    assert s.allows_ip("10.1.2.3")
    assert not s.allows_ip("8.8.8.8")
    s = Scope(include=["10.0.0.0/8"], exclude=["10.99.0.0/16"])
    assert not s.allows_ip("10.99.1.1")
    assert s.allows_ip("10.1.1.1")


def test_settings_env_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("NT_PASS", "s3cret")
    cfg = tmp_path / "c.yaml"
    cfg.write_text("seeds: [10.0.0.1]\ncredentials:\n  - type: ssh\n    username: ${NT_USER:-admin}\n"
                   "    password: ${NT_PASS}\n  - type: snmp\n    version: 2c\n    community: public\n")
    s = load_settings(cfg)
    assert s.credentials[0].username == "admin"
    assert s.credentials[0].secret("password") == "s3cret"
    assert s.sanitized()["credentials"][0]["password"] == "***"


def test_registry_matches():
    reg = default_registry()
    assert reg.match_snmp("1.3.6.1.4.1.9.12.3.1.3.1812", "Cisco NX-OS(tm) n9000").id == "cisco_nxos"
    assert reg.match_snmp("1.3.6.1.4.1.9.1.2066", "Cisco IOS Software [Amsterdam], ISR Software").id == "cisco_ios"
    assert reg.match_snmp("1.3.6.1.4.1.2636.1.1.1.2.21", "Juniper Networks, Inc. mx204").id == "juniper_junos"
    assert reg.match_snmp("1.3.6.1.4.1.14988.1", "RouterOS CRS326-24G-2S+").id == "mikrotik_routeros"
    assert reg.match_snmp("1.3.6.1.4.1.2011.2.23.1", "Huawei Versatile Routing Platform").id == "huawei_vrp"
    assert reg.match_snmp(None, "Arista Networks EOS version 4.31").id == "arista_eos"
    assert reg.match_snmp("1.3.6.1.4.1.99999.1", "Totally unknown box") is None


def test_all_profiles_use_valid_netmiko_drivers():
    from netmiko.ssh_dispatcher import CLASS_MAPPER

    reg = default_registry()
    assert len(reg.all()) >= 30
    for p in reg.all():
        if p.netmiko:
            assert p.netmiko in CLASS_MAPPER, p.id
