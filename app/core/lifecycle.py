"""app/core/lifecycle.py: Lifecycle history, undo, and backward movement for Bag of Holding v2.

Phase 12 addition. Adds:
  - Per-document lifecycle event history (append-only)
  - Backward movement (reverse state transitions)
  - Undo last lifecycle change
  - History log is never erased during undo or backward moves

State ordering: observe → vessel → constraint → integrate → release
"""

import json
import time
from typing import Optional

from app.db import connection as db

# ── Backward transition map ───────────────────────────────────────────────────
BACKWARD_MAP = {
    "release":    "integrate",
    "integrate":  "constraint",
    "constraint": "vessel",
    "vessel":     "observe",
    # "observe" has no backward — it is the initial state
}


# ── Table bootstrap ───────────────────────────────────────────────────────────

def _ensure_table():
    """Create lifecycle_history table if not exists. Safe to call repeatedly."""
    conn = db.get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS lifecycle_history (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id       TEXT    NOT NULL,
                event_ts     INTEGER NOT NULL,
                from_state   TEXT    NOT NULL,
                to_state     TEXT    NOT NULL,
                actor        TEXT    NOT NULL DEFAULT 'user',
                direction    TEXT    NOT NULL DEFAULT 'forward',
                reason       TEXT,
                reversible   INTEGER NOT NULL DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_lh_doc_id ON lifecycle_history(doc_id);
            CREATE INDEX IF NOT EXISTS idx_lh_ts     ON lifecycle_history(event_ts);
        """)
        conn.commit()
    finally:
        conn.close()


# ── Core operations ───────────────────────────────────────────────────────────

def record_event(
    doc_id: str,
    from_state: str,
    to_state: str,
    actor: str = "user",
    direction: str = "forward",
    reason: Optional[str] = None,
) -> int:
    """Append a lifecycle event. Append-only — never deletes existing records.
    Returns the inserted row id.
    """
    _ensure_table()
    conn = db.get_conn()
    try:
        cur = conn.execute(
            """
            INSERT INTO lifecycle_history
              (doc_id, event_ts, from_state, to_state, actor, direction, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (doc_id, int(time.time()), from_state, to_state, actor, direction, reason),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_history(doc_id: str, limit: int = 50) -> list[dict]:
    """Return lifecycle history for a document, newest first."""
    _ensure_table()
    return db.fetchall(
        "SELECT * FROM lifecycle_history WHERE doc_id = ? ORDER BY event_ts DESC, id DESC LIMIT ?",
        (doc_id, limit),
    )


def can_move_backward(doc_id: str) -> dict:
    """Return whether backward movement is possible and what the target state would be."""
    doc = db.fetchone("SELECT operator_state FROM docs WHERE doc_id = ?", (doc_id,))
    if not doc:
        return {"possible": False, "reason": "Document not found"}
    current = doc["operator_state"]
    target = BACKWARD_MAP.get(current)
    if not target:
        return {
            "possible": False,
            "current_state": current,
            "reason": f"'{current}' is the initial state — cannot move backward",
        }
    return {
        "possible": True,
        "current_state": current,
        "target_state": target,
    }


def move_backward(
    doc_id: str,
    reason: Optional[str] = None,
    actor: str = "user",
) -> dict:
    """Move a document one step backward in the lifecycle.
    Records a history event. Does NOT remove prior history.
    """
    check = can_move_backward(doc_id)
    if not check["possible"]:
        return {"success": False, "error": check["reason"]}

    current = check["current_state"]
    target  = check["target_state"]

    db.execute(
        "UPDATE docs SET operator_state = ? WHERE doc_id = ?",
        (target, doc_id),
    )
    record_event(
        doc_id, current, target,
        actor=actor, direction="backward", reason=reason or "manual backward movement",
    )

    return {
        "success": True,
        "doc_id": doc_id,
        "previous_state": current,
        "new_state": target,
        "direction": "backward",
        "reason": reason,
    }


def undo_last(doc_id: str, actor: str = "user") -> dict:
    """Undo the most recent lifecycle change by reverting to its from_state.

    Appends an 'undo' history event — does NOT remove prior history records.
    If the document state was changed since the last history event, still
    reverts to the from_state of the most recent recorded event.
    """
    _ensure_table()
    last = db.fetchone(
        "SELECT * FROM lifecycle_history WHERE doc_id = ? ORDER BY event_ts DESC LIMIT 1",
        (doc_id,),
    )
    if not last:
        return {"success": False, "error": "No lifecycle history found for this document"}

    doc = db.fetchone("SELECT operator_state FROM docs WHERE doc_id = ?", (doc_id,))
    if not doc:
        return {"success": False, "error": "Document not found"}

    revert_to = last["from_state"]
    current   = doc["operator_state"]

    db.execute(
        "UPDATE docs SET operator_state = ? WHERE doc_id = ?",
        (revert_to, doc_id),
    )
    record_event(
        doc_id, current, revert_to,
        actor=actor,
        direction="undo",
        reason=f"Undo of event #{last['id']}: {last['from_state']} → {last['to_state']}",
    )

    return {
        "success": True,
        "doc_id": doc_id,
        "previous_state": current,
        "new_state": revert_to,
        "direction": "undo",
        "undone_event_id": last["id"],
    }
