"""Source-revision state-machine service for WO-1 (Gate B / B2).

A narrow service around the frozen `srid-v1` identity (`source_revision.py`) and the
`intake_source_revisions` ledger. SQLite is authoritative; the atomic claim is a single
conditional UPDATE that resolves concurrent scans.

Operations:
  register_or_observe_revision  — insert if new, else bump last_seen_at (no new work)
  try_claim_revision            — atomic conditional claim; returns a token only to the winner
  complete_revision             — terminal 'complete', lease cleared
  set_terminal_state            — terminal held/quarantined/failed, lease cleared
  reconcile_expired_claims      — expired lease -> revision 'failed' + active run 'failed'
                                  (stale_claim_after_restart); never auto-retries

Lease fields are written all-or-none (matching the table CHECK). A terminal transition always
clears the lease.
"""

from __future__ import annotations

import sqlite3
import uuid
from typing import Callable

from app.db import connection as db
from app.services.intake.clock import utc_now_iso, utc_iso_in
from app.services.intake.source_revision import (
    canonicalize_source_ref,
    compute_source_revision_id,
    resolve_policy_snapshot,
    resolve_adapter_registry_version,
)

ConnFactory = Callable[[], sqlite3.Connection]

DEFAULT_LEASE_SECONDS = 900

# Terminal states that release the row from the active pipeline. 'discovered' is NOT terminal.
TERMINAL_STATES = {"complete", "failed", "held", "quarantined"}

_CLAIM_SQL = """
    UPDATE intake_source_revisions
       SET lifecycle_state = 'claimed', claim_token = ?, claimed_by = ?,
           claimed_at = ?, claim_expires_at = ?, updated_at = ?
     WHERE source_revision_id = ?
       AND lifecycle_state = 'discovered'
       AND claim_token IS NULL
"""

_CLEAR_LEASE = (
    "claim_token = NULL, claimed_by = NULL, claimed_at = NULL, claim_expires_at = NULL"
)


def _factory(conn_factory: ConnFactory | None) -> ConnFactory:
    return conn_factory or db.get_conn


def revision_identity(
    *,
    source_ref: str,
    source_hash_sha256: str,
    policy_snapshot_hash: str | None = None,
    adapter_registry_version: str | None = None,
) -> dict:
    """Resolve the four canonical identity components + the srid-v1 digest. Pure."""
    canonical = canonicalize_source_ref(source_ref)
    policy = resolve_policy_snapshot(policy_snapshot_hash)
    adapter = resolve_adapter_registry_version(adapter_registry_version)
    srid = compute_source_revision_id(
        canonical_source_ref=canonical,
        source_hash_sha256=source_hash_sha256,
        policy_snapshot_hash=policy,
        adapter_registry_version=adapter,
    )
    return {
        "source_revision_id": srid,
        "canonical_source_ref": canonical,
        "source_hash_sha256": source_hash_sha256,
        "policy_snapshot_hash": policy,
        "adapter_registry_version": adapter,
    }


def register_or_observe_revision(
    *,
    source_ref: str,
    source_hash_sha256: str,
    byte_size: int,
    policy_snapshot_hash: str | None = None,
    adapter_registry_version: str | None = None,
    conn_factory: ConnFactory | None = None,
) -> tuple[dict, bool]:
    """Insert the revision if new, else bump `last_seen_at`. Returns (row_dict, created)."""
    ident = revision_identity(
        source_ref=source_ref, source_hash_sha256=source_hash_sha256,
        policy_snapshot_hash=policy_snapshot_hash,
        adapter_registry_version=adapter_registry_version,
    )
    srid = ident["source_revision_id"]
    now = utc_now_iso()
    conn = _factory(conn_factory)()
    try:
        with conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO intake_source_revisions (
                    source_revision_id, canonical_source_ref, source_hash_sha256, byte_size,
                    policy_snapshot_hash, adapter_registry_version, lifecycle_state,
                    created_at, last_seen_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'discovered', ?, ?, ?)
                """,
                (srid, ident["canonical_source_ref"], source_hash_sha256, byte_size,
                 ident["policy_snapshot_hash"], ident["adapter_registry_version"], now, now, now),
            )
            created = cur.rowcount == 1
            if not created:
                conn.execute(
                    "UPDATE intake_source_revisions SET last_seen_at=?, updated_at=? "
                    "WHERE source_revision_id=?",
                    (now, now, srid),
                )
        row = conn.execute(
            "SELECT * FROM intake_source_revisions WHERE source_revision_id=?", (srid,)
        ).fetchone()
        return dict(row), created
    finally:
        conn.close()


def try_claim_revision(
    source_revision_id: str,
    *,
    claimed_by: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    conn_factory: ConnFactory | None = None,
) -> str | None:
    """Atomic conditional claim. Returns a claim token to the single winner, else None."""
    token = uuid.uuid4().hex
    now = utc_now_iso()
    expires = utc_iso_in(lease_seconds)
    conn = _factory(conn_factory)()
    try:
        with conn:
            cur = conn.execute(_CLAIM_SQL, (token, claimed_by, now, expires, now, source_revision_id))
        return token if cur.rowcount == 1 else None
    finally:
        conn.close()


def complete_revision(source_revision_id: str, *, conn_factory: ConnFactory | None = None) -> None:
    set_terminal_state(source_revision_id, "complete", conn_factory=conn_factory)


def set_terminal_state(
    source_revision_id: str, state: str, *, conn_factory: ConnFactory | None = None
) -> None:
    """Move a revision to a terminal state and clear the lease (all-or-none)."""
    if state not in TERMINAL_STATES:
        raise ValueError(f"not a terminal state: {state}")
    now = utc_now_iso()
    conn = _factory(conn_factory)()
    try:
        with conn:
            conn.execute(
                f"UPDATE intake_source_revisions SET lifecycle_state=?, {_CLEAR_LEASE}, "
                f"updated_at=? WHERE source_revision_id=?",
                (state, now, source_revision_id),
            )
    finally:
        conn.close()


# Quarantined revisions are intentionally NOT replay-eligible: re-running blocked content
# (e.g. executables) would defeat the safety model. Replay covers held/failed/complete only.
_REPLAY_RECLAIM_SQL = """
    UPDATE intake_source_revisions
       SET lifecycle_state = 'claimed', claim_token = ?, claimed_by = ?,
           claimed_at = ?, claim_expires_at = ?, updated_at = ?
     WHERE source_revision_id = ?
       AND lifecycle_state IN ('failed', 'held', 'complete')
       AND claim_token IS NULL
