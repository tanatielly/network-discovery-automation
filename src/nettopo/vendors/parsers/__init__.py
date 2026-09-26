"""Parsers de saídas CLI: custom por vendor, ntc-templates (TextFSM) e genéricos."""

from __future__ import annotations

import logging
from collections.abc import Callable

from nettopo.vendors.parsers import generic, linux, mikrotik

log = logging.getLogger(__name__)

Row = dict[str, object]
Parser = Callable[[str], list[Row]]

CUSTOM_PARSERS: dict[str, Parser] = {
    "kv_colon": generic.parse_kv_colon,
    "first_line": generic.parse_first_line,
    "lldp_blocks": generic.parse_lldp_blocks,
    "arp_generic": generic.parse_arp_generic,
    "ip_brief_generic": generic.parse_ip_brief_generic,
    "mikrotik_identity": mikrotik.mikrotik_identity,
    "mikrotik_facts": mikrotik.mikrotik_facts,
    "mikrotik_neighbors": mikrotik.mikrotik_neighbors,
    "mikrotik_interfaces": mikrotik.mikrotik_interfaces,
    "mikrotik_ip_address": mikrotik.mikrotik_ip_address,
    "mikrotik_arp": mikrotik.mikrotik_arp,
    "mikrotik_routes": mikrotik.mikrotik_routes,
    "mikrotik_vlans": mikrotik.mikrotik_vlans,
    "lldpctl_keyvalue": linux.lldpctl_keyvalue,
    "linux_links": linux.linux_links,
    "linux_addrs": linux.linux_addrs,
    "linux_neigh": linux.linux_neigh,
    "linux_routes": linux.linux_routes,
    "linux_facts": linux.linux_facts,
}

# Fallback genérico por tipo de dado
GENERIC_BY_KIND: dict[str, Parser] = {
    "lldp": generic.parse_lldp_blocks,
    "cdp": generic.parse_lldp_blocks,
    "other_l2": generic.parse_lldp_blocks,
    "arp": generic.parse_arp_generic,
    "ip_interfaces": generic.parse_ip_brief_generic,
    "facts": generic.parse_kv_colon,
    "hostname": generic.parse_hostname_generic,
}


def parse_textfsm(platform: str | None, command: str, output: str) -> list[Row]:
    if not platform:
        return []
    try:
        from ntc_templates.parse import parse_output
    except ImportError:  # pragma: no cover
        return []
    try:
        result = parse_output(platform=platform, command=command, data=output)
    except Exception as exc:  # template inexistente ou erro de parsing
        log.debug("ntc-templates %s '%s': %s", platform, command, exc)
        return []
    return result if isinstance(result, list) else []


def parse_output(kind: str, command: str, output: str, platform: str | None,
                 custom: str | None = None) -> tuple[list[Row], str]:
    """Retorna (linhas, origem do parser)."""
    if custom and custom in CUSTOM_PARSERS:
        rows = CUSTOM_PARSERS[custom](output)
        if rows:
            return rows, custom
    rows = parse_textfsm(platform, command, output)
    if rows:
        return rows, "textfsm"
    fallback = GENERIC_BY_KIND.get(kind)
    if fallback:
        rows = fallback(output)
        if rows:
            return rows, "generic"
    return [], "none"
