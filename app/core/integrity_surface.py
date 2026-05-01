"""app/core/integrity_surface.py: Integrity-First Surface Layer.

Phase 24.3 Fix E + Fix F.

Fix E: Integrity panel becomes the primary dashboard, not an optional tab.
       Truth precedes content. Always.

Fix F: Explicit visual states for every node:
       VERIFIED | CONTAINED | DRIFTING | EXPIRED | ESCALATED |
       AUTHORITY_BLOCKED | UNKNOWN

No ambiguity hidden behind generic status labels.
No green checkmark theater.
Users must feel trust boundaries.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.db import connection as db
from app.core.temporal_governor import (
    temporal_integrity_panel,
    evaluate_drift_all,
)

# ---------------------------------------------------------------------------
# Fix F — Explicit visual states
# ---------------------------------------------------------------------------

VISUAL_STATES = (
    "VERIFIED",
    "CONTAINED",
    "DRIFTING",
    "EXPIRED",
    "ESCALATED",
    "AUTHORITY_BLOCKED",
    "UNKNOWN",
)


def compute_visual_state(
    drift: dict[str, Any],
    escalation_level: str | None = None,
    authority_blocked: bool = False,
) -> dict[str, Any]:
    """Fix F: Compute the explicit visual state for a node.

    Priority order:
    1. ESCALATED      — in escalation or containment
    2. AUTHORITY_BLOCKED — authority validation failed
    3. EXPIRED        — valid_until elapsed
    4. CONTAINED      — active anchor event, d=0, m=contain
    5. DRIFTING       — moderate/high drift, not yet contained
    6. VERIFIED       — low drift, fresh, no ambiguity
    7. UNKNOWN        — temporal ambiguity
    """
    now = datetime.now(timezone.utc)

    # UNKNOWN: temporal ambiguity
    if drift.get("temporal_ambiguity"):
        return {
            "state": "UNKNOWN",
            "label": "Unknown",
            "description": "Timestamp missing. Freshness cannot be determined.",
            "color_class": "state-unknown",
            "action_required": True,
        }

    # ESCALATED
    if escalation_level in ("escalation", "containment"):
        return {
            "state": "ESCALATED",
            "label": "Escalated",
            "description": f"Escalation level: {escalation_level}. Authority engagement required.",
            "color_class": "state-escalated",
            "action_required": True,
        }

    # AUTHORITY_BLOCKED
    if authority_blocked:
        return {
            "state": "AUTHORITY_BLOCKED",
            "label": "Authority Blocked",
            "description": "Attempted resolution was rejected. Correct authority required.",
            "color_class": "state-authority-blocked",
            "action_required": True,
        }

    # EXPIRED
    vu_str = drift.get("valid_until")
    if vu_str:
        try:
            vu = datetime.fromisoformat(str(vu_str).replace("Z", "+00:00"))
            if vu <= now:
                return {
                    "state": "EXPIRED",
                    "label": "Expired",
                    "description": f"Valid until {vu_str} has elapsed. Containment active.",
                    "color_class": "state-expired",
                    "action_required": True,
                }
        except Exception:
            pass

    # CONTAINED — check for active anchor
    node_id = drift.get("node_id", "")
    if node_id:
        anchor_row = db.fetchone(
            "SELECT anchor_id FROM anchor_events WHERE node_id LIKE ? AND status='active' LIMIT 1",
            (f"%{node_id.replace('NODE:', '')}%",),
        )
        if anchor_row:
            return {
                "state": "CONTAINED",
                "label": "Contained",
                "description": "Active re-anchor. d=0, m=contain. Single-plane resume required.",
                "color_class": "state-contained",
                "action_required": True,
            }

    # DRIFTING
    if drift.get("drift_risk") in ("moderate", "high"):
        return {
            "state": "DRIFTING",
            "label": "Drifting",
            "description": f"Drift risk: {drift['drift_risk']}. {drift.get('drift_reason', '')}",
            "color_class": "state-drifting",
            "action_required": drift.get("drift_risk") == "high",
        }

    # VERIFIED
    return {
        "state": "VERIFIED",
        "label": "Verified",
        "description": "Low drift. Coherence within acceptable range. Valid until active.",
        "color_class": "state-verified",
        "action_required": False,
    }


# ---------------------------------------------------------------------------
# Fix E — Integrity-first primary dashboard
# ---------------------------------------------------------------------------

DASHBOARD_SECTION_ORDER = [
    "integrity_state",
    "open_containments",
    "highest_drift_risk",
    "authority_violations",
    "expired_without_refresh",
    "open_registry_items",
    "laundering_warnings",
    "library_content",
]


def integrity_first_dashboard(limit: int = 50) -> dict[str, Any]:
    """Fix E: Return the integrity-first primary dashboard.

    Truth precedes content. Always.
    This is the primary landing route, not an optional admin tab.

    Section order:
    1. Integrity State
    2. Open Containments
    3. Highest Drift Risk
    4. Authority Violations
    5. Expired Without Refresh
    6. Open Registry Items
    7. Laundering Warnings
    8. Library / Content Views (last)
    """
    db.init_db()
    panel = temporal_integrity_panel(limit=limit)

    # Authority violations (failed resolution attempts)
    auth_violations = db.fetchall(
        """SELECT * FROM authority_resolution_log
           WHERE authorization_result=0
           ORDER BY timestamp DESC LIMIT ?""",
        (limit,),
    )
    auth_violation_list = [dict(r) for r in auth_violations]

    # Active escalations
    try:
        esc_rows = db.fetchall(
            """SELECT * FROM escalation_events
               WHERE escalation_level IN ('containment','escalation')
               ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        )
        active_escalations = [dict(r) for r in esc_rows]
    except Exception:
        active_escalations = []

    # Compute visual states for highest-risk nodes
    enriched_nodes = []
    for drift in panel.get("highest_drift_risk_nodes", [])[:10]:
        # Check escalation level
        try:
            esc = db.fetchone(
                "SELECT escalation_level FROM escalation_events WHERE node_id LIKE ? ORDER BY created_at DESC LIMIT 1",
                (f"%{drift['node_id'].replace('NODE:', '')}%",),
            )
            esc_level = esc["escalation_level"] if esc else None
        except Exception:
            esc_level = None
        # Check authority blocks
        try:
            auth_block = db.fetchone(
                "SELECT 1 FROM authority_resolution_log WHERE target_id LIKE ? AND authorization_result=0 LIMIT 1",
                (f"%{drift['node_id']}%",),
            )
            authority_blocked = bool(auth_block)
        except Exception:
            authority_blocked = False
        visual = compute_visual_state(drift, esc_level, authority_blocked)
        enriched_nodes.append({**drift, "visual_state": visual})

    summary = panel.get("summary", {})
    integrity_score = _compute_integrity_score(summary)

    return {
        "ok": True,
        "dashboard_version": "integrity-first",
        "section_order": DASHBOARD_SECTION_ORDER,
        "generated_at": panel.get("panel_generated_at"),

        # Section 1: Integrity State
        "integrity_state": {
            "score": integrity_score,
            "label": _integrity_label(integrity_score),
            "summary": summary,
            "visual_states": {s: 0 for s in VISUAL_STATES},
        },

        # Section 2: Open Containments
        "open_containments": panel.get("open_containment_states", []),

        # Section 3: Highest Drift Risk (with visual states)
        "highest_drift_risk": enriched_nodes,

        # Section 4: Authority Violations
        "authority_violations": auth_violation_list,
        "authority_violation_count": len(auth_violation_list),

        # Section 5: Expired Without Refresh
        "expired_without_refresh": panel.get("expired_without_refresh", []),

        # Section 6: Open Registry Items
        "open_registry_items": panel.get("open_items", []),

        # Section 7: Laundering Warnings
        "laundering_warnings": panel.get("laundering_warnings", []),

        # Section 8: Library / Content (last — not first)
        "library_content": {
            "note": "Content views follow integrity state. Truth precedes content.",
            "route": "/api/library",
        },

        # Active escalations (cross-cutting)
        "active_escalations": active_escalations,
    }


def _compute_integrity_score(summary: dict[str, Any]) -> float:
    """0.0 = fully compromised, 1.0 = fully verified."""
    total = summary.get("total_nodes_evaluated", 0)
    if not total:
        return 1.0
    verified = summary.get("active_verified_count", 0)
    refresh_req = summary.get("refresh_required_count", 0) or summary.get("refresh_required", 0)
    critical = summary.get("critical_decay", 0)
    ambiguous = summary.get("temporal_ambiguity", 0)
    bad = min(total, refresh_req + critical * 2 + ambiguous)
    score = max(0.0, 1.0 - (bad / total))
    return round(score, 3)


def _integrity_label(score: float) -> str:
    if score >= 0.85:
        return "VERIFIED"
    if score >= 0.65:
        return "DRIFTING"
    if score >= 0.40:
        return "DEGRADED"
    return "COMPROMISED"
