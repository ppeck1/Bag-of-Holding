"""Context Assembly -- a single read-only deterministic labeled-pack builder.

This is a thin composition layer over the existing, individually-tested Phase 6
primitives. It introduces NO new gate policy: it calls the established gate
(`planar_gate.evaluate_context_pack`) and metadata builder
(`context_pack.build_context_pack`, via the gate) and assembles their results
into one labeled `AssembledContextPack` so downstream consumers (the Phase 7
Context Pack Builder UI, answer-context callers) read from one stable surface.

Composed components:
  - app.core.planar_gate.evaluate_context_pack -> posture, allowed/withheld refs
  - app.core.context_pack (normalize_plane, plane_from_pack, pack_ref)

Read-only by contract: this service performs no writes, never mutates the DB,
and never sets canon_eligible. It is deterministic -- the same inputs yield an
equal AssembledContextPack.to_dict() (no wall-clock field is included).

Gate is authoritative: content is drawn ONLY from gate-allowed refs. Withheld
refs appear solely in the `withheld` declaration, never in a content section or
the source map. A `blocked` posture yields empty content -- nothing bypasses a
failed gate.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from app.core import context_pack as cp
from app.core import planar_gate


# The five buildspec acceptance section labels.
SECTION_LABELS = ["canon", "evidence", "interpretation", "conflict", "open_questions"]

# Normalized plane (post cp.normalize_plane) -> content section label.
# `conflict` is never assigned by plane; it is a cross-listing (see _has_conflict).
_PLANE_TO_SECTION = {
    "canonical": "canon",
    "evidence": "evidence",
    "subjective": "interpretation",
    "review": "open_questions",
    "informational": "evidence",
    "internal": "evidence",
}
_DEFAULT_SECTION = "evidence"

_BLOCKED = "blocked"


def _stable_pack_id(
    context_pack_id: str,
    posture: str,
    sections: dict[str, list[dict[str, Any]]],
    withheld_refs: list[str],
) -> str:
    raw = json.dumps(
        {
            "context_pack_id": context_pack_id,
            "posture": posture,
            "sections": {label: sorted(e.get("ref", "") for e in entries) for label, entries in sections.items()},
            "withheld_refs": sorted(withheld_refs),
        },
        sort_keys=True,
        default=str,
    )
    return "acp_" + hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:24]


@dataclass
class AssembledContextPack:
    """Labeled, deterministic, read-only context pack for one evaluation.

    Carries no wall-clock field so it is reproducible. canon_eligible is
    re-forced to False -- this service never grants canon eligibility.
    """

    context_pack_id: str
    posture: str
    operation: str
    sections: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    source_map: dict[str, dict[str, Any]] = field(default_factory=dict)
    withheld: dict[str, Any] = field(default_factory=dict)
    missing_planes: list[str] = field(default_factory=list)
    blocking_reasons: list[str] = field(default_factory=list)
    warning_reasons: list[str] = field(default_factory=list)
    canon_eligible: bool = False  # INVARIANT: always False
    assembled_pack_id: str = ""

    def __post_init__(self) -> None:
        self.canon_eligible = False
        for label in SECTION_LABELS:
            self.sections.setdefault(label, [])
        if not self.assembled_pack_id:
            self.assembled_pack_id = _stable_pack_id(
                self.context_pack_id, self.posture, self.sections, list(self.withheld.get("refs") or [])
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _locator(pack: dict[str, Any], ref: str) -> str:
    return str(pack.get("path") or pack.get("source_ref") or pack.get("doc_id") or ref)


def _source(pack: dict[str, Any]) -> str:
    return str(pack.get("doc_id") or pack.get("source_ref") or pack.get("path") or "")


def _has_conflict(pack: dict[str, Any]) -> bool:
    return bool(pack.get("conflicts")) or bool(pack.get("conflict_set_ref"))


def _entry(ref: str, pack: dict[str, Any], plane: str) -> dict[str, Any]:
    return {
        "ref": ref,
        "plane": plane,
        "title": str(pack.get("title") or ref),
        "snippet": str(pack.get("snippet") or pack.get("text") or ""),
        "source": _source(pack),
    }


def assemble(
    *,
    query: str,
    operation: str,
    actor: str | dict[str, Any] | None,
    mode: str,
    candidate_packs: list[dict[str, Any]],
    governance_health: dict[str, Any] | None = None,
) -> AssembledContextPack:
    """Compose the gate decision + metadata into one labeled AssembledContextPack.

    Pure composition over `planar_gate.evaluate_context_pack`: content is placed
    only from gate-allowed refs; withheld refs are declared separately; a blocked
    posture yields empty content sections. Performs no writes and is deterministic
    for fixed inputs (the gate's wall-clock `created_ts` is intentionally excluded).
    """
    context, gate = planar_gate.evaluate_context_pack(
        query=query,
        operation=operation,
        actor=actor,
        mode=mode,
        candidate_packs=candidate_packs,
        governance_health=governance_health,
    )

    posture = gate["posture"]
    blocked = posture == _BLOCKED
    allowed = set(gate.get("allowed_context_refs") or [])
    withheld_refs = list(dict.fromkeys(gate.get("withheld_context_refs") or []))

    sections: dict[str, list[dict[str, Any]]] = {label: [] for label in SECTION_LABELS}
    source_map: dict[str, dict[str, Any]] = {}

    if not blocked:
        placed: dict[str, dict[str, Any]] = {}
        for pack in candidate_packs:
            ref = cp.pack_ref(pack)
            if not ref or ref not in allowed or ref in placed:
                continue
            plane = cp.plane_from_pack(pack)
            label = _PLANE_TO_SECTION.get(plane, _DEFAULT_SECTION)
            entry = _entry(ref, pack, plane)
            placed[ref] = entry
            sections[label].append(entry)
            if _has_conflict(pack):
                sections["conflict"].append(entry)
            source_map[ref] = {"locator": _locator(pack, ref), "plane": plane, "source": _source(pack)}

        for missing in context.get("missing_planes") or []:
            sections["open_questions"].append({"type": "missing_plane", "plane": str(missing)})

    for label in SECTION_LABELS:
        sections[label].sort(key=lambda e: (e.get("ref", ""), e.get("plane", "")))
    source_map = {ref: source_map[ref] for ref in sorted(source_map)}

    withheld = {
        "refs": sorted(withheld_refs),
        "reasons": list(dict.fromkeys(list(gate.get("blocking_reasons") or []) + list(gate.get("warning_reasons") or []))),
    }

    return AssembledContextPack(
        context_pack_id=gate["context_pack_id"],
        posture=posture,
        operation=context.get("operation") or str(operation),
        sections=sections,
        source_map=source_map,
        withheld=withheld,
        missing_planes=list(context.get("missing_planes") or []),
        blocking_reasons=list(gate.get("blocking_reasons") or []),
        warning_reasons=list(gate.get("warning_reasons") or []),
    )
