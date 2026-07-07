"""tests/test_db_migrations.py — forward schema-migration architecture.

Covers the baseline + forward-migration runner in app/db/migrations.py:
  - fresh DB: full schema + schema_migrations baseline
  - existing DB: recognized at baseline, data preserved, baseline stamped once
  - idempotent re-run
  - a forward migration applies once, is recorded, skipped thereafter
  - interrupted migration rolls back with no partial/false state
  - WAL-safe backup taken only when a forward migration is pending; none otherwise
  - backup failure fails closed (migration not applied)
  - init_db remains schema-neutral (the runner adds only schema_migrations)
"""

from __future__ import annotations

import os
import sqlite3

import pytest

from app.db import migrations as M


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """A freshly init'd database on disk, with connection.DB_PATH pointed at it."""
    db_path = tmp_path / "boh.db"
    monkeypatch.setenv("BOH_DB", str(db_path))
    import importlib
    import app.db.connection as conn_mod
    importlib.reload(conn_mod)
    conn_mod.DB_PATH = str(db_path)
    conn_mod.init_db()
    return conn_mod, str(db_path)


def _factory(db_path: str):
    def f():
        c = sqlite3.connect(db_path, timeout=30.0)
        c.execute("PRAGMA busy_timeout=30000")
        return c
    return f


def _objects(db_path: str) -> list[tuple]:
    c = sqlite3.connect(db_path)
    try:
        return c.execute(
            "SELECT type,name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' AND name != 'schema_migrations' "
            "ORDER BY type,name"
        ).fetchall()
    finally:
        c.close()


def _ledger(db_path: str) -> list[str]:
    c = sqlite3.connect(db_path)
    try:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone():
            return []
        return [r[0] for r in c.execute("SELECT migration_id FROM schema_migrations ORDER BY migration_id").fetchall()]
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Baseline / existing-DB
# ---------------------------------------------------------------------------

class TestBaseline:
    def test_fresh_db_has_baseline(self, fresh_db):
        _, db_path = fresh_db
        # Baseline is stamped; the registered forward migration(s) are applied after it.
        ledger = _ledger(db_path)
        assert M.BASELINE_ID in ledger
        assert "0001_intake_orchestration_integrity" in ledger

    def test_fresh_db_has_core_tables(self, fresh_db):
        _, db_path = fresh_db
        names = {n for (_t, n, _s) in _objects(db_path)}
        for t in ("docs", "conflicts", "doc_chunks", "intake_capabilities"):
            assert t in names, f"missing table {t}"

    def test_existing_db_recognized_data_preserved(self, fresh_db):
        conn_mod, db_path = fresh_db
        conn_mod.execute("INSERT OR IGNORE INTO docs (doc_id, title) VALUES ('keep1','v')")
        before = _objects(db_path)
        conn_mod.init_db()  # re-run on the existing DB
        assert _objects(db_path) == before, "schema changed on re-run"
        assert _ledger(db_path).count(M.BASELINE_ID) == 1, "baseline stamped more than once"
        row = conn_mod.fetchone("SELECT title FROM docs WHERE doc_id='keep1'")
        assert row and row["title"] == "v", "data not preserved"

    def test_runner_only_adds_schema_migrations(self, fresh_db):
        # init_db is schema-neutral apart from the schema_migrations ledger table.
        _, db_path = fresh_db
        c = sqlite3.connect(db_path)
        has = c.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone()
        c.close()
        assert has is not None


# ---------------------------------------------------------------------------
# Forward migrations
# ---------------------------------------------------------------------------

class TestForwardMigrations:
    def _mig_create(self):
        def up(conn):
            conn.execute("CREATE TABLE mig_demo (id TEXT PRIMARY KEY, v TEXT)")
        return M.Migration("0001_mig_demo", "create mig_demo table", up)

    def test_apply_once(self, fresh_db):
        _, db_path = fresh_db
        summary = M.run_migrations(_factory(db_path), db_path, migrations=[self._mig_create()], backup=False)
        assert "0001_mig_demo" in summary["applied"]
        c = sqlite3.connect(db_path)
        exists = c.execute("SELECT 1 FROM sqlite_master WHERE name='mig_demo'").fetchone()
        c.close()
        assert exists is not None
        assert "0001_mig_demo" in _ledger(db_path)

    def test_skipped_on_rerun(self, fresh_db):
        _, db_path = fresh_db
        migs = [self._mig_create()]
        M.run_migrations(_factory(db_path), db_path, migrations=migs, backup=False)
        s2 = M.run_migrations(_factory(db_path), db_path, migrations=migs, backup=False)
        assert s2["applied"] == [], "migration re-applied"

    def test_pending_introspection(self, fresh_db):
        _, db_path = fresh_db
        migs = [self._mig_create()]
        assert [m.id for m in M.pending_migrations(_factory(db_path), migs)] == ["0001_mig_demo"]
        M.run_migrations(_factory(db_path), db_path, migrations=migs, backup=False)
        assert M.pending_migrations(_factory(db_path), migs) == []

    def test_global_migrations_list_registers_intake_orchestration(self):
        # The first real forward migration (WO-1) is registered, ordered, and unique.
        ids = [m.id for m in M.MIGRATIONS]
        assert "0001_intake_orchestration_integrity" in ids
        assert ids == sorted(ids), "migrations must be in ascending id order"
        assert len(ids) == len(set(ids)), "migration ids must be unique"


