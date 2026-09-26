"""Interface de linha de comando."""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from nettopo import __version__
from nettopo.output import FORMATS, export_all

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="NetTopo - descoberta automática de topologia de rede multi-vendor.")
console = Console()

DEFAULT_FORMATS = "html,drawio,xlsx,md,json"


def _formats(value: str) -> list[str]:
    fmts = [f.strip().lower() for f in value.split(",") if f.strip()]
    bad = [f for f in fmts if f not in FORMATS]
    if bad:
        raise typer.BadParameter(f"formato(s) inválido(s): {', '.join(bad)}. Use: {', '.join(FORMATS)}")
    return fmts


def _progress_printer() -> Any:
    def cb(ev: dict[str, Any]) -> None:
        t = ev.get("type")
        if t == "device_done":
            via = ",".join(ev.get("via") or [])
            console.print(f"  [green]OK[/] {ev.get('hostname') or ev['target']:<28} {ev['target']:<16} "
                          f"[dim]{ev.get('vendor') or '?'} {ev.get('model') or ''} via {via} · "
                          f"{ev.get('neighbors', 0)} vizinhos[/]")
        elif t == "device_failed":
            console.print(f"  [red]XX[/] {ev['target']:<45} [dim]{ev.get('reason', '')[:110]}[/]")
        elif t == "started":
            console.print(f"[bold]Iniciando descoberta[/] a partir de {', '.join(ev.get('seeds', []))}")
    return cb


def _summary(topo: Any, paths: list[Path]) -> None:
    s = topo.meta.stats
    t = Table(title="Resumo da descoberta", show_header=False, title_justify="left")
    for k, v in [("Equipamentos coletados", s.get("collected")), ("Vistos por vizinhos (stubs)", s.get("stubs")),
                 ("Links físicos", s.get("physical_links")), ("Links L3", s.get("l3_links")),
                 ("Adjacências de roteamento", s.get("logical_links")), ("Interfaces", s.get("interfaces")),
                 ("Alvos com falha", s.get("failed_targets")), ("Duração (s)", s.get("duration_s"))]:
        t.add_row(k, str(v))
    t.add_row("Fabricantes", ", ".join(f"{k} ({v})" for k, v in s.get("by_vendor", {}).items()))
    console.print(t)
    if paths:
        console.print("[bold]Arquivos gerados:[/]")
        for p in paths:
            console.print(f"  • {p}")


