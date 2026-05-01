# Phase 23 — Feedback Rewrite Engine Changes

Source requirement: Feedback → edge rewrite, not notes.

## Added

- `app/core/feedback_rewrite.py`
- `app/api/routes/feedback_routes.py`
- `feedback_rewrites` table with reversible previous/new state snapshots
- `tests/test_phase23_feedback_rewrite.py`

## Capabilities

- strengthen edge
- weaken edge
- create constraint
- harden boundary
- shift dominance ordering
- reroute flow path

## Guardrails

- Human/reviewer actor required.
- Autonomous feedback rewrites are rejected.
- Every applied rewrite stores previous topology state.
- Every applied rewrite is reversible by default.
- Reverts restore edge state or archive feedback-created constraint cards.
- Feedback is surfaced through `/api/feedback/*` rather than hidden inside notes.

## Phase review

### Usability impact
Moderate friction increase. Operators must specify feedback kind, action, reason, actor, and topology target. This is intentional because edge rewrites are structural changes, not annotations.

### Friction increase
High for casual users, acceptable for governed mutation. The API rejects vague reasons and autonomous actors to prevent topology corruption.

### False authority risk
Reduced compared with free-form feedback notes, because rewrites are explicit, typed, bounded, and reversible. Still risky if reviewers overfit topology to single outcomes.

### Operator comprehension
Improved for audit-trained users; harder for naïve users. The vocabulary should remain visible in UI labels: reinforcing, dampening, compensatory, destabilizing.

### Failure recovery path
Strong. Each rewrite stores previous state and exposes a revert endpoint.

### Audit survivability
Strong. Rewrite records include previous/new state, actor, reason, feedback kind, action, timestamps, edge/node references, and metadata.

## Net assessment
Correct tradeoff. Phase 23 makes BOH adaptive without making it autonomous. It adds risk, but the risk is visible and recoverable.
