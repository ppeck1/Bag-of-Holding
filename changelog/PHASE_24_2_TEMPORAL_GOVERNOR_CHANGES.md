# BOH v2 — Phase 24.2: Temporal Coherence Governor

## Purpose

Substrate correction. Not feature expansion.

Phase 24.2 installs enforced temporal coherence infrastructure:
conversation momentum must not launder uncertainty into certainty.
Time passing is not verification. Continuation is not resolution.

---

## Fix A — Drift Detection Layer

**Module:** `app/core/temporal_governor.py`

`evaluate_drift(node_id)` continuously evaluates:
- `last_verified_at` — most recent verification event or observation
- `valid_until` — explicit expiry boundary
- `refresh_required` — from Phase 24.1 coherence scoring
- `drift_risk` — low | moderate | high

**Drift risk logic:**
- `temporal_ambiguity` → always `high`
- `valid_until` elapsed → `high`
- coherence < 0.45 → `high`
- coherence < 0.65 or expiry approaching → `moderate`
- otherwise → `low`

`nanny_required: true` is returned when `drift_risk == "high"`.

`evaluate_drift_all()` evaluates all nodes and returns results sorted high→low.

**Routes:**
- `GET /api/temporal/drift/{node_id}`
- `GET /api/temporal/drift?plane=...`

**Also fixed in `coherence_decay.py` — P1 invariant hardening:**
`_node_start_time` now rejects near-epoch ISO datetimes (`.timestamp() < 86400`) in
the cards table observed_at column, closing a sentinel bypass. Administrative
`updated_ts` is never used as an epistemic start time — it is touched on every write
and would launder administrative activity into apparent freshness.

---

## Fix B — Nanny Clause Enforcement

`trigger_re_anchor(node_id, actor, trigger_reason)`:
1. Forces `d=0`, `m=contain` on the underlying doc and card
2. Creates an auditable `anchor_events` record
3. Returns the mandatory trinary output:

```json
{
  "KNOWN": [...verified facts...],
  "UNKNOWN": [...unresolved items...],
  "BLOCKED": [...expired or contradicted items...],
  "next_valid_resolution_plane": "governance | verification",
  "mode": "re_anchor",
  "resume_blocked_until": "re_anchor completes with single_active_plane promotion"
}
```

Autonomous actors (`auto`, `autonomous`, `llm`) are rejected.
No override path. No silent continuation.

**Routes:**
- `POST /api/temporal/re-anchor`
- `GET /api/temporal/anchors`
- `GET /api/temporal/anchors/{anchor_id}`

---

## Fix C — Single Plane Resume Rule

`resume_on_single_plane(anchor_id, active_plane, actor, promotion_reason)`:
- Grants resume on exactly one plane after re-anchor
- Rejects if anchor already has an `active_plane` assigned
- Multi-plane simultaneous recovery creates false synthesis — blocked
- Expansion beyond this plane requires explicit subsequent promotion, not inference

**Route:**
- `POST /api/temporal/resume`

---

## Fix D — Open Item Registry

`create_open_item(...)` registers unresolved ambiguity. Items persist until
explicitly resolved. No disappearance by recency. No burial by token distance.

**Schema:** `open_items` table
```json
{
  "id": "OI_...",
  "plane_boundary": "evidence|verification",
  "created_at": "...",
  "valid_until": "...",
  "resolution_authority": "custodian",
  "status": "open|expired|resolved",
  "drift_priority": "low|moderate|high"
}
```

`expire_stale_open_items()` marks items past `valid_until` as `expired`.
Autonomous resolution is rejected.

**Routes:**
- `POST /api/temporal/open-items`
- `GET /api/temporal/open-items`
- `GET /api/temporal/open-items/{item_id}`
- `POST /api/temporal/open-items/{item_id}/resolve`
- `POST /api/temporal/open-items/expire-stale`

---

## Fix E — Temporal Laundering Warning

`temporal_laundering_check(node_id)` detects three laundering conditions:
1. `valid_until` has elapsed without refresh
2. No verification timestamp ever recorded (temporal ambiguity)
3. High drift risk with no refresh events in the DB

When detected, returns mandatory warning:

> "Warning: Elapsed time does not constitute verification.
> This state degraded into containment, not certainty.
> Do not interpret silence or continuation as resolution."

No suppression. No "probably still true."

**Route:**
- `GET /api/temporal/laundering-check/{node_id}`

---

## Fix F — Temporal Integrity Panel

`temporal_integrity_panel()` aggregates all temporal signals into one view:

- `active_verified_states` — low drift, not ambiguous
- `open_containment_states` — active anchor events
- `expired_without_refresh` — high drift, past valid_until
- `highest_drift_risk_nodes` — top 10 by risk
- `open_items` — unresolved registry items
- `required_resolution_authorities` — who must act
- `laundering_warnings` — detected temporal laundering

**Route:**
- `GET /api/temporal/integrity-panel`
- `GET /api/temporal/schema`

---

## New DB Tables (migration-safe)

```
anchor_events      — Re-anchor audit log (Fix B)
open_items         — Unresolved ambiguity registry (Fix D)
```

Migration order: `coherence_scores → anchor_events → open_items`

---

## Files Added / Modified

| File | Change |
|---|---|
| `app/core/temporal_governor.py` | New — Fixes A–F (908 lines) |
| `app/api/routes/temporal_governor_routes.py` | New — all routes |
| `app/db/connection.py` | `anchor_events`, `open_items` tables |
| `app/api/main.py` | Register `temporal_governor_router` |
| `app/core/coherence_decay.py` | P1 hardening: near-epoch sentinel rejection |
| `tests/test_phase24_2_temporal_governor.py` | New — 28 regression tests |

---

## Test Coverage (28/28 pass)

| Tests | Fix |
|---|---|
| `test_fix_a_low_drift_node_returns_correct_risk` | A |
| `test_fix_a_high_drift_node_is_detected` | A |
| `test_fix_a_temporal_ambiguity_always_high_risk` | A |
| `test_fix_a_drift_all_returns_sorted_high_first` | A |
| `test_fix_a_api_drift_endpoint` | A |
| `test_fix_b_re_anchor_forces_containment_and_returns_trinary` | B |
| `test_fix_b_re_anchor_creates_auditable_event` | B |
| `test_fix_b_autonomous_actor_rejected` | B |
| `test_fix_b_api_re_anchor_endpoint` | B |
| `test_fix_b_trinary_expired_node_has_blocked_entry` | B |
| `test_fix_c_resume_grants_single_plane_only` | C |
| `test_fix_c_second_resume_on_same_anchor_is_rejected` | C |
| `test_fix_c_invalid_plane_rejected` | C |
| `test_fix_c_api_resume_endpoint` | C |
| `test_fix_d_open_item_persists_until_explicitly_resolved` | D |
| `test_fix_d_resolved_by_human_succeeds` | D |
| `test_fix_d_autonomous_resolution_rejected` | D |
| `test_fix_d_expired_items_marked_automatically` | D |
| `test_fix_d_missing_required_fields_rejected` | D |
| `test_fix_d_api_open_items_lifecycle` | D |
| `test_fix_e_laundering_detected_on_expired_node` | E |
| `test_fix_e_laundering_detected_on_ambiguous_node` | E |
| `test_fix_e_fresh_node_has_no_laundering_warning` | E |
| `test_fix_e_api_laundering_check_endpoint` | E |
| `test_fix_f_integrity_panel_contains_required_sections` | F |
| `test_fix_f_api_integrity_panel_endpoint` | F |
| `test_fix_f_schema_endpoint_has_nanny_clause_description` | F |
| `test_migration_order_p242_after_p24` | infra |
