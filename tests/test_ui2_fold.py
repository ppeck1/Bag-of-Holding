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
        # the two Phase-B projections, no Risk/Authority/Evidence/Timeline yet
        assert '"Web"' in js and '"Currentness Map"' in js

    def test_svg_helper_present(self):
        dom = _read(UI2 / "js" / "dom.js")
        assert re.search(r"export function hs\b", dom)
        assert "createElementNS" in dom

    def test_api_reads_real_fold_endpoints(self):
        api = _read(UI2 / "js" / "api.js")
        assert "/api/fold/library" in api
        assert "/api/graph/projection" in api
        assert "/api/fold/node/" in api
        assert re.search(r"export function foldCurrentness\b", api)  # 9->5 label adapter
        assert re.search(r"export async function fetchFoldGraph\b", api)
        assert re.search(r"export async function fetchFoldNode\b", api)


class TestRouting:
    def test_app_routes_fold_to_workspace(self):
        app = _read(UI2 / "js" / "app.js")
        assert "FoldWorkspace" in app and 'from "./screens/fold.js"' in app
        assert "ensureFold" in app
        # the fold route must render the workspace, not only the placeholder
        assert 'r === "fold"' in app
        assert "return FoldWorkspace(" in app


class TestImportIntegrity:
    def test_relative_imports_resolve(self):
        for js_file in (UI2 / "js").rglob("*.js"):
            src = _read(js_file)
            for m in re.finditer(r"""import\s+[^'"]*from\s+['"](\.[^'"]+)['"]""", src):
                target = (js_file.parent / m.group(1)).resolve()
                assert target.exists(), f"{js_file.name} imports missing {m.group(1)}"
