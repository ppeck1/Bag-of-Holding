"""tests/test_ui2_phase_a.py -- static acceptance for the new UI (Phase A) at /v2.

The new UI is a build-free vanilla ES-module surface served at /v2, coexisting with
the classic UI at /. These are static text checks (no runtime/DOM), mirroring the
existing UI test style (test_fold_view_ui.py); they verify the surface is present,
wired, and self-consistent. They do NOT touch app/ui or its tests.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
UI2 = ROOT / "app" / "ui2"
MAIN = ROOT / "app" / "api" / "main.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestSurfacePresent:
    def test_ui2_dir_exists(self):
        assert UI2.is_dir()

    def test_design_css_copied_verbatim(self):
        for name in ("tokens.css", "app.css", "fold.css"):
            assert (UI2 / name).exists(), f"missing {name}"
        # tokens.css carries the design token set
        tokens = _read(UI2 / "tokens.css")
        assert "--state-current" in tokens and "--accent" in tokens

    def test_index_loads_tokens_and_module_entry(self):
        html = _read(UI2 / "index.html")
        assert 'href="tokens.css"' in html
        assert 'type="module"' in html and 'src="js/app.js"' in html


class TestModulesPresent:
    def test_core_modules_exist(self):
        for rel in ("js/dom.js", "js/ns.js", "js/api.js", "js/primitives.js",
                    "js/shell.js", "js/fixtures.js", "js/app.js",
                    "js/screens/overview.js", "js/screens/settings.js",
                    "js/screens/settings-full.js", "js/screens/status.js",
                    "js/screens/component-sheet.js", "js/screens/fold.js",
                    "js/screens/library.js", "js/screens/review.js",
                    "js/screens/authority.js", "js/screens/capture.js",
                    "js/screens/activity.js"):
            assert (UI2 / rel).exists(), f"missing {rel}"

    def test_foundry_defines_primitives(self):
        js = _read(UI2 / "js" / "primitives.js")
        for name in ("Button", "Badge", "MetricTile", "Card", "Modal",
                     "EmptyState", "Skeleton", "Tabs", "Toggle", "AlertBanner"):
            assert re.search(rf"export function {name}\b", js), f"primitive {name} not exported"

    def test_namespaces_defined(self):
        js = _read(UI2 / "js" / "ns.js")
        # currentness namespace drives fill; must include the five values incl. expired
        for ns in ("current", "stale", "expired", "conflict", "unknown"):
            assert re.search(rf"\b{ns}:\s*{{", js), f"namespace {ns} missing"

    def test_overview_wired_to_real_endpoints(self):
        js = _read(UI2 / "js" / "api.js")
        assert "/api/dashboard" in js and "/api/status" in js and "/api/coherence/summary" in js
        # the currentness mapping is honestly flagged inferred
        assert "inferred" in js


class TestServing:
    def test_mount_layout(self):
        src = _read(MAIN)
        # New governed UI is the default at / (served via the cache-revalidating
        # StaticFiles subclass so stale ES modules can't run against fresh siblings).
        assert 'app.mount("/", _CachelessStaticFiles' in src
        # /v2 preserved for backward compatibility
        assert 'app.mount("/v2"' in src
        # Classic UI accessible at /classic for operator-token mutations
        assert 'app.mount("/classic"' in src
        # / must point to ui2 (not the classic ui dir)
        i_root = src.index('app.mount("/",')
        root_region = src[i_root: i_root + 100]
        assert "ui2" in root_region, "root mount must serve ui2 directory"
        # /v2 and /classic must precede the greedy root mount
        i_v2      = src.index('app.mount("/v2"')
        i_classic = src.index('app.mount("/classic"')
        assert i_v2      < i_root, "/v2 must be registered before root"
        assert i_classic < i_root, "/classic must be registered before root"


class TestImportIntegrity:
    def test_relative_imports_resolve(self):
        """Every relative import in the ui2 modules points at a real file."""
        for js_file in (UI2 / "js").rglob("*.js"):
            src = _read(js_file)
            for m in re.finditer(r"""import\s+[^'"]*from\s+['"](\.[^'"]+)['"]""", src):
                target = (js_file.parent / m.group(1)).resolve()
                assert target.exists(), f"{js_file.name} imports missing {m.group(1)}"


class TestEsModuleCompiles:
    """Every ui2 module must parse as an ES module — the same way the browser does.

    Regression guard: a single ESM syntax error (e.g. an unbalanced paren) fails the
    WHOLE module graph in the browser and blanks the SPA, yet `node --check` on a `.js`
    file parses it as a CommonJS script and can miss it, and the Python suite never
    evaluates the JS. This test copies each module to a `.mjs` and runs `node --check`
    so it is checked in true ES-module mode. Skips cleanly when node is unavailable.
    """

    def test_all_modules_compile_as_esm(self, tmp_path):
        import shutil
        import subprocess

        node = shutil.which("node")
        if not node:
            import pytest
            pytest.skip("node not available; ESM compile check skipped")

        failures = []
        for js_file in sorted((UI2 / "js").rglob("*.js")):
            mjs = tmp_path / (js_file.stem + ".mjs")
            mjs.write_text(_read(js_file), encoding="utf-8")
            proc = subprocess.run(
                [node, "--check", str(mjs)],
                capture_output=True, text=True,
            )
            if proc.returncode != 0:
                rel = js_file.relative_to(UI2)
                failures.append(f"{rel}:\n{proc.stderr.strip()[:300]}")
        assert not failures, "ES-module syntax errors (would blank the SPA):\n" + "\n\n".join(failures)


class TestModuleGraphRenders:
    """The whole ui2 module graph must import AND the synchronous boot render() must not
    throw — under a DOM stub, no server.

    Regression guard one level deeper than ESM-syntax: catches a runtime error during module
    evaluation or the initial render (undefined access, bad call) that blanks the SPA but
    parses fine. Reuses the committed harness tools/ui_drive/render_check.mjs. Skips cleanly
    when node is unavailable.
    """

    def test_app_boots_without_throwing(self, tmp_path):
        import shutil
        import subprocess

        node = shutil.which("node")
        if not node:
            import pytest
            pytest.skip("node not available; render check skipped")

        # Copy the module tree and mark it as an ES-module package so .js imports resolve.
        js_dst = tmp_path / "js"
        shutil.copytree(UI2 / "js", js_dst)
        (js_dst / "package.json").write_text('{"type":"module"}', encoding="utf-8")

        render_check = ROOT / "tools" / "ui_drive" / "render_check.mjs"
        proc = subprocess.run(
            [node, str(render_check), str(js_dst)],
            capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode == 0 and "RENDER_OK" in proc.stdout, (
            "ui2 module graph failed to import or boot-render (would blank the SPA):\n"
            + (proc.stderr.strip() or proc.stdout.strip())[:600]
        )
