# Phase 20.1 — Promotion Path Hard Cutover

Applied patch: direct canonical promotion is removed as an executable affordance. Canonical mutation now requires certificate request → human review → approved certificate → `apply_canonical_promotion(node_id, certificate_id)`.

## Implemented

- Added explicit `authority_plane` certificate field.
  - Mandatory on certificate request.
  - Normalized to lower-case epistemic planes.
  - Valid planes: `verification`, `governance`, `evidence`, `narrative`, `operational`, `constitutional`.
  - Invalid planes such as `projection`, `llm`, `viewer`, `admin`, `dev`, `demo`, and `automated` fail hard.
  - Legacy `plane_authority` remains only as a compatibility alias.

- Added immutable canonical lineage.
  - `docs.promoted_by_certificate` records the certificate used for canonical promotion.
  - Canonical promotion writes this field permanently at mutation time.

- Added single canonical mutation door.
  - New function: `apply_canonical_promotion(node_id, certificate_id)`.
  - Requires certificate existence, certificate/node match, approved status, non-expiry, valid authority plane, legal lattice transition, and q/c thresholds.
  - No admin/dev/demo bypass exists.

- Removed executable legacy promotion path.
  - `POST /api/governance/approve/request-promotion` now returns `direct_promotion_removed_use_certificate_flow`.
  - `approval._execute_transfer()` no longer mutates canonical state for `canonical_promotion`.
  - Supersede flow no longer auto-promotes replacement to canonical.
  - Dead legacy endpoints added as explicit 410 blockers:
    - `POST /api/promote`
    - `POST /api/node/promote`
    - `POST /api/canonicalize`

- Added certificate apply endpoint.
  - `POST /api/certificate/apply-canonical-promotion`
  - This is the only API route that applies approved canonical promotion.

- Rewrote UI affordances.
  - Governance form now says `Request Canonical Promotion Certificate`.
  - Main and quick promotion forms submit certificate requests only.
  - UI requires reason, evidence refs, q, c, validity window, and authority plane.
  - No optimistic canonical mutation is exposed.

- Added regression tests.
  - `tests/test_phase20_1_promotion_hard_cutover.py`
  - Covers dead legacy routes, invalid authority planes, pending certificate blocking, approved certificate promotion, certificate lineage, and wrong-plane failure.

## Verification

Passed:

```bash
pytest -q tests/test_phase20_certificate.py tests/test_phase20_1_promotion_hard_cutover.py
# 61 passed, 1 warning
```

A full repository test run was started, but timed out after reaching legacy Phase 15 tests. The first failure is expected under Phase 20.1 because `tests/test_phase15_approval.py` still expects `/api/governance/approve/request-promotion` to create old approval records. That legacy behavior is now intentionally removed.

## Files changed

- `app/core/certificate.py`
- `app/core/constraint_lattice.py`
- `app/core/approval.py`
- `app/api/routes/certificate_routes.py`
- `app/api/routes/approval_routes.py`
- `app/db/connection.py`
- `app/ui/index.html`
- `app/ui/app.js`
- `tests/test_phase20_1_promotion_hard_cutover.py`
