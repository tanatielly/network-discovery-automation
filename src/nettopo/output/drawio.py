"""Exporta a topologia para draw.io / diagrams.net (.drawio), editável e compatível com Visio.

Gera duas páginas: "Física" (LLDP/CDP) e "L3 / Roteamento". Cada equipamento é um
``UserObject`` com propriedades (fabricante, modelo, serial, SO...) visíveis em
"Editar dados" no draw.io.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from nettopo.models import Device, Link, Topology
from nettopo.output.icons import ROLE_LABELS, TIER_LABELS
from nettopo.topology.layout import compute_layout
from nettopo.topology.roles import TIERS
from nettopo.utils import short_ifname

_BASE = ("sketch=0;html=1;pointerEvents=1;dashed=0;strokeColor=#ffffff;strokeWidth=2;verticalLabelPosition=bottom;"
         "verticalAlign=top;align=center;outlineConnect=0;fontSize=11;")

SHAPES: dict[str, tuple[str, int, int]] = {
    "router": ("shape=mxgraph.cisco.routers.router;fillColor=#036897;" + _BASE, 60, 40),
    "l3switch": ("shape=mxgraph.cisco.switches.layer_3_switch;fillColor=#036897;" + _BASE, 56, 50),
    "switch": ("shape=mxgraph.cisco.switches.workgroup_switch;fillColor=#036897;" + _BASE, 64, 32),
    "firewall": ("shape=mxgraph.cisco.security.firewall;fillColor=#036897;" + _BASE, 36, 60),
    "wireless_controller": ("shape=mxgraph.cisco.wireless.wireless_lan_controller;fillColor=#036897;" + _BASE, 64, 30),
    "ap": ("shape=mxgraph.cisco.wireless.access_point;fillColor=#036897;" + _BASE, 56, 24),
    "server": ("shape=mxgraph.cisco.servers.fileserver;fillColor=#036897;" + _BASE, 40, 58),
    "phone": ("shape=mxgraph.cisco.modems_and_phones.ip_phone;fillColor=#036897;" + _BASE, 52, 38),
    "external": ("ellipse;shape=cloud;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;fontSize=11;"
                 "verticalLabelPosition=bottom;verticalAlign=top;", 90, 56),
    "unknown": ("rounded=1;whiteSpace=wrap;html=1;dashed=1;fillColor=#f5f5f5;strokeColor=#999999;fontSize=11;"
                "verticalLabelPosition=bottom;verticalAlign=top;", 50, 40),
}

EDGE_STYLES = {
    "physical": "endArrow=none;html=1;rounded=0;strokeColor=#4d4d4d;",
    "l3": "endArrow=none;html=1;rounded=0;strokeColor=#0969da;dashed=1;",
    "logical": "endArrow=none;html=1;rounded=0;strokeColor=#bf8700;dashed=1;dashPattern=1 3;",
}


def _edge_width(speed: int | None) -> float:
    if not speed:
        return 1.5
    if speed >= 100000:
        return 5
    if speed >= 25000:
        return 4
    if speed >= 10000:
        return 3
    return 2 if speed >= 1000 else 1.5


def _node_label(d: Device) -> str:
    parts = [f"<b>{escape(d.label)}</b>"]
    if d.mgmt_ip:
        parts.append(escape(d.mgmt_ip))
    model = " ".join(x for x in (d.vendor, d.model) if x)
    if model:
        parts.append(f"<font color='#666666' style='font-size:9px'>{escape(model[:48])}</font>")
    return "<br>".join(parts)


def _page(topo: Topology, name: str, page_id: str, links: list[Link], node_ids: set[str]) -> str:
    pos = compute_layout(topo, x_gap=210, y_gap=190)
    xs = [pos[i][0] for i in node_ids if i in pos] or [0]
    ys = [pos[i][1] for i in node_ids if i in pos] or [0]
    ox, oy = 80 - min(xs), 140 - min(ys)
    cells: list[str] = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']

    # Título e bandas das camadas
    title = escape(topo.meta.name or "Topologia de rede")
    when = (topo.meta.finished_at or datetime.now()).strftime("%d/%m/%Y %H:%M")
    title_html = (f"<b>{title}</b> — {escape(name)}<br><font style='font-size:10px' color='#666666'>"
                  f"Gerado por NetTopo em {when} · {len(node_ids)} equipamentos · {len(links)} links</font>")
    cells.append(
        f'<mxCell id="{page_id}-title" value={quoteattr(title_html)} '
        'style="text;html=1;align=left;verticalAlign=top;fontSize=16;" vertex="1" parent="1">'
        '<mxGeometry x="20" y="10" width="700" height="50" as="geometry"/></mxCell>')
    width = (max(xs) - min(xs)) + 260
    tiers_used: dict[str, list[float]] = {}
    for did in node_ids:
        d = topo.devices[did]
        if did in pos:
            tiers_used.setdefault(d.tier or "endpoint", []).append(pos[did][1] + oy)
    for tier in TIERS:
        if tier not in tiers_used:
            continue
        y0, y1 = min(tiers_used[tier]) - 40, max(tiers_used[tier]) + 110
        cells.append(
            f'<mxCell id="{page_id}-band-{tier}" value={quoteattr(TIER_LABELS.get(tier, tier))} '
            'style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f8f9fb;strokeColor=#e1e4e8;dashed=1;align=left;'
            'verticalAlign=top;spacingLeft=8;fontColor=#888888;fontSize=11;arcSize=4;" vertex="1" parent="1">'
            f'<mxGeometry x="20" y="{y0:.0f}" width="{width + 60:.0f}" height="{y1 - y0:.0f}" as="geometry"/></mxCell>')

    for did in sorted(node_ids):
        d = topo.devices[did]
        style, w, h = SHAPES.get(d.role, SHAPES["unknown"])
        if d.stub:
            style += "opacity=70;"
        x, y = pos.get(did, (0, 0))
        props = {
            "hostname": d.hostname or "", "ip": d.mgmt_ip or "", "fabricante": d.vendor or "", "modelo": d.model or "",
            "sistema": d.os or "", "versao": d.os_version or "", "serial": d.serial or "",
            "papel": ROLE_LABELS.get(d.role, d.role), "camada": TIER_LABELS.get(d.tier or "", d.tier or ""),
            "coletado": "não (visto por vizinho)" if d.stub else ", ".join(d.collected_via),
        }
        attrs = " ".join(f"{k}={quoteattr(v)}" for k, v in props.items())
        cells.append(
            f'<UserObject label={quoteattr(_node_label(d))} id="{page_id}-{escape(did)}" {attrs} '
            f'tooltip={quoteattr(d.sys_description or "")}>'
            f'<mxCell style="{style}" vertex="1" parent="1">'
            f'<mxGeometry x="{x + ox - w / 2:.0f}" y="{y + oy - h / 2:.0f}" width="{w}" height="{h}" as="geometry"/>'
            '</mxCell></UserObject>')

    for lk in links:
        style = EDGE_STYLES.get(lk.kind, EDGE_STYLES["physical"]) + f"strokeWidth={_edge_width(lk.speed_mbps)};"
        eid = f"{page_id}-{lk.id}"
        tooltip = f"{lk.source}:{lk.source_interface or '?'} ↔ {lk.target}:{lk.target_interface or '?'} | " \
                  f"{', '.join(lk.protocols)}" + (f" | {lk.subnet}" if lk.subnet else "")
        mid = " / ".join(x for x in (lk.subnet if lk.kind != "physical" else None, lk.lag) if x)
        cells.append(
            f'<UserObject label={quoteattr(escape(mid))} id="{eid}" protocolos={quoteattr(", ".join(lk.protocols))} '
            f'tooltip={quoteattr(tooltip)}><mxCell style="{style}fontSize=9;fontColor=#555555;labelBackgroundColor=#ffffff;" '
            f'edge="1" parent="1" source="{page_id}-{escape(lk.source)}" target="{page_id}-{escape(lk.target)}">'
            '<mxGeometry relative="1" as="geometry"/></mxCell></UserObject>')
        for side, x_rel, label in (("s", -0.72, lk.source_interface), ("t", 0.72, lk.target_interface)):
            if not label:
                continue
            cells.append(
                f'<mxCell id="{eid}-{side}" value={quoteattr(escape(short_ifname(label)))} '
                'style="edgeLabel;html=1;align=center;verticalAlign=middle;resizable=0;points=[];fontSize=9;'
                f'fontColor=#333333;labelBackgroundColor=#ffffff;" vertex="1" connectable="0" parent="{eid}">'
                f'<mxGeometry x="{x_rel}" relative="1" as="geometry"><mxPoint as="offset"/></mxGeometry></mxCell>')

    # Legenda
    ly = max(ys) + oy + 150
    legend = "<b>Legenda</b><br>" + "<br>".join([
        "━━ Link físico (LLDP/CDP) — espessura = velocidade",
        "<font color='#0969da'>╍╍ Link L3 inferido por sub-rede /30-/31</font>",
        "<font color='#bf8700'>┈┈ Adjacência de roteamento (OSPF/BGP)</font>",
        "Transparente = equipamento não coletado (visto por vizinho)",
    ])
    cells.append(
        f'<mxCell id="{page_id}-legend" value={quoteattr(legend)} style="text;html=1;align=left;verticalAlign=top;'
        'fontSize=10;strokeColor=#dddddd;fillColor=#ffffff;spacing=8;rounded=1;" vertex="1" parent="1">'
        f'<mxGeometry x="20" y="{ly:.0f}" width="380" height="90" as="geometry"/></mxCell>')

    body = "".join(cells)
    return (f'<diagram id="{page_id}" name={quoteattr(name)}><mxGraphModel dx="1400" dy="900" grid="1" gridSize="10" '
            'guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="0" pageScale="1" math="0" shadow="0">'
            f"<root>{body}</root></mxGraphModel></diagram>")


def render_drawio(topo: Topology) -> str:
    physical = [lk for lk in topo.links if lk.kind == "physical"]
    phys_nodes = {lk.source for lk in physical} | {lk.target for lk in physical}
    phys_nodes |= {d.id for d in topo.devices.values() if not d.stub}
    pages = [_page(topo, "Física (L1/L2)", "phy", physical, phys_nodes)]

    l3 = [lk for lk in topo.links if lk.kind in ("l3", "logical") or lk.subnet or
          any(p in ("ospf", "bgp", "isis", "eigrp") for p in lk.protocols)]
    if l3:
        l3_nodes = {lk.source for lk in l3} | {lk.target for lk in l3}
        l3_nodes |= {d.id for d in topo.devices.values() if d.role in ("router", "firewall", "l3switch")}
        pages.append(_page(topo, "L3 / Roteamento", "l3", l3, l3_nodes))
    return f'<mxfile host="NetTopo" type="device">{"".join(pages)}</mxfile>'


def write_drawio(topo: Topology, path: Path) -> Path:
    path.write_text(render_drawio(topo), encoding="utf-8")
    return path
