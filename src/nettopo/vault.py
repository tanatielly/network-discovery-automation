"""Cofre local de credenciais.

Backends:

- ``keyring``: cofre do sistema operacional (Gerenciador de Credenciais do Windows, Keychain do macOS,
  Secret Service no Linux). Padrão quando disponível.
- ``arquivo``: ``vault.enc`` cifrado com Fernet (AES-128-CBC + HMAC-SHA256) e chave derivada por scrypt
  da senha em ``NETTOPO_VAULT_PASSWORD``. Para servidores e CI sem cofre do sistema.

O índice (``vault_index.json``) guarda só metadados: nome, tipo, usuário e data. Senhas, communities,
chaves SNMPv3 e tokens nunca são gravados em texto.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from nettopo.config import Credential, Settings
from nettopo.models import utcnow

SERVICE = "nettopo"
SECRET_FIELDS = ("password", "enable_secret", "community", "auth_key", "priv_key", "token")


class VaultError(Exception):
    pass


def _keyring_usable() -> bool:
    try:
        import keyring
        from keyring.backends import fail
    except ImportError:
        return False
    kr = keyring.get_keyring()
    return not isinstance(kr, fail.Keyring) and getattr(kr, "priority", 0) >= 1


def credential_payload(cred: Credential) -> dict[str, Any]:
    data = cred.model_dump(mode="python", exclude={"ref"})
    for k in SECRET_FIELDS:
        v = data.get(k)
        data[k] = v.get_secret_value() if isinstance(v, SecretStr) else v
    return {k: v for k, v in data.items() if v not in (None, "")}


class Vault:
    def __init__(self, data_dir: Path | str | None = None, backend: str | None = None, password: str | None = None):
        self.data_dir = Path(data_dir or os.environ.get("NETTOPO_DATA", "nettopo_data"))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.data_dir / "vault_index.json"
        self.file_path = self.data_dir / "vault.enc"
        password = password or os.environ.get("NETTOPO_VAULT_PASSWORD")
        backend = backend or os.environ.get("NETTOPO_VAULT_BACKEND", "auto")
        if backend == "auto":
            backend = "keyring" if _keyring_usable() else "arquivo"
        if backend not in ("keyring", "arquivo"):
            raise VaultError(f"backend de cofre desconhecido: {backend}")
        self.backend = backend
        self._password = password
        if backend == "arquivo" and not password:
            raise VaultError("cofre em arquivo exige a senha em NETTOPO_VAULT_PASSWORD")

    # ----------------------------------------------------------------- índice
    def _index(self) -> dict[str, dict[str, Any]]:
        if not self.index_path.exists():
            return {}
        return json.loads(self.index_path.read_text(encoding="utf-8"))

    def _save_index(self, idx: dict[str, dict[str, Any]]) -> None:
        self.index_path.write_text(json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8")

    # ----------------------------------------------------------------- arquivo cifrado
    def _fernet(self, salt: bytes) -> Any:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

        key = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive((self._password or "").encode())
        return Fernet(base64.urlsafe_b64encode(key))

    def _load_file(self) -> dict[str, Any]:
        if not self.file_path.exists():
            return {}
        from cryptography.fernet import InvalidToken

        blob = json.loads(self.file_path.read_text(encoding="utf-8"))
        salt = base64.b64decode(blob["salt"])
        try:
            plain = self._fernet(salt).decrypt(blob["data"].encode())
        except InvalidToken as exc:
            raise VaultError("senha do cofre incorreta (NETTOPO_VAULT_PASSWORD)") from exc
        return json.loads(plain)

    def _save_file(self, data: dict[str, Any]) -> None:
        if self.file_path.exists():
            salt = base64.b64decode(json.loads(self.file_path.read_text(encoding="utf-8"))["salt"])
        else:
            salt = os.urandom(16)
        token = self._fernet(salt).encrypt(json.dumps(data).encode()).decode()
        tmp = self.file_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"versao": 1, "salt": base64.b64encode(salt).decode(), "data": token}),
                       encoding="utf-8")
        tmp.replace(self.file_path)

    # ----------------------------------------------------------------- API
    def add(self, cred: Credential) -> None:
        if not cred.name:
            raise VaultError("a credencial precisa de um nome para ser guardada no cofre")
        payload = credential_payload(cred)
        if self.backend == "keyring":
            import keyring

            keyring.set_password(SERVICE, cred.name, json.dumps(payload))
        else:
            data = self._load_file()
            data[cred.name] = payload
            self._save_file(data)
        idx = self._index()
        idx[cred.name] = {"name": cred.name, "type": cred.type, "username": cred.username,
                          "version": cred.version if cred.type == "snmp" else None,
                          "saved_at": utcnow().isoformat(), "backend": self.backend}
        self._save_index(idx)

    def get(self, name: str) -> Credential:
        if self.backend == "keyring":
            import keyring

            raw = keyring.get_password(SERVICE, name)
            if raw is None:
                raise VaultError(f"credencial '{name}' não está no cofre")
            payload = json.loads(raw)
        else:
            payload = self._load_file().get(name)
            if payload is None:
                raise VaultError(f"credencial '{name}' não está no cofre")
        return Credential.model_validate(payload)

    def remove(self, name: str) -> bool:
        idx = self._index()
        found = name in idx
        if self.backend == "keyring":
            import keyring
            from keyring.errors import PasswordDeleteError

            try:
                keyring.delete_password(SERVICE, name)
                found = True
            except PasswordDeleteError:
                pass
        else:
            data = self._load_file()
            if name in data:
                del data[name]
                self._save_file(data)
                found = True
        idx.pop(name, None)
        self._save_index(idx)
        return found

    def list(self) -> list[dict[str, Any]]:
        return sorted(self._index().values(), key=lambda x: x["name"])

    def all(self) -> list[Credential]:
        return [self.get(item["name"]) for item in self.list()]


def resolve_credentials(settings: Settings, vault: Vault | None) -> Settings:
    """Substitui referências ``{ref: nome}`` pelo conteúdo do cofre e, com ``usar_cofre``, inclui todas."""
    creds: list[Credential] = []
    names: set[str] = set()
    for c in settings.credentials:
        if c.ref:
            if vault is None:
                raise VaultError(f"a configuração referencia '{c.ref}', mas o cofre não está disponível")
            resolved = vault.get(c.ref)
            creds.append(resolved)
            names.add(resolved.name)
        else:
            creds.append(c)
    if settings.usar_cofre and vault is not None:
        for c in vault.all():
            if c.name not in names:
                creds.append(c)
    return settings.model_copy(update={"credentials": creds})
