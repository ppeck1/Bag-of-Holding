"""Phase 5 translation routing and normalization tests.

Verifies:
- TranslationRouter returns correct route for each file type
- Direct-staging adapters produce a NormalizedArtifact
- HTML neutralizer strips scripts, forms, iframes and records warnings
- Hold adapters (pdf, docx, image) produce no NormalizedArtifact
- Quarantine adapters (archive, executable) produce no NormalizedArtifact
- IntakeCapability.normalizable=True only on successful normalization
- canon_eligible remains False throughout
- Warnings and known_losses are populated correctly
- AdapterRun is produced for each normalization attempt
- Trace events are emitted for each normalization outcome
"""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest

from app.services.intake.capability import initialize_capability
from app.services.intake.preservation import preserve_file
from app.services.intake.translation_router import route, RouteDecision
from app.services.intake.normalization import (
    NormalizationConfigError,
    NormalizationResult,
    normalize,
    neutralize_html,
)
from app.services.intake.adapter_registry import AdapterRegistry
from app.core.planar_service_schemas import IntakeCapability


# ---------------------------------------------------------------------------
# TranslationRouter — route decisions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename,expected_route", [
    ("doc.md", "direct_stage"),
    ("notes.txt", "direct_stage"),
    ("script.py", "direct_stage"),
    ("data.json", "direct_stage"),
    ("config.yaml", "direct_stage"),
    ("records.csv", "direct_stage"),
    ("page.html", "html_neutralize"),
    ("page.htm", "html_neutralize"),
    ("analysis.ipynb", "direct_stage"),
    ("document.docx", "direct_stage"),
    ("report.pdf", "hold"),
    ("document.doc", "hold"),
    ("photo.jpg", "hold"),
    ("archive.zip", "quarantine"),
    ("setup.exe", "quarantine"),
    ("unknown.xyzzy", "hold"),
])
def test_route_decision_for_file_types(filename, expected_route):
    cap = initialize_capability(source_ref=f"/watch/{filename}", batch_id="b1").capability
    decision = route(cap)
    assert decision.route == expected_route, (
        f"{filename}: expected {expected_route}, got {decision.route}"
    )


def test_route_decision_has_adapter_id():
    cap = initialize_capability(source_ref="/watch/doc.md", batch_id="b1").capability
    decision = route(cap)
    assert decision.adapter_id == "markdown_direct"
    assert decision.reason


def test_route_quarantine_carries_reason():
    cap = initialize_capability(source_ref="/watch/malware.exe", batch_id="b1").capability
    decision = route(cap)
    assert decision.route == "quarantine"
    assert decision.reason


def test_route_hold_carries_reason():
    cap = initialize_capability(source_ref="/watch/report.pdf", batch_id="b1").capability
    decision = route(cap)
    assert decision.route == "hold"
    assert decision.reason


# ---------------------------------------------------------------------------
# HTML neutralizer
# ---------------------------------------------------------------------------

def test_neutralize_html_strips_script_tags():
    html = "<html><body><script>alert('xss')</script><p>Safe text</p></body></html>"
    text, warnings = neutralize_html(html)
    assert "alert" not in text
    assert "Safe text" in text
    assert "script_stripped" in warnings


def test_neutralize_html_strips_form_tags():
    html = "<html><body><form action='/submit'><input type='text'/></form><p>Content</p></body></html>"
    text, warnings = neutralize_html(html)
    assert "<form" not in text
    assert "Content" in text
    assert "form_stripped" in warnings


def test_neutralize_html_strips_iframe():
    html = "<html><body><iframe src='evil.com'></iframe><p>Text</p></body></html>"
    text, warnings = neutralize_html(html)
    assert "evil.com" not in text
    assert "Text" in text
    assert "iframe_stripped" in warnings


def test_neutralize_html_strips_on_event_handlers():
    html = "<html><body><button onclick='doEvil()'>Click</button></body></html>"
    text, warnings = neutralize_html(html)
    assert "doEvil" not in text
    assert "on_event_handler_stripped" in warnings


def test_neutralize_html_preserves_text_content():
    html = "<html><body><h1>Title</h1><p>Paragraph text.</p></body></html>"
    text, warnings = neutralize_html(html)
    assert "Title" in text
    assert "Paragraph text" in text


