"""tests/test_fold_aggregation.py -- Acceptance tests for Phase 7a cluster aggregation.

Each test maps 1:1 to a frozen case in
``docs/specs/fold_phase7a_aggregation_acceptance_spec.md`` (status: accepted).
The case->test-name mapping table in that spec is authoritative for these names.

These are pure-unit tests over the aggregation helpers: members are constructed
node ``CurrentFoldPacket`` objects (no DB needed), mirroring the spec's note that
the engine composes already-resolved node packets.
"""

from __future__ import annotations

import pytest

from app.core.current_fold import (
    CurrentFoldPacket,
    FoldResolverTraceRef,
    FoldScope,
)
from app.core.fold_metrics import FoldScalarState, FoldSymbolicState
from app.core.fold_aggregation import (
    AGGREGATE_TRACE_EVENTS,
    EXCLUSION_REASONS,
    aggregate_cluster,
    aggregate_corpus,
    cluster_scope_id,
    corpus_scope_id,
    FoldMemberInput,
)


# ---------------------------------------------------------------------------
# Builders -- construct node packets without touching the DB
# ---------------------------------------------------------------------------

def _scalar(authority_score: float = 0.5, **overrides) -> FoldScalarState:
    base = {
        "authority_score": authority_score,
        "freshness_score": 0.5,
        "evidence_strength": 0.5,
        "conflict_pressure": 0.0,
        "interpretability": 0.5,
        "queryability": 0.5,
        "canon_readiness": 0.5,
        "drift_risk": 0.5,
        "resolution_confidence": 0.5,
        "blast_radius": 0.5,
    }
    base.update(overrides)
    return FoldScalarState(**base)


def _node(
    scope_id: str,
    currentness_label: str = "current",
    *,
    authority_score: float = 0.5,
    intake_label: str = "interpretable_queryable",
    **pressures,
) -> CurrentFoldPacket:
    scalar = _scalar(authority_score=authority_score, **pressures)
    symbolic = FoldSymbolicState(
        currentness_label=currentness_label,
        authority_label="reviewed",
        freshness_label="valid",
        conflict_label="none",
        intake_label=intake_label,
    )
    return CurrentFoldPacket(
        schema_version="CurrentFoldPacket.v0.3",
        resolver_version="CurrentFoldResolver.v0.1",
        projection_version="DefaultFoldSymbolicPolicy.v0_1",
        visual_contract_version="FoldView.v0.1",
        scope=FoldScope(scale="node", scope_id=scope_id),
        local_state={"doc_id": scope_id},
        scalar_state=scalar,
        symbolic_state=symbolic,
        projection_hints={},
        unknowns=[],
        resolver_trace_summary=[],
        resolver_trace_ref=FoldResolverTraceRef(available=True),
    )


def _member(scope_id, value="boh", **kw) -> FoldMemberInput:
    return FoldMemberInput(node_packet=_node(scope_id, **kw), axis_value=value)


# ---------------------------------------------------------------------------
# Section 1 -- Cluster identity
# ---------------------------------------------------------------------------

class TestClusterIdentity:
    def test_cluster_scope_id_form(self):
        pkt = aggregate_cluster("project", "boh", [_member("A")])
        assert pkt.scope.scale == "cluster"
        assert pkt.scope.scope_id == "project:boh"
        assert pkt.scope.axis == "project"
        assert pkt.scope.axis_value == "boh"
        assert cluster_scope_id("project", "boh") == "project:boh"

    def test_corpus_scope_id_form(self):
        pkt = aggregate_corpus("project", [])
        assert pkt.scope.scale == "corpus"
        assert pkt.scope.scope_id == "corpus:project"
        assert corpus_scope_id("project") == "corpus:project"

    def test_membership_is_live_axis_equality(self):
        members = [
            _member("A", value="boh"),
            _member("B", value="boh"),
            _member("C", value="canon"),
        ]
        pkt = aggregate_cluster("project", "boh", members)
        ids = {c.scope_id for c in pkt.contributors}
        assert ids == {"A", "B"}
        assert "C" not in ids
        assert pkt.aggregation["inputs_count"] == 2

    def test_null_axis_registers_membership_unknown(self):
        members = [
            _member("A", value="boh"),
            FoldMemberInput(node_packet=_node("D"), axis_value=None),
        ]
        pkt = aggregate_cluster("project", "boh", members)
        # D is not a member and not counted.
        assert pkt.aggregation["inputs_count"] == 1
        assert {c.scope_id for c in pkt.contributors} == {"A"}
        fields = [u.field for u in pkt.unknowns]
        assert "cluster_membership_ambiguous" in fields

    def test_batch_axis_flagged_diagnostic_only(self):
        pkt = aggregate_cluster("batch", "batch-001", [_member("A", value="batch-001")])
        assert pkt.aggregation["diagnostic_only"] is True
        # Non-batch axes are not diagnostic.
        other = aggregate_cluster("project", "boh", [_member("A")])
        assert other.aggregation["diagnostic_only"] is False


