"""Parsers genéricos (regex) usados quando não há template TextFSM para o vendor.

São tolerantes a variações de formato, o que garante cobertura razoável mesmo em
equipamentos sem suporte específico (Datacom, ZTE, TP-Link, Intelbras...).
"""

from __future__ import annotations

import re

from nettopo.utils import extract_ipv4s, normalize_mac

Row = dict[str, object]

_SEP = r"\s*[:=]\s*"

# (campo, regex da chave). A ordem importa: padrões mais específicos primeiro.
_LLDP_KEYS: list[tuple[str, re.Pattern[str]]] = [
    ("local_interface", re.compile(
        r"^\s*(?:local\s*(?:intf|interface|port(?:\s*id)?|port\s*name)|interface|port)" + _SEP + r"(.+?)\s*$", re.I)),
    ("neighbor_name", re.compile(
        r"^\s*(?:system\s*name|sysname|neighbor\s*name|device\s*id|remote\s*system\s*name|identity)" + _SEP + r"(.+?)\s*$",
        re.I)),
    ("neighbor_interface", re.compile(
        r"^\s*(?:port\s*id(?:\s*\(outgoing\s*port\))?|remote\s*port(?:\s*id)?|neighbor\s*port|port-id|portid)"
        + _SEP + r"(.+?)\s*$", re.I)),
    ("port_description", re.compile(r"^\s*port\s*desc(?:ription)?" + _SEP + r"(.+?)\s*$", re.I)),
    ("chassis_id", re.compile(r"^\s*chassis\s*id" + _SEP + r"(.+?)\s*$", re.I)),
    ("system_description", re.compile(r"^\s*(?:system\s*desc(?:ription)?|platform)" + _SEP + r"(.+?)\s*$", re.I)),
    ("capabilities", re.compile(
        r"^\s*(?:enabled\s*)?(?:system\s*)?capabilit(?:y|ies)(?:\s*enabled)?" + _SEP + r"(.+?)\s*$", re.I)),
    ("mgmt_address", re.compile(
        r"^\s*(?:management\s*address(?:es)?|mgmt\s*(?:address|ip)|ip\s*address|entry\s*address\(es\)"
        r"|management\s*ip|address)(?:\s*\(ipv4\))?" + _SEP + r"?(.*?)\s*$", re.I)),
]

_HUAWEI_LOCAL = re.compile(r"^\s*(\S+)\s+has\s+\d+\s+neighbor", re.I)
_COMWARE_LOCAL = re.compile(r"LLDP neighbor-information of port \d+\s*\[(\S+)\]", re.I)
_CDP_START = re.compile(r"^-{5,}|^Device ID", re.I)


def parse_lldp_blocks(text: str) -> list[Row]:
    """Parser genérico de saídas LLDP/CDP "detail" orientadas a chave: valor.

    Se a saída separa vizinhos com linhas ``-----`` (Cisco CDP/LLDP), cada bloco é
    interpretado isoladamente; senão, a saída é lida como fluxo contínuo (Huawei, H3C...).
    """
    sep = re.compile(r"^\s*[-=]{5,}\s*$", re.M)
    if sep.search(text or ""):
        rows: list[Row] = []
        for block in sep.split(text):
            rows.extend(_parse_stream(block, carry=False))
        return rows
    return _parse_stream(text, carry=True)


def _parse_stream(text: str, carry: bool) -> list[Row]:
    rows: list[Row] = []
    cur: Row = {}
    pending_ip = 0

    def flush() -> None:
        nonlocal cur
        if cur.get("neighbor_name") or cur.get("chassis_id") or cur.get("neighbor_interface"):
            rows.append(cur)
        cur = {}

    lines = (text or "").splitlines()
    for line in lines:
        if not line.strip():
            continue
        m = _HUAWEI_LOCAL.search(line) or _COMWARE_LOCAL.search(line)
        if m:
            flush()
            cur["local_interface"] = m.group(1)
            continue
        if pending_ip:
            ips = extract_ipv4s(line)
            if ips:
                cur.setdefault("mgmt_address", ips[0])
                pending_ip = 0
                continue
            pending_ip -= 1
        for field, rx in _LLDP_KEYS:
            mm = rx.match(line)
            if not mm:
                continue
            value = mm.group(1).strip().strip('"') if mm.lastindex else ""
            if field == "mgmt_address":
                ips = extract_ipv4s(value)
                if ips:
                    cur.setdefault("mgmt_address", ips[0])
                else:
                    pending_ip = 3  # IP pode vir nas linhas seguintes (CDP)
                break
            if field in ("local_interface", "neighbor_name") and cur.get(field):
                # Novo vizinho na mesma interface herda a interface local
                local = cur.get("local_interface") if field == "neighbor_name" and carry else None
                flush()
                if local:
                    cur["local_interface"] = local
            if field == "local_interface" and "," in value:  # CDP: "Interface: Gi0/1,  Port ID (outgoing port): Gi0/2"
                parts = re.split(r",\s*", value, maxsplit=1)
                value = parts[0]
                pm = re.search(r"port\s*id.*?:\s*(\S+)", parts[1], re.I)
                if pm:
                    cur["neighbor_interface"] = pm.group(1)
            if field == "system_description" and re.search(r",?\s*Capabilities\s*:", value, re.I):
                value, _, caps = re.split(r"(,?\s*Capabilities\s*:\s*)", value, maxsplit=1, flags=re.I)
                cur.setdefault("capabilities", caps.strip())
            if value and field not in cur:
                cur[field] = value
            break
    flush()
    return rows


