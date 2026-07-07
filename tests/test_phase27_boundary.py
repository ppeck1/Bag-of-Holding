import importlib
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def phase27_client(tmp_path, monkeypatch):
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
        yield client, db, library, tmp_path


def _auth():
    return {"X-BOH-Operator-Token": "test-token", "X-BOH-Actor-ID": "local_operator"}


def test_path_traversal_read_is_rejected(phase27_client):
    client, db, _library, tmp_path = phase27_client
    (tmp_path / "outside.txt").write_text("outside secret", encoding="utf-8")
    db.execute(
        "INSERT OR REPLACE INTO docs (doc_id, path, status) VALUES (?,?,?)",
        ("evil-doc", "../outside.txt", "draft"),
    )

    res = client.get("/api/docs/evil-doc/content")
    assert res.status_code == 400
    assert "traversal" in res.text.lower() or "rejected" in res.text.lower()


def test_snapshot_path_poisoning_is_rejected(phase27_client):
    client, db, library, tmp_path = phase27_client
    (tmp_path / "outside.txt").write_text("outside secret", encoding="utf-8")
    snapshot = {
        "run_id": "poison-test",
        "files": [
            {
                "artifacts": {
                    "meta": {
                        "id": "poisoned",
                        "path": "../outside.txt",
                        "type": "note",
                        "status": "draft",
                    }
                }
            }
        ],
    }
    (library / "snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")

    res = client.post("/api/ingest/snapshot", json={"path": "snapshot.json"}, headers=_auth())
    assert res.status_code == 200
    payload = res.json()
    assert payload["inserted_docs"] == 0
    assert payload["skipped"][0]["reason"] == "unsafe_path"
    assert db.fetchone("SELECT * FROM docs WHERE doc_id='poisoned'") is None


def test_index_rejects_external_caller_root_by_default(phase27_client):
    client, _db, _library, tmp_path = phase27_client
    external = tmp_path / "external"
    external.mkdir()
    (external / "x.md").write_text("---\nboh:\n  id: x\n---\n\n# X", encoding="utf-8")

    unauth = client.post("/api/index", json={"library_root": str(external)})
    assert unauth.status_code in (401, 403)

    res = client.post("/api/index", json={"library_root": str(external)}, headers=_auth())
    assert res.status_code == 403


def test_mutation_routes_require_operator_authorization(phase27_client):
    client, _db, _library, _tmp_path = phase27_client
    probes = [
        ("/api/autoindex/run", {"changed_only": True}),
        ("/api/input/markdown", {"title": "Nope", "body": "body"}),
        ("/api/ollama/enabled", {"enabled": True}),
        ("/api/planes/cards", {"plane": "informational", "topic": "Nope", "d": 0, "m": "contain"}),
        ("/api/planes/llm-output", {"topic": "Nope", "text": "proposal"}),
        ("/api/planes/backfill", {}),
    ]
    for path, payload in probes:
        res = client.post(path, json=payload)
        assert res.status_code in (401, 403), path


def test_execution_denied_without_operator_authorization(phase27_client):
    client, _db, _library, _tmp_path = phase27_client
    res = client.post(
        "/api/exec/run",
        json={"doc_id": "d", "block_id": "b", "language": "shell", "code": "echo hi"},
    )
    assert res.status_code in (401, 403)


def test_workspace_reset_requires_operator_beyond_confirm(phase27_client):
    client, _db, _library, _tmp_path = phase27_client
    res = client.post("/api/workspace/reset", json={"confirm": "RESET"})
    assert res.status_code in (401, 403)

    ok = client.post("/api/workspace/reset", json={"confirm": "RESET"}, headers=_auth())
    assert ok.status_code == 200
    assert ok.json()["ok"] is True


def test_governance_policy_mutation_requires_operator(phase27_client):
    client, _db, library, _tmp_path = phase27_client
    payload = {
        "workspace": str(library),
        "entity_type": "model",
        "entity_id": "m",
        "can_read": 1,
        "can_write": 0,
        "can_execute": 0,
        "can_propose": 1,
        "can_promote": 0,
    }
    res = client.post("/api/governance/policy", json=payload)
    assert res.status_code in (401, 403)


def test_review_artifact_write_cannot_escape_library(phase27_client):
    client, db, _library, _tmp_path = phase27_client
    db.execute(
        "INSERT OR REPLACE INTO docs (doc_id, path, status) VALUES (?,?,?)",
        ("escape-review", "../outside.md", "draft"),
    )

    res = client.get("/api/review", params={"path": "../outside.md", "force": "true"}, headers=_auth())
    assert res.status_code in (400, 404)
