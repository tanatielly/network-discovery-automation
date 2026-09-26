"""Parsers para hosts Linux (iproute2 + lldpd)."""

from __future__ import annotations

import re

Row = dict[str, object]


def lldpctl_keyvalue(text: str) -> list[Row]:
    """``lldpctl -f keyvalue``: ``lldp.eth0.chassis.name=sw1``."""
    by_if: dict[str, Row] = {}
    for line in (text or "").splitlines():
        m = re.match(r"^lldp\.([^.]+)\.(.+?)=(.*)$", line.strip())
        if not m:
            continue
        ifname, key, value = m.groups()
        row = by_if.setdefault(ifname, {"local_interface": ifname})
        mapping = {
            "chassis.name": "neighbor_name",
            "chassis.mac": "chassis_id",
            "chassis.descr": "system_description",
            "chassis.mgmt-ip": "mgmt_address",
            "port.ifname": "neighbor_interface",
            "port.descr": "port_description",
            "port.local": "neighbor_interface",
        }
        field = mapping.get(key)
        if field and field not in row:
            row[field] = value
        elif key.startswith("chassis.") and key.endswith(".enabled") and value.lower() == "on":
            caps = row.setdefault("capabilities", [])
            caps.append(key.split(".")[1])  # type: ignore[union-attr]
    return list(by_if.values())


def linux_links(text: str) -> list[Row]:
    rows = []
    for line in (text or "").splitlines():
        m = re.match(r"^\d+:\s+([^:@\s]+)(?:@\S+)?:\s+<([^>]*)>(.*)$", line.strip())
        if not m:
            continue
        name, flags, rest = m.groups()
        if name == "lo":
            continue
        mtu = re.search(r"mtu (\d+)", rest)
        mac = re.search(r"link/ether ([0-9a-f:]{17})", rest)
        rows.append({
            "interface": name,
            "mtu": mtu.group(1) if mtu else None,
            "mac_address": mac.group(1) if mac else None,
            "link_status": "up" if "LOWER_UP" in flags else "down",
            "admin_state": "up" if "UP" in flags.split(",") else "down",
        })
    return rows


def linux_addrs(text: str) -> list[Row]:
    rows = []
    for line in (text or "").splitlines():
        m = re.match(r"^\d+:\s+(\S+)\s+inet\s+(\d+\.\d+\.\d+\.\d+/\d+)", line.strip())
        if m and m.group(1) != "lo":
            rows.append({"interface": m.group(1), "ip_address": m.group(2)})
    return rows


def linux_neigh(text: str) -> list[Row]:
    rows = []
    for line in (text or "").splitlines():
        m = re.match(r"^(\d+\.\d+\.\d+\.\d+)\s+dev\s+(\S+)(?:\s+lladdr\s+(\S+))?", line.strip())
        if m and m.group(3):
            rows.append({"ip_address": m.group(1), "interface": m.group(2), "mac_address": m.group(3)})
    return rows


def linux_routes(text: str) -> list[Row]:
    rows = []
    for line in (text or "").splitlines():
        parts = line.split()
        if not parts:
            continue
        dst = "0.0.0.0/0" if parts[0] == "default" else parts[0]
        via = re.search(r"\bvia (\S+)", line)
        dev = re.search(r"\bdev (\S+)", line)
        proto = re.search(r"\bproto (\S+)", line)
        rows.append({"network": dst, "nexthop_ip": via.group(1) if via else None,
                     "nexthop_if": dev.group(1) if dev else None, "protocol": proto.group(1) if proto else None})
    return rows


def linux_facts(text: str) -> list[Row]:
    row: Row = {}
    lines = (text or "").splitlines()
    for line in lines:
        m = re.match(r'^PRETTY_NAME="?([^"]+)"?', line)
        if m:
            row["model"] = m.group(1)
    kernel = next((ln.strip() for ln in lines if re.match(r"^\d+\.\d+\.\d+", ln.strip())), None)
    if kernel:
        row["version"] = kernel
    tail = [ln.strip() for ln in lines if ln.strip() and "=" not in ln and ln.strip() != kernel]
    if tail:
        row["serial"] = tail[0]
        if len(tail) > 1:
            row["hardware"] = tail[1]
    return [row] if row else []
