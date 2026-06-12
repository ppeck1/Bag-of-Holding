"""tests/test_fold_view_ui.py -- UI acceptance tests for Current Fold View and Graph Lab rename.

Covers:
  - Graph Lab nav label (user-facing rename from Visualization)
  - Current Fold View scatter canvas panel present in HTML
  - Fold Snapshot element present in Graph Lab reader pane
  - Scalar strip labels dimensions, not truth
  - loadFoldLibraryView and canvas rendering functions defined in JS
  - Graph Lab panel still functions (internal route unchanged)
"""

from __future__ import annotations

import re
from pathlib import Path

INDEX_HTML = Path(__file__).parent.parent / "app" / "ui" / "index.html"
APP_JS = Path(__file__).parent.parent / "app" / "ui" / "app.js"


def _html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _js() -> str:
    return APP_JS.read_text(encoding="utf-8")


class TestGraphLabRename:
    def test_nav_label_is_graph_lab(self):
        html = _html()
        assert ">Graph Lab<" in html or "Graph Lab\n" in html

    def test_nav_aria_label_is_graph_lab(self):
        html = _html()
        assert 'aria-label="Graph Lab"' in html

    def test_nav_data_panel_atlas_unchanged(self):
        """Internal panel id must not be renamed."""
        html = _html()
        assert 'data-panel="atlas"' in html

    def test_nav_onclick_atlas_unchanged(self):
        """Internal nav() call must not be renamed."""
        html = _html()
        assert "onclick=\"nav('atlas')\"" in html

    def test_panel_section_id_atlas_unchanged(self):
        html = _html()
        assert 'id="panel-atlas"' in html

    def test_wordmark_says_graph_lab(self):
        html = _html()
        assert "Graph Lab" in html

    def test_no_visualization_in_nav_text(self):
        """The user-facing nav text should no longer say 'Visualization'."""
        html = _html()
        nav_item_block = re.search(
            r'data-panel="atlas"[^>]*>.*?</div>',
            html, re.DOTALL
        )
        assert nav_item_block is not None
        nav_text = nav_item_block.group(0)
        assert "Visualization" not in nav_text


class TestCurrentFoldViewPanel:
    def test_fold_view_panel_present(self):
        html = _html()
        assert 'id="panel-fold-view"' in html

    def test_fold_view_nav_item_present(self):
        html = _html()
        assert 'data-panel="fold-view"' in html

    def test_fold_view_has_scatter_canvas(self):
        """Scatter canvas replaces the old doc-id input form."""
        html = _html()
        assert 'id="fold-view-canvas"' in html

    def test_fold_view_calls_load_fold_library_view(self):
        """Refresh button calls the library batch endpoint, not the old per-doc loader."""
        html = _html()
        assert "loadFoldLibraryView" in html

    def test_load_fold_library_view_function_defined(self):
        js = _js()
        assert "async function loadFoldLibraryView" in js

    def test_fold_label_colors_defined(self):
        js = _js()
        assert "FOLD_LABEL_COLORS" in js

    def test_fold_draw_library_defined(self):
        js = _js()
        assert "_foldDrawLibrary" in js

    def test_fold_hit_test_defined(self):
        js = _js()
        assert "_foldHitTest" in js

    def test_fold_view_fetches_library_api(self):
        js = _js()
        assert "/api/fold/library" in js

    def test_fold_view_shows_compact_trace(self):
        js = _js()
        assert "resolver_trace_summary" in js

    def test_fold_view_shows_unknowns(self):
        js = _js()
        assert "unknowns" in js

    def test_fold_view_fetches_fold_node_api(self):
        js = _js()
        assert "/api/fold/node/" in js

    def test_fold_view_nav_auto_loads(self):
        """nav('fold-view') must trigger loadFoldLibraryView for auto-load."""
        js = _js()
        nav_match = re.search(r"function nav\(panelId\)(.*?)(?=\n(?:async )?function |\n// )", js, re.DOTALL)
        assert nav_match is not None, "nav() function not found"
        assert "fold-view" in nav_match.group(1)
        assert "loadFoldLibraryView" in nav_match.group(1)

    def test_fold_view_detail_panel_present(self):
        html = _html()
        assert 'id="fold-view-detail"' in html

    def test_fold_legend_element_present(self):
        html = _html()
        assert 'id="fold-view-legend"' in html


class TestFoldSnapshot:
    def test_reader_fold_snapshot_element_present(self):
        html = _html()
        assert 'id="reader-fold-snapshot"' in html

    def test_render_fold_snapshot_function_defined(self):
        js = _js()
        assert "async function renderFoldSnapshot" in js

    def test_snapshot_shows_dimensional_pressures_not_truth(self):
        js = _js()
        assert "not truth scores" in js or "dimensional" in js

    def test_snapshot_cleared_on_deselect(self):
        js = _js()
        assert "reader-fold-snapshot" in js
        match = re.search(
            r'function clearVisualizationSelection\(\)(.*?)(?=\n(?:async )?function )',
            js, re.DOTALL
        )
        assert match is not None, "clearVisualizationSelection not found"
        assert "reader-fold-snapshot" in match.group(1)

    def test_snapshot_uses_current_fold_api(self):
        js = _js()
        assert "/api/fold/node/" in js

    def test_snapshot_shows_currentness_label(self):
        js = _js()
        assert "currentness_label" in js

    def test_snapshot_scope_id_is_doc_id(self):
        js = _js()
        assert "scope" in js and "docId" in js


class TestScalarLabelPolicy:
    def test_no_truth_label_in_fold_detail_js(self):
        """Scalar labels in the detail renderer must not claim truth, confidence, or correctness."""
        js = _js()
        section = re.search(
            r'function _foldRenderFullDetail\(.*?\n\}',
            js, re.DOTALL
        )
        if section:
            text = section.group(0)
            assert "Truth:" not in text
            assert "Correctness:" not in text
            assert "Certainty:" not in text

    def test_fold_view_uses_pressure_labels(self):
        js = _js()
        assert "pressure" in js.lower() or "Dimensional" in js

    def test_fold_scalar_bar_uses_pressure_language(self):
        js = _js()
        assert "Authority pressure" in js
        assert "Freshness pressure" in js