@app.command()
def discover(
    config: Path = typer.Option(None, "--config", "-c", exists=True, dir_okay=False,
                                help="Arquivo YAML de configuração (credenciais, escopo...)."),
    seed: list[str] = typer.Option(None, "--seed", "-s", help="IP/hostname semente (pode repetir)."),
    output: Path = typer.Option(Path("output"), "--output", "-o", help="Diretório de saída."),
    formats: str = typer.Option(DEFAULT_FORMATS, "--format", "-f", help=f"Formatos: {', '.join(FORMATS)}."),
    depth: int = typer.Option(None, "--depth", "-d", help="Profundidade máxima (saltos a partir da semente)."),
    concurrency: int = typer.Option(None, "--concurrency", help="Equipamentos coletados em paralelo."),
    name: str = typer.Option(None, "--name", "-n", help="Nome da rede/projeto (título dos documentos)."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Descobre a rede a partir da(s) semente(s) e gera diagrama + documentação."""
    from nettopo.config import load_settings
    from nettopo.discovery.engine import discover as run_discovery

    logging.basicConfig(level=logging.DEBUG if verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    settings = load_settings(config, seeds=list(seed) if seed else None, max_depth=depth,
                             concurrency=concurrency, name=name)
    if not settings.seeds:
        raise typer.BadParameter("informe ao menos uma semente (--seed ou 'seeds' no YAML)")
    if not settings.credentials:
        console.print("[yellow]Aviso:[/] nenhuma credencial configurada — apenas portas serão testadas.")
    fmts = _formats(formats)
    topo = asyncio.run(run_discovery(settings, progress=_progress_printer()))
    paths = export_all(topo, fmts, output)
    _summary(topo, paths)


@app.command()
def demo(
    output: Path = typer.Option(Path("output"), "--output", "-o"),
    formats: str = typer.Option(DEFAULT_FORMATS, "--format", "-f"),
    lab: Path = typer.Option(None, "--lab", exists=True, help="YAML de laboratório simulado (opcional)."),
) -> None:
    """Executa a descoberta em uma rede simulada multi-vendor (sem acesso à rede)."""
    from nettopo.collectors.simulated import SimulatedCollector, demo_settings
    from nettopo.discovery.engine import discover as run_discovery

    sim = SimulatedCollector(lab)
    settings = demo_settings(sim)
    topo = asyncio.run(run_discovery(settings, collector=sim, progress=_progress_printer()))
    paths = export_all(topo, _formats(formats), output)
    _summary(topo, paths)


@app.command()
def report(
    snapshot: Path = typer.Argument(..., exists=True, help="JSON gerado por uma descoberta anterior."),
    output: Path = typer.Option(Path("output"), "--output", "-o"),
    formats: str = typer.Option("html,drawio,xlsx,md", "--format", "-f"),
) -> None:
    """Regenera diagramas e documentação a partir de um snapshot JSON."""
    from nettopo.models import Topology

    topo = Topology.load(str(snapshot))
    paths = export_all(topo, _formats(formats), output)
    _summary(topo, paths)


@app.command()
def diff(old: Path = typer.Argument(..., exists=True), new: Path = typer.Argument(..., exists=True)) -> None:
    """Compara duas descobertas (equipamentos e links adicionados/removidos/alterados)."""
    from nettopo.models import Topology
    from nettopo.topology.diff import diff_topologies

    d = diff_topologies(Topology.load(str(old)), Topology.load(str(new)))
    for key, title, color in [("devices_added", "Equipamentos adicionados", "green"),
                              ("devices_removed", "Equipamentos removidos", "red"),
                              ("links_added", "Links adicionados", "green"),
                              ("links_removed", "Links removidos", "red")]:
        console.print(f"[bold {color}]{title} ({len(d[key])})[/]")
        for item in d[key]:
            console.print(f"  {item}")
    console.print(f"[bold yellow]Equipamentos alterados ({len(d['devices_changed'])})[/]")
    for c in d["devices_changed"]:
        changes = "; ".join(f"{k}: {a} -> {b}" for k, (a, b) in c["changes"].items())
        console.print(f"  {c['device']}: {changes}")


@app.command()
def serve(host: str = typer.Option("127.0.0.1", "--host"), port: int = typer.Option(8000, "--port"),
          reload: bool = typer.Option(False, "--reload")) -> None:
    """Inicia a API REST + interface web."""
    import uvicorn

    console.print(f"Interface web em [bold]http://{host}:{port}[/]  (API em /docs)")
    uvicorn.run("nettopo.api.app:create_app", factory=True, host=host, port=port, reload=reload)


@app.command()
def vendors() -> None:
    """Lista os perfis de fabricante suportados e seus métodos de coleta."""
    from nettopo.vendors.registry import default_registry

    t = Table(title="Fabricantes suportados")
    for col in ("Perfil", "Fabricante", "Sistema", "Categoria", "SNMP", "SSH (Netmiko)", "NETCONF", "API REST"):
        t.add_column(col)
    for p in sorted(default_registry().all(), key=lambda p: (p.vendor, p.os)):
        t.add_row(p.id, p.vendor, p.os, p.category, "sim", p.netmiko or "—", p.netconf or "—", p.rest or "—")
    console.print(t)
    console.print("[dim]Qualquer equipamento com SNMP + LLDP-MIB é descoberto mesmo sem perfil específico.[/]")


@app.command()
def init(path: Path = typer.Argument(Path("config.yaml"))) -> None:
    """Cria um arquivo de configuração de exemplo."""
    src = Path(__file__).parent / "config.example.yaml"
    if path.exists():
        raise typer.BadParameter(f"{path} já existe")
    shutil.copy(src, path)
    console.print(f"Configuração de exemplo criada em [bold]{path}[/]. Edite as credenciais e o escopo.")


@app.command()
def version() -> None:
    """Mostra a versão."""
    console.print(f"NetTopo {__version__}")


if __name__ == "__main__":
    app()
