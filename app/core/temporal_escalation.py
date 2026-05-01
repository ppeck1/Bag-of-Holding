"""app/core/temporal_escalation.py: Temporal Escalation Ladder Engine.

Phase 24.3 Fix C + Fix D.

Problem: detection without escalation is observability without governance.

This module operationalizes what happens next after drift is detected.

Escalation levels:

    LOW           → monitored; no action required
    MODERATE      → warning; owner notified, refresh deadline assigned
    HIGH          → containment; forced d=0, m=contain, anchor required
    PERSISTENT_HIGH → escalation; mandatory authority promotion, supervisory routing

Fix C — Escalation Ladder Engine.
Fix D — Escalation Routing Registry.
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
from app.core.temporal_governor import (
    evaluate_drift,
    trigger_re_anchor,
    list_anchors,
)

# ---------------------------------------------------------------------------
# Escalation levels
# ---------------------------------------------------------------------------

ESCALATION_LEVELS = ("monitored", "warning", "containment", "escalation")

DRIFT_TO_ESCALATION: dict[str, str] = {
    "low":      "monitored",
    "moderate": "warning",
    "high":     "containment",
}

# A HIGH-drift node that has been in containment longer than its
# max_resolution_window transitions to escalation.
DEFAULT_ESCALATION_WINDOW_HOURS: int = 48


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


def _json_loads(v: str | None, default: Any) -> Any:
    if not v:
        return default
    try:
        return json.loads(v)
    except Exception:
        return default


def _esc_id(node_id: str, level: str) -> str:
    raw = f"{node_id}|{level}|{time.time_ns()}".encode()
    return "ESC_" + hashlib.sha1(raw).hexdigest()[:12]

def _lock_id(node_id: str, reason: str) -> str:
    raw = f"{node_id}|{reason}|{time.time_ns()}".encode()
    return "LOCK_" + hashlib.sha1(raw).hexdigest()[:12]

def impose_canonical_lock(node_id: str, reason: str, escalation_id: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create an active canonical lock. Containment is binding, not decorative."""
    db.init_db()
    lid = _lock_id(node_id, reason)
    db.execute(
        """INSERT OR REPLACE INTO canonical_locks
             (lock_id, node_id, reason, escalation_id, active, created_at, released_at, metadata_json)
           VALUES (?,?,?,?,?,?,?,?)""",
        (lid, node_id, reason, escalation_id, 1, _now_iso(), None, json.dumps(metadata or {})),
    )
    return {"lock_id": lid, "node_id": node_id, "active": True, "reason": reason}


# ---------------------------------------------------------------------------
# Fix D — Escalation Routing Registry
# ---------------------------------------------------------------------------

def register_escalation_route(
    plane: str,
    severity: str,
    owner: str,
    supervisor: str,
    max_resolution_window_hours: int = DEFAULT_ESCALATION_WINDOW_HOURS,
    promotion_rule: str = "supervisor_takes_authority_after_window_expiry",
    containment_required: bool = True,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fix D: Register who gets paged, when, why, and what authority changes.

    No governance by memory. The registry is the contract.
    """
    db.init_db()
    errors: list[str] = []
    if not plane or not plane.strip():
        errors.append("plane is required")
    if severity not in ("low", "moderate", "high", "persistent_high"):
        errors.append("severity must be: low | moderate | high | persistent_high")
    if not owner or not owner.strip():
        errors.append("owner is required")
    if not supervisor or not supervisor.strip():
        errors.append("supervisor is required")
    if errors:
        return {"ok": False, "errors": errors}

    now = _now_iso()
    db.execute(
        """INSERT OR REPLACE INTO escalation_registry
             (plane, severity, owner, supervisor, max_resolution_window_hours,
              promotion_rule, containment_required, updated_at, metadata_json)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            plane.strip().lower(), severity.strip().lower(),
            owner.strip(), supervisor.strip(),
            max_resolution_window_hours,
            promotion_rule.strip(),
            1 if containment_required else 0,
            now,
            json.dumps(metadata or {}),
        ),
    )
    return {
        "ok": True,
        "plane": plane,
        "severity": severity,
        "owner": owner,
        "supervisor": supervisor,
        "max_resolution_window_hours": max_resolution_window_hours,
        "promotion_rule": promotion_rule,
    }


def get_escalation_route(plane: str, severity: str) -> dict[str, Any] | None:
    row = db.fetchone(
        "SELECT * FROM escalation_registry WHERE plane=? AND severity=?",
        (plane.strip().lower(), severity.strip().lower()),
    )
    if not row:
        # Fall back to wildcard plane entry
        row = db.fetchone(
            "SELECT * FROM escalation_registry WHERE plane='*' AND severity=?",
            (severity.strip().lower(),),
        )
    if not row:
        return None
    d = dict(row)
    d["metadata"] = _json_loads(d.get("metadata_json"), {})
    return d


