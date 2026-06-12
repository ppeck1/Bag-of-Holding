"""Phase 8 replay, backpressure, and scheduler tests.

Verifies:
- replay.reprocess() re-runs a held/failed capability through the pipeline
- replay.reprocess() updates DB records on success
- replay.list_replayable() returns only non-quarantined held capabilities
- replay.reprocess() returns failure for missing source file
- replay.reprocess() returns failure for missing capability ID
- background_services.start_if_enabled() returns False when disabled
- background_services.start_if_enabled() returns False when BOH_WATCH_PATH unset
- background_services._scan_once() dispatches files under backpressure limit
- Backpressure: _scan_once() skips dispatch when in-flight >= max
- canon_eligible remains False throughout all Phase 8 paths
- ReplayConfigError raised when data_root absent
"""

from __future__ import annotations

import importlib
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_db(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    db_path = tmp_path / "boh.db"
    data_root = tmp_path / "data"
    data_root.mkdir()
    monkeypatch.setenv("BOH_LIBRARY", str(library))
    monkeypatch.setenv("BOH_DB", str(db_path))
    monkeypatch.setenv("BOH_DATA_ROOT", str(data_root))
    monkeypatch.setenv("BOH_OPERATOR_TOKEN", "test-token")

    import app.db.connection as db_conn
    db_conn.DB_PATH = str(db_path)
    db_conn.init_db()
    return db_conn, str(data_root)


def _make_source(tmp_path, filename="doc.md", content="# Title\n\nBody text here."):
    watch = tmp_path / "watch"
    watch.mkdir(exist_ok=True)
    src = watch / filename
    if isinstance(content, bytes):
        src.write_bytes(content)
    else:
        src.write_text(content, encoding="utf-8")
    return str(src)


def _run_intake_pipeline(src, batch_id, data_root, db_conn):
    """Run the full intake pipeline and return (cap_id, success)."""
    from app.services.intake.capability import initialize_capability
    from app.services.intake.preservation import preserve_file
    from app.services.intake.translation_router import route
    from app.services.intake.normalization import normalize
    from app.services.intake import db_writer

    init = initialize_capability(source_ref=src, batch_id=batch_id)
    cap = init.capability
    db_writer.write_capability(cap)

    pres = preserve_file(cap, data_root=data_root)
    if not pres.success:
        db_writer.write_capability(cap)
        return cap.intake_capability_id, False

    db_writer.write_raw_artifact(pres.raw_artifact)
    db_writer.write_capability(cap)
    return cap.intake_capability_id, True


# ---------------------------------------------------------------------------
# replay.reprocess() — success
# ---------------------------------------------------------------------------

def test_reprocess_successful_pipeline(tmp_path, monkeypatch):
    db_conn, data_root = _setup_db(tmp_path, monkeypatch)
    src = _make_source(tmp_path, "replay.md", "# Replay\n\nContent long enough to pass queryability.")
    # New contract (WO-1): an orchestrated first pass produces a terminal revision; replay then
    # reclaims it and runs a fresh attempt.
    from app.services.intake.orchestrator import execute_intake
    first = execute_intake(source_ref=src, batch_id="rp01", trigger_kind="manual", data_root=data_root)
    assert first.outcome == "processed"

    from app.services.intake.replay import reprocess
    result = reprocess(first.intake_capability_id, data_root=data_root)
    assert result.success is True
    assert result.stage_reached == "handoff"


def test_reprocess_updates_capability_in_db(tmp_path, monkeypatch):
    db_conn, data_root = _setup_db(tmp_path, monkeypatch)
    src = _make_source(tmp_path, "replay2.md", "# Replay\n\nContent long enough to pass queryability.")
    from app.services.intake.orchestrator import execute_intake
    first = execute_intake(source_ref=src, batch_id="rp02", trigger_kind="manual", data_root=data_root)

    from app.services.intake.replay import reprocess
    result = reprocess(first.intake_capability_id, data_root=data_root)

    # the replay run produced a new normalizable capability; canon stays false
    row = db_conn.fetchone(
        "SELECT normalizable, canon_eligible FROM intake_capabilities WHERE intake_capability_id = ?",
        (result.intake_capability_id,),
    )
    assert row["normalizable"] == 1
    assert row["canon_eligible"] == 0


def test_reprocess_canon_eligible_never_true(tmp_path, monkeypatch):
    db_conn, data_root = _setup_db(tmp_path, monkeypatch)
    src = _make_source(tmp_path, "replay3.md", "# Replay\n\nContent long enough to pass queryability.")
    cap_id, ok = _run_intake_pipeline(src, "rp03", data_root, db_conn)

    from app.services.intake.replay import reprocess
    result = reprocess(cap_id, data_root=data_root)
    row = db_conn.fetchone(
        "SELECT canon_eligible FROM intake_capabilities WHERE intake_capability_id = ?",
        (cap_id,),
    )
    assert row["canon_eligible"] == 0


def test_reprocess_missing_capability_returns_failure(tmp_path, monkeypatch):
    db_conn, data_root = _setup_db(tmp_path, monkeypatch)
    from app.services.intake.replay import reprocess
    result = reprocess("nonexistent-id", data_root=data_root)
    assert result.success is False
    assert result.failure_reason is not None


def test_reprocess_missing_source_file_returns_failure(tmp_path, monkeypatch):
    db_conn, data_root = _setup_db(tmp_path, monkeypatch)
    src = _make_source(tmp_path, "gone.md", "# Gone\n\nContent.")
    cap_id, ok = _run_intake_pipeline(src, "rp05", data_root, db_conn)
    Path(src).unlink()

    from app.services.intake.replay import reprocess
    result = reprocess(cap_id, data_root=data_root)
    assert result.success is False
    assert "not found" in (result.failure_reason or "").lower()


def test_reprocess_raises_config_error_without_data_root(tmp_path, monkeypatch):
    db_conn, data_root = _setup_db(tmp_path, monkeypatch)
    src = _make_source(tmp_path, "noroot.md", "# No root\n\nContent.")
    cap_id, _ = _run_intake_pipeline(src, "rp06", data_root, db_conn)
    monkeypatch.delenv("BOH_DATA_ROOT", raising=False)

    from app.services.intake.replay import reprocess, ReplayConfigError
    with pytest.raises(ReplayConfigError, match="BOH_DATA_ROOT"):
        reprocess(cap_id)


# ---------------------------------------------------------------------------
# replay.list_replayable()
# ---------------------------------------------------------------------------

def test_list_replayable_returns_held_capabilities(tmp_path, monkeypatch):
    db_conn, data_root = _setup_db(tmp_path, monkeypatch)
    from app.services.intake.capability import initialize_capability
    from app.services.intake import db_writer

    # Create a held (non-normalized) capability
    cap = initialize_capability(source_ref="/watch/report.pdf", batch_id="rp07").capability
    db_writer.write_capability(cap)

    from app.services.intake.replay import list_replayable
    replayable = list_replayable(limit=100)
    ids = [r["intake_capability_id"] for r in replayable]
    assert cap.intake_capability_id in ids


def test_list_replayable_excludes_quarantined(tmp_path, monkeypatch):
    db_conn, data_root = _setup_db(tmp_path, monkeypatch)
    from app.services.intake.capability import initialize_capability
    from app.services.intake import db_writer

    cap = initialize_capability(source_ref="/watch/archive.zip", batch_id="rp08").capability
    db_writer.write_capability(cap)

    from app.services.intake.replay import list_replayable
    replayable = list_replayable(limit=100)
    ids = [r["intake_capability_id"] for r in replayable]
    # archive.zip is quarantined — should not appear in replayable list
    assert cap.intake_capability_id not in ids


# ---------------------------------------------------------------------------
# background_services
# ---------------------------------------------------------------------------

def test_start_if_enabled_returns_false_when_disabled(monkeypatch):
    monkeypatch.setenv("BOH_INTAKE_SCHEDULER_ENABLED", "false")
    from app.services.scheduler import background_services
    importlib.reload(background_services)
    result = background_services.start_if_enabled()
    assert result is False


def test_start_if_enabled_returns_false_when_watch_path_unset(monkeypatch):
    monkeypatch.setenv("BOH_INTAKE_SCHEDULER_ENABLED", "true")
    monkeypatch.delenv("BOH_WATCH_PATH", raising=False)
    monkeypatch.setenv("BOH_DATA_ROOT", "/some/root")
    from app.services.scheduler import background_services
    importlib.reload(background_services)
    result = background_services.start_if_enabled()
    assert result is False


def test_start_if_enabled_returns_false_when_watch_path_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("BOH_INTAKE_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("BOH_WATCH_PATH", str(tmp_path / "nonexistent_watch"))
    monkeypatch.setenv("BOH_DATA_ROOT", str(tmp_path / "data"))
    from app.services.scheduler import background_services
    importlib.reload(background_services)
    result = background_services.start_if_enabled()
    assert result is False


def _arm_manager(mgr, cap, data_root):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from app.services.intake import scheduler_manager as sm
    mgr._max = cap
    mgr._sem = threading.BoundedSemaphore(cap) if cap > 0 else sm._ZeroSemaphore()
    mgr._executor = ThreadPoolExecutor(max_workers=max(1, cap))
    mgr._data_root = data_root
    mgr._policy = None
    mgr._stop = threading.Event()


def test_managed_scheduler_dispatches_and_caps(tmp_path, monkeypatch):
    # New contract (WO-1): the managed scheduler dispatches under cap and reserves capacity
    # before submission; cap=0 accepts nothing.
    import types
    db_conn, data_root = _setup_db(tmp_path, monkeypatch)
    watch = tmp_path / "watch"
    watch.mkdir(exist_ok=True)
    (watch / "a.md").write_text("# A\n\nseveral words of content here", encoding="utf-8")

    from app.services.intake import scheduler_manager as sm
    monkeypatch.setattr(sm, "is_stable", lambda p: types.SimpleNamespace(stable=True))

    mgr = sm.SchedulerManager(pipeline_fn=lambda **kw: None)
    _arm_manager(mgr, 1, data_root)
    assert mgr._scan_once(str(watch), data_root) == 1
    mgr._executor.shutdown(wait=True)

    (watch / "b.md").write_text("# B\n\nmore distinct words here now", encoding="utf-8")
    mgr0 = sm.SchedulerManager(pipeline_fn=lambda **kw: None)
    _arm_manager(mgr0, 0, data_root)
    assert mgr0._scan_once(str(watch), data_root) == 0  # cap 0 accepts nothing


def test_old_independent_scheduler_loop_retired(monkeypatch):
    # The legacy background_services scan loop / worker-count path must be gone; the module is
    # now a thin adapter delegating to the managed SchedulerManager.
    from app.services.scheduler import background_services
    from app.services.intake import scheduler_manager
    importlib.reload(background_services)
    for legacy in ("_scan_once", "_scheduler_loop", "_run_pipeline_for_file", "_in_flight_count"):
        assert not hasattr(background_services, legacy), f"legacy scheduler symbol survived: {legacy}"
    # start_if_enabled delegates to the managed scheduler rather than running its own loop
    monkeypatch.setattr(scheduler_manager, "start_if_enabled", lambda: "DELEGATED")
    assert background_services.start_if_enabled() == "DELEGATED"
    assert isinstance(background_services.get_in_flight_count(), int)


def test_in_flight_count_starts_at_zero():
    from app.services.scheduler import background_services
    importlib.reload(background_services)
    assert background_services.get_in_flight_count() == 0
