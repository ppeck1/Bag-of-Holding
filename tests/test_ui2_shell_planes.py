"""Static source assertions for the v2 shell simplification and plane-visibility filter.

Confirms:
- Scope chip removed; Library chip + Planes chip present in shell.js
- ScopeTree and scopeTree are gone
- normalizePlaneKey exported from ns.js
- state.scope removed from app.js; visiblePlanes added
- fold.js uses visiblePlanes, no scope prop, active-library breadcrumb
- library.js imports normalizePlaneKey, has plane-filtered empty state and count line
- DocumentsTab does NOT reference visiblePlanes (filter is CardsTab-only)
"""

from pathlib import Path

REPO = Path(__file__).parent.parent
NS_JS       = REPO / "app/ui2/js/ns.js"
SHELL_JS    = REPO / "app/ui2/js/shell.js"
APP_JS      = REPO / "app/ui2/js/app.js"
FIXTURES_JS = REPO / "app/ui2/js/fixtures.js"
FOLD_JS     = REPO / "app/ui2/js/screens/fold.js"
LIBRARY_JS  = REPO / "app/ui2/js/screens/library.js"
OVERVIEW_JS = REPO / "app/ui2/js/screens/overview.js"
STATUS_JS   = REPO / "app/ui2/js/screens/status.js"
APP_CSS     = REPO / "app/ui2/app.css"

def _src(path):
    return path.read_text(encoding="utf-8")


class TestNormalizePlaneKey:
    def test_exported_from_ns(self):
        assert "export function normalizePlaneKey" in _src(NS_JS)

    def test_lowercases_and_trims(self):
        # Confirm the function body handles case and whitespace
        src = _src(NS_JS)
        assert "toLowerCase" in src
        assert "trim" in src


class TestShellSimplification:
    def test_scope_chip_removed(self):
        assert "Scope:" not in _src(SHELL_JS)

    def test_scope_tree_removed(self):
        src = _src(SHELL_JS)
        assert "ScopeTree" not in src
        assert "scopeTree" not in src

    def test_library_selector_present(self):
        src = _src(SHELL_JS)
        assert "Logical libraries" in src
        assert "Library: ${libraryLabel(activeLibrary, libraries)}" in src
        assert "onSelectLibrary" in src
        assert "Manage libraries" in src
        assert "onManageLibraries" in src

    def test_library_selector_scope_copy(self):
        assert "Browsing filter for Library and Fold Workspace." in _src(SHELL_JS)

    def test_planes_chip_present(self):
        assert "Planes:" in _src(SHELL_JS)

    def test_planes_popover_has_all_plane_keys(self):
        # Keys are in ns.js PLANES dict; shell.js iterates Object.entries(PLANES) dynamically.
        src = _src(NS_JS)
        for key in ["informational", "subjective", "evidence", "internal",
                    "review", "canonical", "conflict", "archive"]:
            assert key in src, f"plane key missing from ns.js PLANES: {key}"

    def test_planes_popover_subtitle(self):
        src = _src(SHELL_JS)
        assert "Browsing visibility only" in src or "Retrieval and authority are unchanged" in src

    def test_show_all_planes_action(self):
        assert "Show all planes" in _src(SHELL_JS)

    def test_planes_import_in_shell(self):
        assert "PLANES" in _src(SHELL_JS)

    def test_scope_not_in_topbar_signature(self):
        # TopBar should no longer accept scope or onScope
        src = _src(SHELL_JS)
        # Find the TopBar function line
        lines = src.splitlines()
        topbar_line = next((l for l in lines if "export function TopBar" in l or "function TopBar" in l), "")
        assert "scope" not in topbar_line


class TestFixturesCleanup:
    def test_scope_tree_removed_from_fixtures(self):
        assert "scopeTree" not in _src(FIXTURES_JS)

    def test_other_fixtures_preserved(self):
        src = _src(FIXTURES_JS)
        for name in ["metrics", "documents", "attention", "jobs", "systemStatus", "overviewCounts"]:
            assert name in src, f"fixture still needed: {name}"


