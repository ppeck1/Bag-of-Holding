import importlib
import warnings
from contextlib import contextmanager

from fastapi.testclient import TestClient


@contextmanager
def _client(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    db_path = tmp_path / "boh.db"
    monkeypatch.setenv("BOH_LIBRARY", str(library))
    monkeypatch.setenv("BOH_DB", str(db_path))

    import app.db.connection as db
    db.DB_PATH = str(db_path)
    db.init_db()

    import app.api.main as main
    importlib.reload(main)
    main.db.DB_PATH = str(db_path)
    main.db.init_db()
    with TestClient(main.app) as client:
        yield client


def test_health_uses_shared_runtime_version(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        from app.core.version import APP_VERSION, STATUS_LABEL, SYSTEM_PHASE

        res = client.get("/api/health")
        assert res.status_code == 200
        payload = res.json()
        assert payload["version"] == APP_VERSION
        assert payload["phase"] == SYSTEM_PHASE
        assert payload["status_label"] == STATUS_LABEL


def test_openapi_has_no_duplicate_operation_warnings(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            res = client.get("/openapi.json")
        assert res.status_code == 200
        duplicate_warnings = [
            str(w.message) for w in caught
            if "Duplicate Operation ID" in str(w.message)
        ]
        assert duplicate_warnings == []
