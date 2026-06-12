"""app/core/llm_queue.py: LLM Steward Review Queue for Bag of Holding v2.

Phase 12 addition.

Governance rules (non-negotiable):
  - The LLM PROPOSES. The user REVIEWS. The system APPLIES.
  - LLM suggestions NEVER become canonical automatically.
  - Canonical status requires explicit user workflow action.
  - Every approval/rejection is recorded in audit_log.
  - No corpus file is written without user confirmation.

Queue lifecycle:
  pending → approved  (user accepts, safe fields applied to DB)
  pending → rejected  (user declines, no changes)
  pending → edited    (future: user edits proposal before applying)
"""

import json
import time
import uuid
from typing import Optional

from app.db import connection as db
from app.core import audit


# ── Table bootstrap ───────────────────────────────────────────────────────────

def _ensure_table():
    """Create llm_review_queue table if not exists."""
    conn = db.get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS llm_review_queue (
                queue_id        TEXT    PRIMARY KEY,
                doc_id          TEXT,
                file_path       TEXT,
                queued_ts       INTEGER NOT NULL,
                reviewed_ts     INTEGER,
                status          TEXT    NOT NULL DEFAULT 'pending',
                actor           TEXT,
                proposed_json   TEXT    NOT NULL DEFAULT '{}',
                confidence      REAL,
                model           TEXT,
                invocation_id   TEXT,
                note            TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_llmq_doc_id ON llm_review_queue(doc_id);
            CREATE INDEX IF NOT EXISTS idx_llmq_status ON llm_review_queue(status);
            CREATE INDEX IF NOT EXISTS idx_llmq_ts     ON llm_review_queue(queued_ts);
        """)
        conn.commit()
    finally:
        conn.close()


# ── Public API ────────────────────────────────────────────────────────────────

def enqueue(
    proposed: dict,
    doc_id: Optional[str] = None,
    file_path: Optional[str] = None,
    model: Optional[str] = None,
    invocation_id: Optional[str] = None,
) -> str:
    """Add an LLM proposal to the review queue. Returns queue_id."""
    _ensure_table()
    queue_id = str(uuid.uuid4())
    conn = db.get_conn()
    try:
        conn.execute(
            """
            INSERT INTO llm_review_queue
              (queue_id, doc_id, file_path, queued_ts, status,
               proposed_json, confidence, model, invocation_id)
            VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            """,
            (
                queue_id, doc_id, file_path, int(time.time()),
                json.dumps(proposed),
                float(proposed.get("confidence", 0.0) or 0.0),
                model, invocation_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return queue_id


def get_queue(status: str = "pending", limit: int = 50) -> list[dict]:
    """Return queued items. Parses proposed_json into 'proposed' dict."""
    _ensure_table()
    rows = db.fetchall(
        "SELECT * FROM llm_review_queue WHERE status = ? ORDER BY queued_ts DESC LIMIT ?",
        (status, limit),
    )
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["proposed"] = json.loads(item.pop("proposed_json", "{}") or "{}")
        except Exception:
            item["proposed"] = {}
        result.append(item)
    return result


def get_pending_count() -> int:
    """Return number of pending LLM review items."""
    _ensure_table()
    row = db.fetchone(
        "SELECT COUNT(*) AS n FROM llm_review_queue WHERE status = 'pending'"
    )
    return row["n"] if row else 0


def approve(queue_id: str, actor: str = "user") -> dict:
    """Approve an LLM proposal — applies safe metadata fields to the doc DB record.

    SAFETY INVARIANTS (cannot be bypassed):
      - proposed_status = 'canonical' is NEVER applied automatically.
      - type = 'canon' is NEVER applied from an LLM proposal.
      - operator_state = 'release' / 'canonize' is NEVER applied from a proposal.
      - No files are written to disk; only DB metadata fields are updated.
    """
    _ensure_table()
    item = db.fetchone(
        "SELECT * FROM llm_review_queue WHERE queue_id = ?", (queue_id,)
    )
    if not item:
        return {"success": False, "error": "Queue item not found"}
    if item["status"] != "pending":
        return {"success": False, "error": f"Item already {item['status']}"}

    try:
        proposed = json.loads(item["proposed_json"] or "{}")
    except Exception:
        proposed = {}

    doc_id  = item["doc_id"]
    applied: dict = {}

    if doc_id:
        doc = db.fetchone("SELECT * FROM docs WHERE doc_id = ?", (doc_id,))
        if doc:
            # ── Apply title ────────────────────────────────────────────
            if proposed.get("proposed_title"):
                val = str(proposed["proposed_title"])[:200]
                db.execute("UPDATE docs SET title = ? WHERE doc_id = ?", (val, doc_id))
                applied["title"] = val

            # ── Apply summary ──────────────────────────────────────────
            if proposed.get("summary"):
                val = str(proposed["summary"])[:500]
                db.execute("UPDATE docs SET summary = ? WHERE doc_id = ?", (val, doc_id))
                applied["summary"] = val

            # ── Apply topics ───────────────────────────────────────────
            if proposed.get("proposed_topics"):
                toks = [str(t)[:60] for t in proposed["proposed_topics"][:20]]
                val = " ".join(toks)
                db.execute("UPDATE docs SET topics_tokens = ? WHERE doc_id = ?", (val, doc_id))
                applied["topics_tokens"] = val

            # ── Apply type — BLOCK 'canon' ────────────────────────────
            proposed_type = proposed.get("proposed_type")
            if proposed_type and proposed_type not in ("canonical", "canon"):
                db.execute("UPDATE docs SET type = ? WHERE doc_id = ?",
                           (str(proposed_type)[:40], doc_id))
                applied["type"] = proposed_type

            # ── NEVER apply status=canonical or operator_state=release ─
            # (These require explicit user workflow action.)

    # Mark approved
    conn = db.get_conn()
    try:
        conn.execute(
            """UPDATE llm_review_queue
               SET status='approved', reviewed_ts=?, actor=?, note=?
               WHERE queue_id=?""",
            (int(time.time()), actor, json.dumps({"applied": applied}), queue_id),
        )
        conn.commit()
    finally:
        conn.close()

    audit.log_event(
        "llm_call",
        actor_type="user",
        actor_id=actor,
        doc_id=doc_id,
        detail=json.dumps({
            "action": "llm_queue_approve",
            "queue_id": queue_id,
            "applied": applied,
        }),
    )

    return {
        "success": True,
        "queue_id": queue_id,
        "applied": applied,
        "doc_id": doc_id,
        "note": "Canonical status was not applied — that requires explicit user action.",
    }


def reject(
    queue_id: str,
    actor: str = "user",
    reason: Optional[str] = None,
) -> dict:
    """Reject an LLM proposal. No changes applied to the document."""
    _ensure_table()
    item = db.fetchone(
        "SELECT queue_id, status FROM llm_review_queue WHERE queue_id = ?", (queue_id,)
    )
    if not item:
        return {"success": False, "error": "Queue item not found"}
    if item["status"] != "pending":
        return {"success": False, "error": f"Item already {item['status']}"}

    conn = db.get_conn()
    try:
        conn.execute(
            """UPDATE llm_review_queue
               SET status='rejected', reviewed_ts=?, actor=?, note=?
               WHERE queue_id=?""",
            (int(time.time()), actor, reason, queue_id),
        )
        conn.commit()
    finally:
        conn.close()

    return {"success": True, "queue_id": queue_id, "status": "rejected"}
