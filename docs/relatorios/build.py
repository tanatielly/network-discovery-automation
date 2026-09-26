"""Gera os relatórios HTML/PDF a partir do Markdown e dos resultados reais da simulação.

Uso:
    python docs/relatorios/build.py <pasta-do-run>      # ex.: ../nettopo-results/runs/<id>
    python docs/relatorios/build.py <pasta-do-run> --pdf

O Markdown é a fonte do texto. Marcadores ``<!-- viz:NOME -->`` viram visualizações geradas
a partir de ``metrics.json`` e demais arquivos do run (a tabela equivalente fica no Markdown).
Os dados usados são copiados para ``docs/relatorios/dados/`` para o relatório ser reproduzível.
"""

from __future__ import annotations

import base64
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import markdown
import yaml

HERE = Path(__file__).parent
DATA = HERE / "dados"
REPO_URL = "https://github.com/tanatielly/network-discovery-automation"
PDF_URL = REPO_URL + "/raw/main/docs/relatorios/{name}.pdf"
MD_URL = REPO_URL + "/blob/main/docs/relatorios/{name}.md"
REPORTS = ["gestao-tecnica", "tecnico"]
CHROME = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
          r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", "google-chrome", "chromium"]

SCENARIO_LABELS = {
    "01-completo": "Semente única, todos os métodos",
    "02-completo-dns": "Semente única + DNS",
    "03-inventario": "Inventário de IPs de gerência",
    "04-snmp-v2c": "Somente SNMP v2c",
    "05-snmp-v3": "Somente SNMPv3",
    "06-ssh": "Somente SSH",
    "07-apis": "Somente APIs (REST/NETCONF)",
    "08-credenciais-mistas": "Credenciais erradas primeiro",
    "09-escopo": "Profundidade 1 + exclusão",
    "10-concorrencia-1": "Inventário sequencial",
    "11-falha-injetada": "Após falha injetada",
}


# --------------------------------------------------------------------------- dados

def load_run(run: Path) -> dict[str, Any]:
    def j(rel: str, default: Any = None) -> Any:
        p = run / rel
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default

    data = {
        "metrics": j("metrics.json", {}),
        "parse": j("raw/parse-matrix.json", {}),
        "boot": j("lab-state/boot.json", {}),
        "api": j("scenarios/12-api-ui/timing.json", {}),
        "cli": j("scenarios/cli/cli.json", {}),
        "diff": j("scenarios/11-falha-injetada/diff.json", {}),
        "coverage": j("quality/coverage.json", {}),
        "bandit": j("quality/bandit.json", {}),
        "run": run.name,
    }
    for name in ("mypy.txt", "pytest.txt", "ruff.txt"):
        p = run / "quality" / name
        data[name] = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
    return data


def copy_data(run: Path) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    for rel in ("metrics.json", "summary.md", "raw/parse-matrix.json", "lab-state/boot.json",
                "scenarios/12-api-ui/timing.json", "scenarios/cli/cli.json", "scenarios/11-falha-injetada/diff.json"):
        src = run / rel
        if src.exists():
            shutil.copy(src, DATA / rel.replace("/", "__"))
    shots = run / "scenarios" / "12-api-ui" / "screenshots"
    if shots.exists():
        (DATA / "screenshots").mkdir(exist_ok=True)
        for p in shots.glob("*.png"):
            shutil.copy(p, DATA / "screenshots" / p.name)


# --------------------------------------------------------------------------- visualizações

def pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def bar(value: float, label: str, kind: str = "") -> str:
    w = max(0.0, min(1.0, value)) * 100
    return (f'<span class="bar {kind}" role="img" aria-label="{html.escape(label)}">'
            f'<span class="bar-fill" style="width:{w:.1f}%"></span></span>'
            f'<span class="bar-val">{html.escape(label)}</span>')


