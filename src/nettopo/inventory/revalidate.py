"""Revalidação dos equipamentos já conhecidos e descoberta com memória.

Na próxima execução, cada equipamento do inventário passa por uma checagem leve (identidade +
vizinhança) usando o acesso que funcionou da última vez:

- respondeu, mesma identidade e mesma vizinhança -> dados reaproveitados ("verificado agora");
- respondeu com vizinhança ou identidade diferente -> coleta completa ("alterado");
- não respondeu em nenhum IP conhecido -> nova tentativa completa; se falhar, "inacessível".

Depois a descoberta normal segue a partir dos vizinhos, coletando só o que é novo.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from nettopo.config import Settings
from nettopo.discovery.engine import DiscoveryEngine, ProgressCallback
from nettopo.inventory.store import InvDevice, InventoryStore, signature
from nettopo.models import Device, Topology, utcnow
from nettopo.utils import short_hostname

log = logging.getLogger(__name__)


@dataclass
class Revalidation:
    devices: list[Device] = field(default_factory=list)  # ativos (reaproveitados ou recoletados)
    inactive: list[Device] = field(default_factory=list)  # conhecidos que não responderam
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)
    stats: dict[str, int] = field(default_factory=lambda: {"reaproveitados": 0, "recoletados": 0,
                                                           "inacessiveis": 0})


async def _emit(progress: ProgressCallback | None, event: dict[str, Any]) -> None:
    if progress is None:
        return
    r = progress(event)
    if inspect.isawaitable(r):
        await r


async def revalidate(records: list[InvDevice], settings: Settings, collector: Any,
                     progress: ProgressCallback | None = None, full: bool = False,
                     max_age: timedelta = timedelta(hours=24)) -> Revalidation:
    result = Revalidation()
    sem = asyncio.Semaphore(max(1, min(settings.concurrency, settings.carga.concurrency)))
    now = utcnow()
    can_light = hasattr(collector, "light_check")

    async def one(rec: InvDevice) -> None:
        async with sem:
            stored = rec.device()
            access = rec.access_info()
            last_full = rec.last_full
            if last_full is not None and last_full.tzinfo is None:
                last_full = last_full.replace(tzinfo=now.tzinfo)
            fresh = last_full is not None and now - last_full < max_age
            reason = "dados completos com mais de 24 h" if not fresh else None
            if full:
                reason = "coleta completa solicitada"
            changed = False
            if can_light and not full and fresh and stored is not None and access:
                for ip in rec.ips():
                    light = await collector.light_check(ip, access)
                    if light is None:
                        continue
                    same_host = short_hostname(light.hostname) == short_hostname(rec.hostname)
                    if same_host and signature(light) == rec.neighbors_sig:
                        dev = stored.model_copy(deep=True)
                        dev.mgmt_ip = rec.mgmt_ip or ip
                        dev.extra.update({"reutilizado": True, "verificado_em": now.isoformat(), "status": "ativo",
                                          "reached_via": ip, "carga": light.extra.get("carga")})
                        dev.errors = []
                        result.devices.append(dev)
                        result.checks[rec.key] = {"status": "ativo"}
                        result.stats["reaproveitados"] += 1
                        await _emit(progress, {"type": "revalidated", "hostname": rec.hostname, "target": ip,
                                               "status": "ativo", "reused": True})
                        return
                    changed = True
                    reason = "identidade diferente no IP" if not same_host else "vizinhança mudou"
                    break
            # coleta completa nos IPs conhecidos
            errors: list[str] = []
            for ip in rec.ips():
                dev = await collector.collect(ip)
                if dev.reachable and (not rec.hostname or short_hostname(dev.hostname) == short_hostname(rec.hostname)):
                    status = "alterado" if changed else "ativo"
                    dev.extra.update({"status": status, "verificado_em": now.isoformat(), "reached_via": ip,
                                      "motivo_recoleta": reason})
                    result.devices.append(dev)
                    result.checks[rec.key] = {"status": status, "motivo": reason}
                    result.stats["recoletados"] += 1
                    await _emit(progress, {"type": "revalidated", "hostname": rec.hostname, "target": ip,
                                           "status": status, "reused": False, "reason": reason})
                    return
                errors.append(f"{ip}: " + ("; ".join(dev.errors) if not dev.reachable
                                           else f"respondeu como {dev.hostname}"))
            last = rec.last_seen.isoformat() if rec.last_seen else "nunca"
            stub = Device(id=f"inativo-{rec.key}", hostname=rec.hostname, mgmt_ip=rec.mgmt_ip, vendor=rec.vendor,
                          model=rec.model, profile=rec.profile, serial=rec.serial, chassis_id=rec.chassis_mac,
                          reachable=False, stub=True, collected_via=["inventário"])
            stub.extra.update({"status": "inacessivel", "ultima_vez": last,
                               "motivo": f"conhecido, mas sem resposta (última vez visto: {last}): "
                                         + " | ".join(errors)})
            result.inactive.append(stub)
            result.checks[rec.key] = {"status": "inacessivel", "erro": " | ".join(errors)}
            result.stats["inacessiveis"] += 1
            await _emit(progress, {"type": "revalidated", "hostname": rec.hostname, "status": "inacessivel",
                                   "reason": " | ".join(errors)[:300]})

    await asyncio.gather(*(one(r) for r in records))
    result.devices.sort(key=lambda d: d.hostname or "")
    return result


async def discover_with_memory(settings: Settings, store: InventoryStore | None = None, collector: Any = None,
                               progress: ProgressCallback | None = None, full: bool = False,
                               verify_only: bool = False, retry_unreachable_h: float = 6.0) -> Topology:
    """Descoberta completa usando e atualizando a memória persistente.

    ``verify_only``: só confirma os equipamentos conhecidos (não segue vizinhos novos).
    """
    from nettopo.discovery.sweep import sweep

    if collector is None:
        from nettopo.collectors.orchestrator import Orchestrator

        collector = Orchestrator(settings)
    records = store.devices() if store is not None else []
    known = store.known_hosts() if store is not None else {}
    started = utcnow()
    await _emit(progress, {"type": "memory", "known": len(records)})
    reval = await revalidate(records, settings, collector, progress, full=full) if records else Revalidation()
    extra = [] if verify_only else await sweep(settings, collector, known, progress)
    if verify_only:
        settings = settings.model_copy(update={"seeds": [], "max_depth": 0})
    skip = store.recent_unreachable(retry_unreachable_h) if (store is not None and not full) else {}
    engine = DiscoveryEngine(settings, collector=collector, progress=progress, known_hosts=known, skip_ips=skip)
    topo = await engine.run(extra_targets=extra, preloaded=reval.devices + reval.inactive)
    topo.meta.started_at = started
    events = store.record(topo, reval.checks) if store is not None else []
    if store is not None:
        reached = {d.extra.get("reached_via") or d.mgmt_ip for d in topo.devices.values() if not d.stub}
        store.record_unreachable(topo.meta.failed_targets, {ip for ip in reached if ip})
    collected_now = sum(1 for d in topo.devices.values() if not d.stub and not d.extra.get("reutilizado"))
    topo.meta.stats["memoria"] = {
        "conhecidos": len(records), **reval.stats,
        "novos_coletados": max(0, collected_now - reval.stats["recoletados"]),
        "eventos": events,
    }
    if topo.meta.finished_at:
        topo.meta.stats["duration_s"] = round((topo.meta.finished_at - started).total_seconds(), 1)
    return topo
