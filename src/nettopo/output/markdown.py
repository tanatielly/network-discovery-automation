"""Documentação em Markdown: visão geral (com diagrama Mermaid) + um arquivo por equipamento."""

from __future__ import annotations

import re
from pathlib import Path

from nettopo.models import Device, Topology
from nettopo.output.icons import ROLE_LABELS, TIER_LABELS
from nettopo.topology.roles import TIERS
from nettopo.utils import short_ifname, slugify

MERMAID_MAX_NODES = 150


def _cell(v: object) -> str:
    s = "" if v is None else str(v)
    return s.replace("|", "\\|").replace("\n", " ")


def _table(headers: list[str], rows: list[list[object]]) -> str:
    if not rows:
        return "_Nenhum registro._\n"
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def _mid(did: str) -> str:
    return "n_" + re.sub(r"[^A-Za-z0-9_]", "_", did)


def mermaid(topo: Topology) -> str:
    shapes = {"router": ("((", "))"), "firewall": ("{{", "}}"), "external": ("(", ")"), "ap": ("([", "])"),
              "server": ("[(", ")]")}
    lines = ["```mermaid", "graph TD"]
    for tier in TIERS:
        members = [d for d in topo.devices.values() if (d.tier or "endpoint") == tier]
        if not members:
            continue
        lines.append(f'  subgraph {tier}["{TIER_LABELS.get(tier, tier)}"]')
        for d in members:
            a, b = shapes.get(d.role, ("[", "]"))
            label = d.label.replace('"', "'")
            lines.append(f'    {_mid(d.id)}{a}"{label}"{b}')
        lines.append("  end")
    for lk in topo.links:
        lbl = " / ".join(x for x in (short_ifname(lk.source_interface), short_ifname(lk.target_interface)) if x)
        arrow = "---" if lk.kind == "physical" else "-.-"
        lines.append(f'  {_mid(lk.source)} {arrow}|"{lbl}"| {_mid(lk.target)}' if lbl
                     else f"  {_mid(lk.source)} {arrow} {_mid(lk.target)}")
    for d in topo.devices.values():
        if d.stub:
            lines.append(f"  style {_mid(d.id)} stroke-dasharray: 5 5")
    lines.append("```")
    return "\n".join(lines)


def device_markdown(topo: Topology, d: Device) -> str:
    name = {x.id: x.label for x in topo.devices.values()}
    md = [f"# {d.label}", "", "[← Visão geral](../README.md)", ""]
    md.append(_table(["Campo", "Valor"], [[k, v] for k, v in [
        ("IP de gerência", d.mgmt_ip), ("Papel", ROLE_LABELS.get(d.role, d.role)),
        ("Camada", TIER_LABELS.get(d.tier or "", d.tier)), ("Fabricante", d.vendor), ("Sistema", d.os),
        ("Versão", d.os_version), ("Modelo", d.model), ("Serial", d.serial), ("Uptime", d.uptime),
        ("Localização", d.location), ("Contato", d.contact), ("MAC do chassis", d.chassis_id),
        ("Coletado via", ", ".join(d.collected_via) if not d.stub else "não coletado (visto por vizinho)"),
        ("Descoberto a partir de", name.get(d.discovered_from or "")),
        ("Descrição", (d.sys_description or "")[:300]),
    ] if v]))
    links = topo.links_of(d.id)
    md += ["## Conexões", ""]
    md.append(_table(["Interface local", "Vizinho", "Interface remota", "Tipo", "Protocolos", "Velocidade", "Sub-rede"], [
        [lk.source_interface if lk.source == d.id else lk.target_interface,
         f"[{name.get(o, o)}]({slugify(o)}.md)" if not topo.devices[o].stub else name.get(o, o),
         lk.target_interface if lk.source == d.id else lk.source_interface, lk.kind, ", ".join(lk.protocols),
         f"{lk.speed_mbps} Mbps" if lk.speed_mbps else "", lk.subnet]
        for lk in links for o in [lk.target if lk.source == d.id else lk.source]]))
    if d.interfaces:
        md += ["## Interfaces", ""]
        md.append(_table(["Interface", "Descrição", "IPv4", "Admin", "Oper", "Velocidade", "MTU", "LAG"], [
            [i.name, i.description, " ".join(i.ipv4),
             {True: "up", False: "down"}.get(i.admin_up, ""), {True: "up", False: "down"}.get(i.oper_up, ""),
             f"{i.speed_mbps} Mbps" if i.speed_mbps else "", i.mtu, i.parent] for i in d.interfaces]))
    if d.neighbors:
        md += ["## Vizinhos anunciados", ""]
        md.append(_table(["Protocolo", "Interface local", "Vizinho", "Interface remota", "IP", "Plataforma"], [
            [n.protocol, n.local_interface, n.remote_hostname, n.remote_interface, n.remote_mgmt_ip,
             (n.remote_platform or "")[:60]] for n in d.neighbors]))
    if d.vlans:
        md += ["## VLANs", ""]
        md.append(_table(["ID", "Nome"], [[v.id, v.name] for v in sorted(d.vlans, key=lambda v: v.id)]))
    if d.routes:
        md += [f"## Rotas ({len(d.routes)})", ""]
        md.append(_table(["Prefixo", "Next-hop", "Interface", "Protocolo", "VRF"],
                         [[r.prefix, r.next_hop, r.interface, r.protocol, r.vrf] for r in d.routes[:300]]))
    if d.arp:
        md += [f"## ARP ({len(d.arp)})", ""]
        md.append(_table(["IP", "MAC", "Interface"], [[a.ip, a.mac, a.interface] for a in d.arp[:300]]))
    if d.errors:
        md += ["## Avisos de coleta", ""] + [f"- {e}" for e in d.errors] + [""]
    return "\n".join(md)


