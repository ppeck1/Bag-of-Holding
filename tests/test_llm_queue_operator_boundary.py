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

    import app.core.auth as auth
    import app.api.main as main
    importlib.reload(auth)
    importlib.reload(main)
    main.db.DB_PATH = str(db_path)
    main.db.init_db()
    with TestClient(main.app) as client:
        yield client, db, library


def _auth(actor="local_operator"):
    return {"X-BOH-Operator-Token": "test-token", "X-BOH-Actor-ID": actor}


def test_llm_queue_enqueue_requires_operator_token(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, _library):
        res = client.post(
            "/api/llm/queue",
            json={"doc_id": "doc1", "proposed": {"summary": "Better", "confidence": 0.8}},
        )
        assert res.status_code in (401, 403)


def test_llm_queue_enqueue_with_operator_token_records_pending_proposal(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, _library):
        res = client.post(
            "/api/llm/queue",
            json={"doc_id": "doc1", "proposed": {"summary": "Better", "confidence": 0.8}, "model": "llama"},
            headers=_auth(),
        )
        assert res.status_code == 200
        payload = res.json()
        assert payload["status"] == "pending"
        assert payload["queue_id"]

        queue = client.get("/api/llm/queue").json()
        assert queue["count"] == 1
        assert queue["items"][0]["queue_id"] == payload["queue_id"]
