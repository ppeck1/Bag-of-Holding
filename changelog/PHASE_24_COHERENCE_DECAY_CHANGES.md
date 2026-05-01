# Phase 24 — Coherence Decay + Refresh Engine

Implemented from the Phase 21–24 Constraint-Native Lattice Engine sequence.

## Added

- `app/core/coherence_decay.py`
  - Implements `C(t)=C0 * e^(-kτ) + R(t)`.
  - Scores lattice nodes as `fresh`, `aging`, `stale`, `critical_decay`, or `refresh_required`.
  - Records bounded, human-attributed refresh events.
  - Surfaces stale-state detection, coherence warnings, refresh requirements, priority escalation, and review queue resurfacing.

- `app/api/routes/coherence_routes.py`
  - `GET /api/coherence/summary`
  - `GET /api/coherence/scores`
  - `GET /api/coherence/nodes/{node_id}`
  - `GET /api/coherence/stale`
  - `GET /api/coherence/warnings`
  - `GET /api/coherence/refresh-required`
  - `GET /api/coherence/review-queue`
  - `GET /api/coherence/refresh-events`
  - `POST /api/coherence/refresh-events`

- Database migrations in `app/db/connection.py`
  - `coherence_refresh_events`
  - `coherence_scores`

- UI visibility in `app/ui/app.js`
  - Dashboard epistemic grid now displays coherence state counts:
    - Fresh
    - Aging
    - Stale
    - Critical Decay
    - Refresh Required

- Tests
  - `tests/test_phase24_coherence_decay.py`

## Invariants Preserved

- Truth age is visible, not hidden in timestamps.
- Refresh is bounded and auditable.
- Refresh cannot be autonomous.
- Decay does not promote canon, mutate authority, or expand LLM authority.
- Review resurfacing is advisory/governance-facing only.

## Review

### Usability impact

Positive: users can see which truths are aging or stale without manually reading validity timestamps.

Negative: the dashboard will feel more demanding because more items now surface as requiring attention.

### Friction increase

Moderate. Canonical nodes now acquire review pressure over time, even when no contradiction is present.

### False authority risk

Reduced if interpreted correctly. The score is a freshness/coherence signal, not a truth verdict.

### Operator comprehension

Needs UI copy discipline. “Critical decay” must be explained as operational expiry risk, not proof that content is false.

### Failure recovery path

Strong. Refresh events are logged separately and do not rewrite the underlying node without other governance actions.

### Audit survivability

Strong. Latest scores are persisted; refresh events are immutable records with actor, reason, evidence refs, and timestamp.

## Acceptance Position

After Phase 24, BOH now has the full sequence:

- Plane → explicit interface artifact
- Constraint → lattice node
- State → active subgraph
- Flow → traversal
- Feedback → reversible edge rewrite
- Time → coherence decay / refresh pressure

This reaches the requested threshold: BOH behaves less like governed storage and more like a constraint-native coherence engine.