# ---------------------------------------------------------------------------
# Section 2 -- Label precedence
# ---------------------------------------------------------------------------

class TestLabelPrecedence:
    def test_single_quarantined_drives_cluster(self):
        members = [
            _member("A", currentness_label="current"),
            _member("B", currentness_label="current"),
            _member("Q", currentness_label="quarantined"),
        ]
        pkt = aggregate_cluster("project", "boh", members)
        assert pkt.symbolic_state["currentness_label"] == "quarantined"

    def test_quarantined_beats_conflicted(self):
        pkt = aggregate_cluster("project", "boh", [
            _member("C", currentness_label="conflicted"),
            _member("Q", currentness_label="quarantined"),
        ])
        assert pkt.symbolic_state["currentness_label"] == "quarantined"

        pkt2 = aggregate_cluster("project", "boh", [
            _member("C", currentness_label="conflicted"),
            _member("X", currentness_label="current"),
        ])
        assert pkt2.symbolic_state["currentness_label"] == "conflicted"

    def test_total_order_pairwise(self):
        order = [
            "quarantined", "held", "superseded", "conflicted", "stale",
            "unknown", "current_but_contested", "draft_current", "current",
        ]
        # Each adjacent pair: the worse (earlier) label must win.
        for worse, better in zip(order, order[1:]):
            pkt = aggregate_cluster("project", "boh", [
                _member("worse", currentness_label=worse),
                _member("better", currentness_label=better),
            ])
            assert pkt.symbolic_state["currentness_label"] == worse, (worse, better)

    def test_all_current_is_current(self):
        pkt = aggregate_cluster("project", "boh", [
            _member("A", currentness_label="current"),
            _member("B", currentness_label="current"),
        ])
        assert pkt.symbolic_state["currentness_label"] == "current"

    def test_label_driver_identifies_member(self):
        pkt = aggregate_cluster("project", "boh", [
            _member("doc_A", currentness_label="current"),
            _member("doc_Q", currentness_label="quarantined"),
        ])
        assert pkt.aggregation["label_driver"] == {
            "scope_id": "doc_Q",
            "label": "quarantined",
        }

    def test_label_driver_tie_break_lexicographic(self):
        # Two members share the worst label -> lowest scope_id wins (Q6).
        pkt = aggregate_cluster("project", "boh", [
            _member("z_doc", currentness_label="quarantined"),
            _member("a_doc", currentness_label="quarantined"),
        ])
        assert pkt.aggregation["label_driver"]["scope_id"] == "a_doc"


# ---------------------------------------------------------------------------
# Section 3 -- Authority weighting
# ---------------------------------------------------------------------------

class TestAuthorityWeighting:
    def _worked_members(self):
        return [
            _member("M1", authority_score=0.80, freshness_score=0.90, conflict_pressure=0.10),
            _member("M2", authority_score=0.40, freshness_score=0.60, conflict_pressure=0.50),
            _member("M3", authority_score=0.20, freshness_score=0.30, conflict_pressure=0.40),
        ]

    def test_weighted_mean_exact(self):
        pkt = aggregate_cluster("project", "boh", self._worked_members())
        s = pkt.scalar_state
        assert s["freshness_score"] == pytest.approx(0.729, abs=1e-3)
        assert s["conflict_pressure"] == pytest.approx(0.257, abs=1e-3)
        assert s["authority_score"] == pytest.approx(0.600, abs=1e-3)
        assert pkt.aggregation["numeric_fallback_used"] is False

    def test_weight_is_member_authority_score(self):
        pkt = aggregate_cluster("project", "boh", self._worked_members())
        by_id = {c.scope_id: c for c in pkt.contributors}
        assert by_id["M1"].authority_score == 0.80
        assert by_id["M2"].authority_score == 0.40
        assert by_id["M3"].authority_score == 0.20
        # Normalized share (Q8): 0.80 / 1.40.
        assert by_id["M1"].weight == pytest.approx(0.80 / 1.40, abs=1e-3)

    def test_each_pressure_weighted_independently(self):
        pkt = aggregate_cluster("project", "boh", self._worked_members())
        # freshness and conflict differ -> independent rollups, no leakage.
        assert pkt.scalar_state["freshness_score"] != pkt.scalar_state["conflict_pressure"]

    def test_result_clamped_and_not_truth(self):
        pkt = aggregate_cluster("project", "boh", self._worked_members())
        for p in (
            "authority_score", "freshness_score", "evidence_strength",
            "conflict_pressure", "interpretability", "queryability",
            "canon_readiness", "drift_risk", "resolution_confidence", "blast_radius",
        ):
            assert 0.0 <= pkt.scalar_state[p] <= 1.0
        assert pkt.scalar_state["scores_are_truth_values"] is False


