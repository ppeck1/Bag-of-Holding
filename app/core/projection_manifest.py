"""app/core/projection_manifest.py: Ortho Flatten Projection Manifest Layer.

Phase 19.5: Every visualization projection must declare what it preserves,
what it discards, and what inferences are allowed — before rendering.

Reference: ORTHO_FLATTEN_WAVEFORM_v1
  "A projection is an interface point where meaning transfers between planes.
   Every projection must declare what it conserves and what it discards.
   Otherwise people will mistake the waveform for the original phenomenon."

Architectural rules (enforced, not advisory):
  1. No observable projection may render without a projection manifest.
  2. No projection may authorize canonical mutation.
  3. Projections are interpretive artifacts only. They may inform review.
     They may NOT promote canon.

Scope of this patch:
  ✓ ProjectionManifest data model
  ✓ Projection manifest validation
  ✓ Manifest attachment to graph projection endpoint
  ✓ Default manifests for all visualization modes
  ✗ No waveform engine
  ✗ No embedding / manifold computation
  ✗ No canonical mutation from projection output
  ✗ No LLM certificate generation
  ✗ No cross-plane mutation
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal, Any

# ── Projection axis vocabulary ─────────────────────────────────────────────────
# Drawn from ORTHO_FLATTEN_WAVEFORM_v1 orthogonal waveform channels
# plus BOH-specific visualization modes.

ProjectionAxis = Literal[
    # ORTHO_FLATTEN_WAVEFORM_v1 canonical channels
    "trajectory_velocity",      # v(t) — movement speed through motif space
    "transition_energy",        # E(t) — effort/cost to move between states
    "novelty_entropy",          # H(t) — novelty vs repetition (surprise)
    "boundary_proximity",       # B(t) — distance to constraint boundaries
    "attractor_dwell",          # D(t) — time spent near attractors
    # BOH visualization modes
    "constraint_geometry",      # q × c × cost viability surface
    "constitutional_topology",  # custodian governance lane topology
    "variable_overlay",         # Daenary d/m/q/c state space
    "relational_adjacency",     # document relationship network (web mode)
    "identity_membership",      # basic node identity + project (simple)
    "epistemic_expanded",       # expanded epistemic + relational (advanced)
]

VALID_AXES: frozenset[str] = frozenset({
    "trajectory_velocity", "transition_energy", "novelty_entropy",
    "boundary_proximity", "attractor_dwell", "constraint_geometry",
    "constitutional_topology", "variable_overlay", "relational_adjacency",
    "identity_membership", "epistemic_expanded",
})

# Canonical token that MUST appear in every forbidden_inference list.
FORBIDDEN_PROMOTION_TOKEN = "automatic canonical promotion"


# ── Dataclass ──────────────────────────────────────────────────────────────────

@dataclass
class ProjectionManifest:
    """Declares the terms of a projection: what is conserved, what is discarded,
    what inferences are allowed, and what inferences are forbidden.

    Mandatory fields enforce the coherence rule from ORTHO_FLATTEN_WAVEFORM_v1:
      "Always ship the projection manifest with the waveform."
    """
    projection_id:       str
    source_plane:        str
    projection_axis:     str       # must be in VALID_AXES
    signal:              str       # human description of what is projected
    metric:              str       # the concrete measurement/positioning method
    conserved_quantity:  str       # what structural property is preserved
    discarded_dimensions: list[str]   # MUST be non-empty
    quality_gate:         dict[str, Any]  # MUST include min_q and min_c
    allowed_inference:    list[str]   # MUST be non-empty
    forbidden_inference:  list[str]   # MUST include FORBIDDEN_PROMOTION_TOKEN
    version:              str  = "1.0"
    ortho_ref:            str  = "ORTHO_FLATTEN_WAVEFORM_v1"
    non_authoritative:    bool = True  # projection output is never authoritative

    def to_dict(self) -> dict:
        return asdict(self)


# ── Validation ─────────────────────────────────────────────────────────────────

def validate_manifest(m: ProjectionManifest) -> dict[str, Any]:
    """Validate a ProjectionManifest against all required invariants.

    Returns {valid: bool, errors: list[str]}.

    Invariants:
      1. projection_id must be set
      2. projection_axis must be in VALID_AXES
      3. conserved_quantity must be set
      4. discarded_dimensions must be non-empty
      5. allowed_inference must be non-empty
      6. forbidden_inference must include FORBIDDEN_PROMOTION_TOKEN
      7. quality_gate must include min_q and min_c
    """
    errors: list[str] = []

    if not m.projection_id or not m.projection_id.strip():
        errors.append("projection_id is required")

    if not m.projection_axis or m.projection_axis not in VALID_AXES:
        errors.append(
            f"projection_axis {m.projection_axis!r} is not a valid axis. "
            f"Valid: {sorted(VALID_AXES)}"
        )

    if not m.conserved_quantity or not m.conserved_quantity.strip():
        errors.append("conserved_quantity is required")

    if not m.discarded_dimensions:
        errors.append(
            "discarded_dimensions must be non-empty — every projection discards something"
        )

    if not m.allowed_inference:
        errors.append("allowed_inference must be non-empty")

    if FORBIDDEN_PROMOTION_TOKEN not in m.forbidden_inference:
        errors.append(
            f"forbidden_inference must include {FORBIDDEN_PROMOTION_TOKEN!r}. "
            f"Projections may not authorize canonical promotion."
        )

    if "min_q" not in m.quality_gate or "min_c" not in m.quality_gate:
        errors.append("quality_gate must include min_q and min_c")

    return {"valid": len(errors) == 0, "errors": errors}


def validate_manifest_or_error(m: ProjectionManifest) -> dict[str, Any] | None:
    """Return error dict if manifest is invalid, None if valid."""
    result = validate_manifest(m)
    if not result["valid"]:
        return {
            "error": "projection_manifest_required",
            "validation_errors": result["errors"],
            "projection_id": m.projection_id,
        }
    return None


# ── Default manifests ──────────────────────────────────────────────────────────

_MANIFESTS: dict[str, ProjectionManifest] = {}


def _register(m: ProjectionManifest) -> ProjectionManifest:
    _MANIFESTS[m.projection_id] = m
    return m


MANIFEST_WEB = _register(ProjectionManifest(
    projection_id      = "PM_web_relational_v1",
    source_plane       = "All",
    projection_axis    = "relational_adjacency",
    signal             = "Document relationship network projected by project cluster and canonical layer",
    metric             = "project_cluster_angle × layer_rank × drift_offset",
    conserved_quantity = "Relational adjacency and project membership structure",
    discarded_dimensions = [
        "epistemic confidence values (q, c)",
        "meaning_cost and viability score",
        "temporal validity and expiry",
        "directional state (d) and zero-mode (m)",
        "correction_status",
        "constraint lattice detail",
    ],
    quality_gate       = {"min_q": 0.0, "min_c": 0.0},
    allowed_inference  = [
        "structural connectivity between documents",
        "project cluster membership",
        "conflict adjacency identification",
        "lineage path tracing",
        "canonical layer distribution",
    ],
    forbidden_inference = [
        "epistemic truth about document content",
        "automatic canonical promotion",
        "semantic equivalence between documents",
        "authority transfer authorization",
        "source reliability determination",
    ],
))

MANIFEST_VARIABLE = _register(ProjectionManifest(
    projection_id      = "PM_variable_overlay_v1",
    source_plane       = "All",
    projection_axis    = "variable_overlay",
    signal             = "Daenary epistemic state variables: d/m/q/c/validity/correction_status",
    metric             = "d_state_color × epistemic_q_size × epistemic_c_x × epistemic_q_y",
    conserved_quantity = "Directional epistemic state and quality/confidence geometry",
    discarded_dimensions = [
        "full source text content",
        "semantic relationships between documents",
        "cross-plane evidence chains",
        "unmodeled temporal decay trajectory",
        "constraint lattice detail",
        "attractor dwell patterns",
        "transition energy between states",
    ],
    quality_gate       = {"min_q": 0.0, "min_c": 0.0},
    allowed_inference  = [
        "relative epistemic readiness of each node",
        "zero-mode routing (contain vs cancel pressure)",
        "quality and confidence distribution across corpus",
        "review priority by d-state and correction_status",
        "epistemic state gaps (no-state sentinel cluster)",
    ],
    forbidden_inference = [
        "root cause certainty",
        "truth certainty",
        "automatic canonical promotion",
        "source text meaning or accuracy",
        "definitive epistemic classification without human review",
    ],
))

MANIFEST_CONSTRAINT = _register(ProjectionManifest(
    projection_id      = "PM_constraint_geometry_v1",
    source_plane       = "Internal",
    projection_axis    = "constraint_geometry",
    signal             = "q/c/cost viability surface — epistemic confidence × quality × meaning cost",
    metric             = "confidence_quality_cost_positioning",
    conserved_quantity = "Epistemic viability relationship: relative position on q × c surface",
    discarded_dimensions = [
        "full source text content",
        "complete semantic ambiguity structure",
        "unmodeled cross-plane context",
        "temporal trajectory and transition sequence",
        "attractor dwell patterns",
        "novelty and entropy waveform",
        "boundary proximity dynamics",
    ],
    quality_gate       = {"min_q": 0.0, "min_c": 0.0},
    allowed_inference  = [
        "relative epistemic readiness for canonical promotion",
        "contain / cancel / canonical lane pressure",
        "review priority ordering",
        "viability zone classification (viable, contain, weak, low)",
        "high-cost node identification for human review",
    ],
    forbidden_inference = [
        "root cause certainty",
        "truth certainty",
        "automatic canonical promotion",
        "optimal action determination without human review",
        "absolute quality or confidence scoring",
    ],
))

MANIFEST_CONSTITUTIONAL = _register(ProjectionManifest(
    projection_id      = "PM_constitutional_topology_v1",
    source_plane       = "All",
    projection_axis    = "constitutional_topology",
    signal             = "Custodian lane distribution and governance state topology",
    metric             = "custodian_lane_x × lane_position_y × epistemic_q_z",
    conserved_quantity = "Epistemic custody topology — governance state ordering across 8 lanes",
    discarded_dimensions = [
        "full semantic content of documents",
        "cross-plane evidence chains and interfaces",
        "temporal validity decay curve detail",
        "meaning_cost gradient surface",
        "transition energy between governance states",
        "novelty and entropy of document content",
    ],
    quality_gate       = {"min_q": 0.0, "min_c": 0.0},
    allowed_inference  = [
        "governance lane pressure and distribution",
        "canonical candidacy identification",
        "contain/cancel routing readiness",
        "review priority by custody state",
        "expired and raw-imported document identification",
    ],
    forbidden_inference = [
        "root cause certainty",
        "truth certainty",
        "automatic canonical promotion",
        "cross-plane authority transfer",
        "source document accuracy determination",
    ],
))

MANIFEST_SIMPLE = _register(ProjectionManifest(
    projection_id      = "PM_simple_identity_v1",
    source_plane       = "All",
    projection_axis    = "identity_membership",
    signal             = "Basic node identity, project membership, and canonical status",
    metric             = "project_color × status_badge × layer_rank",
    conserved_quantity = "Node identity and project assignment",
    discarded_dimensions = [
        "epistemic state (d, m, q, c, correction_status)",
        "meaning_cost and viability score",
        "confidence and quality values",
        "constraint lattice and certificate state",
        "temporal validity and valid_until",
        "zero-mode and directional state",
        "cross-plane relationships",
    ],
    quality_gate       = {"min_q": 0.0, "min_c": 0.0},
    allowed_inference  = [
        "project membership and cluster identity",
        "rough canonical status",
        "presence and basic classification in corpus",
    ],
    forbidden_inference = [
        "epistemic truth",
        "automatic canonical promotion",
        "authority determination",
        "quality or reliability assessment",
        "governance state routing",
    ],
))

MANIFEST_ADVANCED = _register(ProjectionManifest(
    projection_id      = "PM_advanced_epistemic_v1",
    source_plane       = "All",
    projection_axis    = "epistemic_expanded",
    signal             = "Expanded relationship network with epistemic metadata overlay",
    metric             = "authority_layer_drift × epistemic_badge × relational_adjacency",
    conserved_quantity = "Epistemic metadata, relational adjacency, and authority structure",
    discarded_dimensions = [
        "full source text content",
        "unresolvable semantic ambiguity detail",
        "cross-plane evidence not yet in system",
        "temporal trajectory and waveform dynamics",
        "constraint lattice certificate chains",
    ],
    quality_gate       = {"min_q": 0.0, "min_c": 0.0},
    allowed_inference  = [
        "governance pressure and custodian state",
        "epistemic readiness relative ordering",
        "lineage structure and derivation paths",
        "conflict adjacency and review priority",
        "authority layer distribution",
    ],
    forbidden_inference = [
        "root cause certainty",
        "truth certainty",
        "automatic canonical promotion",
        "source truth determination without evidence review",
        "definitive semantic equivalence",
    ],
))

# Mode → manifest mapping
_MODE_TO_MANIFEST: dict[str, ProjectionManifest] = {
    "web":            MANIFEST_WEB,
    "variable":       MANIFEST_VARIABLE,
    "constraint":     MANIFEST_CONSTRAINT,
    "constitutional": MANIFEST_CONSTITUTIONAL,
    "simple":         MANIFEST_SIMPLE,
    "advanced":       MANIFEST_ADVANCED,
}


def get_manifest(mode: str) -> ProjectionManifest | None:
    """Return the ProjectionManifest for a given visualization mode.

    Returns None if the mode has no registered manifest — which must
    block the projection from rendering.
    """
    return _MODE_TO_MANIFEST.get(mode)


def get_manifest_or_error(mode: str) -> tuple[ProjectionManifest | None, dict | None]:
    """Return (manifest, None) if found and valid, or (None, error_dict) otherwise."""
    m = get_manifest(mode)
    if m is None:
        return None, {
            "error": "projection_manifest_required",
            "validation_errors": [f"No manifest registered for mode {mode!r}"],
            "mode": mode,
        }
    err = validate_manifest_or_error(m)
    if err:
        return None, err
    return m, None


def all_manifests() -> dict[str, dict]:
    """Return all registered manifests as dicts, keyed by mode."""
    return {mode: m.to_dict() for mode, m in _MODE_TO_MANIFEST.items()}
