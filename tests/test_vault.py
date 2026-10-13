import uuid

import pytest

from nettopo.config import Credential, Settings
from nettopo.vault import Vault, VaultError, _keyring_usable, resolve_credentials

SECRETS = ("S3nh@-SSH-xyz", "comunidade-secreta-123", "authkey-987654")


def _creds():
    return [
        Credential(name="ssh-noc", type="ssh", username="noc", password=SECRETS[0]),
        Credential(name="snmp-v2", type="snmp", version="2c", community=SECRETS[1]),
        Credential(name="snmp-v3", type="snmp", version="3", username="mon", auth_key=SECRETS[2],
                   priv_key="privkey-111"),
    ]


def test_file_vault_roundtrip_without_plaintext(tmp_path):
    v = Vault(tmp_path, backend="arquivo", password="mestra-forte")
    for c in _creds():
        v.add(c)
    got = {c.name: c for c in Vault(tmp_path, backend="arquivo", password="mestra-forte").all()}
    assert got["ssh-noc"].secret("password") == SECRETS[0]
    assert got["snmp-v2"].secret("community") == SECRETS[1]
    assert got["snmp-v3"].secret("auth_key") == SECRETS[2] and got["snmp-v3"].version == "3"
    for f in tmp_path.iterdir():
        raw = f.read_bytes()
        assert not any(s.encode() in raw for s in SECRETS), f.name
    assert [i["name"] for i in v.list()] == ["snmp-v2", "snmp-v3", "ssh-noc"]


def test_file_vault_wrong_password_and_missing_password(tmp_path, monkeypatch):
    Vault(tmp_path, backend="arquivo", password="certa").add(_creds()[0])
    with pytest.raises(VaultError, match="senha do cofre incorreta"):
        Vault(tmp_path, backend="arquivo", password="errada").get("ssh-noc")
    monkeypatch.delenv("NETTOPO_VAULT_PASSWORD", raising=False)
    with pytest.raises(VaultError, match="NETTOPO_VAULT_PASSWORD"):
        Vault(tmp_path, backend="arquivo")


def test_remove(tmp_path):
    v = Vault(tmp_path, backend="arquivo", password="x")
    v.add(_creds()[0])
    assert v.remove("ssh-noc") and v.list() == []
    with pytest.raises(VaultError):
        v.get("ssh-noc")


def test_resolve_refs_and_use_all(tmp_path):
    v = Vault(tmp_path, backend="arquivo", password="x")
    for c in _creds():
        v.add(c)
    s = Settings(credentials=[{"ref": "ssh-noc"}, {"type": "rest", "username": "api", "password": "p"}])
    r = resolve_credentials(s, v)
    assert [c.type for c in r.credentials] == ["ssh", "rest"]
    assert r.credentials[0].secret("password") == SECRETS[0]
    r2 = resolve_credentials(Settings(usar_cofre=True), v)
    assert sorted(c.name for c in r2.credentials) == ["snmp-v2", "snmp-v3", "ssh-noc"]
    with pytest.raises(ValueError):
        Settings(credentials=[{"username": "sem-tipo"}])


@pytest.mark.skipif(not _keyring_usable(), reason="sem cofre do sistema operacional")
def test_os_keyring_roundtrip(tmp_path):
    name = f"nettopo-teste-{uuid.uuid4().hex[:8]}"
    v = Vault(tmp_path, backend="keyring")
    v.add(Credential(name=name, type="ssh", username="u", password=SECRETS[0]))
    try:
        assert Vault(tmp_path, backend="keyring").get(name).secret("password") == SECRETS[0]
        assert SECRETS[0].encode() not in (tmp_path / "vault_index.json").read_bytes()
    finally:
        assert v.remove(name)
