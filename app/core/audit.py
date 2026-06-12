"""app/core/audit.py: Audit logging for Bag of Holding v2 governance layer.

Phase 10 addition. Every significant action emits an audit event.
Append-only — audit records are never deleted.

Event types:
  index       — library indexed
  edit        — document opened for editing
  save        — document saved to disk
  run         — code block executed
  llm_call    — LLM invocation triggered
  promote     — document promoted to canon
  conflict    — conflict detected
  policy      — workspace policy changed
"""

import json
import time
from typing import Optional

from app.db import connection as db


def log_event(
    event_type: str,
    actor_type: str = "system",
    actor_id: Optional[str] = None,
    doc_id: Optional[str] = None,
    run_id: Optional[str] = None,
    invocation_id: Optional[str] = None,
    workspace: Optional[str] = None,
    detail: Optional[str] = None,
) -> int:
    """Append an audit event. Returns the inserted rowid."""
    conn = db.get_conn()
    try:
        cur = conn.execute(
            """
            INSERT INTO audit_log
              (event_ts, event_type, actor_type, actor_id,
               doc_id, run_id, invocation_id, workspace, detail)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                int(time.time()), event_type, actor_type, actor_id,
                doc_id, run_id, invocation_id, workspace, detail,
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_events(
    doc_id: Optional[str] = None,
    event_type: Optional[str] = None,
    actor_type: Optional[str] = None,
    since_ts: Optional[int] = None,
    limit: int = 50,
) -> list[dict]:
    """Query audit events with optional filters."""
    query = "SELECT * FROM audit_log WHERE 1=1"
    params: list = []
    if doc_id:
        query += " AND doc_id = ?"
        params.append(doc_id)
    if event_type:
        query += " AND event_type = ?"
        params.append(event_type)
    if actor_type:
        query += " AND actor_type = ?"
        params.append(actor_type)
    if since_ts:
        query += " AND event_ts >= ?"
        params.append(since_ts)
    query += " ORDER BY event_ts DESC LIMIT ?"
    params.append(limit)
    return db.fetchall(query, tuple(params))
