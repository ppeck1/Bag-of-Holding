"""tests/test_ui2_fold.py -- static acceptance for the new UI Fold Workspace (Phase B).

Static text checks (no runtime/DOM), mirroring test_ui2_phase_a.py. Verify the Fold
Workspace module exists, is wired into the router, uses the SVG helper, and reads the
real fold/graph endpoints. Does not touch app/ui (classic) or its tests.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
UI2 = ROOT / "app" / "ui2"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestFoldModule:
    def test_fold_screen_exists_and_exports_workspace(self):
        js = _read(UI2 / "js" / "screens" / "fold.js")
        assert re.search(r"export function FoldWorkspace\b", js)
        for name in ("Web", "Risk Map", "Authority Path", "Currentness Map", "Evidence State", "Timeline"):
            assert f'name: "{name}"' in js or f'"{name}"' in js

    def test_projection_coordinate_branches_are_distinct(self):
        js = _read(UI2 / "js" / "screens" / "fold.js")
        assert 'proj === "risk"' in js
        assert 'proj === "authority"' in js
        assert 'proj === "evidence"' in js
        assert "risk pressure" in js
        assert "authority tier" in js
        assert "plane lanes" in js

    def test_cluster_unfold_keeps_measured_projection_positions(self):
        js = _read(UI2 / "js" / "screens" / "fold.js")
        assert "function radialMemberPos" not in js
        assert "clusterSpread" not in js
        assert "GROUP_MODES" not in js
        assert "Math.cos(angle) * radius" not in js
        assert "Math.sin(angle) * radius" not in js
        assert "function displayPosFor(nd)" in js
        assert "return posFor(nd, st.proj);" in js
        assert "st.expanded.has(cid)" in js
        assert 'type: "wrapped_as", member: true' in js

    def test_view_toolkit_controls_exist(self):
        js = _read(UI2 / "js" / "screens" / "fold.js")
        assert "View toolkit" in js
        assert "LABEL_MODES" in js
        assert "EDGE_MODES" in js
        assert "FOLD_AXES" in js
        assert "clusterAxis" in js
        assert "Folds" in js
        assert "Cluster Focus" in js
        assert "boh_fold_view_v1" in js

    def test_domain_fold_visual_axis_exists(self):
        js = _read(UI2 / "js" / "screens" / "fold.js")
        api = _read(UI2 / "js" / "api.js")
        assert '{ value: "domain", label: "Domain" }' in js
        assert "nodeClusterIds" in js
        assert "foldAxisLabel" in js
        assert 'cluster:domain:' in api
        assert 'addClusterMembership(nd, "domain"' in api
        assert 'fetchFoldCluster("domain", value, activeLibraryId)' in api

    def test_action_queue_view_exists(self):
        js = _read(UI2 / "js" / "screens" / "fold.js")
        assert "function buildActionList" in js
        assert "Action Queue" in js
        assert '{ value: "actions", label: "Actions" }' in js

    def test_svg_helper_present(self):
        dom = _read(UI2 / "js" / "dom.js")
        assert re.search(r"export function hs\b", dom)
        assert "createElementNS" in dom

    def test_api_reads_real_fold_endpoints(self):
        api = _read(UI2 / "js" / "api.js")
        assert "/api/fold/library" in api
        assert "/api/fold/corpus/domain" in api
        assert "/api/graph/projection" in api
        assert "/api/fold/node/" in api
        assert "withLibrary" in api
        assert "library_id=" in api
        assert re.search(r"export function foldCurrentness\b", api)  # 9->5 label adapter
        assert re.search(r"export async function fetchFoldGraph\(activeLibraryId\)", api)
        assert re.search(r"export async function fetchFoldNode\(docId, activeLibraryId\)", api)
        assert re.search(r"export async function fetchFoldCorpus\b", api)

    def test_api_preserves_existing_graph_semantic_fields(self):
        api = _read(UI2 / "js" / "api.js")
        for field in ("epistemicD", "epistemicQ", "epistemicC", "constraintZone", "custodianLane", "authorityState"):
            assert field in api

    def test_fold_inspector_includes_associated_file_preview(self):
        js = _read(UI2 / "js" / "screens" / "fold.js")
        api = _read(UI2 / "js" / "api.js")
        assert 'from "../file-preview.js"' in js
        assert "AssociatedFilePreview" in js
        assert "path: (pk && pk.local_state && pk.local_state.path) || nd.path" in js
        assert "path: d.path || null" in api
        assert "nd.path = n.path || nd.path || null" in api


class TestRouting:
    def test_app_routes_fold_to_workspace(self):
        app = _read(UI2 / "js" / "app.js")
        assert "FoldWorkspace" in app and 'from "./screens/fold.js"' in app
        assert "ensureFold" in app
        # the fold route must render the workspace, not only the placeholder
        assert 'r === "fold"' in app
        assert "return FoldWorkspace(" in app
        assert "activeLibraryId: state.activeLibraryId" in app
        assert "activeLibrary: state.libraries.items.find" in app


class TestImportIntegrity:
    def test_relative_imports_resolve(self):
        for js_file in (UI2 / "js").rglob("*.js"):
            src = _read(js_file)
            for m in re.finditer(r"""import\s+[^'"]*from\s+['"](\.[^'"]+)['"]""", src):
                target = (js_file.parent / m.group(1)).resolve()
                assert target.exists(), f"{js_file.name} imports missing {m.group(1)}"
