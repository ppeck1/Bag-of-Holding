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
        yield client


def test_operator_diagnostic_confirms_headers_without_revealing_token(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        res = client.post(
            "/api/operator/diagnostic",
            headers={"X-BOH-Operator-Token": "test-token", "X-BOH-Actor-ID": "local_operator"},
        )
        assert res.status_code == 200
        payload = res.json()
        assert payload["operator_header_received"] is True
        assert payload["actor_header_received"] is True
        assert payload["actor_id"] == "local_operator"
        assert "test-token" not in res.text
