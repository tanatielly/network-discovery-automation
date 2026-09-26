"""Geração de saídas: HTML interativo, draw.io, Excel, Markdown e JSON."""

from __future__ import annotations

from pathlib import Path

from nettopo.models import Topology
from nettopo.utils import slugify

FORMATS = ("html", "drawio", "xlsx", "md", "json")


def export(topo: Topology, fmt: str, out_dir: Path, basename: str | None = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    base = basename or slugify(topo.meta.name or "topologia")
    if fmt == "json":
        path = out_dir / f"{base}.json"
        topo.save(str(path))
        return path
    if fmt == "html":
        from nettopo.output.html import write_html

        return write_html(topo, out_dir / f"{base}.html")
    if fmt == "drawio":
        from nettopo.output.drawio import write_drawio

        return write_drawio(topo, out_dir / f"{base}.drawio")
    if fmt == "xlsx":
        from nettopo.output.excel import write_excel

        return write_excel(topo, out_dir / f"{base}.xlsx")
    if fmt == "md":
        from nettopo.output.markdown import write_markdown

        return write_markdown(topo, out_dir / f"{base}-docs")
    raise ValueError(f"formato desconhecido: {fmt} (use {', '.join(FORMATS)})")


def export_all(topo: Topology, formats: list[str], out_dir: Path, basename: str | None = None) -> list[Path]:
    return [export(topo, f, out_dir, basename) for f in formats]
