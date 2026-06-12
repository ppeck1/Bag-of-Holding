"""Adapter Registry for the BOH Governed Ingestion & Translation Layer.

Loads AdapterMetadata declarations, matches files by extension or media type,
and produces coverage reports.  Pure in-memory — no database access, no file I/O,
no network calls, no route wiring.

Registry lookup contract:
- Every registered adapter has a unique adapter_id.
- Extension matching is case-insensitive and dot-prefixed.
- When a file matches no registered adapter, the unsupported adapter is returned
  with required_adapter set to the adapter_id that would be needed if one existed.
- No adapter may declare executes_content=True or fetches_remote_assets=True.
- No adapter may set canon_eligible=True on any record (enforced at schema level).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.core.planar_service_schemas import AdapterMetadata
from app.services.intake.adapters import (
    archive_hold,
    code_direct,
    csv_direct,
    docx_hold,
    executable_block,
    html_adapter,
    image_hold,
    json_direct,
    markdown_direct,
    pdf_hold,
    text_direct,
    unsupported,
    yaml_direct,
)


# Ordered list — earlier entries win on extension conflict.
_ADAPTER_MODULES = [
    markdown_direct,
    text_direct,
    code_direct,
    json_direct,
    yaml_direct,
    csv_direct,
    html_adapter,
    pdf_hold,
    docx_hold,
    image_hold,
    archive_hold,
    executable_block,
]

_UNSUPPORTED = unsupported.METADATA


class AdapterRegistry:
    """In-memory registry of AdapterMetadata declarations."""

    def __init__(self) -> None:
        self._by_id: dict[str, AdapterMetadata] = {}
        self._by_ext: dict[str, str] = {}   # ext → adapter_id
        self._by_media: dict[str, str] = {}  # media_type → adapter_id

        for module in _ADAPTER_MODULES:
            self._register(module.METADATA)
        # Unsupported is always the fallback — do not register its extensions
        self._by_id[_UNSUPPORTED.adapter_id] = _UNSUPPORTED

        self._validate()

    def _register(self, meta: AdapterMetadata) -> None:
        if meta.adapter_id in self._by_id:
            raise ValueError(f"Duplicate adapter_id: {meta.adapter_id}")
        self._by_id[meta.adapter_id] = meta
        for ext in meta.supported_extensions:
            key = ext.lower()
            if key not in self._by_ext:
                self._by_ext[key] = meta.adapter_id
        for mt in meta.supported_media_types:
            key = mt.lower()
            if key not in self._by_media:
                self._by_media[key] = meta.adapter_id

    def _validate(self) -> None:
        for meta in self._by_id.values():
            if meta.executes_content:
                raise ValueError(
                    f"Adapter {meta.adapter_id} declares executes_content=True — prohibited"
                )
            if meta.fetches_remote_assets:
                raise ValueError(
                    f"Adapter {meta.adapter_id} declares fetches_remote_assets=True — prohibited"
                )

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get_by_id(self, adapter_id: str) -> AdapterMetadata | None:
        return self._by_id.get(adapter_id)

    def match_extension(self, extension: str) -> AdapterMetadata | None:
        """Return adapter for a dot-prefixed extension, or None."""
        key = extension.lower()
        if not key.startswith("."):
            key = "." + key
        adapter_id = self._by_ext.get(key)
        if adapter_id:
            return self._by_id[adapter_id]
        return None

    def match_media_type(self, media_type: str) -> AdapterMetadata | None:
        """Return adapter for a media type string, or None."""
        key = media_type.lower().split(";")[0].strip()
        adapter_id = self._by_media.get(key)
        if adapter_id:
            return self._by_id[adapter_id]
        return None

    def resolve(self, path: str, media_type: str | None = None) -> tuple[AdapterMetadata, str | None, str | None]:
        """Return (adapter, required_adapter, failure_reason) for a file path.

        - adapter: the matched adapter (may be unsupported fallback)
        - required_adapter: set when the file type is known but no adapter is installed
        - failure_reason: human-readable explanation when the file cannot be processed
        """
        ext = Path(path).suffix.lower()
        meta = self.match_extension(ext)
        if meta is None and media_type:
            meta = self.match_media_type(media_type)

        if meta is not None:
            required_adapter = None
            failure_reason = None
            if not meta.can_normalize:
                required_adapter = meta.adapter_id
                failure_reason = f"Adapter '{meta.adapter_id}' cannot normalize this file type; sandbox or interpreter required."
            return meta, required_adapter, failure_reason

        # Truly unknown — return unsupported fallback
        required_adapter = f"adapter_for_{ext.lstrip('.') or 'unknown'}" if ext else "adapter_for_unknown"
        failure_reason = f"No adapter registered for extension '{ext or '(none)'}'. File held pending adapter installation."
        return _UNSUPPORTED, required_adapter, failure_reason

    # ------------------------------------------------------------------
    # Coverage report
    # ------------------------------------------------------------------

    def all_adapters(self) -> list[AdapterMetadata]:
        return list(self._by_id.values())

    def coverage_report(self) -> dict[str, Any]:
        """Return a report of all registered adapters and their capabilities."""
        rows = []
        for ext, adapter_id in sorted(self._by_ext.items()):
            meta = self._by_id[adapter_id]
            rows.append({
                "extension": ext,
                "adapter_id": adapter_id,
                "adapter_version": meta.adapter_version,
                "can_preserve": meta.can_preserve,
                "can_normalize": meta.can_normalize,
                "can_interpret": meta.can_interpret,
                "can_make_queryable": meta.can_make_queryable,
                "requires_sandbox": meta.requires_sandbox,
                "default_safety_lane": meta.default_safety_lane,
            })
        return {
            "adapter_count": len(self._by_id),
            "extension_count": len(self._by_ext),
            "rows": rows,
        }

    def capability_summary(self) -> dict[str, list[str]]:
        """Return extension lists grouped by capability."""
        preservable, normalizable, interpretable, queryable, blocked, held = [], [], [], [], [], []
        for ext, adapter_id in sorted(self._by_ext.items()):
            meta = self._by_id[adapter_id]
            if meta.default_safety_lane == "quarantine" and not meta.can_preserve:
                blocked.append(ext)
            elif not meta.can_normalize:
                held.append(ext)
            else:
                if meta.can_preserve:
                    preservable.append(ext)
                if meta.can_normalize:
                    normalizable.append(ext)
                if meta.can_interpret:
                    interpretable.append(ext)
                if meta.can_make_queryable:
                    queryable.append(ext)
        return {
            "preservable": preservable,
            "normalizable": normalizable,
            "interpretable": interpretable,
            "queryable": queryable,
            "held_pending_adapter": held,
            "blocked": blocked,
        }


# ----------------------------------------------------------------------
# Deterministic adapter-registry fingerprint (WO-1.1 Phase B)
# ----------------------------------------------------------------------

# Frozen version prefix for the fingerprint serialization. Bump only as a deliberate change.
_FINGERPRINT_VERSION = "adapterfp-v1"


def _adapter_payload(meta: AdapterMetadata) -> dict[str, Any]:
    """Canonical, transformation-relevant projection of one adapter's contract. List fields are
    sorted so incidental ordering never affects the fingerprint."""
    return {
        "adapter_id": meta.adapter_id,
        "adapter_version": meta.adapter_version,
        "supported_extensions": sorted(e.lower() for e in meta.supported_extensions),
        "supported_media_types": sorted(t.lower() for t in meta.supported_media_types),
        "can_preserve": meta.can_preserve,
        "can_normalize": meta.can_normalize,
        "can_interpret": meta.can_interpret,
        "can_make_queryable": meta.can_make_queryable,
        "requires_sandbox": meta.requires_sandbox,
        "fetches_remote_assets": meta.fetches_remote_assets,
        "executes_content": meta.executes_content,
        "output_types": sorted(meta.output_types),
        "known_losses": sorted(meta.known_losses),
        "warning_types": sorted(meta.warning_types),
        "default_safety_lane": meta.default_safety_lane,
    }


def _fingerprint_from(adapters: list[AdapterMetadata], by_ext: dict[str, str],
                      by_media: dict[str, str]) -> str:
    """Deterministic fingerprint over adapter contracts + RESOLVED routing. Adapters are sorted by
    id and routing maps are sorted, so the value is invariant to registration/insertion order while
    still reacting to a genuine contract change (new/changed adapter or changed conflict resolution).
    """
    payload = sorted((_adapter_payload(m) for m in adapters), key=lambda d: d["adapter_id"])
    routing = {
        "by_extension": sorted(by_ext.items()),
        "by_media_type": sorted(by_media.items()),
    }
    blob = json.dumps([_FINGERPRINT_VERSION, payload, routing],
                      separators=(",", ":"), sort_keys=True, ensure_ascii=True)
    return f"{_FINGERPRINT_VERSION}:{hashlib.sha256(blob.encode('utf-8')).hexdigest()[:32]}"


def adapter_registry_fingerprint(registry: AdapterRegistry | None = None) -> str:
    """Deterministic fingerprint of the active adapter registry's transformation contract. Stable
    across registration order and process startup; changes when any adapter's contract or the
    resolved routing changes. Used as `adapter_registry_version` in source-revision identity so a
    transformation-contract change mints a NEW revision even when source bytes are unchanged."""
    reg = registry or get_registry()
    return _fingerprint_from(reg.all_adapters(), reg._by_ext, reg._by_media)


# Module-level singleton — re-create if adapter modules change.
_registry: AdapterRegistry | None = None


def get_registry() -> AdapterRegistry:
    global _registry
    if _registry is None:
        _registry = AdapterRegistry()
    return _registry
