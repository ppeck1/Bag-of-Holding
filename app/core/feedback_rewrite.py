"""app/core/feedback_rewrite.py: Conservative feedback-to-topology rewrite engine.

Phase 23: Feedback must rewrite lattice edges, not merely append notes.

Frozen grammar mapping:
  Feedback -> edge rewrite

Safety invariant:
  - no silent topology changes
  - every rewrite is logged
  - every rewrite is reversible
  - no autonomous application path; caller must identify a human/reviewer actor
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
from app.core.lattice_graph import (
    REQUIRED_EDGE_RELATIONS,
    create_edge,
    get_edge,
    get_node,
    list_edges,
)
from app.core.plane_card import PlaneCard, upsert_card

FEEDBACK_KINDS = {"reinforcing", "dampening", "compensatory", "destabilizing"}
REWRITE_ACTIONS = {
    "strengthen_edge",
    "weaken_edge",
    "create_constraint",
    "harden_boundary",
    "shift_dominance_ordering",
    "reroute_flow_path",
}

EDGE_ACTIONS = {"strengthen_edge", "weaken_edge", "harden_boundary", "shift_dominance_ordering", "reroute_flow_path"}

# P4: Replay guard window in seconds. Duplicate create_constraint calls within
# this window with identical (action, reason, actor, target) are rejected.
IDEMPOTENCY_WINDOW_SECONDS: int = 1800  # 30 minutes
DEFAULT_WEIGHT_DELTA = {
    "reinforcing": 0.20,
    "dampening": -0.20,
    "compensatory": 0.10,
    "destabilizing": 0.30,
}


@dataclass
class FeedbackRewrite:
    rewrite_id: str
    feedback_kind: str
    action: str
    reason: str
    actor: str
    edge_id: str | None = None
    node_id: str | None = None
    previous_state: dict[str, Any] = field(default_factory=dict)
    new_state: dict[str, Any] = field(default_factory=dict)
    reversible: bool = True
    reverted: bool = False
    created_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _rewrite_id(action: str, reason: str, actor: str) -> str:
    raw = f"{action}|{reason}|{actor}|{time.time_ns()}".encode()
    return "FR_" + hashlib.sha1(raw).hexdigest()[:14]


def _clamp_weight(value: float) -> float:
    return round(max(0.0, min(10.0, float(value))), 6)


def _persist_rewrite(record: FeedbackRewrite) -> FeedbackRewrite:
    db.execute(
        """
        INSERT OR REPLACE INTO feedback_rewrites
          (rewrite_id, feedback_kind, action, reason, actor, edge_id, node_id,
           previous_state_json, new_state_json, reversible, reverted, created_at, metadata_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            record.rewrite_id,
            record.feedback_kind,
            record.action,
            record.reason,
            record.actor,
            record.edge_id,
            record.node_id,
            json.dumps(record.previous_state),
            json.dumps(record.new_state),
            1 if record.reversible else 0,
            1 if record.reverted else 0,
            record.created_at or _now_iso(),
            json.dumps(record.metadata or {}),
        ),
    )
    try:
        log_event(
            "feedback_rewrite",
            actor_type="human" if record.actor != "system" else "system",
            actor_id=record.actor,
            detail=json.dumps(record.to_dict(), sort_keys=True),
        )
    except Exception:
        pass
    return record


def _row_to_rewrite(row: dict[str, Any]) -> FeedbackRewrite:
    return FeedbackRewrite(
        rewrite_id=row["rewrite_id"],
        feedback_kind=row["feedback_kind"],
        action=row["action"],
        reason=row["reason"],
        actor=row["actor"],
        edge_id=row.get("edge_id"),
        node_id=row.get("node_id"),
        previous_state=_json_loads(row.get("previous_state_json"), {}),
        new_state=_json_loads(row.get("new_state_json"), {}),
        reversible=bool(row.get("reversible")),
        reverted=bool(row.get("reverted")),
        created_at=row.get("created_at"),
        metadata=_json_loads(row.get("metadata_json"), {}),
    )


