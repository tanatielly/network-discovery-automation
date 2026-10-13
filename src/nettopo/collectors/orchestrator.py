"""Orquestra a coleta de um equipamento: fingerprint -> métodos por preferência -> merge."""

from __future__ import annotations

import logging
from typing import Any

from nettopo import ratelimit
from nettopo.collectors.base import MethodResult
from nettopo.collectors.netconf import NetconfCollector
from nettopo.collectors.rest import RestCollector
from nettopo.collectors.snmp import SnmpCollector, covered_groups, to_text
from nettopo.collectors.ssh import SSHCollector
from nettopo.config import Credential, Settings
from nettopo.discovery.fingerprint import PORTS, Fingerprint, read_ssh_banner, scan_ports
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
        # credencial que funcionou por (método, perfil): numa rede multi-vendor a última que funcionou no
        # geral pode ser de outro fabricante; esta vai primeiro e evita falhas de login (bloqueio no AAA)
        self._good: dict[tuple[str, str], Credential] = {}
        self.throttles = ratelimit.ThrottleRegistry(settings.carga)

    def _promote(self, kind: str, cred: Credential | None, profile_id: str | None = None) -> None:
        lst = self._creds.get(kind, [])
        if cred is not None and cred in lst and lst[0] is not cred:
            lst.remove(cred)
            lst.insert(0, cred)
        if cred is not None and profile_id:
            self._good[(kind, profile_id)] = cred

    def _ordered(self, kind: str, profile_id: str | None, first: Credential | None = None) -> list[Credential]:
        creds = list(self._creds.get(kind, []))
        for c in reversed([c for c in (first, self._good.get((kind, profile_id or ""))) if c is not None]):
            if c in creds:
                creds.remove(c)
                creds.insert(0, c)
        return creds

    async def fingerprint(self, target: str) -> Fingerprint:
        fp = Fingerprint(target=target)
        fp.open_ports = await scan_ports(target, [PORTS["ssh"], PORTS["netconf"], PORTS["https"], PORTS["http"]],
                                         timeout=min(3, self.settings.timeout))
        if self._creds["snmp"] and "snmp" in self.settings.methods:
            probed = await self.snmp.probe(target, list(self._creds["snmp"]), errors=fp.errors)
            if probed:
                fp.snmp_cred, fp.system = probed
                self._promote("snmp", fp.snmp_cred)
                fp.profile = self.registry.match_snmp(to_text(fp.system.get("object_id")),
                                                      to_text(fp.system.get("descr")))
                if fp.profile:
                    fp.method = "snmp"
        if fp.profile is None and PORTS["ssh"] in fp.open_ports and "ssh" in self.settings.methods:
            fp.ssh_banner = await read_ssh_banner(target, PORTS["ssh"], timeout=min(3, self.settings.timeout))
            by_banner = self.registry.match_banner(fp.ssh_banner)
            if len(by_banner) == 1:
                fp.profile, fp.method = by_banner[0], "ssh-banner"
            elif self._creds["ssh"]:
                profile, cred, errors, method = await self.ssh.identify(target, list(self._creds["ssh"]),
                                                                        by_banner or None)
                fp.errors.extend(errors)
                if cred is not None:
                    fp.ssh_cred = cred
                    self._promote("ssh", cred)
                if profile is not None:
                    fp.profile, fp.method = profile, method
                elif cred is not None:  # autenticou mas não reconheceu: último recurso, autodetect do Netmiko
                    detected = await self.ssh.autodetect(target, [cred])
                    if detected:
                        fp.profile = self.registry.by_netmiko(detected[0])
                        fp.method = "ssh-autodetect" if fp.profile else None
        if fp.profile is None and not fp.open_ports and fp.system is None:
            fp.errors.append("sem resposta: portas 22/80/443/830 fechadas e SNMP sem resposta")
        return fp

    async def collect(self, target: str) -> Device:
        throttle = self.throttles.get(target)
        token = ratelimit.use(throttle)
        try:
            async with throttle.session():
                device = await self._collect(target, throttle)
        finally:
            ratelimit.reset(token)
        device.extra["carga"] = throttle.stats()
        return device

    async def _collect(self, target: str, throttle: ratelimit.DeviceThrottle) -> Device:
        fp = await self.fingerprint(target)
        profile = fp.profile
        if profile is not None:  # ajustes de carga por fabricante passam a valer daqui em diante
            self.throttles.get(target, profile.id, to_text((fp.system or {}).get("name")))
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
            creds = self._ordered(method, profile.id if profile else None,
                                  fp.ssh_cred if method == "ssh" else None)
            try:
                res = await collector.collect(target, profile, creds)
            except Exception as exc:  # proteção contra bugs de drivers
                log.exception("coletor %s falhou em %s", method, target)
                res = MethodResult(method=method, errors=[f"{method}: {type(exc).__name__}: {exc}"])
            errors.extend(res.errors if not res.ok else [])
            if res.ok:
                self._promote(method, res.credential, profile.id if profile else None)
                primary = res
                break

        snmp_res: MethodResult | None = None
        if fp.snmp_cred and (primary is None or self.settings.snmp_complement):
            try:
                skip = covered_groups(primary.device) if primary and primary.device else None
                snmp_res = await self.snmp.collect(target, profile, [fp.snmp_cred], system=fp.system, skip=skip)
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
            msgs: list[str] = []
            for e in fp.errors + errors:
                if e not in msgs:
                    msgs.append(e)
            if not msgs:
                msgs.append("nenhum método funcionou (sem credencial do tipo certo para este equipamento)")
            reason = "; ".join(msgs)
            return Device(mgmt_ip=target, reachable=False, errors=[reason],
                          profile=profile.id if profile else None, vendor=profile.vendor if profile else None)
        device.mgmt_ip = target
        if profile:
            device.vendor = device.vendor or profile.vendor
            device.os = device.os or profile.os
            device.profile = device.profile or profile.id
            device.os_version = device.os_version or self.registry.extract_version(profile, device.sys_description)
        device.extra["fingerprint"] = fp.method
        device.extra["acesso"] = {
            "metodo": primary.method if primary else "snmp",
            "credencial": primary.credential.display if primary and primary.credential else None,
            "snmp": fp.snmp_cred.display if fp.snmp_cred else None,
            "perfil": profile.id if profile else None,
        }
        device.errors.extend(e for e in errors if e not in device.errors)
        return device

    def _find_cred(self, kind: str, name: str | None) -> Credential | None:
        for c in self._creds.get(kind, []):
            if c.display == name:
                return c
        return None

    async def light_check(self, target: str, access: dict[str, Any]) -> Device | None:
        """Checagem leve com o acesso que funcionou da última vez: identidade + vizinhança.

        Devolve ``None`` se o acesso salvo não serve mais (credencial removida, método sem resposta).
        """
        throttle = self.throttles.get(target, access.get("perfil"))
        token = ratelimit.use(throttle)
        try:
            async with throttle.session():
                device = await self._light(target, access)
        finally:
            ratelimit.reset(token)
        if device is not None:
            device.extra["carga"] = throttle.stats()
        return device

    async def _light(self, target: str, access: dict[str, Any]) -> Device | None:
        profile = self.registry.get(access.get("perfil"))
        method = access.get("metodo")
        res: MethodResult | None = None
        if method in ("rest", "netconf", "ssh") and profile is not None:
            cred = self._find_cred(method, access.get("credencial"))
            if cred is not None:
                collector: Any = {"rest": self.rest, "netconf": self.netconf, "ssh": self.ssh}[method]
                try:
                    res = await collector.collect(target, profile, [cred], light=True)
                except Exception:
                    log.debug("checagem leve %s falhou em %s", method, target, exc_info=True)
                if res is not None and res.ok:
                    self._promote(method, cred, profile.id)  # recoleta, se houver, já começa por ela
        if (res is None or not res.ok) and access.get("snmp"):
            cred = self._find_cred("snmp", access.get("snmp"))
            if cred is not None:
                try:
                    res = await self.snmp.collect(target, profile, [cred], light=True)
                except Exception:
                    log.debug("checagem leve snmp falhou em %s", target, exc_info=True)
        if res is None or not res.ok or res.device is None:
            return None
        res.device.mgmt_ip = target
        return res.device

    async def close(self) -> None:
        self.snmp.close()
