# BOH v2 Patch — Phase 24.3 Finalization + Phase 25 Governance Hardening

## Purpose

This patch addresses the assessment that the build still protected workflow more strongly than truth. The patch moves the system closer to canonical governance infrastructure by making authority, Daenary custody, escalation, integrity surfacing, and governance-native observability more binding.

## Implemented Changes

### 1. Authority legitimacy enforcement hardened

Changed `app/core/temporal_governor.py` so `resolve_open_item()` is no longer a generic human-resolution path.

Canonical resolution now requires one of the following:

1. Prior server-side authority validation through `authority_gated_resolve(..., authority_validated=True)`.
2. A narrow legacy fallback only for simple, non-expanded authority contracts where `resolved_by` exactly matches `resolution_authority`.

This blocks the previous failure mode where any named human could resolve an item.

Changed `app/core/authority_guard.py` so `authority_gated_resolve()` now passes the authority-validated flag into the final mutation gate and returns the full server-derived authority contract on success.

Expanded authority contracts continue to enforce:

- resolver identity
- team/domain
- role
- scope

### 2. Direct temporal open-item resolution route downgraded

Changed `POST /api/temporal/open-items/{item_id}/resolve`.

This route now rejects unauthorized direct resolution attempts and tells callers to use:

```text
POST /api/governance/resolve
```

This prevents the temporal registry route from bypassing the authority legitimacy gate.

### 3. Daenary Custodian State added as mutation substrate

Added:

```text
app/core/custodian_state.py
```

This introduces a normalized Daenary Custodian State contract:

```json
{
  "d": 0,
  "m": "contain",
  "q": 0.0,
  "c": 0.0,
  "valid_until": null,
  "context_ref": null,
  "correction_status": "incomplete",
  "canonical_lock": false
}
```

Open registry items now automatically carry:

```json
metadata.daenary_custodian_state
```

This means the queue is no longer the only operational substrate. Every unresolved item now has a Daenary custody state attached.

### 4. Custodian gate connected to authority resolution

`authority_gated_resolve()` now evaluates Daenary custody before allowing resolution.

The gate blocks resolution if the state is:

- canonically locked
- contradiction-canceled
- explicitly conflicting
- likely incorrect
- outdated
- expired

This makes Daenary custody operational rather than decorative.

### 5. Temporal escalation made binding through canonical locks

Added canonical lock persistence to the escalation engine.

Changed:

```text
app/core/temporal_escalation.py
```

High drift containment now creates an active canonical lock.

Persistent high drift forced escalation now also creates an active canonical lock.

Added schema support in:

```text
app/db/connection.py
```

New table:

```sql
canonical_locks
```

This makes containment operationally binding instead of only visible.

### 6. Governance-native observability added

Added:

```text
app/core/governance_metrics.py
app/api/routes/governance_metrics_routes.py
```

New endpoint:

```text
GET /api/governance/metrics
```

Primary metrics now include:

- unauthorized mutation attempts
- authority mismatch frequency
- forced escalation count
- containment count
- drift frequency
- high drift frequency
- canonical lock frequency
- average resolution latency
- open registry items
- expired registry items

### 7. `/api/status` reframed around trust state

Changed:

```text
app/api/routes/status_routes.py
```

`/api/status` now includes:

```json
{
  "primary_status_surface": "/api/integrity/dashboard",
  "governance_native_metrics": {}
}
```

This makes the status surface point toward integrity first rather than treating uptime and queue depth as primary truth.

### 8. Main API registered governance metrics route

Changed:

```text
app/api/main.py
```

Registered:

```text
governance_metrics_router
```

## Validation

Syntax compilation passed for the modified modules.

Targeted Phase 24.3/25 test suite result:

```text
39 passed
```

Command used:

```bash
python -m pytest tests/test_phase24_3_and_25.py -q
```

Note: the older Phase 24.2 temporal-governor test suite contains legacy expectations that direct human resolution through `/api/temporal/open-items/{id}/resolve` should succeed. That behavior is intentionally restricted by this hardening patch because it was the unresolved bypass described in the assessment.

## Net Effect

Before this patch:

```text
human approval could still appear legitimate without proving scoped authority
```

After this patch:

```text
canonical resolution must pass authority validation and Daenary custody checks before mutation
```

This moves BOH closer to the intended product boundary:

```text
canonical governance infrastructure
```

not:

```text
review queue software
```
