"""app/core/fold_metrics.py -- Fold metric policy, context loading, and scalar computation.

Implements the metric and symbolic projection layer for CurrentFoldPacket.

Modules:
  FoldMetricPolicy      -- governs freshness source, lineage cap, and scalar rules
  FoldSymbolicPolicy    -- governs symbolic label thresholds and precedence
  FoldMetricContext     -- DB-derived inputs for scalar computation (boundary object)
  FoldMetricContextLoader -- loads FoldMetricContext from DB without hidden access
  FoldScalarState       -- ten dimensional pressures [0.0, 1.0]
  FoldSymbolicState     -- human-readable labels derived from scalar + policy
  compute_fold_scalar_state -- maps context to scalar pressures
  project_symbolic_state    -- maps scalar + policy to symbolic labels

Governance invariants (Patch 002):
  Scalar scores are dimensional pressures, not truth values.
  Missing inputs register FoldUnknown, not silent defaults.
  Symbolic labels are derived from policy thresholds, not hardcoded.
  No LLM-derived scores. No random scores. All values clamped to [0.0, 1.0].
  The symbolic projector never accesses the DB.
  The metric loader never projects symbolic state.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

from app.db import connection as db


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FoldMetricPolicy:
    policy_id: str
    freshness_source_priority: tuple[str, ...]
    max_lineage_depth: int
    scalar_clamping: tuple[float, float]
    scores_are_truth_values: bool
    allow_llm_derived_scores: bool
    allow_random_scores: bool

    @classmethod
    def default(cls) -> "FoldMetricPolicy":
        return cls(
            policy_id="FoldMetricPolicy.v0.1",
            freshness_source_priority=(
                "epistemic_last_evaluated",
                "updated_ts",
            ),
            max_lineage_depth=5,
            scalar_clamping=(0.0, 1.0),
            scores_are_truth_values=False,
            allow_llm_derived_scores=False,
            allow_random_scores=False,
        )


@dataclass(frozen=True)
class FoldSymbolicPolicy:
    policy_id: str
    conflict_pressure_contested_threshold: float
    authority_score_minimum_for_current: float
    freshness_score_stale_threshold: float
    canon_readiness_minimum: float
    resolution_confidence_minimum: float

    @classmethod
    def default(cls) -> "FoldSymbolicPolicy":
        return cls(
            policy_id="DefaultFoldSymbolicPolicy.v0_1",
            conflict_pressure_contested_threshold=0.35,
            authority_score_minimum_for_current=0.30,
            freshness_score_stale_threshold=0.25,
            canon_readiness_minimum=0.50,
            resolution_confidence_minimum=0.40,
        )


# ---------------------------------------------------------------------------
# Scalar and symbolic state types
# ---------------------------------------------------------------------------

@dataclass
class FoldScalarState:
    authority_score: float
    freshness_score: float
    evidence_strength: float
    conflict_pressure: float
    interpretability: float
    queryability: float
    canon_readiness: float
    drift_risk: float
    resolution_confidence: float
    blast_radius: float
    metric_policy: str = "FoldMetricPolicy.v0.1"
    scores_are_truth_values: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "authority_score": self.authority_score,
            "freshness_score": self.freshness_score,
            "evidence_strength": self.evidence_strength,
            "conflict_pressure": self.conflict_pressure,
            "interpretability": self.interpretability,
            "queryability": self.queryability,
            "canon_readiness": self.canon_readiness,
            "drift_risk": self.drift_risk,
            "resolution_confidence": self.resolution_confidence,
            "blast_radius": self.blast_radius,
            "metric_policy": self.metric_policy,
            "scores_are_truth_values": self.scores_are_truth_values,
        }


@dataclass
class FoldSymbolicState:
    currentness_label: str
    authority_label: str
    freshness_label: str
    conflict_label: str
    intake_label: str
    symbolic_policy: str = "DefaultFoldSymbolicPolicy.v0_1"

    def as_dict(self) -> dict[str, Any]:
        return {
            "currentness_label": self.currentness_label,
            "authority_label": self.authority_label,
            "freshness_label": self.freshness_label,
            "conflict_label": self.conflict_label,
            "intake_label": self.intake_label,
            "symbolic_policy": self.symbolic_policy,
        }


# ---------------------------------------------------------------------------
# CANONVariables -- derived CANON policy projections
# ---------------------------------------------------------------------------

_CANON_VARIABLES_POLICY_ID = "canon_variables_policy_v0_1"

# Warnings emitted by the partial (batch) adapter when inputs are insufficient.
_WARN_ENTROPY = "entropy unavailable: resolution_confidence not present in batch context"
_WARN_DELTA_C_STAR = "delta_c_star unavailable: drift_risk not present in batch context"
_WARN_OMEGA = "omega_viability unavailable: node diagnostics not computed in batch context"
_WARN_MISMATCH = "mismatch_gradient unavailable: full metadata fields not present in batch context"


@dataclass
class CANONVariables:
    """Derived CANON policy variables.

    These are deterministic policy projections from existing scalar state and
    document geometry — not directly observed database facts. All non-null values
    are clamped to [0.0, 1.0]. policy_id is always 'canon_variables_policy_v0_1'.
    calculation_mode is 'exact' when all inputs are available, 'partial' otherwise.
    warnings[] lists which fields are null and why.

    omega_viability and mismatch_gradient share their formulas with the graph
    projection's viability_margin / projection_loss (see app/core/scalar_metrics.py).
    See docs/math_authority.md §8 for locked formulas.
    """
    drift_rate: float | None
    entropy: float | None
    delta_c_star: float | None
    gamma: float | None
    policy_id: str
    calculation_mode: str
    warnings: list[str] = field(default_factory=list)
    omega_viability: float | None = None
    mismatch_gradient: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "drift_rate": self.drift_rate,
            "entropy": self.entropy,
            "delta_c_star": self.delta_c_star,
            "gamma": self.gamma,
            "omega_viability": self.omega_viability,
            "mismatch_gradient": self.mismatch_gradient,
            "policy_id": self.policy_id,
            "calculation_mode": self.calculation_mode,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# FoldMetricContext -- boundary object carrying DB-derived inputs
# ---------------------------------------------------------------------------

@dataclass
class FoldMetricContext:
    doc_id: str
    edge_count: int
    cross_unapproved: int
    unresolved_conflicts: int
    lineage_depth: int
    lineage_depth_capped: bool
    freshness_age_days: int | None
    freshness_source_used: str | None
    superseded: bool
    supporting_sources: int
    missing_fields: list[str]
    # Intake capability (None when no record exists)
    intake_interpretable: bool | None
    intake_queryable: bool | None
    intake_safety_lane: str | None
    intake_normalizable: bool | None
    intake_preservable: bool | None
    intake_failure_reason: str | None
    # Epistemic state
    epistemic_d: int | None
    epistemic_q: float | None
    epistemic_c: float | None
    # Raw docs row (for canon-geometry; empty dict when unavailable)
    doc_row: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# FoldMetricContextLoader
# ---------------------------------------------------------------------------

def _safe_fetchone(q: str, params: tuple = ()) -> dict[str, Any]:
    try:
        row = db.fetchone(q, params)
        return dict(row) if row else {}
    except Exception:
        return {}


def _safe_fetchall(q: str, params: tuple = ()) -> list[dict[str, Any]]:
    try:
        return [dict(r) for r in db.fetchall(q, params)]
    except Exception:
        return []


def _safe_count(q: str, params: tuple = ()) -> int:
    try:
        row = db.fetchone(q, params)
        if row:
            return int(list(dict(row).values())[0] or 0)
        return 0
    except Exception:
        return 0


def _parse_freshness_days(value: Any, source: str) -> int | None:
    """Convert a timestamp value to age in days. Returns None on failure."""
    now_ts = time.time()
    try:
        if source == "epistemic_last_evaluated" and value:
            import datetime
            dt = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None: dt = dt.replace(tzinfo=datetime.timezone.utc)
            ts = dt.timestamp()
            return max(0, int((now_ts - ts) / 86400))
        elif source == "updated_ts" and value:
            ts = float(value)
            return max(0, int((now_ts - ts) / 86400))
    except Exception:
        pass
    return None


class FoldMetricContextLoader:
    """Loads DB-derived metric context for scalar computation.

    Isolates all database access so compute_fold_scalar_state() remains pure.
    """

    def __init__(self, policy: FoldMetricPolicy | None = None) -> None:
        self._policy = policy or FoldMetricPolicy.default()

    def load(self, doc_id: str) -> FoldMetricContext:
        missing: list[str] = []
        doc = _safe_fetchone("SELECT * FROM docs WHERE doc_id = ?", (doc_id,))

        # --- Edge counts ---
        edge_count = _safe_count(
            "SELECT COUNT(*) FROM doc_edges WHERE source_doc_id = ? OR target_doc_id = ?",
            (doc_id, doc_id),
        )
        cross_unapproved = _safe_count(
            """SELECT COUNT(*) FROM doc_edges
               WHERE (source_doc_id = ? OR target_doc_id = ?)
                 AND state <= 0""",
            (doc_id, doc_id),
        )

        # --- Conflicts ---
        unresolved_conflicts = _safe_count(
            """SELECT COUNT(*) FROM conflicts
               WHERE doc_ids LIKE ?
                 AND (acknowledged IS NULL OR acknowledged = 0)""",
            (f"%{doc_id}%",),
        )

        # --- Supersession ---
        superseded_row = _safe_fetchone(
            """SELECT id FROM lineage
               WHERE doc_id = ? AND relationship IN ('superseded_by', 'superseded')
               LIMIT 1""",
            (doc_id,),
        )
        superseded = bool(superseded_row)

        # --- Supporting sources ---
        supporting_sources = _safe_count(
            """SELECT COUNT(*) FROM lineage
               WHERE related_doc_id = ?
                 AND relationship IN ('derives', 'derived_from', 'supports', 'cites')""",
            (doc_id,),
        )

        # --- Lineage depth (capped walk) ---
        lineage_depth, capped = self._walk_lineage_depth(doc_id)

        # --- Freshness ---
        freshness_age_days: int | None = None
        freshness_source_used: str | None = None
        for source_col in self._policy.freshness_source_priority:
            raw = doc.get(source_col)
            if raw is not None:
                days = _parse_freshness_days(raw, source_col)
                if days is not None:
                    freshness_age_days = days
                    freshness_source_used = source_col
                    break
        if freshness_age_days is None:
            missing.append("freshness_age_days")

        # --- Intake capability (match by path via source_ref) ---
        doc_path = doc.get("path")
        intake: dict[str, Any] = {}
        if doc_path:
            intake = _safe_fetchone(
                "SELECT * FROM intake_capabilities WHERE source_ref = ? LIMIT 1",
                (doc_path,),
            )

        intake_interpretable: bool | None = None
        intake_queryable: bool | None = None
        intake_safety_lane: str | None = None
        intake_normalizable: bool | None = None
        intake_preservable: bool | None = None
        intake_failure_reason: str | None = None

        if intake:
            intake_interpretable = bool(intake.get("interpretable", 0))
            intake_queryable = bool(intake.get("queryable", 0))
            intake_safety_lane = intake.get("safety_lane")
            intake_normalizable = bool(intake.get("normalizable", 0))
            intake_preservable = bool(intake.get("preservable", 0))
            intake_failure_reason = intake.get("failure_reason")
        # else: leave as None -- will register unknowns in adapter

        # --- Epistemic ---
        epistemic_d: int | None = None
        epistemic_q: float | None = None
        epistemic_c: float | None = None
        try:
            ed = doc.get("epistemic_d")
            eq = doc.get("epistemic_q")
            ec = doc.get("epistemic_c")
            if ed is not None:
                epistemic_d = int(ed)
            if eq is not None:
                epistemic_q = float(eq)
            if ec is not None:
                epistemic_c = float(ec)
        except Exception:
            pass

        return FoldMetricContext(
            doc_id=doc_id,
            edge_count=edge_count,
            cross_unapproved=cross_unapproved,
            unresolved_conflicts=unresolved_conflicts,
            lineage_depth=lineage_depth,
            lineage_depth_capped=capped,
            freshness_age_days=freshness_age_days,
            freshness_source_used=freshness_source_used,
            superseded=superseded,
            supporting_sources=supporting_sources,
            missing_fields=missing,
            intake_interpretable=intake_interpretable,
            intake_queryable=intake_queryable,
            intake_safety_lane=intake_safety_lane,
            intake_normalizable=intake_normalizable,
            intake_preservable=intake_preservable,
            intake_failure_reason=intake_failure_reason,
            epistemic_d=epistemic_d,
            epistemic_q=epistemic_q,
            epistemic_c=epistemic_c,
            doc_row=doc,
        )

    def _walk_lineage_depth(self, doc_id: str) -> tuple[int, bool]:
        """Walk the lineage table BFS to measure depth. Returns (depth, capped)."""
        cap = self._policy.max_lineage_depth
        visited: set[str] = {doc_id}
        frontier: set[str] = {doc_id}
        depth = 0
        while frontier and depth < cap:
            rows = []
            for fid in frontier:
                rows += _safe_fetchall(
                    "SELECT related_doc_id FROM lineage WHERE doc_id = ? LIMIT 20",
                    (fid,),
                )
            next_frontier: set[str] = set()
            for r in rows:
                rid = r.get("related_doc_id", "")
                if rid and rid not in visited:
                    visited.add(rid)
                    next_frontier.add(rid)
            if not next_frontier:
                break
            frontier = next_frontier
            depth += 1
        capped = depth >= cap and bool(frontier)
        return depth, capped


# ---------------------------------------------------------------------------
# Scalar computation
# ---------------------------------------------------------------------------

def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(v) if v == v else lo))  # NaN-safe


_AUTHORITY_SCORES: dict[str, float] = {
    "canonical": 1.0,
    "trusted": 0.90,
    "approved": 0.80,
    "reviewed": 0.75,
    "under_review": 0.55,
    "custodian_review": 0.50,
    "draft": 0.35,
    "non_authoritative": 0.20,
    "unknown": 0.10,
}

_FRESHNESS_DECAY: list[tuple[int, float]] = [
    (7,   1.00),
    (30,  0.90),
    (90,  0.70),
    (180, 0.50),
    (365, 0.30),
]


def _freshness_from_days(days: int | None) -> float:
    if days is None:
        return 0.0
    for threshold, score in _FRESHNESS_DECAY:
        if days <= threshold:
            return score
    return 0.10


def compute_fold_scalar_state(
    base_packet: dict[str, Any],
    context: FoldMetricContext,
    policy: FoldMetricPolicy | None = None,
) -> FoldScalarState:
    """Compute ten dimensional scalar pressures for a CurrentFoldPacket.

    Inputs come exclusively from base_packet (structural facts) and
    context (DB-derived metric context). No DB access occurs here.
    All outputs are clamped to [0.0, 1.0].
    These are not truth scores.
    """
    policy = policy or FoldMetricPolicy.default()
    facets = base_packet.get("facets", {})
    auth_facet = facets.get("authority", {})
    conflict_facet = facets.get("conflicts", {})
    chunk_facet = facets.get("chunks", {})

    authority_state = (auth_facet.get("authority_state") or "").lower()
    authority_score = _clamp(
        _AUTHORITY_SCORES.get(authority_state, 0.10)
        + (0.05 if context.epistemic_c and context.epistemic_c > 0.7 else 0.0)
    )

    freshness_score = _clamp(_freshness_from_days(context.freshness_age_days))

    chunk_count = chunk_facet.get("count", 0) or 0
    evidence_strength = _clamp(
        context.supporting_sources / 5.0 * 0.5
        + min(chunk_count, 10) / 10.0 * 0.5
    )

    conflict_count = conflict_facet.get("count", 0) or 0
    conflict_pressure = _clamp(
        (context.unresolved_conflicts + conflict_count) / 6.0
        + (context.cross_unapproved / 8.0) * 0.20
    )

    if context.intake_interpretable is None:
        interpretability = 0.50
    else:
        interpretability = 0.90 if context.intake_interpretable else 0.15

    if context.intake_queryable is None:
        queryability = 0.50
    else:
        queryability = 0.90 if context.intake_queryable else 0.15

    canon_readiness = _clamp(
        authority_score * 0.40
        + freshness_score * 0.20
        + (1.0 - conflict_pressure) * 0.20
        + evidence_strength * 0.20
    )

    drift_risk = _clamp(
        (1.0 - authority_score) * 0.25
        + (1.0 - freshness_score) * 0.25
        + conflict_pressure * 0.25
        + (1.0 - evidence_strength) * 0.25
    )

    missing_penalty = min(len(context.missing_fields) / 8.0, 0.50)
    resolution_confidence = _clamp(
        1.0 - missing_penalty - conflict_pressure * 0.25
    )

    blast_radius = _clamp(
        context.edge_count / 20.0 * 0.60
        + context.lineage_depth / 5.0 * 0.40
    )

    return FoldScalarState(
        authority_score=round(authority_score, 3),
        freshness_score=round(freshness_score, 3),
        evidence_strength=round(evidence_strength, 3),
        conflict_pressure=round(conflict_pressure, 3),
        interpretability=round(interpretability, 3),
        queryability=round(queryability, 3),
        canon_readiness=round(canon_readiness, 3),
        drift_risk=round(drift_risk, 3),
        resolution_confidence=round(resolution_confidence, 3),
        blast_radius=round(blast_radius, 3),
        metric_policy=policy.policy_id,
        scores_are_truth_values=False,
    )


# ---------------------------------------------------------------------------
# Symbolic projection
# ---------------------------------------------------------------------------

def _authority_label(authority_state: str) -> str:
    mapping = {
        "canonical": "canonical",
        "trusted": "trusted",
        "approved": "approved",
        "reviewed": "reviewed",
        "under_review": "under_review",
        "custodian_review": "under_review",
        "draft": "draft",
        "non_authoritative": "non_authoritative",
    }
    return mapping.get(authority_state.lower(), "unknown")


def _freshness_label(freshness_score: float) -> str:
    if freshness_score >= 0.85:
        return "fresh"
    if freshness_score >= 0.60:
        return "valid"
    if freshness_score >= 0.40:
        return "aging"
    if freshness_score > 0.0:
        return "stale"
    return "unknown"


def _conflict_label(conflict_pressure: float, has_blocking: bool) -> str:
    if has_blocking:
        return "blocking_conflict"
    if conflict_pressure >= 0.35:
        return "contested"
    if conflict_pressure > 0.0:
        return "minor_conflict"
    return "none"


def _intake_label(
    interpretable: bool | None,
    queryable: bool | None,
    safety_lane: str | None,
) -> str:
    lane = (safety_lane or "").lower()
    if lane == "quarantine":
        return "quarantined"
    if lane == "hold":
        return "held"
    if interpretable and queryable:
        return "interpretable_queryable"
    if interpretable:
        return "interpretable_not_queryable"
    if interpretable is False:
        return "preserved_not_interpreted"
    return "unknown"


def project_symbolic_state(
    scalar_state: FoldScalarState,
    base_packet: dict[str, Any],
    policy: FoldSymbolicPolicy | None = None,
) -> FoldSymbolicState:
    """Project human-readable symbolic labels from scalar pressures and policy.

    Must not access the database.
    Must not call LLM services.
    Must not mutate scalar_state or base_packet.
    Thresholds are read from policy, never hardcoded.
    """
    policy = policy or FoldSymbolicPolicy.default()

    facets = base_packet.get("facets", {})
    auth_facet = facets.get("authority", {})
    conflict_facet = facets.get("conflicts", {})
    authority_state = (auth_facet.get("authority_state") or "").lower()
    status = (auth_facet.get("status") or "").lower()
    conflicts = conflict_facet.get("items", [])
    has_blocking = bool(conflicts)

    # Determine safety_lane: prefer intake_capability from context summary
    safety_lane_raw = (
        base_packet.get("intake_capability", {}).get("safety_lane")
        or status
        or ""
    ).lower()

    # --- Precedence rules (Patch 002 Section 5.3) ---
    if safety_lane_raw == "quarantine" or status == "quarantine":
        currentness = "quarantined"
    elif safety_lane_raw == "hold":
        currentness = "held"
    elif base_packet.get("superseded"):
        currentness = "superseded"
    elif has_blocking:
        currentness = "conflicted"
    elif scalar_state.freshness_score < policy.freshness_score_stale_threshold:
        currentness = "stale"
    elif scalar_state.authority_score < policy.authority_score_minimum_for_current:
        currentness = "unknown"
    elif scalar_state.conflict_pressure >= policy.conflict_pressure_contested_threshold:
        currentness = "current_but_contested"
    elif authority_state in {"draft", "non_authoritative", "unknown", ""}:
        currentness = "draft_current"
    else:
        currentness = "current"

    return FoldSymbolicState(
        currentness_label=currentness,
        authority_label=_authority_label(authority_state),
        freshness_label=_freshness_label(scalar_state.freshness_score),
        conflict_label=_conflict_label(scalar_state.conflict_pressure, has_blocking),
        intake_label=_intake_label(None, None, safety_lane_raw),
        symbolic_policy=policy.policy_id,
    )


# ---------------------------------------------------------------------------
# CANON policy variable formula helpers (single location for each formula)
# ---------------------------------------------------------------------------

def _cv_drift_rate(fresh: float, canon: float) -> float:
    return _clamp((1.0 - fresh) ** 1.5 * 0.7 + (1.0 - canon) * 0.3)


def _cv_entropy(conf: float, missing_count: int) -> float:
    return _clamp((1.0 - conf) * 0.6 + min(missing_count / 6.0, 0.4))


def _cv_delta_c_star(canon: float, conf_p: float, drift: float) -> float:
    return _clamp(canon * (1.0 - conf_p) * (1.0 - drift))


def _cv_gamma(auth: float, conf_p: float) -> float:
    return _clamp(auth * (1.0 - conf_p))


# ---------------------------------------------------------------------------
# CANON variable compute functions
# ---------------------------------------------------------------------------

def compute_canon_geometry(
    doc_row: dict[str, Any],
    diagnostics: dict[str, Any],
) -> dict[str, float]:
    """Compute omega_viability and mismatch_gradient from a raw docs row + DCNS
    diagnostics, using the neutral scalar_metrics formulas and the SAME authority
    derivation, completeness defaults, and diagnostic counts the graph projection
    uses. This guarantees graph/Fold parity for these two fields.

    diagnostics is the dict returned by app.core.dcns.get_node_diagnostics(doc_id):
    keys conflict_count, expired_coordinate_count, uncertain_coordinate_count.
    Pure given its inputs; no DB access here.
    """
    from app.core import scalar_metrics
    from app.core.authority_state import authority_score

    import os
    path = doc_row.get("path") or ""
    basename = os.path.basename(path).replace(".md", "") or str(doc_row.get("doc_id", ""))[:12]

    # Canonical completeness record (graph-identical defaults).
    record = scalar_metrics.viability_completeness_record(doc_row, basename=basename)
    completeness = scalar_metrics.metadata_completeness(record)

    # Authority via the same core function the graph uses (status, layer, review).
    layer = (doc_row.get("canonical_layer") or "quarantine")
    authority = authority_score(
        doc_row.get("status") or "",
        layer,
        doc_row.get("review_state") or "",
    )

    conflict_count = diagnostics.get("conflict_count", 0) or 0
    expired = diagnostics.get("expired_coordinate_count", 0) or 0
    uncertain = diagnostics.get("uncertain_coordinate_count", 0) or 0

    return {
        "omega_viability": round(
            scalar_metrics.omega_viability(authority, conflict_count, expired, uncertain, completeness), 3
        ),
        "mismatch_gradient": round(
            scalar_metrics.mismatch_gradient(completeness), 3
        ),
    }


# ---------------------------------------------------------------------------
# CANON variable compute functions
# ---------------------------------------------------------------------------

def compute_canon_variables(
    scalar: FoldScalarState,
    context: FoldMetricContext,
    geometry: dict[str, float] | None = None,
) -> CANONVariables:
    """Compute the derived CANON policy variables (exact mode).

    Requires full FoldScalarState and FoldMetricContext. drift_rate, entropy,
    delta_c_star, gamma are always populated. omega_viability and mismatch_gradient
    are populated only when `geometry` is supplied (from compute_canon_geometry);
    otherwise they are None with warnings.
    calculation_mode = 'exact'. policy_id = canon_variables_policy_v0_1.
    See docs/math_authority.md §8 for locked formulas.
    These are policy-derived projections, not directly observed facts.
    """
    fresh  = _clamp(scalar.freshness_score)
    canon  = _clamp(scalar.canon_readiness)
    conf   = _clamp(scalar.resolution_confidence)
    conf_p = _clamp(scalar.conflict_pressure)
    drift  = _clamp(scalar.drift_risk)
    auth   = _clamp(scalar.authority_score)
    miss   = len(context.missing_fields)

    warnings: list[str] = []
    omega = mismatch = None
    if geometry is not None:
        omega = geometry.get("omega_viability")
        mismatch = geometry.get("mismatch_gradient")
    else:
        warnings.extend([_WARN_OMEGA, _WARN_MISMATCH])

    return CANONVariables(
        drift_rate   = round(_cv_drift_rate(fresh, canon), 3),
        entropy      = round(_cv_entropy(conf, miss), 3),
        delta_c_star = round(_cv_delta_c_star(canon, conf_p, drift), 3),
        gamma        = round(_cv_gamma(auth, conf_p), 3),
        omega_viability   = omega,
        mismatch_gradient = mismatch,
        policy_id         = _CANON_VARIABLES_POLICY_ID,
        calculation_mode  = "exact",
        warnings=warnings,
    )


def compute_canon_variables_partial(
    auth_score: float,
    freshness_score: float,
    conflict_pressure: float,
    canon_readiness: float,
) -> CANONVariables:
    """Batch adapter: computes only the variables derivable from four batch fields.

    entropy, delta_c_star, omega_viability, mismatch_gradient are unavailable in
    batch context (they need resolution_confidence, drift_risk, node diagnostics,
    or full metadata fields). All four are returned as None with explicit warnings.
    calculation_mode = 'partial'. Delegates to the same formula helpers as the
    exact path — no formula logic is duplicated here.
    """
    fresh  = _clamp(freshness_score)
    canon  = _clamp(canon_readiness)
    auth   = _clamp(auth_score)
    conf_p = _clamp(conflict_pressure)

    return CANONVariables(
        drift_rate   = round(_cv_drift_rate(fresh, canon), 3),
        entropy      = None,
        delta_c_star = None,
        gamma        = round(_cv_gamma(auth, conf_p), 3),
        omega_viability   = None,
        mismatch_gradient = None,
        policy_id        = _CANON_VARIABLES_POLICY_ID,
        calculation_mode = "partial",
        warnings=[_WARN_ENTROPY, _WARN_DELTA_C_STAR, _WARN_OMEGA, _WARN_MISMATCH],
    )
