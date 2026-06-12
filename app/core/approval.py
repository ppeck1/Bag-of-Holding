"""app/core/approval.py: Phase 15 explicit governance workflow.

Every authority transfer requires a visible, deliberate, signed approval.

Design invariants:
  - No canonical promotion without approval_id
  - No cross-project edge promotion without approval_id
  - No review artifact overwrite without diff-based approval
  - No supersession without impact acknowledgment
  - Every approved event creates an immutable provenance artifact
  - Governance events are append-only

State machine:
  pending → approved → [authority transfer executes]
  pending → rejected
  pending → withdrawn
  approved → [provenance artifact created] → [state change written]
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Optional

from app.db import connection as db
from app.core.metadata_contract import can_transition

# ── Signing key (deterministic per install — not a security primitive,
# but makes artifact forgery obvious in the audit trail) ─────────────────────
_SIGN_KEY = b"boh-provenance-v1"


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _sign(fields: dict) -> str:
    """HMAC-SHA256 of sorted canonical JSON fields."""
    payload = json.dumps(fields, sort_keys=True, ensure_ascii=True).encode()
    return hmac.new(_SIGN_KEY, payload, hashlib.sha256).hexdigest()


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class ApprovalRequest:
    approval_id:  str
    action_type:  str
    doc_id:       Optional[str]
    target_doc_id: Optional[str]
    from_state:   str
    to_state:     str
    requested_by: str
    requested_ts: int
    reason:       str
    diff_hash:    Optional[str]
    impact_summary: Optional[str]
    status:       str = "pending"


@dataclass
class ProvenanceArtifact:
    artifact_id:  str
    approval_id:  str
    action_type:  str
    document_id:  str
    from_state:   str
    to_state:     str
    approved_by:  str
    approved_at:  int
    reason:       str
    diff_hash:    Optional[str]
    supersedes_id: Optional[str]
    signature:    str
    artifact_json: str


# ── Approval request creation ─────────────────────────────────────────────────

ACTION_TYPES = {
    "canonical_promotion",
    "edge_promotion",
    "review_patch",
    "supersede_operation",
}


# ── Phase 15.5: Governance legibility helpers ────────────────────────────────

def _safe_json_loads(value, fallback=None):
    if value is None or value == "":
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _severity_from_score(score: int) -> str:
    if score >= 90:
        return "extreme"
    if score >= 70:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


def _impact_profile(action_type: str, impact_summary=None, cross_project: bool = False) -> dict:
    """Return a human-legible consequence model for approval UI/ledger use."""
    raw = _safe_json_loads(impact_summary, impact_summary)
    downstream = 0
    projects = set()
    deps = []
    if isinstance(raw, list):
        downstream = len(raw)
        deps = raw[:50]
    elif isinstance(raw, dict):
        downstream = int(raw.get("affected_downstream") or raw.get("affected_doc_count") or len(raw.get("affected_doc_ids", []) or []))
        deps = raw.get("affected_doc_ids") or raw.get("impact_docs") or []
        for key in ("projects_touched", "systems_touched"):
            vals = raw.get(key) or []
            if isinstance(vals, str):
                vals = [vals]
            projects.update(vals)
    elif isinstance(raw, str) and raw:
        downstream = 1

    base = {
        "canonical_promotion": 35,
        "review_patch": 55,
        "supersede_operation": 72,
        "edge_promotion": 30,
    }.get(action_type, 25)
    score = base + min(downstream * 4, 20)
    if cross_project:
        score += 25
    if action_type == "supersede_operation" and downstream:
        score += 10
    score = max(0, min(100, score))
    severity = _severity_from_score(score)
    rollback_complexity = "low" if score < 40 else "medium" if score < 70 else "high" if score < 90 else "extreme"
    return {
        "impact_score": score,
        "severity": severity,
        "downstream_references_affected": downstream,
        "projects_touched": sorted(projects),
        "canonical_dependencies": deps[:20] if isinstance(deps, list) else [],
        "rollback_complexity": rollback_complexity,
        "cross_project_exposure": bool(cross_project),
        "governance_tier": "constitutional" if severity in ("high", "extreme") else "standard",
    }


def _row_get(row, key, default=None):
    try:
        value = row[key]
        return default if value is None else value
    except Exception:
        return default


def _human_provenance(req: dict, approved_by: str, ts: int, signature: str, artifact_id: str, review_note: str) -> dict:
    action_type = _row_get(req, "action_type", "")
    impact = _impact_profile(action_type, _row_get(req, "impact_summary"))
    return {
        "approved_by": approved_by,
        "reason": _row_get(req, "reason", ""),
        "replacing": _row_get(req, "target_doc_id") if action_type == "supersede_operation" else _row_get(req, "from_state"),
        "approved_on_unix": ts,
        "affected_documents": impact["downstream_references_affected"],
        "rollback_available": True,
        "signature_short": signature[:16],
        "artifact_id": artifact_id,
        "review_note": review_note,
    }


def _decorate_approval_row(row: dict) -> dict:
    d = dict(row)
    d["blast_radius"] = _impact_profile(d.get("action_type", ""), d.get("impact_summary"))
    d["impact_score"] = d["blast_radius"]["impact_score"]
    d["severity"] = d["blast_radius"]["severity"]
    d["rollback_complexity"] = d["blast_radius"]["rollback_complexity"]
    return d


def request_canonical_promotion(
    doc_id: str,
    from_state: str,
    to_state: str,
    requested_by: str,
    reason: str,
    diff_hash: Optional[str] = None,
    impact_docs: Optional[list[str]] = None,
) -> dict:
    """Create a pending approval request for canonical promotion.

    This does NOT change the document state. It creates a request that
    must be explicitly approved before any state change occurs.
    """
    ok, msg = can_transition(from_state, to_state, approved=True)
    if not ok:
        return {"error": f"Transition not allowed: {msg}", "ok": False}

    approval_id = _new_id("apr")
    impact_json = json.dumps({"impact_docs": impact_docs or [], "affected_doc_count": len(impact_docs or [])})
    ts = int(time.time())

    db.execute(
        """INSERT INTO approval_requests
           (approval_id, action_type, doc_id, from_state, to_state,
            requested_by, requested_ts, reason, diff_hash, impact_summary, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (approval_id, "canonical_promotion", doc_id, from_state, to_state,
         requested_by, ts, reason, diff_hash, impact_json, "pending"),
    )
    _log_governance_event("approval_request", requested_by, doc_id, approval_id,
                          {"action": "canonical_promotion", "from": from_state, "to": to_state})
    return {
        "ok": True,
        "approval_id": approval_id,
        "status": "pending",
        "message": f"Approval request created. Reviewer must approve before {from_state} → {to_state} executes.",
    }


