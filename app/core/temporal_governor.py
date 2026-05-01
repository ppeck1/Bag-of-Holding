"""app/core/temporal_governor.py: Temporal Coherence Governor.

Phase 24.2 — Substrate correction. Not feature expansion.

This module installs enforced temporal coherence infrastructure:

    Fix A — Drift Detection Layer
        Continuous evaluation of last_verified_at, valid_until, drift_risk.
        Time passing is not verification. Continuation is not resolution.

    Fix B — Nanny Clause Enforcement
        When drift is detected: interrupt, reduce, re-anchor.
        Mandatory trinary output (KNOWN / UNKNOWN / BLOCKED).
        No freeform narrative until re-anchor completes.

    Fix C — Single Plane Resume Rule
        After re-anchor: one active plane only.
        Multi-plane simultaneous recovery creates false synthesis.
        Expansion to additional planes requires explicit promotion.

    Fix D — Open Item Registry
        Unresolved ambiguity persists visibly.
        No disappearance by recency. No burial by token distance.
        Zero remains load-bearing.

    Fix E — Temporal Laundering Warning
        Elapsed time does not constitute verification.
        Silence must not be interpreted as resolution.

    Fix F (substrate) — Integrity panel aggregation function.
        Full UI panel is in temporal_governor_routes.py.

Design invariant: this module never promotes canon, never resolves
uncertainty autonomously, and never allows LLM continuity to stand
in for verification.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone, timedelta
from typing import Any

from app.db import connection as db
from app.core.audit import log_event
from app.core.lattice_graph import get_node, LatticeNode
from app.core.coherence_decay import (
    evaluate_node_coherence,
    PLANE_DECAY_CONSTANTS,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DRIFT_RISK_LEVELS = ("low", "moderate", "high")

# Drift thresholds (coherence score bands, matching Phase 24.1 scoring)
DRIFT_THRESHOLD_HIGH     = 0.45   # coherence below this → high drift risk
DRIFT_THRESHOLD_MODERATE = 0.65   # coherence below this → moderate drift risk

# Approaching expiry window (days before valid_until counts as pressure)
EXPIRY_PRESSURE_DAYS = 7

# Nanny Clause: anchor events older than this are considered stale
ANCHOR_STALE_DAYS = 30

VALID_PLANES = {
    "evidence", "internal", "review", "verification",
    "governance", "canonical", "conflict", "archive",
    "quarantine", "operational", "narrative", "supporting",
}

OPEN_ITEM_STATUSES = ("open", "expired", "resolved")
DRIFT_PRIORITY_LEVELS = ("low", "moderate", "high")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _item_id(plane_boundary: str, node_id: str | None, description: str) -> str:
    raw = f"{plane_boundary}|{node_id or ''}|{description}|{time.time_ns()}".encode()
    return "OI_" + hashlib.sha1(raw).hexdigest()[:14]


def _anchor_id(node_id: str, trigger_reason: str) -> str:
    raw = f"{node_id}|{trigger_reason}|{time.time_ns()}".encode()
    return "ANC_" + hashlib.sha1(raw).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Fix A — Drift Detection Layer
# ---------------------------------------------------------------------------

@dataclass
class DriftState:
    node_id: str
    last_verified_at: str | None
    valid_until: str | None
    refresh_required: bool
    drift_risk: str          # low | moderate | high
    drift_reason: str
    coherence: float
    decay_state: str
    temporal_ambiguity: bool
    context_ref: dict[str, Any] = field(default_factory=dict)
    evaluated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _last_verified_at(node: LatticeNode) -> str | None:
    """Return the most recent verification timestamp for this node."""
    md = node.metadata or {}
    payload = md.get("payload") or {}
    # Prefer refresh events from the DB, then payload timestamps.
    rows = db.fetchall(
        "SELECT created_at FROM coherence_refresh_events WHERE node_id=? ORDER BY created_at DESC LIMIT 1",
        (node.id,),
    )
    if rows:
        return rows[0]["created_at"]
    for key in ("observed_at", "updated_at", "created_at"):
        v = payload.get(key)
        if v:
            dt = _parse_dt(v)
            if dt and dt.timestamp() > 86400:
                return v
    return None


def _context_ref_from_node(node: LatticeNode) -> dict[str, Any]:
    return dict(node.context_refs or []) if isinstance(node.context_refs, dict) else {}


def _drift_risk_from_score(
    coherence: float,
    decay_state: str,
    valid_until: str | None,
    temporal_ambiguity: bool,
) -> tuple[str, str]:
    """Compute drift_risk and drift_reason from available evidence."""
    now = datetime.now(timezone.utc)
    reasons: list[str] = []

    # Temporal ambiguity always → high
    if temporal_ambiguity:
        return "high", "temporal_ambiguity: no verified timestamp; containment required"

    # Expired valid_until → high
    vu = _parse_dt(valid_until)
    if vu and vu <= now:
        reasons.append("valid_until elapsed")
        return "high", "; ".join(reasons) or "valid_until elapsed"

    # Approaching expiry → at least moderate
    expiry_pressure = False
    if vu:
        days_remaining = (vu - now).total_seconds() / 86400.0
        if days_remaining <= EXPIRY_PRESSURE_DAYS:
            expiry_pressure = True
            reasons.append(f"valid_until approaching ({days_remaining:.1f}d remaining)")

    # Coherence thresholds
    if coherence < DRIFT_THRESHOLD_HIGH:
        reasons.append(f"coherence={coherence:.3f} below high-risk threshold")
        return "high", "; ".join(reasons)
    if coherence < DRIFT_THRESHOLD_MODERATE or expiry_pressure:
        reasons.append(f"coherence={coherence:.3f} in moderate-risk band")
        return "moderate", "; ".join(reasons)

    # Explicitly flagged decay states
    if decay_state in {"critical_decay", "refresh_required"}:
        reasons.append(f"decay_state={decay_state}")
        return "high", "; ".join(reasons)
    if decay_state == "stale":
        reasons.append("stale decay state")
        return "moderate", "; ".join(reasons)

    return "low", "coherence within acceptable range; valid_until active"


def evaluate_drift(node_or_card_id: str) -> dict[str, Any]:
    """Fix A: Continuously evaluate drift risk for one node.

    Returns a DriftState describing temporal integrity.
    Time passing is not verification. This function never infers resolution
    from continuity.
    """
    db.init_db()
    node = get_node(node_or_card_id)
    if not node:
        return {"ok": False, "errors": [f"node not found: {node_or_card_id}"]}

    coherence_result = evaluate_node_coherence(node.id)
    if not coherence_result.get("ok"):
        return {"ok": False, "errors": coherence_result.get("errors", [])}

    score = coherence_result["score"]
    coherence = score["coherence"]
    decay_state = score["decay_state"]
    temporal_ambiguity = score.get("temporal_ambiguity", False)
    valid_until = score.get("valid_until")
    refresh_required = score.get("refresh_required", False)

    last_verified = _last_verified_at(node)
    drift_risk, drift_reason = _drift_risk_from_score(
        coherence, decay_state, valid_until, temporal_ambiguity
    )

    state = DriftState(
        node_id=node.id,
        last_verified_at=last_verified,
        valid_until=valid_until,
        refresh_required=refresh_required,
        drift_risk=drift_risk,
        drift_reason=drift_reason,
        coherence=round(coherence, 6),
        decay_state=decay_state,
        temporal_ambiguity=temporal_ambiguity,
        evaluated_at=_now_iso(),
    )

    return {
        "ok": True,
        "drift": state.to_dict(),
        "nanny_required": drift_risk == "high",
    }


def evaluate_drift_all(plane: str | None = None, limit: int = 500) -> dict[str, Any]:
    """Evaluate drift across all nodes. Returns risk-sorted results."""
    from app.core.lattice_graph import list_nodes
    nodes = list_nodes(plane=plane, active_only=False, limit=limit)
    results: list[dict[str, Any]] = []
    counts = {"low": 0, "moderate": 0, "high": 0}
    for n in nodes:
        r = evaluate_drift(n.id)
        if r.get("ok"):
            drift = r["drift"]
            results.append(drift)
            counts[drift["drift_risk"]] = counts.get(drift["drift_risk"], 0) + 1
    priority = {"high": 0, "moderate": 1, "low": 2}
    results.sort(key=lambda d: priority.get(d["drift_risk"], 3))
    return {"ok": True, "counts": counts, "results": results, "total": len(results)}


# ---------------------------------------------------------------------------
# Fix B — Nanny Clause Enforcement
# ---------------------------------------------------------------------------

@dataclass
class AnchorEvent:
    anchor_id: str
    node_id: str
    triggered_by: str
    trigger_reason: str
    drift_risk_at_trigger: str
    forced_d: int
    forced_m: str
    active_plane: str | None
    trinary: dict[str, Any]
    status: str          # active | resolved
    created_at: str
    resolved_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _build_trinary(node: LatticeNode, drift: DriftState) -> dict[str, Any]:
    """Build the mandatory KNOWN/UNKNOWN/BLOCKED trinary output for a node."""
    md = node.metadata or {}
    payload = md.get("payload") or {}
    constraints = md.get("constraints") or {}

    known: list[str] = []
    unknown: list[str] = []
    blocked: list[str] = []

    # KNOWN: only what has explicit verification evidence
    if node.q_quality is not None and node.q_quality >= 0.7:
        known.append(f"node type is {node.type!r} (q={node.q_quality:.2f})")
    if node.plane:
        known.append(f"last registered plane: {node.plane}")
    if drift.last_verified_at:
        known.append(f"last verified at: {drift.last_verified_at}")

    # UNKNOWN: things that are unresolved or ambiguous
    if drift.temporal_ambiguity:
        unknown.append("observation timestamp — cannot determine freshness")
    if node.q_quality is None or node.q_quality < 0.7:
        unknown.append(f"epistemic quality (q={node.q_quality})")
    if node.c_confidence is None or node.c_confidence < 0.5:
        unknown.append(f"confidence level (c={node.c_confidence})")
    if not drift.last_verified_at:
        unknown.append("last verification event — none recorded")
    if drift.drift_risk in {"moderate", "high"} and not drift.temporal_ambiguity:
        unknown.append(f"current accuracy — drift_risk={drift.drift_risk}")

    # BLOCKED: things that have explicitly expired or contradicted
    if drift.valid_until:
        vu = _parse_dt(drift.valid_until)
        if vu and vu <= datetime.now(timezone.utc):
            blocked.append(f"validity window expired at {drift.valid_until}")
    if drift.decay_state in {"critical_decay", "stale"}:
        blocked.append(f"canonical use blocked by decay_state={drift.decay_state}")
    if payload.get("correction_status") in {"contested", "revoked"}:
        blocked.append(f"correction_status={payload['correction_status']}")

    # Determine resolution plane
    auth_plane = node.authority_plane or "verification"
    if drift.drift_risk == "high":
        resolution_planes = ["governance", auth_plane]
    elif drift.drift_risk == "moderate":
        resolution_planes = [auth_plane, "verification"]
    else:
        resolution_planes = [auth_plane]

    return {
        "KNOWN": known if known else ["— no verified facts available —"],
        "UNKNOWN": unknown if unknown else ["— no unresolved items —"],
        "BLOCKED": blocked if blocked else ["— no blocked items —"],
        "next_valid_resolution_plane": " | ".join(dict.fromkeys(resolution_planes)),
        "mode": "re_anchor",
        "resume_blocked_until": "re_anchor completes with single_active_plane promotion",
    }


def trigger_re_anchor(
    node_or_card_id: str,
    actor: str,
    trigger_reason: str = "drift condition detected",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fix B: Nanny Clause enforcement — interrupt, reduce, re-anchor.

    Forces d=0, m=contain on the node. Creates an auditable anchor event.
    Returns the mandatory trinary output form.

    This must never be bypassed by conversational continuity.
    """
    db.init_db()
    if not actor or actor.strip().lower() in {"auto", "autonomous", "llm"}:
        return {"ok": False, "errors": ["actor must identify a human/reviewer; autonomous re-anchor is illegal"]}

    node = get_node(node_or_card_id)
    if not node:
        return {"ok": False, "errors": [f"node not found: {node_or_card_id}"]}

    drift_result = evaluate_drift(node.id)
    if not drift_result.get("ok"):
        return drift_result
    drift = DriftState(**drift_result["drift"])

    # Fix B: force d=0, m=contain on the underlying card/doc
    _force_containment(node.id)

    trinary = _build_trinary(node, drift)
    aid = _anchor_id(node.id, trigger_reason)
    now = _now_iso()

    event = AnchorEvent(
        anchor_id=aid,
        node_id=node.id,
        triggered_by=actor,
        trigger_reason=trigger_reason,
        drift_risk_at_trigger=drift.drift_risk,
        forced_d=0,
        forced_m="contain",
        active_plane=None,      # Fix C: no active plane until explicitly promoted
        trinary=trinary,
        status="active",
        created_at=now,
        metadata=metadata or {},
    )
    _persist_anchor(event)

    try:
        log_event(
            "temporal_re_anchor",
            actor_type="human",
            actor_id=actor,
            detail=json.dumps({
                "anchor_id": aid,
                "node_id": node.id,
                "drift_risk": drift.drift_risk,
                "trigger_reason": trigger_reason,
            }),
        )
    except Exception:
        pass

    return {
        "ok": True,
        "anchor_id": aid,
        "node_id": node.id,
        "forced_state": {"d": 0, "m": "contain"},
        "trinary_output": trinary,
        "drift": drift.to_dict(),
        "message": (
            "We are no longer operating on verified state.\n"
            "Reducing to trinary. No freeform narrative until re-anchor completes."
        ),
    }


