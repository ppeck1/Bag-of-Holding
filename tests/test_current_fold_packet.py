"""tests/test_current_fold_packet.py -- Acceptance tests for CurrentFoldPacket.

Covers:
  - Policy dataclasses (FoldMetricPolicy, FoldSymbolicPolicy)
  - FoldScalarState and FoldSymbolicState construction
  - FoldUnknown object structure
  - adapt_folded_node_to_current_fold() adapter
  - current_fold_from_folded_node() resolver
  - Symbolic projection precedence rules
  - Compact trace: always exactly six events
  - GET /api/fold/node/{doc_id} route
  - GET /api/fold/node/{doc_id}/trace stub
  - Existing /api/docs/{doc_id}/fold unaffected

Governance invariants tested:
  - unknowns[] always present (even if empty)
  - Missing authority registers unknown; blocks currentness
  - Quarantined overrides all currentness labels
  - Superseded not rendered current
  - Blocking conflicts prevent clean current label
  - Scalar scores are NOT truth scores (scores_are_truth_values = False)
  - Compact trace contains exactly six events
  - Degraded packets still contain schema_version, scope, unknowns[]
"""

from __future__ import annotations

import importlib
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Test client fixture (mirrors test_folded_node_packet.py pattern)
# ---------------------------------------------------------------------------