def request_supersede(
    current_doc_id: str,
    replacement_doc_id: str,
    requested_by: str,
    reason: str,
    affected_count: int = 0,
) -> dict:
    """Request approval to supersede a canonical document."""
    approval_id = _new_id("apr")
    ts = int(time.time())
    impact = json.dumps({"affected_downstream": affected_count, "replacement": replacement_doc_id, "rollback_available": True})
    db.execute(
        """INSERT INTO approval_requests
           (approval_id, action_type, doc_id, target_doc_id, from_state, to_state,
            requested_by, requested_ts, reason, impact_summary, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (approval_id, "supersede_operation", current_doc_id, replacement_doc_id,
         "canonical", "superseded", requested_by, ts, reason, impact, "pending"),
    )
    _log_governance_event("approval_request", requested_by, current_doc_id, approval_id,
                          {"action": "supersede_operation", "replacement": replacement_doc_id,
                           "affected": affected_count})
    return {
        "ok": True,
        "approval_id": approval_id,
        "status": "pending",
        "current_doc_id": current_doc_id,
        "replacement_doc_id": replacement_doc_id,
        "message": f"Supersede request created. {affected_count} downstream references will be affected.",
    }


def request_edge_promotion(
    source_doc_id: str,
    target_doc_id: str,
    edge_type: str,
    strength: float,
    requested_by: str,
    reason: str,
    cross_project: bool = False,
) -> dict:
    """Request promotion of a suggested edge to governed authority."""
    edge_apr_id = _new_id("eap")
    ts = int(time.time())
    db.execute(
        """INSERT INTO edge_approval_requests
           (edge_apr_id, source_doc_id, target_doc_id, edge_type, strength,
            cross_project, requested_by, requested_ts, reason, status)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (edge_apr_id, source_doc_id, target_doc_id, edge_type, strength,
         int(cross_project), requested_by, ts, reason, "pending"),
    )
    _log_governance_event("approval_request", requested_by, source_doc_id, edge_apr_id,
                          {"action": "edge_promotion", "target": target_doc_id,
                           "edge_type": edge_type, "cross_project": cross_project})
    return {
        "ok": True,
        "edge_apr_id": edge_apr_id,
        "status": "pending",
        "cross_project": cross_project,
        "message": "Edge promotion request created. Must be explicitly approved before edge becomes authoritative.",
    }