# ---------------------------------------------------------------------------
# Section 4 -- Equal-weight fallback
# ---------------------------------------------------------------------------

class TestEqualWeightFallback:
    def test_zero_weight_sum_falls_back(self):
        pkt = aggregate_cluster("project", "boh", [
            _member("A", authority_score=0.0, freshness_score=0.40),
            _member("B", authority_score=0.0, freshness_score=0.80),
        ])
        assert pkt.scalar_state["freshness_score"] == pytest.approx(0.600, abs=1e-3)
        assert pkt.aggregation["numeric_fallback_used"] is True

    def test_all_missing_weights_fall_back(self):
        a = _node("A", authority_score=0.0, freshness_score=0.20)
        b = _node("B", authority_score=0.0, freshness_score=0.60)
        # Simulate truly-absent weights by nulling authority_score post-build.
        a.scalar_state.authority_score = None  # type: ignore[assignment]
        b.scalar_state.authority_score = None  # type: ignore[assignment]
        pkt = aggregate_cluster("project", "boh", [
            FoldMemberInput(a, "boh"),
            FoldMemberInput(b, "boh"),
        ])
        assert pkt.scalar_state["freshness_score"] == pytest.approx(0.400, abs=1e-3)
        assert pkt.aggregation["numeric_fallback_used"] is True

    def test_fallback_flag_and_label_unaffected(self):
        pkt = aggregate_cluster("project", "boh", [
            _member("Q", currentness_label="quarantined", authority_score=0.0),
            _member("C", currentness_label="current", authority_score=0.0),
        ])
        assert pkt.aggregation["numeric_fallback_used"] is True
        assert pkt.symbolic_state["currentness_label"] == "quarantined"

    def test_partial_missing_weights_policy(self):
        # Q3: some valid weights -> no fallback; missing-weight member contributes
        # 0 to the numerator but still counts as included and feeds the label.
        b = _node("B", authority_score=0.0, freshness_score=0.10)
        b.scalar_state.authority_score = None  # type: ignore[assignment]
        pkt = aggregate_cluster("project", "boh", [
            _member("A", authority_score=1.0, freshness_score=0.90),
            FoldMemberInput(b, "boh"),
        ])
        assert pkt.aggregation["numeric_fallback_used"] is False
        assert pkt.aggregation["included_count"] == 2
        # Only A has weight -> mean equals A's freshness.
        assert pkt.scalar_state["freshness_score"] == pytest.approx(0.900, abs=1e-3)


# ---------------------------------------------------------------------------
# Section 5 -- Excluded numeric behavior
# ---------------------------------------------------------------------------

