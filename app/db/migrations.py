"""app/db/migrations.py: Forward schema-migration runner for Bag of Holding.

Design: BASELINE + FORWARD MIGRATIONS.

The existing `connection.init_db()` is an idempotent, declarative schema builder that
converges any database (fresh or existing) to the current full schema. That schema is the
immutable BASELINE (id ``0000_baseline``). This module governs everything FORWARD from the
baseline: a `schema_migrations` ledger plus an ordered list of numbered migrations applied
after the baseline. The baseline itself is never expressed as migration steps.

Guarantees:
  - Baseline is stamped once on first run (existing DBs are recognized, never re-created).
  - Each forward migration runs in ONE transaction with its own ledger insert, so an
    interrupted migration leaves the DB at the last fully-applied version with no partial
    or false state (SQLite DDL is transactional).
  - A consistent, WAL-safe backup (VACUUM INTO) is taken before applying any pending
    forward migration — and only then. A backup failure aborts the migration (fail-closed).
  - Idempotent: already-applied migrations are skipped.

This is separate from the legacy `schema_version` table (which is cosmetic stamping);
`schema_migrations` is the authoritative migration ledger.

Adding a migration: append a `Migration(id, description, up)` to `MIGRATIONS`. `id` MUST be
unique and ordered (e.g. ``0001_add_foo``). `up(conn)` performs the DDL; do NOT commit or
insert into `schema_migrations` inside `up` (the runner owns the transaction + ledger).
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Callable

BASELINE_ID = "0000_baseline"
BASELINE_DESCRIPTION = "Baseline schema produced by connection.init_db()."

# Set BOH_DB_BACKUP_BEFORE_MIGRATE=0 to disable the pre-forward-migration backup.
_BACKUP_ENV = "BOH_DB_BACKUP_BEFORE_MIGRATE"


@dataclass(frozen=True)
class Migration:
    id: str
    description: str
    up: Callable[[sqlite3.Connection], None]

    def checksum(self) -> str:
        return hashlib.sha256(f"{self.id}:{self.description}".encode("utf-8")).hexdigest()[:16]


# Ordered forward migrations applied after the baseline. Each is defined in its own module and
# appended at the bottom of this file (after `Migration` is defined) to keep this file stable
# and avoid editing the runner when adding a migration.
MIGRATIONS: list[Migration] = []


def _ensure_ledger(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            migration_id TEXT PRIMARY KEY,
            applied_ts   INTEGER NOT NULL,
            checksum     TEXT NOT NULL DEFAULT ''
        )
        """
    )


def applied_migrations(conn: sqlite3.Connection) -> set[str]:
    _ensure_ledger(conn)
    return {r[0] for r in conn.execute("SELECT migration_id FROM schema_migrations").fetchall()}


def _record(conn: sqlite3.Connection, mid: str, checksum: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (migration_id, applied_ts, checksum) VALUES (?,?,?)",
        (mid, int(time.time()), checksum),
    )


def pending_migrations(
    conn_factory: Callable[[], sqlite3.Connection],
    migrations: list[Migration] | None = None,
) -> list[Migration]:
    """Forward migrations not yet applied (baseline excluded)."""
    migs = MIGRATIONS if migrations is None else migrations
    conn = conn_factory()
    try:
        done = applied_migrations(conn)
    finally:
        conn.close()
    return [m for m in migs if m.id not in done]


def _backup_enabled() -> bool:
    return os.environ.get(_BACKUP_ENV, "1").strip().lower() not in ("0", "false", "no", "off")


def _backup(conn_factory: Callable[[], sqlite3.Connection], db_path: str) -> str | None:
    """Consistent single-file backup via VACUUM INTO (WAL-safe). Returns the backup path.

    Skipped for in-memory DBs. Raises on failure so the caller can fail closed.
    """
    if not db_path or db_path == ":memory:" or db_path.startswith("file::memory:"):
        return None
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = f"{db_path}.bak-{ts}"
    # Second-resolution timestamps can collide (e.g. init_db's migration backup plus a second
    # run_migrations within the same second). VACUUM INTO fails if the target exists, so find a
    # free, collision-resistant name rather than aborting a legitimate migration.
    _n = 0
    while os.path.exists(bak):
        _n += 1
        bak = f"{db_path}.bak-{ts}-{_n}"
    # VACUUM INTO takes a string literal (no bind param); escape single quotes in the path.
    target = bak.replace("\\", "/").replace("'", "''")
    conn = conn_factory()
    try:
        conn.execute(f"VACUUM INTO '{target}'")
    finally:
        conn.close()
    return bak


def run_migrations(
    conn_factory: Callable[[], sqlite3.Connection],
    db_path: str,
    migrations: list[Migration] | None = None,
    backup: bool | None = None,
) -> dict:
    """Stamp the baseline (once) and apply any pending forward migrations in order.

    conn_factory() must return a fresh connection to the SAME database as db_path.
    Returns a summary dict: baseline_stamped, applied[], backup_path|None.
    Raises on a migration failure (after rolling that migration back).
    """
    migs = MIGRATIONS if migrations is None else migrations
    do_backup = _backup_enabled() if backup is None else backup

    # 1. Ensure ledger + stamp baseline once (O(1); existing DBs are recognized, not rebuilt).
    conn = conn_factory()
    try:
        _ensure_ledger(conn)
        done = {r[0] for r in conn.execute("SELECT migration_id FROM schema_migrations").fetchall()}
        baseline_stamped = False
        if BASELINE_ID not in done:
            _record(conn, BASELINE_ID,
                    hashlib.sha256(BASELINE_DESCRIPTION.encode()).hexdigest()[:16])
            baseline_stamped = True
            done.add(BASELINE_ID)
        conn.commit()
    finally:
        conn.close()

    pending = [m for m in migs if m.id not in done]
    summary = {"baseline_stamped": baseline_stamped, "applied": [], "backup_path": None}
    if not pending:
        return summary

    # 2. One backup before mutating the DB (fail-closed if it cannot be written).
    if do_backup:
        summary["backup_path"] = _backup(conn_factory, db_path)

    # 3. Apply each pending migration in its own transaction (up + ledger insert atomically).
    for m in pending:
        conn = conn_factory()
        try:
            conn.execute("BEGIN")
            m.up(conn)
            _record(conn, m.id, m.checksum())
            conn.execute("COMMIT")
            summary["applied"].append(m.id)
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            conn.close()

    return summary


# ── Registered forward migrations ─────────────────────────────────────────────────
# Appended here (not edited in place) after `Migration`/`MIGRATIONS` are defined, so each
# migration module can `from app.db.migrations import Migration` without a circular-import
# failure. Order in this list is the apply order.
from app.db.migrations_0001_intake_orchestration_integrity import (  # noqa: E402
    MIGRATION as _m_0001_intake_orchestration_integrity,
)
from app.db.migrations_0002_intake_retrieval_promotion import (  # noqa: E402
    MIGRATION as _m_0002_intake_retrieval_promotion,
)

MIGRATIONS.append(_m_0001_intake_orchestration_integrity)
# 0002: schema-approved + wired for temp-clone rehearsal (DEC-0004, 2026-06-10).
# Real-`boh.db` apply remains a separately authorized gate.
MIGRATIONS.append(_m_0002_intake_retrieval_promotion)
