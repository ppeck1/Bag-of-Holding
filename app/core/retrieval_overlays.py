"""Retrieval overlays -- a deterministic, read-only reweighting engine.

An overlay is a PURE function that, given the candidate list and a context,
proposes a small per-ref additive adjustment to retrieval ranking. This engine
registers named overlays, applies them as BOUNDED additive deltas on top of each
candidate's base `score`, and records an `OverlayRun` trace plus any composition
conflicts. It reweights ONLY: it never overrides canon scoring, never mutates a
candidate's canon/provenance/authority fields, never writes the DB, and never
sets canon_eligible.

This mirrors the philosophy already present in `app/core/search.py`'s bounded
`_daenary_adjustment` ("does not override canon scoring"), generalized into a
registry + trace. It operates on a SUPPLIED candidate list; wiring overlays into
the live search path is a separate integration unit.

Deterministic: the same inputs (candidates + ordered overlays + context) yield an
equal `OverlayRun.to_dict()`. No wall-clock field is included.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from app.core.context_pack import pack_ref


# Bounds: an overlay's per-ref delta and the summed adjustment are clamped so
# overlays can reorder within reason but never dominate / override canon scoring.
PER_OVERLAY_DELTA_BOUND = 0.05
TOTAL_DELTA_BOUND = 0.10

OverlayFn = Callable[[list[dict[str, Any]], dict[str, Any]], dict[str, float]]


def _clamp(value: float, bound: float) -> float:
    return max(-bound, min(bound, value))


@dataclass(frozen=True)
class Overlay:
    """A named, pure reweighting overlay.

    `fn(candidates, context)` returns a mapping of candidate ref -> additive
    delta. `axis` names the ranking dimension the overlay claims (two overlays on
    the same axis are flagged as a composition conflict). `bound` clamps each
    per-ref delta.
    """

    name: str
    axis: str
    fn: OverlayFn
    bound: float = PER_OVERLAY_DELTA_BOUND


class OverlayRegistry:
    def __init__(self) -> None:
        self._overlays: dict[str, Overlay] = {}

    def register(self, overlay: Overlay) -> Overlay:
        if overlay.name in self._overlays:
            raise ValueError(f"overlay already registered: {overlay.name}")
        self._overlays[overlay.name] = overlay
        return overlay

    def get(self, name: str) -> Overlay:
        if name not in self._overlays:
            raise KeyError(f"overlay not registered: {name}")
        return self._overlays[name]

    def list_overlays(self) -> list[str]:
        return sorted(self._overlays)


_DEFAULT_REGISTRY = OverlayRegistry()


def register(overlay: Overlay) -> Overlay:
    return _DEFAULT_REGISTRY.register(overlay)


def get(name: str) -> Overlay:
    return _DEFAULT_REGISTRY.get(name)


def list_overlays() -> list[str]:
    return _DEFAULT_REGISTRY.list_overlays()


def _stable_run_id(
    applied: list[str],
    base_scores: dict[str, float],
    final_scores: dict[str, float],
    final_order: list[str],
    conflicts: list[dict[str, Any]],
) -> str:
    raw = json.dumps(
        {
            "applied": applied,
            "base_scores": base_scores,
            "final_scores": final_scores,
            "final_order": final_order,
            "conflicts": conflicts,
        },
        sort_keys=True,
        default=str,
    )
    return "ovr_" + hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:24]


@dataclass
class OverlayRun:
    """Deterministic, read-only trace of one overlay application.

    Carries no wall-clock field so it is reproducible. canon_eligible is
    re-forced to False -- overlays never grant canon eligibility.
    """

    applied_overlays: list[str] = field(default_factory=list)
    deltas: dict[str, dict[str, float]] = field(default_factory=dict)
    base_scores: dict[str, float] = field(default_factory=dict)
    final_scores: dict[str, float] = field(default_factory=dict)
    final_order: list[str] = field(default_factory=list)
    composition_conflicts: list[dict[str, Any]] = field(default_factory=list)
    canon_eligible: bool = False  # INVARIANT: always False
    overlay_run_id: str = ""

    def __post_init__(self) -> None:
        self.canon_eligible = False
        if not self.overlay_run_id:
            self.overlay_run_id = _stable_run_id(
                self.applied_overlays,
                self.base_scores,
                self.final_scores,
                self.final_order,
                self.composition_conflicts,
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _resolve(
    overlays: list[Overlay | str], registry: OverlayRegistry | None
) -> list[Overlay]:
    reg = registry or _DEFAULT_REGISTRY
    resolved: list[Overlay] = []
    for ov in overlays:
        resolved.append(ov if isinstance(ov, Overlay) else reg.get(ov))
    return resolved


def _detect_conflicts(
    resolved: list[Overlay], deltas_by_overlay: dict[str, dict[str, float]]
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []

    # Axis collisions: two or more applied overlays claim the same ranking axis.
    by_axis: dict[str, list[str]] = {}
    for ov in resolved:
        by_axis.setdefault(ov.axis, []).append(ov.name)
    for axis, names in sorted(by_axis.items()):
        if len(names) > 1:
            conflicts.append({"type": "axis_collision", "axis": axis, "overlays": sorted(names)})

    # Opposing deltas: two overlays push the same ref in opposite directions.
    refs: set[str] = set()
    for d in deltas_by_overlay.values():
        refs.update(d)
    for ref in sorted(refs):
        contributors = [(name, d[ref]) for name, d in deltas_by_overlay.items() if ref in d]
        signs = {1 if v > 0 else -1 for _, v in contributors if v != 0}
        if len(signs) > 1:
            conflicts.append(
                {"type": "opposing_delta", "ref": ref, "overlays": sorted(n for n, _ in contributors)}
            )

    return conflicts


def apply_overlays(
    candidates: list[dict[str, Any]],
    overlays: list[Overlay | str],
    *,
    context: dict[str, Any] | None = None,
    registry: OverlayRegistry | None = None,
) -> OverlayRun:
    """Apply overlays as bounded additive reweighting and return an OverlayRun.

    Pure and read-only: input candidates are NOT mutated (overlays receive shallow
    copies), only a separate `final_scores`/`final_order` is produced. Each per-ref
    delta is clamped to the overlay's bound and the summed adjustment to
    TOTAL_DELTA_BOUND, so canon scoring is never overridden. Deterministic for
    fixed inputs.
    """
    context = context or {}
    resolved = _resolve(overlays, registry)

    base_scores: dict[str, float] = {}
    for c in candidates:
        ref = pack_ref(c)
        if ref:
            base_scores[ref] = float(c.get("score") or 0.0)

    # Overlays receive shallow copies so a misbehaving overlay cannot reassign
    # a candidate's canon/provenance/authority fields on the originals.
    safe_candidates = [dict(c) for c in candidates]

    deltas_by_overlay: dict[str, dict[str, float]] = {}
    for ov in resolved:
        raw = ov.fn(safe_candidates, context) or {}
        clamped: dict[str, float] = {}
        for ref, delta in raw.items():
            if ref not in base_scores:
                continue
            cd = round(_clamp(float(delta), ov.bound), 6)
            if cd:
                clamped[ref] = cd
        deltas_by_overlay[ov.name] = dict(sorted(clamped.items()))

    conflicts = _detect_conflicts(resolved, deltas_by_overlay)

    final_scores: dict[str, float] = {}
    for ref, base in base_scores.items():
        total = sum(deltas_by_overlay[ov.name].get(ref, 0.0) for ov in resolved)
        final_scores[ref] = round(base + _clamp(total, TOTAL_DELTA_BOUND), 6)

    final_order = sorted(base_scores, key=lambda r: (-final_scores[r], r))

    return OverlayRun(
        applied_overlays=[ov.name for ov in resolved],
        deltas=deltas_by_overlay,
        base_scores=dict(sorted(base_scores.items())),
        final_scores=dict(sorted(final_scores.items())),
        final_order=final_order,
        composition_conflicts=conflicts,
    )
