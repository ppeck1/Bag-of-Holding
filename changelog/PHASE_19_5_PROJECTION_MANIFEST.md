# Phase 19.5 — Ortho Flatten Projection Manifest Layer

## Test results: 856 collected (60 new), all passing

Reference: ORTHO_FLATTEN_WAVEFORM_v1

---

## Purpose

Every visualization projection now declares what it preserves, what it discards,
and what inferences are allowed — before rendering.

This is not a waveform engine. This is the governance layer that must exist before
any waveform computation is attempted.

---

## Architectural rules enforced by this patch

1. **No observable projection may render without a projection manifest.**
2. **No projection may authorize canonical mutation.**
3. Projections are interpretive artifacts only. They may inform review.
   They may NOT promote canon.

The third rule is enforced at three levels:
- The manifest's `forbidden_inference` list always includes `"automatic canonical promotion"`
- `validate_manifest()` rejects any manifest missing that token
- `get_projection_graph()` does not call `can_canonicalize()` (verified by static inspection test)

---

## New module: `app/core/projection_manifest.py`

### `ProjectionAxis` vocabulary
Eleven recognized axes drawn from ORTHO_FLATTEN_WAVEFORM_v1 and BOH modes:

| Axis | Origin | Meaning |
|------|--------|---------|
| `trajectory_velocity` | ORTHO v(t) | Movement speed through motif space |
| `transition_energy` | ORTHO E(t) | Effort/cost between states |
| `novelty_entropy` | ORTHO H(t) | Novelty vs repetition |
| `boundary_proximity` | ORTHO B(t) | Distance to constraint boundaries |
| `attractor_dwell` | ORTHO D(t) | Time near attractors |
| `constraint_geometry` | BOH | q × c × cost viability surface |
| `constitutional_topology` | BOH | Custodian lane topology |
| `variable_overlay` | BOH | Daenary d/m/q/c state space |
| `relational_adjacency` | BOH | Document relationship network |
| `identity_membership` | BOH | Basic node identity + project |
| `epistemic_expanded` | BOH | Expanded epistemic + relational |

### `ProjectionManifest` dataclass fields
```
projection_id         str       required
source_plane          str       required
projection_axis       str       must be in VALID_AXES
signal                str       human description of what is projected
metric                str       concrete measurement/positioning method
conserved_quantity    str       required — what structural property is preserved
discarded_dimensions  list[str] MUST be non-empty
quality_gate          dict      MUST include min_q and min_c
allowed_inference     list[str] MUST be non-empty
forbidden_inference   list[str] MUST include "automatic canonical promotion"
version               str       default "1.0"
ortho_ref             str       "ORTHO_FLATTEN_WAVEFORM_v1"
non_authoritative     bool      always True
```

### Validation invariants (all enforced by `validate_manifest()`)
1. `projection_id` required
2. `projection_axis` in VALID_AXES
3. `conserved_quantity` required
4. `discarded_dimensions` non-empty
5. `allowed_inference` non-empty
6. `forbidden_inference` includes `"automatic canonical promotion"`
7. `quality_gate` includes `min_q` and `min_c`

### Six default manifests

| Mode | projection_id | axis |
|------|---------------|------|
| web | PM_web_relational_v1 | relational_adjacency |
| variable | PM_variable_overlay_v1 | variable_overlay |
| constraint | PM_constraint_geometry_v1 | constraint_geometry |
| constitutional | PM_constitutional_topology_v1 | constitutional_topology |
| simple | PM_simple_identity_v1 | identity_membership |
| advanced | PM_advanced_epistemic_v1 | epistemic_expanded |

All six pass validation. All six explicitly forbid automatic canonical promotion.

---

## `visual_projection.py` changes

`get_projection_graph()` now:

1. Calls `get_manifest_or_error(mode)` immediately after normalizing mode
2. Returns `{"error": "projection_manifest_required", "validation_errors": [...]}` if manifest is missing or invalid
3. Includes `"projection_manifest": manifest.to_dict()` in every successful response

