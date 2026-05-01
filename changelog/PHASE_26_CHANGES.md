# PHASE_26_CHANGES.md
# Phase 26 Patch — Constitutive Boundaries + Authority Proof + Canonical Doctrine + Substrate Decision

## Status: Applied. All 24 Phase 26A adversarial tests pass.

---

## Phase 26A — Adversarial Authority Testing

**Deliverable: `AUTHORITY_PROOF_MATRIX.md`**

### New Code
- No new code required — authority enforcement was already structurally correct.
- Phase 26A proves it.

### New Test File
- `tests/test_phase26a_authority_proof.py`
  - 24 adversarial attack-path tests
  - Covers: Wrong User, Wrong Team, Wrong Role, Wrong Scope, Escalation Bypass, Expired Validity, Self-Promotion, Synthetic Resolver Injection, SC3 Plane Mismatch, Legibility Quality, Combined Failures, Audit Permanence, SC3 Classification, API smoke tests
  - All 24 tests pass

### New Document
- `AUTHORITY_PROOF_MATRIX.md` — formal proof that the wrong actor cannot mutate canonical truth

---

## Phase 26B — Canonical Architecture Doctrine

**Deliverable: `BOH_SYSTEM_v1.md`**

### New Document
- `BOH_SYSTEM_v1.md` — single canonical operating doctrine
  - What BOH is (canonical governance infrastructure)
  - Constitutive vs. descriptive zone distinction
  - Authority chain: what may mutate truth
  - Escalation ladder and authority transfer model
  - Daenary → Rubrix relationship
  - Atlas as visibility surface (not authority surface)
  - SC3 mapping (not an ontology split)
  - The actual product definition
  - 8 architectural invariants
  - Use cases and non-use cases

This document supersedes all patch notes, implementation fragments, and historical descriptions. It is the authoritative truth about what BOH is.

---

## Phase 26C — SC3 Constitutive Decision

**Deliverable: `SC3_CONSTITUTIVE_MAPPING.md` + `app/core/sc3_constitutive.py`**

### New Code: `app/core/sc3_constitutive.py`

The SC3 constitutive closure decision, implemented:

- `PLANE_HIERARCHY` — physical(3) > informational(2) > subjective(1)
- `CONSTITUTIVE_ACTIONS` — set of actions where SC3 changes system behavior
- `DESCRIPTIVE_ACTIONS` — set of actions where SC3 is orientation only
- `sc3_constitutive_check(action)` — returns constitutive/descriptive classification
- `sc3_plane_hierarchy_check(source, target)` — returns allowed/blocked with explanation
- `sc3_promotion_gate(doc_id, metadata, target_state, ...)` — full canonical promotion gate
- `sc3_map_node_to_plane(metadata)` — infers SC3 plane from node metadata
- `list_sc3_violations()` — audit trail of all SC3 constitutive violations
- `sc3_mapping_summary()` — full machine-readable architecture decision

**Enforcement rule:**
- `subjective → physical`: BLOCKED (critical severity) — Physical Canon Custodian required
- `subjective → informational`: BLOCKED (high severity) — Informational Canon Custodian required
- `informational → physical`: BLOCKED (medium severity) — Physical Canon Custodian required
- Same-plane: SC3 passes, normal governance applies
- Higher → lower: SC3 passes, normal governance applies

### New API Routes (added to `app/api/routes/authority_routes.py`)

- `POST /api/authority/sc3/check` — action constitutive/descriptive check
- `POST /api/authority/sc3/promotion-gate` — canonical promotion plane enforcement
- `POST /api/authority/sc3/infer-plane` — infer epistemic plane from metadata
- `GET /api/authority/sc3/violations` — SC3 violation audit trail
- `GET /api/authority/sc3/mapping` — full architecture decision document

### Database Migration

- New table: `sc3_violations` (indexed on action, node_id)
  - `violation_id`, `action`, `node_id`, `source_plane`, `target_plane`
  - `requested_by`, `required_resolver`, `severity`, `explanation`
  - `created_at`, `metadata_json`
- Added to `app/db/connection.py` migration pass
- Schema version stamped: `v2.6.0-phase26`

### New Document
- `SC3_CONSTITUTIVE_MAPPING.md` — full constitutive/descriptive zone mapping, mutation rules, projection enforcement, ontology drift prevention

---

## Phase 26D — User Legibility Layer

**Deliverable: `app/core/legibility.py` + updated routes**

### New Code: `app/core/legibility.py`

Translates every blocked action into a structured, legible explanation:

- `explain_block(authority_result)` — translate authority rejection into legible payload
- `explain_sc3_block(sc3_result)` — translate SC3 plane mismatch into legible payload
- `explain_daenary_block(daenary_gate)` — translate Daenary state block into legible payload
- `explain_any_block(result, action_type)` — universal dispatcher (detects block type automatically)

Every legibility payload contains:
- `title` — what was blocked
- `subtitle` — specific failure dimension
- `why_blocked` — detailed explanation per failure type
- `failure_dimensions` — list of dimensions that failed
- `who_must_resolve` — **named**, not abstract
- `escalation_state` — warning / contain / forced_escalation / locked / resolved
- `escalation_label` — human-readable escalation state
- `next_path` — concrete path forward
- `why_override_impossible` — machine truth explanation, not policy language
- `attempted_by` — who tried
- `actor_context` — what authority the actor had
- `required_authority_summary` — what was required
- `audit_note` — reminder that rejection is permanent

### Updated Routes

- `POST /api/authority/validate` — now includes `legibility` payload in rejected responses
- `POST /api/authority/gated-resolve/{item_id}` — now includes `legibility` in 403 detail
- `POST /api/authority/gated-resume` — now includes `legibility` in 403 detail

### New API Route

- `POST /api/authority/explain` — translate any block result into legible explanation
  - Input: any result dict + action_type
  - Output: full legibility payload
  - Auto-detects block type (SC3 / Daenary / authority / generic)

---

## What Was NOT Done (by design)

Phase 26 explicitly avoids:
- No new dashboards
- No new symbolic layers
- No new ontology
- No prettier surfaces

This is the compression phase, not the expansion phase.

The additions are:
- Proof (26A tests)
- Doctrine (26B document)
- Architecture closure (26C SC3 decision)
- Legibility (26D explanation layer)

All four are subtractive from complexity, not additive.

---

## Architectural Invariants Confirmed by Phase 26

1. **Wrong actor cannot mutate truth** — proven by 26A-1 through 26A-7
2. **SC3 is infrastructure at constitutive boundaries** — proven by 26A-8, implemented in 26C
3. **Every rejection is legible** — proven by 26A-9, implemented in 26D
4. **Audit is permanent** — proven by 26A-11
5. **SC3 requires no new ontology tokens** — confirmed (no new coordinates added)
6. **Exploration is fast, truth is expensive** — constitutive/descriptive distinction enforced

---

## Test Results

```
tests/test_phase26a_authority_proof.py — 24/24 PASS
```

Pre-existing failures (not introduced by Phase 26):
- `test_phase15_approval.py` — 14 failures from Phase 20.1 (direct promotion path removed; 410 Gone)
- `test_phase24_3_and_25.py::test_fix_a_correct_authority_resolves` — 1 failure from Phase 25 Daenary gate now binding (open item created with q=0.0, c=0.0 fails custodian gate)

Phase 26 introduces zero new failures.
