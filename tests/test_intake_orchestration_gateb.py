"""Gate-B focused tests for the intake orchestration substrate (WO-1).

All against temporary databases — `init_db()` on a temp path applies the baseline + migration
0001. The real boh.db / app startup path is never touched.
"""

from __future__ import annotations

import os
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.services.intake import intake_writer as W
from app.services.intake import orchestrator as orch
from app.services.intake import source_revision_service as revsvc
from app.services.intake import scheduler_manager as sched
from app.services.intake.capability import initialize_capability
from app.core.planar_service_schemas import QuarantineRecord
from app.services.intake.preservation import PreservationResult


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db_path = tmp_path / "boh.db"
    data_root = tmp_path / "data"; data_root.mkdir()
    watch = tmp_path / "watch"; watch.mkdir()
    monkeypatch.setenv("BOH_DB", str(db_path))
    monkeypatch.setenv("BOH_DATA_ROOT", str(data_root))
    monkeypatch.setenv("BOH_LIBRARY", str(tmp_path / "library"))
    import app.db.connection as conn_mod
    monkeypatch.setattr(conn_mod, "DB_PATH", str(db_path))
    conn_mod.init_db()  # baseline + 0001
    return types.SimpleNamespace(conn=conn_mod, watch=watch, data_root=str(data_root), tmp=tmp_path)


def _txt(path, content="the quick brown fox jumps over the lazy dog"):
    path.write_text(content, encoding="utf-8")
    return str(path)


def _runs(conn, srid):
    return conn.fetchall("SELECT * FROM intake_runs WHERE source_revision_id=?", (srid,))


def _revs(conn, canonical):
    return conn.fetchall(
        "SELECT * FROM intake_source_revisions WHERE canonical_source_ref=?", (canonical,))


# ── B1 writer atomicity ───────────────────────────────────────────────────────────

