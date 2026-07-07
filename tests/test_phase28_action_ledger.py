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


def test_import_reset_seed_and_denied_action_write_ledger(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, library):
        md = "---\nboh:\n  id: led-doc\n  status: draft\n  type: note\n  version: '1'\n  updated: '2026-01-01T00:00:00Z'\n  rubrix:\n    operator_state: observe\n    operator_intent: capture\n---\n# Ledger Doc"
        upload = client.post(
            "/api/input/upload",
            data={"target_folder": "imports"},
            files=[("files", ("led.md", md, "text/markdown"))],
            headers=_auth(),
        )
        assert upload.status_code == 200

        seed = client.post("/api/workspace/seed-fixtures", json={}, headers=_auth())
        assert seed.status_code == 200
        reset = client.post("/api/workspace/reset-full", json={"confirm": "RESET", "preserve_canonical": False}, headers=_auth())
        assert reset.status_code == 200

        client.post("/api/actors", json={"actor_id": "denied_actor", "display_name": "Denied", "actor_type": "human"}, headers=_auth())
        denied = client.post(
            "/api/governance/policy",
            json={"workspace": str(library), "entity_type": "model", "entity_id": "m"},
            headers=_auth("denied_actor"),
        )
        assert denied.status_code == 403

        events = client.get("/api/ledger/recent", params={"limit": 50}).json()["events"]
        actions = [e["action"] for e in events]
        assert "import_document" in actions
        assert "seed_fixtures" in actions
        assert "reset_workspace" in actions
        assert any(e["action"] == "mutate_policy" and e["authority_result"] == "denied" for e in events)


def test_ledger_append_only_visible_via_recent_endpoint(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, library):
        before = client.get("/api/ledger/recent").json()["events"]
        client.post("/api/governance/policy", json={"workspace": str(library), "entity_type": "model", "entity_id": "m"}, headers=_auth())
        after = client.get("/api/ledger/recent").json()["events"]
        assert len(after) >= len(before) + 1
