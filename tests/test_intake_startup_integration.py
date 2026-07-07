"""Gate B.5 startup/lifespan integration — isolated DB only.

Exercises the real application startup path (which triggers init_db() at import) under an
ISOLATED BOH_DB, verifies the migration applies exactly once, and that the lifespan starts and
stops the managed intake scheduler. Never touches the real ./boh.db.
"""

from __future__ import annotations

import importlib
import os

from fastapi.testclient import TestClient


def test_suite_runs_against_isolated_db():
    # Enforced by tests/conftest.py — the suite must never target the repo's real boh.db.
    boh_db = os.environ.get("BOH_DB", "")
    assert boh_db, "BOH_DB must be set to an isolated database for the test suite"
    assert os.path.abspath(boh_db) != os.path.abspath(os.path.join(os.getcwd(), "boh.db"))


def test_app_import_under_isolated_db_applies_migration_once(tmp_path, monkeypatch):
    db_path = tmp_path / "startup.db"
    monkeypatch.setenv("BOH_DB", str(db_path))
    import app.db.connection as conn_mod
    importlib.reload(conn_mod)  # pick up the isolated BOH_DB
    assert conn_mod.DB_PATH == str(db_path)

    import app.api.main as main
    importlib.reload(main)  # triggers init_db() at import against the isolated DB

    rows = conn_mod.fetchall(
        "SELECT migration_id, COUNT(*) AS c FROM schema_migrations GROUP BY migration_id")
    counts = {r["migration_id"]: r["c"] for r in rows}
    assert counts.get("0001_intake_orchestration_integrity") == 1  # applied exactly once


def test_lifespan_starts_then_stops_managed_scheduler(tmp_path, monkeypatch):
    db_path = tmp_path / "lifespan.db"
    data_root = tmp_path / "data"; data_root.mkdir()
    watch = tmp_path / "watch"; watch.mkdir()
    monkeypatch.setenv("BOH_DB", str(db_path))
    monkeypatch.setenv("BOH_DATA_ROOT", str(data_root))
    monkeypatch.setenv("BOH_INTAKE_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("BOH_WATCH_PATH", str(watch))
    monkeypatch.setenv("BOH_INTAKE_SCAN_INTERVAL", "3600")  # scan once then idle

    import app.db.connection as conn_mod
    importlib.reload(conn_mod)
    from app.services.intake import scheduler_manager
    scheduler_manager._MANAGER.stop()  # ensure a clean singleton

    import app.api.main as main
    importlib.reload(main)
    try:
        with TestClient(main.app):  # entering the context runs lifespan startup
            assert scheduler_manager.status()["running"] is True  # one manager started
        # leaving the context runs lifespan shutdown
        assert scheduler_manager.status()["running"] is False  # stopped, dispatch halted
    finally:
        scheduler_manager._MANAGER.stop()
