# BOH v2 — Phase 24.3 + Phase 25

## Status

Mandatory architectural correction. Four governance failures resolved.

---

## Part I — Phase 24.3: Resolution Authority Enforcement

### Fix A — Hard Authority Enforcement Layer

**Module:** `app/core/authority_guard.py`

`validate_resolution_authority(actor, required_authority, target_id, target_type)` enforces that only the declared authority may resolve. Matching checks: actor_id, actor_role, actor_team, actor_scope, actor_plane_authority against required_authority.

Every attempt is logged to `authority_resolution_log`. Rejected attempts are preserved. Failure to resolve is data.

Rejection payload:
```json
{
  "authorized": false,
  "failure_reason": "resolution authority mismatch",
  "required_authority": "...",
  "actor_authority": {...},
  "escalation_required": true
}
```

`authority_gated_resolve()` and `authority_gated_resume()` wrap the resolution gates.

**Routes:**
- `POST /api/authority/validate`
- `POST /api/authority/gated-resolve/{item_id}`
- `POST /api/authority/gated-resume`
- `GET /api/authority/log`

**New table:** `authority_resolution_log` — all attempts, authorized or not.

### Fix B — Authority Promotion Contract

`promote_resolution_authority(old, new, reason, approved_by, ...)` enforces: explicit, justified (≥20 chars), signed by a named human, creates lineage. Self-promotion rejected. Autonomous promotion rejected. Short reasons rejected.

Promotion output becomes part of canonical lineage. When `target_type="open_item"`, the item's `resolution_authority` is updated in place.

**Routes:** `POST /api/authority/promote`, `GET /api/authority/promotions`

**New table:** `authority_promotions` — immutable lineage record.

---

## Part II — Phase 24.3: Temporal Escalation Ladder

### Fix C — Escalation Ladder Engine

**Module:** `app/core/temporal_escalation.py`

`run_escalation(node_id)` evaluates drift and applies the mandatory escalation contract:

| Level | Status | Action |
|---|---|---|
| LOW | monitored | None |
| MODERATE | warning | Owner notified, refresh_due assigned |
| HIGH | containment | Forced d=0, m=contain, anchor created, authority engaged |
| PERSISTENT HIGH | escalation | Authority promotion mandatory, supervisory routing, scope reduction |

Persistent HIGH is detected when a HIGH-drift node has an active anchor older than its `max_resolution_window_hours`.

`escalate_all()` sweeps all nodes.

Bug fixed in this patch: plane extraction now comes directly from the `LatticeNode` rather than the drift state dict (which has no `node` field).

**Routes:** `POST /api/escalation/run/{node_id}`, `POST /api/escalation/run-all`, `GET /api/escalation/events`

**New table:** `escalation_events`

### Fix D — Escalation Routing Registry

`register_escalation_route(plane, severity, owner, supervisor, ...)` answers: who gets paged, when, why, what authority changes. No governance by memory.

Route lookup: `get_escalation_route(plane, severity)` with wildcard fallback to `plane='*'`.

**Routes:** `POST /api/escalation/registry`, `GET /api/escalation/registry`

**New table:** `escalation_registry` — PK: (plane, severity)

---

## Part III — Phase 24.3: Integrity-First User Surface

### Fix E — Integrity Panel as Primary Dashboard

**Module:** `app/core/integrity_surface.py`

`integrity_first_dashboard()` returns sections in mandatory order:

1. `integrity_state` — overall score + label
2. `open_containments` — active anchors
3. `highest_drift_risk` — top nodes with visual states
4. `authority_violations` — rejected resolution attempts
5. `expired_without_refresh`
6. `open_registry_items`
7. `laundering_warnings`
8. `library_content` — last; truth precedes content

`integrity_score` ∈ [0.0, 1.0]. Labels: VERIFIED / DRIFTING / DEGRADED / COMPROMISED.

**Route:** `GET /api/integrity/dashboard`

### Fix F — Explicit Visual States

`compute_visual_state(drift, escalation_level, authority_blocked)` returns one of:

| State | Condition |
|---|---|
| UNKNOWN | Temporal ambiguity |
| ESCALATED | escalation_level in containment/escalation |
| AUTHORITY_BLOCKED | Previous resolution rejected |
| EXPIRED | valid_until elapsed |
| CONTAINED | Active anchor event |
| DRIFTING | moderate/high drift |
| VERIFIED | Low drift, fresh |

