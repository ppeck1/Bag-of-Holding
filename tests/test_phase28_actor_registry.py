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


def test_default_actors_seed_and_no_secret_exposure(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, _library):
        res = client.get("/api/actors")
        assert res.status_code == 200
        ids = {a["actor_id"] for a in res.json()["actors"]}
        assert {"boh_system", "local_operator", "bulk_importer", "unknown_actor", "codex", "ollama_local"} <= ids
        assert "test-token" not in res.text


def test_create_update_alias_and_read_actor(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, _library):
        created = client.post(
            "/api/actors",
            json={"actor_id": "local_user", "display_name": "Local User", "actor_type": "human"},
            headers=_auth(),
        )
        assert created.status_code == 200
        assert created.json()["actor_id"] == "local_user"

        updated = client.patch("/api/actors/local_user", json={"display_name": "Local User Updated"}, headers=_auth())
        assert updated.status_code == 200
        assert updated.json()["display_name"] == "Local User Updated"

        alias = client.post("/api/actors/local_user/aliases", json={"alias": "example_username", "source": "test"}, headers=_auth())
        assert alias.status_code == 200

        read = client.get("/api/actors/local_user")
        assert read.status_code == 200
        assert read.json()["aliases"][0]["alias"] == "example_username"

