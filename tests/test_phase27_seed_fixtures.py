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


def _auth():
    return {"X-BOH-Operator-Token": "test-token"}


def test_seed_requires_auth(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, _library):
        res = client.post("/api/workspace/seed-fixtures", json={})
        assert res.status_code == 401


def test_seed_writes_only_fixture_namespace_and_is_idempotent(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, db, library):
        first = client.post("/api/workspace/seed-fixtures", json={}, headers=_auth())
        assert first.status_code == 200
        first_payload = first.json()
        assert first_payload["seed_namespace"] == "primitive_test"
        assert first_payload["files_created"]
        assert all(p.startswith("fixtures/primitive_test/") for p in first_payload["files_created"])

        second = client.post("/api/workspace/seed-fixtures", json={}, headers=_auth())
        assert second.status_code == 200
        second_payload = second.json()
        assert second_payload["files_created"] == []
        assert second_payload["files_replaced"] == []
        assert second_payload["files_skipped"]

        md = db.fetchone("SELECT doc_id, path FROM docs WHERE doc_id = ?", ("primitive-valid-md",))
        html = db.fetchone("SELECT doc_id, path FROM docs WHERE path = ?", ("fixtures/primitive_test/sample.html",))
        nested = db.fetchone("SELECT doc_id, path FROM docs WHERE path = ?", ("fixtures/primitive_test/nested/path-preserved.md",))
        assert md and md["path"] == "fixtures/primitive_test/valid_markdown.md"
        assert html
        assert nested

        content = client.get("/api/docs/primitive-valid-md/content")
        assert content.status_code == 200
        assert "Primitive Valid Markdown" in content.text


def test_clean_then_seed_known_good_state(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, db, _library):
        clean = client.post(
            "/api/workspace/reset-full",
            json={"confirm": "RESET", "preserve_canonical": False},
            headers=_auth(),
        )
        assert clean.status_code == 200

        seed = client.post("/api/workspace/seed-fixtures", json={}, headers=_auth())
        assert seed.status_code == 200
        assert seed.json()["indexed_count"] >= 6
        row = db.fetchone("SELECT COUNT(*) as n FROM docs WHERE path LIKE 'fixtures/primitive_test/%'")
        assert row["n"] >= 6

