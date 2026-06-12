"""Pure helpers for the pytest database-isolation guard (imported by conftest.py).

Kept separate from conftest so the policy can be unit-tested directly.

`boh_db_isolation_hardening_v0_1` (2026-06-10) adds two mechanical layers on top of the original
env-binding policy, because env binding alone cannot stop a module that resolves its own path
(e.g. a relative "boh.db" against the repo cwd, or an import-time capture):

1. A WRITABLE-OPEN GUARD: conftest wraps `sqlite3.connect` for the test session so any writable
   connection whose target resolves to the real repository `boh.db` raises a structured
   RuntimeError ("boh_db_isolation: ...") BEFORE the file is opened. Temp DBs and read-only
   `file:...?mode=ro` URIs pass through. The guard exists only inside pytest — production
   behavior is untouched.
2. A REAL-DB SENTINEL: a session fixture snapshots the real boh.db (sha256/size/mtime_ns) before
   the suite and fails the session if any field changed afterwards, naming the changed fields.

Controlled-migration boundary: the supervised real-DB migration-apply path runs OUTSIDE pytest
(the owner-gated gate-driver pattern used for C-gates and the re-mint scan), so the guard never
applies to it. **There is NO pytest bypass** (owner correction 2026-06-10): under pytest,
writable access to the resolved real `boh.db` always fails closed — `BOH_ALLOW_REAL_DB_TESTS`
has no effect on the binding rejection, the connect guard, or the sentinel. Read-only
`file:...?mode=ro` inspection remains permitted.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import tempfile


def real_db_path() -> str:
    return str(pathlib.Path(__file__).resolve().parent.parent / "boh.db")


def _connect_target(database) -> str | None:
    """Best-effort filesystem path for a sqlite3.connect() target (None = not a real file)."""
    if isinstance(database, bytes):
        try:
            database = database.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(database, str):
        try:
            database = os.fspath(database)
        except TypeError:
            return None
    if not database or database == ":memory:":
        return None
    if database.startswith("file:"):
        rest = database[5:].split("?", 1)[0]
        if rest.startswith("///"):
            rest = rest[3:]
        elif rest.startswith("//"):
            rest = rest[2:]
        if not rest or rest == ":memory:":
            return None
        database = rest.replace("%20", " ")
    return os.path.abspath(database)


def is_readonly_uri(database) -> bool:
    return isinstance(database, str) and database.startswith("file:") and "mode=ro" in database


def targets_real_db(database, real: str | None = None) -> bool:
    target = _connect_target(database)
    if target is None:
        return False
    return os.path.normcase(target) == os.path.normcase(os.path.abspath(real or real_db_path()))


def make_guarded_connect(original, real: str | None = None):
    """Wrap sqlite3.connect: writable opens of the real boh.db fail closed (test context only)."""
    realp = os.path.abspath(real or real_db_path())

    def guarded(database, *args, **kwargs):
        if targets_real_db(database, realp) and not is_readonly_uri(database):
            raise RuntimeError(
                "boh_db_isolation: writable sqlite3.connect() to the real boh.db is forbidden "
                f"in tests (target={database!r}). Use a temp BOH_DB; read-only inspection must "
                "use a 'file:...?mode=ro' URI. There is no pytest bypass — supervised real-DB "
                "operations run outside pytest (gate-driver pattern)."
            )
        return original(database, *args, **kwargs)

    guarded.__boh_isolation_guard__ = True
    guarded.__wrapped__ = original
    return guarded


def snapshot(path: str) -> dict | None:
    """Sentinel snapshot of a database file: sha256, size, mtime_ns (None if absent)."""
    p = pathlib.Path(path)
    if not p.is_file():
        return None
    digest = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    st = p.stat()
    return {"path": str(p), "sha256": digest.hexdigest(),
            "size": st.st_size, "mtime_ns": st.st_mtime_ns}


def diff_snapshots(pre: dict | None, post: dict | None) -> list[str]:
    """Names of changed sentinel fields (empty = unchanged)."""
    if pre is None and post is None:
        return []
    if (pre is None) != (post is None):
        return ["existence"]
    return [k for k in ("sha256", "size", "mtime_ns") if pre[k] != post[k]]


def isolated_default_path() -> str:
    return str(pathlib.Path(tempfile.gettempdir()) / "boh_pytest_isolated.db")


def resolve_test_db(configured: str | None, real_db: str) -> str:
    """Decide the BOH_DB the test suite may use, failing closed on the real database.

    - unset            -> an isolated temp database
    - a temp/other db  -> allowed as-is
    - the real boh.db  -> RuntimeError (abort the session) — UNCONDITIONALLY; there is no
      pytest override. Supervised real-DB work happens outside pytest (gate-driver pattern).
    """
    real = os.path.abspath(real_db)
    if not configured:
        return isolated_default_path()
    if os.path.normcase(os.path.abspath(configured)) == os.path.normcase(real):
        raise RuntimeError(
            f"Refusing to run the test suite against the real database ({real}). The suite "
            f"applies schema migrations and would mutate it. Unset BOH_DB to use an isolated "
            f"database. There is no pytest override; supervised real-DB operations run outside "
            f"pytest via the owner-gated gate-driver pattern."
        )
    return configured