"""

# Refresh only while the lease is still owned AND not yet expired (no reviving an expired lease).
_REFRESH_SQL = """
    UPDATE intake_source_revisions
       SET claim_expires_at = ?, updated_at = ?
     WHERE source_revision_id = ?
       AND claim_token = ?
       AND lifecycle_state = 'claimed'
       AND claim_expires_at >= ?
"""


def reopen_and_claim_for_replay(
    source_revision_id: str,
    *,
    claimed_by: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    conn_factory: ConnFactory | None = None,
) -> str | None:
    """Atomically reclaim a TERMINAL revision for an explicit replay, in one transaction:
    terminal -> claimed with a fresh lease. The intermediate 'discovered' state is never exposed,
    so the background scheduler cannot steal the revision between reopen and claim. Returns the
    new claim token, or None if the revision is not a reclaimable terminal/unclaimed row."""
    token = uuid.uuid4().hex
    now = utc_now_iso()
    expires = utc_iso_in(lease_seconds)
    conn = _factory(conn_factory)()
    try:
        with conn:
            cur = conn.execute(_REPLAY_RECLAIM_SQL,
                               (token, claimed_by, now, expires, now, source_revision_id))
        return token if cur.rowcount == 1 else None
    finally:
        conn.close()


def refresh_lease(
    source_revision_id: str,
    claim_token: str,
    *,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    conn_factory: ConnFactory | None = None,
) -> bool:
    """Extend the lease ONLY while this token still owns the claim. Returns False if zero rows
    matched — the caller has lost ownership (e.g. a reconciler expired the lease) and must fail
    closed rather than keep writing."""
    now = utc_now_iso()
    expires = utc_iso_in(lease_seconds)
    conn = _factory(conn_factory)()
    try:
        with conn:
            cur = conn.execute(_REFRESH_SQL, (expires, now, source_revision_id, claim_token, now))
        return cur.rowcount == 1
    finally:
        conn.close()


def reconcile_expired_claims(*, conn_factory: ConnFactory | None = None) -> list[str]:
    """Fail-closed reconciliation of expired leases. A claimed revision whose lease has expired
    is moved to 'failed' (lease cleared) and its active run is marked failed with
    `stale_claim_after_restart`. It is NEVER auto-retried — only explicit replay reattempts."""
    now = utc_now_iso()
    conn = _factory(conn_factory)()
    reconciled: list[str] = []
    try:
        rows = conn.execute(
            "SELECT source_revision_id, claim_token FROM intake_source_revisions "
            "WHERE lifecycle_state='claimed' AND claim_expires_at IS NOT NULL AND claim_expires_at < ?",
            (now,),
        ).fetchall()
        for r in rows:
            rid = r["source_revision_id"]
            tok = r["claim_token"]
            with conn:
                # Conditional update closes the TOCTOU race: if a worker refreshed its lease or
                # re-claimed (new token) between the SELECT and here, this matches 0 rows and the
                # worker is NOT falsely failed.
                cur = conn.execute(
                    f"UPDATE intake_source_revisions SET lifecycle_state='failed', {_CLEAR_LEASE}, "
                    f"updated_at=? WHERE source_revision_id=? AND lifecycle_state='claimed' "
                    f"AND claim_token=? AND claim_expires_at IS NOT NULL AND claim_expires_at < ?",
                    (now, rid, tok, now),
                )
                if cur.rowcount != 1:
                    continue  # lease was refreshed/re-claimed/finalized concurrently — leave it
                conn.execute(
                    "UPDATE intake_runs SET lifecycle_state='failed', "
                    "failure_code='stale_claim_after_restart', "
                    "failure_detail='lease expired; reconciled', finished_at=?, updated_at=? "
                    "WHERE source_revision_id=? AND lifecycle_state IN ('created','claimed','running')",
                    (now, now, rid),
                )
            reconciled.append(rid)
        return reconciled
    finally:
        conn.close()
