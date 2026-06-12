"""Phase 14 metadata contract and authority-state helpers.

This module is intentionally deterministic. It does not infer authority from
content. Documents become governed only when explicit metadata is present.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

REQUIRED_GOVERNED_FIELDS = (
    "project",
    "document_class",
    "status",
    "canonical_layer",
    "title",
    "provenance",
    "source_hash",
    "document_id",
)

STATUS_VALUES = {
    "raw", "draft", "scratch", "legacy", "quarantine",
    "review_required", "review_artifact", "approved_patch",
    "canonical_candidate", "canonical", "canonical_update",
    "superseded", "archived", "conflict",
    "imported_non_authoritative", "overwritten_by_import",  # tracked but blocked
}
CANONICAL_LAYERS = {"scratch", "canonical", "supporting", "evidence", "review", "conflict", "archive", "quarantine"}
DOCUMENT_CLASSES = {"formal_system", "architecture", "whitepaper", "source", "note", "reference", "evidence", "review", "import", "legacy", "unknown"}
AUTHORITY_STATES = {"non_authoritative", "draft", "review_required", "approved", "canonical", "superseded", "archived", "quarantined"}

@dataclass
class ValidationError:
    field: str
    code: str
    message: str


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_resolve_under(root: str | Path, rel_path: str | Path) -> Path:
    root_p = Path(root).resolve()
    raw = str(rel_path or "")
    if not raw:
        raise ValueError("Path is empty")
    p = Path(raw)
    if p.is_absolute() or re.match(r"^[A-Za-z]:[/\\]", raw) or raw.startswith("\\\\"):
        raise ValueError(f"Absolute paths are not allowed: {raw!r}")
    target = (root_p / p).resolve()
    try:
        target.relative_to(root_p)
    except ValueError as exc:
        raise ValueError(f"Path traversal rejected: {raw!r}") from exc
    return target


def _clean_scalar(value: Any) -> str:
    return str(value or "").strip()


def normalize_project(value: Any) -> str:
    v = _clean_scalar(value)
    return v or "Quarantine / Legacy Import"


def legacy_metadata(path: str, boh: dict | None, content_hash: str) -> dict:
    boh = boh or {}
    return {
        "project": "Quarantine / Legacy Import",
        "document_class": boh.get("type") or "legacy",
        "status": "legacy" if boh.get("status") not in {"canonical", "archived"} else boh.get("status"),
        "canonical_layer": "quarantine" if boh.get("status") not in {"canonical", "archived"} else ("canonical" if boh.get("status") == "canonical" else "archive"),
        "title": boh.get("title") or boh.get("purpose") or Path(path).stem.replace("-", " ").replace("_", " ").title(),
        "provenance": boh.get("provenance") or {"mode": "legacy_auto_migration", "path": path},
        "source_hash": boh.get("source_hash") or content_hash,
        "document_id": boh.get("document_id") or boh.get("id") or f"legacy-{uuid.uuid5(uuid.NAMESPACE_URL, path).hex[:12]}",
        "authority_state": "quarantined",
        "review_state": "unassigned",
    }


def extract_contract(boh: dict | None, path: str, content_hash: str, allow_legacy: bool = True) -> tuple[dict, list[dict]]:
    errors: list[ValidationError] = []
    b = boh or {}
    meta = {
        "project": b.get("project"),
        "document_class": b.get("document_class") or b.get("type"),
        "status": b.get("status"),
        "canonical_layer": b.get("canonical_layer"),
        "title": b.get("title") or b.get("purpose"),
        "provenance": b.get("provenance"),
        "source_hash": b.get("source_hash"),
        "document_id": b.get("document_id") or b.get("id"),
        "authority_state": b.get("authority_state"),
        "review_state": b.get("review_state"),
    }
    missing = [f for f in REQUIRED_GOVERNED_FIELDS if meta.get(f) in (None, "", [])]
    if missing and allow_legacy:
        lm = legacy_metadata(path, b, content_hash)
        for k, v in lm.items():
            if meta.get(k) in (None, "", []):
                meta[k] = v
        errors.append(ValidationError("boh", "legacy_quarantine", "Missing governed metadata; indexed in Quarantine / Legacy Import."))
    else:
        for f in missing:
            errors.append(ValidationError(f, "required", f"Governed import requires {f}."))

    meta["project"] = normalize_project(meta.get("project"))
    meta["document_class"] = _clean_scalar(meta.get("document_class") or "unknown")
    meta["status"] = _clean_scalar(meta.get("status") or "draft")
    meta["canonical_layer"] = _clean_scalar(meta.get("canonical_layer") or "supporting")
    meta["title"] = _clean_scalar(meta.get("title") or Path(path).stem)
    meta["source_hash"] = _clean_scalar(meta.get("source_hash") or content_hash)
    meta["document_id"] = _clean_scalar(meta.get("document_id"))
    meta["authority_state"] = _clean_scalar(meta.get("authority_state") or authority_for_status(meta["status"], meta["canonical_layer"]))
    meta["review_state"] = _clean_scalar(meta.get("review_state") or default_review_state(meta["status"]))

    if meta["status"] not in STATUS_VALUES:
        errors.append(ValidationError("status", "enum", f"Invalid status {meta['status']!r}."))
    if meta["canonical_layer"] not in CANONICAL_LAYERS:
        errors.append(ValidationError("canonical_layer", "enum", f"Invalid canonical_layer {meta['canonical_layer']!r}."))
    if meta["authority_state"] not in AUTHORITY_STATES:
        errors.append(ValidationError("authority_state", "enum", f"Invalid authority_state {meta['authority_state']!r}."))
    if meta["status"] == "canonical" and meta["canonical_layer"] != "canonical":
        errors.append(ValidationError("canonical_layer", "state", "status=canonical requires canonical_layer=canonical."))
    if meta["canonical_layer"] == "canonical" and meta["authority_state"] != "canonical":
        errors.append(ValidationError("authority_state", "state", "canonical layer requires authority_state=canonical."))
    if not meta["document_id"]:
        errors.append(ValidationError("document_id", "required", "document_id is required."))

    return meta, [asdict(e) for e in errors]


def authority_for_status(status: str, layer: str) -> str:
    if status == "canonical" and layer == "canonical": return "canonical"
    if status == "superseded": return "superseded"
    if status == "archived" or layer == "archive": return "archived"
    if status == "review_required": return "review_required"
    if status == "review_artifact": return "non_authoritative"
    if status in {"scratch", "legacy"} or layer in {"scratch", "quarantine"}: return "quarantined"
    return "draft"


def default_review_state(status: str) -> str:
    return {
        "canonical": "approved",
        "review_required": "pending",
        "review_artifact": "pending",
        "approved_patch": "approved",
        "legacy": "unassigned",
        "scratch": "unassigned",
    }.get(status, "none")


def can_transition(old_status: str | None, new_status: str, approved: bool = False) -> tuple[bool, str]:
    """Validate an authority state transition.

    Design principle: separate safe non-authoritative intake from canonical promotion.
    - Documents may freely enter and move between non-authoritative states.
    - Canonical promotion requires explicit approval.
    - Canonical documents cannot be overwritten by any import or LLM output.
    """
    old = old_status or "raw"
    if new_status == old:
        return True, "same status"

    # ── Hard blocks: canonical cannot be overwritten ──────────────────────────
    CANONICAL_OVERWRITE_BLOCKED = {
        "overwritten_by_import", "overwritten_by_llm", "overwritten_by_review_artifact",
    }
    if old == "canonical" and new_status not in {"superseded", "archived"}:
        return False, f"Canonical documents cannot be overwritten or demoted by import (tried: {old} -> {new_status})."
    if new_status in CANONICAL_OVERWRITE_BLOCKED:
        return False, f"Transition to {new_status!r} is never allowed."

    # ── Canonical promotion always requires explicit approval ─────────────────
    if new_status == "canonical" and not approved:
        return False, "Canonical promotion requires explicit approval (approved=True)."

    # ── Non-authoritative intake: always allowed ──────────────────────────────
    # Documents may freely enter any non-authoritative state from raw/new.
    NON_AUTH_STATES = {
        "raw", "draft", "scratch", "legacy", "quarantine",
        "review_required", "imported_non_authoritative",
    }
    if old in NON_AUTH_STATES and new_status in NON_AUTH_STATES:
        return True, "allowed non-authoritative intake transition"
    if old == "raw" and new_status in NON_AUTH_STATES:
        return True, "allowed raw intake"
    # New documents (no prior state) can enter any non-authoritative state
    if old == "raw":
        return True, "new document — any non-authoritative intake allowed"

    # ── Promotion ladder ──────────────────────────────────────────────────────
    PROMOTION_ALLOWED = {
        ("draft", "review_required"),
        ("draft", "canonical_candidate"),
        ("draft", "canonical"),           # requires approved=True (checked above)
        ("draft", "archived"),
        ("scratch", "draft"),
        ("scratch", "quarantine"),
        ("scratch", "archived"),
        ("legacy", "draft"),
        ("legacy", "quarantine"),
        ("legacy", "archived"),
        ("quarantine", "draft"),
        ("quarantine", "legacy"),
        ("quarantine", "archived"),
        ("review_required", "canonical_candidate"),
        ("review_required", "canonical"),  # requires approved=True
        ("canonical_candidate", "canonical"),
        ("review_artifact", "approved_patch"),
        ("approved_patch", "canonical_update"),
        ("approved_patch", "canonical"),  # requires approved=True
        ("canonical", "superseded"),
        ("canonical", "archived"),
        ("imported_non_authoritative", "draft"),
        ("imported_non_authoritative", "review_required"),
    }
    if (old, new_status) in PROMOTION_ALLOWED:
        return True, "allowed promotion transition"

    # ── Re-index: same non-authoritative state or minor updates ──────────────
    if old in NON_AUTH_STATES and new_status == old:
        return True, "re-index same state"

    # ── Anything not explicitly allowed is disallowed ────────────────────────
    return False, f"Disallowed authority transition: {old} -> {new_status}."
