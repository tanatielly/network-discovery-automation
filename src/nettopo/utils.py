"""Funções utilitárias de normalização (MAC, IP, nomes de interface, hostnames)."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable
from typing import Any

_IPV4_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?:/(\d{1,2}))?(?![\d.])")
_NON_MAC_CHARS = re.compile(r"[^0-9a-fA-F:.\-\s]")


# --------------------------------------------------------------------------- MAC

def normalize_mac(value: Any) -> str | None:
    """Converte qualquer formato de MAC para ``aa:bb:cc:dd:ee:ff``.

    Aceita ``aabb.ccdd.eeff`` (Cisco), ``aabb-ccdd-eeff`` (Huawei/H3C),
    ``aa-bb-cc-dd-ee-ff`` (Windows), ``aa:bb:..`` e bytes crus (SNMP).
    """
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        if len(value) != 6:
            return None
        return ":".join(f"{b:02x}" for b in value)
    s = str(value).strip()
    if not s:
        return None
    if s.lower().startswith("0x"):
        s = s[2:]
    if _NON_MAC_CHARS.search(s):
        return None
    parts = re.split(r"[:\-\s]", s)
    if len(parts) == 6 and all(1 <= len(p) <= 2 for p in parts):
        hexchars = "".join(p.zfill(2) for p in parts)
    else:
        hexchars = re.sub(r"[^0-9a-fA-F]", "", s)
    if len(hexchars) != 12:
        return None
    return ":".join(hexchars[i : i + 2] for i in range(0, 12, 2)).lower()


# --------------------------------------------------------------------------- IP

def parse_ipv4(value: Any) -> str | None:
    """Retorna o IPv4 (sem prefixo) contido em ``value`` ou ``None``."""
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)) and len(value) == 4:
        return ".".join(str(b) for b in value)
    s = str(value).strip().split("/")[0].split("%")[0]
    try:
        ip = ipaddress.ip_address(s)
    except ValueError:
        return None
    return str(ip) if ip.version == 4 else None


def extract_ipv4s(text: str) -> list[str]:
    """Extrai todos os IPv4 válidos de um texto livre."""
    out: list[str] = []
    for m in _IPV4_RE.finditer(text or ""):
        ip = parse_ipv4(m.group(1))
        if ip and ip not in out:
            out.append(ip)
    return out


def is_usable_ip(ip: str | None) -> bool:
    """IP que faz sentido usar como alvo de gerência."""
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (
        addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_unspecified
        or addr.is_reserved
        or str(addr) == "255.255.255.255"
    )


def mask_to_prefix(mask: Any) -> int | None:
    if mask is None:
        return None
    s = str(mask).strip().lstrip("/")
    if s.isdigit():
        n = int(s)
        return n if 0 <= n <= 32 else None
    try:
        return ipaddress.IPv4Network(f"0.0.0.0/{s}").prefixlen
    except (ValueError, ipaddress.NetmaskValueError):
        return None


def ip_with_prefix(ip: Any, prefix: Any = None) -> str | None:
    """Monta ``a.b.c.d/nn``; aceita ``ip`` já com prefixo ou ``prefix`` em máscara/decimal."""
    if ip is None:
        return None
    s = str(ip).strip()
    if "/" in s:
        addr, _, pfx = s.partition("/")
        prefix = prefix if prefix not in (None, "") else pfx
        s = addr
    else:
        parts = s.split()
        if len(parts) == 2:  # "10.0.0.1 255.255.255.0" (FortiOS, ASA)
            s, prefix = parts
    addr = parse_ipv4(s)
    if not addr:
        return None
    pfx = mask_to_prefix(prefix) if prefix not in (None, "") else None
    return f"{addr}/{pfx}" if pfx is not None else addr


def ip_only(value: str) -> str:
    return value.split("/")[0]


def network_of(ip_cidr: str) -> ipaddress.IPv4Network | None:
    if "/" not in ip_cidr:
        return None
    try:
        return ipaddress.IPv4Interface(ip_cidr).network
    except ValueError:
        return None


# --------------------------------------------------------------------------- Interfaces

_IF_CANON: dict[str, str] = {
    "gi": "GigabitEthernet", "gig": "GigabitEthernet", "gigabitethernet": "GigabitEthernet",
    "gigabitethernet ": "GigabitEthernet", "ge": "GigabitEthernet", "gigaethernet": "GigabitEthernet",
    "fa": "FastEthernet", "fas": "FastEthernet", "fastethernet": "FastEthernet",
    "te": "TenGigabitEthernet", "ten": "TenGigabitEthernet", "tengig": "TenGigabitEthernet",
    "tengige": "TenGigabitEthernet", "tengigabitethernet": "TenGigabitEthernet",
    "tw": "TwoGigabitEthernet", "twogigabitethernet": "TwoGigabitEthernet",
    "twe": "TwentyFiveGigE", "twentyfivegige": "TwentyFiveGigE",
    "twentyfivegigabitethernet": "TwentyFiveGigE",
    "fo": "FortyGigabitEthernet", "fortygige": "FortyGigabitEthernet",
    "fortygigabitethernet": "FortyGigabitEthernet",
    "hu": "HundredGigE", "hundredgige": "HundredGigE", "hundredgigabitethernet": "HundredGigE",
    "et": "Ethernet", "eth": "Ethernet", "ethernet": "Ethernet",
    "po": "Port-channel", "port-channel": "Port-channel", "portchannel": "Port-channel",
    "vl": "Vlan", "vlan": "Vlan", "vlanif": "Vlanif",
    "lo": "Loopback", "loopback": "Loopback",
    "tu": "Tunnel", "tunnel": "Tunnel",
    "se": "Serial", "serial": "Serial",
    "mg": "mgmt", "mgmt": "mgmt", "management": "Management", "ma": "Management",
    "xge": "XGigabitEthernet", "xgigabitethernet": "XGigabitEthernet",
    "eth-trunk": "Eth-Trunk", "bundle-ether": "Bundle-Ether", "be": "Bundle-Ether",
    "ten-gigabitethernet": "Ten-GigabitEthernet", "bagg": "Bridge-Aggregation",
    "bridge-aggregation": "Bridge-Aggregation",
}

_IF_SHORT: dict[str, str] = {
    "GigabitEthernet": "Gi", "FastEthernet": "Fa", "TenGigabitEthernet": "Te",
    "TwoGigabitEthernet": "Tw", "TwentyFiveGigE": "Twe", "FortyGigabitEthernet": "Fo",
    "HundredGigE": "Hu", "Ethernet": "Eth", "Port-channel": "Po", "Loopback": "Lo",
    "Tunnel": "Tu", "Serial": "Se", "XGigabitEthernet": "XGE", "Management": "Mgmt",
    "Ten-GigabitEthernet": "XGE", "Bridge-Aggregation": "BAGG", "Bundle-Ether": "BE",
}

_IF_SPLIT = re.compile(r"^([A-Za-z][A-Za-z\-]*?)\s*(\d.*)$")


def canonical_ifname(name: str | None) -> str | None:
    """Expande abreviações de interface (Gi0/1 -> GigabitEthernet0/1)."""
    if name is None:
        return None
    s = str(name).strip().strip('"')
    if not s:
        return None
    m = _IF_SPLIT.match(s)
    if not m:
        return s
    prefix, rest = m.group(1), m.group(2)
    if prefix.lower() == "eth" and "/" not in rest:  # Linux "eth0" não é "Ethernet0"
        return s
    canon = _IF_CANON.get(prefix.lower())
    return f"{canon}{rest}" if canon else f"{prefix}{rest}"


def ifname_key(name: str | None) -> str:
    """Chave de comparação de interfaces, insensível a abreviações e caixa."""
    c = canonical_ifname(name)
    return re.sub(r"\s+", "", c).lower() if c else ""


def short_ifname(name: str | None) -> str:
    """Forma curta para rótulos (GigabitEthernet0/1 -> Gi0/1)."""
    c = canonical_ifname(name) or ""
    m = _IF_SPLIT.match(c)
    if m and m.group(1) in _IF_SHORT:
        return f"{_IF_SHORT[m.group(1)]}{m.group(2)}"
    return c


# --------------------------------------------------------------------------- Hostnames

_DEFAULT_HOSTNAMES = {
    "router", "switch", "localhost", "mikrotik", "huawei", "h3c", "fortigate", "ubnt",
    "edgeswitch", "unifi", "hp", "procurve", "arista", "juniper", "cisco", "ruijie",
    "datacom", "dmos", "vyos", "openwrt", "sw", "ap", "firewall", "none", "unknown",
}


def short_hostname(name: str | None) -> str | None:
    """Normaliza hostname: remove domínio, serial do CDP ``SW1(FOX123)``, aspas e caixa."""
    if not name:
        return None
    s = str(name).strip().strip('"').strip()
    s = re.sub(r"\(.*\)$", "", s).strip()
    if not s:
        return None
    try:
        ipaddress.ip_address(s)
        return s  # não corta IPs
    except ValueError:
        pass
    return s.split(".")[0].lower() or None


def is_default_hostname(name: str | None) -> bool:
    return (short_hostname(name) or "") in _DEFAULT_HOSTNAMES


def slugify(value: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    s = re.sub(r"-{2,}", "-", s).strip("-").lower()
    return s or "device"


# --------------------------------------------------------------------------- Diversos

def first(values: Iterable[Any], default: Any = None) -> Any:
    for v in values:
        if v not in (None, "", [], {}):
            return v
    return default


def to_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    m = re.search(r"-?\d+", str(value).replace(",", ""))
    return int(m.group()) if m else None


def parse_speed_mbps(value: Any) -> int | None:
    """Interpreta velocidade em textos como ``1000000 Kbit``, ``10G``, ``1Gbps``, ``auto``."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip().lower().replace(" ", "")
    m = re.match(r"^(\d+(?:\.\d+)?)([kmgt]?)(bit|bps|b/s|bit/s|b)?", s)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2)
    if unit == "k":
        return int(num / 1000)
    if unit == "g":
        return int(num * 1000)
    if unit == "t":
        return int(num * 1_000_000)
    if unit == "m":
        return int(num)
    # sem unidade: se enorme, provavelmente bps
    if num > 1_000_000:
        return int(num / 1_000_000)
    return int(num)


def truthy_status(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in {"up", "connected", "true", "yes", "enabled", "enable", "1", "running", "active", "*up", "ok"}:
        return True
    if s.startswith("up") or s.startswith("connected"):
        return True
    if s in {"down", "notconnect", "disabled", "false", "no", "0", "err-disabled", "*down", "admin down",
             "administratively down", "adm-down", "inactive", "lowerlayerdown", "notpresent"}:
        return False
    if "down" in s or "disabled" in s:
        return False
    return None