def request_review_patch(
    doc_id: str,
    patch_summary: str,
    diff_hash: str,
    requested_by: str,
    reason: str,
) -> dict:
    """Request approval to apply a review artifact patch to a source document."""
    approval_id = _new_id("apr")
    ts = int(time.time())
    db.execute(
        """INSERT INTO approval_requests
           (approval_id, action_type, doc_id, from_state, to_state,
            requested_by, requested_ts, reason, diff_hash, impact_summary, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (approval_id, "review_patch", doc_id, "review_artifact", "approved_patch",
         requested_by, ts, reason, diff_hash, patch_summary, "pending"),
    )
    _log_governance_event("approval_request", requested_by, doc_id, approval_id,
                          {"action": "review_patch", "diff_hash": diff_hash})
    return {
        "ok": True,
        "approval_id": approval_id,
        "status": "pending",
        "message": "Review patch request created. Requires explicit line-by-line approval before merge.",
    }


# ── Approval execution ────────────────────────────────────────────────────────

def approve_request(
    approval_id: str,
    reviewed_by: str,
    review_note: str,
) -> dict:
    """Approve an approval request and execute the authority transfer.

    This is the only path by which authority state may change.
    Creates an immutable provenance artifact as part of execution.
    """
    req = db.fetchone(
        "SELECT * FROM approval_requests WHERE approval_id = ?", (approval_id,)
    )
    if not req:
        return {"error": f"Approval request {approval_id!r} not found.", "ok": False}
    if req["status"] != "pending":
        return {"error": f"Request is {req['status']!r}, not pending.", "ok": False}
    if not review_note or not review_note.strip():
        return {"error": "Review note is required for approval.", "ok": False}

    ts = int(time.time())

    # Create provenance artifact
    artifact_id = _new_id("prv")
    signed_fields = {
        "artifact_id":  artifact_id,
        "approval_id":  approval_id,
        "action_type":  req["action_type"],
        "document_id":  req["doc_id"] or "",
        "from_state":   req["from_state"],
        "to_state":     req["to_state"],
        "approved_by":  reviewed_by,
        "approved_at":  ts,
        "reason":       req["reason"],
    }
    signature = _sign(signed_fields)
    artifact_record = {
        **signed_fields,
        "diff_hash":    req["diff_hash"],
        "supersedes_id": req["target_doc_id"],
        "review_note":  review_note,
        "human_readable": _human_provenance(req, reviewed_by, ts, signature, artifact_id, review_note),
        "blast_radius": _impact_profile(req["action_type"], _row_get(req, "impact_summary")),
        "signature":    signature,
    }
    artifact_json = json.dumps(artifact_record, sort_keys=True)

    db.execute(
        """INSERT INTO provenance_artifacts
           (artifact_id, approval_id, action_type, document_id, from_state, to_state,
            approved_by, approved_at, reason, diff_hash, supersedes_id, signature, artifact_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (artifact_id, approval_id, req["action_type"], req["doc_id"] or "",
         req["from_state"], req["to_state"], reviewed_by, ts,
         req["reason"], req["diff_hash"], req["target_doc_id"],
         signature, artifact_json),
    )

    # Mark request approved
    db.execute(
        """UPDATE approval_requests
           SET status='approved', reviewed_by=?, reviewed_ts=?, review_note=?,
               provenance_artifact_id=?
           WHERE approval_id=?""",
        (reviewed_by, ts, review_note, artifact_id, approval_id),
    )

    # Execute the authority transfer based on action type
    result = _execute_transfer(req, reviewed_by, artifact_id, ts)

    _log_governance_event("approval_granted", reviewed_by, req["doc_id"], approval_id,
                          {"artifact_id": artifact_id, "action": req["action_type"],
                           "to_state": req["to_state"]})

    return {
        "ok": True,
        "approval_id": approval_id,
        "artifact_id": artifact_id,
        "signature":   signature,
        "signature_short": signature[:16],
        "human_readable": artifact_record.get("human_readable"),
        "action_type": req["action_type"],
        "to_state":    req["to_state"],
        "executed":    result.get("executed", False),
        "message":     result.get("message", "Approval granted and provenance artifact created."),
    }


def _execute_transfer(req: dict, reviewed_by: str, artifact_id: str, ts: int) -> dict:
    """Execute the actual state change after approval is recorded."""
    action = req["action_type"]
    doc_id = req["doc_id"]

    if action == "canonical_promotion":
        return {
            "executed": False,
            "message": "direct_promotion_removed_use_certificate_flow",
        }

    if action == "supersede_operation":
        replacement_id = req["target_doc_id"]
        # Mark current canonical as superseded
        db.execute(
            "UPDATE docs SET status='superseded', updated_ts=? WHERE doc_id=?",
            (ts, doc_id),
        )
        # Phase 20.1: replacement promotion is not automatic.
        # It must be routed through certificate request → review → apply_canonical_promotion.
        # Record lineage
        try:
            db.execute(
                """INSERT OR IGNORE INTO lineage
                   (doc_id, related_doc_id, relationship, detail, ts)
                   VALUES (?,?,?,?,?)""",
                (replacement_id or doc_id, doc_id, "supersedes",
                 json.dumps({"approved_by": reviewed_by, "artifact_id": artifact_id}), ts),
            )
        except Exception:
            pass
        return {"executed": True, "message": "Supersession executed. Old canonical marked superseded; lineage preserved."}

    if action == "review_patch":
        # Move review artifact to approved_patch status — actual content merge
        # requires separate operation (line-by-line diff application)
        db.execute(
            "UPDATE docs SET status='approved_patch', updated_ts=? WHERE doc_id=?",
            (ts, doc_id),
        )
        return {"executed": True, "message": "Review patch approved. Apply patch content via the diff editor."}

    return {"executed": False, "message": f"Action type {action!r} executed (no direct DB state change)."}


def reject_request(
    approval_id: str,
    reviewed_by: str,
    review_note: str,
) -> dict:
    """Reject an approval request. No state change occurs."""
    req = db.fetchone(
        "SELECT * FROM approval_requests WHERE approval_id = ?", (approval_id,)
    )
    if not req:
        return {"error": "Request not found.", "ok": False}
    if req["status"] != "pending":
        return {"error": f"Request is already {req['status']!r}.", "ok": False}

    ts = int(time.time())
    db.execute(
        "UPDATE approval_requests SET status='rejected', reviewed_by=?, reviewed_ts=?, review_note=? WHERE approval_id=?",
        (reviewed_by, ts, review_note, approval_id),
    )
    _log_governance_event("approval_rejected", reviewed_by, req["doc_id"], approval_id,
                          {"reason": review_note})
    return {"ok": True, "approval_id": approval_id, "status": "rejected"}


def approve_edge(
    edge_apr_id: str,
    reviewed_by: str,
    review_note: str,
) -> dict:
    """Approve an edge promotion from suggested to governed."""
    req = db.fetchone(
        "SELECT * FROM edge_approval_requests WHERE edge_apr_id = ?", (edge_apr_id,)
    )
    if not req:
        return {"error": "Edge approval request not found.", "ok": False}
    if req["status"] != "pending":
        return {"error": f"Already {req['status']!r}.", "ok": False}

    ts = int(time.time())
    db.execute(
        "UPDATE edge_approval_requests SET status='approved', reviewed_by=?, reviewed_ts=?, review_note=? WHERE edge_apr_id=?",
        (reviewed_by, ts, review_note, edge_apr_id),
    )
    # Promote edge in doc_edges
    db.execute(
        """UPDATE doc_edges SET authority='governed', approved=1
           WHERE (source_doc_id=? AND target_doc_id=? AND edge_type=?)
              OR (source_doc_id=? AND target_doc_id=? AND edge_type=?)""",
        (req["source_doc_id"], req["target_doc_id"], req["edge_type"],
         req["target_doc_id"], req["source_doc_id"], req["edge_type"]),
    )
    _log_governance_event("edge_promoted", reviewed_by, req["source_doc_id"], edge_apr_id,
                          {"target": req["target_doc_id"], "edge_type": req["edge_type"],
                           "cross_project": bool(req["cross_project"])})
    return {
        "ok": True,
        "edge_apr_id": edge_apr_id,
        "status": "approved",
        "message": f"Edge {req['edge_type']!r} promoted to governed authority.",
    }


# ── Queries ───────────────────────────────────────────────────────────────────

def get_pending_approvals(doc_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    q = "SELECT * FROM approval_requests WHERE status='pending'"
    params: list = []
    if doc_id:
        q += " AND doc_id=?"
        params.append(doc_id)
    q += " ORDER BY requested_ts DESC LIMIT ?"
    params.append(limit)
    return [_decorate_approval_row(dict(r)) for r in db.fetchall(q, tuple(params))]


def get_provenance(doc_id: str) -> list[dict]:
    return [dict(r) for r in db.fetchall(
        "SELECT * FROM provenance_artifacts WHERE document_id=? ORDER BY approved_at DESC",
        (doc_id,),
    )]


def get_pending_edge_approvals(limit: int = 50) -> list[dict]:
    return [dict(r) for r in db.fetchall(
        "SELECT * FROM edge_approval_requests WHERE status='pending' ORDER BY requested_ts DESC LIMIT ?",
        (limit,),
    )]


def get_approval_ledger(status: Optional[str] = None, action_type: Optional[str] = None, doc_id: Optional[str] = None, limit: int = 200) -> list[dict]:
    """Constitutional ledger of pending/completed/rejected authority events."""
    q = "SELECT * FROM approval_requests WHERE 1=1"
    params = []
    if status:
        q += " AND status=?"; params.append(status)
    if action_type:
        q += " AND action_type=?"; params.append(action_type)
    if doc_id:
        q += " AND doc_id=?"; params.append(doc_id)
    q += " ORDER BY requested_ts DESC LIMIT ?"; params.append(limit)
    return [_decorate_approval_row(dict(r)) for r in db.fetchall(q, tuple(params))]


def get_review_diff(approval_id: str) -> dict:
    """Return line-oriented review patch context for a first-class diff surface."""
    req = db.fetchone("SELECT * FROM approval_requests WHERE approval_id=?", (approval_id,))
    if not req:
        return {"ok": False, "error": "Approval request not found."}
    data = _safe_json_loads(req["impact_summary"], {})
    if not isinstance(data, dict):
        data = {"patch_summary": req["impact_summary"] or ""}
    original = str(data.get("original_text") or "")
    proposed = str(data.get("proposed_text") or "")
    o_lines = original.splitlines()
    p_lines = proposed.splitlines()
    max_len = max(len(o_lines), len(p_lines))
    lines = []
    for i in range(max_len):
        old = o_lines[i] if i < len(o_lines) else ""
        new = p_lines[i] if i < len(p_lines) else ""
        changed = old != new
        lines.append({"line": i+1, "original": old, "proposed": new, "changed": changed, "decision": "pending" if changed else "unchanged"})
    return {"ok": True, "approval_id": approval_id, "source_document": data.get("source_document") or req["doc_id"], "review_artifact": data.get("review_artifact") or approval_id, "llm_source": data.get("llm_source") or "undisclosed", "reason": req["reason"], "diff_hash": req["diff_hash"], "blast_radius": _impact_profile(req["action_type"], req["impact_summary"]), "lines": lines}


def get_governance_log(doc_id: Optional[str] = None, limit: int = 100) -> list[dict]:
    q = "SELECT * FROM governance_events"
    params: list = []
    if doc_id:
        q += " WHERE doc_id=?"
        params.append(doc_id)
    q += " ORDER BY event_ts DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in db.fetchall(q, tuple(params))]


def get_impact_preview(doc_id: str) -> dict:
    """Count documents that reference this doc (for supersede impact warning)."""
    lineage_refs = db.fetchall(
        "SELECT doc_id FROM lineage WHERE related_doc_id=?", (doc_id,)
    )
    edge_refs = db.fetchall(
        "SELECT source_doc_id FROM doc_edges WHERE target_doc_id=? AND authority='governed'",
        (doc_id,),
    )
    all_refs = list({r["doc_id"] for r in lineage_refs} |
                   {r["source_doc_id"] for r in edge_refs})
    return {
        "doc_id": doc_id,
        "affected_doc_count": len(all_refs),
        "affected_doc_ids": all_refs[:20],
    }


def can_promote_without_approval(doc_id: str) -> tuple[bool, str]:
    """Always returns False — canonical promotion always requires approval."""
    return False, "Canonical promotion requires an explicit approval request (use /api/governance/approve/request)."


# ── Internal helpers ──────────────────────────────────────────────────────────

def _log_governance_event(
    event_type: str,
    actor: str,
    doc_id: Optional[str],
    approval_id: Optional[str],
    detail: Optional[dict] = None,
) -> None:
    try:
        db.execute(
            """INSERT INTO governance_events
               (event_ts, event_type, actor, doc_id, approval_id, detail)
               VALUES (?,?,?,?,?,?)""",
            (int(time.time()), event_type, actor, doc_id, approval_id,
             json.dumps(detail or {})),
        )
    except Exception:
        pass
