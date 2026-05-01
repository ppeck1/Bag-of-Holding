# Phase 17 Visualization Patch Changes

Implemented the projection-ready Atlas patch from the supplied whitepage.

## Backend

- Added `app/core/visual_projection.py`.
- Added `GET /api/graph/projection?mode=web|structural|constitutional|constraint|variable`.
- Projection payload now includes deterministic x/y/z coordinates, radius, color role, risk score, load score, projection loss, viability margin, CANON variable lexical fallback mappings, constraint metrics, edge style roles, and a projection loss summary.
- Constraint Geometry is explicitly labeled as `Constraint Geometry v1: heuristic diagnostic projection`.
- Constitutional mode suppresses topic/suggested semantic edges by default.

## Frontend

- Atlas now loads from `/api/graph/projection` instead of raw `/api/graph`.
- Non-web modes remain clickable and navigable; the canvas is no longer disabled or replaced by dashboards.
- Overlay modes now function as explanation/legend panels rather than blocking graph replacements.
- ForceGraph respects server-provided projection coordinates and node radius/color roles.
- Tooltips now show project, class, canonical layer, authority state, review state, projection loss, load, conflicts, and stale-coordinate warnings.
- Reset scope now clears mode, project, class, layer, status, lineage-only, topic-edge state, and selected node.

## Tests

- Added `tests/test_visual_projection.py` for projection contract, metrics, variable mapping, and constitutional edge suppression.

## Notes

This is a deterministic v1 diagnostic projection. It does not add full 3D or Three.js. It prioritizes instrument-grade legibility over visual spectacle.
