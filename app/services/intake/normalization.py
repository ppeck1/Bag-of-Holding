"""Normalization service for the BOH Governed Ingestion & Translation Layer.

Executes the route decision produced by the translation router.  For each
eligible RawArtifact, runs the appropriate normalization path, produces a
NormalizedArtifact, and updates the IntakeCapability.

Supported normalization paths:
- direct_stage: copy preserved content as-is to 02_NORMALIZED/
- html_neutralize: strip scripts/forms/iframes using stdlib html.parser;
  record losses and warnings in the NormalizedArtifact

Held and quarantined routes produce no NormalizedArtifact; they update
the capability with failure_reason and return a NormalizationResult with
success=False.

No external libraries.  No database access.  No route or UI wiring.
"""

from __future__ import annotations

import html
import io
import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from app.core.planar_service_schemas import (
    AdapterRun,
    IntakeCapability,
    NormalizedArtifact,
    RawArtifact,
    TraceEvent,
    VersionProvenance,
)
from app.services.intake import trace as trace_module
from app.services.intake.hashing import sha256_file
from app.services.intake.translation_router import RouteDecision, RouteKind


class NormalizationConfigError(Exception):
    """Raised when BOH_DATA_ROOT is not configured."""


def _data_root() -> str:
    root = os.environ.get("BOH_DATA_ROOT", "")
    if not root:
        raise NormalizationConfigError(
            "BOH_DATA_ROOT is not set. Normalization requires an explicit data root."
        )
    return root


def _norm_dir(data_root: str, batch_id: str) -> Path:
    return Path(data_root) / "02_NORMALIZED" / batch_id


@dataclass
class NormalizationResult:
    source_ref: str
    route: RouteKind
    success: bool
    capability: IntakeCapability
    raw_artifact: RawArtifact
    normalized_artifact: NormalizedArtifact | None = None
    adapter_run: AdapterRun | None = None
    trace_events: list[TraceEvent] = field(default_factory=list)
    failure_reason: str | None = None


# ---------------------------------------------------------------------------
# HTML neutralizer (stdlib only)
# ---------------------------------------------------------------------------

class _HtmlNeutralizer(HTMLParser):
    """Strip scripts, forms, iframes, and on* attributes; extract text/structure."""

    _STRIP_TAGS = {"script", "style", "form", "iframe", "object", "embed", "applet", "noscript"}
    _VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._output: list[str] = []
        self.warnings: list[str] = []
        self._skip_depth = 0
        self._current_skip_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if self._skip_depth > 0:
            if tag_lower not in self._VOID_TAGS:
                self._skip_depth += 1
            return
        if tag_lower in self._STRIP_TAGS:
            self.warnings.append(f"{tag_lower}_stripped")
            if tag_lower not in self._VOID_TAGS:
                self._skip_depth += 1
                self._current_skip_tag = tag_lower
            return
        safe_attrs = []
        for name, value in attrs:
            if name.lower().startswith("on"):
                self.warnings.append("on_event_handler_stripped")
                continue
            if name.lower() in ("href", "src") and isinstance(value, str):
                if value.lower().startswith("javascript:"):
                    self.warnings.append("javascript_href_stripped")
                    continue
            safe_attrs.append((name, value))
        if tag_lower == "a" and safe_attrs:
            self._output.append(f"[{tag_lower}]")
        elif tag_lower in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._output.append(f"\n{'#' * int(tag_lower[1])} ")
        elif tag_lower == "p":
            self._output.append("\n")
        elif tag_lower == "br":
            self._output.append("\n")
        elif tag_lower == "li":
            self._output.append("\n- ")

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if self._skip_depth > 0:
            if tag_lower not in self._VOID_TAGS:
                self._skip_depth -= 1
            return
        if tag_lower in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li"):
            self._output.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        stripped = data.strip()
        if stripped:
            self._output.append(stripped + " ")

    def get_text(self) -> str:
        raw = "".join(self._output)
        lines = [line.rstrip() for line in raw.splitlines()]
        return "\n".join(line for line in lines if line).strip()


def neutralize_html(content: str) -> tuple[str, list[str]]:
    """Strip hostile HTML and return (neutralized_text, warnings)."""
    parser = _HtmlNeutralizer()
    parser.feed(content)
    return parser.get_text(), list(set(parser.warnings))


# ---------------------------------------------------------------------------
# Normalization entry point
# ---------------------------------------------------------------------------

