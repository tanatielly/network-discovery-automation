"""Memória persistente: revalidação, reaproveitamento, inativos e histórico."""

import asyncio

from nettopo.collectors.simulated import SimulatedCollector, demo_settings
from nettopo.inventory.revalidate import discover_with_memory
from nettopo.inventory.store import InventoryStore


def _run(sim, store, **kw):
    return asyncio.run(discover_with_memory(demo_settings(sim), store=store, collector=sim, **kw))


def _sig(topo):
    return sorted((lk.kind, lk.source, lk.source_interface, lk.target, lk.target_interface) for lk in topo.links)


def test_second_run_reuses_and_confirms(tmp_path):
    store = InventoryStore(tmp_path)
    sim = SimulatedCollector()
    first = _run(sim, store)
    assert first.meta.stats["memoria"]["conhecidos"] == 0
    assert {e["kind"] for e in first.meta.stats["memoria"]["eventos"]} == {"novo"}
    n_collected = sum(1 for d in first.devices.values() if not d.stub)

    sim2 = SimulatedCollector()
    second = _run(sim2, store)
    mem = second.meta.stats["memoria"]
    assert mem["conhecidos"] == n_collected
    assert mem["reaproveitados"] == n_collected and mem["recoletados"] == 0
    assert sim2.full_collections == 0 and sim2.light_checks == n_collected
    assert mem["eventos"] == []
    assert _sig(second) == _sig(first)
    assert all(d.extra.get("verificado_em") for d in second.devices.values() if not d.stub)


def test_device_down_then_back(tmp_path):
    store = InventoryStore(tmp_path)
    _run(SimulatedCollector(), store)

    sim = SimulatedCollector()
    sim.reachable["SRV-01"] = False
    down = _run(sim, store)
    srv = next(d for d in down.devices.values() if d.hostname == "SRV-01")
    assert srv.stub and srv.extra["status"] == "inacessivel"
    assert "sem resposta" in srv.extra["motivo"]
    assert {"device": "srv-01", "kind": "inacessivel"} in down.meta.stats["memoria"]["eventos"]
    assert store.get("srv-01").status == "inacessivel"

    back = _run(SimulatedCollector(), store)
    assert {"device": "srv-01", "kind": "voltou"} in back.meta.stats["memoria"]["eventos"]
    assert store.get("srv-01").status == "ativo"
    kinds = [e.kind for e in store.events()]
    assert "inacessivel" in kinds and "voltou" in kinds


def test_neighbor_change_triggers_full_collection(tmp_path):
    store = InventoryStore(tmp_path)
    _run(SimulatedCollector(), store)
    sim = SimulatedCollector()
    acc = sim.devices["ACC-SW-04"]
    acc.neighbors = [n for n in acc.neighbors if n.remote_hostname != "SRV-01"]  # cabo retirado
    sim.devices["SRV-01"].neighbors = [n for n in sim.devices["SRV-01"].neighbors if n.remote_hostname != "ACC-SW-04"]
    topo = _run(sim, store)
    mem = topo.meta.stats["memoria"]
    assert mem["recoletados"] >= 2 and sim.full_collections == mem["recoletados"]
    kinds = {e["kind"] for e in mem["eventos"]}
    assert "alterado" in kinds and "link_removido" in kinds


def test_verify_only_does_not_follow_new_neighbors(tmp_path):
    store = InventoryStore(tmp_path)
    sim = SimulatedCollector()
    sim.reachable["SRV-01"] = False  # ainda não conhecido
    _run(sim, store)
    assert store.get("srv-01") is None
    topo = _run(SimulatedCollector(), store, verify_only=True)
    assert all(not d.extra.get("reached_via") or d.extra.get("reutilizado") for d in topo.devices.values()
               if not d.stub)
    assert store.get("srv-01") is None  # verificação não descobre equipamentos novos


def test_full_mode_recollects_everything(tmp_path):
    store = InventoryStore(tmp_path)
    _run(SimulatedCollector(), store)
    sim = SimulatedCollector()
    topo = _run(sim, store, full=True)
    assert topo.meta.stats["memoria"]["reaproveitados"] == 0 and sim.light_checks == 0


def test_unreachable_neighbors_are_not_retried_every_run(tmp_path):
    store = InventoryStore(tmp_path)
    sim = SimulatedCollector()
    calls: list[str] = []
    orig = sim.collect

    async def spy(target):
        calls.append(target)
        return await orig(target)

    sim.collect = spy
    _run(sim, store)
    assert {"10.0.3.21", "10.0.3.22"} <= set(calls)  # APs sem acesso: tentados na primeira vez
    calls.clear()
    second = _run(sim, store)
    assert "10.0.3.21" not in calls and "10.0.3.22" not in calls  # lembrados: sem novo timeout
    assert "última tentativa" in second.meta.failed_targets["10.0.3.21"]
    calls.clear()
    _run(sim, store, full=True)
    assert "10.0.3.21" in calls  # --completo tenta de novo


def test_sweep_respects_scope_and_probes_ports_and_snmp_in_parallel(monkeypatch):
    import time
    from types import SimpleNamespace

    from nettopo.config import Settings
    from nettopo.discovery import sweep as sw

    async def fake_scan(ip, ports, timeout=2.0):
        await asyncio.sleep(0.2)
        return {22} if ip == "10.9.0.2" else set()

    class FakeSnmp:
        async def probe(self, ip, creds, errors=None):
            await asyncio.sleep(0.2)
            return (creds[0], {"name": b"sw-so-snmp"}) if ip == "10.9.0.3" else None

    monkeypatch.setattr(sw, "scan_ports", fake_scan)
    settings = Settings.model_validate({
        "seeds": ["10.9.0.1"], "varredura": ["10.9.0.0/29"],
        "credentials": [{"type": "snmp", "name": "s", "version": "2c", "community": "public"}],
        "scope": {"include": ["10.9.0.0/24"], "exclude": ["10.9.0.6/32"]}})
    assert sw.sweep_hosts(settings) == [f"10.9.0.{i}" for i in range(1, 6)]
    t0 = time.perf_counter()
    found = asyncio.run(sw.sweep(settings, SimpleNamespace(snmp=FakeSnmp()), known={"r1": ["10.9.0.1"]}))
    assert time.perf_counter() - t0 < 0.35  # um IP vazio custa max(portas, SNMP), não a soma
    assert [(t.candidates, t.hostname) for t in found] == [
        ([("10.9.0.2", "varredura")], None), ([("10.9.0.3", "varredura")], "sw-so-snmp")]