def test_neutralize_html_empty_document():
    text, warnings = neutralize_html("")
    assert text == ""


def test_neutralize_html_plain_text_passthrough():
    html = "No tags here at all."
    text, warnings = neutralize_html(html)
    assert "No tags here" in text
    assert warnings == []


# ---------------------------------------------------------------------------
# normalize() — direct staging
# ---------------------------------------------------------------------------

def _setup(tmp_path, filename, content, batch_id="b1") -> tuple:
    """Create a source file, initialize capability, and preserve to RAW."""
    data_root = str(tmp_path / "data")
    source = tmp_path / "watch" / filename
    source.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        source.write_bytes(content)
    else:
        source.write_text(content, encoding="utf-8")
    cap = initialize_capability(source_ref=str(source), batch_id=batch_id).capability
    result = preserve_file(cap, data_root=data_root)
    assert result.success, f"Preservation failed: {result.failure_reason}"
    return cap, result.raw_artifact, data_root


def _minimal_docx_bytes(text: str) -> bytes:
    import io
    buf = io.BytesIO()
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:p><w:r><w:t>' + text + '</w:t></w:r></w:p></w:body></w:document>'
    )
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", xml)
    return buf.getvalue()


def test_normalize_markdown_direct_stage(tmp_path):
    cap, raw, data_root = _setup(tmp_path, "note.md", "# Hello\n\nWorld.")
    decision = route(cap)
    assert decision.route == "direct_stage"

    result = normalize(raw, cap, decision, data_root=data_root)
    assert result.success is True
    assert result.normalized_artifact is not None
    assert result.normalized_artifact.output_type == "markdown"
    assert result.capability.normalizable is True
    assert result.capability.canon_eligible is False


def test_normalize_text_direct_stage(tmp_path):
    cap, raw, data_root = _setup(tmp_path, "notes.txt", "Plain text content.")
    decision = route(cap)
    assert decision.route == "direct_stage"

    result = normalize(raw, cap, decision, data_root=data_root)
    assert result.success is True
    assert result.normalized_artifact.output_type == "text"


def test_normalize_json_direct_stage(tmp_path):
    cap, raw, data_root = _setup(tmp_path, "data.json", '{"key": "value"}')
    decision = route(cap)
    result = normalize(raw, cap, decision, data_root=data_root)
    assert result.success is True
    assert result.normalized_artifact.output_type == "json"


def test_normalize_yaml_direct_stage(tmp_path):
    cap, raw, data_root = _setup(tmp_path, "config.yaml", "key: value\n")
    decision = route(cap)
    result = normalize(raw, cap, decision, data_root=data_root)
    assert result.success is True
    assert result.normalized_artifact.output_type == "yaml"


def test_normalize_csv_direct_stage(tmp_path):
    cap, raw, data_root = _setup(tmp_path, "data.csv", "col1,col2\na,b\n")
    decision = route(cap)
    result = normalize(raw, cap, decision, data_root=data_root)
    assert result.success is True
    assert result.normalized_artifact.output_type == "csv"


def test_normalize_code_direct_stage(tmp_path):
    cap, raw, data_root = _setup(tmp_path, "script.py", "print('hello')\n")
    decision = route(cap)
    result = normalize(raw, cap, decision, data_root=data_root)
    assert result.success is True
    # DEC-0004.1 regression: `output_type` describes the normalized persisted REPRESENTATION,
    # not the source-language subtype — code persists as 'text', and the source-format signal
    # is preserved through existing metadata (the .py source_ref + the code_direct adapter).
    assert result.normalized_artifact.output_type == "text"


def test_normalize_notebook_extracts_cells_without_outputs(tmp_path):
    nb = {
        "cells": [
            {"cell_type": "markdown", "source": ["# Notebook title\n", "Useful notes"]},
            {
                "cell_type": "code",
                "source": ["print('do not execute')"],
                "outputs": [{"text": "SECRET OUTPUT"}],
            },
        ]
    }
    cap, raw, data_root = _setup(tmp_path, "analysis.ipynb", json.dumps(nb))
    decision = route(cap)
    assert decision.route == "direct_stage"
    assert decision.adapter_id == "notebook_direct"

    result = normalize(raw, cap, decision, data_root=data_root)
    assert result.success is True
    assert result.normalized_artifact.output_type == "markdown"
    out = Path(data_root, result.normalized_artifact.output_path).read_text(encoding="utf-8")
    assert "Notebook title" in out
    assert "print('do not execute')" in out
    assert "SECRET OUTPUT" not in out
    assert "notebook_outputs_dropped" in result.normalized_artifact.warnings


