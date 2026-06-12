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


def _auth():
    return {"X-BOH-Operator-Token": "test-token", "X-BOH-Actor-ID": "local_operator"}


def test_demo_seed_reports_capability_surfaces_and_next_steps(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as (client, _db, _library):
        res = client.post("/api/input/demo-seed", headers=_auth())
        assert res.status_code == 200
        payload = res.json()

        surfaces = payload["capability_surfaces"]
        surface_names = {s["surface"] for s in surfaces}
        assert {
            "Library",
            "Search",
            "Visualization",
            "Custodian Layer",
            "Domains",
            "Retrieval",
            "System Status",
        }.issubset(surface_names)
        assert all(s["what_to_check"] for s in surfaces)
        assert all(s["route_hint"].startswith("/api/") for s in surfaces)
        assert payload["next_steps"]
        assert "Open Visualization" in " ".join(payload["next_steps"])
        assert "Proposed Changes" in " ".join(payload["next_steps"])
        assert payload["includes_daenary_epistemic_state"] is True


def test_demo_ui_renders_capability_manifest():
    app_js = open("app/ui/app.js", encoding="utf-8").read()
    assert "capability_surfaces" in app_js
    assert "Capability surfaces:" in app_js
    assert "next_steps" in app_js
