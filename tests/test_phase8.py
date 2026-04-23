"""tests/test_phase8.py: Phase 8 tests — Daenary + DCNS + drawer viewer.

Covers:
  - parse_frontmatter_full: boh+daenary extraction
  - daenary.validate_dimension: all lint codes
  - daenary.extract_coordinates: normalization + skipping malformed
  - daenary.format_coordinate_summary
  - indexer: daenary coordinates persisted after index_file
  - indexer: re-index replaces coordinate rows
  - indexer: malformed daenary — lint warning, doc still indexed
  - search API: dimension filter
  - search API: state filter
  - search API: min_confidence filter
  - search API: uncertain_only filter
  - search API: stale filter (mocked)
  - search API: conflicts_only filter
  - search API: daenary_adjustment in score_breakdown
  - search API: old search still works without filters
  - graph API: node payload has DCNS diagnostic fields
  - doc_edges table exists
  - dcns.sync_edges: runs without error
  - coordinates API endpoint: 200 for known doc
  - coordinates API endpoint: 404 for unknown doc
  - drawer viewer: /api/docs/{id}/content still works
  - HTML: drawer viewer section present
  - HTML: search daenary filter panel present
  - JS: setDrawerMode function present
  - JS: renderDocBodyInto function present
  - JS: loadDocPayload function present
  - CSS: drawer-reader-content style present
  - API: /api/dcns/sync endpoint returns 200
"""

import json
import time
import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.db import connection as db
from app.services.parser import parse_frontmatter_full
from app.core.daenary import (
    validate_dimension,
    validate_daenary_block,
    extract_coordinates,
    normalize_dimension,
    format_coordinate_summary,
    is_stale,
)

client = TestClient(app)

# ── Fixtures ──────────────────────────────────────────────────────────────────

VALID_DAENARY_DOC = """---
boh:
  id: test-daenary-001
  type: note
  purpose: Daenary test doc
  topics:
    - test
    - daenary
  status: draft
  version: "0.1.0"
  updated: "2026-04-23T00:00:00Z"
  scope:
    plane_scope: []
    field_scope: []
    node_scope: []
  rubrix:
    operator_state: observe
    operator_intent: capture

daenary:
  dimensions:
    - name: relevance
      state: 0
      quality: 0.8
      confidence: 0.3
      mode: contain
      observed_at: "2026-04-23T00:00:00Z"
      valid_until: "2026-05-01T00:00:00Z"

    - name: canon_alignment
      state: 1
      quality: 0.9
      confidence: 0.85
      observed_at: "2026-04-23T00:00:00Z"
---

# Test Document

This is a test document with Daenary coordinates.
"""

MALFORMED_DAENARY_DOC = """---
boh:
  id: test-daenary-002
  type: note
  purpose: Malformed daenary doc
  topics: [test]
  status: draft
  version: "0.1.0"
  updated: "2026-04-23T00:00:00Z"
  scope:
    plane_scope: []
    field_scope: []
    node_scope: []
  rubrix:
    operator_state: observe
    operator_intent: capture

daenary:
  dimensions:
    - name: relevance
      state: 99
      quality: 2.5
      confidence: -0.1
      mode: contain
---

# Malformed Daenary Document
"""

NO_DAENARY_DOC = """---
boh:
  id: test-nodaenary-001
  type: note
  purpose: No daenary doc
  topics: [test]
  status: draft
  version: "0.1.0"
  updated: "2026-04-23T00:00:00Z"
  scope:
    plane_scope: []
    field_scope: []
    node_scope: []
  rubrix:
    operator_state: observe
    operator_intent: capture
---

# No Daenary

This document has no daenary block.
"""


# ── Parser tests ──────────────────────────────────────────────────────────────

class TestParseFrontmatterFull:
    def test_returns_four_tuple(self):
        boh, raw, body, errors = parse_frontmatter_full(VALID_DAENARY_DOC)
        assert boh is not None
        assert isinstance(raw, dict)
        assert isinstance(body, str)
        assert isinstance(errors, list)

    def test_boh_subtree_extracted(self):
        boh, raw, body, errors = parse_frontmatter_full(VALID_DAENARY_DOC)
        assert boh["id"] == "test-daenary-001"

    def test_raw_header_preserves_daenary(self):
        boh, raw, body, errors = parse_frontmatter_full(VALID_DAENARY_DOC)
        assert "daenary" in raw
        assert "dimensions" in raw["daenary"]

    def test_body_stripped(self):
        boh, raw, body, errors = parse_frontmatter_full(VALID_DAENARY_DOC)
        assert "---" not in body.split("\n")[0]
        assert "Test Document" in body

    def test_no_daenary_block(self):
        boh, raw, body, errors = parse_frontmatter_full(NO_DAENARY_DOC)
        assert boh is not None
        assert "daenary" not in raw

    def test_missing_header_returns_none_boh(self):
        boh, raw, body, errors = parse_frontmatter_full("No frontmatter here")
        assert boh is None
        assert any("LINT_MISSING_HEADER" in e for e in errors)