def write_markdown(topo: Topology, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "devices").mkdir(exist_ok=True)
    m, s = topo.meta, topo.meta.stats
    devs = sorted(topo.devices.values(), key=lambda d: (d.stub, TIERS.index(d.tier) if d.tier in TIERS else 99,
                                                        d.label.lower()))
    name = {d.id: d.label for d in devs}
    md = [f"# {m.name or 'Topologia de rede'}", "",
          f"Documentação gerada automaticamente pelo **NetTopo {m.tool_version}** em "
          f"{(m.finished_at or m.started_at).strftime('%d/%m/%Y %H:%M')} a partir de `{', '.join(m.seeds)}`.", "",
          "## Resumo", ""]
    md.append(_table(["Indicador", "Valor"], [
        ["Equipamentos coletados", s.get("collected")], ["Vistos apenas por vizinhos", s.get("stubs")],
        ["Links físicos", s.get("physical_links")], ["Links L3 inferidos", s.get("l3_links")],
        ["Adjacências de roteamento", s.get("logical_links")], ["Interfaces", s.get("interfaces")],
        ["Alvos com falha", s.get("failed_targets")], ["Duração (s)", s.get("duration_s")],
        ["Fabricantes", ", ".join(f"{k} ({v})" for k, v in s.get("by_vendor", {}).items())],
    ]))
    md += ["", "## Diagrama", ""]
    if len(topo.devices) <= MERMAID_MAX_NODES:
        md.append(mermaid(topo))
    else:
        md.append(f"_Topologia com {len(topo.devices)} nós — use o relatório HTML ou o arquivo draw.io._")
    md += ["", "## Inventário", ""]
    md.append(_table(["Hostname", "IP", "Papel", "Camada", "Fabricante", "Modelo", "Versão", "Serial"], [
        [f"[{d.label}](devices/{slugify(d.id)}.md)" if not d.stub else f"{d.label} _(não coletado)_", d.mgmt_ip,
         ROLE_LABELS.get(d.role, d.role), TIER_LABELS.get(d.tier or "", d.tier), d.vendor, d.model, d.os_version,
         d.serial] for d in devs]))
    md += ["", "## Links", ""]
    md.append(_table(["ID", "Origem", "Interface", "Destino", "Interface", "Tipo", "Protocolos", "Sub-rede"], [
        [lk.id, name.get(lk.source), lk.source_interface, name.get(lk.target), lk.target_interface, lk.kind,
         ", ".join(lk.protocols), lk.subnet] for lk in topo.links]))
    if m.failed_targets:
        md += ["", "## Falhas de coleta", ""]
        md.append(_table(["Alvo", "Motivo"], [[k, v] for k, v in sorted(m.failed_targets.items())]))
    (out_dir / "README.md").write_text("\n".join(md), encoding="utf-8")
    for d in devs:
        if not d.stub:
            (out_dir / "devices" / f"{slugify(d.id)}.md").write_text(device_markdown(topo, d), encoding="utf-8")
    return out_dir / "README.md"
