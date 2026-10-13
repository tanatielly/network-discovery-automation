import asyncio
import threading
import time

from nettopo import ratelimit
from nettopo.ratelimit import DeviceThrottle, LoadProfile, LoadSettings, ThrottleRegistry


def test_presets_and_overrides():
    s = LoadSettings(perfil="equilibrado", overrides=[
        {"cidr": "10.9.0.0/16", "perfil": "conservador"},
        {"fabricante": "hp_procurve", "intervalo_min_ms": 800, "snmp_max_repetitions": 5},
    ])
    assert s.resolve("10.1.1.1")[1].intervalo_min_ms == 100
    name, p = s.resolve("10.9.3.3")
    assert name == "conservador" and p.intervalo_min_ms == 500 and p.snmp_walks_paralelos == 1
    name, p = s.resolve("10.1.1.1", "hp_procurve")
    assert p.intervalo_min_ms == 800 and p.snmp_max_repetitions == 5 and "ajuste" in name
    assert LoadSettings(perfil="conservador").concurrency == 4


def test_async_pacing_respects_min_interval():
    t = DeviceThrottle("10.0.0.1", "teste", LoadProfile(intervalo_min_ms=50))

    async def burst():
        await asyncio.gather(*(t.pace() for _ in range(6)))

    start = time.monotonic()
    asyncio.run(burst())
    assert time.monotonic() - start >= 0.24  # 5 intervalos de 50 ms
    assert t.min_gap >= 0.049 and t.requests == 6


def test_thread_pacing_shares_the_same_clock():
    t = DeviceThrottle("10.0.0.1", "teste", LoadProfile(intervalo_min_ms=40))
    stamps = []

    def worker():
        for _ in range(3):
            t.pace_sync()
            stamps.append(time.monotonic())

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    stamps.sort()
    gaps = [b - a for a, b in zip(stamps, stamps[1:], strict=False)]
    assert min(gaps) >= 0.035 and t.requests == 9


def test_one_session_per_device():
    reg = ThrottleRegistry(LoadSettings())
    t = reg.get("10.0.0.1")

    async def job():
        async with t.session():
            await asyncio.sleep(0.02)

    async def main():
        await asyncio.gather(*(job() for _ in range(5)))

    asyncio.run(main())
    assert t.max_active == 1


def test_auth_failure_cap_and_context():
    t = DeviceThrottle("10.0.0.1", "teste", LoadProfile(max_falhas_autenticacao=2))
    token = ratelimit.use(t)
    try:
        assert ratelimit.auth_allowed()
        ratelimit.auth_failed()
        ratelimit.auth_failed()
        assert not ratelimit.auth_allowed()
    finally:
        ratelimit.reset(token)
    assert ratelimit.auth_allowed()  # fora do contexto não há limite


def test_ssh_collector_stops_before_lockout(monkeypatch):
    """Com teto de 2 falhas, a terceira credencial nem é tentada."""
    from nettopo.collectors.base import MethodResult
    from nettopo.collectors.ssh import SSHCollector
    from nettopo.config import Settings
    from nettopo.vendors.registry import default_registry

    attempts = []

    class FakeAuthError(Exception):
        pass

    def fake_connect(**params):
        attempts.append(params["username"])
        raise FakeAuthError("Authentication to device failed.")

    import netmiko

    monkeypatch.setattr(netmiko, "ConnectHandler", fake_connect)
    s = Settings(credentials=[{"type": "ssh", "username": u, "password": "x"} for u in ("a", "b", "c")],
                 carga={"perfil": "conservador"})
    col = SSHCollector(s, default_registry())
    t = DeviceThrottle("10.0.0.1", "conservador", ratelimit.PRESETS["conservador"].model_copy(
        update={"intervalo_min_ms": 0}))
    token = ratelimit.use(t)
    try:
        res = MethodResult(method="ssh")
        col._connect("10.0.0.1", default_registry().get("cisco_ios"), s.creds("ssh"), res)
    finally:
        ratelimit.reset(token)
    assert attempts == ["a", "b"]
    assert any("limite de falhas" in e for e in res.errors)
