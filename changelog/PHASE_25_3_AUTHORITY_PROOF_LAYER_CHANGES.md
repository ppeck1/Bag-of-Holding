# Phase 25.3–25.8 Patch Applied

## Implemented

### 25.3 Authority Proof Layer
- Changed authority failure dimension from generic `identity` to explicit `resolver`.
- Authority validation now returns the required failure contract fields:
  - `status: rejected`
  - `reason: authority_mismatch`
  - `failure_type: resolver/team/role/scope`
  - `required_authority`
  - `attempted_by`
  - `canonical_lock: true`
- Unauthorized mutation attempts now create active canonical locks.
- Unauthorized attempts remain permanent governance events through `authority_resolution_log`.

### 25.4 Daenary Sovereignty
- Authority-gated resolution now uses `canonical_mutation=True`.
- Daenary state is now binding for canonical mutation.
- Active server-side canonical locks are checked by the Daenary custodian gate.

### 25.5 Binding Escalation Ladder
- Persistent high drift now transfers unresolved open-item authority to the registered supervisor.
- Forced escalation metadata records the authority transfer rule.
- Forced escalation continues to impose canonical lock and scope reduction.

### 25.6 Integrity-First Default
- Existing UI default already routes blank hash to `integrity`.
- Integrity dashboard remains the primary trust surface.

### 25.7 Governance Stress Demo
- Seed script extended with authority mismatch attempts, canonical locks, escalation events, and governance-native failure metrics.

### 25.8 Governance-Native Metrics
- Existing `/api/governance/metrics` route retained as primary legitimacy metric surface.

### Substrate Lattice Alignment
- Existing `/api/substrate/schema` and registry routes retained.
- BOH mapping remains:
  - Constraint Geometry → `SC3.K.*`
  - Daenary State → `SC3.X.*`
  - Escalation/Custodian Actions → `SC3.F.*`
  - Integrity Panel → `SC3.OBS`
  - Canonical Lock → `SC3.PROJ`

## Product Boundary
This patch strengthens the key proof condition:

governance is not merely visible; illegitimate canonical mutation is structurally blocked.
