"""Coletor SSH/CLI baseado em Netmiko (100+ plataformas) + parsers TextFSM/genéricos."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from nettopo.collectors.base import MethodResult
from nettopo.config import Credential, Settings
from nettopo.models import Device
from nettopo.vendors.parsers import parse_output
from nettopo.vendors.parsers.normalize import apply_rows
from nettopo.vendors.registry import VendorProfile, VendorRegistry

log = logging.getLogger(__name__)

_PROMPT_CLEAN = [
    (re.compile(r"\(.*?\)"), ""),  # (config), (root) VDOM FortiGate
    (re.compile(r"^[AB*]:"), ""),  # Nokia SR OS "A:router#"
    (re.compile(r"^.*@"), ""),  # Junos/Linux "user@host"
    (re.compile(r"[\[\]<>#$%>:~\s]+$"), ""),
    (re.compile(r"^[\[<\s]+"), ""),
]


def hostname_from_prompt(prompt: str) -> str | None:
    s = (prompt or "").strip().splitlines()[-1] if prompt else ""
    s = re.sub(r"^\[.*?@(.+?)\]\s*>?$", r"\1", s)  # MikroTik "[admin@R1] >"
    for rx, repl in _PROMPT_CLEAN:
        s = rx.sub(repl, s).strip()
    s = s.split()[0] if s.split() else s
    return s or None


def kinds_for(settings: Settings) -> list[str]:
    c = settings.collect
    kinds = ["facts", "hostname"]
    if c.interfaces:
        kinds += ["interfaces", "ip_interfaces"]
    kinds += ["lldp", "cdp", "other_l2"]
    if c.arp:
        kinds.append("arp")
    if c.routes:
        kinds.append("routes")
    if c.vlans:
        kinds.append("vlans")
    if c.mac_table:
        kinds.append("mac_table")
    if c.routing_neighbors:
        kinds += ["ospf", "bgp"]
    return kinds


def parse_cli_outputs(device: Device, profile: VendorProfile, outputs: dict[str, tuple[str, str]]) -> None:
    """Aplica saídas ``{kind: (command, output)}`` ao ``device`` (função pura, testável)."""
    for kind, (command, output) in outputs.items():
        rows, source = parse_output(kind, command, output, profile.textfsm_platform, profile.parsers.get(kind))
        count = apply_rows(device, kind, rows)
        log.debug("%s %s '%s' -> %d registros (%s)", device.mgmt_ip, kind, command, count, source)


_ERROR_MARKERS = re.compile(
    r"(% ?Invalid|% ?Unknown|Unrecognized command|syntax error|Error:|% ?Incomplete|invalid input|"
    r"Command not found|not supported|bad command)", re.I)


class SSHCollector:
    name = "ssh"

    def __init__(self, settings: Settings, registry: VendorRegistry):
        self.settings = settings
        self.registry = registry

    # ------------------------------------------------------------------ autodetecção
    async def autodetect(self, target: str, credentials: list[Credential]) -> tuple[str, Credential] | None:
        return await asyncio.to_thread(self._autodetect_sync, target, credentials)

    def _autodetect_sync(self, target: str, credentials: list[Credential]) -> tuple[str, Credential] | None:
        try:
            from netmiko import SSHDetect
        except ImportError:  # pragma: no cover
            return None
        for cred in credentials:
            try:
                det = SSHDetect(device_type="autodetect", host=target, username=cred.username,
                                password=cred.secret("password"), port=cred.port or 22,
                                timeout=self.settings.timeout, conn_timeout=self.settings.timeout,
                                auth_timeout=self.settings.timeout, banner_timeout=self.settings.timeout)
                best = det.autodetect()
                det.connection.disconnect()
                if best:
                    return best, cred
            except Exception as exc:
                log.debug("autodetect %s via %s: %s", target, cred.display, exc)
                if _is_unreachable(exc):
                    return None
        return None

    # ------------------------------------------------------------------ coleta
    async def collect(self, target: str, profile: VendorProfile | None,
                      credentials: list[Credential]) -> MethodResult:
        res = MethodResult(method=self.name)
        if not profile or not profile.netmiko:
            res.errors.append("ssh: perfil sem driver Netmiko")
            return res
        if not credentials:
            res.errors.append("ssh: nenhuma credencial")
            return res
        return await asyncio.to_thread(self._collect_sync, target, profile, credentials, res)

    def _connect(self, target: str, profile: VendorProfile, credentials: list[Credential],
                 res: MethodResult) -> tuple[Any, Credential] | None:
        from netmiko import ConnectHandler

        for cred in credentials:
            params: dict[str, Any] = {
                "device_type": profile.netmiko,
                "host": target,
                "username": cred.username,
                "password": cred.secret("password"),
                "port": cred.port or 22,
                "timeout": self.settings.timeout,
                "conn_timeout": self.settings.timeout,
                "auth_timeout": self.settings.timeout,
                "banner_timeout": self.settings.timeout,
                "fast_cli": False,
            }
            if cred.enable_secret:
                params["secret"] = cred.secret("enable_secret")
            try:
                conn = ConnectHandler(**params)
            except Exception as exc:
                res.errors.append(f"ssh[{cred.display}]: {type(exc).__name__}: {str(exc).splitlines()[0][:160]}")
                if _is_unreachable(exc):
                    return None
                continue
            if cred.enable_secret:
                try:
                    conn.enable()
                except Exception as exc:
                    res.errors.append(f"ssh: enable falhou: {exc}")
            return conn, cred
        return None

    def _collect_sync(self, target: str, profile: VendorProfile, credentials: list[Credential],
                      res: MethodResult) -> MethodResult:
        connected = self._connect(target, profile, credentials, res)
        if not connected:
            return res
        conn, cred = connected
        dev = Device(mgmt_ip=target, vendor=profile.vendor, os=profile.os, profile=profile.id,
                     collected_via=["ssh"])
        outputs: dict[str, tuple[str, str]] = {}
        try:
            try:
                dev.hostname = hostname_from_prompt(conn.find_prompt())
            except Exception:
                pass
            for kind in kinds_for(self.settings):
                for cmd in profile.commands_for(kind):
                    try:
                        out = conn.send_command(cmd, read_timeout=max(30, self.settings.timeout * 4))
                    except Exception as exc:
                        res.errors.append(f"ssh: '{cmd}': {type(exc).__name__}")
                        continue
                    if not isinstance(out, str) or not out.strip() or _ERROR_MARKERS.search(out[:300]):
                        continue
                    outputs[kind] = (cmd, out)
                    break
        finally:
            try:
                conn.disconnect()
            except Exception:
                pass
        prompt_host = dev.hostname
        dev.hostname = None
        parse_cli_outputs(dev, profile, outputs)
        dev.hostname = dev.hostname or prompt_host
        dev.extra["raw_commands"] = sorted(c for c, _ in outputs.values())
        res.device = dev
        res.credential = cred
        return res


def _is_unreachable(exc: Exception) -> bool:
    name = type(exc).__name__
    msg = str(exc).lower()
    return (name in ("NetmikoTimeoutException", "TimeoutError", "ConnectionRefusedError", "NoValidConnectionsError")
            or "timed out" in msg or "unable to connect" in msg or "connection refused" in msg)
