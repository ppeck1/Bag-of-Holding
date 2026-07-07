"""tests/test_fold_scale_actions.py -- Phase 6 node-scale scale_actions.

Covers the additive, read-only scale_actions[] field on the node-level
CurrentFoldPacket (buildspec Phase 6):
  - field is present and additive (existing schema unchanged)
  - project / plane roll-up target_id derivation ("{axis}:{value}", round-trip)
  - missing-axis handling (domain always allowed:false; absent project allowed:false)
  - every allowed:false action carries a non-empty reason
  - actions are navigational only (no mutation, no write path)

No aggregation, no cluster routes, no DB writes are involved.
"""

from __future__ import annotations

import importlib
from contextlib import contextmanager

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Test client fixture (mirrors test_current_fold_packet.py)
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


def _insert_doc(db, doc_id: str, title: str = "Test Doc",
                authority_state: str = "reviewed", project: str | None = None) -> None:
    if project is None:
        db.execute(
            """INSERT OR IGNORE INTO docs (doc_id, title, path, authority_state)
               VALUES (?, ?, ?, ?)""",
            (doc_id, title, f"/library/{doc_id}.md", authority_state),
        )
    else:
        db.execute(
            """INSERT OR IGNORE INTO docs (doc_id, title, path, authority_state, project)
               VALUES (?, ?, ?, ?, ?)""",
            (doc_id, title, f"/library/{doc_id}.md", authority_state, project),
        )


def _insert_lattice_domain(db, domain: str, label: str = "Test Domain") -> None:
    db.execute(
        """INSERT OR IGNORE INTO substrate_lattice_registry
           (lattice_id, domain, label, created_at)
           VALUES (?, ?, ?, ?)""",
        (f"SL_{domain}", domain, label, "2026-01-01T00:00:00+00:00"),
    )


def _link_doc_topic(db, doc_id: str, topics: str) -> None:
    db.execute("UPDATE docs SET topics_tokens = ? WHERE doc_id = ?", (topics, doc_id))


# ---------------------------------------------------------------------------
# Pure-unit tests over the builder helper
# ---------------------------------------------------------------------------

class TestBuildNodeScaleActions:
    def _by_axis(self, actions, axis):
        for a in actions:
            if a.target_axis == axis:
                return a
        raise AssertionError(f"no action for axis {axis}")

    def test_project_action_round_trip(self):
        from app.core.current_fold import _build_node_scale_actions
        base = {"summary": {"project": "boh"}, "facets": {}}
        actions = _build_node_scale_actions(base)
        proj = self._by_axis(actions, "project")
        assert proj.allowed is True
        assert proj.target_scale == "cluster"
        assert proj.target_id == "project:boh"

    def test_project_missing_is_disallowed_with_reason(self):
        from app.core.current_fold import _build_node_scale_actions
        base = {"summary": {}, "facets": {}}
        actions = _build_node_scale_actions(base)
        proj = self._by_axis(actions, "project")
        assert proj.allowed is False
        assert proj.target_id is None
        assert proj.reason and proj.reason.strip()

    def test_plane_action_from_plane_card(self):
        from app.core.current_fold import _build_node_scale_actions
        base = {"summary": {"project": "boh"},
                "facets": {"plane_card": {"present": True, "plane": "authority"}}}
        actions = _build_node_scale_actions(base)
        plane = self._by_axis(actions, "plane")
        assert plane.allowed is True
        assert plane.target_id == "plane:authority"

    def test_plane_falls_back_to_canonical_layer(self):
        from app.core.current_fold import _build_node_scale_actions
        base = {"summary": {"project": "boh"},
                "facets": {"plane_card": {"present": False},
                           "authority": {"canonical_layer": "informational"}}}
        actions = _build_node_scale_actions(base)
        plane = self._by_axis(actions, "plane")
        assert plane.allowed is True
        assert plane.target_id == "plane:informational"

    def test_plane_missing_is_disallowed_with_reason(self):
        from app.core.current_fold import _build_node_scale_actions
        base = {"summary": {"project": "boh"}, "facets": {}}
        actions = _build_node_scale_actions(base)
        plane = self._by_axis(actions, "plane")
        assert plane.allowed is False
        assert plane.reason and plane.reason.strip()

    def test_domain_without_doc_context_is_disallowed_with_reason(self):
        from app.core.current_fold import _build_node_scale_actions
        base = {"summary": {"project": "boh"},
                "facets": {"plane_card": {"present": True, "plane": "authority"}}}
        actions = _build_node_scale_actions(base)
        domain = self._by_axis(actions, "domain")
        assert domain.allowed is False
        assert domain.target_id is None
        assert domain.reason and domain.reason.strip()

    def test_every_disallowed_action_has_reason(self):
        from app.core.current_fold import _build_node_scale_actions
        base = {"summary": {}, "facets": {}}
        actions = _build_node_scale_actions(base)
        for a in actions:
            if not a.allowed:
                assert a.reason and a.reason.strip(), f"{a.target_axis} missing reason"

    def test_non_dict_summary_does_not_crash(self):
        from app.core.current_fold import _build_node_scale_actions
        # The adapter unit tests pass summary as a string; helper must tolerate it.
        base = {"summary": "a plain string summary", "facets": {}}
        actions = _build_node_scale_actions(base)
        assert any(a.target_axis == "project" for a in actions)

    def test_action_as_dict_shape(self):
        from app.core.current_fold import FoldScaleAction
        a = FoldScaleAction(label="Roll up to project", target_scale="cluster",
                            target_axis="project", allowed=True, target_id="project:boh")
        d = a.as_dict()
        assert d["label"] and d["target_scale"] == "cluster"
        assert d["target_axis"] == "project"
        assert d["target_id"] == "project:boh"
        assert d["allowed"] is True
        # reason omitted when None
        assert "reason" not in d


