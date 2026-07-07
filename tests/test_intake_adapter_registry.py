"""Phase 2 adapter registry tests.

Verifies:
- All required adapters are registered with correct metadata
- Extension and media-type matching returns the correct adapter
- Unsupported types fail closed with required_adapter and failure_reason
- No adapter declares executes_content=True or fetches_remote_assets=True
- Coverage report renders without error
- Held adapters (pdf, docx, image) cannot normalize or interpret
- Blocked adapters (archive, executable) cannot preserve
- No adapter can claim canon_eligible authority
"""

from __future__ import annotations

import pytest

from app.services.intake.adapter_registry import AdapterRegistry, get_registry
from app.core.planar_service_schemas import IntakeCapability


# ---------------------------------------------------------------------------
# Fixture — fresh registry per test to avoid singleton cross-contamination
# ---------------------------------------------------------------------------

@pytest.fixture
def registry() -> AdapterRegistry:
    return AdapterRegistry()


# ---------------------------------------------------------------------------
# All required adapter IDs are present
# ---------------------------------------------------------------------------

REQUIRED_ADAPTER_IDS = {
    "markdown_direct",
    "text_direct",
    "markup_direct",
    "config_direct",
    "code_direct",
    "json_direct",
    "yaml_direct",
    "csv_direct",
    "html_adapter",
    "notebook_direct",
    "docx_text",
    "pdf_hold",
    "docx_hold",
    "image_hold",
    "archive_hold",
    "executable_block",
    "unsupported",
}


def test_all_required_adapters_registered(registry):
    registered = {a.adapter_id for a in registry.all_adapters()}
    assert REQUIRED_ADAPTER_IDS <= registered


# ---------------------------------------------------------------------------
# Adapter invariants — no execution, no remote fetch
# ---------------------------------------------------------------------------

def test_no_adapter_executes_content(registry):
    for meta in registry.all_adapters():
        assert meta.executes_content is False, (
            f"Adapter {meta.adapter_id} declares executes_content=True — prohibited"
        )


def test_no_adapter_fetches_remote_assets(registry):
    for meta in registry.all_adapters():
        assert meta.fetches_remote_assets is False, (
            f"Adapter {meta.adapter_id} declares fetches_remote_assets=True — prohibited"
        )


def test_registry_rejects_executes_content_on_init():
    from app.core.planar_service_schemas import AdapterMetadata

    bad_meta = AdapterMetadata(
        adapter_id="bad_adapter",
        adapter_version="0.1.0",
        supported_extensions=[".bad"],
        supported_media_types=[],
        can_preserve=True,
        can_normalize=True,
        can_interpret=True,
        can_make_queryable=True,
        executes_content=True,
    )
    reg = AdapterRegistry.__new__(AdapterRegistry)
    reg._by_id = {}
    reg._by_ext = {}
    reg._by_media = {}
    reg._register(bad_meta)
    with pytest.raises(ValueError, match="executes_content"):
        reg._validate()


# ---------------------------------------------------------------------------
# Extension matching
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ext,expected_id", [
    (".md", "markdown_direct"),
    (".markdown", "markdown_direct"),
    (".mdx", "markup_direct"),
    (".rst", "markup_direct"),
    (".tex", "markup_direct"),
    (".bib", "markup_direct"),
    (".xml", "markup_direct"),
    (".log", "markup_direct"),
    (".toml", "config_direct"),
    (".ini", "config_direct"),
    (".cfg", "config_direct"),
    (".conf", "config_direct"),
    (".properties", "config_direct"),
    (".env.example", "config_direct"),
    (".txt", "text_direct"),
    (".py", "code_direct"),
    (".js", "code_direct"),
    (".json", "json_direct"),
    (".jsonl", "json_direct"),
    (".yaml", "yaml_direct"),
    (".yml", "yaml_direct"),
    (".csv", "csv_direct"),
    (".html", "html_adapter"),
    (".htm", "html_adapter"),
    (".ipynb", "notebook_direct"),
    (".pdf", "pdf_hold"),
    (".docx", "docx_text"),
    (".doc", "docx_hold"),
    (".odt", "docx_hold"),
    (".png", "image_hold"),
    (".jpg", "image_hold"),
    (".jpeg", "image_hold"),
    (".zip", "archive_hold"),
    (".tar", "archive_hold"),
    (".exe", "executable_block"),
    (".bat", "executable_block"),
    (".ps1", "executable_block"),
])
def test_extension_matching(registry, ext, expected_id):
    meta = registry.match_extension(ext)
    assert meta is not None, f"No adapter matched extension {ext}"
    assert meta.adapter_id == expected_id


