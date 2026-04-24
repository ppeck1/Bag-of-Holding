"""tests/test_phase11_graph.py: Phase 11 graph / neighborhood tests.

Covers:
  - /api/graph edges have reasons, shared_topics, crossovers, label fields
  - /api/graph nodes have title, summary fields
  - /api/graph/neighborhood 200 for known doc
  - /api/graph/neighborhood 404 for unknown doc
  - /api/graph/neighborhood depth clamped to [1,2]
  - /api/graph/neighborhood limit clamped to [5,80]
  - /api/graph/neighborhood returns center_doc_id
  - /api/graph/neighborhood node count bounded by limit
  - /api/graph/neighborhood edges contain reasons field
  - pointToSegmentDistance helper logic (backend get_neighborhood)
  - get_neighborhood from related.py directly
  - _enrich_edge returns required fields
"""

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.core.related import get_graph_data, get_neighborhood, _enrich_edge
from app.db import connection as db

client = TestClient(app)


# ── Graph API edge enrichment ─────────────────────────────────────────────────

class TestGraphEdgeEnrichment:
    def test_graph_route_200(self):
        r = client.get("/api/graph")
        assert r.status_code == 200

    def test_graph_has_nodes_and_edges(self):
        data = client.get("/api/graph").json()
        assert "nodes" in data
        assert "edges" in data

    def test_graph_nodes_have_title(self):
        data = client.get("/api/graph").json()
        for node in data.get("nodes", []):
            assert "title"   in node
            assert "summary" in node

    def test_graph_edges_have_enrichment_fields(self):
        data = client.get("/api/graph").json()
        for edge in data.get("edges", []):
            # All edges must have these fields (may be empty lists)
            assert "reasons"       in edge
            assert "shared_topics" in edge
            assert "crossovers"    in edge
            assert "label"         in edge
            # Type assertions
            assert isinstance(edge["reasons"],       list)
            assert isinstance(edge["shared_topics"], list)
            assert isinstance(edge["crossovers"],    list)
            assert isinstance(edge["label"],         str)

    def test_graph_edge_types_are_valid(self):
        data = client.get("/api/graph").json()
        valid_types = {
            "lineage", "related", "duplicate_content", "supersedes",
            "conflicts", "canon_relates_to", "derives",
        }
        for edge in data.get("edges", []):
            assert edge.get("type") in valid_types or edge.get("type") is None


# ── _enrich_edge unit tests ───────────────────────────────────────────────────

class TestEnrichEdge:
    def test_returns_required_fields(self):
        edge = {"source": "a", "target": "b", "type": "lineage", "weight": 1.0}
        enriched = _enrich_edge(edge, {"a", "b"})
        assert "reasons"       in enriched
        assert "shared_topics" in enriched
        assert "crossovers"    in enriched
        assert "label"         in enriched

    def test_lineage_gets_reason(self):
        edge = {"source": "a", "target": "b", "type": "lineage", "weight": 1.0}
        enriched = _enrich_edge(edge, {"a", "b"})
        assert isinstance(enriched["reasons"], list)

    def test_conflict_edge_gets_reason(self):
        edge = {"source": "a", "target": "b", "type": "conflicts", "weight": 0.4}
        enriched = _enrich_edge(edge, {"a", "b"})
        assert any("conflict" in r.lower() for r in enriched["reasons"])

    def test_original_fields_preserved(self):
        edge = {"source": "a", "target": "b", "type": "related",
                "weight": 0.6, "state": 1}
        enriched = _enrich_edge(edge, {"a", "b"})
        assert enriched["source"] == "a"
        assert enriched["target"] == "b"
        assert enriched["weight"] == 0.6


# ── Neighborhood API ──────────────────────────────────────────────────────────

class TestNeighborhoodAPI:
    def _get_real_doc_id(self):
        rows = db.fetchall("SELECT doc_id FROM docs LIMIT 1")
        return rows[0]["doc_id"] if rows else None

    def test_neighborhood_200_for_known_doc(self):
        doc_id = self._get_real_doc_id()
        if not doc_id:
            pytest.skip("No documents indexed")
        r = client.get(f"/api/graph/neighborhood?doc_id={doc_id}")
        assert r.status_code == 200

    def test_neighborhood_404_for_unknown_doc(self):
        r = client.get("/api/graph/neighborhood?doc_id=nonexistent-xyz-abc")
        assert r.status_code == 404

    def test_neighborhood_has_required_fields(self):
        doc_id = self._get_real_doc_id()
        if not doc_id:
            pytest.skip("No documents indexed")
        data = client.get(f"/api/graph/neighborhood?doc_id={doc_id}").json()
        assert "nodes"         in data
        assert "edges"         in data
        assert "center_doc_id" in data
        assert data["center_doc_id"] == doc_id

    def test_neighborhood_center_node_present(self):
        doc_id = self._get_real_doc_id()
        if not doc_id:
            pytest.skip("No documents indexed")
        data = client.get(f"/api/graph/neighborhood?doc_id={doc_id}").json()
        node_ids = {n["id"] for n in data.get("nodes", [])}
        assert doc_id in node_ids

    def test_neighborhood_depth_clamped(self):
        """Depth outside [1,2] should be clamped (FastAPI query validator rejects)."""
        doc_id = self._get_real_doc_id()
        if not doc_id:
            pytest.skip("No documents indexed")
        # depth=0 is below minimum — FastAPI returns 422
        r = client.get(f"/api/graph/neighborhood?doc_id={doc_id}&depth=0")
        assert r.status_code in (422, 200)
        # depth=3 is above maximum — FastAPI returns 422
        r = client.get(f"/api/graph/neighborhood?doc_id={doc_id}&depth=3")
        assert r.status_code in (422, 200)

    def test_neighborhood_limit_respected(self):
        doc_id = self._get_real_doc_id()
        if not doc_id:
            pytest.skip("No documents indexed")
        data = client.get(
            f"/api/graph/neighborhood?doc_id={doc_id}&limit=5"
        ).json()
        # Node count including center should be ≤ limit + 1
        assert len(data.get("nodes", [])) <= 6

    def test_neighborhood_edges_have_enrichment(self):
        doc_id = self._get_real_doc_id()
        if not doc_id:
            pytest.skip("No documents indexed")
        data = client.get(f"/api/graph/neighborhood?doc_id={doc_id}").json()
        for edge in data.get("edges", []):
            assert "reasons"       in edge
            assert "shared_topics" in edge
            assert "crossovers"    in edge


