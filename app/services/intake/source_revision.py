"""Deterministic source-revision identity for intake idempotency (WO-1).

Pure and side-effect-free. SQLite (`intake_source_revisions`) is the authoritative ledger;
this module only computes the stable identity used as the table's `source_revision_id` (PK)
and that matches its four-column UNIQUE identity:

    canonical_source_ref + source_hash_sha256 + policy_snapshot_hash + adapter_registry_version

`lifecycle_state` is deliberately NOT part of identity (it is mutable state).

The digest uses a FROZEN serialization (versioned canonical JSON array, not delimiter
concatenation) so a future refactor cannot silently change revision IDs — guarded by a golden
test. Bump `_DIGEST_VERSION` only as a deliberate, test-updating change.
"""

from __future__ import annotations

import hashlib
import json
import os

# Version prefix frozen into the digest input. Changing it changes every revision id by design.
_DIGEST_VERSION = "srid-v1"

# Explicit sentinels for "no policy bound" / "adapter registry unversioned". The identity tuple
# MUST NOT vary by whether a caller passes None, "", or an omitted value — every caller resolves
# missing values to these constants (also applied defensively inside compute_source_revision_id)
# so srid-v1 is stable across manual intake, replay, and scheduler execution. The resolved value
# is also what gets stored in the NOT NULL identity columns, keeping the digest and the table's
# UNIQUE identity aligned.
UNBOUND_POLICY_SNAPSHOT = "policy-unbound-v1"
UNVERSIONED_ADAPTER_REGISTRY = "adapter-registry-unversioned-v1"


def resolve_policy_snapshot(policy_snapshot_hash: str | None) -> str:
    return policy_snapshot_hash or UNBOUND_POLICY_SNAPSHOT


def resolve_adapter_registry_version(adapter_registry_version: str | None) -> str:
    return adapter_registry_version or UNVERSIONED_ADAPTER_REGISTRY


def canonicalize_source_ref(source_ref: str) -> str:
    """Normalize a source reference to a stable canonical string.

    Absolute path, forward slashes, and case-folded on case-insensitive filesystems (Windows)
    so the same file is not treated as a distinct revision merely because of path casing. Pure
    string normalization — does NOT touch the filesystem.
    """
    p = os.path.abspath(source_ref).replace("\\", "/")
    if os.name == "nt":
        p = p.casefold()
    return p


def compute_source_revision_id(
    *,
    canonical_source_ref: str,
    source_hash_sha256: str,
    policy_snapshot_hash: str | None = None,
    adapter_registry_version: str | None = None,
) -> str:
    """Deterministic sha256 digest of the four identity components.

    Inputs are expected to be already canonical (callers run `canonicalize_source_ref` on the
    path first). Missing policy/adapter values are resolved to explicit sentinels so None, ""
    and the sentinel all yield the SAME id. The resolved values are also what callers store in
    the NOT NULL identity columns.
    """
    payload = json.dumps(
        [
            _DIGEST_VERSION,
            canonical_source_ref,
            source_hash_sha256,
            resolve_policy_snapshot(policy_snapshot_hash),
            resolve_adapter_registry_version(adapter_registry_version),
        ],
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
