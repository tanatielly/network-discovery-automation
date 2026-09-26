"""Relatório HTML interativo e autocontido (diagrama + documentação)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from nettopo.models import Topology
from nettopo.output.graphdata import device_summaries, to_cytoscape

HERE = Path(__file__).parent
ASSETS = HERE / "assets"


def viewer_payload(topo: Topology) -> dict[str, Any]:
    """Estrutura consumida por ``viewer.js`` (mesma usada pela API)."""
    return {
        "meta": topo.meta.model_dump(mode="json"),
        "graph": to_cytoscape(topo),
        "devices": device_summaries(topo),
        "links": [lk.model_dump(mode="json") for lk in topo.links],
    }


def render_html(topo: Topology) -> str:
    env = Environment(loader=FileSystemLoader(HERE / "templates"), autoescape=select_autoescape(["html"]))
    tpl = env.get_template("report.html.j2")
    data = json.dumps(viewer_payload(topo), ensure_ascii=False, separators=(",", ":"))
    # Evita que "</script>" dentro de strings encerre o bloco
    data = data.replace("</", "<\\/").replace("<!--", "<\\!--")
    from markupsafe import Markup

    return tpl.render(
        title=topo.meta.name or "Topologia de rede",
        css=Markup((ASSETS / "viewer.css").read_text(encoding="utf-8")),
        topoview_js=Markup((ASSETS / "topoview.js").read_text(encoding="utf-8")),
        viewer_js=Markup((ASSETS / "viewer.js").read_text(encoding="utf-8")),
        data_json=Markup(data),
    )


def write_html(topo: Topology, path: Path) -> Path:
    path.write_text(render_html(topo), encoding="utf-8")
    return path
