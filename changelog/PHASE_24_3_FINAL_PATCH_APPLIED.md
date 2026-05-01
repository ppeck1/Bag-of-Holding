# Phase 24.3 Final Patch Applied
## Authority Legitimacy Enforcement Tightening

This pass tightens the attached Phase 24.3 / Phase 25 patch around the largest remaining trust failure: legitimate-looking canonical mutation by the wrong actor, team, role, or scope.

## Implemented adjustments

### 1. Hard server-side authority contract validation

`app/core/authority_guard.py` now derives authority validity on the server only.

Validation now evaluates the declared authority contract across:

- `identity` — attempting actor must match the required resolver
- `team` — actor must belong to the required authority domain when declared
- `role` — actor must hold the required mutation-capable role when declared
- `scope` — actor authority must cover the required node / plane / field scope when declared

The client cannot submit or override `authority_valid`.

### 2. Structured failure typing

Rejected attempts now return explicit `failure_type` values, such as:

```json
["identity", "team", "role", "scope"]
```

This converts failed resolution into a governance signal rather than a generic validation error.

### 3. Authority contract support in open-item metadata

`authority_gated_resolve()` now loads open item `metadata_json` and `context_ref_json` and passes that server-held context into the authority validator.

Supported metadata contract examples:

```json
{
  "authority_contract": {
    "resolver": "clinical-canon-custodian-01",
    "team": "Clinical Governance",
    "role": "resolver",
    "scope": "triage.protocols"
  }
}
```

or:

```json
{
  "required_authority": {
    "resolver_id": "clinical-canon-custodian-01",
    "authority_domain": "Clinical Governance",
    "required_role": "resolver",
    "node_scope": "triage.protocols"
  }
}
```

### 4. Migration compatibility retained

Existing open items that only contain legacy `resolution_authority` still validate against resolver identity, while new structured items can enforce all four legitimacy dimensions.

This avoids breaking current test data while allowing strict scoped authority enforcement going forward.

## Validation performed

Python syntax validation passed for:

- `app/core/authority_guard.py`
- `app/api/routes/governance_routes.py`
- `app/core/integrity_surface.py`
- `app/core/temporal_escalation.py`

## Net effect

The build now better matches the patch requirement:

> Canonical truth may mutate only through legitimate scoped authority.

This moves the system closer to hard legitimacy enforcement rather than visible-but-bypassable governance.
