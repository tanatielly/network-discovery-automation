import time

from fastapi.testclient import TestClient

from nettopo.api.app import create_app


def test_api_demo_flow(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        assert any(v["id"] == "cisco_ios" for v in client.get("/api/vendors").json())
        rid = client.post("/api/demo").json()["id"]
        with client.websocket_connect(f"/api/discoveries/{rid}/events") as ws:
            types = []
            while True:
                ev = ws.receive_json()
                types.append(ev["type"])
                if ev["type"] == "closed":
                    break
        assert "device_done" in types and "finished" in types
        for _ in range(50):
            info = client.get(f"/api/discoveries/{rid}").json()
            if info["status"] == "finished":
                break
            time.sleep(0.1)
        assert info["status"] == "finished" and info["stats"]["collected"] == 16
        view = client.get(f"/api/discoveries/{rid}/view").json()
        assert len(view["graph"]["elements"]["nodes"]) == len(view["devices"])
        for fmt in ("html", "drawio", "xlsx", "md", "json"):
            r = client.get(f"/api/discoveries/{rid}/export/{fmt}")
            assert r.status_code == 200 and len(r.content) > 500, fmt
        assert client.get("/").status_code == 200
        assert client.delete(f"/api/discoveries/{rid}").json()["deleted"]


def test_api_validation_and_no_secrets_stored(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        assert client.post("/api/discoveries", json={"seeds": []}).status_code == 422
        body = {"seeds": ["192.0.2.1"], "timeout": 2, "methods": ["snmp"],
                "credentials": [{"type": "snmp", "version": "2c", "community": "supersecret"}]}
        rid = client.post("/api/discoveries", json=body).json()["id"]
        rec = app.state.store.get(rid)
        assert "supersecret" not in rec.settings_json


def test_api_token(tmp_path, monkeypatch):
    monkeypatch.setenv("NETTOPO_API_TOKEN", "abc")
    app = create_app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/discoveries").status_code == 401
        assert client.get("/api/discoveries", headers={"Authorization": "Bearer abc"}).status_code == 200


def _wait(client, rid):
    for _ in range(100):
        st = client.get(f"/api/discoveries/{rid}").json()
        if st["status"] in ("finished", "failed"):
            return st
        time.sleep(0.1)
    return st


def test_api_credentials_memory_and_verify(tmp_path, monkeypatch):
    monkeypatch.setenv("NETTOPO_VAULT_BACKEND", "arquivo")
    monkeypatch.setenv("NETTOPO_VAULT_PASSWORD", "senha-teste")
    app = create_app(tmp_path)
    with TestClient(app) as client:
        r = client.post("/api/credentials", json={"name": "snmp-lab", "type": "snmp", "community": "segredo-xyz"})
        assert r.status_code == 201
        listed = client.get("/api/credentials").json()
        assert listed["backend"] == "arquivo" and listed["items"][0]["name"] == "snmp-lab"
        assert "segredo-xyz" not in str(listed)
        assert client.post("/api/verify").status_code == 409  # memória vazia

        first = _wait(client, client.post("/api/demo").json()["id"])
        second = _wait(client, client.post("/api/demo").json()["id"])
        assert first["stats"]["memoria"]["conhecidos"] == 0
        assert second["stats"]["memoria"]["reaproveitados"] == second["stats"]["collected"] == 16
        assert client.get("/api/inventory").json()["devices"] == []  # demo usa memória separada
        assert client.delete("/api/credentials/snmp-lab").json()["deleted"]
