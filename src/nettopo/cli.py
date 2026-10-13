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
                  help="Mapa de Rede - descoberta automática de topologia de rede multi-vendor.")
console = Console()

DEFAULT_FORMATS = "html,drawio,xlsx,md,json"
DATA_HELP = "Diretório da memória persistente e do cofre (padrão: NETTOPO_DATA ou ./nettopo_data)."

STATUS_STYLE = {"ativo": "green", "novo": "cyan", "alterado": "yellow", "inacessivel": "red", "retirado": "dim"}


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
            seeds = ev.get("seeds", [])
            if seeds:
                console.print(f"[bold]Descoberta[/] a partir de {', '.join(seeds)}")
        elif t == "memory" and ev.get("known"):
            console.print(f"[bold]Memória:[/] confirmando {ev['known']} equipamento(s) conhecido(s)")
        elif t == "revalidated":
            style = STATUS_STYLE.get(ev.get("status", ""), "white")
            how = "dados reaproveitados" if ev.get("reused") else (ev.get("reason") or "coleta completa")
            console.print(f"  [{style}]{ev.get('status', ''):<11}[/] {ev.get('hostname') or '':<28} "
                          f"{ev.get('target') or '':<16} [dim]{how}[/]")
        elif t == "sweep":
            console.print(f"[bold]Varredura:[/] {ev['found']} de {ev['tested']} endereços responderam")
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
    mem = s.get("memoria")
    if mem:
        t.add_row("Memória", f"{mem['conhecidos']} conhecidos · {mem['reaproveitados']} confirmados sem recoleta · "
                             f"{mem['recoletados']} recoletados · {mem['inacessiveis']} inacessíveis · "
                             f"{mem['novos_coletados']} novos")
    console.print(t)
    if mem and mem.get("eventos"):
        console.print("[bold]Mudanças desde a última execução:[/]")
        for e in mem["eventos"][:40]:
            console.print(f"  • {e['kind']}: {e.get('device') or e.get('detail')}")
    if paths:
        console.print("[bold]Arquivos gerados:[/]")
        for p in paths:
            console.print(f"  • {p}")


def _load(config: Path | None, data: Path | None, **overrides: Any) -> Any:
    from nettopo.config import load_settings
    from nettopo.vault import Vault, VaultError, resolve_credentials

    settings = load_settings(config, **overrides)
    needs_vault = settings.usar_cofre or any(c.ref for c in settings.credentials)
    if needs_vault:
        try:
            settings = resolve_credentials(settings, Vault(data))
        except VaultError as exc:
            raise typer.BadParameter(str(exc)) from exc
    return settings


