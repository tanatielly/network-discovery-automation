"""API REST + WebSocket + interface web."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import shutil
import tempfile
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from nettopo import __version__
from nettopo.api.store import DiscoveryRecord, Store
from nettopo.collectors.base import DeviceCollector
from nettopo.config import Settings
from nettopo.models import utcnow
from nettopo.output import FORMATS, export
from nettopo.output.html import viewer_payload
from nettopo.utils import slugify
from nettopo.vendors.registry import default_registry

HERE = Path(__file__).parent
STATIC = HERE / "static"
ASSETS = HERE.parent / "output" / "assets"
MAX_EVENTS = 3000


@dataclass
class Job:
    id: str
    task: asyncio.Task[Any] | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    subscribers: set[asyncio.Queue[dict[str, Any]]] = field(default_factory=set)
    done: bool = False

    def publish(self, event: dict[str, Any]) -> None:
        event = {**event, "ts": utcnow().isoformat()}
        self.events.append(event)
        if len(self.events) > MAX_EVENTS:
            del self.events[: len(self.events) - MAX_EVENTS]
        for q in list(self.subscribers):
            q.put_nowait(event)


class JobManager:
    def __init__(self, store: Store):
        self.store = store
        self.jobs: dict[str, Job] = {}

    def start(self, settings: Settings, collector: DeviceCollector | None = None, demo: bool = False) -> str:
        from nettopo.discovery.engine import discover

        rid = uuid.uuid4().hex[:12]
        self.store.add(DiscoveryRecord(id=rid, name=settings.name, demo=demo, seeds=json.dumps(settings.seeds),
                                       settings_json=json.dumps(settings.sanitized())))
        job = Job(id=rid)
        self.jobs[rid] = job

        async def run() -> None:
            self.store.update(rid, status="running")
            try:
                topo = await discover(settings, collector=collector, progress=job.publish)
                self.store.update(rid, status="finished", finished_at=utcnow(),
                                  stats_json=json.dumps(topo.meta.stats), topology_json=topo.model_dump_json())
            except Exception as exc:  # erro inesperado vira status "failed"
                self.store.update(rid, status="failed", finished_at=utcnow(), error=f"{type(exc).__name__}: {exc}")
                job.publish({"type": "error", "message": str(exc)})
            finally:
                job.done = True
                job.publish({"type": "closed"})

        job.task = asyncio.create_task(run())
        return rid


def _auth(request: Request) -> None:
    token = os.environ.get("NETTOPO_API_TOKEN")
    if not token:
        return
    header = request.headers.get("authorization", "")
    if not secrets.compare_digest(header, f"Bearer {token}"):
        raise HTTPException(status_code=401, detail="token inválido")


def create_app(data_dir: Path | None = None) -> FastAPI:
    store = Store(data_dir)
    manager = JobManager(store)

    @asynccontextmanager
    async def lifespan(_: FastAPI):  # noqa: ANN202
        store.mark_interrupted()
        yield

    app = FastAPI(title="NetTopo API", version=__version__, lifespan=lifespan,
                  description="Descoberta automática de topologia de rede multi-vendor.")
    app.state.store = store
    app.state.jobs = manager
    guard = [Depends(_auth)]

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/vendors", dependencies=guard)
    def vendors() -> list[dict[str, Any]]:
        return [{"id": p.id, "vendor": p.vendor, "os": p.os, "category": p.category, "methods": p.methods,
                 "netmiko": p.netmiko, "rest": p.rest, "netconf": p.netconf}
                for p in sorted(default_registry().all(), key=lambda p: (p.vendor, p.os))]

    @app.post("/api/discoveries", status_code=202, dependencies=guard)
    async def start_discovery(settings: Settings) -> dict[str, Any]:
        if not settings.seeds:
            raise HTTPException(status_code=422, detail="informe ao menos uma semente")
        rid = manager.start(settings)
        return {"id": rid, "status": "queued"}

    @app.post("/api/demo", status_code=202, dependencies=guard)
    async def start_demo() -> dict[str, Any]:
        from nettopo.collectors.simulated import SimulatedCollector, demo_settings

        sim = SimulatedCollector(delay=0.25)
        rid = manager.start(demo_settings(sim, concurrency=4), collector=sim, demo=True)
        return {"id": rid, "status": "queued"}

    @app.get("/api/discoveries", dependencies=guard)
    def list_discoveries(limit: int = 100) -> list[dict[str, Any]]:
        return [r.summary() for r in store.list(limit)]

    @app.get("/api/discoveries/{rid}", dependencies=guard)
    def get_discovery(rid: str) -> dict[str, Any]:
        rec = store.get(rid)
        if rec is None:
            raise HTTPException(status_code=404, detail="descoberta não encontrada")
        out = rec.summary()
        job = manager.jobs.get(rid)
        out["events"] = len(job.events) if job else 0
        return out

    @app.delete("/api/discoveries/{rid}", dependencies=guard)
    def delete_discovery(rid: str) -> dict[str, bool]:
        job = manager.jobs.pop(rid, None)
        if job and job.task and not job.task.done():
            job.task.cancel()
        if not store.delete(rid):
            raise HTTPException(status_code=404, detail="descoberta não encontrada")
        return {"deleted": True}

    @app.get("/api/discoveries/{rid}/view", dependencies=guard)
    def view(rid: str) -> JSONResponse:
        topo = store.topology(rid)
        if topo is None:
            raise HTTPException(status_code=404, detail="topologia indisponível (descoberta em andamento ou falhou)")
        return JSONResponse(viewer_payload(topo))

    @app.get("/api/discoveries/{rid}/export/{fmt}", dependencies=guard)
    def export_file(rid: str, fmt: str, background: BackgroundTasks) -> FileResponse:
        if fmt not in FORMATS:
            raise HTTPException(status_code=400, detail=f"formato inválido; use {', '.join(FORMATS)}")
        topo = store.topology(rid)
        if topo is None:
            raise HTTPException(status_code=404, detail="topologia indisponível")
        tmp = Path(tempfile.mkdtemp(prefix="nettopo-"))
        background.add_task(shutil.rmtree, tmp, True)
        base = slugify(topo.meta.name or f"topologia-{rid}")
        path = export(topo, fmt, tmp, base)
        if fmt == "md":
            archive = shutil.make_archive(str(tmp / f"{base}-docs"), "zip", root_dir=path.parent)
            return FileResponse(archive, filename=f"{base}-docs.zip", media_type="application/zip")
        media = {"html": "text/html", "json": "application/json", "drawio": "application/xml",
                 "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}[fmt]
        return FileResponse(path, filename=path.name, media_type=media)

    @app.websocket("/api/discoveries/{rid}/events")
    async def events(ws: WebSocket, rid: str) -> None:
        token = os.environ.get("NETTOPO_API_TOKEN")
        if token and not secrets.compare_digest(ws.query_params.get("token", ""), token):
            await ws.close(code=4401)
            return
        await ws.accept()
        job = manager.jobs.get(rid)
        if job is None:
            rec = store.get(rid)
            await ws.send_json({"type": "closed", "status": rec.status if rec else "unknown"})
            await ws.close()
            return
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        for ev in list(job.events):
            q.put_nowait(ev)
        job.subscribers.add(q)
        try:
            while True:
                ev = await q.get()
                await ws.send_json(ev)
                if ev.get("type") == "closed":
                    break
        except WebSocketDisconnect:
            pass
        finally:
            job.subscribers.discard(q)
        try:
            await ws.close()
        except RuntimeError:
            pass

    app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> HTMLResponse:
        return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))

    return app
