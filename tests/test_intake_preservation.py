"""Phase 4 preservation tests.

Verifies:
- preserve_file() copies file to RAW directory and returns a RawArtifact
- SHA-256 is computed before and after copy; hashes must match
- Hash mismatch triggers quarantine and blocks downstream processing
- Original source files are never mutated
- preservable=True only on successful preservation
- source_registry.jsonl is appended per preserved file
- batch_manifest.json is written per batch
- Missing BOH_DATA_ROOT raises PreservationConfigError
- Trace events are emitted for each preservation outcome
- canon_eligible remains False throughout
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.services.intake.capability import initialize_capability
from app.services.intake.preservation import (
    PreservationConfigError,
    PreservationResult,
    preserve_file,
    write_batch_manifest,
)
from app.services.intake.hashing import sha256_file, sha256_bytes


# ---------------------------------------------------------------------------
# Hashing helpers
# ---------------------------------------------------------------------------

def test_sha256_file_produces_consistent_hash(tmp_path):
    f = tmp_path / "test.md"
    f.write_text("hello world")
    h1 = sha256_file(str(f))
    h2 = sha256_file(str(f))
    assert h1 == h2
    assert len(h1) == 64


def test_sha256_file_differs_for_different_content(tmp_path):
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text("content A")
    b.write_text("content B")
    assert sha256_file(str(a)) != sha256_file(str(b))


def test_sha256_bytes_consistent():
    data = b"test content"
    assert sha256_bytes(data) == sha256_bytes(data)
    assert len(sha256_bytes(data)) == 64


# ---------------------------------------------------------------------------
# preserve_file — success path
# ---------------------------------------------------------------------------

def test_preserve_file_copies_to_raw_directory(tmp_path, monkeypatch):
    data_root = str(tmp_path / "data")
    monkeypatch.setenv("BOH_DATA_ROOT", data_root)

    source = tmp_path / "watch" / "note.md"
    source.parent.mkdir()
    source.write_text("# Hello from note")

    cap = initialize_capability(source_ref=str(source), batch_id="b_001").capability
    result = preserve_file(cap, data_root=data_root)

    assert result.success is True
    assert result.raw_artifact is not None
    raw = result.raw_artifact
    assert raw.source_hash_sha256 == raw.preserved_hash_sha256
    assert raw.byte_size > 0
    assert raw.preservation_path


def test_preserve_file_updates_capability_to_preservable(tmp_path, monkeypatch):
    data_root = str(tmp_path / "data")
    source = tmp_path / "doc.md"
    source.write_text("content")

    cap = initialize_capability(source_ref=str(source), batch_id="b1").capability
    assert cap.preservable is False

    result = preserve_file(cap, data_root=data_root)

    assert result.capability.preservable is True
    assert result.capability.lifecycle_state == "preserved"
    assert result.capability.raw_artifact_id is not None


def test_preserve_file_does_not_mutate_source(tmp_path):
    data_root = str(tmp_path / "data")
    source = tmp_path / "note.md"
    content = "original content"
    source.write_text(content)
    original_mtime = source.stat().st_mtime

    cap = initialize_capability(source_ref=str(source), batch_id="b1").capability
    preserve_file(cap, data_root=data_root)

    assert source.read_text() == content
    assert source.stat().st_mtime == original_mtime


def test_preserve_file_canon_eligible_stays_false(tmp_path):
    data_root = str(tmp_path / "data")
    source = tmp_path / "doc.md"
    source.write_text("content")

    cap = initialize_capability(source_ref=str(source), batch_id="b1").capability
    result = preserve_file(cap, data_root=data_root)

    assert result.capability.canon_eligible is False


def test_preserve_file_emits_trace_event(tmp_path):
    data_root = str(tmp_path / "data")
    source = tmp_path / "doc.md"
    source.write_text("trace test")

    cap = initialize_capability(source_ref=str(source), batch_id="b1").capability
    result = preserve_file(cap, data_root=data_root)

    assert result.success is True
    assert len(result.trace_events) == 1
    te = result.trace_events[0]
    assert te.event_type == "preserved"
    assert te.intake_capability_id == cap.intake_capability_id


def test_preserve_file_trace_id_appended_to_capability(tmp_path):
    data_root = str(tmp_path / "data")
    source = tmp_path / "doc.md"
    source.write_text("content")

    cap = initialize_capability(source_ref=str(source), batch_id="b1").capability
    result = preserve_file(cap, data_root=data_root)

    for te in result.trace_events:
        assert te.trace_event_id in result.capability.trace_event_refs


def test_preserve_file_raw_artifact_has_correct_hashes(tmp_path):
    data_root = str(tmp_path / "data")
    source = tmp_path / "hashed.md"
    content = "checksum test content"
    source.write_bytes(content.encode("utf-8"))
    expected_hash = sha256_bytes(content.encode("utf-8"))

    cap = initialize_capability(source_ref=str(source), batch_id="b1").capability
    result = preserve_file(cap, data_root=data_root)

    assert result.success is True
    assert result.raw_artifact.source_hash_sha256 == expected_hash
    assert result.raw_artifact.preserved_hash_sha256 == expected_hash


# ---------------------------------------------------------------------------
# preserve_file — source registry
# ---------------------------------------------------------------------------

def test_preserve_file_appends_to_source_registry(tmp_path):
    data_root = str(tmp_path / "data")
    source = tmp_path / "doc.md"
    source.write_text("registry test")

    cap = initialize_capability(source_ref=str(source), batch_id="b1").capability
    preserve_file(cap, data_root=data_root)

    # Find the registry file
    registry_files = list(Path(data_root).rglob("source_registry.jsonl"))
    assert len(registry_files) == 1
    lines = registry_files[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["source_ref"].endswith("doc.md")
    assert entry["source_hash_sha256"]
    assert entry["byte_size"] > 0


def test_preserve_file_multiple_files_appends_registry(tmp_path):
    data_root = str(tmp_path / "data")

    for i in range(3):
        source = tmp_path / f"doc_{i}.md"
        source.write_text(f"content {i}")
        cap = initialize_capability(source_ref=str(source), batch_id="batch_multi").capability
        preserve_file(cap, data_root=data_root)

    registry_files = list(Path(data_root).rglob("source_registry.jsonl"))
    assert len(registry_files) == 1
    lines = registry_files[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3


# ---------------------------------------------------------------------------
# preserve_file — hash mismatch / quarantine
# ---------------------------------------------------------------------------

def test_preserve_file_hash_mismatch_quarantines(tmp_path, monkeypatch):
    """Simulate a hash mismatch by patching sha256_file to return different values."""
    data_root = str(tmp_path / "data")
    source = tmp_path / "doc.md"
    source.write_text("content")

    cap = initialize_capability(source_ref=str(source), batch_id="b1").capability

    call_count = [0]
    original_hash = sha256_file(str(source))

    def fake_hash(path: str) -> str:
        call_count[0] += 1
        if call_count[0] == 1:
            return original_hash          # source hash
        return "0" * 64                   # wrong preserved hash

    import app.services.intake.preservation as preservation_module
    monkeypatch.setattr(preservation_module, "sha256_file", fake_hash)

    result = preserve_file(cap, data_root=data_root)

    assert result.success is False
    assert result.quarantine_record is not None
    assert result.quarantine_record.quarantine_category == "failed_hash"
    assert result.capability.preservable is False
    assert result.capability.safety_lane == "quarantine"
    assert result.capability.lifecycle_state == "quarantined"
    assert result.failure_reason is not None
    assert "mismatch" in result.failure_reason.lower()


def test_preserve_file_hash_mismatch_blocks_downstream(tmp_path, monkeypatch):
    """After a hash mismatch, normalizable and interpretable must remain False."""
    data_root = str(tmp_path / "data")
    source = tmp_path / "doc.md"
    source.write_text("content")

    cap = initialize_capability(source_ref=str(source), batch_id="b1").capability

    call_count = [0]
    original_hash = sha256_file(str(source))

    def fake_hash(path: str) -> str:
        call_count[0] += 1
        return original_hash if call_count[0] == 1 else "badhash" * 8

    import app.services.intake.preservation as preservation_module
    monkeypatch.setattr(preservation_module, "sha256_file", fake_hash)

    result = preserve_file(cap, data_root=data_root)

    cap = result.capability
    assert cap.normalizable is False
    assert cap.interpretable is False
    assert cap.queryable is False
    assert cap.canon_eligible is False


# ---------------------------------------------------------------------------
# preserve_file — missing source
# ---------------------------------------------------------------------------

def test_preserve_file_missing_source_fails_gracefully(tmp_path):
    data_root = str(tmp_path / "data")
    cap = initialize_capability(source_ref="/nonexistent/source.md", batch_id="b1").capability
    result = preserve_file(cap, data_root=data_root)
    assert result.success is False
    assert result.failure_reason is not None
    assert result.capability.preservable is False
    assert result.capability.lifecycle_state == "failed"


# ---------------------------------------------------------------------------
# preserve_file — missing BOH_DATA_ROOT
# ---------------------------------------------------------------------------

def test_preserve_file_raises_without_data_root(tmp_path, monkeypatch):
    monkeypatch.delenv("BOH_DATA_ROOT", raising=False)
    source = tmp_path / "doc.md"
    source.write_text("content")
    cap = initialize_capability(source_ref=str(source), batch_id="b1").capability
    with pytest.raises(PreservationConfigError, match="BOH_DATA_ROOT"):
        preserve_file(cap)


# ---------------------------------------------------------------------------
# Batch manifest
# ---------------------------------------------------------------------------

def test_write_batch_manifest_creates_json_file(tmp_path):
    data_root = str(tmp_path / "data")
    source1 = tmp_path / "a.md"
    source2 = tmp_path / "b.md"
    source1.write_text("a")
    source2.write_text("b")

    cap1 = initialize_capability(source_ref=str(source1), batch_id="batch_x").capability
    cap2 = initialize_capability(source_ref=str(source2), batch_id="batch_x").capability
    r1 = preserve_file(cap1, data_root=data_root)
    r2 = preserve_file(cap2, data_root=data_root)

    write_batch_manifest(data_root, "batch_x", [r1, r2])

    manifests = list(Path(data_root).rglob("batch_manifest.json"))
    assert len(manifests) == 1
    m = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert m["batch_id"] == "batch_x"
    assert m["total"] == 2
    assert m["preserved"] == 2
    assert m["failed"] == 0


def test_write_batch_manifest_counts_failures(tmp_path, monkeypatch):
    data_root = str(tmp_path / "data")
    source = tmp_path / "ok.md"
    source.write_text("ok")

    cap_ok = initialize_capability(source_ref=str(source), batch_id="bm").capability
    r_ok = preserve_file(cap_ok, data_root=data_root)

    cap_fail = initialize_capability(source_ref="/nonexistent/fail.md", batch_id="bm").capability
    r_fail = preserve_file(cap_fail, data_root=data_root)

    write_batch_manifest(data_root, "bm", [r_ok, r_fail])

    manifests = list(Path(data_root).rglob("batch_manifest.json"))
    m = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert m["total"] == 2
    assert m["preserved"] == 1
    assert m["failed"] == 1