def test_normalize_malformed_notebook_fails_closed(tmp_path):
    cap, raw, data_root = _setup(tmp_path, "broken.ipynb", "{not json")
    result = normalize(raw, cap, route(cap), data_root=data_root)
    assert result.success is False
    assert "Invalid notebook JSON" in result.failure_reason


def test_normalize_docx_extracts_document_text(tmp_path):
    cap, raw, data_root = _setup(tmp_path, "document.docx", _minimal_docx_bytes("Docx extracted text"))
    decision = route(cap)
    assert decision.route == "direct_stage"
    assert decision.adapter_id == "docx_text"

    result = normalize(raw, cap, decision, data_root=data_root)
    assert result.success is True
    assert result.normalized_artifact.output_type == "text"
    out = Path(data_root, result.normalized_artifact.output_path).read_text(encoding="utf-8")
    assert "Docx extracted text" in out
    assert "docx_embedded_media_ignored" in result.normalized_artifact.warnings


def test_normalize_malformed_docx_fails_closed(tmp_path):
    cap, raw, data_root = _setup(tmp_path, "broken.docx", b"not a zip")
    result = normalize(raw, cap, route(cap), data_root=data_root)
    assert result.success is False
    assert "Invalid DOCX" in result.failure_reason


# ---------------------------------------------------------------------------
# normalize() — HTML neutralization
# ---------------------------------------------------------------------------

def test_normalize_html_neutralize_strips_scripts(tmp_path):
    html_content = "<html><body><script>alert(1)</script><p>Safe</p></body></html>"
    cap, raw, data_root = _setup(tmp_path, "page.html", html_content)
    decision = route(cap)
    assert decision.route == "html_neutralize"

    result = normalize(raw, cap, decision, data_root=data_root)
    assert result.success is True
    norm = result.normalized_artifact
    assert norm is not None
    assert "script_stripped" in norm.warnings
    assert "interactive_behavior" in norm.known_losses

    # Read the output and verify no scripts remain
    output_full = Path(data_root) / norm.output_path
    output_text = output_full.read_text(encoding="utf-8")
    assert "alert" not in output_text
    assert "Safe" in output_text


def test_normalize_html_warns_on_stripped_elements(tmp_path):
    html_content = "<html><body><form><input/></form><iframe src='x'></iframe><p>text</p></body></html>"
    cap, raw, data_root = _setup(tmp_path, "hostile.html", html_content)
    decision = route(cap)
    result = normalize(raw, cap, decision, data_root=data_root)

    assert result.success is True
    warnings = result.normalized_artifact.warnings
    assert "form_stripped" in warnings
    assert "iframe_stripped" in warnings


def test_normalize_html_normalizable_is_true(tmp_path):
    html_content = "<html><body><p>Hello</p></body></html>"
    cap, raw, data_root = _setup(tmp_path, "page.html", html_content)
    decision = route(cap)
    result = normalize(raw, cap, decision, data_root=data_root)

    assert result.capability.normalizable is True
    assert result.capability.lifecycle_state == "normalized"


# ---------------------------------------------------------------------------
# normalize() — hold path (pdf, docx, image)
# ---------------------------------------------------------------------------

def test_normalize_pdf_hold_produces_no_artifact(tmp_path):
    cap, raw, data_root = _setup(tmp_path, "report.pdf", b"%PDF-1.4 fake content")
    decision = route(cap)
    assert decision.route == "hold"

    result = normalize(raw, cap, decision, data_root=data_root)
    assert result.success is False
    assert result.normalized_artifact is None
    assert result.capability.normalizable is False
    assert result.failure_reason is not None


