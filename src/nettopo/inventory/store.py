"""Inventário persistente: o que a ferramenta já conhece entre uma execução e outra.

Guarda por equipamento o acesso que funcionou (método, nome da credencial, perfil), os IPs de
gerência conhecidos, a assinatura da vizinhança, o último dado completo e o status. Também guarda os
links e um histórico de eventos (novo, inacessível, voltou, alterado, link novo/removido).
Nenhum segredo é gravado aqui: credenciais ficam no cofre (``nettopo.vault``).
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Column, Text
from sqlmodel import Field, Session, SQLModel, create_engine, select

from nettopo.models import L2_PROTOCOLS, Device, Link, Topology, utcnow
from nettopo.utils import ifname_key, normalize_mac, short_hostname, slugify

STATUS_PT = {"novo": "novo", "ativo": "ativo", "alterado": "alterado", "inacessivel": "inacessível",
             "retirado": "retirado"}


def default_data_dir() -> Path:
    return Path(os.environ.get("NETTOPO_DATA", "nettopo_data"))


def device_key(device: Device) -> str:
    return slugify(short_hostname(device.hostname) or device.mgmt_ip or device.id)


def neighbor_pairs(device: Device) -> list[list[str]]:
    """Vizinhança L2 normalizada: ``[interface local, vizinho]`` (independe do protocolo e do método)."""
    pairs = set()
    for n in device.neighbors:
        if n.protocol not in L2_PROTOCOLS:
            continue
        remote = short_hostname(n.remote_hostname) or normalize_mac(n.remote_chassis_id) or n.remote_mgmt_ip
        if remote:
            pairs.add((ifname_key(n.local_interface), remote))
    return [list(p) for p in sorted(pairs)]


def signature(device: Device) -> str:
    return hashlib.sha1(json.dumps(neighbor_pairs(device)).encode(), usedforsecurity=False).hexdigest()[:16]


def link_key(topo: Topology, lk: Link) -> str:
    def end(dev_id: str, itf: str | None) -> str:
        d = topo.devices.get(dev_id)
        return f"{device_key(d) if d else dev_id}:{ifname_key(itf)}"

    a, b = sorted([end(lk.source, lk.source_interface), end(lk.target, lk.target_interface)])
    return f"{lk.kind}|{a}|{b}"


class InvDevice(SQLModel, table=True):
    __tablename__ = "inv_device"

    key: str = Field(primary_key=True)
    hostname: str | None = None
    mgmt_ip: str | None = None
    alt_ips: str = "[]"
    profile: str | None = None
    vendor: str | None = None
    model: str | None = None
    serial: str | None = None
    chassis_mac: str | None = None
    access: str = "{}"  # {"metodo": "rest", "credencial": "rest-mikrotik", "snmp": "snmp-v2c", "perfil": "..."}
    neighbors_sig: str | None = None
    data: str | None = Field(default=None, sa_column=Column(Text))  # último Device completo (JSON)
    status: str = "novo"
    first_seen: datetime = Field(default_factory=utcnow)
    last_seen: datetime | None = None
    last_verified: datetime | None = None
    last_full: datetime | None = None
    fail_count: int = 0
    last_error: str | None = Field(default=None, sa_column=Column(Text))

    def device(self) -> Device | None:
        return Device.model_validate_json(self.data) if self.data else None

    def ips(self) -> list[str]:
        out = [self.mgmt_ip] if self.mgmt_ip else []
        out += [ip for ip in json.loads(self.alt_ips or "[]") if ip not in out]
        return out

    def access_info(self) -> dict[str, Any]:
        return json.loads(self.access or "{}")

    def summary(self) -> dict[str, Any]:
        return {"key": self.key, "hostname": self.hostname, "mgmt_ip": self.mgmt_ip, "vendor": self.vendor,
                "model": self.model, "profile": self.profile, "status": self.status,
                "status_label": STATUS_PT.get(self.status, self.status), "access": self.access_info(),
                "first_seen": _iso(self.first_seen), "last_seen": _iso(self.last_seen),
                "last_verified": _iso(self.last_verified), "last_full": _iso(self.last_full),
                "fail_count": self.fail_count, "last_error": self.last_error}


class InvLink(SQLModel, table=True):
    __tablename__ = "inv_link"

    key: str = Field(primary_key=True)
    kind: str = "physical"
    a: str = ""
    b: str = ""
    status: str = "ativo"
    first_seen: datetime = Field(default_factory=utcnow)
    last_seen: datetime | None = None


class InvUnreachable(SQLModel, table=True):
    """Endereços anunciados que não responderam: evita repetir timeouts a cada execução."""

    __tablename__ = "inv_unreachable"

    ip: str = Field(primary_key=True)
    reason: str | None = Field(default=None, sa_column=Column(Text))
    last_try: datetime = Field(default_factory=utcnow)
    tries: int = 1


class InvEvent(SQLModel, table=True):
    __tablename__ = "inv_event"

    id: int | None = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=utcnow)
    device_key: str | None = None
    kind: str = ""
    detail: str | None = Field(default=None, sa_column=Column(Text))

    def summary(self) -> dict[str, Any]:
        return {"ts": _iso(self.ts), "device": self.device_key, "kind": self.kind, "detail": self.detail}


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        from datetime import timezone

        return dt.replace(tzinfo=timezone.utc)
    return dt


class InventoryStore:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = Path(data_dir or default_data_dir())
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{self.data_dir / 'nettopo.db'}",
                                    connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)

    # ----------------------------------------------------------------- leitura
    def devices(self, include_retired: bool = False) -> list[InvDevice]:
        with Session(self.engine) as s:
            rows = list(s.exec(select(InvDevice).order_by(InvDevice.key)))
        return [r for r in rows if include_retired or r.status != "retirado"]

    def get(self, key: str) -> InvDevice | None:
        with Session(self.engine) as s:
            return s.get(InvDevice, key)

    def known_hosts(self) -> dict[str, list[str]]:
        """hostname curto -> IPs de gerência que já funcionaram (para alcançar vizinhos)."""
        out: dict[str, list[str]] = {}
        for r in self.devices():
            host = short_hostname(r.hostname)
            if host and r.mgmt_ip:
                out[host] = r.ips()
        return out

    def events(self, limit: int = 200) -> list[InvEvent]:
        with Session(self.engine) as s:
            return list(s.exec(select(InvEvent).order_by(InvEvent.id.desc()).limit(limit)))  # type: ignore[union-attr]

    def links(self) -> list[InvLink]:
        with Session(self.engine) as s:
            return list(s.exec(select(InvLink).order_by(InvLink.key)))

    # ----------------------------------------------------------------- escrita
    def _event(self, s: Session, key: str | None, kind: str, detail: str | None = None) -> None:
        s.add(InvEvent(device_key=key, kind=kind, detail=detail))

    def record(self, topo: Topology, checks: dict[str, dict[str, Any]] | None = None,
               retire_after_days: int = 30) -> list[dict[str, Any]]:
        """Atualiza o inventário com o resultado de uma execução e devolve os eventos gerados.

        ``checks``: resultado da revalidação por chave (``{"status": "ativo"|"alterado"|"inacessivel",
        "erro": ...}``); equipamentos coletados por completo nesta execução vêm de ``topo``.
        """
        checks = checks or {}
        now = utcnow()
        new_events: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        with Session(self.engine) as s:
            for d in sorted(topo.devices.values(), key=lambda x: x.id):
                if d.stub and d.extra.get("status") != "inacessivel":
                    continue
                key = device_key(d)
                seen_keys.add(key)
                row = s.get(InvDevice, key)
                check = checks.get(key, {})
                if d.stub:  # equipamento conhecido que não respondeu nesta execução
                    if row is None:
                        continue
                    if row.status != "inacessivel":
                        self._event(s, key, "inacessivel", check.get("erro") or d.extra.get("motivo"))
                        new_events.append({"device": key, "kind": "inacessivel"})
                    row.status = "inacessivel"
                    row.fail_count += 1
                    row.last_error = check.get("erro") or d.extra.get("motivo")
                    last = _aware(row.last_seen)
                    if last and now - last > timedelta(days=retire_after_days):
                        row.status = "retirado"
                        self._event(s, key, "retirado", f"sem resposta há mais de {retire_after_days} dias")
                    s.add(row)
                    continue
                if row is None:
                    row = InvDevice(key=key, first_seen=now)
                    self._event(s, key, "novo", f"{d.vendor or ''} {d.model or ''} {d.mgmt_ip or ''}".strip())
                    new_events.append({"device": key, "kind": "novo"})
                else:
                    if row.status in ("inacessivel", "retirado"):
                        self._event(s, key, "voltou", f"respondeu novamente em {d.extra.get('reached_via') or d.mgmt_ip}")
                        new_events.append({"device": key, "kind": "voltou"})
                    changes = [f"{f}: {getattr(row, f)} -> {v}" for f, v in
                               (("serial", d.serial), ("model", d.model), ("vendor", d.vendor))
                               if getattr(row, f) and v and getattr(row, f) != v]
                    if row.neighbors_sig and row.neighbors_sig != signature(d) and not d.extra.get("reutilizado"):
                        changes.append("vizinhança mudou")
                    if changes:
                        self._event(s, key, "alterado", "; ".join(changes))
                        new_events.append({"device": key, "kind": "alterado", "detail": changes})
                ips = [ip for ip in [d.mgmt_ip, d.extra.get("reached_via")] if ip]
                old_ips = row.ips()
                row.alt_ips = json.dumps(sorted({*old_ips, *ips} - {d.mgmt_ip}))
                row.hostname, row.mgmt_ip = d.hostname, d.mgmt_ip
                row.profile, row.vendor, row.model = d.profile, d.vendor, d.model
                row.serial, row.chassis_mac = d.serial, normalize_mac(d.chassis_id)
                if d.extra.get("acesso"):
                    row.access = json.dumps(d.extra["acesso"])
                row.neighbors_sig = signature(d)
                stored = d.model_copy(deep=True)
                stored.role, stored.tier = "unknown", None
                for k in ("status", "reutilizado", "verificado_em", "capabilities", "motivo"):
                    stored.extra.pop(k, None)
                row.data = stored.model_dump_json()
                row.status = "ativo"
                row.fail_count = 0
                row.last_error = None
                row.last_seen = row.last_verified = now
                if not d.extra.get("reutilizado"):
                    row.last_full = now
                s.add(row)
            # links
            current = {link_key(topo, lk): lk for lk in topo.links
                       if not topo.devices[lk.source].stub or not topo.devices[lk.target].stub}
            for key, lk in current.items():
                row_l = s.get(InvLink, key)
                if row_l is None:
                    row_l = InvLink(key=key, kind=lk.kind, a=key.split("|")[1], b=key.split("|")[2], first_seen=now)
                    if self.has_history():
                        self._event(s, None, "link_novo", f"{row_l.a} <-> {row_l.b}")
                        new_events.append({"kind": "link_novo", "detail": key})
                elif row_l.status != "ativo":
                    self._event(s, None, "link_voltou", f"{row_l.a} <-> {row_l.b}")
                row_l.status, row_l.last_seen = "ativo", now
                s.add(row_l)
            for row_l in s.exec(select(InvLink)):
                if row_l.key not in current and row_l.status == "ativo":
                    row_l.status = "removido"
                    self._event(s, None, "link_removido", f"{row_l.a} <-> {row_l.b}")
                    new_events.append({"kind": "link_removido", "detail": row_l.key})
                    s.add(row_l)
            s.commit()
        return new_events

    def recent_unreachable(self, hours: float) -> dict[str, str]:
        """IPs que falharam há menos de ``hours`` horas -> motivo (para não tentar de novo agora)."""
        now = utcnow()
        out: dict[str, str] = {}
        with Session(self.engine) as s:
            for row in s.exec(select(InvUnreachable)):
                last = _aware(row.last_try)
                if last and now - last < timedelta(hours=hours):
                    out[row.ip] = (f"sem resposta na última tentativa ({last:%d/%m %H:%M}, {row.tries}x); "
                                   f"nova tentativa após {hours:g} h ou com --completo: {row.reason or ''}")
        return out

    def record_unreachable(self, failed: dict[str, str], succeeded: set[str]) -> None:
        now = utcnow()
        with Session(self.engine) as s:
            for ip, reason in failed.items():
                if reason.startswith("sem resposta na última tentativa"):
                    continue  # não foi tentado agora (veio da memória)
                row = s.get(InvUnreachable, ip)
                if row is None:
                    row = InvUnreachable(ip=ip, reason=reason[:2000], last_try=now)
                else:
                    row.reason, row.last_try, row.tries = reason[:2000], now, row.tries + 1
                s.add(row)
            for ip in succeeded:
                row = s.get(InvUnreachable, ip)
                if row is not None:
                    s.delete(row)
            s.commit()

    def has_history(self) -> bool:
        with Session(self.engine) as s:
            return s.exec(select(InvDevice).limit(1)).first() is not None

    def clear(self) -> None:
        with Session(self.engine) as s:
            for model in (InvEvent, InvLink, InvDevice, InvUnreachable):
                for row in s.exec(select(model)):
                    s.delete(row)
            s.commit()
