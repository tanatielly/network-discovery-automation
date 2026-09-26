"""Persistência das descobertas (SQLite via SQLModel). Credenciais nunca são gravadas."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Column, Text
from sqlmodel import Field, Session, SQLModel, create_engine, select

from nettopo.models import Topology, utcnow


class DiscoveryRecord(SQLModel, table=True):
    __tablename__ = "discoveries"

    id: str = Field(primary_key=True)
    name: str | None = None
    status: str = "queued"  # queued | running | finished | failed
    demo: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    seeds: str = "[]"
    settings_json: str = Field(default="{}", sa_column=Column(Text))
    stats_json: str | None = Field(default=None, sa_column=Column(Text))
    topology_json: str | None = Field(default=None, sa_column=Column(Text))
    error: str | None = Field(default=None, sa_column=Column(Text))

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "status": self.status, "demo": self.demo,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "seeds": json.loads(self.seeds or "[]"),
            "stats": json.loads(self.stats_json) if self.stats_json else None,
            "error": self.error,
        }


def default_data_dir() -> Path:
    return Path(os.environ.get("NETTOPO_DATA", "nettopo_data"))


class Store:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{self.data_dir / 'nettopo.db'}",
                                    connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)

    def add(self, rec: DiscoveryRecord) -> DiscoveryRecord:
        with Session(self.engine) as s:
            s.add(rec)
            s.commit()
            s.refresh(rec)
            return rec

    def update(self, rid: str, **fields: Any) -> None:
        with Session(self.engine) as s:
            rec = s.get(DiscoveryRecord, rid)
            if rec is None:
                return
            for k, v in fields.items():
                setattr(rec, k, v)
            s.add(rec)
            s.commit()

    def get(self, rid: str) -> DiscoveryRecord | None:
        with Session(self.engine) as s:
            return s.get(DiscoveryRecord, rid)

    def list(self, limit: int = 100) -> list[DiscoveryRecord]:
        with Session(self.engine) as s:
            stmt = select(DiscoveryRecord).order_by(DiscoveryRecord.created_at.desc()).limit(limit)
            return list(s.exec(stmt))

    def delete(self, rid: str) -> bool:
        with Session(self.engine) as s:
            rec = s.get(DiscoveryRecord, rid)
            if rec is None:
                return False
            s.delete(rec)
            s.commit()
            return True

    def topology(self, rid: str) -> Topology | None:
        rec = self.get(rid)
        if rec is None or not rec.topology_json:
            return None
        return Topology.model_validate_json(rec.topology_json)

    def mark_interrupted(self) -> None:
        """Descobertas que estavam rodando quando o servidor caiu."""
        with Session(self.engine) as s:
            for rec in s.exec(select(DiscoveryRecord).where(DiscoveryRecord.status.in_(["queued", "running"]))):
                rec.status = "failed"
                rec.error = "interrompida (servidor reiniciado)"
                s.add(rec)
            s.commit()
