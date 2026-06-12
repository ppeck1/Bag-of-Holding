"""Gate-A tests for migration 0001 (intake orchestration integrity) — revision 3.

Proves the schema + migration path in isolation. The migration is registered in the live
`MIGRATIONS` list, but these tests apply it to throwaway temp DBs (either via an explicit
`migrations=[MIGRATION]` list or via `connection.init_db()` on a temp `DB_PATH`) so no real DB
is touched. Scheduler/orchestration behavior tests follow at Gate B.
"""

from __future__ import annotations

import os
import sqlite3
import threading

import pytest

from app.db.migrations import run_migrations, applied_migrations, BASELINE_ID
from app.db.migrations_0001_intake_orchestration_integrity import MIGRATION
from app.services.intake.clock import utc_now_iso
from app.services.intake.source_revision import (
    canonicalize_source_ref,
    compute_source_revision_id,
    resolve_policy_snapshot,
    resolve_adapter_registry_version,
    UNBOUND_POLICY_SNAPSHOT,
    UNVERSIONED_ADAPTER_REGISTRY,
)


# ── helpers ──────────────────────────────────────────────────────────────────────

@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "boh.db")


def _factory(path):
    def make():
        return sqlite3.connect(path, timeout=30)
    return make


def _apply(path):
    return run_migrations(_factory(path), path, migrations=[MIGRATION], backup=False)


def _table_info(conn, table):
    return conn.execute(f"PRAGMA table_info({table})").fetchall()  # cid,name,type,notnull,dflt,pk


def _columns(conn, table):
    return {r[1] for r in _table_info(conn, table)}


def _index_names(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA index_list({table})").fetchall()}


def _all_tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}


def _insert_revision(conn, *, rid, ref, h, policy="", adapter="", lifecycle="discovered",
                     claim_token=None, claimed_by=None, claimed_at=None, claim_expires_at=None):
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO intake_source_revisions (
            source_revision_id, canonical_source_ref, source_hash_sha256, byte_size,
            policy_snapshot_hash, adapter_registry_version, lifecycle_state,
            claim_token, claimed_by, claimed_at, claim_expires_at,
            created_at, last_seen_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (rid, ref, h, 10, policy, adapter, lifecycle,
         claim_token, claimed_by, claimed_at, claim_expires_at, now, now, now),
    )
    conn.commit()


# ── schema shape ─────────────────────────────────────────────────────────────────

def test_creates_both_ledgers_with_expected_columns(db_path):
    _apply(db_path)
    conn = sqlite3.connect(db_path)
    try:
        rev = _columns(conn, "intake_source_revisions")
        run_info = _table_info(conn, "intake_runs")
        run = {r[1] for r in run_info}
        snap_notnull = next(r[3] for r in run_info if r[1] == "source_ref_snapshot")
    finally:
        conn.close()
    assert {
        "source_revision_id", "canonical_source_ref", "source_hash_sha256", "byte_size",
        "policy_snapshot_hash", "adapter_registry_version", "lifecycle_state",
        "claim_token", "claimed_by", "claimed_at", "claim_expires_at",
        "created_at", "last_seen_at", "updated_at",
    } == rev
    assert "last_run_id" not in rev
    assert {
        "run_id", "source_revision_id", "source_ref_snapshot", "intake_capability_id",
        "trigger_kind", "lifecycle_state", "stage_reached", "failure_code", "failure_detail",
        "batch_id", "created_at", "started_at", "finished_at", "updated_at",
    } == run
    assert snap_notnull == 1  # source_ref_snapshot is NOT NULL


def test_expected_indexes_present(db_path):
    _apply(db_path)
    conn = sqlite3.connect(db_path)
    try:
        rev_idx = _index_names(conn, "intake_source_revisions")
        run_idx = _index_names(conn, "intake_runs")
    finally:
        conn.close()
    assert "idx_intake_source_revisions_state_claim_expiry" in rev_idx
    assert "idx_intake_runs_source_created" in run_idx
    assert "idx_intake_runs_capability" in run_idx
    assert "idx_intake_runs_state_updated" in run_idx


# ── runner integration ───────────────────────────────────────────────────────────

def test_migration_recorded_and_baseline_stamped(db_path):
    summary = _apply(db_path)
    assert MIGRATION.id in summary["applied"]
    conn = sqlite3.connect(db_path)
    try:
        done = applied_migrations(conn)
    finally:
        conn.close()
    assert BASELINE_ID in done and MIGRATION.id in done


def test_idempotent_second_run_is_ledger_noop(db_path):
    _apply(db_path)
    summary2 = _apply(db_path)
    assert MIGRATION.id not in summary2["applied"]
    conn = sqlite3.connect(db_path)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE migration_id=?", (MIGRATION.id,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 1