**Route:** `GET /api/integrity/visual-state/{node_id}`

---

## Part IV — Phase 25: Substrate Lattice

### Fix G — Scalar-3³ Persistence Architecture

**Module:** `app/core/substrate_lattice.py`

9-coordinate persistence registry. Every persistent system maps here without free-form metaphor.

```
Constraint (K): K.P  K.I  K.S
State (X):      X.P  X.I  X.S
Dynamic (F):    F.P  F.I  F.S

Plus: CPL (coupling map), PROJ (projection operator), OBS (observation model)
```

Evolution equation: `X_{t+1} = Π_K(F(X_t))`

`register_lattice_object(obj)` validates all 9 coordinates are populated. Objects declaring `requires_new_ontology=True` are blocked. `project_state()` applies the PROJ operator.

**Routes:** `POST /api/substrate/register`, `GET /api/substrate/objects`, `GET /api/substrate/project/{lattice_id}`

**New table:** `substrate_lattice_registry`

### Fix H — Anti-Bullshit Validation Test

`run_validation_test()` maps three canonical domains using NO NEW TOKENS:

1. **Musical section** — K.P: acoustic/tempo constraints; K.I: harmonic grammar; K.S: compositional intent; X: chord/harmonic/tension states; F: note selection/resolution/arc update rules
2. **Single-cell lifecycle phase** — K.P: metabolic constraints; K.I: gene regulatory checkpoints; K.S: epigenetic fate locks; X: organelle/expression/fate states; F: metabolic/transcriptional/differentiation updates
3. **Roman Empire era slice** — K.P: geographic frontier; K.I: administrative/legal constraints; K.S: legitimacy/succession norms; X: troop/records/authority states; F: campaign/administrative/succession updates

All three map completely. No new ontology required. Verdict: **LATTICE STRUCTURALLY VIABLE**.

**Route:** `POST /api/substrate/validate`

---

## Files Added / Modified

| File | Change |
|---|---|
| `app/core/authority_guard.py` | New — Fix A + Fix B (403 lines) |
| `app/core/temporal_escalation.py` | New — Fix C + Fix D (410 lines) |
| `app/core/integrity_surface.py` | New — Fix E + Fix F (290 lines) |
| `app/core/substrate_lattice.py` | New — Fix G + Fix H (493 lines) |
| `app/api/routes/authority_routes.py` | New |
| `app/api/routes/escalation_routes.py` | New |
| `app/api/routes/integrity_routes.py` | New |
| `app/api/routes/substrate_routes.py` | New |
| `app/db/connection.py` | 4 new tables + indexes |
| `app/api/main.py` | 4 new routers registered |
| `tests/test_phase24_3_and_25.py` | New — 39 regression tests |

## Test Results: 39/39 passed

---

## Supplemental Patch Applied in This Turn

Additional enforcement from the whitepage patch was applied after the initial Phase 24.3/25 bundle:

### POST /api/governance/resolve

Added a direct governance resolution endpoint that enforces server-side authority validation before any open item can be resolved.

Failure contract now returns the required Phase 24.3 structure for unauthorized attempts:

```json
{
  "status": "rejected",
  "reason": "authority_mismatch",
  "failure_type": ["identity", "team", "role", "scope"],
  "required_authority": "...",
  "attempted_by": "...",
  "authority_valid": false,
  "governance_event": true
}
```

### Authority Guard Failure Payloads

`authority_gated_resolve()` and `authority_gated_resume()` now include:

- `status: rejected`
- `reason: authority_mismatch`
- `authority_valid: false`
- `failure_type: [identity, team, role, scope]`
- `attempted_by`

This aligns the runtime failure object with the whitepage's required hard-reject contract.

### Integrity Panel as Primary UI

The frontend now loads the Integrity Panel as the default landing surface instead of the generic dashboard.

Changes:

- Added `Integrity Panel` as the first nav item.
- Added `panel-integrity` as the active default panel.
- Changed no-hash route fallback from `dashboard` to `integrity`.
- Added `loadIntegrityDashboard()` backed by `GET /api/integrity/dashboard`.
- Displays integrity label, score, authority violations, containments, escalations, highest drift risks, rejected authority attempts, and open registry items before ordinary content interaction.

### Validation

Targeted Phase 24.3/25 regression suite:

```text
39 passed
```
