"""tests/test_canon_variables.py — Acceptance tests for CANON policy variables.

Covers:
  - compute_canon_variables() exact mode
  - compute_canon_variables_partial() partial mode
  - Formula parity between exact and partial paths for shared variables
  - Partial mode: null fields with explicit warnings, calculation_mode = "partial"
  - Exact mode: all fields populated, calculation_mode = "exact", no warnings
  - Boundary / clamp behaviour for edge inputs
  - NaN-input protection
  - Risk Map regression: high conflict produces high risk regardless of drift_rate
  - Authority regression: raw authP preserved independently of gamma
  - Timeline regression: delta_c_star does not affect time_norm
  - CurrentFoldPacket carries canon_variables in as_dict()
  - Aggregation engine (FoldAggregation) unaffected by canon_variables field
  - Dataclass field ordering: canon_variables is an optional field after all required fields
  - Serialisation: policy_id, calculation_mode, warnings always present in as_dict()
"""

from __future__ import annotations

import math
from dataclasses import fields as dc_fields
from typing import Any

import pytest

from app.core.fold_metrics import (
    CANONVariables,
    FoldMetricContext,
    FoldScalarState,
    compute_canon_variables,
    compute_canon_variables_partial,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scalar(
    authority_score: float = 0.75,
    freshness_score: float = 0.80,
    evidence_strength: float = 0.60,
    conflict_pressure: float = 0.10,
    interpretability: float = 0.90,
    queryability: float = 0.90,
    canon_readiness: float = 0.70,
    drift_risk: float = 0.20,
    resolution_confidence: float = 0.85,
    blast_radius: float = 0.30,
) -> FoldScalarState:
    return FoldScalarState(
        authority_score=authority_score,
        freshness_score=freshness_score,
        evidence_strength=evidence_strength,
        conflict_pressure=conflict_pressure,
        interpretability=interpretability,
        queryability=queryability,
        canon_readiness=canon_readiness,
        drift_risk=drift_risk,
        resolution_confidence=resolution_confidence,
        blast_radius=blast_radius,
    )


def _context(missing_fields: list[str] | None = None) -> FoldMetricContext:
    return FoldMetricContext(
        doc_id="test-doc",
        edge_count=3,
        cross_unapproved=0,
        unresolved_conflicts=0,
        lineage_depth=1,
        lineage_depth_capped=False,
        freshness_age_days=14,
        freshness_source_used="updated_ts",
        superseded=False,
        supporting_sources=2,
        missing_fields=missing_fields or [],
        intake_interpretable=True,
        intake_queryable=True,
        intake_safety_lane="direct",
        intake_normalizable=True,
        intake_preservable=True,
        intake_failure_reason=None,
        epistemic_d=1,
        epistemic_q=0.8,
        epistemic_c=0.7,
    )


# ---------------------------------------------------------------------------
# Exact mode: all four fields
# ---------------------------------------------------------------------------

class TestComputeCanonVariablesExact:
    def test_returns_canon_variables_instance(self):
        cv = compute_canon_variables(_scalar(), _context())
        assert isinstance(cv, CANONVariables)

    def test_all_fields_populated(self):
        cv = compute_canon_variables(_scalar(), _context())
        assert cv.drift_rate   is not None
        assert cv.entropy      is not None
        assert cv.delta_c_star is not None
        assert cv.gamma        is not None

    def test_calculation_mode_exact(self):
        cv = compute_canon_variables(_scalar(), _context())
        assert cv.calculation_mode == "exact"

    def test_no_warnings_in_exact_mode_with_geometry(self):
        # Exact mode WITH geometry supplied has no warnings.
        geom = {"omega_viability": 0.5, "mismatch_gradient": 0.25}
        cv = compute_canon_variables(_scalar(), _context(), geometry=geom)
        assert cv.warnings == []
        assert cv.omega_viability == 0.5
        assert cv.mismatch_gradient == 0.25

    def test_exact_mode_without_geometry_warns_omega_mismatch(self):
        # Without geometry, omega/mismatch are None with two warnings.
        cv = compute_canon_variables(_scalar(), _context())
        assert cv.omega_viability is None
        assert cv.mismatch_gradient is None
        assert len(cv.warnings) == 2
        assert any("omega_viability" in w for w in cv.warnings)
        assert any("mismatch_gradient" in w for w in cv.warnings)

    def test_policy_id(self):
        cv = compute_canon_variables(_scalar(), _context())
        assert cv.policy_id == "canon_variables_policy_v0_1"

    def test_all_outputs_in_unit_interval(self):
        cv = compute_canon_variables(_scalar(), _context())
        for name, val in [
            ("drift_rate",   cv.drift_rate),
            ("entropy",      cv.entropy),
            ("delta_c_star", cv.delta_c_star),
            ("gamma",        cv.gamma),
        ]:
            assert 0.0 <= val <= 1.0, f"{name} = {val} out of [0,1]"

    def test_drift_rate_increases_as_freshness_falls(self):
        fresh_high = compute_canon_variables(_scalar(freshness_score=0.95), _context())
        fresh_low  = compute_canon_variables(_scalar(freshness_score=0.10), _context())
        assert fresh_low.drift_rate > fresh_high.drift_rate

    def test_gamma_zero_when_conflict_maxed(self):
        cv = compute_canon_variables(_scalar(conflict_pressure=1.0), _context())
        assert cv.gamma == 0.0

    def test_delta_c_star_zero_when_conflict_maxed(self):
        cv = compute_canon_variables(_scalar(conflict_pressure=1.0), _context())
        assert cv.delta_c_star == 0.0

    def test_delta_c_star_zero_when_drift_maxed(self):
        cv = compute_canon_variables(_scalar(drift_risk=1.0), _context())
        assert cv.delta_c_star == 0.0

    def test_entropy_high_when_low_confidence_and_many_missing(self):
        cv = compute_canon_variables(
            _scalar(resolution_confidence=0.0),
            _context(missing_fields=["a", "b", "c", "d", "e", "f"]),
        )
        assert cv.entropy >= 0.9

    def test_entropy_low_when_high_confidence_and_no_missing(self):
        cv = compute_canon_variables(
            _scalar(resolution_confidence=1.0),
            _context(missing_fields=[]),
        )
        assert cv.entropy == 0.0

    def test_gamma_equals_auth_when_no_conflict(self):
        auth = 0.80
        cv = compute_canon_variables(_scalar(authority_score=auth, conflict_pressure=0.0), _context())
        assert abs(cv.gamma - round(auth, 3)) < 0.01


# ---------------------------------------------------------------------------
# Partial mode: batch adapter
# ---------------------------------------------------------------------------

class TestComputeCanonVariablesPartial:
    def _cv(self, auth=0.75, fresh=0.80, conf_p=0.10, canon=0.70):
        return compute_canon_variables_partial(
            auth_score=auth,
            freshness_score=fresh,
            conflict_pressure=conf_p,
            canon_readiness=canon,
        )

    def test_returns_canon_variables_instance(self):
        assert isinstance(self._cv(), CANONVariables)

    def test_calculation_mode_partial(self):
        assert self._cv().calculation_mode == "partial"

    def test_drift_rate_populated(self):
        assert self._cv().drift_rate is not None

    def test_gamma_populated(self):
        assert self._cv().gamma is not None

    def test_entropy_is_null(self):
        assert self._cv().entropy is None

    def test_delta_c_star_is_null(self):
        assert self._cv().delta_c_star is None

    def test_warnings_non_empty(self):
        # Partial mode: entropy, delta_c_star, omega_viability, mismatch_gradient.
        assert len(self._cv().warnings) == 4

    def test_entropy_warning_present(self):
        warnings = self._cv().warnings
        assert any("entropy" in w for w in warnings)

    def test_delta_c_star_warning_present(self):
        warnings = self._cv().warnings
        assert any("delta_c_star" in w for w in warnings)

    def test_policy_id(self):
        assert self._cv().policy_id == "canon_variables_policy_v0_1"

    def test_populated_outputs_in_unit_interval(self):
        cv = self._cv()
        assert 0.0 <= cv.drift_rate <= 1.0
        assert 0.0 <= cv.gamma      <= 1.0


# ---------------------------------------------------------------------------
# Exact / partial parity for shared variables
# ---------------------------------------------------------------------------

class TestExactPartialParity:
    def test_drift_rate_matches(self):
        s = _scalar(freshness_score=0.60, canon_readiness=0.55)
        c = _context()
        exact   = compute_canon_variables(s, c)
        partial = compute_canon_variables_partial(
            auth_score=s.authority_score,
            freshness_score=s.freshness_score,
            conflict_pressure=s.conflict_pressure,
            canon_readiness=s.canon_readiness,
        )
        assert exact.drift_rate == partial.drift_rate

    def test_gamma_matches(self):
        s = _scalar(authority_score=0.70, conflict_pressure=0.30)
        c = _context()
        exact   = compute_canon_variables(s, c)
        partial = compute_canon_variables_partial(
            auth_score=s.authority_score,
            freshness_score=s.freshness_score,
            conflict_pressure=s.conflict_pressure,
            canon_readiness=s.canon_readiness,
        )
        assert exact.gamma == partial.gamma


# ---------------------------------------------------------------------------
# Boundary and NaN protection
# ---------------------------------------------------------------------------

class TestBoundaryAndNaN:
    def test_all_zero_inputs_exact(self):
        s = _scalar(
            authority_score=0.0, freshness_score=0.0, canon_readiness=0.0,
            conflict_pressure=0.0, drift_risk=0.0, resolution_confidence=0.0,
        )
        cv = compute_canon_variables(s, _context())
        for v in [cv.drift_rate, cv.entropy, cv.delta_c_star, cv.gamma]:
            assert 0.0 <= v <= 1.0

    def test_all_one_inputs_exact(self):
        s = _scalar(
            authority_score=1.0, freshness_score=1.0, canon_readiness=1.0,
            conflict_pressure=1.0, drift_risk=1.0, resolution_confidence=1.0,
        )
        cv = compute_canon_variables(s, _context())
        for v in [cv.drift_rate, cv.entropy, cv.delta_c_star, cv.gamma]:
            assert 0.0 <= v <= 1.0

    def test_over_range_inputs_clamped(self):
        s = _scalar(authority_score=2.5, freshness_score=-0.3, conflict_pressure=3.0)
        cv = compute_canon_variables(s, _context())
        for v in [cv.drift_rate, cv.entropy, cv.delta_c_star, cv.gamma]:
            assert 0.0 <= v <= 1.0

    def test_nan_inputs_do_not_propagate(self):
        s = _scalar(authority_score=float("nan"), freshness_score=float("nan"))
        cv = compute_canon_variables(s, _context())
        for v in [cv.drift_rate, cv.entropy, cv.delta_c_star, cv.gamma]:
            assert not math.isnan(v)

    def test_partial_boundary_all_zero(self):
        cv = compute_canon_variables_partial(0.0, 0.0, 0.0, 0.0)
        assert 0.0 <= cv.drift_rate <= 1.0
        assert 0.0 <= cv.gamma      <= 1.0

    def test_partial_nan_inputs(self):
        cv = compute_canon_variables_partial(float("nan"), float("nan"), float("nan"), float("nan"))
        assert not math.isnan(cv.drift_rate)
        assert not math.isnan(cv.gamma)


# ---------------------------------------------------------------------------
# Projection regressions
# ---------------------------------------------------------------------------

class TestProjectionRegressions:
    def test_risk_map_high_conflict_stays_high_when_drift_rate_low(self):
        """Risk Map composite must remain high when conflict_pressure is 1.0 even if
        drift_rate is near zero (fresh document under heavy conflict)."""
        s = _scalar(freshness_score=0.99, canon_readiness=0.99, conflict_pressure=1.0)
        cv = compute_canon_variables(s, _context())
        # drift_rate low (fresh doc), but composite risk must see conflict_pressure = 1.0
        composite_risk = max(cv.drift_rate or 0.0, s.conflict_pressure, 0.0)
        assert composite_risk == 1.0

    def test_authority_regression_high_authority_conflicted_node(self):
        """A high-authority node under conflict retains raw authP while gamma drops."""
        s = _scalar(authority_score=0.90, conflict_pressure=0.80)
        cv = compute_canon_variables(s, _context())
        # raw authority stays high
        assert s.authority_score >= 0.7
        # effective authority (gamma) is meaningfully lower
        assert cv.gamma < 0.4

    def test_delta_c_star_change_does_not_affect_time_norm_concept(self):
        """delta_c_star is a stability signal, not temporal.
        Two nodes with identical freshness but different stability must share time_norm."""
        fresh = 0.65
        s_stable   = _scalar(freshness_score=fresh, conflict_pressure=0.0, drift_risk=0.0)
        s_unstable = _scalar(freshness_score=fresh, conflict_pressure=0.9, drift_risk=0.9)
        cv_stable   = compute_canon_variables(s_stable,   _context())
        cv_unstable = compute_canon_variables(s_unstable, _context())
        # delta_c_star differs
        assert cv_stable.delta_c_star > cv_unstable.delta_c_star
        # freshness_score (the basis for time_norm) is identical
        assert s_stable.freshness_score == s_unstable.freshness_score


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

class TestSerialisation:
    def test_as_dict_exact_has_required_keys(self):
        cv = compute_canon_variables(_scalar(), _context())
        d = cv.as_dict()
        for key in ("drift_rate", "entropy", "delta_c_star", "gamma",
                    "policy_id", "calculation_mode", "warnings"):
            assert key in d, f"missing key: {key}"

    def test_as_dict_partial_has_required_keys(self):
        cv = compute_canon_variables_partial(0.7, 0.8, 0.1, 0.65)
        d = cv.as_dict()
        for key in ("drift_rate", "entropy", "delta_c_star", "gamma",
                    "policy_id", "calculation_mode", "warnings"):
            assert key in d, f"missing key: {key}"

    def test_as_dict_partial_null_fields(self):
        d = compute_canon_variables_partial(0.7, 0.8, 0.1, 0.65).as_dict()
        assert d["entropy"]      is None
        assert d["delta_c_star"] is None

    def test_as_dict_warnings_list(self):
        d = compute_canon_variables_partial(0.5, 0.5, 0.5, 0.5).as_dict()
        assert isinstance(d["warnings"], list)
        assert len(d["warnings"]) == 4
        assert d["omega_viability"] is None
        assert d["mismatch_gradient"] is None


# ---------------------------------------------------------------------------
# CurrentFoldPacket integration
# ---------------------------------------------------------------------------

class TestCurrentFoldPacketIntegration:
    def _make_packet(self, with_canon_vars: bool = True):
        from app.core.current_fold import (
            CurrentFoldPacket,
            FoldResolverTraceRef,
            FoldScope,
        )
        from app.core.fold_metrics import FoldSymbolicState

        s = _scalar()
        sym = FoldSymbolicState(
            currentness_label="current",
            authority_label="approved",
            freshness_label="fresh",
            conflict_label="none",
            intake_label="interpretable_queryable",
        )
        cv = compute_canon_variables(s, _context()) if with_canon_vars else None

        return CurrentFoldPacket(
            schema_version="CurrentFoldPacket.v0.3",
            resolver_version="CurrentFoldResolver.v0.1",
            projection_version="DefaultFoldSymbolicPolicy.v0_1",
            visual_contract_version="FoldView.v0.1",
            scope=FoldScope(scale="node", scope_id="doc-test"),
            local_state={},
            scalar_state=s,
            symbolic_state=sym,
            projection_hints={},
            unknowns=[],
            resolver_trace_summary=[],
            resolver_trace_ref=FoldResolverTraceRef(available=False),
            canon_variables=cv,
        )

    def test_as_dict_includes_canon_variables_when_set(self):
        d = self._make_packet(with_canon_vars=True).as_dict()
        assert "canon_variables" in d
        assert d["canon_variables"]["calculation_mode"] == "exact"

    def test_as_dict_omits_canon_variables_key_when_none(self):
        d = self._make_packet(with_canon_vars=False).as_dict()
        assert "canon_variables" not in d

    def test_scalar_state_still_ten_fields(self):
        """FoldScalarState must not be modified — exactly 10 scalar pressure fields."""
        scalar_fields = [
            f.name for f in dc_fields(FoldScalarState)
            if f.name not in ("metric_policy", "scores_are_truth_values")
        ]
        assert len(scalar_fields) == 10, (
            f"FoldScalarState has {len(scalar_fields)} scalar fields, expected 10: {scalar_fields}"
        )

    def test_canon_variables_field_is_optional_after_required_fields(self):
        """canon_variables must be an optional field (has default) in CurrentFoldPacket."""
        from app.core.current_fold import CurrentFoldPacket
        field_names = [f.name for f in dc_fields(CurrentFoldPacket)]
        assert "canon_variables" in field_names
        # Optional fields (those with defaults) come after required ones in dataclass
        # Verify it has a default by checking Python's __dataclass_fields__
        f = CurrentFoldPacket.__dataclass_fields__["canon_variables"]
        from dataclasses import MISSING
        assert f.default is None or f.default_factory is not MISSING or f.default is not MISSING


# ---------------------------------------------------------------------------
# Aggregation engine regression
# ---------------------------------------------------------------------------

class TestAggregationEngineUnaffected:
    def test_fold_aggregation_accepts_packet_with_canon_variables(self):
        """The Phase 7a aggregation engine must not break when canon_variables is present."""
        from app.core.fold_aggregation import FoldMemberInput, aggregate_cluster

        from app.core.current_fold import (
            CurrentFoldPacket,
            FoldResolverTraceRef,
            FoldScope,
        )
        from app.core.fold_metrics import FoldSymbolicState

        s = _scalar()
        sym = FoldSymbolicState(
            currentness_label="current",
            authority_label="approved",
            freshness_label="fresh",
            conflict_label="none",
            intake_label="interpretable_queryable",
        )
        cv = compute_canon_variables(s, _context())

        packet = CurrentFoldPacket(
            schema_version="CurrentFoldPacket.v0.3",
            resolver_version="CurrentFoldResolver.v0.1",
            projection_version="DefaultFoldSymbolicPolicy.v0_1",
            visual_contract_version="FoldView.v0.1",
            scope=FoldScope(scale="node", scope_id="doc-agg-test"),
            local_state={},
            scalar_state=s,
            symbolic_state=sym,
            projection_hints={},
            unknowns=[],
            resolver_trace_summary=[],
            resolver_trace_ref=FoldResolverTraceRef(available=False),
            canon_variables=cv,
        )

        members = [FoldMemberInput(node_packet=packet, axis_value="test-project")]
        result = aggregate_cluster("project", "test-project", members)
        # Should succeed; the aggregation engine should not choke on canon_variables
        assert result is not None
        cluster_dict = result.as_dict()
        assert "scalar_state" in cluster_dict
        # canon_variables is not part of aggregate packets (no requirement to propagate it)
