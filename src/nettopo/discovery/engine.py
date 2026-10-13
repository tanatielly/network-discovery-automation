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
from nettopo.discovery.scope import Target, next_targets, resolve_hostname
from nettopo.models import Device, DiscoveryMeta, Topology, utcnow
from nettopo.topology.builder import build_topology
from nettopo.utils import is_default_hostname, is_usable_ip, normalize_mac, short_hostname
from nettopo.vendors.registry import VendorRegistry, default_registry

log = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None] | None]

ORIGIN_PT = {"memoria": "memória", "anunciado": "IP anunciado", "dns": "DNS", "arp": "ARP",
             "semente": "semente", "varredura": "varredura"}


class _Hints:
    """Fontes extras de IP: memória (execuções anteriores/varredura) e ARP dos equipamentos coletados."""

    def __init__(self, engine: DiscoveryEngine):
        self.engine = engine

    def ips_for_host(self, hostname: str | None) -> list[str]:
        host = short_hostname(hostname)
        return list(self.engine.known_hosts.get(host or "", [])) if host else []

    def ips_for_mac(self, mac: str | None) -> list[str]:
        m = normalize_mac(mac)
        if not m:
            return []
        out: list[str] = []
        for d in sorted(self.engine.index.devices.values(), key=lambda x: x.id):
            for a in d.arp:
                if normalize_mac(a.mac) == m and a.ip not in out:
                    out.append(a.ip)
        return out


