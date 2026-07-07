"""Phase 6 interpretation and queryability handoff tests.

Verifies:
- queryability.assess() returns queryable=True for sufficient text content
- queryability.assess() returns queryable=False for short/empty content
- queryability.assess() returns queryable=False for non-text output types
- interpretation.produce_evidence_units() returns an EvidenceUnit from normalized content
- EvidenceUnit carries correct span, unit_type='body', and text_hash
- governance_handoff.assemble_handoff() produces a HandoffPacket without raising
- HandoffPacket carries correct refs and enforces canon_eligible=False
- handoff_ready emitted when queryable and normalizable
- handoff_skipped emitted when not queryable or not normalizable
- canon_eligible never set True throughout Phase 6
- IntakeCapability.queryable=True only on affirmative queryability assessment
- QueryabilityConfigError raised when data_root absent
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.services.intake.capability import initialize_capability
from app.services.intake.preservation import preserve_file
from app.services.intake.translation_router import route
from app.services.intake.normalization import normalize
from app.services.intake.queryability import (
    QueryabilityConfigError,
    assess,
)
from app.services.intake.interpretation import (
    InterpretationConfigError,
    produce_evidence_units,
)
from app.services.intake.governance_handoff import assemble_handoff
from app.core.planar_service_schemas import (
    NormalizedArtifact,
    RawArtifact,
    VersionProvenance,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _full_pipeline(tmp_path, filename, content, batch_id="b1"):
    """Run the full intake pipeline through normalization and return results."""
    data_root = str(tmp_path / "data")
    source = tmp_path / "watch" / filename
    source.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        source.write_bytes(content)
    else:
        source.write_text(content, encoding="utf-8")

    cap = initialize_capability(source_ref=str(source), batch_id=batch_id).capability
    pres = preserve_file(cap, data_root=data_root)
    assert pres.success, f"Preservation failed: {pres.failure_reason}"

    decision = route(cap)
    norm_result = normalize(pres.raw_artifact, cap, decision, data_root=data_root)
    return cap, pres.raw_artifact, norm_result, data_root


# ---------------------------------------------------------------------------
# queryability.assess()
# ---------------------------------------------------------------------------

def test_assess_queryable_markdown(tmp_path):
    cap, raw, norm, data_root = _full_pipeline(
        tmp_path, "doc.md", "# Hello\n\nThis document has plenty of words in it."
    )
    assert norm.success
    result = assess(norm.normalized_artifact, cap, data_root=data_root)
    assert result.queryable is True
    assert result.word_count >= 5
    assert result.capability.queryable is True
    assert result.capability.interpretable is True


def test_assess_queryable_text(tmp_path):
    cap, raw, norm, data_root = _full_pipeline(
        tmp_path, "notes.txt", "This is a plain text file with enough words for queryability."
    )
    assert norm.success
    result = assess(norm.normalized_artifact, cap, data_root=data_root)
    assert result.queryable is True


def test_assess_short_content_not_queryable(tmp_path):
    cap, raw, norm, data_root = _full_pipeline(tmp_path, "tiny.txt", "Hi.")
    assert norm.success
    result = assess(norm.normalized_artifact, cap, data_root=data_root)
    assert result.queryable is False
    assert result.failure_reason is not None
    assert result.capability.queryable is False


def test_assess_empty_content_not_queryable(tmp_path):
    cap, raw, norm, data_root = _full_pipeline(tmp_path, "empty.txt", "")
    assert norm.success
    result = assess(norm.normalized_artifact, cap, data_root=data_root)
    assert result.queryable is False


def test_assess_sets_capability_queryable_true(tmp_path):
    cap, raw, norm, data_root = _full_pipeline(
        tmp_path, "article.md", "# Title\n\nLong enough body with multiple meaningful words here."
    )
    assert norm.success
    assert cap.queryable is False  # before assess
    assess(norm.normalized_artifact, cap, data_root=data_root)
    assert cap.queryable is True


def test_assess_queryable_json(tmp_path):
    cap, raw, norm, data_root = _full_pipeline(
        tmp_path, "data.json", '{"key": "value", "count": 42, "items": ["a", "b", "c"]}'
    )
    assert norm.success
    result = assess(norm.normalized_artifact, cap, data_root=data_root)
    assert result.queryable is True


def test_assess_emits_trace_event(tmp_path):
    cap, raw, norm, data_root = _full_pipeline(
        tmp_path, "doc.md", "# Hello\n\nThis is long enough content to be queryable."
    )
    assert norm.success
    result = assess(norm.normalized_artifact, cap, data_root=data_root)
    assert len(result.trace_events) == 1
    assert result.trace_events[0].event_type == "queryable"
    assert result.trace_events[0].intake_capability_id == cap.intake_capability_id


def test_assess_skip_emits_trace_event(tmp_path):
    cap, raw, norm, data_root = _full_pipeline(tmp_path, "tiny.txt", "Too short.")
    assert norm.success
    result = assess(norm.normalized_artifact, cap, data_root=data_root)
    assert len(result.trace_events) == 1
    assert "skip" in result.trace_events[0].event_type or "failed" in result.trace_events[0].event_type


def test_assess_canon_eligible_never_true(tmp_path):
    cap, raw, norm, data_root = _full_pipeline(
        tmp_path, "doc.md", "# Hello\n\nContent that is long enough to be queryable today."
    )
    assess(norm.normalized_artifact, cap, data_root=data_root)
    assert cap.canon_eligible is False


def test_assess_raises_without_data_root(tmp_path, monkeypatch):
    monkeypatch.delenv("BOH_DATA_ROOT", raising=False)
    cap, raw, norm, data_root = _full_pipeline(
        tmp_path, "doc.md", "# Content that is long enough to pass."
    )
    with pytest.raises(QueryabilityConfigError, match="BOH_DATA_ROOT"):
        assess(norm.normalized_artifact, cap)


# ---------------------------------------------------------------------------
# interpretation.produce_evidence_units()
# ---------------------------------------------------------------------------

def test_produce_evidence_units_returns_unit(tmp_path):
    cap, raw, norm, data_root = _full_pipeline(
        tmp_path, "doc.md", "# Title\n\nThis is the body of the document."
    )
    assert norm.success
    result = produce_evidence_units(norm.normalized_artifact, cap, data_root=data_root)
    assert result.success is True
    assert len(result.evidence_units) == 1


def test_evidence_unit_fields(tmp_path):
    cap, raw, norm, data_root = _full_pipeline(
        tmp_path, "doc.md", "# Title\n\nThis is the body."
    )
    assert norm.success
    result = produce_evidence_units(norm.normalized_artifact, cap, data_root=data_root)
    eu = result.evidence_units[0]
    assert eu.span_start == 0
    assert eu.span_end > 0
    assert eu.unit_type == "body"
    assert len(eu.text_hash) == 64  # sha256 hex
    assert eu.normalized_artifact_id == norm.normalized_artifact.normalized_artifact_id


def test_evidence_unit_canon_eligible_false(tmp_path):
    cap, raw, norm, data_root = _full_pipeline(
        tmp_path, "doc.md", "# Title\n\nBody text."
    )
    assert norm.success
    result = produce_evidence_units(norm.normalized_artifact, cap, data_root=data_root)
    for eu in result.evidence_units:
        assert eu.canon_eligible is False


def test_interpretation_sets_capability_interpretable(tmp_path):
    cap, raw, norm, data_root = _full_pipeline(
        tmp_path, "doc.md", "# Title\n\nBody text for interpretation."
    )
    assert norm.success
    assert cap.interpretable is False
    produce_evidence_units(norm.normalized_artifact, cap, data_root=data_root)
    assert cap.interpretable is True


def test_interpretation_emits_trace_event(tmp_path):
    cap, raw, norm, data_root = _full_pipeline(
        tmp_path, "doc.md", "# Title\n\nBody text."
    )
    assert norm.success
    result = produce_evidence_units(norm.normalized_artifact, cap, data_root=data_root)
    assert len(result.trace_events) == 1
    assert result.trace_events[0].event_type == "interpreted"
    assert result.trace_events[0].intake_capability_id == cap.intake_capability_id


def test_interpretation_evidence_unit_id_stable(tmp_path):
    cap, raw, norm, data_root = _full_pipeline(
        tmp_path, "doc.md", "# Title\n\nBody text."
    )
    assert norm.success
    r1 = produce_evidence_units(norm.normalized_artifact, cap, data_root=data_root)
    r2 = produce_evidence_units(norm.normalized_artifact, cap, data_root=data_root)
    assert r1.evidence_units[0].evidence_unit_id == r2.evidence_units[0].evidence_unit_id


def test_interpretation_raises_without_data_root(tmp_path, monkeypatch):
    monkeypatch.delenv("BOH_DATA_ROOT", raising=False)
    cap, raw, norm, data_root = _full_pipeline(
        tmp_path, "doc.md", "# Title\n\nBody text."
    )
    with pytest.raises(InterpretationConfigError, match="BOH_DATA_ROOT"):
        produce_evidence_units(norm.normalized_artifact, cap)


# ---------------------------------------------------------------------------
# governance_handoff.assemble_handoff()
# ---------------------------------------------------------------------------

def test_assemble_handoff_ready(tmp_path):
    cap, raw, norm, data_root = _full_pipeline(
        tmp_path, "doc.md", "# Title\n\nContent long enough for full pipeline."
    )
    assert norm.success
    assess(norm.normalized_artifact, cap, data_root=data_root)
    interp = produce_evidence_units(norm.normalized_artifact, cap, data_root=data_root)

    result = assemble_handoff(
        capability=cap,
        raw_artifact=raw,
        normalized_artifact=norm.normalized_artifact,
        evidence_units=interp.evidence_units,
    )
    assert result.success is True
    assert result.handoff_packet is not None
    assert result.handoff_packet.intake_capability_id == cap.intake_capability_id


def test_assemble_handoff_emits_handoff_ready(tmp_path):
    cap, raw, norm, data_root = _full_pipeline(
        tmp_path, "doc.md", "# Title\n\nContent that is long enough to pass queryability."
    )
    assert norm.success
    assess(norm.normalized_artifact, cap, data_root=data_root)
    interp = produce_evidence_units(norm.normalized_artifact, cap, data_root=data_root)

    result = assemble_handoff(cap, raw, norm.normalized_artifact, interp.evidence_units)
    assert len(result.trace_events) == 1
    assert result.trace_events[0].event_type == "handoff_ready"


def test_assemble_handoff_skipped_when_not_queryable(tmp_path):
    cap, raw, norm, data_root = _full_pipeline(tmp_path, "tiny.txt", "Short.")
    assert norm.success
    assess(norm.normalized_artifact, cap, data_root=data_root)

    result = assemble_handoff(cap, raw, norm.normalized_artifact, [])
    assert result.success is True
    assert result.trace_events[0].event_type == "handoff_skipped"


def test_assemble_handoff_skipped_when_hold(tmp_path):
    cap = initialize_capability(source_ref="/watch/report.pdf", batch_id="b1").capability
    result = assemble_handoff(cap, raw_artifact=None, normalized_artifact=None, evidence_units=[])
    assert result.success is True
    assert result.trace_events[0].event_type == "handoff_skipped"


def test_handoff_packet_enforces_canon_eligible_false(tmp_path):
    cap, raw, norm, data_root = _full_pipeline(
        tmp_path, "doc.md", "# Title\n\nContent long enough for full pipeline."
    )
    assert norm.success
    assess(norm.normalized_artifact, cap, data_root=data_root)
    interp = produce_evidence_units(norm.normalized_artifact, cap, data_root=data_root)

    result = assemble_handoff(cap, raw, norm.normalized_artifact, interp.evidence_units)
    assert result.handoff_packet.capability_state["canon_eligible"] is False


def test_handoff_packet_carries_evidence_refs(tmp_path):
    cap, raw, norm, data_root = _full_pipeline(
        tmp_path, "doc.md", "# Title\n\nContent long enough for full pipeline."
    )
    assert norm.success
    assess(norm.normalized_artifact, cap, data_root=data_root)
    interp = produce_evidence_units(norm.normalized_artifact, cap, data_root=data_root)

    result = assemble_handoff(cap, raw, norm.normalized_artifact, interp.evidence_units)
    assert len(result.handoff_packet.evidence_candidate_refs) == 1
    assert result.handoff_packet.evidence_candidate_refs[0] == interp.evidence_units[0].evidence_unit_id


def test_handoff_packet_carries_normalized_artifact_id(tmp_path):
    cap, raw, norm, data_root = _full_pipeline(
        tmp_path, "doc.md", "# Title\n\nContent long enough for full pipeline."
    )
    assert norm.success
    assess(norm.normalized_artifact, cap, data_root=data_root)
    interp = produce_evidence_units(norm.normalized_artifact, cap, data_root=data_root)

    result = assemble_handoff(cap, raw, norm.normalized_artifact, interp.evidence_units)
    assert result.handoff_packet.normalized_artifact_id == norm.normalized_artifact.normalized_artifact_id


def test_handoff_packet_has_stable_id(tmp_path):
    cap, raw, norm, data_root = _full_pipeline(
        tmp_path, "doc.md", "# Title\n\nContent long enough for full pipeline."
    )
    assert norm.success
    assess(norm.normalized_artifact, cap, data_root=data_root)
    interp = produce_evidence_units(norm.normalized_artifact, cap, data_root=data_root)

    r1 = assemble_handoff(cap, raw, norm.normalized_artifact, interp.evidence_units)
    r2 = assemble_handoff(cap, raw, norm.normalized_artifact, interp.evidence_units)
    assert r1.handoff_packet.handoff_id == r2.handoff_packet.handoff_id


def test_full_phase6_pipeline_canon_eligible_never_true(tmp_path):
    cap, raw, norm, data_root = _full_pipeline(
        tmp_path, "article.md",
        "# Article\n\nThis article has a substantial body of text that easily clears the queryability threshold."
    )
    assert norm.success
    assess(norm.normalized_artifact, cap, data_root=data_root)
    interp = produce_evidence_units(norm.normalized_artifact, cap, data_root=data_root)
    result = assemble_handoff(cap, raw, norm.normalized_artifact, interp.evidence_units)

    assert cap.canon_eligible is False
    assert result.handoff_packet.capability_state["canon_eligible"] is False
    for eu in interp.evidence_units:
        assert eu.canon_eligible is False
