import importlib
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient


@contextmanager
def _client(tmp_path, monkeypatch, token_marker="set"):
    library = tmp_path / "library"
    library.mkdir()
    db_path = tmp_path / "boh.db"
    monkeypatch.setenv("BOH_LIBRARY", str(library))
    monkeypatch.setenv("BOH_DB", str(db_path))
    if token_marker == "unset":
        monkeypatch.delenv("BOH_OPERATOR_TOKEN", raising=False)
    else:
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


def _auth(value="test-token"):
    return {"X-BOH-Operator-Token": value}


def test_reset_open_when_operator_token_unset(tmp_path, monkeypatch):
    """Dev-open mode: when BOH_OPERATOR_TOKEN is not set, protected routes are allowed through.
    This is intentional for frictionless local development. Set the env var to enforce auth."""
    with _client(tmp_path, monkeypatch, token_marker="unset") as (client, _db, _library):
        res = client.post("/api/workspace/reset", json={"confirm": "RESET"})
        # In dev-open mode the route is permitted (200) rather than blocked (403)
        assert res.status_code == 200


def test_reset_fails_when_header_missing(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, _library):
        res = client.post("/api/workspace/reset", json={"confirm": "RESET"})
        assert res.status_code == 401
        assert "X-BOH-Operator-Token" in res.text


def test_reset_fails_with_invalid_token(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, _library):
        res = client.post("/api/workspace/reset", json={"confirm": "RESET"}, headers=_auth("bad"))
        assert res.status_code == 403


def test_reset_succeeds_with_valid_token(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, _library):
        res = client.post("/api/workspace/reset", json={"confirm": "RESET"}, headers=_auth())
        assert res.status_code == 200
        assert res.json()["ok"] is True


def test_operator_status_does_not_reveal_secret(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, _library):
        res = client.get("/api/operator/status")
        assert res.status_code == 200
        payload = res.json()
        # When token IS configured: dev_open=False, configured=True, fail_closed=True
        assert payload["configured"] is True
        assert payload["dev_open"] is False
        assert payload["protected_routes_fail_closed"] is True
        assert payload["header_name"] == "X-BOH-Operator-Token"
        assert "test-token" not in res.text


def test_governance_mutation_requires_auth(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, library):
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
        assert res.status_code == 401

