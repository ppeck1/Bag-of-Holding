import importlib
from contextlib import contextmanager

from fastapi.testclient import TestClient


@contextmanager
def _client(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    db_path = tmp_path / "boh.db"
    monkeypatch.setenv("BOH_LIBRARY", str(library))
    monkeypatch.setenv("BOH_DB", str(db_path))
    monkeypatch.setenv("BOH_OPERATOR_TOKEN", "test-token")

    import app.db.connection as db
    db.DB_PATH = str(db_path)
    db.init_db()

    import app.api.main as main
    importlib.reload(main)
    main.db.DB_PATH = str(db_path)
    main.db.init_db()
    with TestClient(main.app) as client:
        yield client, db, library


def _auth(actor="local_operator"):
    return {"X-BOH-Operator-Token": "test-token", "X-BOH-Actor-ID": actor}


def test_create_grant_requires_operator_and_is_scope_aware(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, _library):
        client.post("/api/actors", json={"actor_id": "reviewer1", "display_name": "Reviewer", "actor_type": "human"}, headers=_auth())
        payload = {
            "actor_id": "reviewer1",
            "action": "review_proposal",
            "scope_type": "project",
            "scope_id": "Primitive Test",
            "authority_level": "reviewer",
        }
        missing = client.post("/api/authority/grants", json=payload)
        assert missing.status_code == 401

        ok = client.post("/api/authority/grants", json=payload, headers=_auth())
        assert ok.status_code == 200
        grant = ok.json()
        assert grant["scope_type"] == "project"
        assert grant["scope_id"] == "Primitive Test"

        listed = client.get("/api/authority/grants", params={"actor_id": "reviewer1", "scope_id": "Primitive Test"})
        assert len(listed.json()["grants"]) == 1


def test_inactive_grant_ignored_and_restricted_action_denied_without_grant(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, library):
        client.post("/api/actors", json={"actor_id": "noauth", "display_name": "No Auth", "actor_type": "human"}, headers=_auth())
        denied = client.post(
            "/api/governance/policy",
            json={
                "workspace": str(library),
                "entity_type": "model",
                "entity_id": "m",
                "can_read": 1,
                "can_write": 0,
                "can_execute": 0,
                "can_propose": 1,
                "can_promote": 0,
            },
            headers=_auth("noauth"),
        )
        assert denied.status_code == 403

        grant = client.post(
            "/api/authority/grants",
            json={"actor_id": "noauth", "action": "mutate_policy", "scope_type": "workspace", "scope_id": str(library), "authority_level": "operator", "active": False},
            headers=_auth(),
        )
        assert grant.status_code == 200
        denied_again = client.post(
            "/api/governance/policy",
            json={
                "workspace": str(library),
                "entity_type": "model",
                "entity_id": "m",
                "can_read": 1,
                "can_write": 0,
                "can_execute": 0,
                "can_propose": 1,
                "can_promote": 0,
            },
            headers=_auth("noauth"),
        )
        assert denied_again.status_code == 403

        ledger = client.get("/api/ledger/recent", params={"actor_id": "noauth"})
        assert any(e["authority_result"] == "denied" for e in ledger.json()["events"])


def test_operator_fallback_logged_when_allowed(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, library):
        ok = client.post(
            "/api/governance/policy",
            json={"workspace": str(library), "entity_type": "model", "entity_id": "m"},
            headers=_auth(),
        )
        assert ok.status_code == 200
        ledger = client.get("/api/ledger/recent", params={"actor_id": "local_operator"})
        assert any(e["action"] == "mutate_policy" and e["authority_result"] == "allowed" for e in ledger.json()["events"])