@contextmanager
def _client(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    db_path = tmp_path / "boh.db"
    monkeypatch.setenv("BOH_LIBRARY", str(library))
    monkeypatch.setenv("BOH_DB", str(db_path))
    monkeypatch.setenv("BOH_OPERATOR_TOKEN", "test-token")

    import app.db.connection as db
    db.DB_PATH = str(db_path)
    db.init_db()

    import app.core.auth as auth
    import app.api.main as main
    importlib.reload(auth)
    importlib.reload(main)
    main.db.DB_PATH = str(db_path)
    main.db.init_db()
    with TestClient(main.app) as client:
        yield client, db, library


def _insert_doc(db, doc_id: str, title: str = "Test Doc", authority_state: str = "reviewed") -> None:
    db.execute(
        """INSERT OR IGNORE INTO docs (doc_id, title, path, authority_state)
           VALUES (?, ?, ?, ?)""",
        (doc_id, title, f"/library/{doc_id}.md", authority_state),
    )


# ---------------------------------------------------------------------------
# Policy dataclass tests (pure unit -- no DB needed)
# ---------------------------------------------------------------------------

class TestFoldMetricPolicy:
    def test_default_policy_id(self):
        from app.core.fold_metrics import FoldMetricPolicy
        p = FoldMetricPolicy.default()
        assert p.policy_id == "FoldMetricPolicy.v0.1"

    def test_default_scores_are_not_truth(self):
        from app.core.fold_metrics import FoldMetricPolicy
        p = FoldMetricPolicy.default()
        assert p.scores_are_truth_values is False

    def test_default_no_llm_scores(self):
        from app.core.fold_metrics import FoldMetricPolicy
        p = FoldMetricPolicy.default()
        assert p.allow_llm_derived_scores is False

    def test_default_no_random_scores(self):
        from app.core.fold_metrics import FoldMetricPolicy
        p = FoldMetricPolicy.default()
        assert p.allow_random_scores is False

    def test_default_lineage_depth_cap(self):
        from app.core.fold_metrics import FoldMetricPolicy
        p = FoldMetricPolicy.default()
        assert p.max_lineage_depth == 5

    def test_default_scalar_clamping(self):
        from app.core.fold_metrics import FoldMetricPolicy
        p = FoldMetricPolicy.default()
        assert p.scalar_clamping == (0.0, 1.0)

    def test_default_freshness_priority(self):
        from app.core.fold_metrics import FoldMetricPolicy
        p = FoldMetricPolicy.default()
        assert p.freshness_source_priority[0] == "epistemic_last_evaluated"
        assert p.freshness_source_priority[1] == "updated_ts"

    def test_frozen(self):
        from app.core.fold_metrics import FoldMetricPolicy
        p = FoldMetricPolicy.default()
        with pytest.raises((AttributeError, TypeError)):
            p.policy_id = "tampered"  # type: ignore[misc]


class TestFoldSymbolicPolicy:
    def test_default_policy_id(self):
        from app.core.fold_metrics import FoldSymbolicPolicy
        p = FoldSymbolicPolicy.default()
        assert p.policy_id == "DefaultFoldSymbolicPolicy.v0_1"

    def test_default_thresholds(self):
        from app.core.fold_metrics import FoldSymbolicPolicy
        p = FoldSymbolicPolicy.default()
        assert p.conflict_pressure_contested_threshold == pytest.approx(0.35)
        assert p.authority_score_minimum_for_current == pytest.approx(0.30)
        assert p.freshness_score_stale_threshold == pytest.approx(0.25)
        assert p.canon_readiness_minimum == pytest.approx(0.50)
        assert p.resolution_confidence_minimum == pytest.approx(0.40)

    def test_frozen(self):
        from app.core.fold_metrics import FoldSymbolicPolicy
        p = FoldSymbolicPolicy.default()
        with pytest.raises((AttributeError, TypeError)):
            p.policy_id = "tampered"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Scalar computation tests (pure unit)
# ---------------------------------------------------------------------------

class TestComputeFoldScalarState:
    def _make_context(self, **overrides):
        from app.core.fold_metrics import FoldMetricContext
        defaults = dict(
            doc_id="doc_1",
            edge_count=3,
            cross_unapproved=0,
            unresolved_conflicts=0,
            lineage_depth=1,
            lineage_depth_capped=False,
            freshness_age_days=14,
            freshness_source_used="updated_ts",
            superseded=False,
            supporting_sources=2,
            missing_fields=[],
            intake_interpretable=True,
            intake_queryable=True,
            intake_safety_lane="direct",
            intake_normalizable=True,
            intake_preservable=True,
            intake_failure_reason=None,
            epistemic_d=None,
            epistemic_q=None,
            epistemic_c=None,
        )
        defaults.update(overrides)
        return FoldMetricContext(**defaults)

    def _make_base_packet(self, authority_state: str = "reviewed") -> dict:
        return {
            "doc_id": "doc_1",
            "title": "Test",
            "facets": {
                "authority": {"authority_state": authority_state, "canon_eligible": 0},
                "conflicts": {"count": 0, "items": []},
                "chunks": {"count": 3},
            }
        }

    def test_all_scores_in_range(self):
        from app.core.fold_metrics import compute_fold_scalar_state
        ctx = self._make_context()
        packet = self._make_base_packet()
        result = compute_fold_scalar_state(packet, ctx)
        for fname in ["authority_score", "freshness_score", "evidence_strength",
                      "conflict_pressure", "interpretability", "queryability",
                      "canon_readiness", "drift_risk", "resolution_confidence", "blast_radius"]:
            val = getattr(result, fname)
            assert 0.0 <= val <= 1.0, f"{fname}={val} out of [0, 1]"

    def test_scores_are_not_truth(self):
        from app.core.fold_metrics import compute_fold_scalar_state
        ctx = self._make_context()
        result = compute_fold_scalar_state(self._make_base_packet(), ctx)
        assert result.scores_are_truth_values is False

    def test_metric_policy_tagged(self):
        from app.core.fold_metrics import compute_fold_scalar_state
        ctx = self._make_context()
        result = compute_fold_scalar_state(self._make_base_packet(), ctx)
        assert result.metric_policy == "FoldMetricPolicy.v0.1"

    def test_high_authority_score(self):
        from app.core.fold_metrics import compute_fold_scalar_state
        ctx = self._make_context()
        result = compute_fold_scalar_state(self._make_base_packet("canonical"), ctx)
        assert result.authority_score >= 0.90

    def test_unknown_authority_low_score(self):
        from app.core.fold_metrics import compute_fold_scalar_state
        ctx = self._make_context()
        result = compute_fold_scalar_state(self._make_base_packet("unknown"), ctx)
        assert result.authority_score < 0.30

    def test_missing_freshness_zero(self):
        from app.core.fold_metrics import compute_fold_scalar_state
        ctx = self._make_context(freshness_age_days=None)
        result = compute_fold_scalar_state(self._make_base_packet(), ctx)
        assert result.freshness_score == pytest.approx(0.0)

    def test_as_dict_contains_all_fields(self):
        from app.core.fold_metrics import compute_fold_scalar_state
        ctx = self._make_context()
        result = compute_fold_scalar_state(self._make_base_packet(), ctx)
        d = result.as_dict()
        for key in ["authority_score", "freshness_score", "evidence_strength",
                    "conflict_pressure", "interpretability", "queryability",
                    "canon_readiness", "drift_risk", "resolution_confidence", "blast_radius",
                    "metric_policy", "scores_are_truth_values"]:
            assert key in d, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# Symbolic projection tests (pure unit)
# ---------------------------------------------------------------------------

class TestProjectSymbolicState:
    def _make_scalar(self, **overrides):
        from app.core.fold_metrics import FoldScalarState
        defaults = dict(
            authority_score=0.75,
            freshness_score=0.80,
            evidence_strength=0.50,
            conflict_pressure=0.10,
            interpretability=0.90,
            queryability=0.90,
            canon_readiness=0.65,
            drift_risk=0.20,
            resolution_confidence=0.85,
            blast_radius=0.15,
        )
        defaults.update(overrides)
        return FoldScalarState(**defaults)

    def _make_base(self, authority_state: str = "reviewed", conflicts: bool = False,
                   superseded: bool = False, status: str = "") -> dict:
        items = [{"desc": "conflict"}] if conflicts else []
        return {
            "doc_id": "doc_1",
            "superseded": superseded,
            "facets": {
                "authority": {"authority_state": authority_state, "status": status},
                "conflicts": {"count": len(items), "items": items},
            }
        }

    def test_clean_node_is_current(self):
        from app.core.fold_metrics import project_symbolic_state
        scalar = self._make_scalar()
        result = project_symbolic_state(scalar, self._make_base())
        assert result.currentness_label == "current"

    def test_quarantined_overrides_all(self):
        from app.core.fold_metrics import project_symbolic_state
        scalar = self._make_scalar(authority_score=0.95, freshness_score=0.95)
        base = self._make_base(status="quarantine")
        result = project_symbolic_state(scalar, base)
        assert result.currentness_label == "quarantined"

    def test_held_produces_held(self):
        from app.core.fold_metrics import project_symbolic_state
        scalar = self._make_scalar()
        base = self._make_base(status="hold")
        result = project_symbolic_state(scalar, base)
        assert result.currentness_label == "held"

    def test_superseded_not_current(self):
        from app.core.fold_metrics import project_symbolic_state
        scalar = self._make_scalar()
        base = self._make_base(superseded=True)
        result = project_symbolic_state(scalar, base)
        assert result.currentness_label == "superseded"

    def test_blocking_conflict_is_conflicted(self):
        from app.core.fold_metrics import project_symbolic_state
        scalar = self._make_scalar()
        base = self._make_base(conflicts=True)
        result = project_symbolic_state(scalar, base)
        assert result.currentness_label == "conflicted"

    def test_stale_freshness_produces_stale(self):
        from app.core.fold_metrics import project_symbolic_state
        scalar = self._make_scalar(freshness_score=0.10)
        result = project_symbolic_state(scalar, self._make_base())
        assert result.currentness_label == "stale"

    def test_low_authority_is_unknown(self):
        from app.core.fold_metrics import project_symbolic_state
        scalar = self._make_scalar(authority_score=0.15)
        result = project_symbolic_state(scalar, self._make_base())
        assert result.currentness_label == "unknown"

    def test_high_conflict_pressure_contested(self):
        from app.core.fold_metrics import project_symbolic_state
        scalar = self._make_scalar(conflict_pressure=0.50)
        result = project_symbolic_state(scalar, self._make_base())
        assert result.currentness_label == "current_but_contested"

    def test_draft_authority_is_draft_current(self):
        from app.core.fold_metrics import project_symbolic_state
        scalar = self._make_scalar()
        base = self._make_base(authority_state="draft")
        result = project_symbolic_state(scalar, base)
        assert result.currentness_label == "draft_current"

    def test_symbolic_policy_tagged(self):
        from app.core.fold_metrics import project_symbolic_state
        scalar = self._make_scalar()
        result = project_symbolic_state(scalar, self._make_base())
        assert result.symbolic_policy == "DefaultFoldSymbolicPolicy.v0_1"

    def test_as_dict_contains_all_fields(self):
        from app.core.fold_metrics import project_symbolic_state
        scalar = self._make_scalar()
        result = project_symbolic_state(scalar, self._make_base())
        d = result.as_dict()
        for key in ["currentness_label", "authority_label", "freshness_label",
                    "conflict_label", "intake_label", "symbolic_policy"]:
            assert key in d


# ---------------------------------------------------------------------------
# FoldUnknown tests (pure unit)
# ---------------------------------------------------------------------------

class TestFoldUnknown:
    def test_unknown_has_all_fields(self):
        from app.core.current_fold import FoldUnknown
        u = FoldUnknown(
            field="authority_state",
            severity="high",
            meaning="No authority state found.",
            blocks_currentness=True,
            blocks_canon_eligibility=True,
            blocks_queryability=False,
            resolution_action="Route to review queue.",
        )
        d = u.as_dict()
        assert d["field"] == "authority_state"
        assert d["severity"] == "high"
        assert d["blocks_currentness"] is True
        assert d["blocks_canon_eligibility"] is True
        assert d["blocks_queryability"] is False
        assert "resolution_action" in d


# ---------------------------------------------------------------------------
# Adapter tests (pure unit -- no DB)
# ---------------------------------------------------------------------------

class TestAdaptFoldedNodeToCurrentFold:
    def _make_inputs(self, authority_state: str = "reviewed"):
        from app.core.fold_metrics import (
            FoldScalarState, FoldSymbolicState, FoldMetricContext,
            compute_fold_scalar_state, project_symbolic_state,
        )
        base = {
            "doc_id": "doc_1",
            "title": "Test",
            "summary": "A test document.",
            "facets": {
                "authority": {"authority_state": authority_state, "canon_eligible": 0, "status": ""},
                "conflicts": {"count": 0, "items": []},
                "chunks": {"count": 2},
                "lifecycle": {},
                "provenance": {},
                "source": {},
            }
        }
        ctx = FoldMetricContext(
            doc_id="doc_1", edge_count=2, cross_unapproved=0, unresolved_conflicts=0,
            lineage_depth=1, lineage_depth_capped=False, freshness_age_days=10,
            freshness_source_used="updated_ts", superseded=False, supporting_sources=1,
            missing_fields=[], intake_interpretable=True, intake_queryable=True,
            intake_safety_lane="direct", intake_normalizable=True, intake_preservable=True,
            intake_failure_reason=None, epistemic_d=None, epistemic_q=None, epistemic_c=None,
        )
        scalar = compute_fold_scalar_state(base, ctx)
        symbolic = project_symbolic_state(scalar, base)
        return base, scalar, symbolic

    def test_packet_has_schema_version(self):
        from app.core.current_fold import adapt_folded_node_to_current_fold
        base, scalar, symbolic = self._make_inputs()
        pkt = adapt_folded_node_to_current_fold(base, scalar, symbolic)
        assert pkt.schema_version.startswith("CurrentFoldPacket")

    def test_packet_has_resolver_version(self):
        from app.core.current_fold import adapt_folded_node_to_current_fold
        base, scalar, symbolic = self._make_inputs()
        pkt = adapt_folded_node_to_current_fold(base, scalar, symbolic)
        assert pkt.resolver_version

    def test_packet_has_scope_node(self):
        from app.core.current_fold import adapt_folded_node_to_current_fold
        base, scalar, symbolic = self._make_inputs()
        pkt = adapt_folded_node_to_current_fold(base, scalar, symbolic)
        assert pkt.scope.scale == "node"
        assert pkt.scope.scope_id == "doc_1"

    def test_packet_unknowns_always_present(self):
        from app.core.current_fold import adapt_folded_node_to_current_fold
        base, scalar, symbolic = self._make_inputs()
        pkt = adapt_folded_node_to_current_fold(base, scalar, symbolic)
        assert isinstance(pkt.unknowns, list)

    def test_missing_authority_registers_unknown(self):
        from app.core.current_fold import adapt_folded_node_to_current_fold
        base, scalar, symbolic = self._make_inputs(authority_state="unknown")
        pkt = adapt_folded_node_to_current_fold(base, scalar, symbolic)
        fields = [u.field for u in pkt.unknowns]
        assert "authority_state" in fields

    def test_missing_authority_blocks_currentness(self):
        from app.core.current_fold import adapt_folded_node_to_current_fold
        base, scalar, symbolic = self._make_inputs(authority_state="unknown")
        pkt = adapt_folded_node_to_current_fold(base, scalar, symbolic)
        for u in pkt.unknowns:
            if u.field == "authority_state":
                assert u.blocks_currentness is True
                break

    def test_lineage_capped_registers_unknown(self):
        from app.core.current_fold import adapt_folded_node_to_current_fold
        base, scalar, symbolic = self._make_inputs()
        pkt = adapt_folded_node_to_current_fold(
            base, scalar, symbolic, lineage_depth_capped=True
        )
        fields = [u.field for u in pkt.unknowns]
        assert "lineage_depth" in fields

    def test_compact_trace_exactly_six_events(self):
        from app.core.current_fold import adapt_folded_node_to_current_fold
        base, scalar, symbolic = self._make_inputs()
        pkt = adapt_folded_node_to_current_fold(base, scalar, symbolic)
        assert len(pkt.resolver_trace_summary) == 6

    def test_compact_trace_event_names(self):
        from app.core.current_fold import adapt_folded_node_to_current_fold
        base, scalar, symbolic = self._make_inputs()
        pkt = adapt_folded_node_to_current_fold(base, scalar, symbolic)
        events = [e.event for e in pkt.resolver_trace_summary]
        expected = [
            "authority_state_checked",
            "supersession_checked",
            "conflicts_checked",
            "freshness_checked",
            "intake_capability_checked",
            "scalar_state_computed",
        ]
        assert events == expected

    def test_scalar_state_computed_collapsed_by_default(self):
        from app.core.current_fold import adapt_folded_node_to_current_fold
        base, scalar, symbolic = self._make_inputs()
        pkt = adapt_folded_node_to_current_fold(base, scalar, symbolic)
        last = pkt.resolver_trace_summary[-1]
        assert last.event == "scalar_state_computed"
        assert last.collapsed_by_default is True

    def test_projection_hints_present(self):
        from app.core.current_fold import adapt_folded_node_to_current_fold
        base, scalar, symbolic = self._make_inputs()
        pkt = adapt_folded_node_to_current_fold(base, scalar, symbolic)
        assert "recommended_default_surface" in pkt.projection_hints
        assert pkt.projection_hints["layout_is_truth"] is False

    def test_as_dict_complete_schema(self):
        from app.core.current_fold import adapt_folded_node_to_current_fold
        base, scalar, symbolic = self._make_inputs()
        pkt = adapt_folded_node_to_current_fold(base, scalar, symbolic)
        d = pkt.as_dict()
        required = [
            "schema_version", "resolver_version", "projection_version",
            "visual_contract_version", "scope", "local_state", "scalar_state",
            "symbolic_state", "projection_hints", "unknowns",
            "resolver_trace_summary", "resolver_trace_ref", "cache_status",
        ]
        for key in required:
            assert key in d, f"Missing key: {key}"

    def test_cache_status_live(self):
        from app.core.current_fold import adapt_folded_node_to_current_fold
        base, scalar, symbolic = self._make_inputs()
        pkt = adapt_folded_node_to_current_fold(base, scalar, symbolic)
        assert pkt.cache_status == "live"


# ---------------------------------------------------------------------------
# Why-current provenance rows
# ---------------------------------------------------------------------------

class TestWhyCurrentProvenance:
    """The why_current rows must carry provenance prefixes so a reader can tell
    how each factor was derived: direct / computed / inferred / unknown."""

    def _packet(self, authority_state="reviewed", conflict_count=0,
                missing_freshness=False):
        from app.core.fold_metrics import (
            FoldMetricContext, compute_fold_scalar_state, project_symbolic_state,
        )
        from app.core.current_fold import adapt_folded_node_to_current_fold
        base = {
            "doc_id": "doc_w", "title": "T", "summary": "S",
            "facets": {
                "authority": {"authority_state": authority_state, "canon_eligible": 0, "status": ""},
                "conflicts": {"count": conflict_count, "items": [{"id": i} for i in range(conflict_count)]},
                "chunks": {"count": 1}, "lifecycle": {}, "provenance": {}, "source": {},
            },
        }
        ctx = FoldMetricContext(
            doc_id="doc_w", edge_count=0, cross_unapproved=0,
            unresolved_conflicts=conflict_count,
            lineage_depth=0, lineage_depth_capped=False,
            freshness_age_days=None if missing_freshness else 5,
            freshness_source_used=None if missing_freshness else "updated_ts",
            superseded=False, supporting_sources=0,
            missing_fields=["freshness_age_days"] if missing_freshness else [],
            intake_interpretable=True, intake_queryable=True, intake_safety_lane="direct",
            intake_normalizable=True, intake_preservable=True, intake_failure_reason=None,
            epistemic_d=None, epistemic_q=None, epistemic_c=None,
        )
        scalar = compute_fold_scalar_state(base, ctx)
        symbolic = project_symbolic_state(scalar, base)
        return adapt_folded_node_to_current_fold(
            base, scalar, symbolic,
            metric_context_missing=ctx.missing_fields,
        )

    def _rows(self, pkt):
        return [r.as_dict() for r in pkt.why_current]

    def test_every_row_has_provenance_prefix(self):
        rows = self._rows(self._packet())
        assert rows
        prefixes = ("direct:", "computed:", "inferred:", "unknown:")
        for r in rows:
            assert any(r["evi"].startswith(p) for p in prefixes), \
                f"row missing provenance prefix: {r}"

    def test_conflict_row_is_direct_count(self):
        rows = self._rows(self._packet(conflict_count=2))
        conflict = next(r for r in rows if r["factor"] == "Open conflicts")
        assert conflict["evi"].startswith("direct:")
        assert "2 open conflicts" in conflict["evi"]

    def test_no_conflict_row_is_direct_none(self):
        rows = self._rows(self._packet(conflict_count=0))
        conflict = next(r for r in rows if r["factor"] == "Open conflicts")
        assert conflict["evi"] == "direct: none"

    def test_missing_freshness_emits_unknown_row(self):
        rows = self._rows(self._packet(missing_freshness=True))
        fresh = next(r for r in rows if r["factor"] == "Source freshness")
        assert fresh["evi"].startswith("unknown:")

    def test_present_freshness_is_computed_or_direct(self):
        rows = self._rows(self._packet(missing_freshness=False))
        fresh = next(r for r in rows if r["factor"] == "Source freshness")
        assert fresh["evi"].startswith("computed:") or fresh["evi"].startswith("direct:")

    def test_absent_authority_state_emits_unknown_row(self):
        rows = self._rows(self._packet(authority_state=""))
        auth = next(r for r in rows if r["factor"] == "Authority")
        assert auth["evi"].startswith("unknown:")

    def test_present_authority_state_is_direct(self):
        rows = self._rows(self._packet(authority_state="reviewed"))
        auth = next(r for r in rows if r["factor"] == "Authority")
        assert auth["evi"].startswith("direct:")
        assert "reviewed" in auth["evi"]

    def test_disclosure_preserved_not_removed(self):
        # The provenance disclosure must remain even though wording improved:
        # at least one row should be computed/unknown (not all "direct").
        rows = self._rows(self._packet(missing_freshness=True, authority_state=""))
        kinds = {r["evi"].split(":")[0] for r in rows}
        assert "unknown" in kinds


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------

class TestFoldRoutes:
    def test_fold_node_404_for_missing_doc(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            r = client.get("/api/fold/node/nonexistent_doc_999")
            assert r.status_code == 404

    def test_fold_node_returns_current_fold_packet(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "doc_fold_1", authority_state="reviewed")
            r = client.get("/api/fold/node/doc_fold_1")
            assert r.status_code == 200
            data = r.json()
            assert "schema_version" in data
            assert "scope" in data
            assert data["scope"]["scope_id"] == "doc_fold_1"
            assert data["local_state"]["path"] == "/library/doc_fold_1.md"

    def test_fold_node_unknowns_always_present(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "doc_fold_2", authority_state="reviewed")
            r = client.get("/api/fold/node/doc_fold_2")
            assert r.status_code == 200
            data = r.json()
            assert "unknowns" in data
            assert isinstance(data["unknowns"], list)

    def test_fold_node_compact_trace_six_events(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "doc_fold_3", authority_state="approved")
            r = client.get("/api/fold/node/doc_fold_3")
            assert r.status_code == 200
            data = r.json()
            assert len(data["resolver_trace_summary"]) == 6

    def test_fold_node_scores_not_truth(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "doc_fold_4", authority_state="trusted")
            r = client.get("/api/fold/node/doc_fold_4")
            assert r.status_code == 200
            data = r.json()
            assert data["scalar_state"]["scores_are_truth_values"] is False

    def test_fold_node_cache_status_live(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "doc_fold_5", authority_state="reviewed")
            r = client.get("/api/fold/node/doc_fold_5")
            assert r.status_code == 200
            assert r.json()["cache_status"] == "live"

    def test_fold_trace_stub_returns_200(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "doc_fold_6")
            r = client.get("/api/fold/node/doc_fold_6/trace")
            assert r.status_code == 200

    def test_fold_trace_stub_available_false(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "doc_fold_7")
            r = client.get("/api/fold/node/doc_fold_7/trace")
            assert r.status_code == 200
            assert r.json()["available"] is False

    def test_existing_fold_endpoint_unaffected(self, tmp_path, monkeypatch):
        """Existing /api/docs/{id}/fold must still work unchanged."""
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "doc_fold_8", title="Old Fold Test")
            r = client.get("/api/docs/doc_fold_8/fold")
            assert r.status_code == 200

    def test_fold_node_resolver_trace_ref_endpoint(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "doc_fold_9")
            r = client.get("/api/fold/node/doc_fold_9")
            assert r.status_code == 200
            ref = r.json()["resolver_trace_ref"]
            assert "/api/fold/node/doc_fold_9/trace" in ref["endpoint"]

    def test_fold_node_symbolic_state_present(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "doc_fold_10", authority_state="reviewed")
            r = client.get("/api/fold/node/doc_fold_10")
            assert r.status_code == 200
            sym = r.json()["symbolic_state"]
            assert "currentness_label" in sym
            assert "symbolic_policy" in sym

    def test_fold_node_scope_is_node_scale(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "doc_fold_11")
            r = client.get("/api/fold/node/doc_fold_11")
            assert r.status_code == 200
            assert r.json()["scope"]["scale"] == "node"