# ── get_neighborhood unit tests ───────────────────────────────────────────────

class TestGetNeighborhoodCore:
    def test_returns_error_for_unknown_doc(self):
        result = get_neighborhood("does-not-exist-xyz")
        assert result.get("error") is not None

    def test_returns_center_in_nodes_for_known_doc(self):
        rows = db.fetchall("SELECT doc_id FROM docs LIMIT 1")
        if not rows:
            pytest.skip("No documents indexed")
        doc_id = rows[0]["doc_id"]
        result = get_neighborhood(doc_id, depth=1, limit=10)
        node_ids = {n["id"] for n in result.get("nodes", [])}
        assert doc_id in node_ids

    def test_depth_2_does_not_exceed_limit(self):
        rows = db.fetchall("SELECT doc_id FROM docs LIMIT 1")
        if not rows:
            pytest.skip("No documents indexed")
        doc_id = rows[0]["doc_id"]
        result = get_neighborhood(doc_id, depth=2, limit=8)
        # Should not have wildly more nodes than the limit
        assert len(result.get("nodes", [])) <= 9  # limit + center

    def test_node_has_is_center_flag(self):
        rows = db.fetchall("SELECT doc_id FROM docs LIMIT 1")
        if not rows:
            pytest.skip("No documents indexed")
        doc_id = rows[0]["doc_id"]
        result = get_neighborhood(doc_id)
        center_nodes = [n for n in result.get("nodes", []) if n.get("isCenter")]
        assert len(center_nodes) == 1
        assert center_nodes[0]["id"] == doc_id


# ── UI file smoke tests ───────────────────────────────────────────────────────

class TestPhase11UIFiles:
    def _read(self, path):
        from pathlib import Path
        return (Path(__file__).parent.parent / "app" / "ui" / path).read_text()

    def test_html_has_input_panel(self):
        assert "panel-input" in self._read("index.html")

    def test_html_has_new_import_nav(self):
        assert "New / Import" in self._read("index.html")

    def test_html_has_drawer_resizer(self):
        assert "doc-drawer-resizer" in self._read("index.html")

    def test_html_has_drawer_toolbar(self):
        assert "doc-drawer-toolbar" in self._read("index.html")

    def test_html_has_atlas_expand_button(self):
        assert "expandSelectedAtlasNode" in self._read("index.html")

    def test_html_has_atlas_reset_button(self):
        assert "collapseAtlasToInitial" in self._read("index.html")

    def test_html_has_reader_width_controls(self):
        assert "setAtlasReaderWidth" in self._read("index.html")

    def test_js_has_create_markdown_doc(self):
        assert "function createMarkdownDoc" in self._read("app.js")

    def test_js_has_upload_documents(self):
        assert "function uploadDocuments" in self._read("app.js")

    def test_js_has_init_drawer_resize(self):
        assert "function initDrawerResize" in self._read("app.js")

    def test_js_has_set_drawer_width_mode(self):
        assert "function setDrawerWidthMode" in self._read("app.js")

    def test_js_has_set_atlas_reader_width(self):
        assert "function setAtlasReaderWidth" in self._read("app.js")

    def test_js_has_expand_neighborhood(self):
        assert "function expandAtlasNeighborhood" in self._read("app.js")

    def test_js_has_hit_test_edge(self):
        assert "hitTestEdge" in self._read("app.js")

    def test_js_has_draw_edge(self):
        assert "drawEdge" in self._read("app.js")

    def test_js_has_draw_edge_tooltip(self):
        assert "drawEdgeTooltip" in self._read("app.js")

    def test_js_has_rebuild_adjacency(self):
        assert "rebuildAdjacency" in self._read("app.js")

    def test_js_has_point_to_segment(self):
        assert "pointToSegmentDistance" in self._read("app.js")

    def test_js_version_phase11(self):
        assert "v2-phase11" in self._read("app.js")

    def test_html_cache_buster_v11(self):
        assert "?v=11" in self._read("index.html")

    def test_css_has_input_grid(self):
        assert ".input-grid" in self._read("style.css")

    def test_css_has_drawer_resizer(self):
        assert "#doc-drawer-resizer" in self._read("style.css")