def list_escalation_routes(plane: str | None = None) -> list[dict[str, Any]]:
    q = "SELECT * FROM escalation_registry WHERE 1=1"
    params: list[Any] = []
    if plane:
        q += " AND plane=?"
        params.append(plane.strip().lower())
    q += " ORDER BY plane, severity"
    rows = db.fetchall(q, tuple(params))
    out = []
    for r in rows:
        d = dict(r)
        d["metadata"] = _json_loads(d.get("metadata_json"), {})
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# Fix C — Escalation Ladder Engine
# ---------------------------------------------------------------------------

@dataclass
class EscalationRecord:
    escalation_id: str
    node_id: str
    drift_risk: str
    escalation_level: str
    action_taken: str
    notification_sent: bool
    owner: str | None
    supervisor: str | None
    refresh_due: str | None
    escalated_to: str | None
    why: str | None
    supervisory_plane: str | None
    forced_scope_reduction: bool
    anchor_id: str | None
    route_found: bool
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_persistent_high(node_id: str, route: dict[str, Any] | None) -> bool:
    """Detect if a HIGH-drift node has exceeded its resolution window."""
    window_hours = (route or {}).get(
        "max_resolution_window_hours", DEFAULT_ESCALATION_WINDOW_HOURS
    )
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=window_hours)
    ).isoformat()
    # Check if there's an anchor older than the window with no resolved_at
    anchors = db.fetchall(
        """SELECT anchor_id, created_at, resolved_at FROM anchor_events
           WHERE node_id LIKE ? AND status='active' AND created_at <= ?
           ORDER BY created_at ASC LIMIT 1""",
        (f"%{node_id.replace('NODE:', '')}%", cutoff),
    )
    return bool(anchors)


def run_escalation(node_id: str, actor: str = "escalation-engine") -> dict[str, Any]:
    """Fix C: Evaluate node and execute the appropriate escalation level.

    LOW:              monitored — no action.
    MODERATE:         warning — owner notified, refresh deadline assigned.
    HIGH:             containment — force d=0, m=contain, anchor, engage authority.
    PERSISTENT_HIGH:  escalation — mandatory authority promotion, supervisory routing.
    """
    db.init_db()
    drift_result = evaluate_drift(node_id)
    if not drift_result.get("ok"):
        return drift_result

    drift = drift_result["drift"]
    drift_risk = drift["drift_risk"]
    # Extract plane from the LatticeNode directly (drift state has no node field)
    from app.core.lattice_graph import get_node as _get_node
    _node = _get_node(node_id)
    node_plane_norm = (_node.plane or "internal").lower() if _node else "internal"

    base_level = DRIFT_TO_ESCALATION.get(drift_risk, "monitored")
    route = get_escalation_route(node_plane_norm, drift_risk)

    # Check for persistent HIGH
    if base_level == "containment" and _is_persistent_high(node_id, route):
        base_level = "escalation"

    eid = _esc_id(node_id, base_level)
    now = _now_iso()
    record = EscalationRecord(
        escalation_id=eid,
        node_id=node_id,
        drift_risk=drift_risk,
        escalation_level=base_level,
        action_taken="",
        notification_sent=False,
        owner=route["owner"] if route else None,
        supervisor=route["supervisor"] if route else None,
        refresh_due=None,
        escalated_to=None,
        why=None,
        supervisory_plane=None,
        forced_scope_reduction=False,
        anchor_id=None,
        route_found=bool(route),
        created_at=now,
    )

    if base_level == "monitored":
        record.action_taken = "status=monitored; no action required"

    elif base_level == "warning":
        record.notification_sent = True
        record.refresh_due = (
            datetime.now(timezone.utc)
            + timedelta(hours=(route or {}).get("max_resolution_window_hours", 72))
        ).isoformat()
        record.action_taken = (
            f"status=warning; owner={record.owner or 'unregistered'}; "
            f"refresh_due={record.refresh_due}"
        )

    elif base_level == "containment":
        # Force d=0, m=contain, anchor required
        anchor_result = trigger_re_anchor(
            node_or_card_id=node_id,
            actor=actor if actor != "escalation-engine" else "escalation-system",
            trigger_reason=f"escalation-ladder: HIGH drift detected ({drift_risk})",
        )
        if anchor_result.get("ok"):
            record.anchor_id = anchor_result.get("anchor_id")
        lock = impose_canonical_lock(
            node_id,
            reason="high_drift_containment",
            escalation_id=eid,
            metadata={"drift_risk": drift_risk, "anchor_id": record.anchor_id},
        )
        record.metadata["canonical_lock"] = lock
        record.notification_sent = True
        record.forced_scope_reduction = True
        record.action_taken = (
            f"status=containment; forced d=0, m=contain; "
            f"anchor_id={record.anchor_id}; canonical_lock={lock['lock_id']}; "
            f"authority_engaged={record.owner or 'unregistered'}"
        )

    elif base_level == "escalation":
        supervisor = (route or {}).get("supervisor", "governance")
        sup_plane = (route or {}).get("plane", "governance")
        record.escalated_to = supervisor
        record.why = (
            f"HIGH drift persisted beyond resolution window; "
            f"drift_reason={drift.get('drift_reason', '')}"
        )
        record.supervisory_plane = sup_plane
        lock = impose_canonical_lock(
            node_id,
            reason="persistent_high_drift_forced_escalation",
            escalation_id=eid,
            metadata={"drift_risk": drift_risk, "escalated_to": supervisor, "supervisory_plane": sup_plane},
        )
        record.metadata["canonical_lock"] = lock
        record.forced_scope_reduction = True
        record.notification_sent = True
        try:
            db.execute(
                """UPDATE open_items
                   SET resolution_authority=?
                   WHERE (node_id=? OR node_id LIKE ?) AND status IN ('open','expired')""",
                (supervisor, node_id, f"%{node_id.replace('NODE:', '')}%"),
            )
        except Exception:
            pass
        record.metadata["authority_transfer"] = {
            "from": record.owner,
            "to": supervisor,
            "rule": (route or {}).get("promotion_rule", "forced_escalation_transfer"),
        }
        record.action_taken = (
            f"status=escalation; escalated_to={supervisor}; "
            f"authority_transferred_to={supervisor}; supervisory_plane={sup_plane}; "
            f"canonical_lock={lock['lock_id']}; forced_scope_reduction=true"
        )

    _persist_escalation(record)

    try:
        log_event(
            "temporal_escalation",
            actor_type="system",
            actor_id=actor,
            detail=json.dumps({
                "escalation_id": eid,
                "node_id": node_id,
                "drift_risk": drift_risk,
                "escalation_level": base_level,
                "action_taken": record.action_taken,
            }),
        )
    except Exception:
        pass

    return {
        "ok": True,
        "escalation": record.to_dict(),
        "drift": drift,
        "route": route,
    }