def get_rewrite(rewrite_id: str) -> dict[str, Any] | None:
    row = db.fetchone("SELECT * FROM feedback_rewrites WHERE rewrite_id=?", (rewrite_id,))
    return _row_to_rewrite(dict(row)).to_dict() if row else None


def list_rewrites(edge_id: str | None = None, node_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    q = "SELECT * FROM feedback_rewrites WHERE 1=1"
    params: list[Any] = []
    if edge_id:
        q += " AND edge_id=?"
        params.append(edge_id)
    if node_id:
        nid = node_id if node_id.startswith("NODE:") else f"NODE:{node_id}"
        q += " AND node_id=?"
        params.append(nid)
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    return [_row_to_rewrite(dict(r)).to_dict() for r in db.fetchall(q, tuple(params))]


def _apply_edge_weight(edge: dict[str, Any], new_weight: float, metadata_patch: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = dict(edge.get("metadata") or {})
    if metadata_patch:
        metadata.update(metadata_patch)
    db.execute(
        "UPDATE lattice_edges SET weight=?, metadata_json=? WHERE edge_id=?",
        (_clamp_weight(new_weight), json.dumps(metadata), edge["edge_id"]),
    )
    return get_edge(edge["edge_id"]) or {}



def _find_recent_create_constraint(action: str, reason: str, actor: str, target: str) -> str | None:
    """Return the rewrite_id of a matching recent create_constraint rewrite, or None.

    P4: Prevents the same feedback from creating multiple topology mutations
    when operators retry or double-submit.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=IDEMPOTENCY_WINDOW_SECONDS)).isoformat()
    rows = db.fetchall(
        """
        SELECT rewrite_id, metadata_json
          FROM feedback_rewrites
         WHERE action = ?
           AND reason = ?
           AND actor = ?
           AND reverted = 0
           AND created_at >= ?
         ORDER BY created_at DESC
         LIMIT 20
        """,
        (action, reason, actor, cutoff),
    )
    target_norm = str(target).strip().lower()
    for row in rows:
        md = _json_loads(row["metadata_json"], {})
        stored_target = str(md.get("constraint_target", "") or "").strip().lower()
        if stored_target == target_norm or not stored_target:
            return row["rewrite_id"]
    return None


def apply_feedback_rewrite(
    feedback_kind: str,
    action: str,
    reason: str,
    actor: str,
    edge_id: str | None = None,
    source_id: str | None = None,
    target_id: str | None = None,
    relation: str | None = None,
    weight_delta: float | None = None,
    new_weight: float | None = None,
    new_relation: str | None = None,
    constraint_target: str | None = None,
    plane: str = "Review",
    authority_plane: str = "governance",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply a conservative, reversible feedback rewrite.

    This function intentionally performs only bounded topology changes. It does
    not infer the rewrite target; callers must identify an edge or explicit
    source/target pair.
    """
    db.init_db()
    feedback_kind = feedback_kind.strip().lower()
    action = action.strip().lower()
    relation = relation.strip().lower() if relation else relation
    new_relation = new_relation.strip().lower() if new_relation else new_relation
    errors: list[str] = []
    if feedback_kind not in FEEDBACK_KINDS:
        errors.append(f"feedback_kind must be one of {sorted(FEEDBACK_KINDS)}")
    if action not in REWRITE_ACTIONS:
        errors.append(f"action must be one of {sorted(REWRITE_ACTIONS)}")
    if not reason or len(reason.strip()) < 8:
        errors.append("reason must be explicit enough for audit review")
    if not actor or actor.strip().lower() in {"auto", "autonomous", "llm"}:
        errors.append("actor must identify a human/reviewer; autonomous feedback rewrites are illegal")
    if errors:
        return {"ok": False, "errors": errors}

    metadata = metadata or {}
    now = _now_iso()

    if action == "create_constraint":
        topic = constraint_target or metadata.get("constraint_target") or reason[:80]

        # P4: Reject duplicate create_constraint calls within the idempotency window.
        existing_duplicate = _find_recent_create_constraint(action, reason, actor, str(topic))
        if existing_duplicate:
            return {
                "ok": False,
                "errors": [
                    "duplicate feedback rejected: a matching create_constraint rewrite exists "
                    f"within the {IDEMPOTENCY_WINDOW_SECONDS // 60}-minute idempotency window",
                ],
                "existing_rewrite_id": existing_duplicate,
            }

        node_seed = f"feedback:{topic}:{now}"
        card_id = "CARD:FB:" + hashlib.sha1(node_seed.encode()).hexdigest()[:10]
        card = PlaneCard(
            id=card_id,
            plane=plane,
            card_type="review",
            topic=str(topic)[:120],
            b=0,
            d=0,
            m="contain",
            delta={"kind": "feedback", "feedback_kind": feedback_kind},
            constraints={
                "created_by_feedback": True,
                "hardened": action == "harden_boundary",
                "allows_refinement": True,
                "requires_certificate_for_base_flip": True,
            },
            authority={"write": [actor], "resolve": [actor, "custodian"], "locked": False, "authority_plane": authority_plane},
            observed_at=now,
            valid_until=(datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
            context_ref={"feedback_reason": reason, "source_edge": edge_id, "source": "feedback_rewrite"},
            payload={"title": topic, "summary": reason, "status": "review_required", "feedback_kind": feedback_kind},
            doc_id=None,
            created_ts=int(time.time()),
            updated_ts=int(time.time()),
        )
        upsert_card(card)
        node_id = f"NODE:{card.id}"
        rec = FeedbackRewrite(
            rewrite_id=_rewrite_id(action, reason, actor),
            feedback_kind=feedback_kind,
            action=action,
            reason=reason,
            actor=actor,
            node_id=node_id,
            previous_state={},
            new_state={"node": get_node(card.id).to_dict() if get_node(card.id) else {"id": node_id}},
            created_at=now,
            metadata=metadata,
        )
        _persist_rewrite(rec)
        return {"ok": True, "rewrite_id": rec.rewrite_id, "rewrite": rec.to_dict(), "node": rec.new_state.get("node")}

    # Edge mutations below.
    edge = get_edge(edge_id) if edge_id else None
    if not edge and source_id and target_id and relation:
        if action in {"reroute_flow_path", "shift_dominance_ordering"} and relation not in REQUIRED_EDGE_RELATIONS:
            return {"ok": False, "errors": [f"relation must be one of {sorted(REQUIRED_EDGE_RELATIONS)}"]}
        created = create_edge(source_id, target_id, relation, weight=1.0, created_by=actor, metadata={"created_by_feedback_rewrite": True})
        if not created.get("ok"):
            return created
        edge = created["edge"]
        edge_id = created["edge_id"]
    if not edge:
        return {"ok": False, "errors": ["edge_id or explicit source_id/target_id/relation is required for edge rewrite"]}

    previous = dict(edge)
    base_weight = float(edge.get("weight") or 0.0)
    delta = weight_delta if weight_delta is not None else DEFAULT_WEIGHT_DELTA.get(feedback_kind, 0.1)
    target_weight = new_weight if new_weight is not None else base_weight + delta

    if action == "weaken_edge":
        target_weight = new_weight if new_weight is not None else base_weight - abs(delta)
    elif action == "strengthen_edge":
        target_weight = new_weight if new_weight is not None else base_weight + abs(delta)
    elif action == "harden_boundary":
        target_weight = new_weight if new_weight is not None else max(base_weight + abs(delta), 1.0)
        new_relation = new_relation or "bounds"
    elif action == "shift_dominance_ordering":
        target_weight = new_weight if new_weight is not None else base_weight + abs(delta)
    elif action == "reroute_flow_path":
        if not target_id:
            return {"ok": False, "errors": ["target_id is required to reroute flow path"]}
        target_node = get_node(target_id)
        if not target_node:
            return {"ok": False, "errors": [f"reroute target not found: {target_id}"]}
        old_meta = dict(edge.get("metadata") or {})
        old_meta.update({"rerouted_from": edge["target_id"], "feedback_reason": reason})
        tid = target_node.id
        db.execute(
            "UPDATE lattice_edges SET target_id=?, relation=?, weight=?, metadata_json=? WHERE edge_id=?",
            (tid, new_relation or "routes_to", _clamp_weight(target_weight), json.dumps(old_meta), edge["edge_id"]),
        )
        new_state = get_edge(edge["edge_id"]) or {}
        rec = FeedbackRewrite(
            rewrite_id=_rewrite_id(action, reason, actor),
            feedback_kind=feedback_kind,
            action=action,
            reason=reason,
            actor=actor,
            edge_id=edge["edge_id"],
            node_id=tid,
            previous_state=previous,
            new_state=new_state,
            created_at=now,
            metadata=metadata,
        )
        _persist_rewrite(rec)
        return {"ok": True, "rewrite_id": rec.rewrite_id, "rewrite": rec.to_dict(), "edge": new_state}

    if new_relation:
        if new_relation not in REQUIRED_EDGE_RELATIONS:
            return {"ok": False, "errors": [f"new_relation must be one of {sorted(REQUIRED_EDGE_RELATIONS)}"]}
        meta = dict(edge.get("metadata") or {})
        meta.update({"previous_relation": edge.get("relation"), "feedback_reason": reason})
        db.execute(
            "UPDATE lattice_edges SET relation=?, weight=?, metadata_json=? WHERE edge_id=?",
            (new_relation, _clamp_weight(target_weight), json.dumps(meta), edge["edge_id"]),
        )
        new_state = get_edge(edge["edge_id"]) or {}
    else:
        new_state = _apply_edge_weight(edge, target_weight, {"feedback_reason": reason, "last_feedback_kind": feedback_kind})

    rec = FeedbackRewrite(
        rewrite_id=_rewrite_id(action, reason, actor),
        feedback_kind=feedback_kind,
        action=action,
        reason=reason,
        actor=actor,
        edge_id=edge["edge_id"],
        node_id=edge.get("target_id"),
        previous_state=previous,
        new_state=new_state,
        created_at=now,
        metadata=metadata,
    )
    _persist_rewrite(rec)
    return {"ok": True, "rewrite_id": rec.rewrite_id, "rewrite": rec.to_dict(), "edge": new_state}


def revert_feedback_rewrite(rewrite_id: str, actor: str, reason: str = "manual revert") -> dict[str, Any]:
    db.init_db()
    row = db.fetchone("SELECT * FROM feedback_rewrites WHERE rewrite_id=?", (rewrite_id,))
    if not row:
        return {"ok": False, "errors": ["rewrite not found"]}
    rec = _row_to_rewrite(dict(row))
    if rec.reverted:
        return {"ok": False, "errors": ["rewrite already reverted"]}
    if not rec.reversible:
        return {"ok": False, "errors": ["rewrite is not reversible"]}

    if rec.edge_id and rec.previous_state:
        prev = rec.previous_state
        db.execute(
            """
            UPDATE lattice_edges
               SET source_id=?, target_id=?, relation=?, weight=?, status=?, created_by=?, reversible=?, metadata_json=?
             WHERE edge_id=?
            """,
            (
                prev["source_id"], prev["target_id"], prev["relation"], float(prev.get("weight") or 0),
                prev.get("status") or "active", prev.get("created_by") or "human", 1 if prev.get("reversible", True) else 0,
                json.dumps(prev.get("metadata") or {}), rec.edge_id,
            ),
        )
    elif rec.node_id and not rec.previous_state:
        # Constraint created by feedback: reversible means archive/deactivate, not delete.
        card_id = rec.node_id[5:] if rec.node_id.startswith("NODE:") else rec.node_id
        db.execute(
            "UPDATE cards SET plane='Archive', payload_json=json_set(COALESCE(payload_json,'{}'), '$.status', 'reverted') WHERE id=?",
            (card_id,),
        )
    else:
        return {"ok": False, "errors": ["rewrite lacks restorable previous state"]}

    db.execute("UPDATE feedback_rewrites SET reverted=1, metadata_json=? WHERE rewrite_id=?", (json.dumps({**rec.metadata, "reverted_by": actor, "revert_reason": reason, "reverted_at": _now_iso()}), rewrite_id))
    try:
        log_event("feedback_rewrite_revert", actor_type="human", actor_id=actor, detail=json.dumps({"rewrite_id": rewrite_id, "reason": reason}))
    except Exception:
        pass
    return {"ok": True, "rewrite_id": rewrite_id, "reverted": True, "current_edge": get_edge(rec.edge_id) if rec.edge_id else None}


def feedback_topology_status() -> dict[str, Any]:
    rewrites = list_rewrites(limit=500)
    active_edges = list_edges(active_only=True)
    return {
        "rewrite_count": len(rewrites),
        "active_edge_count": len(active_edges),
        "reverted_count": sum(1 for r in rewrites if r.get("reverted")),
        "actions": sorted({r["action"] for r in rewrites}),
        "feedback_kinds": sorted({r["feedback_kind"] for r in rewrites}),
        "safety": {
            "autonomous_rewrites_allowed": False,
            "reversible_by_default": True,
            "audit_required": True,
        },
    }


# ---------------------------------------------------------------------------
# P7: Pre-mutation rewrite preview (simulation without apply)
# ---------------------------------------------------------------------------

def preview_feedback_rewrite(
    feedback_kind: str,
    action: str,
    reason: str,
    actor: str,
    edge_id: str | None = None,
    source_id: str | None = None,
    target_id: str | None = None,
    relation: str | None = None,
    weight_delta: float | None = None,
    new_weight: float | None = None,
    new_relation: str | None = None,
    constraint_target: str | None = None,
    plane: str = "Review",
    authority_plane: str = "governance",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Simulate a feedback rewrite and return a constraint diff preview.

    P7: Operators must see the full topology change before approval.
    This function NEVER writes to the database. It is read-only.

    Returns:
        ok: bool
        preview: {
            before_state, after_state, affected_nodes,
            affected_flows, reversibility, revert_path, warnings
        }
    """
    db.init_db()
    feedback_kind = (feedback_kind or "").strip().lower()
    action = (action or "").strip().lower()
    relation = relation.strip().lower() if relation else relation
    new_relation = new_relation.strip().lower() if new_relation else new_relation

    errors: list[str] = []
    if feedback_kind not in FEEDBACK_KINDS:
        errors.append(f"feedback_kind must be one of {sorted(FEEDBACK_KINDS)}")
    if action not in REWRITE_ACTIONS:
        errors.append(f"action must be one of {sorted(REWRITE_ACTIONS)}")
    if not reason or len(reason.strip()) < 8:
        errors.append("reason must be explicit enough for audit review")
    if not actor or actor.strip().lower() in {"auto", "autonomous", "llm"}:
        errors.append("actor must identify a human/reviewer")
    if errors:
        return {"ok": False, "errors": errors}

    metadata = metadata or {}

    if action == "create_constraint":
        topic = constraint_target or metadata.get("constraint_target") or reason[:80]
        existing = _find_recent_create_constraint(action, reason, actor, str(topic))
        after_state = {
            "action": "create_constraint",
            "topic": topic,
            "plane": plane,
            "card_type": "review",
            "status": "review_required",
            "constraints": {
                "created_by_feedback": True,
                "hardened": action == "harden_boundary",
                "allows_refinement": True,
                "requires_certificate_for_base_flip": True,
            },
        }
        warnings = []
        if existing:
            warnings.append(
                f"A matching create_constraint rewrite ({existing}) already exists within "
                f"the {IDEMPOTENCY_WINDOW_SECONDS // 60}-minute window. Apply would be rejected."
            )
        return {
            "ok": True,
            "preview": {
                "action": action,
                "feedback_kind": feedback_kind,
                "before_state": None,
                "after_state": after_state,
                "affected_nodes": [{"topic": topic, "plane": plane, "status": "would be created"}],
                "affected_flows": [],
                "reversibility": "reversible: card archived to Archive plane on revert",
                "revert_path": "revert_feedback_rewrite -> card status set to reverted",
                "warnings": warnings,
                "simulation_only": True,
            },
        }

    # Edge mutation preview.
    edge = get_edge(edge_id) if edge_id else None
    if not edge and source_id and target_id and relation:
        src_node = get_node(source_id)
        tgt_node = get_node(target_id)
        if not src_node or not tgt_node:
            return {"ok": False, "errors": ["source or target node not found for edge preview"]}
        edge = {
            "edge_id": "(would be created)",
            "source_id": src_node.id,
            "target_id": tgt_node.id,
            "relation": relation,
            "weight": 1.0,
            "status": "active",
            "reversible": True,
            "metadata": {},
        }
    if not edge:
        return {"ok": False, "errors": ["edge_id or source_id/target_id/relation required"]}

    before = dict(edge)
    base_weight = float(edge.get("weight") or 0.0)
    delta = weight_delta if weight_delta is not None else DEFAULT_WEIGHT_DELTA.get(feedback_kind, 0.1)

    # Compute simulated after state without writing.
    after = dict(edge)
    after_relation = new_relation or edge.get("relation")
    if action == "weaken_edge":
        after["weight"] = _clamp_weight(new_weight if new_weight is not None else base_weight - abs(delta))
    elif action == "strengthen_edge":
        after["weight"] = _clamp_weight(new_weight if new_weight is not None else base_weight + abs(delta))
    elif action == "harden_boundary":
        after["weight"] = _clamp_weight(new_weight if new_weight is not None else max(base_weight + abs(delta), 1.0))
        after_relation = new_relation or "bounds"
    elif action == "shift_dominance_ordering":
        after["weight"] = _clamp_weight(new_weight if new_weight is not None else base_weight + abs(delta))
    elif action == "reroute_flow_path":
        if target_id:
            tgt_node = get_node(target_id)
            after["target_id"] = tgt_node.id if tgt_node else target_id
        after_relation = new_relation or "routes_to"
        after["weight"] = _clamp_weight(new_weight if new_weight is not None else base_weight)
    else:
        after["weight"] = _clamp_weight(new_weight if new_weight is not None else base_weight + delta)

    after["relation"] = after_relation

    # Describe downstream effect.
    weight_change = after["weight"] - base_weight
    direction = "strengthened" if weight_change > 0 else ("weakened" if weight_change < 0 else "unchanged")
    affected_nodes = []
    src_node = get_node(edge.get("source_id", ""))
    tgt_node = get_node(edge.get("target_id", ""))
    if src_node:
        affected_nodes.append({"id": src_node.id, "role": "source"})
    if tgt_node:
        affected_nodes.append({"id": tgt_node.id, "role": "target"})

    downstream_edges = list_edges(node_id=edge.get("target_id"), active_only=True)
    affected_flows = [
        {"from": e["source_id"], "to": e["target_id"], "relation": e["relation"]}
        for e in downstream_edges[:10]
    ]

    warnings = []
    if abs(weight_change) > 1.5:
        warnings.append(f"Large weight delta ({weight_change:+.2f}) may destabilize downstream flows.")
    if after_relation != before.get("relation"):
        warnings.append(
            f"Relation change: {before.get('relation')!r} -> {after_relation!r}. "
            "All downstream traversal paths are affected."
        )

    return {
        "ok": True,
        "preview": {
            "action": action,
            "feedback_kind": feedback_kind,
            "before_state": before,
            "after_state": after,
            "weight_change": round(weight_change, 4),
            "direction": direction,
            "affected_nodes": affected_nodes,
            "affected_flows": affected_flows,
            "reversibility": "reversible: previous_state snapshot stored on apply",
            "revert_path": "POST /api/feedback/rewrites/{rewrite_id}/revert",
            "warnings": warnings,
            "simulation_only": True,
        },
    }
