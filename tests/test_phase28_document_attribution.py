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


def test_imported_document_gets_imported_by_attribution(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, _library):
        client.post("/api/actors", json={"actor_id": "importer_a", "display_name": "Importer A", "actor_type": "human"}, headers=_auth())
        md = "---\nboh:\n  id: attr-doc\n  status: draft\n  type: note\n  version: '1'\n  updated: '2026-01-01T00:00:00Z'\n  rubrix:\n    operator_state: observe\n    operator_intent: capture\n---\n# Attr Doc"
        res = client.post(
            "/api/input/upload",
            data={"target_folder": "imports"},
            files=[("files", ("attr.md", md, "text/markdown"))],
            headers=_auth("importer_a"),
        )
        assert res.status_code == 200
        attr = client.get("/api/docs/attr-doc/attribution").json()["attribution"]
        assert any(a["attribution_type"] == "imported_by" and a["actor_id"] == "importer_a" for a in attr)


def test_modified_and_approved_attribution(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, db, library):
        doc_path = library / "doc.md"
        doc_path.write_text("---\nboh:\n  id: doc1\n  status: draft\n  type: note\n  version: '1'\n  updated: '2026-01-01T00:00:00Z'\n  rubrix:\n    operator_state: observe\n    operator_intent: capture\n---\n# Doc", encoding="utf-8")
        db.execute("INSERT OR REPLACE INTO docs (doc_id, path, status, operator_state, operator_intent) VALUES (?,?,?,?,?)", ("doc1", "doc.md", "draft", "observe", "capture"))

        trans = client.patch("/api/workflow/doc1", json={"operator_state": "vessel", "operator_intent": "triage"}, headers=_auth())
        assert trans.status_code == 200

        q = client.post("/api/llm/queue", json={"doc_id": "doc1", "proposed": {"summary": "Better", "confidence": 0.8}, "model": "llama"}, headers=_auth())
        queue_id = q.json()["queue_id"]
        app = client.post(f"/api/llm/queue/{queue_id}/approve", json={"actor": "local_operator"}, headers=_auth())
        assert app.status_code == 200

        attr = client.get("/api/docs/doc1/attribution").json()["attribution"]
        kinds = {a["attribution_type"] for a in attr}
        assert "modified_by" in kinds
        assert "approved_by" in kinds