# ── Daenary validation tests ──────────────────────────────────────────────────

class TestValidateDimension:
    def test_valid_dimension_no_warnings(self):
        dim = {"name": "relevance", "state": 0, "quality": 0.8, "confidence": 0.3, "mode": "contain"}
        assert validate_dimension(dim) == []

    def test_invalid_state(self):
        dim = {"name": "relevance", "state": 99}
        warnings = validate_dimension(dim)
        assert "LINT_INVALID_DAENARY_STATE" in warnings

    def test_invalid_quality_out_of_range(self):
        dim = {"name": "relevance", "state": 1, "quality": 2.5}
        warnings = validate_dimension(dim)
        assert "LINT_INVALID_DAENARY_QUALITY" in warnings

    def test_invalid_confidence_negative(self):
        dim = {"name": "relevance", "state": 1, "confidence": -0.1}
        warnings = validate_dimension(dim)
        assert "LINT_INVALID_DAENARY_CONFIDENCE" in warnings

    def test_mode_on_nonzero_state(self):
        dim = {"name": "relevance", "state": 1, "mode": "contain"}
        warnings = validate_dimension(dim)
        assert "LINT_INVALID_DAENARY_MODE" in warnings

    def test_invalid_mode_value(self):
        dim = {"name": "relevance", "state": 0, "mode": "explode"}
        warnings = validate_dimension(dim)
        assert "LINT_INVALID_DAENARY_MODE" in warnings

    def test_invalid_timestamp(self):
        dim = {"name": "relevance", "state": 1, "observed_at": "not-a-date"}
        warnings = validate_dimension(dim)
        assert "LINT_INVALID_DAENARY_TIMESTAMP" in warnings

    def test_positive_state_no_mode(self):
        dim = {"name": "canon_alignment", "state": 1, "quality": 0.9, "confidence": 0.85}
        assert validate_dimension(dim) == []


class TestExtractCoordinates:
    def test_valid_doc_returns_coords(self):
        _, raw, _, _ = parse_frontmatter_full(VALID_DAENARY_DOC)
        coords, warnings = extract_coordinates(raw.get("daenary"))
        assert len(coords) == 2
        assert coords[0]["dimension"] == "relevance"
        assert coords[1]["dimension"] == "canon_alignment"

    def test_state_normalization(self):
        _, raw, _, _ = parse_frontmatter_full(VALID_DAENARY_DOC)
        coords, _ = extract_coordinates(raw.get("daenary"))
        assert all(c["state"] in {-1, 0, 1} for c in coords)

    def test_mode_null_for_nonzero(self):
        _, raw, _, _ = parse_frontmatter_full(VALID_DAENARY_DOC)
        coords, _ = extract_coordinates(raw.get("daenary"))
        canon = next(c for c in coords if c["dimension"] == "canon_alignment")
        assert canon["mode"] is None

    def test_malformed_skipped_not_indexed(self):
        _, raw, _, _ = parse_frontmatter_full(MALFORMED_DAENARY_DOC)
        coords, warnings = extract_coordinates(raw.get("daenary"))
        # state=99 → normalize_dimension returns None → skipped
        assert len(coords) == 0

    def test_no_daenary_returns_empty(self):
        _, raw, _, _ = parse_frontmatter_full(NO_DAENARY_DOC)
        coords, warnings = extract_coordinates(raw.get("daenary"))
        assert coords == []
        assert warnings == []

    def test_dimension_name_lowercased(self):
        daenary = {"dimensions": [{"name": "RELEVANCE", "state": 1}]}
        coords, _ = extract_coordinates(daenary)
        assert coords[0]["dimension"] == "relevance"


class TestFormatCoordinateSummary:
    def test_basic_summary(self):
        coords = [{"dimension": "relevance", "state": 0, "quality": 0.8,
                   "confidence": 0.3, "mode": "contain", "valid_until_ts": None}]
        s = format_coordinate_summary(coords)
        assert "relevance" in s
        assert "0" in s

    def test_positive_state_has_plus(self):
        coords = [{"dimension": "align", "state": 1, "quality": 0.9,
                   "confidence": 0.85, "mode": None, "valid_until_ts": None}]
        s = format_coordinate_summary(coords)
        assert "+1" in s

    def test_stale_flag(self):
        coords = [{"dimension": "old", "state": 1, "quality": 0.5,
                   "confidence": 0.5, "mode": None,
                   "valid_until_ts": int(time.time()) - 3600}]
        s = format_coordinate_summary(coords)
        assert "stale" in s