def test_extension_matching_case_insensitive(registry):
    assert registry.match_extension(".MD").adapter_id == "markdown_direct"
    assert registry.match_extension(".PDF").adapter_id == "pdf_hold"
    assert registry.match_extension(".HTML").adapter_id == "html_adapter"


def test_extension_matching_without_dot(registry):
    meta = registry.match_extension("md")
    assert meta is not None
    assert meta.adapter_id == "markdown_direct"


def test_unknown_extension_returns_none(registry):
    assert registry.match_extension(".xyzzy_unknown") is None


# ---------------------------------------------------------------------------
# Media-type matching
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("media_type,expected_id", [
    ("text/markdown", "markdown_direct"),
    ("text/plain", "text_direct"),
    ("text/html", "html_adapter"),
    ("application/json", "json_direct"),
    ("application/pdf", "pdf_hold"),
    ("image/png", "image_hold"),
    ("image/jpeg", "image_hold"),
    ("application/zip", "archive_hold"),
    ("application/x-msdownload", "executable_block"),
])
def test_media_type_matching(registry, media_type, expected_id):
    meta = registry.match_media_type(media_type)
    assert meta is not None, f"No adapter matched media type {media_type}"
    assert meta.adapter_id == expected_id


def test_media_type_matching_strips_charset(registry):
    meta = registry.match_media_type("text/html; charset=utf-8")
    assert meta is not None
    assert meta.adapter_id == "html_adapter"


# ---------------------------------------------------------------------------
# resolve() — full path resolution
# ---------------------------------------------------------------------------

def test_resolve_supported_normalizable_file(registry):
    meta, required_adapter, failure_reason = registry.resolve("notes/doc.md")
    assert meta.adapter_id == "markdown_direct"
    assert required_adapter is None
    assert failure_reason is None


def test_resolve_pdf_held(registry):
    meta, required_adapter, failure_reason = registry.resolve("report.pdf")
    assert meta.adapter_id == "pdf_hold"
    assert required_adapter is not None
    assert failure_reason is not None
    assert "pdf_hold" in failure_reason


def test_resolve_docx_held(registry):
    meta, required_adapter, failure_reason = registry.resolve("document.docx")
    assert meta.adapter_id == "docx_text"
    assert required_adapter is None
    assert failure_reason is None


def test_resolve_legacy_doc_held(registry):
    meta, required_adapter, failure_reason = registry.resolve("document.doc")
    assert meta.adapter_id == "docx_hold"
    assert required_adapter is not None


def test_resolve_image_held(registry):
    meta, required_adapter, failure_reason = registry.resolve("photo.jpg")
    assert meta.adapter_id == "image_hold"
    assert required_adapter is not None


def test_resolve_archive_quarantined(registry):
    meta, required_adapter, failure_reason = registry.resolve("data.zip")
    assert meta.adapter_id == "archive_hold"
    assert meta.default_safety_lane == "quarantine"


def test_resolve_executable_quarantined(registry):
    meta, required_adapter, failure_reason = registry.resolve("setup.exe")
    assert meta.adapter_id == "executable_block"
    assert meta.default_safety_lane == "quarantine"
    assert meta.can_preserve is False


def test_resolve_unknown_extension_returns_unsupported(registry):
    meta, required_adapter, failure_reason = registry.resolve("file.xyzzy_unknown")
    assert meta.adapter_id == "unsupported"
    assert required_adapter is not None
    assert "xyzzy_unknown" in required_adapter
    assert failure_reason is not None


def test_resolve_no_extension_returns_unsupported(registry):
    meta, required_adapter, failure_reason = registry.resolve("README")
    assert meta.adapter_id == "unsupported"
    assert required_adapter is not None
    assert failure_reason is not None


