"""Test-suite database-isolation guard (fail-closed).

`app.api.main` triggers `init_db()` at import, which (since WO-1) applies a forward migration and
takes a backup. So the suite must NEVER run against the repo's real `./boh.db`. pytest imports
this conftest before collecting/importing test modules (and thus before `app.db.connection` reads
`BOH_DB` into `DB_PATH`), so resolving it here is sufficient.

Policy (see tests/db_isolation.py): unset -> isolated temp DB; an explicit temp DB -> allowed; the
real boh.db -> the session aborts UNCONDITIONALLY. There is no pytest override
(`BOH_ALLOW_REAL_DB_TESTS` is inert here); supervised real-DB operations run outside pytest via
the owner-gated gate-driver pattern.
"""

from __future__ import annotations

import os
import pathlib
import sqlite3

import pytest

import db_isolation
from db_isolation import resolve_test_db

_REAL_DB = str(pathlib.Path(__file__).resolve().parent.parent / "boh.db")

# Layer 1 — binding: raises (aborting the session) if BOH_DB points at the real database.
# UNCONDITIONAL (owner correction 2026-06-10): no environment variable can disable it.
# Runs before any app import reads BOH_DB.
os.environ["BOH_DB"] = resolve_test_db(os.environ.get("BOH_DB"), _REAL_DB)

# Layer 2 — writable-open guard (`boh_db_isolation_hardening_v0_1`): env binding cannot stop a
# module that resolves its own path (relative "boh.db" against the repo cwd, import-time
# captures). Wrap every in-process connect alias — sqlite3.connect, sqlite3.dbapi2.connect,
# and the raw C module's _sqlite3.connect — so a WRITABLE open of the real boh.db fails closed
# with a traceback at the offending site, regardless of how the caller imported connect.
# Read-only `file:...?mode=ro` URIs and all temp DBs pass through. UNCONDITIONAL in pytest:
# there is no bypass env. Production code outside pytest is untouched.
if not getattr(sqlite3.connect, "__boh_isolation_guard__", False):
    _guarded = db_isolation.make_guarded_connect(sqlite3.connect, _REAL_DB)
    sqlite3.connect = _guarded
    sqlite3.dbapi2.connect = _guarded
    import _sqlite3
    _sqlite3.connect = _guarded


# Layer 3 — real-DB sentinel: the suite FAILS if the real boh.db's sha256, size, or mtime_ns
# changed across the session (the teardown assertion names the changed fields). UNCONDITIONAL.
@pytest.fixture(autouse=True, scope="session")
def _real_db_sentinel():
    pre = db_isolation.snapshot(_REAL_DB)
    yield
    post = db_isolation.snapshot(_REAL_DB)
    changed = db_isolation.diff_snapshots(pre, post)
    assert not changed, (
        f"boh_db_isolation sentinel: the real boh.db changed during the test session. "
        f"Changed fields: {changed}. pre={pre} post={post}"
    )
