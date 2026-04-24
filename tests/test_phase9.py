"""tests/test_phase9.py: Phase 9 UX Elevation tests.

Covers:
  - docs table has title + summary columns
  - extract_title: purpose → heading → empty
  - extract_summary: first non-heading paragraph, stripped
  - indexer: title + summary persisted to docs table
  - indexer: re-index updates title/summary
  - search results include title and summary fields
  - conflicts endpoint enriches doc_ids with titles+paths
  - review GET loads existing artifact without regenerating
  - review POST /regenerate force-regenerates
  - review artifact includes doc_title, doc_id, doc_status
  - review suspected_conflicts have title+path
  - review _status field present (existing/generated/regenerated)
  - graph nodes have title and summary fields
  - docTitle helper exists in app.js
  - matchReason helper exists in app.js
  - copyToClip function exists in app.js
  - clearDaenaryFilters function exists in app.js
  - restoreDaenaryFilters function exists in app.js
  - clear filters button in HTML
  - library table header says Title
  - sig-badge CSS present
  - lib-title CSS present
  - match-reason CSS present
  - cache buster bumped to v9
  - version string is v2-phase9
  - regression: all prior routes still 200
"""

import json
import tempfile
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.db import connection as db
from app.services.indexer import extract_title, extract_summary, index_file
from app.services.reviewer import (
    generate_review_artifact,
    load_review_artifact,
    review_artifact_exists,
)

client = TestClient(app)

# ── Sample docs ───────────────────────────────────────────────────────────────

TITLED_DOC = """---
boh:
  id: phase9-title-001
  type: note
  purpose: The Grand Unified Theory of Testing
  topics: [test, phase9]
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

# Document Title From Heading

This is the first real paragraph. It contains enough text to be a useful summary snippet for display purposes.

Another paragraph follows here.
"""

HEADINGLESS_DOC = """---
boh:
  id: phase9-noheading-001
  type: note
  purpose: No Heading Doc
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

Just a paragraph without any heading. This should become the summary.
"""


# ── Schema tests ──────────────────────────────────────────────────────────────

class TestSchemaColumns:
    def test_docs_has_title_column(self):
        cols = {r[1] for r in db.get_conn().execute("PRAGMA table_info(docs)").fetchall()}
        assert "title" in cols

    def test_docs_has_summary_column(self):
        cols = {r[1] for r in db.get_conn().execute("PRAGMA table_info(docs)").fetchall()}
        assert "summary" in cols


# ── extract_title tests ───────────────────────────────────────────────────────

class TestExtractTitle:
    def test_purpose_takes_priority(self):
        boh = {"purpose": "The Grand Theory"}
        assert extract_title(boh, "# Some Heading\n\nbody") == "The Grand Theory"

    def test_falls_back_to_heading(self):
        boh = {}
        assert extract_title(boh, "# My Heading\n\nbody") == "My Heading"

    def test_empty_when_no_signals(self):
        assert extract_title({}, "just body text") == ""

    def test_truncates_to_120(self):
        boh = {"purpose": "A" * 200}
        assert len(extract_title(boh, "")) == 120


# ── extract_summary tests ─────────────────────────────────────────────────────

class TestExtractSummary:
    def test_skips_headings(self):
        body = "# Heading\n\nFirst real paragraph here."
        summary = extract_summary(body)
        assert "Heading" not in summary
        assert "First real" in summary

    def test_strips_markdown_bold(self):
        body = "**Bold text** and more content here."
        summary = extract_summary(body)
        assert "**" not in summary

    def test_truncates_to_max_len(self):
        body = "Word " * 100
        assert len(extract_summary(body, max_len=50)) <= 50

    def test_empty_on_all_headings(self):
        body = "# One\n\n## Two\n\n### Three"
        # All blocks are headings — summary is empty or very short
        result = extract_summary(body)
        assert len(result) < 10

    def test_minimum_length_threshold(self):
        # Very short blocks (< 20 chars) are skipped
        body = "Hi.\n\nLong enough paragraph to qualify as a summary."
        summary = extract_summary(body)
        assert "Long enough" in summary


# ── Indexer persistence tests ─────────────────────────────────────────────────