def test_resolve_falls_back_to_media_type(registry):
    # Extension not known but media type is
    meta, required_adapter, failure_reason = registry.resolve("document.unknown_ext", media_type="text/html")
    assert meta.adapter_id == "html_adapter"


# ---------------------------------------------------------------------------
# Hold and quarantine adapters cannot normalize or interpret
# ---------------------------------------------------------------------------

def test_pdf_adapter_cannot_normalize(registry):
    meta = registry.get_by_id("pdf_hold")
    assert meta.can_normalize is False
    assert meta.can_interpret is False
    assert meta.can_make_queryable is False


def test_image_adapter_cannot_normalize(registry):
    meta = registry.get_by_id("image_hold")
    assert meta.can_normalize is False
    assert meta.can_interpret is False


def test_archive_adapter_cannot_preserve(registry):
    meta = registry.get_by_id("archive_hold")
    assert meta.can_preserve is False
    assert meta.can_normalize is False
    assert meta.default_safety_lane == "quarantine"


def test_executable_adapter_cannot_preserve(registry):
    meta = registry.get_by_id("executable_block")
    assert meta.can_preserve is False
    assert meta.can_normalize is False
    assert meta.can_interpret is False


# ---------------------------------------------------------------------------
# Adapters cannot grant canon_eligible
# ---------------------------------------------------------------------------

def test_adapter_cannot_promote_canon_via_intake_capability(registry):
    # Verify that creating an IntakeCapability (the schema-level guardrail)
    # prevents any adapter from marking canon_eligible=True
    cap = IntakeCapability(
        source_ref="doc.md",
        batch_id="b1",
        canon_eligible=True,  # attempt to set True via the capability record
    )
    assert cap.canon_eligible is False, (
        "IntakeCapability.__post_init__ must prevent canon_eligible from being set True"
    )


def test_adapter_metadata_has_no_canon_promotion_method(registry):
    for meta in registry.all_adapters():
        assert not hasattr(meta, "promote_canon")
        assert not hasattr(meta, "approve_canon")
        assert not hasattr(meta, "set_canon_eligible")


# ---------------------------------------------------------------------------
# Coverage report
# ---------------------------------------------------------------------------

def test_coverage_report_renders(registry):
    report = registry.coverage_report()
    assert "adapter_count" in report
    assert "extension_count" in report
    assert "rows" in report
    assert report["adapter_count"] >= len(REQUIRED_ADAPTER_IDS)
    assert report["extension_count"] > 0


def test_coverage_report_rows_have_required_fields(registry):
    report = registry.coverage_report()
    for row in report["rows"]:
        assert "extension" in row
        assert "adapter_id" in row
        assert "can_preserve" in row
        assert "can_normalize" in row
        assert "can_interpret" in row
        assert "can_make_queryable" in row
        assert "default_safety_lane" in row


def test_capability_summary_groups_by_capability(registry):
    summary = registry.capability_summary()
    assert "preservable" in summary
    assert "normalizable" in summary
    assert "interpretable" in summary
    assert "queryable" in summary
    assert "held_pending_adapter" in summary
    assert "blocked" in summary
    # Markdown and text should be normalizable
    assert ".md" in summary["normalizable"]
    assert ".txt" in summary["normalizable"]
    # PDFs and images should be held
    assert ".pdf" in summary["held_pending_adapter"]
    assert ".jpg" in summary["held_pending_adapter"] or ".jpeg" in summary["held_pending_adapter"]
    # Executables should be blocked
    assert ".exe" in summary["blocked"]


def test_coverage_report_accounts_for_all_registered_extensions(registry):
    report = registry.coverage_report()
    covered_exts = {row["extension"] for row in report["rows"]}
    # Key extensions must appear
    for ext in [".md", ".txt", ".html", ".pdf", ".docx", ".ipynb", ".env.example", ".zip", ".exe"]:
        assert ext in covered_exts, f"{ext} missing from coverage report"


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

def test_get_registry_returns_valid_registry():
    reg = get_registry()
    assert isinstance(reg, AdapterRegistry)
    assert reg.get_by_id("markdown_direct") is not None


def test_get_registry_is_stable():
    reg1 = get_registry()
    reg2 = get_registry()
    assert reg1 is reg2
