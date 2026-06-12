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
    monkeypatch.setenv("BOH_DETERMINISTIC_REVIEW_ON_INDEX", "false")

    import app.db.connection as db
    db.DB_PATH = str(db_path)
    db.init_db()

    import app.core.autoindex as autoindex
    importlib.reload(autoindex)

    import app.api.main as main
    importlib.reload(main)
    main.db.DB_PATH = str(db_path)
    main.db.init_db()
    with TestClient(main.app) as client:
        yield client, db, library, autoindex


def _auth():
    return {"X-BOH-Operator-Token": "test-token", "X-BOH-Actor-ID": "local_operator"}


def _plain_md(title: str = "Browser Doc") -> str:
    return f"# {title}\n\nImported from the browser.\n"


def _count_events(db, event_type: str) -> int:
    row = db.fetchone("SELECT COUNT(*) AS n FROM audit_log WHERE event_type = ?", (event_type,))
    return row["n"]


def test_bulk_upload_once_creates_one_import_activity_event(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, db, _library, _autoindex):
        res = client.post(
            "/api/input/upload",
            data={"target_folder": "imports/activity"},
            files=[("files", ("doc.md", _plain_md(), "text/markdown"))],
            headers=_auth(),
        )
        assert res.status_code == 200
        payload = res.json()
        assert payload["saved"][0]["action"] == "imported"
        assert payload["saved"][0]["indexed"] is True
        assert _count_events(db, "import") == 1

        activity = client.get("/api/workspace/activity-log", params={"event_type": "import"}).json()
        assert activity["total"] == 1
        assert activity["events"][0]["label"] == "File imported"


def test_repeated_unchanged_upload_is_skipped_not_imported(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, db, _library, _autoindex):
        files = [("files", ("doc.md", _plain_md(), "text/markdown"))]
        first = client.post("/api/input/upload", data={"target_folder": "imports/activity"}, files=files, headers=_auth())
        assert first.status_code == 200
        assert first.json()["saved"][0]["action"] == "imported"

        second = client.post("/api/input/upload", data={"target_folder": "imports/activity"}, files=files, headers=_auth())
        assert second.status_code == 200
        item = second.json()["saved"][0]
        assert item["skipped"] is True
        assert item["action"] == "skipped_unchanged"
        assert item["skip_reason"] == "unchanged"
        assert _count_events(db, "import") == 1
        assert _count_events(db, "import_skipped_unchanged") == 1

        paths = db.fetchall("SELECT path FROM docs")
        assert [row["path"] for row in paths] == ["imports/activity/doc.md"]


def test_backend_upload_endpoint_does_not_double_log_import(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, db, _library, _autoindex):
        res = client.post(
            "/api/input/upload",
            data={"target_folder": "imports/activity"},
            files=[
                ("files", ("a.md", _plain_md("A"), "text/markdown")),
                ("files", ("b.md", _plain_md("B"), "text/markdown")),
            ],
            headers=_auth(),
        )
        assert res.status_code == 200
        assert len(res.json()["saved"]) == 2
        assert _count_events(db, "import") == 2


def test_autoindex_existing_import_does_not_create_import_activity(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, db, library, autoindex):
        res = client.post(
            "/api/input/upload",
            data={"target_folder": "imports/activity"},
            files=[("files", ("doc.md", _plain_md(), "text/markdown"))],
            headers=_auth(),
        )
        assert res.status_code == 200
        assert _count_events(db, "import") == 1

        result = autoindex.run_auto_index(str(library), changed_only=True)
        assert result["failed"] == 0
        assert _count_events(db, "import") == 1
        assert _count_events(db, "index") == 1


def test_activity_log_distinguishes_import_index_and_analysis(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, db, library, autoindex):
        res = client.post(
            "/api/input/upload",
            data={"target_folder": "imports/activity"},
            files=[("files", ("doc.md", _plain_md(), "text/markdown"))],
            headers=_auth(),
        )
        assert res.status_code == 200
        autoindex.run_auto_index(str(library), changed_only=True)

        event_types = {row["event_type"] for row in db.fetchall("SELECT event_type FROM audit_log")}
        assert "import" in event_types
        assert "index" in event_types
        assert "save" in event_types
        assert "import" != "index"
        assert "import" != "save"