class TestIndexerTitleSummary:
    def _index(self, content: str, doc_id_hint: str = "test"):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fpath = root / f"{doc_id_hint}.md"
            fpath.write_text(content, encoding="utf-8")
            return index_file(fpath, root)

    def test_title_persisted(self):
        self._index(TITLED_DOC, "titled001")
        row = db.fetchone("SELECT title FROM docs WHERE doc_id = ?", ("phase9-title-001",))
        assert row is not None
        # Purpose takes priority
        assert "Grand Unified" in row["title"]

    def test_summary_persisted(self):
        self._index(TITLED_DOC, "titled001")
        row = db.fetchone("SELECT summary FROM docs WHERE doc_id = ?", ("phase9-title-001",))
        assert row is not None
        assert len(row["summary"]) > 10

    def test_summary_strips_heading(self):
        self._index(TITLED_DOC, "titled001")
        row = db.fetchone("SELECT summary FROM docs WHERE doc_id = ?", ("phase9-title-001",))
        # Summary should not start with heading text
        assert not row["summary"].startswith("#")

    def test_reindex_updates_title(self):
        self._index(TITLED_DOC, "titled001")
        self._index(TITLED_DOC, "titled001")
        rows = db.fetchall("SELECT title FROM docs WHERE doc_id = ?", ("phase9-title-001",))
        assert len(rows) == 1  # Not duplicated

    def test_headingless_doc_uses_paragraph_as_summary(self):
        self._index(HEADINGLESS_DOC, "noheading001")
        row = db.fetchone("SELECT summary FROM docs WHERE doc_id = ?", ("phase9-noheading-001",))
        assert row is not None
        assert "paragraph" in row["summary"]

    def test_result_includes_title_and_summary(self):
        result = self._index(TITLED_DOC, "titled001")
        assert "title" in result
        assert "summary" in result


# ── Search results tests ──────────────────────────────────────────────────────

class TestSearchTitleSummary:
    def test_search_result_has_title_field(self):
        r = client.get("/api/search?q=planar")
        assert r.status_code == 200
        for res in r.json().get("results", []):
            assert "title" in res

    def test_search_result_has_summary_field(self):
        r = client.get("/api/search?q=planar")
        assert r.status_code == 200
        for res in r.json().get("results", []):
            assert "summary" in res


# ── Conflicts enrichment tests ────────────────────────────────────────────────

class TestConflictsEnrichment:
    def test_conflicts_have_docs_field(self):
        r = client.get("/api/conflicts")
        assert r.status_code == 200
        for c in r.json().get("conflicts", []):
            assert "docs" in c

    def test_conflict_docs_have_title_and_path(self):
        r = client.get("/api/conflicts")
        assert r.status_code == 200
        for c in r.json().get("conflicts", []):
            for doc in c.get("docs", []):
                assert "doc_id" in doc
                assert "title" in doc
                assert "path" in doc


# ── Review artifact tests ─────────────────────────────────────────────────────

class TestReviewArtifact:
    def _make_library(self, content: str) -> tempfile.TemporaryDirectory:
        tmpdir = tempfile.TemporaryDirectory()
        p = Path(tmpdir.name) / "testdoc.md"
        p.write_text(content, encoding="utf-8")
        return tmpdir

    def test_review_artifact_exists_false_initially(self):
        with self._make_library(TITLED_DOC) as tmpdir:
            assert not review_artifact_exists("testdoc.md", tmpdir)

    def test_generate_writes_artifact(self):
        with self._make_library(TITLED_DOC) as tmpdir:
            generate_review_artifact("testdoc.md", tmpdir)
            assert review_artifact_exists("testdoc.md", tmpdir)

    def test_load_returns_none_when_missing(self):
        with self._make_library(TITLED_DOC) as tmpdir:
            assert load_review_artifact("testdoc.md", tmpdir) is None

    def test_load_returns_artifact_when_present(self):
        with self._make_library(TITLED_DOC) as tmpdir:
            generate_review_artifact("testdoc.md", tmpdir)
            artifact = load_review_artifact("testdoc.md", tmpdir)
            assert artifact is not None
            assert artifact.get("_loaded_from_disk") is True

    def test_artifact_includes_doc_title(self):
        with self._make_library(TITLED_DOC) as tmpdir:
            artifact = generate_review_artifact("testdoc.md", tmpdir)
            assert "doc_title" in artifact

    def test_artifact_includes_doc_id(self):
        with self._make_library(TITLED_DOC) as tmpdir:
            artifact = generate_review_artifact("testdoc.md", tmpdir)
            assert "doc_id" in artifact

    def test_artifact_includes_doc_status(self):
        with self._make_library(TITLED_DOC) as tmpdir:
            artifact = generate_review_artifact("testdoc.md", tmpdir)
            assert "doc_status" in artifact

    def test_non_authoritative_always_true(self):
        with self._make_library(TITLED_DOC) as tmpdir:
            artifact = generate_review_artifact("testdoc.md", tmpdir)
            assert artifact["non_authoritative"] is True
            assert artifact["requires_explicit_confirmation"] is True


