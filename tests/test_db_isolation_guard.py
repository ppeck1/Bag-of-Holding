"""Tests for the fail-closed pytest database-isolation policy (tests/db_isolation.py).

Updated for `boh_db_isolation_hardening_v0_1` (owner correction 2026-06-10): the binding
rejection is UNCONDITIONAL — there is no pytest override. Supervised real-DB operations run
outside pytest via the owner-gated gate-driver pattern.
"""

from __future__ import annotations

import pytest

from db_isolation import resolve_test_db, isolated_default_path

_REAL = "/repo/boh.db"  # treated as the real DB path for these cases


def test_unset_redirects_to_isolated_database():
    assert resolve_test_db(None, _REAL) == isolated_default_path()
    assert resolve_test_db("", _REAL) == isolated_default_path()


def test_temporary_database_is_allowed():
    assert resolve_test_db("/tmp/some_temp.db", _REAL) == "/tmp/some_temp.db"


def test_real_database_aborts_the_session():
    with pytest.raises(RuntimeError, match="real database"):
        resolve_test_db(_REAL, _REAL)


def test_real_database_has_no_override(monkeypatch):
    # The historical BOH_ALLOW_REAL_DB_TESTS escape hatch was removed (owner correction):
    # the env variable must have no effect, and the API exposes no allow flag.
    monkeypatch.setenv("BOH_ALLOW_REAL_DB_TESTS", "1")
    with pytest.raises(RuntimeError, match="no pytest override"):
        resolve_test_db(_REAL, _REAL)