def test_writer_stage_is_atomic_on_failure(env, monkeypatch):
    init = initialize_capability(source_ref="/x/a.md", batch_id="b")
    conn = env.conn.get_conn()
    # force the trace write (which runs AFTER the capability write) to fail
    monkeypatch.setattr(W, "_write_trace_event", lambda c, te: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        W.persist_stage_transition(conn, capability=init.capability, trace_events=[init.trace_event])
    conn.close()
    n = env.conn.fetchone(
        "SELECT COUNT(*) AS n FROM intake_capabilities WHERE intake_capability_id=?",
        (init.capability.intake_capability_id,))["n"]
    assert n == 0  # capability write rolled back with the failed trace write


# ── B1 JSONL degradation ──────────────────────────────────────────────────────────

def test_jsonl_registry_failure_does_not_fail_run(env, monkeypatch):
    import app.services.intake.preservation as pres
    monkeypatch.setattr(pres, "_append_registry",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    r = orch.execute_intake(source_ref=_txt(env.tmp / "a.txt"), batch_id="b",
                            trigger_kind="manual", data_root=env.data_root)
    assert r.outcome == "processed"  # SQLite transition stands despite JSONL failure
    assert _runs(env.conn, r.source_revision_id)[0]["lifecycle_state"] == "complete"


# ── B3 successful-path audit completeness ─────────────────────────────────────────

def test_successful_run_persists_discovery_and_preservation_traces(env):
    r = orch.execute_intake(source_ref=_txt(env.tmp / "a.txt"), batch_id="b",
                            trigger_kind="manual", data_root=env.data_root)
    assert r.outcome == "processed"
    events = {row["event_type"] for row in env.conn.fetchall(
        "SELECT event_type FROM intake_trace_events WHERE intake_capability_id=?",
        (r.intake_capability_id,))}
    assert "discovered" in events and "preserved" in events  # not only terminal state


def test_canon_eligible_false_after_success(env):
    r = orch.execute_intake(source_ref=_txt(env.tmp / "a.txt"), batch_id="b",
                            trigger_kind="manual", data_root=env.data_root)
    ce = env.conn.fetchone(
        "SELECT canon_eligible FROM intake_capabilities WHERE intake_capability_id=?",
        (r.intake_capability_id,))["canon_eligible"]
    assert ce == 0


# ── B3 preservation failure / quarantine / unexpected exception ───────────────────

def test_preservation_quarantine_is_inspectable(env, monkeypatch):
    def fake_preserve(cap, **kw):
        qr = QuarantineRecord(intake_capability_id=cap.intake_capability_id,
                              quarantine_reason="hash mismatch", quarantine_category="failed_hash")
        return PreservationResult(source_ref=cap.source_ref, success=False, capability=cap,
                                  quarantine_record=qr, failure_reason="hash mismatch")
    monkeypatch.setattr(orch, "preserve_file", fake_preserve)
    r = orch.execute_intake(source_ref=_txt(env.tmp / "a.txt"), batch_id="b",
                            trigger_kind="manual", data_root=env.data_root)
    assert r.outcome == "quarantined"
    run = _runs(env.conn, r.source_revision_id)[0]
    assert run["lifecycle_state"] == "quarantined"
    rev = env.conn.fetchone(
        "SELECT lifecycle_state FROM intake_source_revisions WHERE source_revision_id=?",
        (r.source_revision_id,))
    assert rev["lifecycle_state"] == "quarantined"
    qn = env.conn.fetchone(
        "SELECT COUNT(*) AS n FROM intake_quarantine_records WHERE intake_capability_id=?",
        (r.intake_capability_id,))["n"]
    assert qn == 1


def test_unexpected_exception_fails_closed_and_clears_lease(env, monkeypatch):
    monkeypatch.setattr(orch, "normalize",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("kaboom")))
    r = orch.execute_intake(source_ref=_txt(env.tmp / "a.txt"), batch_id="b",
                            trigger_kind="manual", data_root=env.data_root)
    assert r.outcome == "failed" and r.failure_code == "unexpected_exception"
    rev = env.conn.fetchone(
        "SELECT lifecycle_state, claim_token FROM intake_source_revisions WHERE source_revision_id=?",
        (r.source_revision_id,))
    assert rev["lifecycle_state"] == "failed" and rev["claim_token"] is None  # lease cleared
    run = _runs(env.conn, r.source_revision_id)[0]
    assert run["lifecycle_state"] == "failed" and run["failure_code"] == "unexpected_exception"


# ── manual idempotency / replay / revision identity ───────────────────────────────

def test_manual_is_idempotent_on_known_revision(env):
    p = _txt(env.tmp / "a.txt")
    r1 = orch.execute_intake(source_ref=p, batch_id="b", trigger_kind="manual", data_root=env.data_root)
    r2 = orch.execute_intake(source_ref=p, batch_id="b", trigger_kind="manual", data_root=env.data_root)
    assert r1.outcome == "processed" and r2.outcome == "already_seen"
    assert len(_runs(env.conn, r1.source_revision_id)) == 1  # no duplicate run


def test_replay_creates_one_new_run_without_minting_revision(env):
    p = _txt(env.tmp / "a.txt")
    r1 = orch.execute_intake(source_ref=p, batch_id="b", trigger_kind="manual", data_root=env.data_root)
    # strict replay begins from the stored revision id (NOT execute_intake)
    r2 = orch.replay_revision(source_revision_id=r1.source_revision_id, source_ref=p, batch_id="b",
                              data_root=env.data_root)
    assert r2.outcome == "processed" and r2.source_revision_id == r1.source_revision_id
    runs = _runs(env.conn, r1.source_revision_id)
    assert len(runs) == 2
    assert any(run["trigger_kind"] == "replay" for run in runs)
    from app.services.intake.source_revision import canonicalize_source_ref
    assert len(_revs(env.conn, canonicalize_source_ref(p))) == 1  # identity unchanged


def test_content_change_yields_new_revision_and_run(env):
    p = env.tmp / "a.txt"
    r1 = orch.execute_intake(source_ref=_txt(p, "alpha alpha alpha alpha alpha alpha"),
                             batch_id="b", trigger_kind="manual", data_root=env.data_root)
    r2 = orch.execute_intake(source_ref=_txt(p, "beta beta beta beta beta beta changed"),
                             batch_id="b", trigger_kind="manual", data_root=env.data_root)
    assert r1.source_revision_id != r2.source_revision_id
    from app.services.intake.source_revision import canonicalize_source_ref
    assert len(_revs(env.conn, canonicalize_source_ref(str(p)))) == 2


def test_timestamp_only_change_is_idempotent(env):
    p = _txt(env.tmp / "a.txt")
    orch.execute_intake(source_ref=p, batch_id="b", trigger_kind="manual", data_root=env.data_root)
    os.utime(p, None)  # touch mtime, content unchanged → same hash → same revision
    r2 = orch.execute_intake(source_ref=p, batch_id="b", trigger_kind="manual", data_root=env.data_root)
    assert r2.outcome == "already_seen"


# ── B2 reconciliation of expired leases ───────────────────────────────────────────

def test_expired_lease_reconciles_to_failed_no_autoloop(env):
    p = _txt(env.tmp / "a.txt")
    row, _ = revsvc.register_or_observe_revision(source_ref=p, source_hash_sha256="H", byte_size=1)
    srid = row["source_revision_id"]
    revsvc.try_claim_revision(srid, claimed_by="scheduler", lease_seconds=-1)  # already expired
    W_run_id = "stale-run"
    env.conn.execute(
        "INSERT INTO intake_runs (run_id, source_revision_id, source_ref_snapshot, trigger_kind, "
        "lifecycle_state, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (W_run_id, srid, p, "scheduler", "running", "t", "t"))
    reconciled = revsvc.reconcile_expired_claims()
    assert srid in reconciled
    rev = env.conn.fetchone(
        "SELECT lifecycle_state, claim_token FROM intake_source_revisions WHERE source_revision_id=?", (srid,))
    assert rev["lifecycle_state"] == "failed" and rev["claim_token"] is None
    run = env.conn.fetchone("SELECT lifecycle_state, failure_code FROM intake_runs WHERE run_id=?", (W_run_id,))
    assert run["lifecycle_state"] == "failed" and run["failure_code"] == "stale_claim_after_restart"


# ── Gate B.5 corrections: atomic replay reclaim + lease refresh ───────────────────

def test_replay_reclaim_is_atomic_scheduler_cannot_steal(env):
    p = _txt(env.tmp / "a.txt")
    r1 = orch.execute_intake(source_ref=p, batch_id="b", trigger_kind="manual", data_root=env.data_root)
    srid = r1.source_revision_id  # now 'complete'
    token = revsvc.reopen_and_claim_for_replay(srid, claimed_by="replay")
    assert token is not None  # terminal -> claimed atomically
    state = env.conn.fetchone(
        "SELECT lifecycle_state FROM intake_source_revisions WHERE source_revision_id=?", (srid,))["lifecycle_state"]
    assert state == "claimed"  # never exposed as 'discovered'
    # a racing scheduler claim cannot take a row that is already claimed
    assert revsvc.try_claim_revision(srid, claimed_by="scheduler") is None


def test_lease_refresh_only_for_owning_token(env):
    p = _txt(env.tmp / "a.txt")
    row, _ = revsvc.register_or_observe_revision(source_ref=p, source_hash_sha256="H", byte_size=1)
    srid = row["source_revision_id"]
    token = revsvc.try_claim_revision(srid, claimed_by="scheduler")
    assert revsvc.refresh_lease(srid, token) is True
    assert revsvc.refresh_lease(srid, "not-the-token") is False  # only the owner may refresh


def test_lost_lease_fails_closed_without_touching_revision(env):
    p = _txt(env.tmp / "a.txt")
    row, _ = revsvc.register_or_observe_revision(source_ref=p, source_hash_sha256="H", byte_size=1)
    srid = row["source_revision_id"]
    real_token = revsvc.try_claim_revision(srid, claimed_by="scheduler")
    # run with a token we do NOT own -> first stage-boundary refresh loses ownership
    r = orch.run_pipeline_for_claimed_revision(
        source_ref=p, batch_id="b", source_revision_id=srid, trigger_kind="scheduler",
        claim_token="WRONG", data_root=env.data_root)
    assert r.outcome == "failed" and r.failure_code == "lost_lease"
    rev = env.conn.fetchone(
        "SELECT lifecycle_state, claim_token FROM intake_source_revisions WHERE source_revision_id=?", (srid,))
    assert rev["lifecycle_state"] == "claimed" and rev["claim_token"] == real_token  # untouched


# ── safety contract: blocked/held files are metadata-only (no RAW copy) ───────────

def test_blocked_executable_is_metadata_only_and_quarantined(env):
    p = env.tmp / "blocked.exe"; p.write_bytes(b"MZ\x90\x00\x03\x00")
    r = orch.execute_intake(source_ref=str(p), batch_id="b", trigger_kind="manual", data_root=env.data_root)
    assert r.outcome == "quarantined"
    cid = r.intake_capability_id
    # NOT copied into RAW; no normalized artifact; exactly one quarantine-ledger row
    assert env.conn.fetchone("SELECT COUNT(*) AS n FROM intake_raw_artifacts WHERE intake_capability_id=?", (cid,))["n"] == 0
    assert env.conn.fetchone("SELECT COUNT(*) AS n FROM intake_normalized_artifacts n JOIN intake_raw_artifacts r ON r.raw_artifact_id=n.raw_artifact_id WHERE r.intake_capability_id=?", (cid,))["n"] == 0
    assert env.conn.fetchone("SELECT COUNT(*) AS n FROM intake_quarantine_records WHERE intake_capability_id=?", (cid,))["n"] == 1
    assert env.conn.fetchone("SELECT lifecycle_state FROM intake_source_revisions WHERE source_revision_id=?", (r.source_revision_id,))["lifecycle_state"] == "quarantined"
    assert env.conn.fetchone("SELECT canon_eligible FROM intake_capabilities WHERE intake_capability_id=?", (cid,))["canon_eligible"] == 0


def test_archive_is_metadata_only_and_quarantined(env):
    p = env.tmp / "bundle.zip"; p.write_bytes(b"PK\x03\x04\x00\x00")
    r = orch.execute_intake(source_ref=str(p), batch_id="b", trigger_kind="manual", data_root=env.data_root)
    assert r.outcome == "quarantined"
    cid = r.intake_capability_id
    assert env.conn.fetchone("SELECT COUNT(*) AS n FROM intake_raw_artifacts WHERE intake_capability_id=?", (cid,))["n"] == 0
    assert env.conn.fetchone("SELECT COUNT(*) AS n FROM intake_quarantine_records WHERE intake_capability_id=?", (cid,))["n"] == 1


def test_unsupported_type_is_metadata_only_held(env):
    p = env.tmp / "unknown.xyz"; p.write_text("some unknown content here", encoding="utf-8")
    r = orch.execute_intake(source_ref=str(p), batch_id="b", trigger_kind="manual", data_root=env.data_root)
    assert r.outcome == "held"
    cid = r.intake_capability_id
    assert env.conn.fetchone("SELECT COUNT(*) AS n FROM intake_raw_artifacts WHERE intake_capability_id=?", (cid,))["n"] == 0
    assert env.conn.fetchone("SELECT COUNT(*) AS n FROM intake_quarantine_records WHERE intake_capability_id=?", (cid,))["n"] == 0


def test_quarantined_revision_is_not_replay_eligible(env):
    p = env.tmp / "blocked.exe"; p.write_bytes(b"MZ\x90\x00")
    r = orch.execute_intake(source_ref=str(p), batch_id="b", trigger_kind="manual", data_root=env.data_root)
    assert r.outcome == "quarantined"
    # blocked content must not be re-runnable via replay
    assert revsvc.reopen_and_claim_for_replay(r.source_revision_id, claimed_by="replay") is None


# ── lease safety: token-conditioned finalize + strict refresh ─────────────────────

def test_finalize_owned_rejects_wrong_token(env):
    p = _txt(env.tmp / "a.txt")
    row, _ = revsvc.register_or_observe_revision(source_ref=p, source_hash_sha256="H", byte_size=1)
    srid = row["source_revision_id"]
    token = revsvc.try_claim_revision(srid, claimed_by="scheduler")
    conn = env.conn.get_conn()
    try:
        W.create_run(conn, run_id="r1", source_ref_snapshot=p, trigger_kind="scheduler", source_revision_id=srid)
        ru = {"run_id": "r1", "lifecycle_state": "complete"}
        assert W.finalize_owned(conn, source_revision_id=srid, claim_token="WRONG", rev_state="complete", run_update=ru) is False
        assert W.finalize_owned(conn, source_revision_id=srid, claim_token=token, rev_state="complete", run_update=ru) is True
    finally:
        conn.close()
    assert env.conn.fetchone("SELECT lifecycle_state FROM intake_source_revisions WHERE source_revision_id=?", (srid,))["lifecycle_state"] == "complete"


def test_refresh_lease_rejects_expired_lease(env):
    p = _txt(env.tmp / "a.txt")
    row, _ = revsvc.register_or_observe_revision(source_ref=p, source_hash_sha256="H", byte_size=1)
    srid = row["source_revision_id"]
    token = revsvc.try_claim_revision(srid, claimed_by="scheduler", lease_seconds=-1)  # already expired
    assert revsvc.refresh_lease(srid, token) is False  # cannot revive an expired lease


def test_reconcile_leaves_valid_lease_untouched(env):
    p = _txt(env.tmp / "a.txt")
    row, _ = revsvc.register_or_observe_revision(source_ref=p, source_hash_sha256="H", byte_size=1)
    srid = row["source_revision_id"]
    revsvc.try_claim_revision(srid, claimed_by="scheduler", lease_seconds=900)  # valid
    assert revsvc.reconcile_expired_claims() == []  # nothing expired
    assert env.conn.fetchone("SELECT lifecycle_state FROM intake_source_revisions WHERE source_revision_id=?", (srid,))["lifecycle_state"] == "claimed"


# ── B4 scheduler manager: capacity, dedup, failure handling ───────────────────────

def _arm(mgr, cap, data_root):
    mgr._max = cap
    mgr._sem = (threading.BoundedSemaphore(cap) if cap > 0 else sched._ZeroSemaphore())
    mgr._executor = ThreadPoolExecutor(max_workers=max(1, cap))
    mgr._data_root = data_root
    mgr._policy = None
    mgr._stop = threading.Event()


def test_capacity_caps_queued_plus_running(env, monkeypatch):
    monkeypatch.setattr(sched, "is_stable", lambda p: types.SimpleNamespace(stable=True))
    for i in range(6):
        _txt(env.watch / f"f{i}.txt", f"file number {i} has several words here")
    started, release = threading.Event(), threading.Event()

    def blocking(**kw):
        started.set(); release.wait(5)

    mgr = sched.SchedulerManager(pipeline_fn=blocking)
    _arm(mgr, 1, env.data_root)
    dispatched = mgr._scan_once(str(env.watch), env.data_root)
    assert started.wait(3)
    assert dispatched == 1
    st = mgr.status()
    assert st["queued_or_running"] == 1 and st["active_workers"] == 1
    release.set(); mgr._executor.shutdown(wait=True)
    assert mgr.status()["queued_or_running"] == 0


def test_cap_zero_accepts_nothing(env, monkeypatch):
    monkeypatch.setattr(sched, "is_stable", lambda p: types.SimpleNamespace(stable=True))
    _txt(env.watch / "a.txt")
    mgr = sched.SchedulerManager(pipeline_fn=lambda **kw: None)
    _arm(mgr, 0, env.data_root)
    assert mgr._scan_once(str(env.watch), env.data_root) == 0


def test_submission_failure_releases_capacity(env, monkeypatch):
    monkeypatch.setattr(sched, "is_stable", lambda p: types.SimpleNamespace(stable=True))
    _txt(env.watch / "a.txt")
    mgr = sched.SchedulerManager(pipeline_fn=lambda **kw: None)
    _arm(mgr, 1, env.data_root)

    class BadExecutor:
        def submit(self, *a, **k):
            raise RuntimeError("submit failed")
    mgr._executor = BadExecutor()
    assert mgr._scan_once(str(env.watch), env.data_root) == 0
    assert mgr.status()["queued_or_running"] == 0  # reserved slot returned


def test_worker_failure_releases_capacity(env, monkeypatch):
    monkeypatch.setattr(sched, "is_stable", lambda p: types.SimpleNamespace(stable=True))
    _txt(env.watch / "a.txt")
    mgr = sched.SchedulerManager(pipeline_fn=lambda **kw: (_ for _ in ()).throw(RuntimeError("x")))
    _arm(mgr, 1, env.data_root)
    mgr._scan_once(str(env.watch), env.data_root)
    mgr._executor.shutdown(wait=True)
    assert mgr.status()["queued_or_running"] == 0


def test_unchanged_rescan_dispatches_zero(env, monkeypatch):
    monkeypatch.setattr(sched, "is_stable", lambda p: types.SimpleNamespace(stable=True))
    _txt(env.watch / "a.txt")

    def complete(**kw):
        revsvc.complete_revision(kw["source_revision_id"])  # mark terminal like a real run

    mgr = sched.SchedulerManager(pipeline_fn=complete)
    _arm(mgr, 1, env.data_root)
    assert mgr._scan_once(str(env.watch), env.data_root) == 1
    mgr._executor.shutdown(wait=True)
    _arm(mgr, 1, env.data_root)  # fresh executor; revision now terminal
    assert mgr._scan_once(str(env.watch), env.data_root) == 0


def test_scheduler_respects_custom_ignore_patterns(env, monkeypatch):
    # A file matching a custom ignore pattern is excluded at discovery: not dispatched and never
    # registered as a source revision (no ledger row). Unset patterns leave behavior unchanged.
    monkeypatch.setattr(sched, "is_stable", lambda p: types.SimpleNamespace(stable=True))
    _txt(env.watch / "keep.md", "this document has several words and should be kept")
    (env.watch / "skip.db").write_bytes(b"generated index bytes, not source content")

    # default (no patterns) sees both candidates
    assert len(sched.scan(str(env.watch)).candidates) == 2

    mgr = sched.SchedulerManager(pipeline_fn=lambda **kw: None)
    _arm(mgr, 4, env.data_root)
    mgr._ignore = ["*.db"]
    dispatched = mgr._scan_once(str(env.watch), env.data_root)
    mgr._executor.shutdown(wait=True)
    assert dispatched == 1  # only keep.md dispatched; skip.db excluded
    assert env.conn.fetchall(
        "SELECT 1 FROM intake_source_revisions WHERE canonical_source_ref LIKE '%keep.md'") != []
    assert env.conn.fetchall(
        "SELECT 1 FROM intake_source_revisions WHERE canonical_source_ref LIKE '%skip.db'") == []


def test_env_ignore_patterns_parsing(monkeypatch):
    monkeypatch.delenv("BOH_INTAKE_IGNORE_PATTERNS", raising=False)
    assert sched._ignore_patterns() is None                       # unset → no-op
    monkeypatch.setenv("BOH_INTAKE_IGNORE_PATTERNS", "  ")
    assert sched._ignore_patterns() is None                       # blank → no-op
    monkeypatch.setenv("BOH_INTAKE_IGNORE_PATTERNS", "vault.db, *.tmp ,")
    assert sched._ignore_patterns() == ["vault.db", "*.tmp"]      # comma-split, trimmed, no empties


# ── B4 lifecycle: singleton / teardown / restart ──────────────────────────────────

@pytest.fixture()
def sched_env(env, monkeypatch):
    monkeypatch.setenv("BOH_INTAKE_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("BOH_WATCH_PATH", str(env.watch))
    monkeypatch.setenv("BOH_INTAKE_SCAN_INTERVAL", "3600")  # scan once, then idle
    return env


def test_singleton_start_is_noop(sched_env):
    mgr = sched.SchedulerManager()
    try:
        assert mgr.start_if_enabled() is True
        t1 = mgr._thread
        assert mgr.start_if_enabled() is True  # no-op while running
        assert mgr._thread is t1
    finally:
        mgr.stop()


def test_stop_then_running_false(sched_env):
    mgr = sched.SchedulerManager()
    mgr.start_if_enabled()
    assert mgr.status()["running"] is True
    mgr.stop()
    assert mgr.status()["running"] is False


def test_start_stop_start_restarts_cleanly(sched_env):
    mgr = sched.SchedulerManager()
    assert mgr.start_if_enabled() is True
    mgr.stop()
    assert mgr.start_if_enabled() is True  # fresh replacement loop
    assert mgr.status()["running"] is True
    mgr.stop()


def test_disabled_start_returns_false(env, monkeypatch):
    monkeypatch.delenv("BOH_INTAKE_SCHEDULER_ENABLED", raising=False)
    assert sched.SchedulerManager().start_if_enabled() is False


# ── delegation: all trigger kinds route through the orchestrator core ─────────────

def test_all_callers_delegate_to_orchestrator(env, monkeypatch):
    calls = []
    monkeypatch.setattr(sched, "is_stable", lambda p: types.SimpleNamespace(stable=True))

    def spy(**kw):
        calls.append(kw["trigger_kind"])
        return orch.IntakeExecutionResult("processed", kw["source_revision_id"], "r")

    # manual goes through execute_intake; strict replay goes through replay_revision; both delegate
    # to run_pipeline_for_claimed_revision.
    monkeypatch.setattr(orch, "run_pipeline_for_claimed_revision", spy)
    orch.execute_intake(source_ref=_txt(env.tmp / "m.txt"), batch_id="b",
                        trigger_kind="manual", data_root=env.data_root)
    # replay needs a terminal revision to reclaim (the spy doesn't finalize), so pre-seed one with
    # the SAME identity inputs the caller uses — including the active adapter-registry fingerprint.
    from app.services.intake.hashing import sha256_file
    from app.services.intake.adapter_registry import adapter_registry_fingerprint
    rp = _txt(env.tmp / "r.txt")
    rrow, _ = revsvc.register_or_observe_revision(
        source_ref=rp, source_hash_sha256=sha256_file(rp), byte_size=os.path.getsize(rp),
        adapter_registry_version=adapter_registry_fingerprint())
    revsvc.complete_revision(rrow["source_revision_id"])
    orch.replay_revision(source_revision_id=rrow["source_revision_id"], source_ref=rp, batch_id="b",
                         data_root=env.data_root)
    # scheduler manager calls its pipeline_fn (default = run_pipeline_for_claimed_revision)
    mgr = sched.SchedulerManager(pipeline_fn=spy)
    _arm(mgr, 1, env.data_root)
    _txt(env.watch / "s.txt")
    mgr._scan_once(str(env.watch), env.data_root)
    mgr._executor.shutdown(wait=True)
    assert set(calls) == {"manual", "replay", "scheduler"}


# ── WO-1.1 Phase A: P0 operational hardening ───────────────────────────────────────

def test_p0_preserved_bytes_match_revision_identity(env):
    """Provenance invariant on success: revision.source_hash == raw.source_hash == raw.preserved_hash."""
    src = _txt(env.watch / "bind_ok.md",
               "the quick brown fox jumps over the lazy dog with plenty of words here")
    res = orch.execute_intake(source_ref=src, batch_id="b", trigger_kind="manual",
                              data_root=env.data_root)
    assert res.outcome == "processed"
    rev = env.conn.fetchone(
        "SELECT source_hash_sha256 FROM intake_source_revisions WHERE source_revision_id=?",
        (res.source_revision_id,))
    raw = env.conn.fetchone(
        "SELECT source_hash_sha256, preserved_hash_sha256 FROM intake_raw_artifacts "
        "WHERE intake_capability_id=?", (res.intake_capability_id,))
    assert rev["source_hash_sha256"] == raw["source_hash_sha256"] == raw["preserved_hash_sha256"]


def test_p0_source_changed_between_claim_and_preservation_fails_closed(env):
    """Mutate-before-copy: the stale claimed identity fails closed with a structured code and NO RAW
    artifact; a later scan mints the correct new revision that completes."""
    from app.services.intake.hashing import sha256_file
    p = env.watch / "mutating.md"
    p.write_text("ORIGINAL content with enough words to be queryable here right now", encoding="utf-8")
    hash_a = sha256_file(str(p))
    row, _ = revsvc.register_or_observe_revision(
        source_ref=str(p), source_hash_sha256=hash_a, byte_size=os.path.getsize(str(p)))
    srid_a = row["source_revision_id"]
    token = revsvc.try_claim_revision(srid_a, claimed_by="test")
    assert token
    # mutate the file AFTER claim, BEFORE preservation copy
    p.write_text("MUTATED different content also with several words present here now", encoding="utf-8")
    res = orch.run_pipeline_for_claimed_revision(
        source_ref=str(p), batch_id="b", source_revision_id=srid_a, trigger_kind="scheduler",
        claim_token=token, data_root=env.data_root, expected_source_hash=hash_a)
    assert res.outcome == "failed"
    assert res.failure_code == "source_changed_before_preservation"
    # no RAW artifact attached to the stale identity
    assert env.conn.fetchone(
        "SELECT COUNT(*) AS n FROM intake_raw_artifacts WHERE intake_capability_id=?",
        (res.intake_capability_id,))["n"] == 0
    # the old revision is terminal-failed
    assert env.conn.fetchone(
        "SELECT lifecycle_state FROM intake_source_revisions WHERE source_revision_id=?",
        (srid_a,))["lifecycle_state"] == "failed"
    # a later scan mints the correct NEW revision for the new content and completes
    res2 = orch.execute_intake(source_ref=str(p), batch_id="b2", trigger_kind="manual",
                               data_root=env.data_root)
    assert res2.outcome == "processed"
    assert res2.source_revision_id != srid_a
    assert env.conn.fetchone(
        "SELECT preserved_hash_sha256 FROM intake_raw_artifacts WHERE intake_capability_id=?",
        (res2.intake_capability_id,))["preserved_hash_sha256"] == sha256_file(str(p))


def test_p0_validate_layout_rejects_unsafe_root_overlap(tmp_path, monkeypatch):
    """Canonical, case-folded ancestor/descendant overlap rejection for watch/data/library/DB."""
    watch = tmp_path / "watch"; watch.mkdir()
    data = tmp_path / "data"; data.mkdir()
    lib = tmp_path / "library"; lib.mkdir()
    db = tmp_path / "boh.db"; db.write_text("x", encoding="utf-8")
    monkeypatch.setenv("BOH_LIBRARY", str(lib))
    monkeypatch.setenv("BOH_DB", str(db))

    assert sched._validate_layout(str(watch), str(data)) is None          # safe topology
    assert sched._validate_layout(str(watch), str(watch / "inner")) is not None   # data inside watch
    w2 = data / "inner_watch"; w2.mkdir()
    assert sched._validate_layout(str(w2), str(data)) is not None         # watch inside data
    # trailing separator + deeper nesting still detected
    assert sched._validate_layout(str(watch) + os.sep, str(watch / "a" / "b")) is not None
    monkeypatch.setenv("BOH_LIBRARY", str(watch / "lib_inside"))
    assert sched._validate_layout(str(watch), str(data)) is not None      # library inside watch
    monkeypatch.setenv("BOH_LIBRARY", str(lib))
    # DB overlap uses the EFFECTIVE app.db.connection.DB_PATH, not BOH_DB env.
    from app.db import connection as dbc
    monkeypatch.setattr(dbc, "DB_PATH", str(watch / "inner.db"))
    assert sched._validate_layout(str(watch), str(data)) is not None      # db inside watch
    monkeypatch.setattr(dbc, "DB_PATH", str(data / "inner.db"))
    assert sched._validate_layout(str(watch), str(data)) is not None      # db inside data root
    monkeypatch.setattr(dbc, "DB_PATH", str(lib / "inner.db"))
    assert sched._validate_layout(str(watch), str(data)) is not None      # db inside library
    monkeypatch.setattr(dbc, "DB_PATH", str(db))                          # safe external db
    # library inside data (and the reverse) — full library/data pairwise overlap
    monkeypatch.setenv("BOH_LIBRARY", str(data / "lib_in_data"))
    assert sched._validate_layout(str(watch), str(data)) is not None      # library inside data root
    monkeypatch.setenv("BOH_LIBRARY", str(lib))
    f = tmp_path / "not_a_dir"; f.write_text("x", encoding="utf-8")
    assert sched._validate_layout(str(f), str(data)) is not None          # non-directory watch
    if os.name == "nt":  # case-insensitive overlap on Windows
        assert sched._validate_layout(str(watch).upper(), str(watch / "x")) is not None


def test_p0_undrained_stop_refuses_restart_and_keeps_counters_nonnegative(env, monkeypatch):
    """A drain timeout leaves state 'undrained', refuses restart until the old generation settles,
    and never lets counters go negative; once settled a clean restart is allowed."""
    monkeypatch.setattr(sched, "is_stable", lambda p: types.SimpleNamespace(stable=True))
    monkeypatch.setenv("BOH_INTAKE_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("BOH_WATCH_PATH", str(env.watch))
    monkeypatch.setenv("BOH_INTAKE_SCAN_INTERVAL", "3600")
    monkeypatch.setenv("BOH_INTAKE_BACKPRESSURE_MAX", "2")
    release, started = threading.Event(), threading.Event()

    def blocking(**kw):
        started.set(); release.wait(5)

    mgr = sched.SchedulerManager(pipeline_fn=blocking)
    _txt(env.watch / "block.md", "several words present in this document body right now")
    assert mgr.start_if_enabled() is True            # loop's first scan dispatches the blocking worker
    assert started.wait(3)
    assert mgr.status()["active_workers"] >= 1 and mgr.status()["state"] == "running"

    res = mgr.stop(drain_timeout=0.3)                # worker still blocked -> undrained
    assert res["drained"] is False and res["state"] == "undrained"
    assert mgr.start_if_enabled() is False           # restart refused while prior gen undrained
    assert mgr.status()["last_error"] == "restart_refused_prior_generation_undrained"

    release.set()                                    # let the old worker finish
    deadline = time.time() + 5
    while mgr.status()["active_workers"] > 0 and time.time() < deadline:
        time.sleep(0.05)
    st = mgr.status()
    assert st["active_workers"] == 0 and st["queued_or_running"] >= 0   # never negative

    assert mgr.start_if_enabled() is True            # old generation settled -> clean restart
    assert mgr.stop()["drained"] is True


# ── WO-1.1 Phase A addendum: ledger-authoritative binding + FS outcome + diagnostics ──

@pytest.mark.parametrize("trigger", ["scheduler", "manual", "replay"])
def test_p0_ledger_hash_binds_without_expected_arg(env, trigger):
    """All claimed paths funnel through run_pipeline_for_claimed_revision; the DURABLE ledger hash is
    authoritative, so binding holds even when the optional expected_source_hash is OMITTED."""
    from app.services.intake.hashing import sha256_file
    p = env.watch / f"omit_{trigger}.md"
    p.write_text("ORIGINAL words enough to be queryable here now okay", encoding="utf-8")
    hash_a = sha256_file(str(p))
    row, _ = revsvc.register_or_observe_revision(
        source_ref=str(p), source_hash_sha256=hash_a, byte_size=os.path.getsize(str(p)))
    srid = row["source_revision_id"]
    token = revsvc.try_claim_revision(srid, claimed_by=trigger)
    assert token
    p.write_text("MUTATED words also enough to be queryable present now okay", encoding="utf-8")
    res = orch.run_pipeline_for_claimed_revision(           # expected_source_hash OMITTED on purpose
        source_ref=str(p), batch_id="b", source_revision_id=srid, trigger_kind=trigger,
        claim_token=token, data_root=env.data_root)
    assert res.outcome == "failed"
    assert res.failure_code == "source_changed_before_preservation"


def test_p0_expected_hash_assertion_must_equal_ledger(env):
    from app.services.intake.hashing import sha256_file
    p = env.watch / "assert.md"
    p.write_text("stable content with several words here right now okay", encoding="utf-8")
    h = sha256_file(str(p))
    row, _ = revsvc.register_or_observe_revision(
        source_ref=str(p), source_hash_sha256=h, byte_size=os.path.getsize(str(p)))
    srid = row["source_revision_id"]
    token = revsvc.try_claim_revision(srid, claimed_by="t")
    res = orch.run_pipeline_for_claimed_revision(
        source_ref=str(p), batch_id="b", source_revision_id=srid, trigger_kind="scheduler",
        claim_token=token, data_root=env.data_root, expected_source_hash="deadbeef" * 8)
    assert res.outcome == "failed" and res.failure_code == "expected_hash_mismatch"


def test_p0_unloadable_claimed_revision_fails_closed(env):
    res = orch.run_pipeline_for_claimed_revision(
        source_ref=str(env.watch / "nope.md"), batch_id="b",
        source_revision_id="srid-does-not-exist", trigger_kind="scheduler",
        claim_token=None, data_root=env.data_root)
    assert res.outcome == "failed" and res.failure_code == "claimed_revision_not_found"


def test_p0_source_changed_filesystem_outcome(env):
    """Full FS + DB outcome of a stale claimed revision."""
    from app.services.intake.hashing import sha256_file
    from app.services.intake import preservation as P
    p = env.watch / "fsout.md"
    p.write_text("ORIGINAL content with enough words to be queryable here right now", encoding="utf-8")
    hash_a = sha256_file(str(p))
    row, _ = revsvc.register_or_observe_revision(
        source_ref=str(p), source_hash_sha256=hash_a, byte_size=os.path.getsize(str(p)))
    srid = row["source_revision_id"]
    token = revsvc.try_claim_revision(srid, claimed_by="t")
    p.write_text("MUTATED content also with enough words to be queryable present now", encoding="utf-8")
    res = orch.run_pipeline_for_claimed_revision(
        source_ref=str(p), batch_id="bfs", source_revision_id=srid, trigger_kind="scheduler",
        claim_token=token, data_root=env.data_root, expected_source_hash=hash_a)
    cid = res.intake_capability_id
    assert res.outcome == "failed" and res.failure_code == "source_changed_before_preservation"
    # lifecycle: run + revision both failed
    assert env.conn.fetchone(
        "SELECT lifecycle_state FROM intake_runs WHERE source_revision_id=?",
        (srid,))["lifecycle_state"] == "failed"
    assert env.conn.fetchone(
        "SELECT lifecycle_state FROM intake_source_revisions WHERE source_revision_id=?",
        (srid,))["lifecycle_state"] == "failed"
    # zero RAW + zero normalized attachments; no successful downstream
    assert env.conn.fetchone(
        "SELECT COUNT(*) AS n FROM intake_raw_artifacts WHERE intake_capability_id=?", (cid,))["n"] == 0
    assert env.conn.fetchone("SELECT COUNT(*) AS n FROM intake_normalized_artifacts")["n"] == 0
    # no misleading completion trace; the explicit failure trace is present
    events = {r["event_type"] for r in env.conn.fetchall(
        "SELECT event_type FROM intake_trace_events WHERE intake_capability_id=?", (cid,))}
    assert "source_changed_before_preservation" in events
    assert events.isdisjoint({"preserved", "normalized", "queryable", "interpreted", "handoff_ready"})
    # no ordinary untracked RAW artifact remains at the success RAW location
    files_dir = P._raw_dir(env.data_root, "bfs")
    remaining = [x.name for x in files_dir.iterdir()] if files_dir.exists() else []
    assert remaining == [], f"orphaned RAW files remain: {remaining}"
    # next scan mints the correct new revision and completes normally
    res2 = orch.execute_intake(source_ref=str(p), batch_id="bfs2", trigger_kind="manual",
                               data_root=env.data_root)
    assert res2.outcome == "processed" and res2.source_revision_id != srid


def test_p0_source_changed_registry_residue_tombstoned(env):
    """source_registry.jsonl must not retain a valid-looking record pointing at the deleted RAW
    artifact: preserve_file's success entry is explicitly tombstoned (append-only invalidation)."""
    import json
    from app.services.intake.hashing import sha256_file
    from app.services.intake import preservation as P
    p = env.watch / "resid.md"
    p.write_text("ORIGINAL content with enough words to be queryable here right now", encoding="utf-8")
    hash_a = sha256_file(str(p))
    row, _ = revsvc.register_or_observe_revision(
        source_ref=str(p), source_hash_sha256=hash_a, byte_size=os.path.getsize(str(p)))
    srid = row["source_revision_id"]
    token = revsvc.try_claim_revision(srid, claimed_by="t")
    p.write_text("MUTATED content also with enough words to be queryable present now", encoding="utf-8")
    res = orch.run_pipeline_for_claimed_revision(
        source_ref=str(p), batch_id="bres", source_revision_id=srid, trigger_kind="scheduler",
        claim_token=token, data_root=env.data_root, expected_source_hash=hash_a)
    assert res.failure_code == "source_changed_before_preservation"
    reg = P._registry_path(env.data_root, "bres")
    records = ([json.loads(line) for line in reg.read_text(encoding="utf-8").splitlines() if line.strip()]
               if reg.exists() else [])
    success_ids = {r["raw_artifact_id"] for r in records
                   if r.get("event") != "invalidated" and r.get("preservation_path")}
    tombstoned_ids = {r["raw_artifact_id"] for r in records if r.get("event") == "invalidated"}
    assert success_ids, "preserve_file should have written a success-looking registry record"
    assert success_ids <= tombstoned_ids, \
        f"untombstoned registry residue points at deleted artifact: {success_ids - tombstoned_ids}"
    # and the RAW file is gone
    files_dir = P._raw_dir(env.data_root, "bres")
    assert ([x.name for x in files_dir.iterdir()] if files_dir.exists() else []) == []


def test_p0_crash_after_tombstone_before_orphan_delete(env, monkeypatch):
    """Crash-safe ordering: if the process dies AFTER the durable tombstone but BEFORE orphan delete,
    the tombstone exists and dominates; the orphan may remain; no successful downstream state."""
    import json
    from app.services.intake.hashing import sha256_file
    from app.services.intake import preservation as P

    def boom(*a, **k):
        raise RuntimeError("crash after durable tombstone, before orphan delete")
    monkeypatch.setattr(orch, "_safe_remove_preserved", boom)

    p = env.watch / "crash.md"
    p.write_text("ORIGINAL content with enough words to be queryable here right now", encoding="utf-8")
    hash_a = sha256_file(str(p))
    row, _ = revsvc.register_or_observe_revision(
        source_ref=str(p), source_hash_sha256=hash_a, byte_size=os.path.getsize(str(p)))
    srid = row["source_revision_id"]
    token = revsvc.try_claim_revision(srid, claimed_by="t")
    p.write_text("MUTATED content also with enough words to be queryable present now", encoding="utf-8")
    res = orch.run_pipeline_for_claimed_revision(
        source_ref=str(p), batch_id="bcrash", source_revision_id=srid, trigger_kind="scheduler",
        claim_token=token, data_root=env.data_root, expected_source_hash=hash_a)
    cid = res.intake_capability_id
    assert res.outcome == "failed"
    assert env.conn.fetchone(
        "SELECT lifecycle_state FROM intake_source_revisions WHERE source_revision_id=?",
        (srid,))["lifecycle_state"] == "failed"
    # durable tombstone exists and dominates the success-looking record
    reg = P._registry_path(env.data_root, "bcrash")
    records = ([json.loads(line) for line in reg.read_text(encoding="utf-8").splitlines() if line.strip()]
               if reg.exists() else [])
    success_ids = {r["raw_artifact_id"] for r in records
                   if r.get("event") != "invalidated" and r.get("preservation_path")}
    tombstoned_ids = {r["raw_artifact_id"] for r in records if r.get("event") == "invalidated"}
    assert success_ids and success_ids <= tombstoned_ids
    # orphan MAY remain (delete was crashed out) -> proves the tombstone preceded the delete
    files_dir = P._raw_dir(env.data_root, "bcrash")
    assert files_dir.exists() and len(list(files_dir.iterdir())) >= 1
    # zero RAW DB attachments; zero normalized; no successful downstream trace
    assert env.conn.fetchone(
        "SELECT COUNT(*) AS n FROM intake_raw_artifacts WHERE intake_capability_id=?", (cid,))["n"] == 0
    assert env.conn.fetchone("SELECT COUNT(*) AS n FROM intake_normalized_artifacts")["n"] == 0
    events = {r["event_type"] for r in env.conn.fetchall(
        "SELECT event_type FROM intake_trace_events WHERE intake_capability_id=?", (cid,))}
    assert events.isdisjoint({"preserved", "normalized", "queryable", "interpreted", "handoff_ready"})


def test_p0_tombstone_failure_retains_orphan(env, monkeypatch):
    """If the tombstone append is not durable, the orphan is NOT deleted and the run fails closed
    with registry_invalidation_failed; no successful downstream state exists."""
    from app.services.intake.hashing import sha256_file
    from app.services.intake import preservation as P
    monkeypatch.setattr(orch, "invalidate_registry_entry", lambda *a, **k: False)
    p = env.watch / "tfail.md"
    p.write_text("ORIGINAL content with enough words to be queryable here right now", encoding="utf-8")
    hash_a = sha256_file(str(p))
    row, _ = revsvc.register_or_observe_revision(
        source_ref=str(p), source_hash_sha256=hash_a, byte_size=os.path.getsize(str(p)))
    srid = row["source_revision_id"]
    token = revsvc.try_claim_revision(srid, claimed_by="t")
    p.write_text("MUTATED content also with enough words to be queryable present now", encoding="utf-8")
    res = orch.run_pipeline_for_claimed_revision(
        source_ref=str(p), batch_id="btfail", source_revision_id=srid, trigger_kind="scheduler",
        claim_token=token, data_root=env.data_root, expected_source_hash=hash_a)
    cid = res.intake_capability_id
    assert res.outcome == "failed" and res.failure_code == "registry_invalidation_failed"
    files_dir = P._raw_dir(env.data_root, "btfail")
    assert files_dir.exists() and len(list(files_dir.iterdir())) >= 1   # orphan retained
    assert env.conn.fetchone(
        "SELECT COUNT(*) AS n FROM intake_raw_artifacts WHERE intake_capability_id=?", (cid,))["n"] == 0
    assert env.conn.fetchone("SELECT COUNT(*) AS n FROM intake_normalized_artifacts")["n"] == 0
    assert env.conn.fetchone(
        "SELECT lifecycle_state FROM intake_runs WHERE source_revision_id=?",
        (srid,))["lifecycle_state"] == "failed"


def test_p0_registry_appends_serialized_under_concurrency(tmp_path):
    """Parallel success + invalidation appends to one registry produce valid, parseable JSONL with
    intact raw_artifact_id values (single-writer discipline, no interleaving)."""
    import json
    import threading as _t
    from app.services.intake import preservation as P
    from app.core.planar_service_schemas import RawArtifact
    data_root = str(tmp_path)
    batch = "concur"
    raws = [RawArtifact(intake_capability_id=f"cap{i}", source_ref=f"/s/{i}", batch_id=batch,
                        source_hash_sha256=("%064x" % i), preserved_hash_sha256=("%064x" % i),
                        byte_size=1, preservation_path=f"p/{i}") for i in range(40)]

    def work(r):
        P._append_registry(data_root, batch, r)
        P.invalidate_registry_entry(data_root, batch, r, "concurrency-test")

    threads = [_t.Thread(target=work, args=(r,)) for r in raws]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    reg = P._registry_path(data_root, batch)
    lines = [line for line in reg.read_text(encoding="utf-8").splitlines() if line.strip()]
    parsed = [json.loads(line) for line in lines]   # raises if any line interleaved/corrupt
    assert len(parsed) == 80                          # 40 success + 40 invalidation
    assert all(r.get("raw_artifact_id") for r in parsed)
    assert {r["raw_artifact_id"] for r in parsed} == {r.raw_artifact_id for r in raws}


def test_p0_accounting_underflow_records_diagnostic():
    """An attempted counter underflow is recorded as a structured error diagnostic, not silently
    hidden by the clamp."""
    mgr = sched.SchedulerManager()
    mgr._accepted = 0
    mgr._dec_accepted()
    assert mgr._accepted == 0
    assert mgr.status()["last_error"] == "accounting_underflow:accepted"
    mgr._dec_active(99)  # no such generation -> underflow diagnostic
    assert mgr.status()["last_error"] == "accounting_underflow:active"
    assert mgr._active_total() == 0


# ── WO-1.1 Phase B (item 1): deterministic adapter-registry fingerprint ─────────────

def test_p1_adapter_fingerprint_deterministic_and_startup_stable():
    from app.services.intake.adapter_registry import (
        AdapterRegistry, adapter_registry_fingerprint, get_registry)
    fp = adapter_registry_fingerprint(get_registry())
    assert fp.startswith("adapterfp-v1:")
    assert adapter_registry_fingerprint() == fp                 # repeated call stable
    assert adapter_registry_fingerprint(AdapterRegistry()) == fp  # fresh instance ~ new process startup


def test_p1_adapter_fingerprint_independent_of_registration_order():
    from app.services.intake.adapter_registry import _fingerprint_from, get_registry
    reg = get_registry()
    adapters = reg.all_adapters()
    assert (_fingerprint_from(adapters, reg._by_ext, reg._by_media)
            == _fingerprint_from(list(reversed(adapters)), reg._by_ext, reg._by_media))


def test_p1_adapter_fingerprint_changes_on_contract_change():
    import dataclasses
    from app.services.intake.adapter_registry import _fingerprint_from, get_registry
    reg = get_registry()
    adapters = reg.all_adapters()
    base = _fingerprint_from(adapters, reg._by_ext, reg._by_media)
    mutated = ([dataclasses.replace(adapters[0], adapter_version=adapters[0].adapter_version + ".x")]
               + adapters[1:])
    assert _fingerprint_from(mutated, reg._by_ext, reg._by_media) != base


def test_p1_adapter_fingerprint_in_identity_and_stored_by_callers(env):
    from app.services.intake import source_revision_service as rs
    from app.services.intake.adapter_registry import adapter_registry_fingerprint
    # identity reacts to the adapter fingerprint (same bytes/path/policy, different contract -> new id)
    a = rs.revision_identity(source_ref="/x/a.md", source_hash_sha256="H", adapter_registry_version="fp-A")
    b = rs.revision_identity(source_ref="/x/a.md", source_hash_sha256="H", adapter_registry_version="fp-B")
    assert a["source_revision_id"] != b["source_revision_id"]
    # manual/replay (execute_intake) stamps the REAL fingerprint into the stored revision row
    fp = adapter_registry_fingerprint()
    src = _txt(env.watch / "fp.md", "a document with several words for the fingerprint test here now")
    res = orch.execute_intake(source_ref=src, batch_id="b", trigger_kind="manual", data_root=env.data_root)
    assert res.outcome == "processed"
    assert env.conn.fetchone(
        "SELECT adapter_registry_version FROM intake_source_revisions WHERE source_revision_id=?",
        (res.source_revision_id,))["adapter_registry_version"] == fp


def test_p1_adapter_contract_change_mints_new_revision_same_bytes(env, monkeypatch):
    import app.services.intake.orchestrator as O
    src = _txt(env.watch / "same.md", "identical bytes document with several words present here now")
    res1 = O.execute_intake(source_ref=src, batch_id="b1", trigger_kind="manual", data_root=env.data_root)
    assert res1.outcome == "processed"
    # simulate a transformation-contract change: only the adapter fingerprint differs
    monkeypatch.setattr(O, "adapter_registry_fingerprint", lambda *a, **k: "adapterfp-v1:CHANGED")
    res2 = O.execute_intake(source_ref=src, batch_id="b2", trigger_kind="manual", data_root=env.data_root)
    assert res2.outcome == "processed"
    assert res2.source_revision_id != res1.source_revision_id   # new identity, unchanged source bytes


def test_p1_scheduler_stamps_adapter_fingerprint(env, monkeypatch):
    from app.services.intake.adapter_registry import adapter_registry_fingerprint
    from app.services.intake.source_revision import canonicalize_source_ref
    monkeypatch.setattr(sched, "is_stable", lambda p: types.SimpleNamespace(stable=True))
    _txt(env.watch / "s1.md", "scheduler fingerprint document with several words present here now")
    mgr = sched.SchedulerManager(pipeline_fn=lambda **kw: None)
    _arm(mgr, 2, env.data_root)
    mgr._adapter_fp = adapter_registry_fingerprint()   # start_if_enabled binds this; set it for _arm
    mgr._scan_once(str(env.watch), env.data_root)
    mgr._executor.shutdown(wait=True)
    wpref = canonicalize_source_ref(str(env.watch))
    row = env.conn.fetchone(
        "SELECT adapter_registry_version FROM intake_source_revisions WHERE canonical_source_ref LIKE ?",
        (wpref + "%",))
    assert row["adapter_registry_version"] == adapter_registry_fingerprint()


# ── WO-1.1 Phase B (item 2): policy binding + replay vs reprocess ────────────────────

def _count(conn, table):
    return conn.fetchone(f"SELECT COUNT(*) AS n FROM {table}")["n"]


def test_p2_scheduler_and_manual_same_identity_same_contract(env, monkeypatch):
    from app.services.intake import source_revision_service as rs
    from app.services.intake.adapter_registry import adapter_registry_fingerprint
    from app.services.intake.hashing import sha256_file
    monkeypatch.setenv("BOH_INTAKE_POLICY_SNAPSHOT_BIND", "POLICY-CONSISTENT")
    src = _txt(env.watch / "consistent.md", "consistency document with several words present right now ok")
    res = orch.execute_intake(source_ref=str(src), batch_id="m", trigger_kind="manual",
                              data_root=env.data_root)
    fp = adapter_registry_fingerprint()
    # the scheduler computes identity from the SAME active contract pair (policy + fingerprint)
    sched_ident = rs.revision_identity(source_ref=str(src), source_hash_sha256=sha256_file(str(src)),
                                       policy_snapshot_hash="POLICY-CONSISTENT", adapter_registry_version=fp)
    assert sched_ident["source_revision_id"] == res.source_revision_id
    rowv = env.conn.fetchone(
        "SELECT policy_snapshot_hash, adapter_registry_version FROM intake_source_revisions "
        "WHERE source_revision_id=?", (res.source_revision_id,))
    assert rowv["policy_snapshot_hash"] == "POLICY-CONSISTENT" and rowv["adapter_registry_version"] == fp


def test_p2_replay_matching_contract_reclaims_same_revision_no_new_row(env):
    from app.services.intake import replay
    src = _txt(env.watch / "rep.md", "a replayable document with several words present here right now ok")
    res1 = orch.execute_intake(source_ref=str(src), batch_id="b", trigger_kind="manual",
                               data_root=env.data_root)
    assert res1.outcome == "processed"
    before = _count(env.conn, "intake_source_revisions")
    rr = replay.reprocess(res1.intake_capability_id, data_root=env.data_root)
    assert rr.success
    assert _count(env.conn, "intake_source_revisions") == before   # no new revision row
    run = env.conn.fetchone(
        "SELECT source_revision_id FROM intake_runs WHERE trigger_kind='replay' "
        "ORDER BY created_at DESC LIMIT 1")
    assert run["source_revision_id"] == res1.source_revision_id   # reclaimed the SAME identity


def test_p2_replay_after_adapter_change_fails_closed_no_row(env, monkeypatch):
    from app.services.intake import replay
    import app.services.intake.orchestrator as O
    src = _txt(env.watch / "rep2.md", "document for adapter-change replay test with several words now ok")
    res1 = O.execute_intake(source_ref=str(src), batch_id="b", trigger_kind="manual", data_root=env.data_root)
    assert res1.outcome == "processed"
    rev_before, run_before = _count(env.conn, "intake_source_revisions"), _count(env.conn, "intake_runs")
    monkeypatch.setattr(O, "adapter_registry_fingerprint", lambda *a, **k: "adapterfp-v1:DIFFERENT")
    rr = replay.reprocess(res1.intake_capability_id, data_root=env.data_root)
    assert not rr.success and rr.stage_reached == "replay_adapter_contract_unavailable"
    assert _count(env.conn, "intake_source_revisions") == rev_before
    assert _count(env.conn, "intake_runs") == run_before          # no new run row either


def test_p2_replay_after_policy_change_fails_closed_no_row(env, monkeypatch):
    from app.services.intake import replay
    monkeypatch.setenv("BOH_INTAKE_POLICY_SNAPSHOT_BIND", "POLICY-ORIG")
    src = _txt(env.watch / "rep3.md", "document for policy-change replay test with several words now ok")
    res1 = orch.execute_intake(source_ref=str(src), batch_id="b", trigger_kind="manual", data_root=env.data_root)
    assert res1.outcome == "processed"
    before = _count(env.conn, "intake_source_revisions")
    monkeypatch.setenv("BOH_INTAKE_POLICY_SNAPSHOT_BIND", "POLICY-NEW")
    rr = replay.reprocess(res1.intake_capability_id, data_root=env.data_root)
    assert not rr.success and rr.stage_reached == "replay_policy_contract_unavailable"
    assert _count(env.conn, "intake_source_revisions") == before


def test_p2_sentinel_era_replay_fails_closed(env):
    from app.services.intake.hashing import sha256_file
    src = _txt(env.watch / "sent.md", "sentinel-era document with several words present here right now ok")
    h = sha256_file(str(src))
    # register the OLD way (no adapter fingerprint -> sentinel adapter_registry_version)
    row, _ = revsvc.register_or_observe_revision(
        source_ref=str(src), source_hash_sha256=h, byte_size=os.path.getsize(str(src)))
    revsvc.complete_revision(row["source_revision_id"])
    before = _count(env.conn, "intake_source_revisions")
    res = orch.replay_revision(source_revision_id=row["source_revision_id"], source_ref=str(src),
                               batch_id="b", data_root=env.data_root)
    assert res.outcome == "failed" and res.failure_code == "replay_adapter_contract_unavailable"
    assert _count(env.conn, "intake_source_revisions") == before


def test_p2_reprocess_under_changed_adapter_mints_new_identity(env, monkeypatch):
    from app.services.intake import replay
    import app.services.intake.orchestrator as O
    src = _txt(env.watch / "rp_a.md", "reprocess adapter document with several words present here now ok")
    res1 = O.execute_intake(source_ref=str(src), batch_id="b", trigger_kind="manual", data_root=env.data_root)
    assert res1.outcome == "processed"
    monkeypatch.setattr(O, "adapter_registry_fingerprint", lambda *a, **k: "adapterfp-v1:NEWCONTRACT")
    rr = replay.reprocess_under_current_contract(res1.intake_capability_id, data_root=env.data_root)
    assert rr.success
    new_run = env.conn.fetchone(
        "SELECT source_revision_id FROM intake_runs WHERE source_revision_id != ? "
        "ORDER BY created_at DESC LIMIT 1", (res1.source_revision_id,))
    assert new_run and new_run["source_revision_id"] != res1.source_revision_id   # new identity
    link = env.conn.fetchone(
        "SELECT detail_json FROM intake_trace_events WHERE event_type='reprocessed_from' "
        "ORDER BY created_at DESC LIMIT 1")
    assert link is not None and res1.source_revision_id in link["detail_json"]   # prior->new link


def test_p2_reprocess_under_changed_policy_mints_new_identity(env, monkeypatch):
    from app.services.intake import replay
    monkeypatch.setenv("BOH_INTAKE_POLICY_SNAPSHOT_BIND", "POL-A")
    src = _txt(env.watch / "rp_p.md", "reprocess policy document with several words present here now ok")
    res1 = orch.execute_intake(source_ref=str(src), batch_id="b", trigger_kind="manual", data_root=env.data_root)
    assert res1.outcome == "processed"
    monkeypatch.setenv("BOH_INTAKE_POLICY_SNAPSHOT_BIND", "POL-B")
    rr = replay.reprocess_under_current_contract(res1.intake_capability_id, data_root=env.data_root)
    assert rr.success
    assert env.conn.fetchone(
        "SELECT COUNT(*) AS n FROM intake_source_revisions WHERE source_revision_id != ?",
        (res1.source_revision_id,))["n"] >= 1


def test_p2_scheduler_generation_binds_contract_at_start_and_rebinds_next_generation(env, monkeypatch):
    monkeypatch.setenv("BOH_INTAKE_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("BOH_WATCH_PATH", str(env.watch))
    monkeypatch.setenv("BOH_INTAKE_SCAN_INTERVAL", "3600")
    monkeypatch.setattr(sched, "adapter_registry_fingerprint", lambda *a, **k: "adapterfp-v1:FP-A")
    monkeypatch.setenv("BOH_INTAKE_POLICY_SNAPSHOT_BIND", "POLICY-A")
    mgr = sched.SchedulerManager()
    assert mgr.start_if_enabled()
    assert mgr._adapter_fp == "adapterfp-v1:FP-A" and mgr._policy == "POLICY-A"
    # a runtime config change does NOT rebind the live generation
    monkeypatch.setattr(sched, "adapter_registry_fingerprint", lambda *a, **k: "adapterfp-v1:FP-B")
    monkeypatch.setenv("BOH_INTAKE_POLICY_SNAPSHOT_BIND", "POLICY-B")
    assert mgr._adapter_fp == "adapterfp-v1:FP-A" and mgr._policy == "POLICY-A"
    assert mgr.stop()["stopped"]
    # a NEW generation binds the updated contract
    assert mgr.start_if_enabled()
    assert mgr._adapter_fp == "adapterfp-v1:FP-B" and mgr._policy == "POLICY-B"
    mgr.stop()


# ── WO-1.1 Phase B (item 3): scheduler status surface ───────────────────────────────

_STATUS_FIELDS = ("running", "enabled", "state", "generation", "watch_path",
                  "data_root_configured", "queued_or_running", "active_workers", "drained",
                  "last_scan_ts", "last_error", "restart_refusal_reason")


def test_p3_status_exposes_all_required_fields_disabled():
    st = sched.SchedulerManager().status()
    for k in _STATUS_FIELDS:
        assert k in st, f"missing status field: {k}"
    assert st["state"] == "disabled" and st["running"] is False and st["generation"] == 0
    assert st["drained"] is True and st["restart_refusal_reason"] is None


def test_p3_status_state_transitions_running_then_stopped(env, monkeypatch):
    monkeypatch.setenv("BOH_INTAKE_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("BOH_WATCH_PATH", str(env.watch))
    monkeypatch.setenv("BOH_INTAKE_SCAN_INTERVAL", "3600")
    mgr = sched.SchedulerManager()
    assert mgr.start_if_enabled()
    st = mgr.status()
    assert st["state"] == "running" and st["running"] is True and st["generation"] == 1
    assert st["watch_path"] == str(env.watch) and st["data_root_configured"] is True
    mgr.stop()
    assert mgr.status()["state"] == "stopped" and mgr.status()["running"] is False


def test_p3_restart_refusal_reason_surfaced(env, monkeypatch):
    monkeypatch.setenv("BOH_INTAKE_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("BOH_WATCH_PATH", str(env.watch))
    mgr = sched.SchedulerManager()
    mgr._state = "undrained"; mgr._active_by_gen = {1: 1}   # a prior generation still in flight
    assert mgr.start_if_enabled() is False
    assert mgr.status()["restart_refusal_reason"] == "restart_refused_prior_generation_undrained"
    assert mgr.status()["state"] == "undrained"


# ── WO-1.1 Phase B (item 4): fail-closed config validation ──────────────────────────

def _enable_env(env, monkeypatch):
    monkeypatch.setenv("BOH_INTAKE_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("BOH_WATCH_PATH", str(env.watch))


@pytest.mark.parametrize("val", ["0", "-1", "abc", "999999999"])
def test_p4_invalid_scan_interval_fails_closed(env, monkeypatch, val):
    _enable_env(env, monkeypatch)
    monkeypatch.setenv("BOH_INTAKE_SCAN_INTERVAL", val)
    mgr = sched.SchedulerManager()
    assert mgr.start_if_enabled() is False
    st = mgr.status()
    assert st["state"] == "error"
    assert st["last_error"].startswith("config_invalid:BOH_INTAKE_SCAN_INTERVAL")


@pytest.mark.parametrize("val", ["0", "-1", "abc", "99999"])
def test_p4_invalid_capacity_fails_closed(env, monkeypatch, val):
    _enable_env(env, monkeypatch)
    monkeypatch.setenv("BOH_INTAKE_BACKPRESSURE_MAX", val)
    mgr = sched.SchedulerManager()
    assert mgr.start_if_enabled() is False
    assert mgr.status()["last_error"].startswith("config_invalid:BOH_INTAKE_BACKPRESSURE_MAX")


@pytest.mark.parametrize("val", ["0", "-1", "abc", "99999"])
def test_p4_invalid_drain_timeout_fails_closed(env, monkeypatch, val):
    _enable_env(env, monkeypatch)
    monkeypatch.setenv("BOH_INTAKE_DRAIN_TIMEOUT", val)
    mgr = sched.SchedulerManager()
    assert mgr.start_if_enabled() is False
    assert mgr.status()["last_error"].startswith("config_invalid:BOH_INTAKE_DRAIN_TIMEOUT")


def test_p4_malformed_ignore_patterns_fails_closed(env, monkeypatch):
    _enable_env(env, monkeypatch)
    monkeypatch.setenv("BOH_INTAKE_IGNORE_PATTERNS", ", , ,")   # set but no real patterns
    mgr = sched.SchedulerManager()
    assert mgr.start_if_enabled() is False
    assert mgr.status()["last_error"] == "config_invalid:BOH_INTAKE_IGNORE_PATTERNS:no_valid_patterns"


def test_p4_nondeterministic_adapter_fingerprint_fails_closed(env, monkeypatch):
    import itertools
    _enable_env(env, monkeypatch)
    seq = itertools.count()
    monkeypatch.setattr(sched, "adapter_registry_fingerprint",
                        lambda *a, **k: f"adapterfp-v1:{next(seq)}")
    mgr = sched.SchedulerManager()
    assert mgr.start_if_enabled() is False
    assert mgr.status()["last_error"] == "config_adapter_fingerprint_nondeterministic"


def test_p4_uncreatable_data_root_fails_closed(env, monkeypatch):
    f = env.tmp / "a_plain_file"; f.write_text("x", encoding="utf-8")
    monkeypatch.setenv("BOH_INTAKE_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("BOH_WATCH_PATH", str(env.watch))
    monkeypatch.setenv("BOH_DATA_ROOT", str(f / "sub"))        # parent is a file -> uncreatable
    mgr = sched.SchedulerManager()
    assert mgr.start_if_enabled() is False
    st = mgr.status()
    assert st["state"] == "error" and "data_root" in st["last_error"]


# ── WO-1.1 Phase B closure addendum ─────────────────────────────────────────────────

def test_cl1_module_stop_wrapper_passes_none_and_override(monkeypatch):
    """Module-level stop() forwards None (manager uses validated timeout); a numeric override wins."""
    seen = []
    monkeypatch.setattr(sched._MANAGER, "stop",
                        lambda drain_timeout=None: (seen.append(drain_timeout), {"stopped": True})[1])
    sched.stop()
    sched.stop(drain_timeout=2.5)
    assert seen == [None, 2.5]


def test_cl1_background_services_stop_wrapper_passes_none(monkeypatch):
    from app.services.scheduler import background_services as bg
    seen = []
    monkeypatch.setattr(sched._MANAGER, "stop",
                        lambda drain_timeout=None: (seen.append(drain_timeout), {"stopped": True})[1])
    bg.stop()
    assert seen == [None]


def test_cl1_validated_drain_timeout_bound_on_start(env, monkeypatch):
    monkeypatch.setenv("BOH_INTAKE_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("BOH_WATCH_PATH", str(env.watch))
    monkeypatch.setenv("BOH_INTAKE_DRAIN_TIMEOUT", "12")
    mgr = sched.SchedulerManager()
    assert mgr.start_if_enabled()
    assert mgr._drain_timeout == 12.0
    mgr.stop()


def test_cl2_missing_watch_path_structured_error(env, monkeypatch):
    monkeypatch.setenv("BOH_INTAKE_SCHEDULER_ENABLED", "true")
    monkeypatch.delenv("BOH_WATCH_PATH", raising=False)
    mgr = sched.SchedulerManager()
    assert mgr.start_if_enabled() is False
    assert mgr.status()["state"] == "error"
    assert mgr.status()["last_error"] == "config_missing:BOH_WATCH_PATH"


def test_cl2_missing_data_root_structured_error(env, monkeypatch):
    monkeypatch.setenv("BOH_INTAKE_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("BOH_WATCH_PATH", str(env.watch))
    monkeypatch.delenv("BOH_DATA_ROOT", raising=False)
    mgr = sched.SchedulerManager()
    assert mgr.start_if_enabled() is False
    assert mgr.status()["state"] == "error"
    assert mgr.status()["last_error"] == "config_missing:BOH_DATA_ROOT"


def test_cl2_disabled_missing_roots_stays_inert(env, monkeypatch):
    monkeypatch.delenv("BOH_INTAKE_SCHEDULER_ENABLED", raising=False)
    monkeypatch.delenv("BOH_WATCH_PATH", raising=False)
    monkeypatch.delenv("BOH_DATA_ROOT", raising=False)
    mgr = sched.SchedulerManager()
    assert mgr.start_if_enabled() is False
    assert mgr.status()["state"] == "disabled" and mgr.status()["last_error"] is None


@pytest.mark.parametrize("val", ["nan", "inf", "-inf"])
def test_cl3_non_finite_drain_timeout_fails_closed(env, monkeypatch, val):
    monkeypatch.setenv("BOH_INTAKE_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("BOH_WATCH_PATH", str(env.watch))
    monkeypatch.setenv("BOH_INTAKE_DRAIN_TIMEOUT", val)
    mgr = sched.SchedulerManager()
    assert mgr.start_if_enabled() is False
    assert mgr.status()["last_error"].startswith("config_invalid:BOH_INTAKE_DRAIN_TIMEOUT:not_finite")


def test_cl4_writability_probe_preserves_existing_fixed_name_file(env):
    victim = os.path.join(env.data_root, ".boh_intake_write_probe")
    with open(victim, "w", encoding="utf-8") as f:
        f.write("USER DATA")
    assert sched._validate_layout(str(env.watch), env.data_root) is None
    with open(victim, encoding="utf-8") as f:
        assert f.read() == "USER DATA"                         # byte-identical, untouched
    leftovers = sorted(n for n in os.listdir(env.data_root)
                       if n.startswith(".boh_intake_write_probe"))
    assert leftovers == [".boh_intake_write_probe"]            # only the user file; no orphan probe


def test_cl5_effective_db_inside_each_root_rejected(env, monkeypatch):
    from app.db import connection as dbc
    monkeypatch.setattr(dbc, "DB_PATH", str(env.watch / "inner.db"))
    assert "db_inside_watch" in sched._validate_layout(str(env.watch), env.data_root)
    monkeypatch.setattr(dbc, "DB_PATH", os.path.join(env.data_root, "inner.db"))
    assert "db_inside_data_root" in sched._validate_layout(str(env.watch), env.data_root)
    lib = str(env.tmp / "library")
    monkeypatch.setenv("BOH_LIBRARY", lib)
    monkeypatch.setattr(dbc, "DB_PATH", os.path.join(lib, "inner.db"))
    assert "db_inside_library" in sched._validate_layout(str(env.watch), env.data_root)


def test_cl5_default_relative_db_inside_watch_rejected(env, monkeypatch):
    from app.db import connection as dbc
    monkeypatch.chdir(env.watch)               # cwd inside the watched tree
    monkeypatch.setattr(dbc, "DB_PATH", "boh.db")   # effective default, relative to cwd
    assert "db_inside_watch" in sched._validate_layout(str(env.watch), env.data_root)


def test_cl5_safe_external_db_accepted(env, monkeypatch):
    from app.db import connection as dbc
    monkeypatch.setattr(dbc, "DB_PATH", str(env.tmp / "boh.db"))   # sibling, outside all roots
    monkeypatch.setenv("BOH_LIBRARY", str(env.tmp / "library"))
    assert sched._validate_layout(str(env.watch), env.data_root) is None


def test_cl6_generation_binds_validated_fingerprint_not_later_read(env, monkeypatch):
    monkeypatch.setenv("BOH_INTAKE_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("BOH_WATCH_PATH", str(env.watch))
    vals = iter(["adapterfp-v1:A", "adapterfp-v1:A", "adapterfp-v1:B", "adapterfp-v1:B"])
    monkeypatch.setattr(sched, "adapter_registry_fingerprint", lambda *a, **k: next(vals))
    mgr = sched.SchedulerManager()
    assert mgr.start_if_enabled()
    assert mgr._adapter_fp == "adapterfp-v1:A"   # the validated value, not a later read
    mgr.stop()


def test_cl6_generation_binds_validated_policy_not_later_read(env, monkeypatch):
    monkeypatch.setenv("BOH_INTAKE_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("BOH_WATCH_PATH", str(env.watch))
    vals = iter(["POL-A", "POL-A", "POL-B", "POL-B"])
    monkeypatch.setattr(sched, "_policy_bind", lambda: next(vals))
    mgr = sched.SchedulerManager()
    assert mgr.start_if_enabled()
    assert mgr._policy == "POL-A"                 # the validated value, not a later read
    mgr.stop()


def test_cl7_execute_intake_replay_forbidden_no_row(env):
    p = _txt(env.watch / "noreplay.md", "several words present in this document body right now ok")
    before_rev = _count(env.conn, "intake_source_revisions")
    before_run = _count(env.conn, "intake_runs")
    res = orch.execute_intake(source_ref=str(p), batch_id="b", trigger_kind="replay",
                              data_root=env.data_root)
    assert res.outcome == "failed" and res.failure_code == "replay_via_execute_intake_forbidden"
    assert _count(env.conn, "intake_source_revisions") == before_rev   # no new identity minted
    assert _count(env.conn, "intake_runs") == before_run
    assert env.conn.fetchone(
        "SELECT COUNT(*) AS n FROM intake_source_revisions WHERE lifecycle_state='discovered'")["n"] == 0


def test_cl8_replay_source_ref_mismatch_fails_closed_no_row(env):
    pa = _txt(env.watch / "pathA.md", "identical bytes document with several words present here ok now")
    r1 = orch.execute_intake(source_ref=str(pa), batch_id="b", trigger_kind="manual", data_root=env.data_root)
    assert r1.outcome == "processed"
    pb = _txt(env.watch / "pathB.md", "identical bytes document with several words present here ok now")
    rev_before, run_before = _count(env.conn, "intake_source_revisions"), _count(env.conn, "intake_runs")
    res = orch.replay_revision(source_revision_id=r1.source_revision_id, source_ref=str(pb),
                               batch_id="b", data_root=env.data_root)
    assert res.outcome == "failed" and res.failure_code == "replay_source_ref_mismatch"
    assert _count(env.conn, "intake_source_revisions") == rev_before
    assert _count(env.conn, "intake_runs") == run_before


def test_cl8_replay_from_original_path_succeeds(env):
    pa = _txt(env.watch / "orig.md", "replayable doc with several words present here right now ok")
    r1 = orch.execute_intake(source_ref=str(pa), batch_id="b", trigger_kind="manual", data_root=env.data_root)
    res = orch.replay_revision(source_revision_id=r1.source_revision_id, source_ref=str(pa),
                               batch_id="b", data_root=env.data_root)
    assert res.outcome == "processed" and res.source_revision_id == r1.source_revision_id


def test_cl10_preservation_copy_failure_leaves_no_orphan(env, monkeypatch):
    from app.services.intake import preservation as P
    from app.services.intake.capability import initialize_capability
    src = _txt(env.watch / "p10a.md", "doc with several words for preservation copy-fail test ok now")
    cap = initialize_capability(source_ref=str(src), batch_id="b10a").capability

    def bad_copy(s, d):
        with open(d, "w", encoding="utf-8") as f:
            f.write("partial")          # leave a partial dest, then raise
        raise OSError("copy boom")
    monkeypatch.setattr(P.shutil, "copy2", bad_copy)
    res = P.preserve_file(cap, data_root=str(env.data_root))
    assert res.success is False
    files_dir = P._raw_dir(str(env.data_root), "b10a")
    assert ([x.name for x in files_dir.iterdir()] if files_dir.exists() else []) == []   # no orphan


def test_cl10_preservation_hash_failure_leaves_no_orphan(env, monkeypatch):
    from app.services.intake import preservation as P
    from app.services.intake.capability import initialize_capability
    src = _txt(env.watch / "p10b.md", "doc with several words for preservation hash-fail test ok now")
    cap = initialize_capability(source_ref=str(src), batch_id="b10b").capability
    real = P.sha256_file

    def flaky(path):                     # source hash ok; preserved-copy (01_RAW) hash raises
        if "01_RAW" in str(path).replace("\\", "/"):
            raise OSError("hash boom")
        return real(path)
    monkeypatch.setattr(P, "sha256_file", flaky)
    res = P.preserve_file(cap, data_root=str(env.data_root))
    assert res.success is False
    files_dir = P._raw_dir(str(env.data_root), "b10b")
    assert ([x.name for x in files_dir.iterdir()] if files_dir.exists() else []) == []   # no orphan