class DiscoveryEngine:
    def __init__(self, settings: Settings, collector: DeviceCollector | None = None,
                 registry: VendorRegistry | None = None, progress: ProgressCallback | None = None,
                 known_hosts: dict[str, list[str]] | None = None):
        self.settings = settings
        self.registry = registry or default_registry()
        if collector is None:
            from nettopo.collectors.orchestrator import Orchestrator

            collector = Orchestrator(settings, self.registry)
        self.collector = collector
        self.progress = progress
        self.index = IdentityIndex()
        self.failed: dict[str, str] = {}
        # hostname curto -> IPs de gerência conhecidos (memória persistente e varredura)
        self.known_hosts: dict[str, list[str]] = dict(known_hosts or {})
        self._queued: set[str] = set()
        self._queued_hosts: set[str] = set()  # hostnames anunciados já enfileirados
        self._dead: dict[str, str] = {}  # cache negativo: IP -> motivo da falha nesta execução
        self._lock = asyncio.Lock()
        self._processed = 0
        self._hints = _Hints(self)
        self._dns_cache: dict[str, str | None] = {}

    async def _late_candidates(self, target: Target) -> list[tuple[str, str]]:
        """Candidatos resolvidos só quando os imediatos falham: memória atualizada, DNS e ARP."""
        out: list[tuple[str, str]] = []
        host = short_hostname(target.hostname)
        for ip in self._hints.ips_for_host(host):
            out.append((ip, "memoria"))
        if target.hostname and self.settings.dns_resolve and host:
            if host not in self._dns_cache:
                self._dns_cache[host] = await resolve_hostname(target.hostname)
            if self._dns_cache[host]:
                out.append((self._dns_cache[host], "dns"))
        for mac in target.macs:
            for ip in self._hints.ips_for_mac(mac):
                out.append((ip, "arp"))
        tried = {ip for ip, _ in target.candidates}
        seen: set[str] = set()
        result = []
        for ip, origin in out:
            if (ip in tried or ip in seen or not is_usable_ip(ip) or not self.settings.scope.allows_ip(ip)):
                continue
            seen.add(ip)
            result.append((ip, origin))
        return result

    async def _emit(self, event: dict[str, Any]) -> None:
        if self.progress is None:
            return
        try:
            r = self.progress(event)
            if inspect.isawaitable(r):
                await r
        except Exception:  # callback nunca derruba a descoberta
            log.debug("progress callback falhou", exc_info=True)

    async def seed_targets(self) -> list[Target]:
        targets: list[Target] = []
        for seed in self.settings.seeds:
            ip = await resolve_hostname(seed)
            if not ip:
                self.failed[seed] = "não foi possível resolver o nome"
                continue
            if ip in self._queued:
                continue
            self._queued.add(ip)
            targets.append(Target(candidates=[(ip, "semente")]))
        return targets

    async def run(self, extra_targets: list[Target] | None = None,
                  preloaded: list[Device] | None = None) -> Topology:
        """Executa a descoberta.

        ``preloaded``: equipamentos já confirmados (revalidação) que entram no grafo sem nova coleta;
        seus vizinhos ainda alimentam a fila. ``extra_targets``: alvos adicionais (varredura, memória).
        """
        meta = DiscoveryMeta(name=self.settings.name, seeds=list(self.settings.seeds), tool_version=__version__,
                             max_depth=self.settings.max_depth, settings=self.settings.sanitized())
        queue: asyncio.Queue[Target] = asyncio.Queue()
        for dev in preloaded or []:
            async with self._lock:
                self.index.add(dev)
        targets = await self.seed_targets()
        for t in extra_targets or []:
            ips = [ip for ip, _ in t.candidates if ip not in self._queued]
            if ips:
                self._queued.update(ips)
                targets.append(t)
        for t in targets:
            queue.put_nowait(t)
        await self._emit({"type": "started", "seeds": [t.candidates[0][0] for t in targets]})
        for dev in preloaded or []:
            await self._enqueue_neighbors(queue, dev, dev.depth)

        workers = [asyncio.create_task(self._worker(queue)) for _ in range(max(1, self.settings.concurrency))]
        try:
            await queue.join()
        finally:
            for w in workers:
                w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            await self.collector.close()

        meta.failed_targets = dict(sorted(self.failed.items()))
        meta.finished_at = utcnow()
        topo = build_topology(self.index.devices, self.settings, meta, self.registry)
        await self._emit({"type": "finished", "stats": topo.meta.stats})
        return topo

    async def _worker(self, queue: asyncio.Queue[Target]) -> None:
        while True:
            target = await queue.get()
            try:
                await self._process(queue, target)
            except Exception as exc:
                log.exception("erro processando %s", target.label)
                self.failed[target.candidates[0][0]] = f"erro interno: {exc}"
            finally:
                queue.task_done()

    async def _process(self, queue: asyncio.Queue[Target], target: Target) -> None:
        if len(self.index.devices) >= self.settings.max_devices:
            self.failed[target.candidates[0][0]] = "limite max_devices atingido"
            return
        if self.index.lookup_hostname(target.hostname):
            return  # já coletado por outro caminho
        attempts: list[str] = []
        device: Device | None = None
        used_ip = None
        candidates = list(target.candidates)
        late_done = False
        i = 0
        while True:
            if i >= len(candidates):
                if late_done:
                    break
                late_done = True
                candidates += await self._late_candidates(target)
                target.candidates = candidates
                if i >= len(candidates):
                    break
            ip, origin = candidates[i]
            i += 1
            if self.index.lookup_ip(ip):
                return  # IP pertence a um equipamento já coletado
            if ip in self._dead:
                attempts.append(f"{ORIGIN_PT.get(origin, origin)} {ip}: {self._dead[ip]}")
                continue
            await self._emit({"type": "device_started", "target": ip, "origin": origin, "hostname": target.hostname,
                              "depth": target.depth, "parent": target.parent})
            result = await self.collector.collect(ip)
            self._processed += 1
            if result.reachable:
                device, used_ip = result, ip
                break
            reason = "; ".join(result.errors) or "sem resposta"
            self._dead[ip] = reason
            attempts.append(f"{ORIGIN_PT.get(origin, origin)} {ip}: {reason}")
        if device is None:
            key = target.candidates[0][0] if target.candidates else (target.hostname or "?")
            # O motivo fica associado a todos os IPs tentados (o builder procura pelo IP anunciado)
            summary = " | ".join(attempts) or "nenhum IP candidato"
            if target.hostname and {o for _, o in target.candidates} <= {"anunciado"}:
                summary += " | nenhum outro IP de gerência conhecido (configure DNS, memória/inventário ou varredura)"
            if not attempts:  # nenhum IP para tentar: o motivo vai no nó (builder), não na lista de falhas
                return
            for ip, _ in target.candidates:
                self.failed[ip] = summary
            await self._emit({"type": "device_failed", "target": key, "hostname": target.hostname,
                              "reason": summary[:400], "processed": self._processed})
            return
        device.depth = target.depth
        device.discovered_from = target.parent
        device.extra["reached_via"] = used_ip
        async with self._lock:
            device = self.index.add(device)
        await self._emit({"type": "device_done", "target": used_ip, "id": device.id, "hostname": device.hostname,
                          "vendor": device.vendor, "model": device.model, "via": device.collected_via,
                          "neighbors": len(device.neighbors), "processed": self._processed,
                          "known": len(self.index.devices)})
        await self._enqueue_neighbors(queue, device, target.depth)

    async def _enqueue_neighbors(self, queue: asyncio.Queue[Target], device: Device, depth: int) -> None:
        if depth >= self.settings.max_depth:
            return
        for t in await next_targets(device, self.settings, self._hints):
            host = short_hostname(t.hostname)
            async with self._lock:
                ips = [ip for ip, _ in t.candidates]
                if any(ip in self._queued or self.index.lookup_ip(ip) for ip in ips):
                    continue
                if self.index.lookup_hostname(t.hostname):
                    continue
                if host and not is_default_hostname(host):
                    if host in self._queued_hosts:
                        continue
                    self._queued_hosts.add(host)
                self._queued.update(ips)
            t.depth, t.parent = depth + 1, device.id
            queue.put_nowait(t)
            await self._emit({"type": "queued", "target": t.candidates[0][0] if t.candidates else t.hostname,
                              "hostname": t.hostname,
                              "candidates": [f"{ORIGIN_PT.get(o, o)}:{ip}" for ip, o in t.candidates],
                              "depth": depth + 1})


async def discover(settings: Settings, collector: DeviceCollector | None = None,
                   progress: ProgressCallback | None = None,
                   known_hosts: dict[str, list[str]] | None = None) -> Topology:
    return await DiscoveryEngine(settings, collector=collector, progress=progress,
                                 known_hosts=known_hosts).run()
