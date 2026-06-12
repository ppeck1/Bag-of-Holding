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


def test_clean_workspace_removes_stale_refs_and_preserves_outside(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, db, library):
        outside = tmp_path / "outside-sentinel.txt"
        outside.write_text("do not touch", encoding="utf-8")

        app_owned = library / "fixtures" / "primitive_test" / "old.md"
        app_owned.parent.mkdir(parents=True)
        app_owned.write_text("old", encoding="utf-8")
        uncertain = library / "user-note.md"
        uncertain.write_text("user material", encoding="utf-8")
        artifact = library / "user-note.review.json"
        artifact.write_text("{}", encoding="utf-8")

        db.execute(
            "INSERT OR REPLACE INTO docs (doc_id, path, status) VALUES (?,?,?)",
            ("missing-doc", "missing.md", "draft"),
        )
        db.execute(
            "INSERT OR IGNORE INTO lineage (doc_id, related_doc_id, relationship, detected_ts) VALUES (?,?,?,?)",
            ("missing-doc", "other", "derived_from", 1),
        )
        try:
            db.execute(
                "INSERT INTO docs_fts(content, title, path, topics) VALUES (?,?,?,?)",
                ("missing", "missing", "missing.md", "[]"),
            )
        except Exception:
            pass

        res = client.post(
            "/api/workspace/reset-full",
            json={"confirm": "RESET", "preserve_canonical": False},
            headers=_auth(),
        )
        assert res.status_code == 200
        payload = res.json()
        assert set(payload) >= {
            "ok", "files_removed", "files_quarantined", "artifacts_removed",
            "stale_refs_removed", "db_rows_removed", "fixtures_seeded",
            "reindex_status", "warnings",
        }
        assert not app_owned.exists()
        assert not artifact.exists()
        assert not uncertain.exists()
        assert any("user-note.md" in p for p in payload["files_quarantined"])
        assert outside.read_text(encoding="utf-8") == "do not touch"
        assert db.fetchone("SELECT * FROM docs WHERE doc_id = ?", ("missing-doc",)) is None
