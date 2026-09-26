"""Motor de descoberta: BFS assíncrono a partir das sementes."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from nettopo import __version__
from nettopo.collectors.base import DeviceCollector
from nettopo.config import Settings
from nettopo.discovery.identity import IdentityIndex
from nettopo.discovery.scope import next_targets, resolve_hostname
from nettopo.models import DiscoveryMeta, Topology, utcnow
from nettopo.topology.builder import build_topology
from nettopo.utils import is_default_hostname, short_hostname
from nettopo.vendors.registry import VendorRegistry, default_registry

log = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


class DiscoveryEngine:
    def __init__(self, settings: Settings, collector: DeviceCollector | None = None,
                 registry: VendorRegistry | None = None, progress: ProgressCallback | None = None):
        self.settings = settings
        self.registry = registry or default_registry()
        if collector is None:
            from nettopo.collectors.orchestrator import Orchestrator

            collector = Orchestrator(settings, self.registry)
        self.collector = collector
        self.progress = progress
        self.index = IdentityIndex()
        self.failed: dict[str, str] = {}
        self._queued: set[str] = set()
        self._queued_hosts: set[str] = set()  # hostnames anunciados já enfileirados
        self._lock = asyncio.Lock()
        self._processed = 0

    async def _emit(self, event: dict[str, Any]) -> None:
        if self.progress is None:
            return
        try:
            r = self.progress(event)
            if inspect.isawaitable(r):
                await r
        except Exception:  # callback nunca derruba a descoberta
            log.debug("progress callback falhou", exc_info=True)

    async def run(self) -> Topology:
        meta = DiscoveryMeta(name=self.settings.name, seeds=list(self.settings.seeds), tool_version=__version__,
                             max_depth=self.settings.max_depth, settings=self.settings.sanitized())
        queue: asyncio.Queue[tuple[str, int, str | None]] = asyncio.Queue()
        seed_ips: set[str] = set()
        for seed in self.settings.seeds:
            ip = await resolve_hostname(seed)
            if not ip:
                self.failed[seed] = "não foi possível resolver o nome"
                continue
            seed_ips.add(ip)
            self._queued.add(ip)
            queue.put_nowait((ip, 0, None))
        self._seed_ips = seed_ips
        await self._emit({"type": "started", "seeds": sorted(seed_ips)})

        workers = [asyncio.create_task(self._worker(queue)) for _ in range(max(1, self.settings.concurrency))]
        try:
            await queue.join()
        finally:
            for w in workers:
                w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            await self.collector.close()

        meta.failed_targets = dict(self.failed)
        meta.finished_at = utcnow()
        topo = build_topology(self.index.devices, self.settings, meta, self.registry)
        await self._emit({"type": "finished", "stats": topo.meta.stats})
        return topo

    async def _worker(self, queue: asyncio.Queue[tuple[str, int, str | None]]) -> None:
        while True:
            target, depth, parent = await queue.get()
            try:
                await self._process(queue, target, depth, parent)
            except Exception as exc:
                log.exception("erro processando %s", target)
                self.failed[target] = f"erro interno: {exc}"
            finally:
                queue.task_done()

    async def _process(self, queue: asyncio.Queue[tuple[str, int, str | None]], target: str, depth: int,
                       parent: str | None) -> None:
        if len(self.index.devices) >= self.settings.max_devices:
            self.failed[target] = "limite max_devices atingido"
            return
        if self.index.lookup_ip(target):
            return  # IP pertence a um equipamento já coletado
        await self._emit({"type": "device_started", "target": target, "depth": depth, "parent": parent})
        device = await self.collector.collect(target)
        self._processed += 1
        if not device.reachable:
            reason = "; ".join(device.errors) or "inacessível"
            self.failed[target] = reason
            await self._emit({"type": "device_failed", "target": target, "reason": reason[:300],
                              "processed": self._processed})
            return
        device.depth = depth
        device.discovered_from = parent
        async with self._lock:
            device = self.index.add(device)
        await self._emit({"type": "device_done", "target": target, "id": device.id, "hostname": device.hostname,
                          "vendor": device.vendor, "model": device.model, "via": device.collected_via,
                          "neighbors": len(device.neighbors), "processed": self._processed,
                          "known": len(self.index.devices)})
        if depth >= self.settings.max_depth:
            return
        for ip, hostname in await next_targets(device, self.settings):
            host = short_hostname(hostname)
            async with self._lock:
                if ip in self._queued or self.index.lookup_ip(ip) or self.index.lookup_hostname(hostname):
                    continue
                if host and not is_default_hostname(host):
                    if host in self._queued_hosts:
                        continue
                    self._queued_hosts.add(host)
                self._queued.add(ip)
            queue.put_nowait((ip, depth + 1, device.id))
            await self._emit({"type": "queued", "target": ip, "hostname": hostname, "depth": depth + 1})


async def discover(settings: Settings, collector: DeviceCollector | None = None,
                   progress: ProgressCallback | None = None) -> Topology:
    return await DiscoveryEngine(settings, collector=collector, progress=progress).run()