def _run_memory(settings: Any, data: Path | None, use_memory: bool, full: bool, verify_only: bool,
                progress: Any = None) -> Any:
    from nettopo.inventory.revalidate import discover_with_memory
    from nettopo.inventory.store import InventoryStore

    store = InventoryStore(data) if use_memory else None
    return asyncio.run(discover_with_memory(settings, store=store, progress=progress or _progress_printer(),
                                            full=full, verify_only=verify_only))


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
    data: Path = typer.Option(None, "--dados", help=DATA_HELP),
    full: bool = typer.Option(False, "--completo", help="Recoleta tudo, sem reaproveitar dados confirmados."),
    no_memory: bool = typer.Option(False, "--sem-memoria", help="Não usa nem atualiza a memória persistente."),
    load: str = typer.Option(None, "--carga", help="Perfil de carga: conservador, equilibrado ou rapido."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Descobre a rede, confirmando primeiro o que já é conhecido, e gera diagrama + documentação."""
    logging.basicConfig(level=logging.DEBUG if verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    settings = _load(config, data, seeds=list(seed) if seed else None, max_depth=depth, concurrency=concurrency,
                     name=name)
    if load:
        settings = settings.model_copy(update={"carga": settings.carga.model_copy(update={"perfil": load})})
    if not settings.seeds and not settings.varredura and no_memory:
        raise typer.BadParameter("informe ao menos uma semente (--seed ou 'seeds' no YAML)")
    if not settings.credentials:
        console.print("[yellow]Aviso:[/] nenhuma credencial configurada — apenas portas serão testadas.")
    fmts = _formats(formats)
    topo = _run_memory(settings, data, not no_memory, full, verify_only=False)
    paths = export_all(topo, fmts, output)
    _summary(topo, paths)


@app.command()
def verificar(
    config: Path = typer.Option(None, "--config", "-c", exists=True, dir_okay=False),
    data: Path = typer.Option(None, "--dados", help=DATA_HELP),
    output: Path = typer.Option(None, "--output", "-o", help="Gera relatórios também (opcional)."),
    formats: str = typer.Option("html,json", "--format", "-f"),
) -> None:
    """Confirma rapidamente se os equipamentos já conhecidos continuam ativos (não procura novos)."""
    from nettopo.inventory.store import InventoryStore

    if not InventoryStore(data).devices():
        raise typer.BadParameter("a memória está vazia: rode 'nettopo discover' primeiro")
    settings = _load(config, data)
    topo = _run_memory(settings, data, True, False, verify_only=True)
    paths = export_all(topo, _formats(formats), output) if output else []
    _summary(topo, paths)


@app.command()
def inventario(data: Path = typer.Option(None, "--dados", help=DATA_HELP),
               eventos: int = typer.Option(15, "--eventos", help="Quantos eventos recentes mostrar.")) -> None:
    """Lista os equipamentos conhecidos, com status e última confirmação."""
    from nettopo.inventory.store import STATUS_PT, InventoryStore

    store = InventoryStore(data)
    t = Table(title="Inventário (memória persistente)")
    for col in ("Equipamento", "IP de gerência", "Fabricante", "Status", "Verificado em", "Acesso"):
        t.add_column(col)
    for r in store.devices(include_retired=True):
        acc = r.access_info()
        st = STATUS_STYLE.get(r.status, "white")
        t.add_row(r.hostname or r.key, r.mgmt_ip or "", r.vendor or "", f"[{st}]{STATUS_PT.get(r.status, r.status)}[/]",
                  r.last_verified.strftime("%d/%m %H:%M") if r.last_verified else "",
                  f"{acc.get('metodo', '')} {acc.get('credencial') or acc.get('snmp') or ''}".strip())
    console.print(t)
    evs = store.events(eventos)
    if evs:
        console.print("[bold]Eventos recentes:[/]")
        for e in evs:
            console.print(f"  {e.ts:%d/%m %H:%M}  {e.kind:<14} {e.device_key or ''} [dim]{e.detail or ''}[/]")


cred_app = typer.Typer(help="Cofre local de credenciais (Gerenciador de Credenciais do SO ou arquivo cifrado).")
app.add_typer(cred_app, name="cred")


@cred_app.command("add")
def cred_add(
    name: str = typer.Argument(..., help="Nome da credencial (usado em {ref: nome} no config)."),
    type_: str = typer.Option(..., "--tipo", "-t", help="ssh, snmp, netconf ou rest."),
    username: str = typer.Option(None, "--usuario", "-u"),
    version: str = typer.Option("2c", "--versao", help="SNMP: 1, 2c ou 3."),
    port: int = typer.Option(None, "--porta"),
    data: Path = typer.Option(None, "--dados", help=DATA_HELP),
) -> None:
    """Guarda uma credencial no cofre (os segredos são pedidos sem eco no terminal)."""
    from nettopo.config import Credential
    from nettopo.vault import Vault

    fields: dict[str, Any] = {"name": name, "type": type_, "username": username, "port": port}
    if type_ == "snmp" and version != "3":
        fields.update(version=version, community=typer.prompt("Community", hide_input=True))
    elif type_ == "snmp":
        fields.update(version="3", auth_key=typer.prompt("Chave de autenticação (SHA)", hide_input=True),
                      priv_key=typer.prompt("Chave de privacidade (AES)", hide_input=True))
    elif type_ == "rest" and typer.confirm("Usar token de API em vez de usuário/senha?", default=False):
        fields["token"] = typer.prompt("Token", hide_input=True)
    else:
        fields["password"] = typer.prompt("Senha", hide_input=True)
        if type_ == "ssh" and typer.confirm("Informar senha de enable?", default=False):
            fields["enable_secret"] = typer.prompt("Enable", hide_input=True)
    vault = Vault(data)
    vault.add(Credential.model_validate({k: v for k, v in fields.items() if v is not None}))
    console.print(f"Credencial [bold]{name}[/] guardada no cofre ({vault.backend}).")


@cred_app.command("list")
def cred_list(data: Path = typer.Option(None, "--dados", help=DATA_HELP)) -> None:
    """Lista as credenciais do cofre (sem os segredos)."""
    from nettopo.vault import Vault

    t = Table(title="Cofre de credenciais")
    for col in ("Nome", "Tipo", "Usuário", "Guardada em", "Onde"):
        t.add_column(col)
    for item in Vault(data).list():
        t.add_row(item["name"], item["type"] or "", item.get("username") or "", item["saved_at"][:16],
                  item.get("backend", ""))
    console.print(t)


@cred_app.command("remove")
def cred_remove(name: str, data: Path = typer.Option(None, "--dados", help=DATA_HELP)) -> None:
    """Remove uma credencial do cofre."""
    from nettopo.vault import Vault

    if not Vault(data).remove(name):
        raise typer.BadParameter(f"'{name}' não está no cofre")
    console.print(f"Credencial [bold]{name}[/] removida.")


@cred_app.command("import")
def cred_import(config: Path = typer.Argument(..., exists=True, dir_okay=False),
                data: Path = typer.Option(None, "--dados", help=DATA_HELP)) -> None:
    """Move as credenciais de um config YAML para o cofre (depois troque-as por {ref: nome})."""
    from nettopo.config import load_settings
    from nettopo.vault import Vault

    vault = Vault(data)
    n = 0
    for i, c in enumerate(load_settings(config).credentials, start=1):
        if c.ref:
            continue
        if not c.name:
            c = c.model_copy(update={"name": f"{c.type}-{i}"})
        vault.add(c)
        n += 1
        console.print(f"  • {c.name} ({c.type})")
    console.print(f"{n} credencial(is) importada(s) para o cofre ({vault.backend}).")


@app.command()
def demo(
    output: Path = typer.Option(Path("output"), "--output", "-o"),
    formats: str = typer.Option(DEFAULT_FORMATS, "--format", "-f"),
    lab: Path = typer.Option(None, "--lab", exists=True, help="YAML de laboratório simulado (opcional)."),
    memory: bool = typer.Option(False, "--memoria", help="Usa memória persistente (rode duas vezes para ver)."),
) -> None:
    """Executa a descoberta em uma rede simulada multi-vendor (sem acesso à rede)."""
    from nettopo.collectors.simulated import SimulatedCollector, demo_settings
    from nettopo.inventory.revalidate import discover_with_memory
    from nettopo.inventory.store import InventoryStore

    sim = SimulatedCollector(lab, delay=0.05)
    settings = demo_settings(sim)
    store = InventoryStore(output / ".memoria-demo") if memory else None
    topo = asyncio.run(discover_with_memory(settings, store=store, collector=sim, progress=_progress_printer()))
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
    import os

    import uvicorn

    if host not in ("127.0.0.1", "localhost", "::1") and not os.environ.get("NETTOPO_API_TOKEN"):
        console.print("[red]Recusado:[/] fora de 127.0.0.1 a API exige NETTOPO_API_TOKEN (ela recebe credenciais "
                      "de rede e acessa o cofre).")
        raise typer.Exit(2)
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
    console.print(f"Mapa de Rede {__version__} (comando nettopo)")


if __name__ == "__main__":
    app()
