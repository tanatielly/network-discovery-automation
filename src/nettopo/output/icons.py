"""Ícones SVG por papel (embutidos como data URI no HTML e na UI web)."""

from __future__ import annotations

from urllib.parse import quote

ROLE_COLORS = {
    "router": "#1f6feb",
    "l3switch": "#0e7c66",
    "switch": "#2da44e",
    "firewall": "#cf222e",
    "wireless_controller": "#8250df",
    "ap": "#8250df",
    "server": "#57606a",
    "phone": "#bc4c00",
    "external": "#6e7781",
    "unknown": "#8c959f",
}

ROLE_LABELS = {
    "router": "Roteador",
    "l3switch": "Switch L3",
    "switch": "Switch",
    "firewall": "Firewall",
    "wireless_controller": "Controladora Wi-Fi",
    "ap": "Access Point",
    "server": "Servidor/Host",
    "phone": "Telefone IP",
    "external": "Externo",
    "unknown": "Desconhecido",
}

TIER_LABELS = {
    "external": "Externo / Operadoras",
    "edge": "Borda / Roteamento",
    "security": "Segurança",
    "core": "Núcleo (Core)",
    "distribution": "Distribuição",
    "access": "Acesso",
    "endpoint": "Endpoints",
}

_ARROW = "M0,-9 L6,-3 L2,-3 L2,9 L-2,9 L-2,-3 L-6,-3 Z"


def _router(c: str) -> str:
    arrows = "".join(
        f'<path d="{_ARROW}" fill="#fff" transform="translate(32 32) rotate({a}) translate(0 -12) scale(.85)"/>'
        for a in (45, 135, 225, 315))
    return f'<circle cx="32" cy="32" r="28" fill="{c}"/>{arrows}'


def _switch(c: str, l3: bool = False) -> str:
    rows = ""
    for i, (y, rot) in enumerate(((22, 90), (30, -90), (38, 90), (46, -90))):
        rows += f'<path d="{_ARROW}" fill="#fff" transform="translate({24 if i % 2 == 0 else 40} {y}) rotate({rot}) scale(.55)"/>'
    badge = ('<rect x="40" y="4" width="20" height="13" rx="3" fill="#fff"/>'
             f'<text x="50" y="14" font-size="10" font-family="Arial" font-weight="700" fill="{c}" '
             'text-anchor="middle">L3</text>') if l3 else ""
    return f'<rect x="4" y="12" width="56" height="42" rx="8" fill="{c}"/>{rows}{badge}'


def _firewall(c: str) -> str:
    bricks = ""
    for r in range(4):
        y = 12 + r * 11
        off = 0 if r % 2 == 0 else 8
        for x in range(-8 + off, 56, 16):
            x0 = max(6, x + 6)
            w = min(x + 6 + 14, 58) - x0
            if w > 3:
                bricks += f'<rect x="{x0}" y="{y}" width="{w}" height="9" rx="1.5" fill="#fff" opacity=".9"/>'
    return f'<rect x="4" y="8" width="56" height="50" rx="6" fill="{c}"/>{bricks}'


def _ap(c: str) -> str:
    return (f'<circle cx="32" cy="32" r="28" fill="{c}"/>'
            '<circle cx="32" cy="42" r="4" fill="#fff"/>'
            '<path d="M22 34 a14 14 0 0 1 20 0" stroke="#fff" stroke-width="4" fill="none" stroke-linecap="round"/>'
            '<path d="M15 27 a24 24 0 0 1 34 0" stroke="#fff" stroke-width="4" fill="none" stroke-linecap="round"/>')


def _server(c: str) -> str:
    slots = "".join(f'<rect x="16" y="{y}" width="32" height="10" rx="2" fill="#fff" opacity=".9"/>'
                    f'<circle cx="42" cy="{y + 5}" r="2" fill="{c}"/>' for y in (12, 27, 42))
    return f'<rect x="10" y="4" width="44" height="56" rx="6" fill="{c}"/>{slots}'


def _phone(c: str) -> str:
    return (f'<rect x="8" y="8" width="48" height="48" rx="10" fill="{c}"/>'
            '<path d="M22 18 q-6 0 -6 8 q2 14 22 22 q8 0 8-6 l-7-6 -5 4 q-8-4 -10-10 l4-5 z" fill="#fff"/>')


def _cloud(c: str) -> str:
    return (f'<path d="M18 48 a12 12 0 0 1 0-24 a16 16 0 0 1 30 -2 a11 11 0 0 1 0 26 z" fill="{c}"/>'
            '<text x="32" y="42" font-size="11" font-family="Arial" font-weight="700" fill="#fff" '
            'text-anchor="middle">EXT</text>')


def _unknown(c: str) -> str:
    return (f'<circle cx="32" cy="32" r="27" fill="#fff" stroke="{c}" stroke-width="4" stroke-dasharray="6 4"/>'
            f'<text x="32" y="41" font-size="26" font-family="Arial" font-weight="700" fill="{c}" '
            'text-anchor="middle">?</text>')


_BUILDERS = {
    "router": _router, "l3switch": lambda c: _switch(c, True), "switch": _switch, "firewall": _firewall,
    "ap": _ap, "wireless_controller": _ap, "server": _server, "phone": _phone, "external": _cloud,
    "unknown": _unknown,
}


def icon_svg(role: str) -> str:
    color = ROLE_COLORS.get(role, ROLE_COLORS["unknown"])
    body = _BUILDERS.get(role, _unknown)(color)
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">{body}</svg>'


def icon_data_uri(role: str) -> str:
    return "data:image/svg+xml;charset=utf-8," + quote(icon_svg(role))


def all_icons() -> dict[str, str]:
    return {role: icon_data_uri(role) for role in ROLE_COLORS}
