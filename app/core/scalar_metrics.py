"""app/core/scalar_metrics.py -- Neutral CANON geometry formulas.

Single source of truth for the viability / completeness scalar formulas shared by
the graph projection (``app/core/visual_projection.py``) and the Current Fold View
canon-variable path (``app/core/fold_metrics.py`` / ``current_fold.py``).

These are pure, deterministic functions. No DB access, no LLM, no randomness.
All outputs clamped to [0.0, 1.0]. These are dimensional pressures / policy
projections, NOT truth values.

Field names exposed to callers:
  graph projection contract : viability_margin, projection_loss  (unchanged, legacy)
  fold canon-variable contract : omega_viability, mismatch_gradient

omega_viability and viability_margin are the SAME formula. mismatch_gradient and
projection_loss are the SAME formula. The fold contract uses the omega_/mismatch_
names; the graph contract keeps its legacy names. See docs/math_authority.md §8.

The completeness defaults here are the canonical definition of the per-field defaults
that ``related.get_graph_data`` applies inline when building graph nodes. The graph/fold
parity tests lock the two together; if they drift, the parity test fails.
"""

from __future__ import annotations

from typing import Any


# Values treated as "field absent" for completeness scoring.
_COMPLETENESS_ABSENT = {None, "", "unassigned", "unknown"}

# The eight metadata fields scored for completeness (order is not significant).
COMPLETENESS_FIELDS: tuple[str, ...] = (
    "title", "project", "document_class", "canonical_layer",
    "authority_state", "review_state", "status", "summary",
)


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return lo
    if fv != fv:  # NaN
        return lo
    return max(lo, min(hi, fv))


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _norm(v: Any, denom: float) -> float:
    """Normalize a count to [0,1] against a denominator, clamped."""
    if denom <= 0:
        return 0.0
    return _clamp(_safe_float(v) / denom)


def metadata_completeness(record: dict[str, Any]) -> float:
    """Fraction of the eight metadata fields that carry a meaningful value.

    A field counts as present unless its value is None, "", "unassigned", or
    "unknown". The record is read as-is; callers that need the graph's defaults
    should normalize via ``viability_completeness_record`` first.
    """
    present = sum(
        1 for f in COMPLETENESS_FIELDS
        if record.get(f) not in _COMPLETENESS_ABSENT
    )
    return present / len(COMPLETENESS_FIELDS)


def viability_completeness_record(doc_row: dict[str, Any], basename: str = "") -> dict[str, Any]:
    """Build the eight completeness fields from a raw ``docs`` row, applying the
    SAME defaults that ``related.get_graph_data`` applies inline when constructing
    a graph node. This is the canonical definition of those defaults; the graph/fold
    parity test locks ``get_graph_data`` to it.

    Defaults (verbatim from get_graph_data):
      title           -> doc.title or basename
      project         -> doc.project or "Quarantine / Legacy Import"
      document_class  -> doc.document_class or doc.type or "unknown"
      canonical_layer -> doc.canonical_layer or "quarantine"
      authority_state -> doc.authority_state or "quarantined"
      review_state    -> doc.review_state or "unassigned"
      status          -> doc.status (no default)
      summary         -> doc.summary or ""
    """
    return {
        "title": doc_row.get("title") or basename,
        "project": doc_row.get("project") or "Quarantine / Legacy Import",
        "document_class": doc_row.get("document_class") or doc_row.get("type") or "unknown",
        "canonical_layer": doc_row.get("canonical_layer") or "quarantine",
        "authority_state": doc_row.get("authority_state") or "quarantined",
        "review_state": doc_row.get("review_state") or "unassigned",
        "status": doc_row.get("status"),
        "summary": doc_row.get("summary") or "",
    }


def omega_viability(
    authority: float,
    conflict_count: float,
    expired_count: float,
    uncertain_count: float,
    completeness: float,
) -> float:
    """Viability margin = how far a node sits above the instability floor.

    Identical formula to the graph projection's ``viability_margin``.
    Higher = more viable. See docs/math_authority.md §8.
    """
    return _clamp(
        _safe_float(authority)
        - _norm(conflict_count, 4) * 0.35
        - _norm(_safe_float(expired_count) + _safe_float(uncertain_count), 6) * 0.20
        - (1.0 - _clamp(completeness)) * 0.25
    )


def mismatch_gradient(completeness: float) -> float:
    """Metadata mismatch / incompleteness gradient.

    Identical formula to the graph projection's ``projection_loss``.
    Higher = more incomplete. Mapping to the governing CANON spec name is
    PROVISIONAL (see docs/math_authority.md §8).
    """
    return _clamp(1.0 - _clamp(completeness))