_MAC_TOKEN = re.compile(
    r"\b([0-9a-fA-F]{4}[.\-][0-9a-fA-F]{4}[.\-][0-9a-fA-F]{4}|(?:[0-9a-fA-F]{1,2}[:\-]){5}[0-9a-fA-F]{1,2})\b"
)
_IF_TOKEN = re.compile(r"^[A-Za-z][\w\-/.:]*\d[\w\-/.:]*$")


def parse_arp_generic(text: str) -> list[Row]:
    rows: list[Row] = []
    for line in (text or "").splitlines():
        ips = extract_ipv4s(line)
        mm = _MAC_TOKEN.search(line)
        if not ips or not mm:
            continue
        mac = normalize_mac(mm.group(1))
        if not mac:
            continue
        tail = line[mm.end():].split()
        cands = [t for t in tail if _IF_TOKEN.match(t) and not extract_ipv4s(t)]
        itf = next((t for t in cands if "/" in t), cands[-1] if cands else None)
        rows.append({"ip_address": ips[0], "mac_address": mac, "interface": itf})
    return rows


def parse_ip_brief_generic(text: str) -> list[Row]:
    """``show ip interface brief`` e similares: ``<interface> <ip>[/mask] ... <status>``."""
    rows: list[Row] = []
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) < 2 or not _IF_TOKEN.match(parts[0]):
            continue
        m = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})(?:/(\d{1,2})|\s+(\d{1,3}(?:\.\d{1,3}){3}))?", line)
        if not m:
            continue
        status = next((p for p in parts[2:] if p.lower() in ("up", "down", "*down", "administratively")), None)
        rows.append({"interface": parts[0], "ip_address": m.group(1),
                     "prefix_length": m.group(2) or m.group(3), "status": status})
    return rows


def parse_kv_colon(text: str) -> list[Row]:
    """Saídas "Chave: valor" (FortiOS ``get system status``, PAN-OS ``show system info``...)."""
    row: Row = {}
    for line in (text or "").splitlines():
        m = re.match(r"^\s*([A-Za-z][\w \-/()]*?)\s*[:=]\s*(.+?)\s*$", line)
        if not m:
            continue
        key = re.sub(r"[^a-z0-9]+", "_", m.group(1).lower()).strip("_")
        row.setdefault(key, m.group(2))
    aliases = {
        "hostname": ("hostname", "host_name", "system_name", "sysname", "devicename", "device_name", "name"),
        "version": ("version", "sw_version", "software_version", "os_version", "firmware_version",
                    "product_version", "version_ver"),
        "serial": ("serial_number", "serial", "serial_num", "sn", "serialnumber", "system_serial_number"),
        "model": ("model", "platform", "hardware_version", "product", "hardware", "system_type",
                  "chassis_type", "product_name", "device_model"),
        "uptime": ("uptime", "up_time", "system_up_time", "system_uptime"),
    }
    out: Row = dict(row)
    for target, keys in aliases.items():
        for k in keys:
            if row.get(k):
                out[target] = row[k]
                break
    return [out] if out else []


def parse_hostname_generic(text: str) -> list[Row]:
    """``hostname X`` / ``sysname X`` / ``Hostname: X`` / ``name: X``."""
    for line in (text or "").splitlines():
        m = re.match(r"^\s*(?:hostname|sysname|host-name|system\s+name|name)\s*[:=]?\s*\"?([\w.\-]+)\"?\s*;?$",
                     line, re.I)
        if m:
            return [{"hostname": m.group(1)}]
    return []


def parse_first_line(text: str) -> list[Row]:
    for line in (text or "").splitlines():
        s = line.strip()
        if s:
            return [{"hostname": s.split()[-1]}]
    return []
