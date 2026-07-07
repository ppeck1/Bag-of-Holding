"""app/core/current_fold.py -- CurrentFoldPacket types, adapter, and resolver.

Implements the read-model contract for Current Fold View (Phases 0-5).

Exported symbols:
  FoldScope                       -- scale + scope_id identity
  FoldUnknown                     -- first-class unknown registration
  FoldResolverTraceSummaryEvent   -- one event in the compact six-event trace
  FoldResolverTraceRef            -- pointer to the lazy full-trace endpoint
  CurrentFoldPacket               -- complete resolver output packet
  adapt_folded_node_to_current_fold  -- adapter from folded-node packet
  current_fold_from_folded_node      -- canonical four-step resolver

Governance (Patch 001 + 002):
  Scalar scores are dimensional pressures, not truth values.
  unknowns[] must always be present, even when empty.
  The adapter never invents state; missing inputs become FoldUnknowns.
  The compact trace is frozen at six events; no extra events may be added here.
  Resolvers may not default silently on missing inputs.
  Deferred (Phase 6-8): cluster aggregation, corpus rollup, 2.5D/3D spatial.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.folded_node import build_folded_node_packet
from app.core.fold_metrics import (
    CANONVariables,
    FoldMetricContextLoader,
    FoldMetricPolicy,
    FoldScalarState,
    FoldSymbolicState,
    FoldSymbolicPolicy,
    compute_canon_variables,
    compute_fold_scalar_state,
    project_symbolic_state,
)

_SCHEMA_VERSION = "CurrentFoldPacket.v0.3"
_RESOLVER_VERSION = "CurrentFoldResolver.v0.1"
_PROJECTION_VERSION = "DefaultFoldSymbolicPolicy.v0_1"
_VISUAL_CONTRACT_VERSION = "FoldView.v0.1"


# ---------------------------------------------------------------------------
# Supporting types
# ---------------------------------------------------------------------------

@dataclass
class WhyCurrentRow:
    dir: str      # "pos" | "weak" | "neutral"
    factor: str   # human-readable factor name
    evi: str      # evidence value (date, cert ID, count, etc.)

    def as_dict(self) -> dict[str, Any]:
        return {"dir": self.dir, "factor": self.factor, "evi": self.evi}

@dataclass
class FoldScope:
    scale: str       # "node" for this build; cluster/corpus deferred
    scope_id: str    # doc_id for node scale


@dataclass
class FoldUnknown:
    field: str
    severity: str                    # "high" | "medium" | "low"
    meaning: str
    blocks_currentness: bool
    blocks_canon_eligibility: bool
    blocks_queryability: bool
    resolution_action: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "severity": self.severity,
            "meaning": self.meaning,
            "blocks_currentness": self.blocks_currentness,
            "blocks_canon_eligibility": self.blocks_canon_eligibility,
            "blocks_queryability": self.blocks_queryability,
            "resolution_action": self.resolution_action,
        }


@dataclass
class FoldResolverTraceSummaryEvent:
    event: str
    result: str
    confidence: float
    collapsed_by_default: bool = False
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "event": self.event,
            "result": self.result,
            "confidence": self.confidence,
        }
        if self.collapsed_by_default:
            d["collapsed_by_default"] = True
        if self.detail:
            d["detail"] = self.detail
        return d


@dataclass
class FoldResolverTraceRef:
    available: bool
    endpoint: str | None = None
    trace_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"available": self.available}
        if self.endpoint is not None:
            d["endpoint"] = self.endpoint
        if self.trace_id is not None:
            d["trace_id"] = self.trace_id
        return d


@dataclass
class FoldScaleAction:
    """A safe, declarative scale-transition affordance (Phase 6).

    Navigational only -- never implies a mutation. When allowed is False, reason
    must explain why (e.g. the node has no value on that axis).
    """
    label: str
    target_scale: str
    target_axis: str
    allowed: bool
    target_id: str | None = None
    reason: str | None = None
    filter: str | None = None

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "label": self.label,
            "target_scale": self.target_scale,
            "target_axis": self.target_axis,
            "target_id": self.target_id,
            "allowed": self.allowed,
        }
        if self.reason is not None:
            d["reason"] = self.reason
        if self.filter is not None:
            d["filter"] = self.filter
        return d


# ---------------------------------------------------------------------------
# CurrentFoldPacket
# ---------------------------------------------------------------------------

@dataclass
class CurrentFoldPacket:
    # Versioning
    schema_version: str
    resolver_version: str
    projection_version: str
    visual_contract_version: str

    # Identity
    scope: FoldScope

    # State layers
    local_state: dict[str, Any]         # doc title, summary, authority, etc.
    scalar_state: FoldScalarState
    symbolic_state: FoldSymbolicState

    # Governance signals
    projection_hints: dict[str, Any]
    unknowns: list[FoldUnknown]

    # Resolver trace
    resolver_trace_summary: list[FoldResolverTraceSummaryEvent]
    resolver_trace_ref: FoldResolverTraceRef

    # Cache
    cache_status: str = "live"

    # Scale transition affordances (Phase 6)
    scale_actions: list[FoldScaleAction] = field(default_factory=list)

    # Why current explanation rows (Phase 7c)
    why_current: list[WhyCurrentRow] = field(default_factory=list)

    # Derived CANON policy variables (canon_variables_v0_1)
    canon_variables: CANONVariables | None = field(default=None)

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "schema_version": self.schema_version,
            "resolver_version": self.resolver_version,
            "projection_version": self.projection_version,
            "visual_contract_version": self.visual_contract_version,
            "scope": {
                "scale": self.scope.scale,
                "scope_id": self.scope.scope_id,
            },
            "local_state": self.local_state,
            "scalar_state": self.scalar_state.as_dict(),
            "symbolic_state": self.symbolic_state.as_dict(),
            "projection_hints": self.projection_hints,
            "unknowns": [u.as_dict() for u in self.unknowns],
            "resolver_trace_summary": [e.as_dict() for e in self.resolver_trace_summary],
            "resolver_trace_ref": self.resolver_trace_ref.as_dict(),
            "cache_status": self.cache_status,
            "scale_actions": [a.as_dict() for a in self.scale_actions],
            "why_current": [r.as_dict() for r in self.why_current],
        }
        if self.canon_variables is not None:
            d["canon_variables"] = self.canon_variables.as_dict()
        return d


# ---------------------------------------------------------------------------
# Adapter -- Step 7
# ---------------------------------------------------------------------------

def _extract_local_state(base_packet: dict[str, Any]) -> dict[str, Any]:
    facets = base_packet.get("facets", {})
    auth = facets.get("authority", {})
    lifecycle = facets.get("lifecycle", {})
    provenance = facets.get("provenance", {})
    source = facets.get("source", {})
    conflicts = facets.get("conflicts", {})

    return {
        "doc_id": base_packet.get("doc_id"),
        "title": base_packet.get("title"),
        "summary": base_packet.get("summary"),
        "path": source.get("path"),
        "authority_state": auth.get("authority_state"),
        "canon_eligible": auth.get("canon_eligible"),
        "safety_lane": auth.get("safety_lane") or lifecycle.get("safety_lane"),
        "status": lifecycle.get("status"),
        "created_at": provenance.get("created_at"),
        "updated_at": provenance.get("updated_at"),
        "source_type": source.get("type"),
        "conflict_count": conflicts.get("count", 0),
    }


def _build_compact_trace(
    base_packet: dict[str, Any],
    scalar_state: FoldScalarState,
    symbolic_state: FoldSymbolicState,
    unknowns: list[FoldUnknown],
) -> list[FoldResolverTraceSummaryEvent]:
    """Build the frozen six-event compact trace. No extra events permitted here."""
    facets = base_packet.get("facets", {})
    auth = facets.get("authority", {})
    conflicts = facets.get("conflicts", {})

    authority_state = (auth.get("authority_state") or "unknown").lower()
    conflict_count = conflicts.get("count", 0) or 0
    has_blocking = bool(conflicts.get("items"))

    # Event 1: authority_state_checked
    auth_confidence = round(scalar_state.authority_score, 3)
    auth_result = authority_state if authority_state else "unknown"

    # Event 2: supersession_checked
    superseded = bool(base_packet.get("superseded"))
    supersession_result = "superseded" if superseded else "not_superseded"
    supersession_conf = 0.90 if not superseded else 0.95

    # Event 3: conflicts_checked
    if has_blocking:
        conflict_result = "blocking_conflicts_present"
        conflict_conf = 0.95
    elif conflict_count > 0:
        conflict_result = "non_blocking_conflicts"
        conflict_conf = 0.90
    else:
        conflict_result = "none"
        conflict_conf = 0.95

    # Event 4: freshness_checked
    freshness_conf = round(scalar_state.freshness_score, 3)
    freshness_result = symbolic_state.freshness_label

    # Event 5: intake_capability_checked
    intake_label = symbolic_state.intake_label
    intake_conf = (
        0.80 if intake_label not in {"unknown", "quarantined", "held"} else 0.50
    )

    # Event 6: scalar_state_computed (collapsed by default)
    scalar_detail = {
        "metric_policy": scalar_state.metric_policy,
        "symbolic_policy": scalar_state.metric_policy,
        "scores_are_truth_values": False,
        "missing_inputs": len([u for u in unknowns if "metric" in u.field or "freshness" in u.field]),
    }

    return [
        FoldResolverTraceSummaryEvent(
            event="authority_state_checked",
            result=auth_result,
            confidence=auth_confidence,
        ),
        FoldResolverTraceSummaryEvent(
            event="supersession_checked",
            result=supersession_result,
            confidence=supersession_conf,
        ),
        FoldResolverTraceSummaryEvent(
            event="conflicts_checked",
            result=conflict_result,
            confidence=conflict_conf,
        ),
        FoldResolverTraceSummaryEvent(
            event="freshness_checked",
            result=freshness_result,
            confidence=freshness_conf,
        ),
        FoldResolverTraceSummaryEvent(
            event="intake_capability_checked",
            result=intake_label,
            confidence=intake_conf,
        ),
        FoldResolverTraceSummaryEvent(
            event="scalar_state_computed",
            result="computed",
            confidence=round(scalar_state.resolution_confidence, 3),
            collapsed_by_default=True,
            detail=scalar_detail,
        ),
    ]


def _collect_unknowns(
    base_packet: dict[str, Any],
    scalar_state: FoldScalarState,
    metric_context_missing: list[str],
    lineage_depth_capped: bool,
) -> list[FoldUnknown]:
    unknowns: list[FoldUnknown] = []
    facets = base_packet.get("facets", {})
    auth = facets.get("authority", {})

    authority_state = (auth.get("authority_state") or "").lower()
    if not authority_state or authority_state == "unknown":
        unknowns.append(FoldUnknown(
            field="authority_state",
            severity="high",
            meaning="No authority state was found for this node.",
            blocks_currentness=True,
            blocks_canon_eligibility=True,
            blocks_queryability=False,
            resolution_action="Route node to review queue.",
        ))

    if "freshness_age_days" in metric_context_missing:
        unknowns.append(FoldUnknown(
            field="freshness_age_days",
            severity="medium",
            meaning="No freshness timestamp available; both epistemic_last_evaluated and updated_ts are null.",
            blocks_currentness=False,
            blocks_canon_eligibility=True,
            blocks_queryability=False,
            resolution_action="Add an epistemic evaluation or update timestamp to this node.",
        ))

    if lineage_depth_capped:
        unknowns.append(FoldUnknown(
            field="lineage_depth",
            severity="low",
            meaning="Lineage traversal capped at 5 hops; full depth unresolved.",
            blocks_currentness=False,
            blocks_canon_eligibility=False,
            blocks_queryability=False,
            resolution_action="Review lineage manually or raise traversal cap in FoldMetricPolicy.",
        ))

    canon_eligible = auth.get("canon_eligible")
    if canon_eligible is None:
        unknowns.append(FoldUnknown(
            field="canon_eligible",
            severity="medium",
            meaning="Canon eligibility field is absent from authority facet.",
            blocks_currentness=False,
            blocks_canon_eligibility=True,
            blocks_queryability=False,
            resolution_action="Evaluate and set canon_eligible on the document.",
        ))

    return unknowns


def _build_node_scale_actions(base_packet: dict[str, Any]) -> list[FoldScaleAction]:
    """Derive node-scale roll-up affordances from axis values on the folded packet.

    Phase 6: declares roll-up targets to the clusters this node belongs to. Target ids
    use the deterministic "{axis}:{value}" form (buildspec 2.1); the cluster endpoints
    that consume them are Phase 7b. Domain linkage is a read-only lookup over existing
    docs/cards/lattice data; no mutation or schema assumption is introduced here.
    """
    summary = base_packet.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    facets = base_packet.get("facets", {})
    if not isinstance(facets, dict):
        facets = {}

    actions: list[FoldScaleAction] = []

    # --- project axis (working: docs.project is on every node) ---
    project = summary.get("project")
    if project:
        actions.append(FoldScaleAction(
            label="Roll up to project",
            target_scale="cluster",
            target_axis="project",
            allowed=True,
            target_id=f"project:{project}",
        ))
    else:
        actions.append(FoldScaleAction(
            label="Roll up to project",
            target_scale="cluster",
            target_axis="project",
            allowed=False,
            reason="This node has no project value to roll up to.",
        ))

    # --- plane axis (working when a plane card or canonical_layer resolves) ---
    plane_card = facets.get("plane_card", {})
    plane = None
    if plane_card.get("present"):
        plane = plane_card.get("plane")
    if not plane:
        plane = facets.get("authority", {}).get("canonical_layer")
    if plane:
        actions.append(FoldScaleAction(
            label="Roll up to plane",
            target_scale="cluster",
            target_axis="plane",
            allowed=True,
            target_id=f"plane:{plane}",
        ))
    else:
        actions.append(FoldScaleAction(
            label="Roll up to plane",
            target_scale="cluster",
            target_axis="plane",
            allowed=False,
            reason="No plane is resolvable for this node at node scale.",
        ))

    # --- domain axis (read-only linkage from registered domains + doc/card topics) ---
    doc_id = base_packet.get("doc_id")
    domains: tuple[str, ...] = ()
    if doc_id:
        try:
            from app.core.domain_linkage import domains_for_doc
            domains = domains_for_doc(str(doc_id))
        except Exception:
            domains = ()
    if len(domains) == 1:
        actions.append(FoldScaleAction(
            label="Roll up to domain",
            target_scale="cluster",
            target_axis="domain",
            allowed=True,
            target_id=f"domain:{domains[0]}",
        ))
    elif len(domains) > 1:
        actions.append(FoldScaleAction(
            label="Roll up to domain",
            target_scale="cluster",
            target_axis="domain",
            allowed=False,
            reason=f"Multiple registered domains are linked to this node: {', '.join(domains)}.",
        ))
    else:
        actions.append(FoldScaleAction(
            label="Roll up to domain",
            target_scale="cluster",
            target_axis="domain",
            allowed=False,
            reason="No registered domain token is linked to this node.",
        ))

    return actions


def _build_why_current(base_packet: dict[str, Any], packet: "CurrentFoldPacket") -> list:
    """Build a list of WhyCurrentRow explaining the currentness determination.

    Reads only the already-assembled base_packet and packet — no DB access.
    Each row carries a direction (pos/weak/neutral), a factor label, and evidence
    text. The evidence text is provenance-prefixed so the reader can tell how the
    factor was derived — this disclosure must be preserved even when wording improves:

      direct:   read straight from a stored packet field (e.g. a valid_until date,
                a conflict count, an authority_state string)
      computed: derived deterministically from a scalar pressure formula
      inferred: synthesized from a symbolic label or several signals, no single field
      unknown:  the underlying source field is missing/unresolvable
    """
    rows: list[WhyCurrentRow] = []
    ss = packet.scalar_state or {}

    # scalar_state may be a FoldScalarState dataclass or dict; handle both
    def _ss(key: str, default: float = 0.0) -> float:
        try:
            if hasattr(ss, key):
                return float(getattr(ss, key) or default)
            return float(ss.get(key, default) or default)  # type: ignore[attr-defined]
        except Exception:
            return default

    # Which inputs the resolver flagged as unknown (FoldUnknown objects, by field).
    unknown_fields = set()
    for u in (packet.unknowns or []):
        f = getattr(u, "field", None)
        if f is None and isinstance(u, dict):
            f = u.get("field")
        if f:
            unknown_fields.add(f)

    freshP = _ss("freshness_score")
    authP  = _ss("authority_score")
    canon  = _ss("canon_readiness")

    facets = base_packet.get("facets", {}) if isinstance(base_packet, dict) else {}

    # --- Freshness row ---
    plane_card = facets.get("plane_card", {}) if isinstance(facets, dict) else {}
    valid_until = plane_card.get("valid_until") or ""
    if "freshness_age_days" in unknown_fields and not valid_until:
        rows.append(WhyCurrentRow(
            "weak", "Source freshness",
            "unknown: no freshness timestamp (epistemic_last_evaluated / updated_ts absent)",
        ))
    elif valid_until:
        # A real stored expiry date is direct evidence.
        rows.append(WhyCurrentRow(
            "pos" if freshP >= 0.6 else "weak", "Source freshness",
            f"direct: valid until {valid_until}",
        ))
    else:
        # No stored date; freshness is the decay-computed pressure.
        rows.append(WhyCurrentRow(
            "pos" if freshP >= 0.6 else "weak", "Source freshness",
            f"computed: freshness pressure {freshP:.2f} (timestamp decay)",
        ))

    # --- Authority row ---
    auth_facet = facets.get("authority", {}) if isinstance(facets, dict) else {}
    auth_state = str(auth_facet.get("authority_state") or "").lower()
    has_cert = "cert" in auth_state or "verif" in auth_state

    tier = 0
    try:
        raw_auth = float(authP)
        if raw_auth >= 0.75:
            tier = 3
        elif raw_auth >= 0.5:
            tier = 2
        elif raw_auth >= 0.25:
            tier = 1
    except Exception:
        pass

    if "authority_state" in unknown_fields or not auth_state:
        rows.append(WhyCurrentRow(
            "weak", "Authority",
            "unknown: no authority_state on this node",
        ))
    elif has_cert:
        rows.append(WhyCurrentRow(
            "pos", "Authority",
            f"direct: certificate present ({auth_state}) · computed tier {tier}",
        ))
    elif tier >= 2:
        rows.append(WhyCurrentRow(
            "pos", "Authority",
            f"direct: {auth_state} · computed tier {tier} · no certificate",
        ))
    elif tier > 0:
        rows.append(WhyCurrentRow(
            "weak", "Authority",
            f"direct: {auth_state} · computed tier {tier} · no certificate",
        ))
    else:
        rows.append(WhyCurrentRow(
            "weak", "Authority",
            f"direct: {auth_state} · computed tier 0",
        ))

    # --- Conflict row (real count from the conflicts facet, not the symbolic label) ---
    conflict_facet = facets.get("conflicts", {}) if isinstance(facets, dict) else {}
    try:
        conflict_count = int(conflict_facet.get("count", 0) or 0)
    except Exception:
        conflict_count = 0
    has_items = bool(conflict_facet.get("items"))
    if conflict_count > 0 or has_items:
        n = conflict_count or (len(conflict_facet.get("items") or []) if has_items else 1)
        rows.append(WhyCurrentRow(
            "weak", "Open conflicts",
            f"direct: {n} open conflict{'s' if n != 1 else ''}",
        ))
    else:
        rows.append(WhyCurrentRow("pos", "Open conflicts", "direct: none"))

    # --- Canon readiness (only surface when noteworthy; always a computed composite) ---
    if canon < 0.3:
        rows.append(WhyCurrentRow("weak", "Canon readiness", f"computed: low ({canon:.2f})"))
    elif canon >= 0.7:
        rows.append(WhyCurrentRow("pos", "Canon readiness", f"computed: high ({canon:.2f})"))

    return rows


def adapt_folded_node_to_current_fold(
    base_packet: dict[str, Any],
    scalar_state: FoldScalarState,
    symbolic_state: FoldSymbolicState,
    metric_context_missing: list[str] | None = None,
    lineage_depth_capped: bool = False,
    canon_variables: CANONVariables | None = None,
) -> CurrentFoldPacket:
    """Assemble a CurrentFoldPacket from pre-computed resolver layers.

    Does not access the database.
    Does not invent state not provided in inputs.
    Missing inputs become FoldUnknowns.
    canon_variables is optional; when supplied it is attached to the packet.
    """
    doc_id = base_packet.get("doc_id", "")
    missing = metric_context_missing or []

    local_state = _extract_local_state(base_packet)
    unknowns = _collect_unknowns(base_packet, scalar_state, missing, lineage_depth_capped)
    compact_trace = _build_compact_trace(base_packet, scalar_state, symbolic_state, unknowns)
    scale_actions = _build_node_scale_actions(base_packet)

    projection_hints = {
        "recommended_default_surface": "current_fold_view",
        "recommended_graph_scope": "local_neighborhood",
        "global_graph_allowed": True,
        "global_graph_is_advanced": True,
        "layout_is_truth": False,
    }

    trace_ref = FoldResolverTraceRef(
        available=True,
        endpoint=f"/api/fold/node/{doc_id}/trace",
        trace_id=None,
    )

    packet = CurrentFoldPacket(
        schema_version=_SCHEMA_VERSION,
        resolver_version=_RESOLVER_VERSION,
        projection_version=_PROJECTION_VERSION,
        visual_contract_version=_VISUAL_CONTRACT_VERSION,
        scope=FoldScope(scale="node", scope_id=doc_id),
        local_state=local_state,
        scalar_state=scalar_state,
        symbolic_state=symbolic_state,
        projection_hints=projection_hints,
        unknowns=unknowns,
        resolver_trace_summary=compact_trace,
        resolver_trace_ref=trace_ref,
        cache_status="live",
        scale_actions=scale_actions,
        canon_variables=canon_variables,
    )

    try:
        packet.why_current = _build_why_current(base_packet, packet)
    except Exception:
        packet.why_current = []

    return packet


# ---------------------------------------------------------------------------
# Canonical four-step resolver -- Step 8
# ---------------------------------------------------------------------------

def current_fold_from_folded_node(doc_id: str) -> CurrentFoldPacket | None:
    """Canonical four-step CurrentFoldPacket resolver.

    Step 1: build_folded_node_packet   -- structural and document facts
    Step 2: FoldMetricContextLoader    -- DB lookups for scalar inputs
    Step 3: compute_fold_scalar_state  -- dimensional pressures [0.0, 1.0]
    Step 4: project_symbolic_state     -- human-readable labels from scalar + policy

    Returns None if the document does not exist.
    Returns a degraded packet (with unknowns) if inputs are partially missing.
    Never raises on partial data; prefer visible incompleteness over silent failure.
    """
    base_packet = build_folded_node_packet(doc_id)
    if not base_packet:
        return None

    metric_context = FoldMetricContextLoader().load(doc_id)

    scalar_state = compute_fold_scalar_state(
        base_packet,
        metric_context,
    )

    symbolic_state = project_symbolic_state(
        scalar_state,
        base_packet,
        policy=None,    # resolves to DefaultFoldSymbolicPolicy.v0_1
    )

    # Canon geometry (omega_viability, mismatch_gradient) needs DCNS diagnostics —
    # one extra DB call. Reuses the already-loaded doc row for graph-identical
    # completeness/authority derivation. Degrades to None on any failure.
    geometry = None
    try:
        from app.core.dcns import get_node_diagnostics
        from app.core.fold_metrics import compute_canon_geometry
        diag = get_node_diagnostics(doc_id)
        geometry = compute_canon_geometry(metric_context.doc_row, diag)
    except Exception:
        geometry = None

    try:
        canon_vars = compute_canon_variables(scalar_state, metric_context, geometry=geometry)
    except Exception:
        canon_vars = None

    return adapt_folded_node_to_current_fold(
        base_packet=base_packet,
        scalar_state=scalar_state,
        symbolic_state=symbolic_state,
        metric_context_missing=metric_context.missing_fields,
        lineage_depth_capped=metric_context.lineage_depth_capped,
        canon_variables=canon_vars,
    )
