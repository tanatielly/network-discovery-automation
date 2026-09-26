"""Orquestra a coleta de um equipamento: fingerprint -> métodos por preferência -> merge."""

from __future__ import annotations

import logging
from typing import Any

from nettopo.collectors.base import MethodResult
from nettopo.collectors.netconf import NetconfCollector
from nettopo.collectors.rest import RestCollector
from nettopo.collectors.snmp import SnmpCollector, to_text
from nettopo.collectors.ssh import SSHCollector
from nettopo.config import Credential, Settings
from nettopo.discovery.fingerprint import PORTS, Fingerprint, scan_ports
from nettopo.discovery.identity import merge_device
from nettopo.models import Device
from nettopo.vendors.registry import VendorRegistry, default_registry

log = logging.getLogger(__name__)


class Orchestrator:
    """Implementa :class:`~nettopo.collectors.base.DeviceCollector` para rede real.

    Ordem padrão: REST -> NETCONF -> SSH (o primeiro que funcionar é o "primário"),
    e SNMP como complemento (ou como único método, se nada mais funcionar).
    """

    def __init__(self, settings: Settings, registry: VendorRegistry | None = None):
        self.settings = settings
        self.registry = registry or default_registry()
        self.snmp = SnmpCollector(settings, self.registry)
        self.ssh = SSHCollector(settings, self.registry)
        self.netconf = NetconfCollector(settings, self.registry)
        self.rest = RestCollector(settings, self.registry)
        # credenciais que funcionaram sobem para o início da lista (acelera redes grandes)
        self._creds: dict[str, list[Credential]] = {
            t: settings.creds(t) for t in ("ssh", "snmp", "netconf", "rest")
        }

    def _promote(self, kind: str, cred: Credential | None) -> None:
        lst = self._creds.get(kind, [])
        if cred is not None and cred in lst and lst[0] is not cred:
            lst.remove(cred)
            lst.insert(0, cred)

    async def fingerprint(self, target: str) -> Fingerprint:
        fp = Fingerprint(target=target)
        fp.open_ports = await scan_ports(target, [PORTS["ssh"], PORTS["netconf"], PORTS["https"], PORTS["http"]],
                                         timeout=min(3, self.settings.timeout))
        if self._creds["snmp"] and "snmp" in self.settings.methods:
            probed = await self.snmp.probe(target, list(self._creds["snmp"]))
            if probed:
                fp.snmp_cred, fp.system = probed
                self._promote("snmp", fp.snmp_cred)
                fp.profile = self.registry.match_snmp(to_text(fp.system.get("object_id")),
                                                      to_text(fp.system.get("descr")))
                if fp.profile:
                    fp.method = "snmp"
        if fp.profile is None and PORTS["ssh"] in fp.open_ports and self._creds["ssh"] \
                and "ssh" in self.settings.methods:
            detected = await self.ssh.autodetect(target, list(self._creds["ssh"]))
            if detected:
                device_type, fp.ssh_cred = detected
                fp.profile = self.registry.by_netmiko(device_type)
                if fp.profile:
                    fp.method = "ssh-autodetect"
        return fp

    async def collect(self, target: str) -> Device:
        fp = await self.fingerprint(target)
        profile = fp.profile
        errors: list[str] = []
        primary: MethodResult | None = None

        for method in self.settings.methods:
            if method == "snmp":
                continue
            if method == "rest" and (not profile or not profile.rest or not self._creds["rest"]):
                continue
            if method == "netconf" and (not self._creds["netconf"] or PORTS["netconf"] not in fp.open_ports
                                        or (profile and not profile.netconf)):
                continue
            if method == "ssh" and (not self._creds["ssh"] or PORTS["ssh"] not in fp.open_ports):
                continue
            collector: Any = {"rest": self.rest, "netconf": self.netconf, "ssh": self.ssh}[method]
            creds = list(self._creds[method])
            if method == "ssh" and fp.ssh_cred in creds:
                creds.remove(fp.ssh_cred)
                creds.insert(0, fp.ssh_cred)
            try:
                res = await collector.collect(target, profile, creds)
            except Exception as exc:  # proteção contra bugs de drivers
                log.exception("coletor %s falhou em %s", method, target)
                res = MethodResult(method=method, errors=[f"{method}: {type(exc).__name__}: {exc}"])
            errors.extend(res.errors if not res.ok else [])
            if res.ok:
                self._promote(method, res.credential)
                primary = res
                break

        snmp_res: MethodResult | None = None
        if fp.snmp_cred and (primary is None or self.settings.snmp_complement):
            try:
                snmp_res = await self.snmp.collect(target, profile, [fp.snmp_cred], system=fp.system)
            except Exception as exc:
                log.exception("SNMP falhou em %s", target)
                errors.append(f"snmp: {type(exc).__name__}: {exc}")

        device: Device | None = None
        if primary and primary.device:
            device = primary.device
            if snmp_res and snmp_res.device:
                merge_device(device, snmp_res.device)
        elif snmp_res and snmp_res.device:
            device = snmp_res.device
        if device is None:
            reason = "; ".join(errors) or ("sem resposta (portas fechadas / credenciais ausentes)"
                                           if not fp.open_ports and not fp.snmp_cred else "nenhum método funcionou")
            return Device(mgmt_ip=target, reachable=False, errors=[reason],
                          profile=profile.id if profile else None, vendor=profile.vendor if profile else None)
        device.mgmt_ip = target
        if profile:
            device.vendor = device.vendor or profile.vendor
            device.os = device.os or profile.os
            device.profile = device.profile or profile.id
            device.os_version = device.os_version or self.registry.extract_version(profile, device.sys_description)
        device.extra["fingerprint"] = fp.method
        device.errors.extend(e for e in errors if e not in device.errors)
        return device

    async def close(self) -> None:
        self.snmp.close()