class TestAppStateCleanup:
    def test_scope_removed_from_state(self):
        src = _src(APP_JS)
        assert 'scope: "Project Atlas"' not in src

    def test_state_scope_not_referenced(self):
        assert "state.scope" not in _src(APP_JS)

    def test_visible_planes_in_state(self):
        assert "visiblePlanes" in _src(APP_JS)

    def test_active_library_in_state(self):
        src = _src(APP_JS)
        assert "activeLibraryId" in src
        assert 'api("/api/libraries")' in src
        assert "setActiveLibrary" in src
        assert "libraryId: nextId" in src
        assert "fetchFoldGraph(libraryId)" in src
        assert "state.activeLibraryId || \"all\"" in src
        assert 'api("/api/libraries?include_hidden=true")' in src
        assert 'api("/api/libraries/order"' in src
        assert "tokenHeaders()" in src
        assert "LibraryManagerModal" in src

    def test_toggle_plane_function(self):
        assert "togglePlane" in _src(APP_JS) or "toggle_plane" in _src(APP_JS)

    def test_show_all_planes_function(self):
        assert "showAllPlanes" in _src(APP_JS)

    def test_normalizeplanekey_imported_in_app(self):
        assert "normalizePlaneKey" in _src(APP_JS)

    def test_planes_imported_in_app(self):
        assert "PLANES" in _src(APP_JS)

    def test_modal_dialog_uses_library_not_scope(self):
        src = _src(APP_JS)
        assert '"Library"' in src or "'Library'" in src


class TestOverviewAndStatus:
    def test_overview_no_scope_prop(self):
        src = _src(OVERVIEW_JS)
        # The destructuring should not include 'scope'
        assert "scope," not in src.split("const {")[1].split("}")[0] if "const {" in src else True

    def test_overview_says_bag_of_holding(self):
        assert "Bag of Holding" in _src(OVERVIEW_JS)

    def test_overview_no_for_scope_template(self):
        assert "for ${scope}" not in _src(OVERVIEW_JS)

    def test_status_no_scope_prop(self):
        src = _src(STATUS_JS)
        assert "scope, statusCells" not in src and "{ scope," not in src

    def test_status_says_bag_of_holding(self):
        assert "Bag of Holding" in _src(STATUS_JS)

    def test_status_no_for_scope_template(self):
        assert "for ${scope}" not in _src(STATUS_JS)


class TestFoldFilter:
    def test_normalizeplanekey_imported(self):
        assert "normalizePlaneKey" in _src(FOLD_JS)

    def test_visible_planes_in_signature(self):
        src = _src(FOLD_JS)
        assert "visiblePlanes" in src

    def test_scope_prop_removed(self):
        src = _src(FOLD_JS)
        assert "{ scope," not in src and "scope, data" not in src

    def test_active_library_breadcrumb(self):
        src = _src(FOLD_JS)
        assert "activeLibrary" in src
        assert "libraryName" in src
        assert "All libraries" in src

    def test_corpus_breadcrumb_removed(self):
        assert '"Corpus"' not in _src(FOLD_JS)

    def test_cluster_filtered_count(self):
        # visCount / nd.count pattern must exist for filtered cluster labels
        src = _src(FOLD_JS)
        assert "visCount" in src

    def test_planes_info_chip(self):
        assert "planesInfo" in _src(FOLD_JS) or "Planes:" in _src(FOLD_JS)