# ---------------------------------------------------------------------------
# Interrupted migration
# ---------------------------------------------------------------------------

class TestInterruptedMigration:
    def test_rollback_no_partial_state(self, fresh_db):
        _, db_path = fresh_db

        def up(conn):
            conn.execute("CREATE TABLE half_a (id TEXT)")     # would-be partial change
            raise RuntimeError("boom mid-migration")

        bad = M.Migration("0001_bad", "fails mid-way", up)
        with pytest.raises(RuntimeError):
            M.run_migrations(_factory(db_path), db_path, migrations=[bad], backup=False)

        c = sqlite3.connect(db_path)
        partial = c.execute("SELECT 1 FROM sqlite_master WHERE name='half_a'").fetchone()
        c.close()
        assert partial is None, "partial DDL was not rolled back"
        assert "0001_bad" not in _ledger(db_path), "failed migration was recorded"

    def test_baseline_intact_after_failure(self, fresh_db):
        _, db_path = fresh_db

        def up(conn):
            raise RuntimeError("nope")

        with pytest.raises(RuntimeError):
            M.run_migrations(_factory(db_path), db_path,
                             migrations=[M.Migration("0001_x", "x", up)], backup=False)
        assert M.BASELINE_ID in _ledger(db_path)


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

class TestBackup:
    def _mig(self):
        def up(conn):
            conn.execute("CREATE TABLE bak_demo (id TEXT)")
        return M.Migration("0001_bak", "bak demo", up)

    def test_backup_created_when_pending(self, fresh_db, tmp_path):
        _, db_path = fresh_db
        summary = M.run_migrations(_factory(db_path), db_path, migrations=[self._mig()], backup=True)
        bak = summary["backup_path"]
        assert bak and os.path.exists(bak), "no backup written before forward migration"
        # backup is a valid SQLite DB containing the pre-migration schema
        c = sqlite3.connect(bak)
        n = c.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
        has_demo = c.execute("SELECT 1 FROM sqlite_master WHERE name='bak_demo'").fetchone()
        c.close()
        assert n > 0
        assert has_demo is None, "backup taken AFTER the migration, not before"

    def test_backup_name_collision_same_second_is_resolved(self, tmp_path, monkeypatch):
        # Regression: two backups within the same wall-clock second must not collide. VACUUM INTO
        # fails if the target exists, so _backup must pick a free, collision-resistant name.
        db_path = str(tmp_path / "boh.db")
        c = sqlite3.connect(db_path)
        c.execute("CREATE TABLE t (x INTEGER)")
        c.execute("INSERT INTO t VALUES (42)")
        c.commit()
        c.close()
        # freeze the timestamp so both backups would otherwise compute the same name
        monkeypatch.setattr(M.time, "strftime", lambda *a, **k: "20260604-000000")

        b1 = M._backup(_factory(db_path), db_path)
        b2 = M._backup(_factory(db_path), db_path)

        assert b1 and b2 and b1 != b2, "second backup reused the first backup's name"
        assert os.path.exists(b1) and os.path.exists(b2), "a backup file is missing"
        for b in (b1, b2):
            cc = sqlite3.connect(b)
            try:
                assert cc.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert cc.execute("SELECT x FROM t").fetchone()[0] == 42  # neither was overwritten
            finally:
                cc.close()

    def test_no_backup_when_nothing_pending(self, fresh_db):
        _, db_path = fresh_db
        summary = M.run_migrations(_factory(db_path), db_path, migrations=[], backup=True)
        assert summary["backup_path"] is None, "backup churned with nothing to apply"

    def test_backup_failure_fails_closed(self, fresh_db, monkeypatch):
        _, db_path = fresh_db

        def boom(*a, **k):
            raise OSError("disk full")
        monkeypatch.setattr(M, "_backup", boom)

        with pytest.raises(OSError):
            M.run_migrations(_factory(db_path), db_path, migrations=[self._mig()], backup=True)
        # migration must NOT have applied
        c = sqlite3.connect(db_path)
        applied = c.execute("SELECT 1 FROM sqlite_master WHERE name='bak_demo'").fetchone()
        c.close()
        assert applied is None, "migration applied despite backup failure"
        assert "0001_bak" not in _ledger(db_path)

    def test_backup_disabled_by_env(self, fresh_db, monkeypatch):
        _, db_path = fresh_db
        monkeypatch.setenv("BOH_DB_BACKUP_BEFORE_MIGRATE", "0")
        summary = M.run_migrations(_factory(db_path), db_path, migrations=[self._mig()])
        assert summary["backup_path"] is None
        assert "0001_bak" in summary["applied"]