def _force_containment(node_id: str) -> None:
    """Force d=0, m=contain on the doc and card backing this node."""
    card_id = node_id[5:] if node_id.startswith("NODE:") else node_id
    # Update docs table if this is a doc-backed card
    db.execute(
        """UPDATE docs SET epistemic_d=0, epistemic_m='contain',
           authority_state='contained'
           WHERE doc_id=(SELECT doc_id FROM cards WHERE id=? LIMIT 1)""",
        (card_id,),
    )
    # Update card payload
    db.execute(
        """UPDATE cards SET
           payload_json=json_set(COALESCE(payload_json,'{}'),
               '$.d', 0,
               '$.m', 'contain',
               '$.forced_containment', 1,
               '$.forced_at', ?)
           WHERE id=?""",
        (_now_iso(), card_id),
    )


def _persist_anchor(event: AnchorEvent) -> None:
    db.execute(
        """INSERT OR REPLACE INTO anchor_events
             (anchor_id, node_id, triggered_by, trigger_reason,
              drift_risk_at_trigger, forced_d, forced_m, active_plane,
              trinary_json, status, created_at, resolved_at, metadata_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            event.anchor_id, event.node_id, event.triggered_by,
            event.trigger_reason, event.drift_risk_at_trigger,
            event.forced_d, event.forced_m, event.active_plane,
            json.dumps(event.trinary), event.status, event.created_at,
            event.resolved_at, json.dumps(event.metadata),
        ),
    )


def _row_to_anchor(row: dict[str, Any]) -> AnchorEvent:
    return AnchorEvent(
        anchor_id=row["anchor_id"],
        node_id=row["node_id"],
        triggered_by=row["triggered_by"],
        trigger_reason=row["trigger_reason"],
        drift_risk_at_trigger=row["drift_risk_at_trigger"],
        forced_d=int(row.get("forced_d") or 0),
        forced_m=row.get("forced_m") or "contain",
        active_plane=row.get("active_plane"),
        trinary=_json_loads(row.get("trinary_json"), {}),
        status=row.get("status") or "active",
        created_at=row["created_at"],
        resolved_at=row.get("resolved_at"),
        metadata=_json_loads(row.get("metadata_json"), {}),
    )


def get_anchor(anchor_id: str) -> dict[str, Any] | None:
    row = db.fetchone("SELECT * FROM anchor_events WHERE anchor_id=?", (anchor_id,))
    return _row_to_anchor(dict(row)).to_dict() if row else None


def list_anchors(
    node_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    q = "SELECT * FROM anchor_events WHERE 1=1"
    params: list[Any] = []
    if node_id:
        nid = node_id if node_id.startswith("NODE:") else f"NODE:{node_id}"
        q += " AND node_id=?"
        params.append(nid)
    if status:
        q += " AND status=?"
        params.append(status)
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    return [_row_to_anchor(dict(r)).to_dict() for r in db.fetchall(q, tuple(params))]


# ---------------------------------------------------------------------------
# Fix C — Single Plane Resume Rule
# ---------------------------------------------------------------------------

def resume_on_single_plane(
    anchor_id: str,
    active_plane: str,
    actor: str,
    promotion_reason: str,
) -> dict[str, Any]:
    """Fix C: After re-anchor, grant resume in exactly one plane.

    Multi-plane simultaneous recovery creates false synthesis.
    Expansion beyond this single plane requires explicit subsequent promotion.
    """
    db.init_db()
    if not actor or actor.strip().lower() in {"auto", "autonomous", "llm"}:
        return {"ok": False, "errors": ["actor must be a human reviewer"]}

    plane_norm = active_plane.strip().lower()
    if plane_norm not in VALID_PLANES:
        return {"ok": False, "errors": [f"invalid plane {active_plane!r}; must be one of {sorted(VALID_PLANES)}"]}

    row = db.fetchone("SELECT * FROM anchor_events WHERE anchor_id=?", (anchor_id,))
    if not row:
        return {"ok": False, "errors": ["anchor event not found"]}

    event = _row_to_anchor(dict(row))
    if event.status != "active":
        return {"ok": False, "errors": [f"anchor is {event.status!r}; only active anchors can resume"]}
    if event.active_plane is not None:
        return {
            "ok": False,
            "errors": [
                f"anchor already resumed on plane {event.active_plane!r}. "
                "Expansion to additional planes requires a new explicit promotion, not re-use of this anchor."
            ],
        }

    db.execute(
        """UPDATE anchor_events SET active_plane=?, metadata_json=json_set(
               COALESCE(metadata_json,'{}'), '$.resume_actor', ?, '$.promotion_reason', ?, '$.resumed_at', ?)
           WHERE anchor_id=?""",
        (plane_norm, actor, promotion_reason, _now_iso(), anchor_id),
    )

    try:
        log_event(
            "temporal_single_plane_resume",
            actor_type="human",
            actor_id=actor,
            detail=json.dumps({
                "anchor_id": anchor_id,
                "node_id": event.node_id,
                "active_plane": plane_norm,
                "promotion_reason": promotion_reason,
            }),
        )
    except Exception:
        pass

    return {
        "ok": True,
        "anchor_id": anchor_id,
        "node_id": event.node_id,
        "active_plane": plane_norm,
        "resume_scope": "single-plane-only",
        "expansion_policy": (
            "Additional planes require explicit promotion. "
            "Inference from this anchor to other planes is prohibited."
        ),
    }


# ---------------------------------------------------------------------------
# Fix D — Open Item Registry
# ---------------------------------------------------------------------------

@dataclass
class OpenItem:
    id: str
    plane_boundary: str
    created_at: str
    valid_until: str | None
    resolution_authority: str
    status: str              # open | expired | resolved
    drift_priority: str      # low | moderate | high
    node_id: str | None = None
    description: str = ""
    context_ref: dict[str, Any] = field(default_factory=dict)
    resolved_at: str | None = None
    resolved_by: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _row_to_open_item(row: dict[str, Any]) -> OpenItem:
    return OpenItem(
        id=row["id"],
        plane_boundary=row["plane_boundary"],
        created_at=row["created_at"],
        valid_until=row.get("valid_until"),
        resolution_authority=row["resolution_authority"],
        status=row["status"],
        drift_priority=row["drift_priority"],
        node_id=row.get("node_id"),
        description=row.get("description") or "",
        context_ref=_json_loads(row.get("context_ref_json"), {}),
        resolved_at=row.get("resolved_at"),
        resolved_by=row.get("resolved_by"),
        metadata=_json_loads(row.get("metadata_json"), {}),
    )


def create_open_item(
    plane_boundary: str,
    resolution_authority: str,
    drift_priority: str,
    description: str,
    node_id: str | None = None,
    valid_until: str | None = None,
    context_ref: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fix D: Register an unresolved ambiguity in the Open Item Registry.

    Items persist until explicitly resolved. They do not disappear by recency
    or burial by token distance. Zero remains load-bearing.
    """
    db.init_db()
    errors: list[str] = []
    if not plane_boundary or "|" not in plane_boundary:
        errors.append("plane_boundary must denote a transition, e.g. 'evidence|verification'")
    if drift_priority not in DRIFT_PRIORITY_LEVELS:
        errors.append(f"drift_priority must be one of {DRIFT_PRIORITY_LEVELS}")
    if not resolution_authority or not resolution_authority.strip():
        errors.append("resolution_authority is required")
    if not description or len(description.strip()) < 8:
        errors.append("description must meaningfully describe the unresolved ambiguity")
    if errors:
        return {"ok": False, "errors": errors}

    item_id = _item_id(plane_boundary, node_id, description)
    now = _now_iso()
    # Phase 24.4: every open item carries Daenary Custodian State.
    # Queue status is workflow; this state is the mutation substrate.
    from app.core.custodian_state import normalize_custodian_state
    metadata = metadata or {}
    custodian_state = normalize_custodian_state(metadata, context_ref=context_ref or {}, valid_until=valid_until)
    metadata["daenary_custodian_state"] = custodian_state

    item = OpenItem(
        id=item_id,
        plane_boundary=plane_boundary,
        created_at=now,
        valid_until=valid_until,
        resolution_authority=resolution_authority.strip(),
        status="open",
        drift_priority=drift_priority,
        node_id=node_id,
        description=description.strip(),
        context_ref=context_ref or {},
        metadata=metadata,
    )
    db.execute(
        """INSERT OR REPLACE INTO open_items
             (id, plane_boundary, created_at, valid_until, resolution_authority,
              status, drift_priority, node_id, description,
              context_ref_json, resolved_at, resolved_by, metadata_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            item.id, item.plane_boundary, item.created_at, item.valid_until,
            item.resolution_authority, item.status, item.drift_priority,
            item.node_id, item.description, json.dumps(item.context_ref),
            None, None, json.dumps(item.metadata),
        ),
    )
    return {"ok": True, "item": item.to_dict()}


def resolve_open_item(
    item_id: str,
    resolved_by: str,
    resolution_note: str = "",
    *,
    authority_validated: bool = False,
) -> dict[str, Any]:
    """Mark an open item as resolved only after server-side authority validation.

    Phase 24.3 hardening: this function is the final canonical-resolution
    mutation gate. It no longer accepts generic human approval. Either:
      1) authority_gated_resolve has already validated identity/team/role/scope
         and calls this with authority_validated=True, or
      2) the legacy direct caller is accepted only when resolved_by exactly
         matches resolution_authority and the item has no expanded authority
         contract.

    This prevents the old bypass where any named human could resolve an item.
    """
    db.init_db()
    if not resolved_by or resolved_by.strip().lower() in {"auto", "autonomous", "llm", "system"}:
        return {"ok": False, "errors": ["resolved_by must identify a legitimate human authority"]}
    row = db.fetchone("SELECT * FROM open_items WHERE id=?", (item_id,))
    if not row:
        return {"ok": False, "errors": ["open item not found"]}
    item = _row_to_open_item(dict(row))
    if item.status == "resolved":
        return {"ok": False, "errors": ["item is already resolved"]}

    metadata = item.metadata or {}
    has_expanded_contract = bool(metadata.get("required_authority") or metadata.get("authority_contract"))
    if not authority_validated:
        # Legacy safety path: direct resolve is identity-only and only legal for
        # simple items that did not declare team/role/scope requirements.
        if has_expanded_contract or resolved_by.strip().lower() != item.resolution_authority.strip().lower():
            from app.core.authority_guard import ActorProfile, validate_resolution_authority
            auth = validate_resolution_authority(
                ActorProfile(actor_id=resolved_by.strip()),
                item.resolution_authority,
                item_id,
                "open_item",
                {**metadata, "context_ref": item.context_ref},
            )
            return {
                "ok": False,
                "status": "rejected",
                "reason": "authority_mismatch",
                "authority_valid": False,
                "failure_type": auth.get("failure_type", ["identity"]),
                "required_authority": auth.get("required_authority"),
                "attempted_by": resolved_by,
                "errors": ["server-side authority validation failed; use /api/governance/resolve with actor identity/team/role/scope"],
            }

    now = _now_iso()
    db.execute(
        """UPDATE open_items SET status='resolved', resolved_at=?, resolved_by=?,
           metadata_json=json_set(COALESCE(metadata_json,'{}'), '$.resolution_note', ?, '$.authority_validated', ?)
           WHERE id=?""",
        (now, resolved_by, resolution_note, 1 if authority_validated else 0, item_id),
    )
    return {"ok": True, "item_id": item_id, "status": "resolved", "resolved_at": now, "authority_validated": authority_validated}

def expire_stale_open_items() -> dict[str, Any]:
    """Mark open items past their valid_until as expired."""
    db.init_db()
    now = _now_iso()
    rows = db.fetchall(
        "SELECT id, valid_until FROM open_items WHERE status='open' AND valid_until IS NOT NULL",
        (),
    )
    expired: list[str] = []
    for row in rows:
        vu = _parse_dt(row["valid_until"])
        if vu and vu <= datetime.now(timezone.utc):
            db.execute(
                "UPDATE open_items SET status='expired' WHERE id=?", (row["id"],)
            )
            expired.append(row["id"])
    return {"ok": True, "expired_count": len(expired), "expired_ids": expired}


def get_open_item(item_id: str) -> dict[str, Any] | None:
    row = db.fetchone("SELECT * FROM open_items WHERE id=?", (item_id,))
    return _row_to_open_item(dict(row)).to_dict() if row else None


def list_open_items(
    status: str | None = None,
    drift_priority: str | None = None,
    node_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    q = "SELECT * FROM open_items WHERE 1=1"
    params: list[Any] = []
    if status:
        q += " AND status=?"
        params.append(status)
    if drift_priority:
        q += " AND drift_priority=?"
        params.append(drift_priority)
    if node_id:
        nid = node_id if node_id.startswith("NODE:") else f"NODE:{node_id}"
        q += " AND node_id=?"
        params.append(nid)
    priority_order = "CASE drift_priority WHEN 'high' THEN 0 WHEN 'moderate' THEN 1 ELSE 2 END"
    q += f" ORDER BY {priority_order}, created_at DESC LIMIT ?"
    params.append(limit)
    return [_row_to_open_item(dict(r)).to_dict() for r in db.fetchall(q, tuple(params))]


# ---------------------------------------------------------------------------
# Fix E — Temporal Laundering Warning
# ---------------------------------------------------------------------------

TEMPORAL_LAUNDERING_WARNING = (
    "Warning: Elapsed time does not constitute verification. "
    "This state degraded into containment, not certainty. "
    "Do not interpret silence or continuation as resolution."
)


def temporal_laundering_check(node_or_card_id: str) -> dict[str, Any]:
    """Fix E: Detect and surface temporal laundering conditions.

    If state expired without refresh, this warning must be displayed.
    No suppression. No 'probably still true.'
    """
    db.init_db()
    node = get_node(node_or_card_id)
    if not node:
        return {"ok": False, "errors": [f"node not found: {node_or_card_id}"]}

    drift_result = evaluate_drift(node.id)
    if not drift_result.get("ok"):
        return drift_result

    drift = drift_result["drift"]
    now = datetime.now(timezone.utc)
    laundering_detected = False
    laundering_details: list[str] = []

    # Condition 1: valid_until has elapsed
    vu = _parse_dt(drift.get("valid_until"))
    if vu and vu <= now:
        laundering_detected = True
        laundering_details.append(
            f"valid_until elapsed at {drift['valid_until']}; "
            "node entered containment — not certainty"
        )

    # Condition 2: temporal ambiguity (never had a verified timestamp)
    if drift.get("temporal_ambiguity"):
        laundering_detected = True
        laundering_details.append(
            "no verification timestamp ever recorded; "
            "any assumed freshness is laundered, not real"
        )

    # Condition 3: high drift with no refresh events
    if drift.get("drift_risk") == "high":
        last_ev = db.fetchone(
            "SELECT created_at FROM coherence_refresh_events WHERE node_id=? ORDER BY created_at DESC LIMIT 1",
            (node.id,),
        )
        if not last_ev:
            laundering_detected = True
            laundering_details.append(
                "high drift risk with no recorded refresh events; "
                "continuation does not constitute re-verification"
            )

    return {
        "ok": True,
        "node_id": node.id,
        "laundering_detected": laundering_detected,
        "laundering_details": laundering_details,
        "warning": TEMPORAL_LAUNDERING_WARNING if laundering_detected else None,
        "drift": drift,
    }


# ---------------------------------------------------------------------------
# Fix F (substrate) — Integrity Panel Aggregation
# ---------------------------------------------------------------------------

def temporal_integrity_panel(limit: int = 50) -> dict[str, Any]:
    """Fix F: Aggregate all temporal integrity signals into one panel.

    Designed to be the first-order trust boundary display. Full UI panel
    is rendered by the routes layer; this function provides the data.
    """
    db.init_db()

    all_drift = evaluate_drift_all(limit=limit)
    drift_results = all_drift.get("results", [])

    # Active verified states (low drift, not temporal_ambiguity)
    active_verified = [
        d for d in drift_results
        if d["drift_risk"] == "low" and not d["temporal_ambiguity"]
    ]

    # Open containment states (d=0, m=contain, anchor active)
    active_anchors = list_anchors(status="active", limit=limit)

    # Expired without refresh
    expired_without_refresh = [
        d for d in drift_results
        if d["drift_risk"] == "high" and not d["temporal_ambiguity"]
    ]

    # Highest drift risk nodes
    highest_risk = drift_results[:10]  # already sorted high→low

    # Open items requiring resolution
    open_items = list_open_items(status="open", limit=limit)

    # Resolution authority summary
    resolution_authorities: dict[str, int] = {}
    for item in open_items:
        auth = item.get("resolution_authority") or "unknown"
        resolution_authorities[auth] = resolution_authorities.get(auth, 0) + 1

    # Laundering warnings across high-risk nodes
    laundering_warnings: list[dict[str, Any]] = []
    for d in drift_results[:20]:
        if d["drift_risk"] == "high":
            lc = temporal_laundering_check(d["node_id"])
            if lc.get("ok") and lc.get("laundering_detected"):
                laundering_warnings.append({
                    "node_id": d["node_id"],
                    "details": lc["laundering_details"],
                })

    return {
        "ok": True,
        "summary": {
            "total_nodes_evaluated": all_drift.get("total", 0),
            "drift_counts": all_drift.get("counts", {}),
            "active_verified_count": len(active_verified),
            "open_containment_count": len(active_anchors),
            "expired_without_refresh_count": len(expired_without_refresh),
            "open_items_count": len(open_items),
            "laundering_warning_count": len(laundering_warnings),
        },
        "active_verified_states": active_verified[:10],
        "open_containment_states": active_anchors,
        "expired_without_refresh": expired_without_refresh[:10],
        "highest_drift_risk_nodes": highest_risk,
        "open_items": open_items[:10],
        "required_resolution_authorities": resolution_authorities,
        "laundering_warnings": laundering_warnings,
        "panel_generated_at": _now_iso(),
    }