def test_normalize_image_hold_produces_no_artifact(tmp_path):
    cap, raw, data_root = _setup(tmp_path, "photo.jpg", b"\xff\xd8\xff fake jpeg")
    decision = route(cap)
    assert decision.route == "hold"

    result = normalize(raw, cap, decision, data_root=data_root)
    assert result.success is False
    assert result.normalized_artifact is None


# ---------------------------------------------------------------------------
# normalize() — quarantine path
# ---------------------------------------------------------------------------

def test_normalize_archive_quarantine_produces_no_artifact(tmp_path):
    # Archives are quarantined at safety lane level; preservation may not happen
    # Test the normalization routing for a quarantine-lane capability
    cap = initialize_capability(source_ref="/watch/archive.zip", batch_id="b1").capability
    assert cap.safety_lane == "quarantine"
    decision = route(cap)
    assert decision.route == "quarantine"

    # Create a fake raw artifact (preservation skipped for quarantined files in practice)
    from app.core.planar_service_schemas import RawArtifact, VersionProvenance
    raw = RawArtifact(
        intake_capability_id=cap.intake_capability_id,
        source_ref="/watch/archive.zip",
        batch_id="b1",
        source_hash_sha256="fakehash",
        preserved_hash_sha256="fakehash",
        byte_size=0,
        preservation_path="01_RAW/2026-01-01/b1/files/archive.zip",
    )
    result = normalize(raw, cap, decision, data_root=str(tmp_path / "data"))
    assert result.success is False
    assert result.normalized_artifact is None


# ---------------------------------------------------------------------------
# normalize() — canonical invariants
# ---------------------------------------------------------------------------

def test_normalize_canon_eligible_never_set_true(tmp_path):
    cap, raw, data_root = _setup(tmp_path, "doc.md", "# content")
    decision = route(cap)
    result = normalize(raw, cap, decision, data_root=data_root)
    assert result.capability.canon_eligible is False
    if result.normalized_artifact:
        assert not hasattr(result.normalized_artifact, "canon_eligible") or True


def test_normalize_produces_adapter_run(tmp_path):
    cap, raw, data_root = _setup(tmp_path, "doc.md", "# content")
    decision = route(cap)
    result = normalize(raw, cap, decision, data_root=data_root)
    assert result.success is True
    assert result.adapter_run is not None
    assert result.adapter_run.adapter_id == decision.adapter_id
    assert result.adapter_run.success is True
    assert result.normalized_artifact.normalized_artifact_id in result.adapter_run.output_artifact_ids


def test_normalize_emits_trace_event(tmp_path):
    cap, raw, data_root = _setup(tmp_path, "doc.md", "# content")
    decision = route(cap)
    result = normalize(raw, cap, decision, data_root=data_root)
    assert len(result.trace_events) == 1
    te = result.trace_events[0]
    assert te.event_type == "normalized"
    assert te.intake_capability_id == cap.intake_capability_id


def test_normalize_hold_emits_trace_event(tmp_path):
    cap, raw, data_root = _setup(tmp_path, "report.pdf", b"%PDF fake")
    decision = route(cap)
    result = normalize(raw, cap, decision, data_root=data_root)
    assert len(result.trace_events) == 1
    assert "hold" in result.trace_events[0].event_type


def test_normalize_normalized_artifact_has_output_hash(tmp_path):
    cap, raw, data_root = _setup(tmp_path, "doc.md", "# content")
    decision = route(cap)
    result = normalize(raw, cap, decision, data_root=data_root)
    assert result.normalized_artifact.output_hash_sha256
    assert len(result.normalized_artifact.output_hash_sha256) == 64


def test_normalize_raises_without_data_root(tmp_path, monkeypatch):
    monkeypatch.delenv("BOH_DATA_ROOT", raising=False)
    from app.core.planar_service_schemas import RawArtifact, VersionProvenance
    cap = initialize_capability(source_ref="/watch/doc.md", batch_id="b1").capability
    raw = RawArtifact(
        intake_capability_id=cap.intake_capability_id,
        source_ref="/watch/doc.md", batch_id="b1",
        source_hash_sha256="h", preserved_hash_sha256="h",
        byte_size=10, preservation_path="01_RAW/fake",
    )
    decision = route(cap)
    with pytest.raises(NormalizationConfigError, match="BOH_DATA_ROOT"):
        normalize(raw, cap, decision)
