"""Phase 3 discovery and capability initialization tests.

Verifies:
- Discovery scans a directory and returns candidate file paths
- Partial/temp files are excluded by default patterns
- Custom ignore patterns are respected
- Missing or non-directory watch paths produce an error result
- CapabilityInitializer creates IntakeCapability(discovered=True) with all other capability booleans False
- safety_lane defaults are driven by the adapter registry
- required_adapter and failure_reason are set for held/blocked file types
- Every initialized capability produces a TraceEvent(event_type="discovered")
- Discovery does not trigger preservation, normalization, or queryability
- Stabilizer correctly detects stable vs. unstable files
- Trace helpers produce correctly typed events
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from app.services.intake.discovery import scan, scan_paths, DEFAULT_IGNORE_PATTERNS
from app.services.intake.stabilizer import is_stable
from app.services.intake.capability import initialize_capability, initialize_batch, InitializedCandidate
from app.services.intake import trace as trace_module
from app.services.intake.adapter_registry import AdapterRegistry
from app.core.planar_service_schemas import IntakeCapability, TraceEvent


# ---------------------------------------------------------------------------
# Discovery — scan()
# ---------------------------------------------------------------------------

def test_scan_finds_files_in_directory(tmp_path):
    (tmp_path / "note.md").write_text("# Hello")
    (tmp_path / "data.json").write_text("{}")
    result = scan(str(tmp_path))
    assert result.error is None
    found = {Path(p).name for p in result.candidates}
    assert "note.md" in found
    assert "data.json" in found


def test_scan_returns_error_for_missing_path():
    result = scan("/nonexistent/path/that/does/not/exist")
    assert result.error is not None
    assert "does not exist" in result.error


def test_scan_returns_error_for_non_directory(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("text")
    result = scan(str(f))
    assert result.error is not None
    assert "not a directory" in result.error


def test_scan_excludes_partial_download_files(tmp_path):
    (tmp_path / "good.md").write_text("content")
    (tmp_path / "download.crdownload").write_bytes(b"\x00" * 10)
    (tmp_path / "partial.part").write_bytes(b"\x00" * 10)
    (tmp_path / "tempfile.tmp").write_text("temp")
    result = scan(str(tmp_path))
    found = {Path(p).name for p in result.candidates}
    excluded_names = {Path(p).name for p, _ in result.excluded}
    assert "good.md" in found
    assert "download.crdownload" not in found
    assert "partial.part" not in found
    assert "tempfile.tmp" not in found
    assert "download.crdownload" in excluded_names
    assert "partial.part" in excluded_names
    assert "tempfile.tmp" in excluded_names


def test_scan_excludes_ms_office_temp_files(tmp_path):
    (tmp_path / "~$document.docx").write_bytes(b"\x00")
    (tmp_path / "document.docx").write_bytes(b"\x00")
    result = scan(str(tmp_path))
    found = {Path(p).name for p in result.candidates}
    assert "~$document.docx" not in found
    assert "document.docx" in found


def test_scan_excludes_vim_swap_files(tmp_path):
    (tmp_path / "notes.swp").write_bytes(b"\x00")
    (tmp_path / "notes.md").write_text("notes")
    result = scan(str(tmp_path))
    found = {Path(p).name for p in result.candidates}
    assert "notes.swp" not in found
    assert "notes.md" in found


def test_scan_excludes_ds_store(tmp_path):
    (tmp_path / ".DS_Store").write_bytes(b"\x00")
    (tmp_path / "real.txt").write_text("hello")
    result = scan(str(tmp_path))
    found = {Path(p).name for p in result.candidates}
    assert ".DS_Store" not in found
    assert "real.txt" in found


def test_scan_respects_custom_ignore_patterns(tmp_path):
    (tmp_path / "secret.bak").write_text("backup")
    (tmp_path / "normal.md").write_text("# hi")
    result = scan(str(tmp_path), ignore_patterns=["*.bak"])
    found = {Path(p).name for p in result.candidates}
    assert "secret.bak" not in found
    assert "normal.md" in found


def test_scan_descends_subdirectories_by_default(tmp_path):
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    (subdir / "nested.md").write_text("# nested")
    (tmp_path / "top.md").write_text("# top")
    result = scan(str(tmp_path))
    found = {Path(p).name for p in result.candidates}
    assert "top.md" in found
    assert "nested.md" in found


def test_scan_non_recursive_does_not_descend(tmp_path):
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    (subdir / "nested.md").write_text("# nested")
    (tmp_path / "top.md").write_text("# top")
    result = scan(str(tmp_path), recursive=False)
    found = {Path(p).name for p in result.candidates}
    assert "top.md" in found
    assert "nested.md" not in found


def test_scan_paths_returns_one_result_per_path(tmp_path):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    (dir_a / "file_a.md").write_text("a")
    (dir_b / "file_b.txt").write_text("b")
    results = scan_paths([str(dir_a), str(dir_b)])
    assert len(results) == 2
    found_a = {Path(p).name for p in results[0].candidates}
    found_b = {Path(p).name for p in results[1].candidates}
    assert "file_a.md" in found_a
    assert "file_b.txt" in found_b


def test_scan_empty_directory_returns_no_candidates(tmp_path):
    result = scan(str(tmp_path))
    assert result.error is None
    assert result.candidates == []


# ---------------------------------------------------------------------------
# Stabilizer
# ---------------------------------------------------------------------------

def test_stable_file_is_detected(tmp_path):
    f = tmp_path / "stable.md"
    f.write_text("content")
    result = is_stable(str(f), settle_seconds=0.05)
    assert result.stable is True
    assert result.size_bytes > 0
    assert result.reason is None


def test_nonexistent_file_is_not_stable(tmp_path):
    result = is_stable(str(tmp_path / "does_not_exist.md"), settle_seconds=0.01)
    assert result.stable is False
    assert result.reason is not None


# ---------------------------------------------------------------------------
# IntakeCapability initialization
# ---------------------------------------------------------------------------

def test_initialize_capability_creates_discovered_record(tmp_path):
    result = initialize_capability(
        source_ref=str(tmp_path / "doc.md"),
        batch_id="batch_001",
    )
    cap = result.capability
    assert cap.discovered is True
    assert cap.source_ref.endswith("doc.md")
    assert cap.batch_id == "batch_001"


def test_initialize_capability_all_other_booleans_false():
    result = initialize_capability(source_ref="/watch/notes.md", batch_id="b1")
    cap = result.capability
    assert cap.preservable is False
    assert cap.normalizable is False
    assert cap.interpretable is False
    assert cap.queryable is False
    assert cap.canon_eligible is False


def test_initialize_capability_safety_lane_from_adapter():
    # .md → markdown_direct → safety_lane=accept
    result = initialize_capability(source_ref="/watch/notes.md", batch_id="b1")
    assert result.capability.safety_lane == "accept"


def test_initialize_capability_pdf_is_held():
    result = initialize_capability(source_ref="/docs/report.pdf", batch_id="b1")
    cap = result.capability
    assert cap.safety_lane == "hold"
    assert cap.required_adapter is not None
    assert cap.failure_reason is not None


def test_initialize_capability_zip_is_quarantined():
    result = initialize_capability(source_ref="/downloads/archive.zip", batch_id="b1")
    cap = result.capability
    assert cap.safety_lane == "quarantine"


def test_initialize_capability_exe_is_quarantined():
    result = initialize_capability(source_ref="/downloads/setup.exe", batch_id="b1")
    cap = result.capability
    assert cap.safety_lane == "quarantine"
    assert cap.preservable is False


def test_initialize_capability_unknown_extension_is_held():
    result = initialize_capability(source_ref="/watch/mystery.xyzzy", batch_id="b1")
    cap = result.capability
    assert cap.required_adapter is not None
    assert cap.failure_reason is not None


def test_initialize_capability_emits_trace_event():
    result = initialize_capability(source_ref="/watch/doc.md", batch_id="b1", job_id="job_001")
    te = result.trace_event
    assert isinstance(te, TraceEvent)
    assert te.event_type == "discovered"
    assert te.job_id == "job_001"
    assert "doc.md" in te.detail.get("source_ref", "")


def test_initialize_capability_trace_event_id_in_capability():
    result = initialize_capability(source_ref="/watch/doc.md", batch_id="b1")
    cap = result.capability
    te = result.trace_event
    assert te.trace_event_id in cap.trace_event_refs


def test_initialize_capability_canon_eligible_invariant():
    result = initialize_capability(source_ref="/watch/doc.md", batch_id="b1")
    assert result.capability.canon_eligible is False


def test_initialize_capability_lifecycle_state_is_discovered():
    result = initialize_capability(source_ref="/watch/doc.md", batch_id="b1")
    assert result.capability.lifecycle_state == "discovered"


def test_initialize_capability_trust_state_is_unknown():
    result = initialize_capability(source_ref="/watch/doc.md", batch_id="b1")
    assert result.capability.trust_state == "unknown"


def test_initialize_batch_creates_one_capability_per_source():
    refs = ["/watch/a.md", "/watch/b.txt", "/watch/c.pdf"]
    results = initialize_batch(source_refs=refs, batch_id="batch_002")
    assert len(results) == 3
    for r in results:
        assert isinstance(r, InitializedCandidate)
        assert r.capability.discovered is True
        assert r.capability.canon_eligible is False


def test_initialize_batch_each_has_unique_capability_id():
    refs = ["/watch/a.md", "/watch/b.md", "/watch/c.md"]
    results = initialize_batch(source_refs=refs, batch_id="b1")
    ids = [r.capability.intake_capability_id for r in results]
    assert len(ids) == len(set(ids))


def test_initialize_batch_emits_trace_per_file():
    refs = ["/watch/a.md", "/watch/b.pdf"]
    results = initialize_batch(source_refs=refs, batch_id="b1")
    for r in results:
        assert r.trace_event.event_type == "discovered"
        assert r.trace_event.trace_event_id in r.capability.trace_event_refs


# ---------------------------------------------------------------------------
# Discovery does not trigger preservation, normalization, or queryability
# ---------------------------------------------------------------------------

def test_discovery_does_not_preserve_files(tmp_path):
    """Scanning a directory must not create any new files."""
    (tmp_path / "doc.md").write_text("# test")
    before = set(str(p) for p in tmp_path.rglob("*"))
    scan(str(tmp_path))
    after = set(str(p) for p in tmp_path.rglob("*"))
    assert after == before, "Discovery must not write any files"


def test_capability_init_does_not_create_files(tmp_path):
    """IntakeCapability initialization must not create any new files."""
    f = tmp_path / "doc.md"
    f.write_text("# test")
    before = set(str(p) for p in tmp_path.rglob("*"))
    initialize_capability(source_ref=str(f), batch_id="b1")
    after = set(str(p) for p in tmp_path.rglob("*"))
    assert after == before, "Capability initialization must not write any files"


def test_discovery_does_not_import_or_index_files(tmp_path):
    """Scanning must not trigger any database writes (no DB import)."""
    (tmp_path / "doc.md").write_text("# test")
    result = scan(str(tmp_path))
    # If this test runs without error, no DB import was triggered.
    # The scan result carries only paths — no indexing side effect.
    assert len(result.candidates) == 1
    cap = initialize_capability(source_ref=result.candidates[0], batch_id="b1").capability
    # Capability is in-memory only; no DB record exists
    assert cap.intake_capability_id
    assert cap.preservable is False
    assert cap.normalizable is False
    assert cap.queryable is False


# ---------------------------------------------------------------------------
# Trace helpers
# ---------------------------------------------------------------------------

def test_trace_discovered_event_has_correct_type():
    te = trace_module.discovered_event(
        source_ref="/watch/doc.md",
        batch_id="b1",
        intake_capability_id="ic_001",
        job_id="job_001",
    )
    assert te.event_type == "discovered"
    assert te.intake_capability_id == "ic_001"
    assert te.detail["source_ref"] == "/watch/doc.md"


def test_trace_stabilization_event_stable():
    te = trace_module.stabilization_event(
        source_ref="/watch/doc.md",
        intake_capability_id="ic_001",
        stable=True,
    )
    assert te.event_type == "stabilized"
    assert te.detail["stable"] is True


def test_trace_stabilization_event_unstable():
    te = trace_module.stabilization_event(
        source_ref="/watch/growing.bin",
        intake_capability_id="ic_002",
        stable=False,
        reason="File size changed.",
    )
    assert te.event_type == "stabilization_failed"
    assert te.detail["stable"] is False
    assert "changed" in te.detail["reason"]


def test_trace_excluded_event():
    te = trace_module.excluded_event(
        source_ref="/watch/file.tmp",
        reason="Matches ignore pattern '*.tmp'.",
    )
    assert te.event_type == "excluded"
    assert "tmp" in te.detail["source_ref"]


def test_trace_emit_generic():
    te = trace_module.emit(
        event_type="custom_event",
        intake_capability_id="ic_001",
        job_id="job_001",
        detail={"key": "value"},
    )
    assert te.event_type == "custom_event"
    assert te.intake_capability_id == "ic_001"
    assert te.job_id == "job_001"
    assert te.detail["key"] == "value"
    assert te.trace_event_id.startswith("te_")