def viz_kpis(d: dict[str, Any]) -> str:
    """Faixa de indicadores: melhor configuração (07-apis) x padrão com semente única (01-completo)."""
    best, default = d["metrics"].get("07-apis", {}), d["metrics"].get("01-completo", {})
    false_best = len(best.get("false_links", []))
    drawn = best.get("links_found", 0) + false_best
    tiles = [
        (f"{best.get('nodes_collected', '—')} de {best.get('nodes_expected_collected', '—')}",
         "equipamentos coletados", "melhor configuração: APIs + SNMP para identificar"),
        (f"{default.get('nodes_collected', '—')} de {default.get('nodes_expected_collected', '—')}",
         "com a configuração padrão", "todos os métodos, partindo de um único IP"),
        (f"{best.get('links_found', '—')} de {best.get('links_expected', '—')}", "links reais encontrados",
         "melhor configuração"),
        (f"{false_best} de {drawn}", "links desenhados não existem", "duplicados ou vindos da rede de gerência"),
        (str(d.get("high_defects", "—")), "defeitos de alta severidade", "impedem uso como fonte oficial hoje"),
        (d.get("run_minutes", "—"), "por rodada completa na nuvem", "GitHub Actions, sem custo e sem hardware local"),
    ]
    cells = "".join(f'<div class="kpi"><b>{html.escape(str(v))}</b><span class="kpi-l">{html.escape(lab)}</span>'
                    f'<span class="kpi-n">{html.escape(n)}</span></div>' for v, lab, n in tiles)
    return f'<div class="kpis">{cells}</div>'


def viz_scenarios(d: dict[str, Any]) -> str:
    rows = []
    for sid, m in d["metrics"].items():
        label = SCENARIO_LABELS.get(sid, m.get("title", sid))
        nodes = "{}/{}".format(m["nodes_collected"], m["nodes_expected_collected"])
        links = "{}/{}".format(m["links_found"], m["links_expected"])
        rows.append(
            f"<tr><th scope='row'><span class='sid'>{html.escape(sid[:2])}</span>{html.escape(label)}</th>"
            f"<td>{bar(m['node_recall'], nodes)}</td>"
            f"<td>{bar(m['link_recall'], links)}</td>"
            + (f"<td>{bar(m['interface_accuracy'], pct(m['interface_accuracy']))}</td>" if m["links_found"]
               else "<td><span class='bar-val'>—</span></td>")
            +
            f"<td class='num'>{m.get('duration_s', '—')}</td></tr>")
    return ("<figure class='viz'><div class='table-wrap'><table class='scen'><thead><tr><th scope='col'>Cenário</th>"
            "<th scope='col'>Equipamentos coletados</th><th scope='col'>Links encontrados</th>"
            "<th scope='col'>Portas corretas</th><th scope='col' class='num'>Tempo (s)</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table></div><figcaption>Barras em escala de 0 a 100% do gabarito "
            "(7 equipamentos coletáveis, 9 links físicos). Fonte: <code>metrics.json</code> do run "
            f"{html.escape(d['run'])}.</figcaption></figure>")


STATUS = {"ok": ("✓", "funciona"), "partial": ("◐", "parcial"), "fail": ("✕", "falha"), "na": ("·", "não se aplica")}


def chip(state: str, note: str = "") -> str:
    icon, label = STATUS[state]
    title = f' title="{html.escape(note)}"' if note else ""
    return f'<span class="chip {state}"{title}><span aria-hidden="true">{icon}</span> {label}</span>'