def normalize(
    raw_artifact: RawArtifact,
    capability: IntakeCapability,
    decision: RouteDecision,
    data_root: str | None = None,
    policy_snapshot_hash: str | None = None,
) -> NormalizationResult:
    """Execute the normalization route for a single RawArtifact.

    Returns a NormalizationResult.  On success, capability.normalizable=True
    and a NormalizedArtifact is attached.  On hold/quarantine, success=False
    and no normalized output is produced.
    """
    root = data_root or _data_root()
    prov = VersionProvenance(policy_snapshot_hash=policy_snapshot_hash)
    source_ref = raw_artifact.source_ref
    batch_id = raw_artifact.batch_id

    if decision.route in ("hold", "quarantine", "ignore"):
        reason = decision.reason or f"Route '{decision.route}': normalization not performed."
        capability.normalizable = False
        capability.failure_reason = capability.failure_reason or reason
        te = trace_module.emit(
            f"normalization_{decision.route}",
            intake_capability_id=capability.intake_capability_id,
            detail={"source_ref": source_ref, "route": decision.route, "reason": reason},
        )
        capability.trace_event_refs.append(te.trace_event_id)
        return NormalizationResult(
            source_ref=source_ref, route=decision.route,
            success=False, capability=capability,
            raw_artifact=raw_artifact,
            failure_reason=reason,
            trace_events=[te],
        )

    # Locate the preserved file
    preservation_full_path = _resolve_preserved_path(raw_artifact, root)
    if preservation_full_path is None or not Path(preservation_full_path).exists():
        failure = f"Preserved file not found at expected path: {raw_artifact.preservation_path}"
        capability.normalizable = False
        capability.failure_reason = failure
        te = trace_module.emit(
            "normalization_failed",
            intake_capability_id=capability.intake_capability_id,
            detail={"source_ref": source_ref, "reason": failure},
        )
        capability.trace_event_refs.append(te.trace_event_id)
        return NormalizationResult(
            source_ref=source_ref, route=decision.route,
            success=False, capability=capability,
            raw_artifact=raw_artifact,
            failure_reason=failure,
            trace_events=[te],
        )

    # Execute normalization
    norm_dir = _norm_dir(root, batch_id)
    norm_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(source_ref).stem
    output_path = norm_dir / f"{capability.intake_capability_id[:8]}_{stem}.md"

    known_losses: list[str] = []
    warnings: list[str] = []

    try:
        if decision.route == "html_neutralize":
            raw_content = Path(preservation_full_path).read_text(encoding="utf-8", errors="replace")
            neutralized, html_warnings = neutralize_html(raw_content)
            output_path.write_text(neutralized, encoding="utf-8")
            warnings = html_warnings
            known_losses = ["interactive_behavior", "layout_precision", "script_behavior"]
            output_type = "markdown"
        else:  # direct_stage
            shutil.copy2(preservation_full_path, output_path)
            output_type = _infer_output_type(source_ref)

    except OSError as exc:
        failure = f"Normalization I/O error: {exc}"
        capability.normalizable = False
        capability.failure_reason = failure
        te = trace_module.emit(
            "normalization_failed",
            intake_capability_id=capability.intake_capability_id,
            detail={"source_ref": source_ref, "reason": failure},
        )
        capability.trace_event_refs.append(te.trace_event_id)
        return NormalizationResult(
            source_ref=source_ref, route=decision.route,
            success=False, capability=capability,
            raw_artifact=raw_artifact,
            failure_reason=failure,
            trace_events=[te],
        )

    output_hash = sha256_file(str(output_path))

    adapter_run = AdapterRun(
        adapter_id=decision.adapter_id,
        adapter_version="0.1.0",
        raw_artifact_id=raw_artifact.raw_artifact_id,
        intake_capability_id=capability.intake_capability_id,
        success=True,
        warnings=warnings,
        version_provenance=prov,
    )

    norm_artifact = NormalizedArtifact(
        raw_artifact_id=raw_artifact.raw_artifact_id,
        adapter_run_id=adapter_run.adapter_run_id,
        output_path=str(output_path.relative_to(root)) if str(output_path).startswith(root) else str(output_path),
        output_hash_sha256=output_hash,
        output_type=output_type,
        known_losses=known_losses,
        warnings=warnings,
        version_provenance=prov,
    )
    adapter_run.output_artifact_ids.append(norm_artifact.normalized_artifact_id)

    capability.normalizable = True
    capability.lifecycle_state = "normalized"

    te = trace_module.emit(
        "normalized",
        intake_capability_id=capability.intake_capability_id,
        detail={
            "source_ref": source_ref,
            "route": decision.route,
            "adapter_id": decision.adapter_id,
            "output_type": output_type,
            "warnings": warnings,
        },
    )
    capability.trace_event_refs.append(te.trace_event_id)

    return NormalizationResult(
        source_ref=source_ref, route=decision.route,
        success=True, capability=capability,
        raw_artifact=raw_artifact,
        normalized_artifact=norm_artifact,
        adapter_run=adapter_run,
        trace_events=[te],
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_preserved_path(raw: RawArtifact, data_root: str) -> str | None:
    """Resolve the full path of the preserved file from preservation_path."""
    preservation_path = raw.preservation_path
    if os.path.isabs(preservation_path):
        return preservation_path
    full = Path(data_root) / preservation_path
    return str(full) if full.exists() else None


def _infer_output_type(source_ref: str) -> str:
    ext = Path(source_ref).suffix.lower()
    return {
        ".md": "markdown", ".markdown": "markdown",
        ".txt": "text",
        ".json": "json", ".jsonl": "json",
        ".yaml": "yaml", ".yml": "yaml",
        ".csv": "csv",
        ".html": "markdown", ".htm": "markdown",
    }.get(ext, "text")