def test_unexpected_preexisting_table_fails_loudly(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE intake_source_revisions (x TEXT)")
    conn.commit()
    conn.close()
    with pytest.raises(sqlite3.OperationalError):
        _apply(db_path)  # plain CREATE TABLE must raise, not silently pass


def test_applies_to_legacy_initialized_db_with_data(tmp_path, monkeypatch):
    """Realistic upgrade path: full legacy baseline (init_db) + existing data, then migrate."""
    import app.db.connection as conn_mod
    import app.db.migrations as migrations

    legacy = str(tmp_path / "legacy.db")
    monkeypatch.setattr(conn_mod, "DB_PATH", legacy)

    # 1. legacy baseline only (no forward migrations registered yet)
    monkeypatch.setattr(migrations, "MIGRATIONS", [])
    conn_mod.init_db()

    # representative existing data in a baseline table (generic minimal insert)
    seed = conn_mod.get_conn()
    try:
        info = _table_info(seed, "docs")
        pk_col = next(r[1] for r in info if r[5])
        cols, vals = [], []
        for _cid, name, ctype, notnull, dflt, pk in info:
            if pk:
                cols.append(name); vals.append("legacy-doc-1")
            elif notnull and dflt is None:
                t = (ctype or "").upper()
                cols.append(name); vals.append(0 if ("INT" in t or "REAL" in t or "NUM" in t) else "x")
        seed.execute(
            f"INSERT INTO docs ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals
        )
        seed.commit()
    finally:
        seed.close()

    pre = conn_mod.get_conn()
    try:
        assert "intake_source_revisions" not in _all_tables(pre)
    finally:
        pre.close()

    # 2. upgrade: register the real migration and run the forward path
    monkeypatch.setattr(migrations, "MIGRATIONS", [MIGRATION])
    summary = migrations.run_migrations(conn_mod.get_conn, legacy, backup=False)
    assert MIGRATION.id in summary["applied"]

    post = conn_mod.get_conn()
    try:
        tables = _all_tables(post)
        survived = post.execute(
            f"SELECT COUNT(*) FROM docs WHERE {pk_col}=?", ("legacy-doc-1",)
        ).fetchone()[0]
    finally:
        post.close()
    assert "intake_source_revisions" in tables and "intake_runs" in tables
    assert survived == 1  # existing data survived the upgrade


def test_runtime_factory_enforces_foreign_keys(tmp_path, monkeypatch):
    """The FK on intake_runs.source_revision_id is only enforced if the factory enables it."""
    import app.db.connection as conn_mod
    monkeypatch.setattr(conn_mod, "DB_PATH", str(tmp_path / "fk.db"))
    c = conn_mod.get_conn()
    try:
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        c.close()


# ── revision identity (table constraints) ────────────────────────────────────────

def test_duplicate_identity_rejected(db_path):
    _apply(db_path)
    conn = sqlite3.connect(db_path)
    try:
        _insert_revision(conn, rid="r1", ref="/lib/a.md", h="HASH", policy="p1", adapter="v1")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_revision(conn, rid="r2", ref="/lib/a.md", h="HASH", policy="p1", adapter="v1")
    finally:
        conn.close()


def test_null_identity_component_rejected(db_path):
    _apply(db_path)
    conn = sqlite3.connect(db_path)
    try:
        now = utc_now_iso()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO intake_source_revisions (
                    source_revision_id, canonical_source_ref, source_hash_sha256, byte_size,
                    policy_snapshot_hash, adapter_registry_version, lifecycle_state,
                    created_at, last_seen_at, updated_at
                ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)
                """,
                ("r1", "/lib/a.md", "HASH", 10, "v1", "discovered", now, now, now),
            )
    finally:
        conn.close()


def test_bad_lifecycle_state_rejected(db_path):
    _apply(db_path)
    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            _insert_revision(conn, rid="r1", ref="/lib/a.md", h="HASH", lifecycle="bogus")
    finally:
        conn.close()


# ── claim lease constraints ──────────────────────────────────────────────────────

def test_partial_lease_fields_rejected(db_path):
    _apply(db_path)
    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            # claim_token set but the other three NULL → all-or-none CHECK violation
            _insert_revision(conn, rid="r1", ref="/lib/a.md", h="HASH", claim_token="tok")
    finally:
        conn.close()


def test_duplicate_claim_token_rejected(db_path):
    _apply(db_path)
    conn = sqlite3.connect(db_path)
    try:
        now = utc_now_iso()
        _insert_revision(conn, rid="r1", ref="/lib/a.md", h="H1", lifecycle="claimed",
                         claim_token="T", claimed_by="s", claimed_at=now, claim_expires_at=now)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_revision(conn, rid="r2", ref="/lib/b.md", h="H2", lifecycle="claimed",
                             claim_token="T", claimed_by="s", claimed_at=now, claim_expires_at=now)
    finally:
        conn.close()


_CLAIM_SQL = """
    UPDATE intake_source_revisions
       SET lifecycle_state = 'claimed', claim_token = ?, claimed_by = ?,
           claimed_at = ?, claim_expires_at = ?, updated_at = ?
     WHERE source_revision_id = ?
       AND lifecycle_state = 'discovered'
       AND claim_token IS NULL
"""


def test_concurrent_claim_has_exactly_one_winner(db_path):
    _apply(db_path)
    seed = sqlite3.connect(db_path)
    _insert_revision(seed, rid="r1", ref="/lib/a.md", h="HASH")
    seed.close()

    results = {}
    barrier = threading.Barrier(2)

    def claim(name, token):
        conn = sqlite3.connect(db_path, timeout=30)
        try:
            now = utc_now_iso()
            barrier.wait()  # both threads race the same conditional UPDATE
            cur = conn.execute(_CLAIM_SQL, (token, name, now, now, now, "r1"))
            conn.commit()
            results[name] = cur.rowcount
        finally:
            conn.close()

    t1 = threading.Thread(target=claim, args=("A", "tok-A"))
    t2 = threading.Thread(target=claim, args=("B", "tok-B"))
    t1.start(); t2.start(); t1.join(); t2.join()

    assert sorted(results.values()) == [0, 1]  # exactly one scanner claims the row


# ── run ledger semantics ─────────────────────────────────────────────────────────

def test_run_row_allows_pre_revision_failure_with_snapshot(db_path):
    _apply(db_path)
    conn = sqlite3.connect(db_path)
    try:
        now = utc_now_iso()
        conn.execute(
            """
            INSERT INTO intake_runs (
                run_id, source_ref_snapshot, trigger_kind, lifecycle_state,
                failure_code, failure_detail, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("run-1", "/lib/a.md", "scheduler", "failed",
             "unexpected_exception", "boom in preserve", now, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT source_revision_id, intake_capability_id, source_ref_snapshot, "
            "failure_code FROM intake_runs WHERE run_id=?", ("run-1",)
        ).fetchone()
    finally:
        conn.close()
    assert row == (None, None, "/lib/a.md", "unexpected_exception")


# ── source-revision identity helper (frozen serialization) ───────────────────────

def test_revision_id_is_frozen_golden_value():
    assert compute_source_revision_id(
        canonical_source_ref="/lib/a.md", source_hash_sha256="abc123",
    ) == "aef2d945a6db8b4888c5191064bdf4c90331a053d4356b4cb216281398eb32c8"


def test_missing_policy_and_adapter_normalize_to_sentinels():
    a = compute_source_revision_id(canonical_source_ref="/lib/a.md", source_hash_sha256="H")
    b = compute_source_revision_id(canonical_source_ref="/lib/a.md", source_hash_sha256="H",
                                   policy_snapshot_hash="", adapter_registry_version="")
    c = compute_source_revision_id(canonical_source_ref="/lib/a.md", source_hash_sha256="H",
                                   policy_snapshot_hash=None, adapter_registry_version=None)
    d = compute_source_revision_id(canonical_source_ref="/lib/a.md", source_hash_sha256="H",
                                   policy_snapshot_hash=UNBOUND_POLICY_SNAPSHOT,
                                   adapter_registry_version=UNVERSIONED_ADAPTER_REGISTRY)
    assert a == b == c == d
    assert resolve_policy_snapshot("") == UNBOUND_POLICY_SNAPSHOT
    assert resolve_adapter_registry_version(None) == UNVERSIONED_ADAPTER_REGISTRY


def test_content_change_yields_new_revision_id():
    base = compute_source_revision_id(canonical_source_ref="/lib/a.md", source_hash_sha256="H1")
    changed = compute_source_revision_id(canonical_source_ref="/lib/a.md", source_hash_sha256="H2")
    assert base != changed


def test_timestamp_only_change_reuses_revision_id():
    a = compute_source_revision_id(canonical_source_ref="/lib/a.md", source_hash_sha256="H1")
    b = compute_source_revision_id(canonical_source_ref="/lib/a.md", source_hash_sha256="H1")
    assert a == b


def test_policy_change_yields_new_revision_id():
    base = compute_source_revision_id(
        canonical_source_ref="/lib/a.md", source_hash_sha256="H1", policy_snapshot_hash="p1")
    changed = compute_source_revision_id(
        canonical_source_ref="/lib/a.md", source_hash_sha256="H1", policy_snapshot_hash="p2")
    assert base != changed


def test_adapter_version_change_yields_new_revision_id():
    base = compute_source_revision_id(
        canonical_source_ref="/lib/a.md", source_hash_sha256="H1", adapter_registry_version="v1")
    changed = compute_source_revision_id(
        canonical_source_ref="/lib/a.md", source_hash_sha256="H1", adapter_registry_version="v2")
    assert base != changed


@pytest.mark.skipif(os.name != "nt", reason="case-folding applies on case-insensitive FS (Windows)")
def test_path_casing_normalized_same_revision_on_windows():
    a = canonicalize_source_ref(r"C:\Lib\A.MD")
    b = canonicalize_source_ref(r"c:\lib\a.md")
    assert a == b
    assert (
        compute_source_revision_id(canonical_source_ref=a, source_hash_sha256="H1")
        == compute_source_revision_id(canonical_source_ref=b, source_hash_sha256="H1")
    )