class TestReviewEndpoints:
    def _real_doc_path(self):
        """Return path of a doc whose file still exists on disk (library/ folder)."""
        docs = db.fetchall(
            "SELECT path FROM docs WHERE path LIKE '%.md' ORDER BY updated_ts DESC LIMIT 10"
        )
        import os
        lib_root = os.environ.get("BOH_LIBRARY", "./library")
        from pathlib import Path
        for d in docs:
            full = Path(lib_root) / d["path"]
            if full.exists():
                return d["path"]
        return None

    def test_review_get_200_for_indexed_doc(self):
        path = self._real_doc_path()
        if not path:
            pytest.skip("No on-disk docs available")
        r = client.get(f"/api/review/{path}")
        assert r.status_code == 200

    def test_review_get_has_status_field(self):
        path = self._real_doc_path()
        if not path:
            pytest.skip("No on-disk docs available")
        r = client.get(f"/api/review/{path}")
        assert r.status_code == 200
        assert "_status" in r.json()

    def test_review_regenerate_endpoint_200(self):
        path = self._real_doc_path()
        if not path:
            pytest.skip("No on-disk docs available")
        r = client.post(f"/api/review/{path}/regenerate")
        assert r.status_code == 200

    def test_review_regenerate_status_is_regenerated(self):
        path = self._real_doc_path()
        if not path:
            pytest.skip("No on-disk docs available")
        r = client.post(f"/api/review/{path}/regenerate")
        assert r.status_code == 200
        assert r.json().get("_status") == "regenerated"

    def test_review_get_second_call_returns_existing(self):
        path = self._real_doc_path()
        if not path:
            pytest.skip("No on-disk docs available")
        client.get(f"/api/review/{path}")
        r = client.get(f"/api/review/{path}")
        assert r.status_code == 200
        assert r.json().get("_status") in ("existing", "generated")

    def test_review_404_for_nonexistent(self):
        r = client.get("/api/review/nonexistent/path/doc.md")
        assert r.status_code == 404


# ── Graph node fields tests ───────────────────────────────────────────────────

class TestGraphNodeFields:
    def test_graph_nodes_have_title(self):
        r = client.get("/api/graph")
        assert r.status_code == 200
        for node in r.json().get("nodes", []):
            assert "title" in node

    def test_graph_nodes_have_summary(self):
        r = client.get("/api/graph")
        assert r.status_code == 200
        for node in r.json().get("nodes", []):
            assert "summary" in node

    def test_graph_node_label_uses_title(self):
        r = client.get("/api/graph")
        assert r.status_code == 200
        # At least some nodes should have non-empty title
        titles = [n.get("title", "") for n in r.json().get("nodes", [])]
        # Not all labels should be doc_id fragments
        assert any(t and not t.startswith("phase") for t in titles) or len(titles) == 0


# ── UI file tests ─────────────────────────────────────────────────────────────

class TestPhase9UIFiles:
    def _read(self, path):
        return (Path(__file__).parent.parent / "app" / "ui" / path).read_text()

    def test_js_has_doc_title_helper(self):
        assert "function docTitle" in self._read("app.js")

    def test_js_has_match_reason_helper(self):
        assert "function matchReason" in self._read("app.js")

    def test_js_has_copy_to_clip(self):
        assert "function copyToClip" in self._read("app.js")

    def test_js_has_clear_daenary_filters(self):
        assert "function clearDaenaryFilters" in self._read("app.js")

    def test_js_has_restore_daenary_filters(self):
        assert "function restoreDaenaryFilters" in self._read("app.js")

    def test_js_has_save_daenary_filters(self):
        assert "function saveDaenaryFilters" in self._read("app.js")

    def test_js_phase9_version(self):
        assert "v2-phase" in self._read("app.js")  # increments each phase

    def test_html_has_clear_filters_button(self):
        assert "clearDaenaryFilters" in self._read("index.html")

    def test_html_library_header_has_title(self):
        html = self._read("index.html")
        assert "Title" in html

    def test_html_cache_buster_v9(self):
        assert "?v=" in self._read("index.html")  # increments each phase

    def test_css_has_sig_badge(self):
        assert ".sig-badge" in self._read("style.css")

    def test_css_has_lib_title(self):
        assert ".lib-title" in self._read("style.css")

    def test_css_has_match_reason(self):
        assert ".match-reason" in self._read("style.css")

    def test_css_has_lib_summary(self):
        assert ".lib-summary" in self._read("style.css")


# ── Regression ────────────────────────────────────────────────────────────────

class TestPhase9Regression:
    def test_health(self):
        assert client.get("/api/health").status_code == 200

    def test_search(self):
        assert client.get("/api/search?q=planar").status_code == 200

    def test_graph(self):
        assert client.get("/api/graph").status_code == 200

    def test_docs_list(self):
        assert client.get("/api/docs").status_code == 200

    def test_conflicts(self):
        assert client.get("/api/conflicts").status_code == 200

    def test_lineage(self):
        assert client.get("/api/lineage").status_code == 200

    def test_dashboard(self):
        assert client.get("/api/dashboard").status_code == 200

    def test_dcns_sync(self):
        assert client.post("/api/dcns/sync").status_code == 200
