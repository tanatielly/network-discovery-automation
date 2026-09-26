"""Registro de perfis de vendor (carregados de ``profiles/*.yaml``)."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

PROFILES_DIR = Path(__file__).parent / "profiles"

# Tipos de coleta suportados via CLI
COMMAND_KINDS = (
    "facts", "hostname", "interfaces", "ip_interfaces", "lldp", "cdp", "other_l2",
    "arp", "routes", "vlans", "mac_table", "ospf", "bgp",
)


class VendorProfile(BaseModel):
    id: str
    vendor: str
    os: str
    category: str = "network"  # router | switch | firewall | wireless | server | network
    priority: int = 10  # maior = testado antes no match por SNMP
    netmiko: str | None = None
    textfsm: str | None = None  # plataforma do ntc-templates (padrão = netmiko)
    sys_object_id: list[str] = Field(default_factory=list)
    sys_descr: list[str] = Field(default_factory=list)  # regex
    version_regex: str | None = None
    rest: str | None = None  # driver REST: eapi | nxapi | restconf_iosxe | mikrotik | fortios
    netconf: str | None = None  # device handler do ncclient: default | junos | huawei | nexus | iosxr
    commands: dict[str, list[str]] = Field(default_factory=dict)
    parsers: dict[str, str] = Field(default_factory=dict)  # tipo -> parser custom
    notes: str | None = None

    @property
    def textfsm_platform(self) -> str | None:
        return self.textfsm or self.netmiko

    def commands_for(self, kind: str) -> list[str]:
        cmds = self.commands.get(kind) or []
        return [cmds] if isinstance(cmds, str) else list(cmds)

    @property
    def methods(self) -> list[str]:
        m = ["snmp"]
        if self.netmiko:
            m.append("ssh")
        if self.netconf:
            m.append("netconf")
        if self.rest:
            m.append("rest")
        return m


class VendorRegistry:
    def __init__(self, profiles: list[VendorProfile]):
        self._profiles = {p.id: p for p in profiles}
        self._ordered = sorted(profiles, key=lambda p: -p.priority)

    @classmethod
    def load(cls, directory: Path = PROFILES_DIR) -> VendorRegistry:
        profiles: list[VendorProfile] = []
        for f in sorted(directory.glob("*.yaml")):
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            for item in data.get("profiles", []):
                cmds = item.get("commands") or {}
                item["commands"] = {k: ([v] if isinstance(v, str) else v) for k, v in cmds.items()}
                profiles.append(VendorProfile.model_validate(item))
        return cls(profiles)

    def all(self) -> list[VendorProfile]:
        return list(self._ordered)

    def get(self, profile_id: str | None) -> VendorProfile | None:
        return self._profiles.get(profile_id or "")

    def by_netmiko(self, device_type: str | None) -> VendorProfile | None:
        if not device_type:
            return None
        for p in self._ordered:
            if p.netmiko == device_type:
                return p
        return None

    def match_snmp(self, sys_object_id: str | None, sys_descr: str | None) -> VendorProfile | None:
        """Identifica o perfil a partir de sysObjectID/sysDescr (ou descrição LLDP/CDP)."""
        oid = (sys_object_id or "").lstrip(".")
        descr = sys_descr or ""

        def oid_score(p: VendorProfile) -> int:
            best = 0
            for prefix in p.sys_object_id:
                pr = prefix.lstrip(".")
                if oid and (oid == pr.rstrip(".") or oid.startswith(pr if pr.endswith(".") else pr + ".")):
                    best = max(best, len(pr))
            return best

        if descr:
            by_descr = [p for p in self._ordered if any(re.search(rx, descr, re.I) for rx in p.sys_descr)]
            if by_descr:
                return max(by_descr, key=lambda p: (oid_score(p), p.priority))
        if oid:
            scored = [(oid_score(p), p.priority, p) for p in self._ordered]
            scored = [s for s in scored if s[0] > 0]
            if scored:
                return max(scored, key=lambda s: (s[0], s[1]))[2]
        return None

    def extract_version(self, profile: VendorProfile | None, text: str | None) -> str | None:
        if not text:
            return None
        patterns = [profile.version_regex] if profile and profile.version_regex else []
        patterns += [r"Version[:\s]+([\w.\-()]+)", r"\bv(\d+\.\d+[\w.\-()]*)", r"\b(\d+\.\d+(?:\.\d+)+[\w\-()]*)"]
        for rx in patterns:
            m = re.search(rx, text, re.I)
            if m:
                return m.group(1).rstrip(",")
        return None


@lru_cache(maxsize=1)
def default_registry() -> VendorRegistry:
    return VendorRegistry.load()
