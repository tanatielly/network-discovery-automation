"""Comparação entre duas descobertas (auditoria de mudanças)."""

from __future__ import annotations

from typing import Any

from nettopo.models import Link, Topology
from nettopo.utils import ifname_key, short_hostname

TRACKED = ["mgmt_ip", "vendor", "model", "os_version", "serial", "role"]


def _dev_key(topo: Topology, did: str) -> str:
    d = topo.devices[did]
    return short_hostname(d.hostname) or d.mgmt_ip or did


def _link_sig(topo: Topology, lk: Link) -> tuple:
    a = (_dev_key(topo, lk.source), ifname_key(lk.source_interface))
    b = (_dev_key(topo, lk.target), ifname_key(lk.target_interface))
    return (lk.kind, *sorted([a, b]))


def diff_topologies(old: Topology, new: Topology) -> dict[str, Any]:
    old_devs = {_dev_key(old, i): d for i, d in old.devices.items()}
    new_devs = {_dev_key(new, i): d for i, d in new.devices.items()}
    changed = []
    for k in sorted(set(old_devs) & set(new_devs)):
        o, n = old_devs[k], new_devs[k]
        fields = {f: (getattr(o, f), getattr(n, f)) for f in TRACKED if getattr(o, f) != getattr(n, f)}
        if fields:
            changed.append({"device": k, "changes": fields})
    old_links = {_link_sig(old, lk): lk for lk in old.links}
    new_links = {_link_sig(new, lk): lk for lk in new.links}

    def fmt(sig: tuple) -> str:
        kind, (a, ai), (b, bi) = sig
        return f"[{kind}] {a}:{ai or '?'} <-> {b}:{bi or '?'}"

    return {
        "devices_added": sorted(set(new_devs) - set(old_devs)),
        "devices_removed": sorted(set(old_devs) - set(new_devs)),
        "devices_changed": changed,
        "links_added": sorted(fmt(s) for s in set(new_links) - set(old_links)),
        "links_removed": sorted(fmt(s) for s in set(old_links) - set(new_links)),
    }