def viz_matrix(d: dict[str, Any]) -> str:
    """Matriz fabricante x método, derivada de per_node dos cenários de método único."""
    m = d["metrics"]
    groups = {"MikroTik CHR 7.16": ["edge-mk1", "edge-mk2"], "Nokia SR Linux 25.10": ["core-srl1", "core-srl2"],
              "Linux / FRR": ["dist-frr1", "srv1", "srv2"]}
    cols = [("04-snmp-v2c", "SNMP v2c"), ("05-snmp-v3", "SNMPv3"), ("06-ssh", "SSH/CLI"),
            ("07-apis", "APIs")]
    head = "".join(f"<th scope='col'>{c}</th>" for _, c in cols)
    body = []
    for g, nodes in groups.items():
        cells = []
        for sid, _ in cols:
            per = m.get(sid, {}).get("per_node", {})
            got = [n for n in nodes if per.get(n, {}).get("collected")]
            state = "ok" if len(got) == len(nodes) else "partial" if got else "fail"
            if sid == "05-snmp-v3" and g != "Linux / FRR":
                state = "na"
            if sid == "07-apis" and g == "Linux / FRR":
                state = "na"
            cells.append(f"<td>{chip(state, f'{len(got)}/{len(nodes)} coletados')}</td>")
        body.append(f"<tr><th scope='row'>{g}</th>{''.join(cells)}</tr>")
    return ("<figure class='viz'><div class='table-wrap'><table class='matrix'><thead><tr><th scope='col'>Sistema</th>"
            + head + "</tr></thead><tbody>" + "".join(body) + "</tbody></table></div><figcaption>"
            "Coleta por método isolado. “Não se aplica”: o método não existe/não foi configurado nesse sistema no "
            "laboratório.</figcaption></figure>")


def viz_parse(d: dict[str, Any]) -> str:
    kinds = ["facts", "hostname", "interfaces", "ip_interfaces", "lldp", "other_l2", "arp", "routes"]
    names = {"facts": "Identificação", "hostname": "Hostname", "interfaces": "Interfaces",
             "ip_interfaces": "IPs", "lldp": "LLDP", "other_l2": "MNDP/LLDP", "arp": "ARP", "routes": "Rotas"}
    show = ["edge-mk1", "core-srl1", "dist-frr1"]
    head = "".join(f"<th scope='col'>{names[k]}</th>" for k in kinds)
    body = []
    for node in show:
        row = d["parse"].get(node, {})
        cells = []
        for k in kinds:
            e = row.get(k)
            if not e:
                cells.append(f"<td>{chip('na')}</td>")
                continue
            rec = e.get("records", 0)
            state = "ok" if rec > 0 else "fail"
            cells.append(f"<td>{chip(state, e.get('command', ''))}<span class='sub'>{rec} reg · "
                         f"{html.escape(str(e.get('parser')))}</span></td>")
        body.append(f"<tr><th scope='row'><code>{node}</code></th>{''.join(cells)}</tr>")
    return ("<figure class='viz'><div class='table-wrap'><table class='matrix parse'><thead><tr>"
            "<th scope='col'>Equipamento</th>" + head + "</tr></thead><tbody>" + "".join(body)
            + "</tbody></table></div><figcaption>Saídas reais dos comandos do perfil de cada fabricante, "
            "interpretadas pelos parsers do NetTopo (registros extraídos · parser usado). Fonte: "
            "<code>raw/parse-matrix.json</code>.</figcaption></figure>")


def viz_shot(name: str, caption: str) -> str:
    p = DATA / "screenshots" / f"{name}.png"
    if not p.exists():
        return f"<p class='missing'>[captura {html.escape(name)} indisponível]</p>"
    b64 = base64.b64encode(p.read_bytes()).decode()
    return (f"<figure class='shot'><img src='data:image/png;base64,{b64}' alt='{html.escape(caption)}' "
            f"loading='lazy'><figcaption>{html.escape(caption)}</figcaption></figure>")


VIZ = {
    "kpis": viz_kpis,
    "scenarios": viz_scenarios,
    "matrix": viz_matrix,
    "parse": viz_parse,
}


def expand(body: str, d: dict[str, Any]) -> str:
    def rep(mt: re.Match[str]) -> str:
        name, arg = mt.group(1), (mt.group(2) or "").strip()
        if name == "shot":
            key, _, caption = arg.partition("|")
            return viz_shot(key.strip(), caption.strip())
        fn = VIZ.get(name)
        return fn(d) if fn else mt.group(0)

    # Blocos com fallback em Markdown: <!-- viz:x --> tabela equivalente <!-- /viz -->
    body = re.sub(r"<!--\s*viz:(\w+)\s*([^>]*?)-->(?:(?!<!--\s*viz:).)*?<!--\s*/viz\s*-->", rep, body,
                  flags=re.S)
    return re.sub(r"<!--\s*viz:(\w+)\s*([^>]*?)-->", rep, body)


