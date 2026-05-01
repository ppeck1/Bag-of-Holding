"""app/core/coherence_decay.py: Coherence decay + refresh runtime.

Phase 24 makes time first-class in the constraint lattice.

Formula:
    C(t) = C0 * e^(-kτ) + R(t)

Where C0 is initial coherence, k is the decay constant (plane-specific),
τ is elapsed time in calendar days since observation/last evaluation, and
R(t) is bounded refresh credit from explicit refresh events.

Phase 24.1 corrections:

    P1 — Temporal ambiguity:
        Missing timestamps are ambiguity, not proof of decay.
        Nodes without timestamps enter temporal_ambiguity state.
        Epoch-0 fallback is permanently removed.

    P2 — Per-plane decay policy:
        k is not uniform. Canonical truths decay more slowly than evidence.
        Default k_daily is now 0.007 (approx quarterly review cadence).
        Each plane has a configured decay constant.

    P3 — Evaluation performance gate:
        coherence_summary() uses a 5-minute TTL cache.
        Dashboard loads read persisted coherence_scores when fresh.
        O(n) writes are not triggered on every dashboard render.

No autonomous promotion or mutation occurs here. The engine scores, warns,
and surfaces review requirements only.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any

from app.db import connection as db
from app.core.audit import log_event
from app.core.lattice_graph import LatticeNode, list_nodes, get_node

# ---------------------------------------------------------------------------
# P1: temporal_ambiguity is a first-class decay state.
# ---------------------------------------------------------------------------
DECAY_STATES = ("fresh", "aging", "stale", "critical_decay", "refresh_required", "temporal_ambiguity")

# ---------------------------------------------------------------------------
# P2: Per-plane decay policy.
# Plane names are normalised to lowercase before lookup.
# Unknown planes fall back to DEFAULT_DECAY_CONSTANT.
# ---------------------------------------------------------------------------
DEFAULT_DECAY_CONSTANT: float = 0.007       # daily; approx quarterly review cadence

PLANE_DECAY_CONSTANTS: dict[str, float] = {
    # Slow: canonical truths are deliberately stable.
    "canonical":      0.003,
    "constitutional": 0.002,
    # Medium: evidence and verification evolve with the record.
    "evidence":       0.010,
    "verification":   0.008,
    # Medium-high: operational and review planes turn over faster.
    "operational":    0.012,
    "review":         0.014,
    # Variable: narrative depends on context; use the default.
    "narrative":      0.007,
    "internal":       0.007,
    "supporting":     0.007,
    # Containment planes: explicit slow decay.
    "conflict":       0.005,
    "archive":        0.002,
    "quarantine":     0.003,
    "governance":     0.005,
}

PLANE_DECAY_LABELS: dict[str, str] = {
    "canonical":      "slow",
    "constitutional": "very slow",
    "evidence":       "fast",
    "verification":   "medium",
    "operational":    "fast",
    "review":         "fast",
    "narrative":      "variable",
    "internal":       "medium",
    "supporting":     "medium",
    "conflict":       "slow",
    "archive":        "very slow",
    "quarantine":     "slow",
    "governance":     "slow",
}

DEFAULT_REFRESH_DECAY_DAYS: float = 45.0
MAX_REFRESH_CREDIT: float = 0.35

# ---------------------------------------------------------------------------
# P3: TTL cache for coherence_summary().
# ---------------------------------------------------------------------------
_SUMMARY_CACHE_TTL: int = 300           # 5 minutes in seconds
_summary_cache: dict[str, Any] = {}


@dataclass
class RefreshEvent:
    refresh_id: str
    node_id: str
    refresh_type: str
    amount: float
    reason: str
    actor: str
    created_at: str
    evidence_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CoherenceScore:
    node_id: str
    coherence: float
    c0: float
    k: float
    tau_days: float
    refresh_credit: float
    decay_state: str
    refresh_required: bool
    priority: str
    reason: str
    evaluated_at: str
    decay_policy_label: str = "medium"
    temporal_ambiguity: bool = False
    valid_until: str | None = None
    node: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        try:
            ts = float(value)
            # P1: reject epoch-0 / near-epoch timestamps -- sentinel, not real.
            if ts < 86400:      # anything before 1970-01-02
                return None
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None


def _clamp01(v: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except Exception:
        return default


def _refresh_id(node_id: str, reason: str, actor: str) -> str:
    raw = f"{node_id}|{reason}|{actor}|{time.time_ns()}".encode()
    return "REF_" + hashlib.sha1(raw).hexdigest()[:14]


def _row_to_refresh(row: dict[str, Any]) -> RefreshEvent:
    return RefreshEvent(
        refresh_id=row["refresh_id"],
        node_id=row["node_id"],
        refresh_type=row["refresh_type"],
        amount=float(row["amount"] or 0),
        reason=row["reason"],
        actor=row["actor"],
        created_at=row["created_at"],
        evidence_refs=_json_loads(row.get("evidence_refs_json"), []),
        metadata=_json_loads(row.get("metadata_json"), {}),
    )


# ---------------------------------------------------------------------------
# Refresh event management
# ---------------------------------------------------------------------------

def record_refresh_event(
    node_id: str,
    refresh_type: str,
    amount: float,
    reason: str,
    actor: str,
    evidence_refs: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record a bounded refresh event. This does not promote canon."""
    db.init_db()
    node = get_node(node_id)
    if not node:
        return {"ok": False, "errors": [f"node not found: {node_id}"]}
    if not reason or len(reason.strip()) < 8:
        return {"ok": False, "errors": ["reason must explain the refresh basis"]}
    if not actor or actor.strip().lower() in {"auto", "autonomous", "llm"}:
        return {"ok": False, "errors": ["actor must identify a human/reviewer; autonomous refresh is illegal"]}
    amt = _clamp01(amount, 0.0)
    rid = _refresh_id(node.id, reason, actor)
    now = _now_iso()
    db.execute(
        """
        INSERT INTO coherence_refresh_events
          (refresh_id, node_id, refresh_type, amount, reason, actor, created_at, evidence_refs_json, metadata_json)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (rid, node.id, refresh_type.strip().lower() or "review", amt, reason.strip(),
         actor.strip(), now, json.dumps(evidence_refs or []), json.dumps(metadata or {})),
    )
    try:
        log_event("coherence_refresh", actor_type="human", actor_id=actor,
                  detail=json.dumps({"refresh_id": rid, "node_id": node.id, "amount": amt}))
    except Exception:
        pass
    _invalidate_summary_cache()
    return {"ok": True, "refresh": get_refresh_event(rid), "score": evaluate_node_coherence(node.id)}


def get_refresh_event(refresh_id: str) -> dict[str, Any] | None:
    row = db.fetchone("SELECT * FROM coherence_refresh_events WHERE refresh_id=?", (refresh_id,))
    return _row_to_refresh(dict(row)).to_dict() if row else None


def list_refresh_events(node_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    q = "SELECT * FROM coherence_refresh_events WHERE 1=1"
    params: list[Any] = []
    if node_id:
        nid = node_id if node_id.startswith("NODE:") else f"NODE:{node_id}"
        q += " AND node_id=?"
        params.append(nid)
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    return [_row_to_refresh(dict(r)).to_dict() for r in db.fetchall(q, tuple(params))]


# ---------------------------------------------------------------------------
# P2: Per-plane decay constant resolution
# ---------------------------------------------------------------------------

def plane_decay_constant(node: LatticeNode) -> tuple[float, str]:
    """Return (k, label) for this node's plane."""
    plane_raw = (node.plane or "").lower().strip()
    k = PLANE_DECAY_CONSTANTS.get(plane_raw, DEFAULT_DECAY_CONSTANT)
    label = PLANE_DECAY_LABELS.get(plane_raw, "medium")
    return k, label


# ---------------------------------------------------------------------------
# Scoring internals
# ---------------------------------------------------------------------------

def _node_c0(node: LatticeNode) -> float:
    q = node.q_quality if node.q_quality is not None else 0.5
    c = node.c_confidence if node.c_confidence is not None else 0.5
    return _clamp01((float(q) + float(c)) / 2.0, 0.5)


def _node_start_time(node: LatticeNode) -> datetime | None:
    """Return observed-at datetime or None on temporal ambiguity.

    P1 correction: a missing or sentinel timestamp returns None.
    Callers that receive None must set decay_state = temporal_ambiguity.
    Epoch-0 fallback is permanently removed.

    Lookup priority:
    1. payload.observed_at / updated_at / created_at
    2. cards table observed_at column (doc-backed cards store it here)
    3. docs table updated_ts (unix integer, used as last-known timestamp)
    valid_until is never used as a start time.
    """
    md = node.metadata or {}
    payload = md.get("payload") or {}
    # Priority 1: inline payload timestamps
    for key in ("observed_at", "updated_at", "created_at"):
        v = payload.get(key)
        if v:
            dt = _parse_dt(v)
            if dt is not None:
                return dt
    # Priority 2: cards table observed_at column (reject near-epoch sentinels).
    # Only the observed_at column counts — it is set by the authoring flow when
    # a human records an observation. The administrative updated_ts field is NOT
    # used: it is touched on every card write and does not represent epistemic
    # observation time. Using it would launder administrative activity into
    # apparent freshness, violating the P1 invariant.
    if node.card_id:
        row = db.fetchone(
            "SELECT observed_at FROM cards WHERE id=?", (node.card_id,)
        )
        if row:
            dt = _parse_dt(row.get("observed_at") or "")
            # Reject sentinels: must be after 1970-01-02 (86400s epoch)
            if dt is not None and dt.timestamp() > 86400:
                return dt
    return None     # temporal ambiguity


def _refresh_credit(node_id: str, now: datetime) -> float:
    credit = 0.0
    for ev in list_refresh_events(node_id=node_id, limit=500):
        created = _parse_dt(ev.get("created_at")) or now
        age_days = max(0.0, (now - created).total_seconds() / 86400.0)
        credit += _clamp01(ev.get("amount"), 0.0) * math.exp(-age_days / DEFAULT_REFRESH_DECAY_DAYS)
    return round(min(MAX_REFRESH_CREDIT, credit), 6)


def _expiry_pressure(node: LatticeNode, now: datetime) -> tuple[bool, str]:
    valid_until = _parse_dt(node.valid_until)
    if not valid_until:
        return False, "no explicit expiry"
    if valid_until <= now:
        return True, "valid_until elapsed"
    days = (valid_until - now).total_seconds() / 86400.0
    if days <= 7:
        return True, "valid_until approaching"
    return False, "valid_until active"


def _state_from_score(coherence: float, expiry_pressure: bool) -> tuple[str, str]:
    if coherence < 0.25:
        return "critical_decay", "critical"
    if coherence < 0.45:
        return "refresh_required", "high"
    if expiry_pressure and coherence < 0.65:
        return "refresh_required", "high"
    if coherence < 0.65:
        return "stale", "moderate"
    if coherence < 0.82 or expiry_pressure:
        return "aging", "low"
    return "fresh", "none"


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------

def evaluate_node_coherence(node_or_card_id: str, k: float | None = None) -> dict[str, Any]:
    """Evaluate coherence for one node.

    P1: Nodes with no timestamp enter temporal_ambiguity state.
    P2: k defaults to plane-specific constant when not explicitly supplied.
    """
    db.init_db()
    node = get_node(node_or_card_id)
    if not node:
        return {"ok": False, "errors": [f"node not found: {node_or_card_id}"]}

    now = datetime.now(timezone.utc)
    c0 = _node_c0(node)

    # P2: plane-specific decay constant
    k_plane, policy_label = plane_decay_constant(node)
    k_val = float(k) if k is not None else k_plane

    # P1: check for temporal ambiguity before applying decay
    start = _node_start_time(node)
    if start is None:
        refresh = _refresh_credit(node.id, now)
        score = CoherenceScore(
            node_id=node.id,
            coherence=round(c0, 6),     # preserve as-scored; decay not applied
            c0=round(c0, 6),
            k=round(k_val, 6),
            tau_days=0.0,
            refresh_credit=round(refresh, 6),
            decay_state="temporal_ambiguity",
            refresh_required=True,
            priority="high",
            reason=(
                "Timestamp missing. Truth freshness cannot be determined. "
                "Containment required until temporal context is established."
            ),
            evaluated_at=_now_iso(),
            decay_policy_label=policy_label,
            temporal_ambiguity=True,
            valid_until=node.valid_until,
            node=node.to_dict(),
        )
        _persist_latest_score(score)
        return {"ok": True, "score": score.to_dict()}

    tau_days = max(0.0, (now - start).total_seconds() / 86400.0)
    refresh = _refresh_credit(node.id, now)
    coherence = _clamp01((c0 * math.exp(-k_val * tau_days)) + refresh, 0.0)
    expiry_pressure, expiry_reason = _expiry_pressure(node, now)
    state, priority = _state_from_score(coherence, expiry_pressure)
    refresh_required = state in {"stale", "critical_decay", "refresh_required"}
    reason = (
        f"C(t)=C0*e^(-k*tau)+R(t); "
        f"C0={c0:.3f}, k={k_val:.4f} ({policy_label}), tau={tau_days:.1f}d, "
        f"R={refresh:.3f}; {expiry_reason}"
    )
    score = CoherenceScore(
        node_id=node.id,
        coherence=round(coherence, 6),
        c0=round(c0, 6),
        k=round(k_val, 6),
        tau_days=round(tau_days, 4),
        refresh_credit=round(refresh, 6),
        decay_state=state,
        refresh_required=refresh_required,
        priority=priority,
        reason=reason,
        evaluated_at=_now_iso(),
        decay_policy_label=policy_label,
        temporal_ambiguity=False,
        valid_until=node.valid_until,
        node=node.to_dict(),
    )
    _persist_latest_score(score)
    return {"ok": True, "score": score.to_dict()}


def _persist_latest_score(score: CoherenceScore) -> None:
    db.execute(
        """
        INSERT OR REPLACE INTO coherence_scores
          (node_id, coherence, c0, k, tau_days, refresh_credit, decay_state,
           refresh_required, priority, reason, evaluated_at, valid_until, score_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (score.node_id, score.coherence, score.c0, score.k, score.tau_days,
         score.refresh_credit, score.decay_state,
         1 if score.refresh_required else 0, score.priority, score.reason,
         score.evaluated_at, score.valid_until, json.dumps(score.to_dict())),
    )


# ---------------------------------------------------------------------------
# P3: TTL cache helpers
# ---------------------------------------------------------------------------

def _summary_cache_valid() -> bool:
    ts = _summary_cache.get("ts", 0.0)
    return (time.monotonic() - ts) < _SUMMARY_CACHE_TTL


def _invalidate_summary_cache() -> None:
    _summary_cache.clear()


# ---------------------------------------------------------------------------
# Aggregate evaluation
# ---------------------------------------------------------------------------

def evaluate_all_coherence(plane: str | None = None, limit: int = 500) -> dict[str, Any]:
    """Evaluate all nodes. Not cached -- use coherence_summary() for dashboard loads."""
    nodes = list_nodes(plane=plane, active_only=False, limit=limit)
    scores: list[dict[str, Any]] = []
    counts: dict[str, int] = {s: 0 for s in DECAY_STATES}
    for n in nodes:
        result = evaluate_node_coherence(n.id)
        if result.get("ok"):
            score = result["score"]
            scores.append(score)
            counts[score["decay_state"]] = counts.get(score["decay_state"], 0) + 1
    scores.sort(key=lambda s: (s.get("refresh_required") is not True, s.get("coherence", 1.0)))
    return {"ok": True, "counts": counts, "scores": scores, "count": len(scores)}


def stale_state_detection(limit: int = 100) -> list[dict[str, Any]]:
    scores = evaluate_all_coherence(limit=1000).get("scores", [])
    return [
        s for s in scores
        if s.get("decay_state") in {"stale", "critical_decay", "refresh_required", "temporal_ambiguity"}
    ][:limit]


def coherence_warnings(limit: int = 100) -> list[dict[str, Any]]:
    scores = evaluate_all_coherence(limit=1000).get("scores", [])
    return [s for s in scores if s.get("priority") in {"moderate", "high", "critical"}][:limit]


def refresh_requirements(limit: int = 100) -> list[dict[str, Any]]:
    scores = evaluate_all_coherence(limit=1000).get("scores", [])
    return [s for s in scores if s.get("refresh_required")][:limit]


def review_queue_resurfacing(limit: int = 100) -> list[dict[str, Any]]:
    out = []
    for s in refresh_requirements(limit=limit):
        queue_reason = (
            "requires_temporal_review" if s.get("temporal_ambiguity")
            else "custodian_refresh_review"
        )
        out.append({
            "node_id": s["node_id"],
            "priority": s["priority"],
            "decay_state": s["decay_state"],
            "temporal_ambiguity": s.get("temporal_ambiguity", False),
            "reason": s["reason"],
            "recommended_queue": queue_reason,
            "node": s.get("node"),
        })
    return out


def coherence_summary() -> dict[str, Any]:
    """Return coherence summary, using a 5-minute TTL cache.

    P3: if cached scores are fresh, read the persisted coherence_scores table
    without triggering an O(n) evaluation sweep.
    """
    db.init_db()
    if _summary_cache_valid() and _summary_cache.get("result"):
        cached = dict(_summary_cache["result"])
        cached["from_cache"] = True
        return cached

    # Full evaluation sweep.
    all_scores = evaluate_all_coherence(limit=1000)
    req = [s for s in all_scores.get("scores", []) if s.get("refresh_required")]
    crit = [s for s in all_scores.get("scores", []) if s.get("decay_state") == "critical_decay"]
    ambiguous = [s for s in all_scores.get("scores", []) if s.get("temporal_ambiguity")]

    result = {
        "ok": True,
        "counts": all_scores.get("counts", {}),
        "total": all_scores.get("count", 0),
        "refresh_required": len(req),
        "critical_decay": len(crit),
        "temporal_ambiguity": len(ambiguous),
        "top_refresh_queue": review_queue_resurfacing(limit=10),
        "decay_policy": {
            plane: {"k": k, "label": PLANE_DECAY_LABELS.get(plane, "medium")}
            for plane, k in PLANE_DECAY_CONSTANTS.items()
        },
        "from_cache": False,
    }
    _summary_cache["result"] = result
    _summary_cache["ts"] = time.monotonic()
    return result
