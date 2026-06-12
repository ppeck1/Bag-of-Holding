"""Focused tests for `boh_db_isolation_hardening_v0_1` (guard + sentinel; temp files only).

The writable-open guard and the sentinel are installed by tests/conftest.py for the whole
session; these tests prove the mechanics without ever opening the real boh.db writable
(the guard raises BEFORE any file handle is created).
"""

import os
import sqlite3

import pytest

import db_isolation


def test_guard_is_installed_for_this_session():
    assert getattr(sqlite3.connect, "__boh_isolation_guard__", False) is True


def test_guard_rejects_writable_open_of_real_db():
    with pytest.raises(RuntimeError, match="boh_db_isolation"):
        sqlite3.connect(db_isolation.real_db_path())


def test_guard_rejects_relative_path_resolving_to_real_db():
    # pytest runs from the repo root, so a bare relative "boh.db" resolves to the real file —
    # exactly the bug class env binding cannot stop.
    rel = os.path.relpath(db_isolation.real_db_path())
    with pytest.raises(RuntimeError, match="boh_db_isolation"):
        sqlite3.connect(rel)


def test_guard_rejects_writable_file_uri_to_real_db():
    with pytest.raises(RuntimeError, match="boh_db_isolation"):
        sqlite3.connect(f"file:{db_isolation.real_db_path()}?mode=rwc", uri=True)


def test_allow_real_env_does_not_disable_guard(monkeypatch):
    # Owner correction: under pytest there is NO bypass — the historical override env must
    # have no effect on the writable-open guard.
    monkeypatch.setenv("BOH_ALLOW_REAL_DB_TESTS", "1")
    with pytest.raises(RuntimeError, match="boh_db_isolation"):
        sqlite3.connect(db_isolation.real_db_path())


def test_binding_rejection_has_no_override(monkeypatch):
    # The binding layer is unconditional too: resolve_test_db has no allow flag, and the env
    # variable changes nothing.
    monkeypatch.setenv("BOH_ALLOW_REAL_DB_TESTS", "1")
    real = db_isolation.real_db_path()
    with pytest.raises(RuntimeError, match="Refusing to run the test suite"):
        db_isolation.resolve_test_db(real, real)
    # Case/separator variants are also rejected. Case-folding is a Windows
    # filesystem property; on POSIX an upper-cased path is a different file.
    if os.name == "nt":
        with pytest.raises(RuntimeError, match="Refusing to run the test suite"):
            db_isolation.resolve_test_db(real.upper().replace("\\", "/"), real)


def test_connect_aliases_are_guarded():
    # Every in-process alias path must hit the same guard.
    from sqlite3 import connect as plain_connect
    from sqlite3.dbapi2 import connect as dbapi2_connect
    import _sqlite3
    real = db_isolation.real_db_path()
    for alias in (plain_connect, dbapi2_connect, _sqlite3.connect, sqlite3.dbapi2.connect):
        assert getattr(alias, "__boh_isolation_guard__", False) is True
        with pytest.raises(RuntimeError, match="boh_db_isolation"):
            alias(real)


def test_guard_permits_temp_db_and_memory(tmp_path):
    conn = sqlite3.connect(tmp_path / "ok.db")
    conn.execute("CREATE TABLE t (x)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()
    mem = sqlite3.connect(":memory:")
    mem.execute("SELECT 1")
    mem.close()


@pytest.mark.skipif(not os.path.isfile(db_isolation.real_db_path()),
                    reason="real boh.db not present in this checkout")
def test_guard_permits_readonly_uri_to_real_db():
    conn = sqlite3.connect(f"file:{db_isolation.real_db_path()}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] >= 2
    conn.close()


def test_targets_real_db_path_forms():
    real = db_isolation.real_db_path()
    assert db_isolation.targets_real_db(real)
    if os.name == "nt":
        assert db_isolation.targets_real_db(real.upper())                  # Windows case-fold
    assert db_isolation.targets_real_db(real.replace("\\", "/"))          # mixed separators
    assert db_isolation.targets_real_db(f"file:{real}?mode=rwc")
    assert not db_isolation.targets_real_db(":memory:")
    assert not db_isolation.targets_real_db("")
    assert not db_isolation.targets_real_db("file::memory:?cache=shared")
    assert not db_isolation.targets_real_db(real + ".bak")


def test_sentinel_detects_intentional_mutation_on_temp_copy(tmp_path):
    target = tmp_path / "sentinel.db"
    target.write_bytes(b"sqlite-ish bytes for the sentinel test")
    pre = db_isolation.snapshot(str(target))

    # Content mutation: sha256 + size flagged (mtime_ns usually too, but an append landing in
    # the same NTFS 100ns timestamp tick as file creation can leave it identical — the
    # touch-only case below proves mtime_ns detection independently and deterministically).
    with open(target, "ab") as fh:
        fh.write(b" mutated")
    post = db_isolation.snapshot(str(target))
    changed = db_isolation.diff_snapshots(pre, post)
    assert {"sha256", "size"} <= set(changed)

    # Touch-only mutation (the WAL-checkpoint signature): mtime_ns alone is flagged.
    pre2 = db_isolation.snapshot(str(target))
    os.utime(target, ns=(pre2["mtime_ns"] + 1_000_000, pre2["mtime_ns"] + 1_000_000))
    post2 = db_isolation.snapshot(str(target))
    assert db_isolation.diff_snapshots(pre2, post2) == ["mtime_ns"]

    # Deletion is reported as an existence change.
    target.unlink()
    assert db_isolation.diff_snapshots(pre2, db_isolation.snapshot(str(target))) == ["existence"]
    # And a clean pair reports nothing.
    assert db_isolation.diff_snapshots(pre2, pre2) == []