# --------------------------------------------------------------------------- página

def split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        return yaml.safe_load(fm) or {}, body
    return {}, text


def render(name: str, d: dict[str, Any]) -> str:
    meta, body_md = split_front_matter((HERE / f"{name}.md").read_text(encoding="utf-8"))
    d = {**d, **meta.get("data", {})}
    md = markdown.Markdown(extensions=["tables", "fenced_code", "attr_list", "toc", "sane_lists", "md_in_html"],
                           extension_configs={"toc": {"toc_depth": "2-2", "permalink": False}})
    body = expand(md.convert(body_md), d)
    toc = md.toc if meta.get("toc") else ""  # type: ignore[attr-defined]
    css = (HERE / "report.css").read_text(encoding="utf-8")
    tag = "".join(f"<div><dt>{html.escape(k)}</dt><dd>{html.escape(str(v))}</dd></div>"
                  for k, v in meta.get("tag", {}).items())
    other = [r for r in REPORTS if r != name][0]
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{html.escape(meta['title'])}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Semi+Condensed:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&display=swap">
<style>{css}</style>
</head>
<body class="{html.escape(name)}">
<div class="page">
<header class="doc-head">
  <div class="doc-kicker">{html.escape(meta.get('kicker', ''))}</div>
  <h1>{html.escape(meta['title'])}</h1>
  <p class="doc-lede">{html.escape(meta.get('lede', ''))}</p>
  <dl class="asset-tag">{tag}</dl>
  <nav class="doc-actions" aria-label="Ações do documento">
    <button type="button" class="btn primary" id="btn-print">Imprimir / salvar PDF</button>
    <a class="btn" href="{PDF_URL.format(name=name)}" target="_blank" rel="noopener">Baixar PDF</a>
    <a class="btn" href="{MD_URL.format(name=name)}" target="_blank" rel="noopener">Ver Markdown</a>
    <a class="btn ghost" href="{other}.html">{html.escape(meta.get('other_label', 'Outro relatório'))}</a>
  </nav>
</header>
{f'<nav class="toc" aria-label="Sumário"><h2>Sumário</h2>{toc}</nav>' if toc else ''}
<main class="doc">
{body}
</main>
<footer class="doc-foot">Gerado a partir dos resultados do run <code>{html.escape(d['run'])}</code> ·
<a href="{REPO_URL}">{REPO_URL.replace('https://', '')}</a></footer>
</div>
<script>
document.getElementById("btn-print").addEventListener("click", function () {{
  try {{ window.print(); }} catch (e) {{ /* visualizador sem impressão */ }}
}});
</script>
</body>
</html>
"""


def find_chrome() -> str | None:
    for c in CHROME:
        if Path(c).exists() or shutil.which(c):
            return c
    return None


def to_pdf(html_path: Path) -> Path | None:
    chrome = find_chrome()
    if not chrome:
        print("Chrome/Edge não encontrado; PDF não gerado")
        return None
    pdf = html_path.with_suffix(".pdf")
    subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    "--virtual-time-budget=8000", f"--print-to-pdf={pdf}", html_path.resolve().as_uri()],
                   check=False, capture_output=True, timeout=180)
    return pdf if pdf.exists() else None


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    run = Path(sys.argv[1])
    copy_data(run)
    d = load_run(run)
    for name in REPORTS:
        if not (HERE / f"{name}.md").exists():
            continue
        out = HERE / f"{name}.html"
        out.write_text(render(name, d), encoding="utf-8")
        print("HTML:", out)
        if "--pdf" in sys.argv:
            print("PDF:", to_pdf(out))


if __name__ == "__main__":
    main()
