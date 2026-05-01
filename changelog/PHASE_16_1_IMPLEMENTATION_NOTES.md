# Phase 16.1 Implementation Notes

Applied repair pass for Visualization Integrity + Operational Reality.

## Implemented

- Kept the Visualization mode bar persistent across Web, Variable Overlay, Constraint Geometry, and Constitutional modes.
- Added explicit recovery controls: Reset, Fit, Focus, Clear selection, Refresh, and Clear project scope.
- Converted project filtering to multi-select project scope so the same control supports single-project view, multi-project comparison, and cross-project overlay.
- Updated graph filtering to apply selected project scopes across all visualization modes.
- Reworked initial graph placement and force gravity toward a non-uniform semantic web:
  - project-level gravity wells
  - canonical center-of-gravity clustering
  - derived/evidence orbiting structure
  - fossilized archived/superseded nodes pushed outward
  - no random decorative background dots added
- Updated Variable Overlay to use explicit CANON variable terms rather than fallback semantic theater. Zero-count variables remain visible instead of being fabricated.
- Kept visualization controls visible in Simple mode; Simple/Advanced now changes detail density rather than hiding recovery paths.
- Expanded Duplicate Review into an operational workflow surface:
  - original file
  - duplicate file
  - canonical candidate
  - hash similarity
  - semantic similarity assertion state
  - modified/detected dates
  - authority state
  - canonical owner placeholder
  - review recommendation
  - Mark Canonical / Mark Duplicate / Mark Ignored / Move to Quarantine / Compare Side-by-Side / Copy File Path / Open File Location
- Added persistent duplicate review decision endpoint: `POST /api/duplicates/decision`.
- Added Phase 16.1 demo seed data with fake projects and deliberate refusal/failure cases:
  - Hospital LOS
  - E. coli Viability
  - Corporate Governance
  - Governance Failure Cases

## Validation performed

- `python -m py_compile app/api/routes/input_routes.py app/api/routes/lineage.py` passed.
- `node --check app/ui/app.js` passed.
- Full pytest run was attempted, but the existing suite stops on a `UNIQUE constraint failed: docs.path` error in `tests/test_ollama_hardening.py` while inserting repeated `/tmp/test.md` fixture data. This appears unrelated to the Phase 16.1 changes.