# ---------------------------------------------------------------------------
# Adapter / packet integration (additive field, no regression)
# ---------------------------------------------------------------------------

class TestPacketAdditiveField:
    def _inputs(self, base):
        from app.core.fold_metrics import (
            FoldMetricContext, compute_fold_scalar_state, project_symbolic_state,
        )
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
        return scalar, symbolic

    def test_as_dict_includes_scale_actions(self):
        from app.core.current_fold import adapt_folded_node_to_current_fold
        base = {
            "doc_id": "doc_1", "title": "Test",
            "summary": {"project": "boh"},
            "facets": {
                "authority": {"authority_state": "reviewed", "canon_eligible": 0,
                              "status": "", "canonical_layer": "informational"},
                "conflicts": {"count": 0, "items": []},
                "chunks": {"count": 2},
                "plane_card": {"present": True, "plane": "authority"},
            },
        }
        scalar, symbolic = self._inputs(base)
        pkt = adapt_folded_node_to_current_fold(base, scalar, symbolic)
        d = pkt.as_dict()
        assert "scale_actions" in d
        assert isinstance(d["scale_actions"], list) and len(d["scale_actions"]) >= 1
        # pre-existing schema keys remain intact
        for key in ["schema_version", "scope", "local_state", "scalar_state",
                    "symbolic_state", "unknowns", "resolver_trace_summary",
                    "resolver_trace_ref", "cache_status"]:
            assert key in d


# ---------------------------------------------------------------------------
# Route integration
# ---------------------------------------------------------------------------

class TestFoldNodeScaleActionsRoute:
    def test_route_returns_scale_actions(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "doc_sa_1", project="boh")
            r = client.get("/api/fold/node/doc_sa_1")
            assert r.status_code == 200
            data = r.json()
            assert "scale_actions" in data
            assert isinstance(data["scale_actions"], list)

    def test_route_project_target_id_round_trip(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "doc_sa_2", project="boh")
            r = client.get("/api/fold/node/doc_sa_2")
            assert r.status_code == 200
            proj = [a for a in r.json()["scale_actions"] if a["target_axis"] == "project"]
            assert proj and proj[0]["allowed"] is True
            assert proj[0]["target_id"] == "project:boh"

    def test_route_domain_disallowed_with_reason(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "doc_sa_3")
            r = client.get("/api/fold/node/doc_sa_3")
            assert r.status_code == 200
            domain = [a for a in r.json()["scale_actions"] if a["target_axis"] == "domain"]
            assert domain and domain[0]["allowed"] is False
            assert domain[0].get("reason")

    def test_route_domain_allowed_when_single_registered_topic_matches(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_lattice_domain(db, "clinical")
            _insert_doc(db, "doc_sa_domain", project="boh")
            _link_doc_topic(db, "doc_sa_domain", "clinical")
            r = client.get("/api/fold/node/doc_sa_domain")
            assert r.status_code == 200
            domain = [a for a in r.json()["scale_actions"] if a["target_axis"] == "domain"]
            assert domain and domain[0]["allowed"] is True
            assert domain[0]["target_id"] == "domain:clinical"

    def test_route_domain_disallowed_when_multiple_registered_topics_match(self, tmp_path, monkeypatch):
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_lattice_domain(db, "clinical")
            _insert_lattice_domain(db, "engineering")
            _insert_doc(db, "doc_sa_multi_domain", project="boh")
            _link_doc_topic(db, "doc_sa_multi_domain", "clinical engineering")
            r = client.get("/api/fold/node/doc_sa_multi_domain")
            assert r.status_code == 200
            domain = [a for a in r.json()["scale_actions"] if a["target_axis"] == "domain"]
            assert domain and domain[0]["allowed"] is False
            assert "Multiple registered domains" in domain[0].get("reason", "")

    def test_route_actions_are_cluster_scale_only(self, tmp_path, monkeypatch):
        # Phase 6 emits only roll-up (cluster) targets; no drill/compare yet.
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "doc_sa_4", project="boh")
            r = client.get("/api/fold/node/doc_sa_4")
            assert r.status_code == 200
            for a in r.json()["scale_actions"]:
                assert a["target_scale"] == "cluster"
                assert a["target_axis"] in {"project", "plane", "domain"}

    def test_route_default_project_value_surfaces(self, tmp_path, monkeypatch):
        # docs.project has a default; a doc inserted without project still rolls up.
        with _client(tmp_path, monkeypatch) as (client, db, _):
            _insert_doc(db, "doc_sa_5")
            r = client.get("/api/fold/node/doc_sa_5")
            assert r.status_code == 200
            proj = [a for a in r.json()["scale_actions"] if a["target_axis"] == "project"]
            assert proj and proj[0]["allowed"] is True
            assert proj[0]["target_id"].startswith("project:")