class TestLibraryFilter:
    def test_normalizeplanekey_imported(self):
        assert "normalizePlaneKey" in _src(LIBRARY_JS)

    def test_visible_planes_in_signature(self):
        assert "visiblePlanes" in _src(LIBRARY_JS)

    def test_filtered_empty_state(self):
        assert "No PlaneCards in the visible planes" in _src(LIBRARY_JS)

    def test_showing_count_line(self):
        src = _src(LIBRARY_JS)
        assert "Showing" in src and "of" in src and "PlaneCards" in src

    def test_no_planes_tab_added(self):
        # Only CardsTab should reference visiblePlanes, not a new top-level tab
        src = _src(LIBRARY_JS)
        assert 'label: "Planes"' not in src

    def test_documents_tab_not_filtered(self):
        # DocumentsTab function must NOT reference visiblePlanes
        src = _src(LIBRARY_JS)
        docs_start = src.find("function DocumentsTab")
        search_start = src.find("function SearchTab")
        assert docs_start != -1 and search_start != -1
        docs_tab_src = src[docs_start:search_start]
        assert "visiblePlanes" not in docs_tab_src, "DocumentsTab must not be filtered by visiblePlanes"

    def test_search_tab_not_filtered(self):
        # SearchTab function must NOT reference visiblePlanes
        src = _src(LIBRARY_JS)
        search_start = src.find("function SearchTab")
        do_search_start = src.find("function doSearch")
        assert search_start != -1 and do_search_start != -1
        search_tab_src = src[search_start:do_search_start]
        assert "visiblePlanes" not in search_tab_src, "SearchTab must not be filtered by visiblePlanes"

    def test_library_id_filters_library_tabs(self):
        src = _src(LIBRARY_JS)
        assert "activeLibraryId" in src
        assert "libraryParam(activeLibraryId)" in src
        assert "/api/docs?page=" in src
        assert "/api/search?q=" in src
        assert "/api/planes/cards?limit=200" in src


class TestInspectorLayoutFixes:
    """B7 (collapse reclaims width) and B13 (responsive overlay) regression assertions."""

    def test_grid_template_always_set_inline(self):
        # app.js must always pass gridTemplateColumns — not rely on CSS-class-only switching.
        # The closed path ("1fr") and the open path ("1fr 5px Npx") must both be present.
        src = _src(APP_JS)
        assert '"1fr"' in src or "'1fr'" in src, "closed gridTemplateColumns '1fr' must be set inline"
        assert "1fr 5px" in src, "open gridTemplateColumns '1fr 5px Npx' must be set inline"

    def test_with_inspector_css_class_not_sole_grid_control(self):
        # .main.with-inspector must NOT be the only thing controlling grid-template-columns
        # (since inline style in app.js is now authoritative).
        css = _src(APP_CSS)
        # The old `.main.with-inspector { grid-template-columns: ... }` rule must be removed.
        assert ".main.with-inspector" not in css or "grid-template-columns" not in css.split(".main.with-inspector")[1].split("}")[0], \
            ".main.with-inspector must not set grid-template-columns (inline style is authoritative)"

    def test_responsive_media_query_present(self):
        css = _src(APP_CSS)
        assert "@media" in css and "1279px" in css, "responsive @media (max-width: 1279px) rule must be present"

    def test_responsive_forces_single_column(self):
        css = _src(APP_CSS)
        assert "grid-template-columns: 1fr" in css and "!important" in css, \
            "responsive rule must force grid-template-columns: 1fr !important"

    def test_inspector_resize_hidden_in_responsive(self):
        css = _src(APP_CSS)
        assert "inspector-resize" in css and "display: none" in css, \
            "resize handle must be hidden in responsive mode"

    def test_inspector_fixed_in_responsive(self):
        css = _src(APP_CSS)
        assert "position: fixed" in css, "inspector must use position: fixed in responsive mode"

    def test_startresize_targets_main_not_with_inspector(self):
        src = _src(APP_JS)
        # Must query ".main" not ".main.with-inspector" (with-inspector class may not be present at drag time)
        assert '".main.with-inspector"' not in src and "'.main.with-inspector'" not in src, \
            "startResize must query '.main', not '.main.with-inspector'"
        assert '".main"' in src or "'.main'" in src, "startResize must query '.main'"
