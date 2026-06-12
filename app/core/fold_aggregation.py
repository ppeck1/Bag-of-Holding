"""app/core/fold_aggregation.py -- Current Fold View Phase 7a cluster aggregation.

Pure, read-only roll-up of node-level CurrentFoldPackets to a derived
(axis, value) cluster, and of clusters to an axis-wide corpus, using the frozen
dual-channel contract:

  Label channel   -- worst-case precedence over members' currentness_label,
                     reusing the node 9-label order. Considers ALL members,
                     including those excluded from the numeric channel.
  Numeric channel -- authority-weighted arithmetic mean per pressure, with an
                     equal-weight fallback when the weight sum is zero. Only
                     non-excluded members participate.

Authority for every semantic here is the accepted acceptance spec
``docs/specs/fold_phase7a_aggregation_acceptance_spec.md`` (status: accepted).
Where that spec and the design buildspec differ, the acceptance spec wins.

Governance invariants:
  No DB writes. No mutation of member packets. No routes/UI/visualization.
  ``unknowns`` is always present, even when empty.
  ``canon_eligible`` is never surfaced as true at cluster or corpus scale.
  Cluster scalars are dimensional pressures, not truth values.
  The aggregate compact trace is frozen at exactly six events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.current_fold import (
    CurrentFoldPacket,
    FoldResolverTraceRef,
    FoldResolverTraceSummaryEvent,
    FoldUnknown,
)

_AGG_SCHEMA_VERSION = "ClusterFoldPacket.v0.3"
_AGG_RESOLVER_VERSION = "FoldAggregationResolver.v0.1"
_PROJECTION_VERSION = "DefaultFoldSymbolicPolicy.v0_1"
_VISUAL_CONTRACT_VERSION = "FoldView.v0.1"

_AGG_METHOD = "dual_channel_v1"
_LABEL_CHANNEL = "worst_case_precedence"
_NUMERIC_CHANNEL = "authority_weighted_mean"

# Frozen cluster label total order, worst first (acceptance spec Section 2, Q1).
# The buildspec-invented `expired`/`advisory` are deliberately NOT emitted.
CLUSTER_LABEL_PRECEDENCE: tuple[str, ...] = (
    "quarantined",
    "held",
    "superseded",
    "conflicted",
    "stale",
    "unknown",
    "current_but_contested",
    "draft_current",
    "current",
)
_LABEL_RANK: dict[str, int] = {label: i for i, label in enumerate(CLUSTER_LABEL_PRECEDENCE)}
# Unrecognized labels rank with `unknown` rather than spuriously dominating or hiding.
_UNKNOWN_RANK = _LABEL_RANK["unknown"]

# Frozen numeric-exclusion reason enum (acceptance spec Section 5 / buildspec §4).
EXCLUSION_REASONS: tuple[str, ...] = (
    "quarantined",
    "held",
    "preserved_only",
    "missing_axis_value",
    "superseded",
    "expired_validity",
)

# The ten scalar pressures, rolled up independently (acceptance spec Grounding).
SCALAR_PRESSURES: tuple[str, ...] = (
    "authority_score",
    "freshness_score",
    "evidence_strength",
    "conflict_pressure",
    "interpretability",
    "queryability",
    "canon_readiness",
    "drift_risk",
    "resolution_confidence",
    "blast_radius",
)

# Frozen six-event aggregate compact trace, in order (acceptance spec INV / buildspec §6).
AGGREGATE_TRACE_EVENTS: tuple[str, ...] = (
    "cluster_membership_resolved",
    "members_loaded",
    "label_precedence_applied",
    "numeric_rollup_computed",
    "exclusions_recorded",
    "aggregate_state_emitted",
)

# Axes whose aggregate is corpus-diagnostic only and must never be read as authority.
# "domain" is temporary: diagnostic-only pending doc→domain linkage implementation.
# "batch" is inherently diagnostic provenance and remains diagnostic permanently.
_DIAGNOSTIC_AXES: frozenset[str] = frozenset({"batch", "domain"})


# ---------------------------------------------------------------------------
# Supporting types
# ---------------------------------------------------------------------------

@dataclass
class FoldAggregateScope:
    scale: str        # "cluster" | "corpus"
    scope_id: str     # "{axis}:{value}" | "corpus:{axis}"
    axis: str
    axis_value: Any = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "scale": self.scale,
            "scope_id": self.scope_id,
            "axis": self.axis,
            "axis_value": self.axis_value,
        }


@dataclass
class FoldMemberInput:
    """A candidate member for a cluster: a resolved node packet plus the node's
    value on the cluster axis (None when the node has no value on that axis)."""
    node_packet: CurrentFoldPacket | dict[str, Any]
    axis_value: Any


@dataclass
class FoldContributor:
    scope_id: str
    authority_score: float | None   # raw member authority pressure
    weight: float | None            # normalized share actually used in the mean
    included: bool
    excluded_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "scope_id": self.scope_id,
            "authority_score": self.authority_score,
            "weight": self.weight,
            "included": self.included,
            "excluded_reason": self.excluded_reason,
        }


@dataclass
class AggregateFoldPacket:
    schema_version: str
    resolver_version: str
    projection_version: str
    visual_contract_version: str
    scope: FoldAggregateScope
    scalar_state: dict[str, Any]            # pressure -> float | None (+ metadata)
    symbolic_state: dict[str, Any]
    aggregation: dict[str, Any]
    contributors: list[FoldContributor]
    unknowns: list[FoldUnknown]
    resolver_trace_summary: list[FoldResolverTraceSummaryEvent]
    resolver_trace_ref: FoldResolverTraceRef
    canon_eligible: bool = False            # never surfaced as true
    cache_status: str = "live"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "resolver_version": self.resolver_version,
            "projection_version": self.projection_version,
            "visual_contract_version": self.visual_contract_version,
            "scope": self.scope.as_dict(),
            "scalar_state": self.scalar_state,
            "symbolic_state": self.symbolic_state,
            "aggregation": self.aggregation,
            "contributors": [c.as_dict() for c in self.contributors],
            "unknowns": [u.as_dict() for u in self.unknowns],
            "resolver_trace_summary": [e.as_dict() for e in self.resolver_trace_summary],
            "resolver_trace_ref": self.resolver_trace_ref.as_dict(),
            "canon_eligible": self.canon_eligible,
            "cache_status": self.cache_status,
        }


# ---------------------------------------------------------------------------
# scope_id helpers (acceptance spec Section 1)
# ---------------------------------------------------------------------------

def cluster_scope_id(axis: str, value: Any) -> str:
    return f"{axis}:{value}"


def corpus_scope_id(axis: str) -> str:
    return f"corpus:{axis}"


# ---------------------------------------------------------------------------
# Member-view normalization (works for node packets and cluster packets alike)
# ---------------------------------------------------------------------------

@dataclass
class _MemberView:
    scope_id: str
    currentness_label: str
    intake_label: str
    authority_score: float | None
    scalars: dict[str, float | None]


def _as_dict(packet: Any) -> dict[str, Any]:
    if isinstance(packet, dict):
        return packet
    if hasattr(packet, "as_dict"):
        return packet.as_dict()
    raise TypeError(f"Cannot normalize member packet of type {type(packet)!r}")


def _member_view(packet: CurrentFoldPacket | dict[str, Any]) -> _MemberView:
    d = _as_dict(packet)
    scope = d.get("scope", {}) or {}
    symbolic = d.get("symbolic_state", {}) or {}
    scalar = d.get("scalar_state", {}) or {}
    scalars: dict[str, float | None] = {}
    for p in SCALAR_PRESSURES:
        v = scalar.get(p)
        scalars[p] = None if v is None else float(v)
    return _MemberView(
        scope_id=str(scope.get("scope_id", "")),
        currentness_label=str(symbolic.get("currentness_label", "unknown")),
        intake_label=str(symbolic.get("intake_label", "")),
        authority_score=scalars.get("authority_score"),
        scalars=scalars,
    )


# ---------------------------------------------------------------------------
# Label channel
# ---------------------------------------------------------------------------

def _label_rank(label: str) -> int:
    return _LABEL_RANK.get(label, _UNKNOWN_RANK)


def _resolve_label(views: list[_MemberView]) -> tuple[str, dict[str, str] | None]:
    """Worst-case label over ALL members. Tie-break: lowest scope_id."""
    if not views:
        return "unknown", None
    worst_rank = min(_label_rank(v.currentness_label) for v in views)
    candidates = [v for v in views if _label_rank(v.currentness_label) == worst_rank]
    driver = min(candidates, key=lambda v: v.scope_id)
    label = CLUSTER_LABEL_PRECEDENCE[worst_rank] if worst_rank < len(CLUSTER_LABEL_PRECEDENCE) else driver.currentness_label
    return label, {"scope_id": driver.scope_id, "label": driver.currentness_label}


# ---------------------------------------------------------------------------
# Numeric exclusion classification (acceptance spec Case 5.4, Q9)
# ---------------------------------------------------------------------------

def _exclusion_reason(view: _MemberView) -> str | None:
    label = view.currentness_label
    if label == "quarantined":
        return "quarantined"
    if label == "held":
        return "held"
    if label == "superseded":
        return "superseded"
    if view.intake_label == "preserved_not_interpreted":
        return "preserved_only"
    return None


# ---------------------------------------------------------------------------
# Numeric channel
# ---------------------------------------------------------------------------

def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def _weighted_mean(pairs: list[tuple[float, float]], fallback: bool) -> float | None:
    """pairs: (weight, value) for members whose value is present.

    fallback: when True (Sigma weights == 0 over included members) use an equal
    arithmetic mean. Returns None when there are no contributing pairs.
    """
    if not pairs:
        return None
    if fallback:
        mean = sum(v for _, v in pairs) / len(pairs)
        return round(_clamp01(mean), 3)
    denom = sum(w for w, _ in pairs)
    if denom == 0:
        mean = sum(v for _, v in pairs) / len(pairs)
        return round(_clamp01(mean), 3)
    mean = sum(w * v for w, v in pairs) / denom
    return round(_clamp01(mean), 3)


# ---------------------------------------------------------------------------
# Core aggregation
# ---------------------------------------------------------------------------

def _empty_scalar_state() -> dict[str, Any]:
    state: dict[str, Any] = {p: None for p in SCALAR_PRESSURES}
    state["metric_policy"] = "FoldMetricPolicy.v0.1"
    state["scores_are_truth_values"] = False
    return state


def _build_trace(
    inputs_count: int,
    included_count: int,
    excluded_count: int,
    label: str,
    fallback: bool,
) -> list[FoldResolverTraceSummaryEvent]:
    return [
        FoldResolverTraceSummaryEvent(
            event="cluster_membership_resolved",
            result=f"{inputs_count}_members",
            confidence=1.0,
        ),
        FoldResolverTraceSummaryEvent(
            event="members_loaded",
            result=f"{included_count}/{inputs_count}",
            confidence=1.0,
        ),
        FoldResolverTraceSummaryEvent(
            event="label_precedence_applied",
            result=label,
            confidence=1.0,
        ),
        FoldResolverTraceSummaryEvent(
            event="numeric_rollup_computed",
            result="equal_weight_fallback" if fallback else "authority_weighted",
            confidence=1.0,
        ),
        FoldResolverTraceSummaryEvent(
            event="exclusions_recorded",
            result=f"{excluded_count}_excluded",
            confidence=1.0,
        ),
        FoldResolverTraceSummaryEvent(
            event="aggregate_state_emitted",
            result="emitted",
            confidence=1.0,
            collapsed_by_default=True,
        ),
    ]


def _aggregate(
    *,
    scale: str,
    scope: FoldAggregateScope,
    views: list[_MemberView],
    membership_unknowns: list[FoldUnknown],
    diagnostic_only: bool,
) -> AggregateFoldPacket:
    """Pure dual-channel roll-up over normalized member views."""
    unknowns: list[FoldUnknown] = list(membership_unknowns)
    inputs_count = len(views)

    # --- Empty cluster (zero members) -- acceptance spec Section 7 (Q2) ---
    if inputs_count == 0:
        unknowns.append(FoldUnknown(
            field="empty_cluster",
            severity="medium",
            meaning="Cluster (axis,value) resolved to zero members.",
            blocks_currentness=False,
            blocks_canon_eligibility=True,
            blocks_queryability=False,
            resolution_action="Verify the axis value exists, or treat as a typo / stale reference.",
        ))
        aggregation = {
            "method": _AGG_METHOD,
            "label_channel": _LABEL_CHANNEL,
            "numeric_channel": _NUMERIC_CHANNEL,
            "inputs_count": 0,
            "included_count": 0,
            "excluded_count": 0,
            "excluded_reasons": [],
            "label_driver": None,
            "numeric_fallback_used": False,
            "diagnostic_only": diagnostic_only,
        }
        return AggregateFoldPacket(
            schema_version=_AGG_SCHEMA_VERSION,
            resolver_version=_AGG_RESOLVER_VERSION,
            projection_version=_PROJECTION_VERSION,
            visual_contract_version=_VISUAL_CONTRACT_VERSION,
            scope=scope,
            scalar_state=_empty_scalar_state(),
            symbolic_state={"currentness_label": "unknown", "symbolic_policy": _PROJECTION_VERSION},
            aggregation=aggregation,
            contributors=[],
            unknowns=unknowns,
            resolver_trace_summary=_build_trace(0, 0, 0, "unknown", False),
            resolver_trace_ref=FoldResolverTraceRef(available=False),
        )

    # --- Label channel: ALL members (including numeric-excluded) ---
    label, label_driver = _resolve_label(views)

    # --- Exclusion classification ---
    reasons: dict[str, str | None] = {}
    included: list[_MemberView] = []
    excluded_reason_set: set[str] = set()
    for v in views:
        reason = _exclusion_reason(v)
        reasons[v.scope_id] = reason
        if reason is None:
            included.append(v)
        else:
            excluded_reason_set.add(reason)
    included_count = len(included)
    excluded_count = inputs_count - included_count

    # --- Numeric channel over included members ---
    numeric_weights = [(v.authority_score if v.authority_score is not None else 0.0) for v in included]
    weight_sum = sum(numeric_weights)
    fallback = included_count > 0 and weight_sum == 0.0

    if included_count == 0:
        # All members excluded -- acceptance spec Case 5.5 (Q4).
        scalar_state = _empty_scalar_state()
        numeric_fallback_used = False
        unknowns.append(FoldUnknown(
            field="numeric_channel_no_included_members",
            severity="medium",
            meaning="Every member was excluded from the numeric channel; no numeric aggregate is defined.",
            blocks_currentness=False,
            blocks_canon_eligibility=True,
            blocks_queryability=False,
            resolution_action="Inspect member exclusion reasons; the label channel still reflects worst-case state.",
        ))
    else:
        scalar_state = {}
        for p in SCALAR_PRESSURES:
            pairs = [
                (w, v.scalars[p])
                for w, v in zip(numeric_weights, included)
                if v.scalars.get(p) is not None
            ]
            scalar_state[p] = _weighted_mean(pairs, fallback)
        scalar_state["metric_policy"] = "FoldMetricPolicy.v0.1"
        scalar_state["scores_are_truth_values"] = False
        numeric_fallback_used = fallback

    # --- Contributors (normalized share actually used) ---
    contributors: list[FoldContributor] = []
    for v in views:
        reason = reasons.get(v.scope_id)
        if reason is not None:
            weight = 0.0
        elif fallback:
            weight = round(1.0 / included_count, 3)
        elif weight_sum > 0:
            w = v.authority_score if v.authority_score is not None else 0.0
            weight = round(w / weight_sum, 3)
        else:
            weight = 0.0
        contributors.append(FoldContributor(
            scope_id=v.scope_id,
            authority_score=v.authority_score,
            weight=weight,
            included=(reason is None),
            excluded_reason=reason,
        ))

    aggregation = {
        "method": _AGG_METHOD,
        "label_channel": _LABEL_CHANNEL,
        "numeric_channel": _NUMERIC_CHANNEL,
        "inputs_count": inputs_count,
        "included_count": included_count,
        "excluded_count": excluded_count,
        "excluded_reasons": sorted(excluded_reason_set),
        "label_driver": label_driver,
        "numeric_fallback_used": numeric_fallback_used,
        "diagnostic_only": diagnostic_only,
    }

    return AggregateFoldPacket(
        schema_version=_AGG_SCHEMA_VERSION,
        resolver_version=_AGG_RESOLVER_VERSION,
        projection_version=_PROJECTION_VERSION,
        visual_contract_version=_VISUAL_CONTRACT_VERSION,
        scope=scope,
        scalar_state=scalar_state,
        symbolic_state={"currentness_label": label, "symbolic_policy": _PROJECTION_VERSION},
        aggregation=aggregation,
        contributors=contributors,
        unknowns=unknowns,
        resolver_trace_summary=_build_trace(
            inputs_count, included_count, excluded_count, label, numeric_fallback_used,
        ),
        resolver_trace_ref=FoldResolverTraceRef(available=False),
    )


# ---------------------------------------------------------------------------
# Public cluster / corpus entry points
# ---------------------------------------------------------------------------

def aggregate_cluster(
    axis: str,
    value: Any,
    members: list[FoldMemberInput],
) -> AggregateFoldPacket:
    """Roll node packets up to cluster ``{axis}:{value}``.

    Membership is live axis equality (acceptance spec Case 1.3): a candidate is a
    member iff its ``axis_value == value``. A candidate whose ``axis_value`` is
    None is NOT a silent member and is NOT counted toward ``inputs_count`` (Q10);
    it registers a ``cluster_membership_ambiguous`` unknown (Case 1.4 / 6.1).
    """
    membership_unknowns: list[FoldUnknown] = []
    member_views: list[_MemberView] = []
    saw_ambiguous = False
    for m in members:
        if m.axis_value is None:
            saw_ambiguous = True
            continue
        if m.axis_value != value:
            continue
        member_views.append(_member_view(m.node_packet))

    if saw_ambiguous:
        membership_unknowns.append(FoldUnknown(
            field="cluster_membership_ambiguous",
            severity="medium",
            meaning=f"One or more nodes have no value on axis '{axis}' and cannot be placed in a cluster.",
            blocks_currentness=False,
            blocks_canon_eligibility=True,
            blocks_queryability=False,
            resolution_action=f"Assign an explicit '{axis}' value to the affected nodes, or review them at corpus scope.",
        ))

    scope = FoldAggregateScope(
        scale="cluster",
        scope_id=cluster_scope_id(axis, value),
        axis=axis,
        axis_value=value,
    )
    return _aggregate(
        scale="cluster",
        scope=scope,
        views=member_views,
        membership_unknowns=membership_unknowns,
        diagnostic_only=axis in _DIAGNOSTIC_AXES,
    )


def aggregate_corpus(
    axis: str,
    clusters: list[AggregateFoldPacket | dict[str, Any]],
) -> AggregateFoldPacket:
    """Roll cluster packets up to the axis-wide corpus (buildspec §2.3).

    The corpus aggregates clusters, not raw nodes. The same dual-channel contract
    applies, treating each cluster's authority pressure as its weight.
    """
    views = [_member_view(c) for c in clusters]
    scope = FoldAggregateScope(
        scale="corpus",
        scope_id=corpus_scope_id(axis),
        axis=axis,
        axis_value=None,
    )
    return _aggregate(
        scale="corpus",
        scope=scope,
        views=views,
        membership_unknowns=[],
        diagnostic_only=axis in _DIAGNOSTIC_AXES,
    )
