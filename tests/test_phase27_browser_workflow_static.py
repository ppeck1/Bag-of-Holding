from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_clean_workspace_uses_protected_api_headers_and_exact_payload():
    app_js = (ROOT / "app" / "ui" / "app.js").read_text(encoding="utf-8")
    assert "withOperatorHeaders(path, opts)" in app_js
    assert "headers.set(OPERATOR_HEADER_NAME, token)" in app_js
    assert "headers.set(ACTOR_HEADER_NAME, actor)" in app_js
    assert "protectedRequestPreview" in app_js
    assert "'/api/workspace/reset-full'" in app_js
    assert "JSON.stringify({confirm: 'RESET'})" in app_js
    assert "preserve_canonical: false" not in app_js


def test_index_cache_busts_app_js_and_exposes_build_marker():
    index = (ROOT / "app" / "ui" / "index.html").read_text(encoding="utf-8")
    assert "UI build:" in index
    assert "app.js?v=186" in index


def test_bulk_upload_handlers_are_inline_once_and_guarded():
    index = (ROOT / "app" / "ui" / "index.html").read_text(encoding="utf-8")
    app_js = (ROOT / "app" / "ui" / "app.js").read_text(encoding="utf-8")
    assert index.count('onchange="uploadDocuments()"') == 1
    assert index.count('onchange="uploadDocumentsFromInput(this)"') == 1
    assert "let bulkUploadInProgress = false" in app_js
    assert app_js.count("bulkUploadInProgress = true") >= 3
    assert "Upload already in progress." in app_js
    assert "fetch('/api/input/upload', withOperatorHeaders('/api/input/upload'" in app_js
    assert "fetch('/api/input/upload', { method: 'POST', body: fd })" not in app_js