The manifest gate runs before any DB query. No partial projection is returned if the manifest cannot be validated.

---

## UI changes (`app.js`, `style.css`)

### Manifest panel function: `_renderManifestPanel(manifest)`
Renders a compact expandable panel showing:
- Axis pill (e.g., `constraint_geometry`)
- Signal description
- Metric
- Conserved quantity
- Quality gate (min_q, min_c)
- Discarded dimensions (italic, with `·` prefix)
- Allowed inference (green, with `✓` prefix)
- Forbidden inference (red, with `✗` prefix)
- Non-authoritative footer: "✗ Non-authoritative · Cannot promote canon · Interpretive artifact only"

Collapsed by default. Expands on click. Does not clutter the main visualization.

### Manifest injected into every mode
- **Non-web modes**: manifest panel appears at bottom of the sidebar, before the footer
- **Web mode**: manifest panel appears as a small fixed overlay at bottom-left of canvas
  (previously web mode showed nothing — now it shows just the manifest)

### New CSS classes
`.viz-manifest-panel`, `.viz-manifest-toggle`, `.viz-manifest-body`,
`.viz-manifest-row`, `.viz-manifest-key`, `.viz-manifest-val`,
`.viz-manifest-list`, `.viz-manifest-list-item.allowed/forbidden/discarded`,
`.viz-manifest-axis-pill`, `.viz-manifest-non-auth`

---

## Tests: 60 new tests in `tests/test_phase19_5_manifest.py`

| Class | Tests | Coverage |
|-------|-------|---------|
| `TestProjectionReturnsManifest` | 5 | All modes return manifest |
| `TestMissingManifestReturnsError` | 3 | Error on missing manifest |
| `TestDiscardedDimensionsRequired` | 3 | Non-empty discarded_dimensions |
| `TestForbiddenInferenceRequired` | 2 | Non-empty forbidden_inference |
| `TestForbiddenPromotionToken` | 4 | Promotion token enforcement |
| `TestConstitutionalManifest` | 4 | Constitutional mode manifest |
| `TestVariableOverlayManifest` | 4 | Variable overlay manifest |
| `TestConstraintGeometryManifest` | 4 | Constraint geometry manifest |
| `TestVisualizationResponseHasManifest` | 3 | Response structure |
| `TestProjectionCannotPromoteCanon` | 4 | No canon promotion from projection |
| `TestManifestValidation` | 8 | All validation invariants |
| `TestAllDefaultManifestsValid` | 8 | All 6 defaults pass validation |
| `TestWebManifest` | 4 | Web mode manifest |
| `TestProjectionAxisVocabulary` | 4 | ORTHO_FLATTEN_WAVEFORM_v1 axis compatibility |

---

## Scope boundary (strictly observed)

This patch adds ONLY:
- ✓ ProjectionManifest data model
- ✓ Projection manifest validation
- ✓ Manifest attachment to graph projection endpoint
- ✓ UI display of projection manifest metadata
- ✓ Regression tests enforcing projection honesty
- ✓ Default manifests for all visualization modes

This patch does NOT add:
- ✗ Manifold embedding engine
- ✗ Waveform generation (E(t), B(t), H(t), D(t), v(t))
- ✗ Sonification
- ✗ Automatic computation from raw data
- ✗ Canonical mutation from projection output
- ✗ LLM-authored certificate generation
- ✗ Cross-plane mutation logic
- ✗ Membrane security
- ✗ Predictive coding engine

---

## Roadmap position

```
✓ Phase 18   — Daenary state contract
✓ Phase 19   — Plane Card storage
✓ Phase 19.5 — Projection manifest layer (this patch)
  Phase 20   — Constraint lattice + certificate gate
  Phase 21   — Plane interfaces (cross-plane translation)
  Phase 22   — Plane-aware retrieval
  Phase 23   — Membrane security
  [future]   — Waveform engine (requires Phase 20-22 substrate)
```
