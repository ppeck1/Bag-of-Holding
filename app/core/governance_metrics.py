"""Governance-native observability.

Phase 25.1: BOH is measured as a legitimacy system first. API latency,
indexed-doc counts, and service availability are secondary to whether the
system prevented illegitimate canonical mutation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from app.db import connection as db

def _count(sql: str, params: tuple[Any, ...] = ()) -> int:
    try:
        row = db.fetchone(sql, params)
        return int(row["n"] if row else 0)
    except Exception:
        return 0

def _avg_resolution_latency_seconds() -> float | None:
    try:
        rows = db.fetchall(
            "SELECT created_at, resolved_at FROM open_items WHERE resolved_at IS NOT NULL",
            (),
        )
        vals: list[float] = []
        for r in rows:
            try:
                c = datetime.fromisoformat(str(r["created_at"]).replace("Z", "+00:00"))
                z = datetime.fromisoformat(str(r["resolved_at"]).replace("Z", "+00:00"))
                vals.append(max(0.0, (z - c).total_seconds()))
            except Exception:
                pass
        return round(sum(vals) / len(vals), 2) if vals else None
    except Exception:
        return None

def governance_native_metrics(limit: int = 50) -> dict[str, Any]:
    db.init_db()
    unauthorized = _count("SELECT COUNT(*) AS n FROM authority_resolution_log WHERE authorization_result=0")
    authorized = _count("SELECT COUNT(*) AS n FROM authority_resolution_log WHERE authorization_result=1")
    forced_escalations = _count("SELECT COUNT(*) AS n FROM escalation_events WHERE escalation_level='escalation'")
    containment_events = _count("SELECT COUNT(*) AS n FROM escalation_events WHERE escalation_level='containment'")
    canonical_locks = _count("SELECT COUNT(*) AS n FROM canonical_locks WHERE active=1")
    drift_events = _count("SELECT COUNT(*) AS n FROM coherence_scores WHERE priority IN ('moderate','high','critical') OR refresh_required=1")
    high_drift = _count("SELECT COUNT(*) AS n FROM coherence_scores WHERE priority IN ('high','critical')")
    open_items = _count("SELECT COUNT(*) AS n FROM open_items WHERE status='open'")
    expired_items = _count("SELECT COUNT(*) AS n FROM open_items WHERE status='expired'")

    try:
        recent_violations = [dict(r) for r in db.fetchall(
            """SELECT target_id, target_type, actor_id, actor_role, actor_team,
                      required_authority, failure_reason, timestamp, metadata_json
                 FROM authority_resolution_log
                WHERE authorization_result=0
                ORDER BY timestamp DESC LIMIT ?""",
            (limit,),
        )]
    except Exception:
        recent_violations = []

    return {
        "ok": True,
        "metric_frame": "governance_native_observability",
        "primary_metrics": {
            "unauthorized_mutation_attempts": unauthorized,
            "authority_mismatch_frequency": unauthorized,
            "authorized_resolution_attempts": authorized,
            "forced_escalation_count": forced_escalations,
            "containment_count": containment_events,
            "drift_frequency": drift_events,
            "high_drift_frequency": high_drift,
            "canonical_lock_frequency": canonical_locks,
            "resolution_latency_seconds_avg": _avg_resolution_latency_seconds(),
            "open_registry_items": open_items,
            "expired_registry_items": expired_items,
        },
        "interpretation": {
            "unauthorized_mutation_attempts": "How often the system prevented illegitimate truth mutation.",
            "authority_mismatch_frequency": "How often actor identity/team/role/scope failed authority validation.",
            "forced_escalation_count": "How often drift became operationally binding.",
            "drift_frequency": "How often truth substrate degraded or required refresh.",
            "canonical_lock_frequency": "How often canonical truth required freeze.",
            "resolution_latency_seconds_avg": "Detection-to-legitimate-resolution speed, not API speed.",
        },
        "recent_authority_violations": recent_violations,
    }