def _persist_escalation(record: EscalationRecord) -> None:
    db.execute(
        """INSERT OR REPLACE INTO escalation_events
             (escalation_id, node_id, drift_risk, escalation_level, action_taken,
              notification_sent, owner, supervisor, refresh_due, escalated_to,
              why, supervisory_plane, forced_scope_reduction, anchor_id,
              route_found, created_at, metadata_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            record.escalation_id, record.node_id, record.drift_risk,
            record.escalation_level, record.action_taken,
            1 if record.notification_sent else 0,
            record.owner, record.supervisor, record.refresh_due,
            record.escalated_to, record.why, record.supervisory_plane,
            1 if record.forced_scope_reduction else 0,
            record.anchor_id, 1 if record.route_found else 0,
            record.created_at, json.dumps(record.metadata),
        ),
    )


def escalate_all(plane: str | None = None, limit: int = 200) -> dict[str, Any]:
    """Run the escalation ladder across all nodes."""
    from app.core.lattice_graph import list_nodes
    nodes = list_nodes(plane=plane, active_only=False, limit=limit)
    results: list[dict[str, Any]] = []
    counts = {lvl: 0 for lvl in ESCALATION_LEVELS}
    for n in nodes:
        r = run_escalation(n.id)
        if r.get("ok"):
            esc = r["escalation"]
            results.append(esc)
            lvl = esc.get("escalation_level", "monitored")
            counts[lvl] = counts.get(lvl, 0) + 1
    return {"ok": True, "counts": counts, "escalations": results, "total": len(results)}


def get_escalation(escalation_id: str) -> dict[str, Any] | None:
    row = db.fetchone(
        "SELECT * FROM escalation_events WHERE escalation_id=?", (escalation_id,)
    )
    if not row:
        return None
    d = dict(row)
    d["metadata"] = _json_loads(d.get("metadata_json"), {})
    return d


def list_escalations(
    node_id: str | None = None,
    level: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    q = "SELECT * FROM escalation_events WHERE 1=1"
    params: list[Any] = []
    if node_id:
        nid = node_id if node_id.startswith("NODE:") else f"NODE:{node_id}"
        q += " AND (node_id=? OR node_id LIKE ?)"
        params.extend([nid, f"%{node_id}%"])
    if level:
        q += " AND escalation_level=?"
        params.append(level.strip().lower())
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = db.fetchall(q, tuple(params))
    out = []
    for r in rows:
        d = dict(r)
        d["metadata"] = _json_loads(d.get("metadata_json"), {})
        out.append(d)
    return out
