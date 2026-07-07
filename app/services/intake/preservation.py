"""Preservation service for the BOH Governed Ingestion & Translation Layer.

Copies eligible files from the watch path to a RAW staging area under
BOH_DATA_ROOT.  Hashes before and after copy; quarantines on mismatch.
Writes source_registry.jsonl and batch_manifest.json per batch.

Contract:
- Never writes to BOH_LIBRARY.
- Requires BOH_DATA_ROOT to be configured; fails closed if absent.
- Original source files are never mutated.
- A hash mismatch quarantines the artifact; downstream stages are blocked.
- canon_eligible remains False throughout.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.planar_service_schemas import (
    IntakeCapability,
    QuarantineRecord,
    RawArtifact,
    TraceEvent,
    VersionProvenance,
)
from app.services.intake import trace as trace_module
from app.services.intake.hashing import sha256_file


class PreservationConfigError(Exception):
    """Raised when BOH_DATA_ROOT is not configured."""


@dataclass
class PreservationResult:
    source_ref: str
    success: bool
    capability: IntakeCapability
    raw_artifact: RawArtifact | None = None
    quarantine_record: QuarantineRecord | None = None
    trace_events: list[TraceEvent] = field(default_factory=list)
    failure_reason: str | None = None


def _data_root() -> str:
    root = os.environ.get("BOH_DATA_ROOT", "")
    if not root:
        raise PreservationConfigError(
            "BOH_DATA_ROOT is not set. Preservation requires an explicit data root "
            "and must not silently default to BOH_LIBRARY."
        )
    return root


def _raw_dir(data_root: str, batch_id: str) -> Path:
    today = time.strftime("%Y-%m-%d", time.gmtime())
    return Path(data_root) / "01_RAW" / today / batch_id / "files"


def _registry_path(data_root: str, batch_id: str) -> Path:
    today = time.strftime("%Y-%m-%d", time.gmtime())
    return Path(data_root) / "01_RAW" / today / batch_id / "source_registry.jsonl"


def _manifest_path(data_root: str, batch_id: str) -> Path:
    today = time.strftime("%Y-%m-%d", time.gmtime())
    return Path(data_root) / "01_RAW" / today / batch_id / "batch_manifest.json"


def preserve_file(
    capability: IntakeCapability,
    data_root: str | None = None,
    policy_snapshot_hash: str | None = None,
) -> PreservationResult:
    """Preserve a single file to RAW storage.

    Steps:
    1. Hash the source file.
    2. Copy to RAW directory.
    3. Hash the copy and verify equality.
    4. Update IntakeCapability.
    5. Emit trace events.
    6. Append to source_registry.jsonl.

    Returns a PreservationResult with success=True and a RawArtifact on success,
    or success=False with a QuarantineRecord on hash mismatch or I/O error.
    """
    root = data_root or _data_root()
    source = capability.source_ref
    batch_id = capability.batch_id
    prov = VersionProvenance(policy_snapshot_hash=policy_snapshot_hash)

    # Stage 1: hash the source
    try:
        source_hash = sha256_file(source)
    except OSError as exc:
        failure = f"Cannot read source file for hashing: {exc}"
        _update_capability_failed(capability, failure)
        te = trace_module.emit(
            "preservation_failed",
            intake_capability_id=capability.intake_capability_id,
            detail={"source_ref": source, "reason": failure},
        )
        capability.trace_event_refs.append(te.trace_event_id)
        return PreservationResult(
            source_ref=source, success=False,
            capability=capability, failure_reason=failure,
            trace_events=[te],
        )

    source_size = os.path.getsize(source)

    # Stage 2: copy to RAW
    raw_dir = _raw_dir(root, batch_id)
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / Path(source).name
    # Avoid filename collision by appending capability id suffix
    if dest.exists():
        dest = raw_dir / f"{capability.intake_capability_id[:8]}_{Path(source).name}"

    try:
        shutil.copy2(source, dest)
    except OSError as exc:
        failure = f"Copy to RAW failed: {exc}"
        try:  # remove any partial copy — leave no orphan RAW file at the success location
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        _update_capability_failed(capability, failure)
        te = trace_module.emit(
            "preservation_failed",
            intake_capability_id=capability.intake_capability_id,
            detail={"source_ref": source, "reason": failure},
        )
        capability.trace_event_refs.append(te.trace_event_id)
        return PreservationResult(
            source_ref=source, success=False,
            capability=capability, failure_reason=failure,
            trace_events=[te],
        )

    # Stage 3: verify hash
    try:
        preserved_hash = sha256_file(str(dest))
    except OSError as exc:
        failure = f"Cannot hash preserved copy: {exc}"
        try:  # remove the unverified copy — leave no orphan RAW file at the success location
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        _update_capability_failed(capability, failure)
        te = trace_module.emit(
            "preservation_failed",
            intake_capability_id=capability.intake_capability_id,
            detail={"source_ref": source, "reason": failure},
        )
        capability.trace_event_refs.append(te.trace_event_id)
        return PreservationResult(
            source_ref=source, success=False,
            capability=capability, failure_reason=failure,
            trace_events=[te],
        )

    if source_hash != preserved_hash:
        failure = (
            f"Hash mismatch after copy: source={source_hash[:16]}... "
            f"preserved={preserved_hash[:16]}..."
        )
        _update_capability_failed(capability, failure)
        te_fail = trace_module.emit(
            "preservation_hash_mismatch",
            intake_capability_id=capability.intake_capability_id,
            detail={"source_ref": source, "source_hash": source_hash, "preserved_hash": preserved_hash},
        )
        capability.trace_event_refs.append(te_fail.trace_event_id)
        capability.safety_lane = "quarantine"
        capability.lifecycle_state = "quarantined"

        qr = QuarantineRecord(
            intake_capability_id=capability.intake_capability_id,
            quarantine_reason=failure,
            quarantine_category="failed_hash",
            version_provenance=prov,
        )
        # Remove the corrupted copy
        try:
            dest.unlink()
        except OSError:
            pass
        return PreservationResult(
            source_ref=source, success=False,
            capability=capability,
            quarantine_record=qr,
            failure_reason=failure,
            trace_events=[te_fail],
        )

    # Stage 4: update capability
    preservation_path = str(dest.relative_to(Path(root))) if str(dest).startswith(root) else str(dest)
    raw = RawArtifact(
        intake_capability_id=capability.intake_capability_id,
        source_ref=source,
        batch_id=batch_id,
        source_hash_sha256=source_hash,
        preserved_hash_sha256=preserved_hash,
        byte_size=source_size,
        preservation_path=preservation_path,
        version_provenance=prov,
    )
    capability.raw_artifact_id = raw.raw_artifact_id
    capability.preservable = True
    capability.lifecycle_state = "preserved"

    te_ok = trace_module.emit(
        "preserved",
        intake_capability_id=capability.intake_capability_id,
        detail={
            "source_ref": source,
            "preservation_path": preservation_path,
            "source_hash": source_hash,
            "byte_size": source_size,
        },
    )
    capability.trace_event_refs.append(te_ok.trace_event_id)

    # Stage 5: append source registry entry. The JSONL registry is a rebuildable compatibility
    # artifact, NOT the authoritative ledger (SQLite is), so a write failure here must not fail
    # preservation or roll back the downstream SQLite transition — log it structurally instead.
    try:
        _append_registry(root, batch_id, raw)
    except OSError:
        logging.getLogger(__name__).warning(
            "source_registry.jsonl append failed for %s (compatibility artifact; SQLite is "
            "authoritative)", raw.raw_artifact_id, exc_info=True,
        )

    return PreservationResult(
        source_ref=source, success=True,
        capability=capability,
        raw_artifact=raw,
        trace_events=[te_ok],
    )


def write_batch_manifest(
    data_root: str,
    batch_id: str,
    results: list[PreservationResult],
) -> None:
    """Write (or overwrite) the batch_manifest.json for a completed batch."""
    manifest = {
        "batch_id": batch_id,
        "total": len(results),
        "preserved": sum(1 for r in results if r.success),
        "failed": sum(1 for r in results if not r.success),
        "quarantined": sum(1 for r in results if r.quarantine_record is not None),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    path = _manifest_path(data_root, batch_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _update_capability_failed(capability: IntakeCapability, reason: str) -> None:
    capability.preservable = False
    capability.failure_reason = reason
    capability.lifecycle_state = "failed"


# Per-registry-path single-writer locks: append-only avoids rewrite races, but a lock is still
# required so concurrent sibling workers cannot interleave partial JSON lines in the same file.
_REGISTRY_LOCKS: dict[str, threading.Lock] = {}
_REGISTRY_LOCKS_GUARD = threading.Lock()


def _registry_lock(reg_path: str) -> threading.Lock:
    key = os.path.normcase(os.path.abspath(reg_path))
    with _REGISTRY_LOCKS_GUARD:
        lk = _REGISTRY_LOCKS.get(key)
        if lk is None:
            lk = threading.Lock()
            _REGISTRY_LOCKS[key] = lk
        return lk


def _write_registry_line(reg_path: Path, entry: dict, *, fsync: bool = False) -> None:
    """Append ONE complete JSON line under the per-path single-writer lock (no interleaving). When
    `fsync` is set the line is durably flushed to disk before returning."""
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry) + "\n"
    with _registry_lock(str(reg_path)):
        with open(reg_path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            if fsync:
                os.fsync(f.fileno())


def _append_registry(data_root: str, batch_id: str, raw: RawArtifact) -> None:
    _write_registry_line(_registry_path(data_root, batch_id), {
        "raw_artifact_id": raw.raw_artifact_id,
        "intake_capability_id": raw.intake_capability_id,
        "source_ref": raw.source_ref,
        "source_hash_sha256": raw.source_hash_sha256,
        "preserved_hash_sha256": raw.preserved_hash_sha256,
        "byte_size": raw.byte_size,
        "preservation_path": raw.preservation_path,
    })


def invalidate_registry_entry(data_root: str | None, batch_id: str, raw: RawArtifact,
                              reason: str) -> bool:
    """DURABLY append a tombstone to source_registry.jsonl invalidating a previously-appended
    preservation entry whose RAW artifact is being rejected (e.g. the source changed between claim
    and preservation). Returns True iff the tombstone is durably persisted (flush + fsync).

    Registry folding rule: for each `raw_artifact_id`, an `{"event":"invalidated"}` record DOMINATES
    any earlier preservation record; invalidated artifacts are excluded from ordinary RAW
    projections; SQLite remains authoritative if registry and ledger disagree. The JSONL registry is
    append-only and NON-authoritative, so reconciliation is a tombstone, never a rewrite (which keeps
    it concurrency-safe for sibling appends in the same batch)."""
    root = data_root or _data_root()
    reg_path = _registry_path(root, batch_id)
    entry = {
        "event": "invalidated",
        "raw_artifact_id": raw.raw_artifact_id,
        "intake_capability_id": raw.intake_capability_id,
        "preservation_path": raw.preservation_path,
        "reason": reason,
        "invalidated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        _write_registry_line(reg_path, entry, fsync=True)
        return True
    except OSError:
        logging.getLogger(__name__).warning(
            "source_registry.jsonl tombstone append failed for %s (compatibility artifact; SQLite is "
            "authoritative)", raw.raw_artifact_id, exc_info=True)
        return False