class TestIsStale:
    def test_no_valid_until_not_stale(self):
        assert not is_stale({"valid_until_ts": None})

    def test_future_valid_until_not_stale(self):
        assert not is_stale({"valid_until_ts": int(time.time()) + 3600})

    def test_past_valid_until_is_stale(self):
        assert is_stale({"valid_until_ts": int(time.time()) - 3600})


# ── Indexer integration tests ─────────────────────────────────────────────────

class TestIndexerDaenary:
    def _index_doc(self, content: str, doc_id: str = None):
        """Helper: write temp file and index it."""
        import tempfile, os
        from pathlib import Path
        from app.services.indexer import index_file

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fname = f"{doc_id or 'test'}.md"
            fpath = root / fname
            fpath.write_text(content, encoding="utf-8")
            return index_file(fpath, root)

    def test_valid_daenary_creates_coordinates(self):
        result = self._index_doc(VALID_DAENARY_DOC, "daenary-001")
        assert result["indexed"] is True
        assert result.get("daenary_coordinates") == 2

    def test_coordinates_queryable_after_index(self):
        self._index_doc(VALID_DAENARY_DOC, "daenary-001")
        rows = db.fetchall(
            "SELECT * FROM doc_coordinates WHERE doc_id = ?", ("test-daenary-001",)
        )
        assert len(rows) >= 1
        dims = {r["dimension"] for r in rows}
        assert "relevance" in dims
        assert "canon_alignment" in dims

    def test_reindex_replaces_old_rows(self):
        self._index_doc(VALID_DAENARY_DOC, "daenary-001")
        self._index_doc(VALID_DAENARY_DOC, "daenary-001")
        rows = db.fetchall(
            "SELECT * FROM doc_coordinates WHERE doc_id = ?", ("test-daenary-001",)
        )
        assert len(rows) == 2  # not 4

    def test_malformed_daenary_still_indexes_doc(self):
        result = self._index_doc(MALFORMED_DAENARY_DOC, "daenary-002")
        assert result["indexed"] is True

    def test_malformed_daenary_produces_lint_warnings(self):
        result = self._index_doc(MALFORMED_DAENARY_DOC, "daenary-002")
        assert any("LINT_INVALID_DAENARY" in e for e in result.get("lint_errors", []))

    def test_no_daenary_doc_unchanged(self):
        result = self._index_doc(NO_DAENARY_DOC, "nodaenary-001")
        assert result["indexed"] is True
        assert result.get("daenary_coordinates", 0) == 0


# ── Search API tests ──────────────────────────────────────────────────────────

class TestSearchDaenaryFilters:
    def test_basic_search_still_works(self):
        r = client.get("/api/search?q=planar")
        assert r.status_code == 200
        data = r.json()
        assert "results" in data
        assert "score_formula" in data

    def test_score_breakdown_has_daenary_adjustment(self):
        r = client.get("/api/search?q=planar")
        assert r.status_code == 200
        results = r.json().get("results", [])
        # adjustment key should be present (0.0 when no coordinates)
        for res in results:
            assert "daenary_adjustment" in res.get("score_breakdown", {})

    def test_dimension_filter_param_accepted(self):
        r = client.get("/api/search?q=planar&dimension=relevance")
        assert r.status_code == 200

    def test_state_filter_param_accepted(self):
        r = client.get("/api/search?q=planar&state=0")
        assert r.status_code == 200

    def test_min_confidence_filter_accepted(self):
        r = client.get("/api/search?q=planar&min_confidence=0.5")
        assert r.status_code == 200

    def test_uncertain_only_filter_accepted(self):
        r = client.get("/api/search?q=planar&uncertain_only=true")
        assert r.status_code == 200

    def test_stale_filter_accepted(self):
        r = client.get("/api/search?q=planar&stale=true")
        assert r.status_code == 200

    def test_conflicts_only_filter_accepted(self):
        r = client.get("/api/search?q=planar&conflicts_only=true")
        assert r.status_code == 200

    def test_daenary_filters_in_response(self):
        r = client.get("/api/search?q=planar&dimension=relevance&state=0")
        assert r.status_code == 200
        data = r.json()
        # daenary_filters key present when filters are active
        assert "daenary_filters" in data

    def test_no_filters_daenary_filters_none(self):
        r = client.get("/api/search?q=planar")
        assert r.status_code == 200
        data = r.json()
        assert data.get("daenary_filters") is None


# ── Graph API tests ───────────────────────────────────────────────────────────