class TestExcludedNumeric:
    def test_excluded_member_not_in_numeric_mean(self):
        pkt = aggregate_cluster("project", "boh", [
            _member("M1", authority_score=0.80, freshness_score=0.90),
            _member("MQ", currentness_label="quarantined", authority_score=0.50, freshness_score=0.10),
        ])
        assert pkt.scalar_state["freshness_score"] == pytest.approx(0.900, abs=1e-3)
        assert pkt.aggregation["included_count"] == 1
        assert pkt.aggregation["excluded_count"] == 1

    def test_excluded_member_still_drives_label(self):
        pkt = aggregate_cluster("project", "boh", [
            _member("M1", authority_score=0.80, freshness_score=0.90),
            _member("MQ", currentness_label="quarantined", authority_score=0.50, freshness_score=0.10),
        ])
        assert pkt.symbolic_state["currentness_label"] == "quarantined"
        assert pkt.aggregation["label_driver"]["scope_id"] == "MQ"

    def test_counts_invariant(self):
        members = [
            _member("a"), _member("b"),
            _member("q", currentness_label="quarantined"),
            _member("h", currentness_label="held"),
        ]
        pkt = aggregate_cluster("project", "boh", members)
        agg = pkt.aggregation
        assert agg["inputs_count"] == 4
        assert agg["excluded_count"] == 2
        assert agg["included_count"] == 2
        assert agg["inputs_count"] == agg["included_count"] + agg["excluded_count"]

    def test_excluded_reason_enum(self):
        members = [
            _member("q", currentness_label="quarantined"),
            _member("h", currentness_label="held"),
            _member("s", currentness_label="superseded"),
            _member("p", intake_label="preserved_not_interpreted"),
        ]
        pkt = aggregate_cluster("project", "boh", members)
        reasons = {c.excluded_reason for c in pkt.contributors if not c.included}
        assert reasons <= set(EXCLUSION_REASONS)
        assert reasons == {"quarantined", "held", "superseded", "preserved_only"}
        # No silent drops: every excluded contributor carries a reason.
        for c in pkt.contributors:
            if not c.included:
                assert c.excluded_reason is not None

    def test_all_excluded_numeric_policy(self):
        pkt = aggregate_cluster("project", "boh", [
            _member("q1", currentness_label="quarantined"),
            _member("q2", currentness_label="held"),
        ])
        assert pkt.scalar_state["freshness_score"] is None
        assert pkt.scalar_state["authority_score"] is None
        assert pkt.aggregation["numeric_fallback_used"] is False
        assert "numeric_channel_no_included_members" in [u.field for u in pkt.unknowns]
        # Label channel still computed over excluded members.
        assert pkt.symbolic_state["currentness_label"] == "quarantined"
        assert pkt.aggregation["label_driver"] is not None


# ---------------------------------------------------------------------------
# Section 6 -- Unknown scope
# ---------------------------------------------------------------------------

class TestUnknownScope:
    def test_missing_axis_value_unknown(self):
        pkt = aggregate_cluster("project", "boh", [
            _member("A", value="boh"),
            FoldMemberInput(_node("D"), axis_value=None),
        ])
        assert "cluster_membership_ambiguous" in [u.field for u in pkt.unknowns]
        assert pkt.aggregation["inputs_count"] == 1

    def test_unknowns_always_present(self):
        pkt = aggregate_cluster("project", "boh", [_member("A"), _member("B")])
        assert isinstance(pkt.unknowns, list)  # present even when empty/clean
        assert isinstance(pkt.as_dict()["unknowns"], list)

    def test_canon_eligible_never_true(self):
        cluster = aggregate_cluster("project", "boh", [_member("A")])
        corpus = aggregate_corpus("project", [cluster])
        assert cluster.canon_eligible is not True
        assert corpus.canon_eligible is not True
        assert cluster.as_dict()["canon_eligible"] is False


# ---------------------------------------------------------------------------
# Section 7 -- Empty cluster
# ---------------------------------------------------------------------------

class TestEmptyCluster:
    def test_zero_members_packet_shape(self):
        pkt = aggregate_cluster("project", "does_not_exist", [])
        assert pkt.aggregation["inputs_count"] == 0
        assert pkt.symbolic_state["currentness_label"] == "unknown"
        assert pkt.scalar_state["freshness_score"] is None
        assert pkt.scalar_state["authority_score"] is None
        assert pkt.aggregation["numeric_fallback_used"] is False
        assert pkt.aggregation["label_driver"] is None
        assert pkt.contributors == []
        assert "empty_cluster" in [u.field for u in pkt.unknowns]

    def test_zero_members_counts_invariant(self):
        pkt = aggregate_cluster("project", "does_not_exist", [])
        agg = pkt.aggregation
        assert agg["inputs_count"] == agg["included_count"] + agg["excluded_count"]
        assert agg["inputs_count"] == 0


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------

class TestAggregateInvariants:
    def test_compact_trace_six_events(self):
        for pkt in (
            aggregate_cluster("project", "boh", [_member("A"), _member("B")]),
            aggregate_cluster("project", "empty", []),
            aggregate_cluster("project", "boh", [_member("q", currentness_label="quarantined")]),
        ):
            events = [e.event for e in pkt.resolver_trace_summary]
            assert events == list(AGGREGATE_TRACE_EVENTS)
            assert len(events) == 6

    def test_aggregation_method_constants(self):
        pkt = aggregate_cluster("project", "boh", [_member("A")])
        agg = pkt.aggregation
        assert agg["method"] == "dual_channel_v1"
        assert agg["label_channel"] == "worst_case_precedence"
        assert agg["numeric_channel"] == "authority_weighted_mean"