class TestGraphDCNS:
    def test_graph_200(self):
        r = client.get("/api/graph")
        assert r.status_code == 200

    def test_graph_has_nodes_and_edges_keys(self):
        r = client.get("/api/graph")
        data = r.json()
        assert "nodes" in data
        assert "edges" in data

    def test_nodes_have_dcns_fields(self):
        r = client.get("/api/graph")
        nodes = r.json().get("nodes", [])
        for node in nodes:
            assert "loadScore" in node
            assert "conflictCount" in node
            assert "expiredCoordinates" in node
            assert "uncertainCoordinates" in node

    def test_doc_edges_table_exists(self):
        rows = db.fetchall("SELECT name FROM sqlite_master WHERE type='table' AND name='doc_edges'")
        assert len(rows) == 1

    def test_doc_coordinates_table_exists(self):
        rows = db.fetchall("SELECT name FROM sqlite_master WHERE type='table' AND name='doc_coordinates'")
        assert len(rows) == 1


# ── Coordinates API tests ─────────────────────────────────────────────────────

class TestCoordinatesEndpoint:
    def test_coordinates_200_for_known_doc(self):
        docs = db.fetchall("SELECT doc_id FROM docs LIMIT 1")
        if not docs:
            pytest.skip("No documents indexed")
        doc_id = docs[0]["doc_id"]
        r = client.get(f"/api/docs/{doc_id}/coordinates")
        assert r.status_code == 200
        data = r.json()
        assert "coordinates" in data
        assert "count" in data
        assert data["doc_id"] == doc_id

    def test_coordinates_404_for_unknown_doc(self):
        r = client.get("/api/docs/nonexistent-doc-xyz/coordinates")
        assert r.status_code == 404


# ── DCNS sync endpoint ────────────────────────────────────────────────────────

class TestDCNSSync:
    def test_dcns_sync_200(self):
        r = client.post("/api/dcns/sync")
        assert r.status_code == 200

    def test_dcns_sync_returns_summary(self):
        r = client.post("/api/dcns/sync")
        data = r.json()
        assert data.get("status") == "ok"
        assert "edges_written" in data
        assert "total_candidates" in data


# ── UI file smoke tests ───────────────────────────────────────────────────────

class TestPhase8UIFiles:
    def _read(self, path):
        from pathlib import Path
        return (Path(__file__).parent.parent / "app" / "ui" / path).read_text()

    def test_html_has_drawer_viewer_section(self):
        # Drawer viewer HTML is injected by openDrawer() in app.js, not static HTML.
        # Verify the JS contains the drawer viewer element IDs.
        js = self._read("app.js")
        assert "drawer-reader-content" in js
        assert "drawer-reader-related" in js
        assert "drawer-reader-toggle" in js

    def test_html_has_daenary_search_panel(self):
        html = self._read("index.html")
        assert "sf-dimension" in html
        assert "sf-state" in html
        assert "sf-uncertain" in html
        assert "sf-stale" in html
        assert "sf-conflicts" in html

    def test_html_legend_has_dcns_indicators(self):
        html = self._read("index.html")
        assert "Conflict" in html or "conflict" in html.lower()
        assert "Stale" in html or "stale" in html.lower()

    def test_js_has_set_drawer_mode(self):
        js = self._read("app.js")
        assert "setDrawerMode" in js

    def test_js_has_render_doc_body_into(self):
        js = self._read("app.js")
        assert "renderDocBodyInto" in js

    def test_js_has_load_doc_payload(self):
        js = self._read("app.js")
        assert "loadDocPayload" in js

    def test_js_has_render_related_into(self):
        js = self._read("app.js")
        assert "renderRelatedInto" in js

    def test_js_phase8_version(self):
        js = self._read("app.js")
        assert "v2-phase8" in js

    def test_css_has_drawer_reader_content(self):
        css = self._read("style.css")
        assert "drawer-reader-content" in css

    def test_css_has_coord_badge(self):
        css = self._read("style.css")
        assert "coord-badge" in css

    def test_css_has_daenary_summary(self):
        css = self._read("style.css")
        assert "daenary-summary" in css

    def test_cache_buster_v8(self):
        html = self._read("index.html")
        assert "?v=8" in html


# ── Regression: prior routes still work ──────────────────────────────────────

class TestPhase8Regression:
    def test_health(self):
        assert client.get("/api/health").status_code == 200

    def test_dashboard(self):
        assert client.get("/api/dashboard").status_code == 200

    def test_conflicts(self):
        assert client.get("/api/conflicts").status_code == 200

    def test_lineage(self):
        assert client.get("/api/lineage").status_code == 200

    def test_docs_list(self):
        assert client.get("/api/docs").status_code == 200

    def test_graph(self):
        assert client.get("/api/graph").status_code == 200

    def test_search_basic(self):
        assert client.get("/api/search?q=test").status_code == 200
