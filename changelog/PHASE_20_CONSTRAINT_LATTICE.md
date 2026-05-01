# Phase 20 — Constraint Lattice + Certificate Gate

## Test results: 913 collected (57 new), all passing

---

## Purpose

Phase 19.5 made projection honest.

Phase 20 makes canonical mutation lawful.

This patch establishes the actual transition authority system:

    d=0 → ±1    requires certificate
    ±1 → canon  requires certificate
    projection  may inform review
    projection  may NEVER mutate canon

This is the hard trust boundary.

---

## Canonical Mutation Invariant (enforced, not advisory)

No node may transition d=0 → d=±1, or epistemic_state → canonical,
without a valid certificate. No exceptions. No UI bypass. No admin bypass.
No LLM bypass. No projection bypass.

The invariant is enforced at three levels:
1. `constraint_lattice.check_transition_legal()` — rejects at runtime
2. `certificate.validate_certificate_request()` — rejects at request time
3. Static inspection tests — verify projection source contains no mutation calls

---

## New modules

### `app/core/constraint_lattice.py` — Lattice Rules A–D

**Rule A — Zero State Legitimacy**
`d=0` is a valid, stable state. Not incomplete. Not failure. Active containment.
The system must not pressure forced resolution. Aligns with Daenary trinary state law.

**Rule B — Forced Collapse Detection**
`d=0 → ±1` without certificate is a forced collapse event.
- Detected by `is_forced_collapse(from_d, to_d, has_certificate)`
- Blocked by `check_transition_legal()`
- Logged as `severity=critical` in the immutable `lattice_events` table
- Matches `E_rp(t) = 1` from the CANON collapse model

**Rule C — Authority Alignment**
Mutation authority must match plane responsibility.
- `projection` → rank 0 (cannot certify anything)
- `llm` → rank 0 (cannot certify anything)
- `automated` → rank 0 (cannot certify anything)
- `Viewer` → rank 0 | `Internal` → rank 2 | `Evidence` → rank 3
- `Governance` → rank 5 | `Canonical` → rank 6
- Wrong-plane authority = invalid certificate

**Rule D — Expiry Decay**
Expired certificates block promotion. No stale authority.
Matches `C(t) = C₀e^(-kτ) + R(t)`.

**Key functions:**
| Function | Description |
|----------|-------------|
| `check_transition_legal(from_d, to_d, certificate)` | Full 4-rule legality check |
| `is_forced_collapse(from_d, to_d, has_certificate)` | Rule B detector |
| `can_apply_transition(doc, to_d, certificate)` | Document-level gate + collapse logging |
| `log_lattice_event(...)` | Append-only lattice event log |
| `get_lattice_events(node_id)` | Read immutable event history |
| `get_risk_class(from_d, to_d)` | Risk tier for a transition |
| `get_qc_thresholds(risk_class)` | Q/C minimums by tier |

**Risk class thresholds:**

| Tier | min_q | min_c | Example transitions |
|------|-------|-------|---------------------|
| low | 0.60 | 0.50 | None → contain/affirm |
| moderate | 0.70 | 0.60 | contain→affirm, revert |
| high | 0.85 | 0.75 | contain→negate, affirm→negate |
| critical | 0.95 | 0.90 | (reserved) |

### `app/core/certificate.py` — Certificate CRUD + Validation

**Mutation path (the only legal path):**
```
request_certificate() → pending
  → review → approve_certificate() → approved
    → can_apply_transition() validates certificate → transition executes
```

There is no shortcut. No bypass. No admin exception.

**Certificate fields:**
```
certificate_id   str    CERT_{10-char hex}
node_id          str    required
from_d/to_d      int    must differ (no identity certs)
reason           str    required, non-empty
evidence_refs    list   MUST be non-empty
issuer_type      str    MUST be "human" (llm/projection/automated rejected)
review_required  bool   auto-true for d=0 → ±1 and high-risk
risk_class       str    derived from (from_d, to_d)
q, c             float  must meet risk-class thresholds
valid_until      str    ISO datetime, must be future at request time
status           str    pending / approved / rejected / revoked
plane_authority  str    must match or exceed target plane (Rule C)
```

**Key functions:**
| Function | Description |
|----------|-------------|
| `request_certificate(...)` | Validate + persist pending cert |
| `approve_certificate(cert_id, reviewed_by)` | Approve (does not apply transition) |
| `reject_certificate(cert_id, reviewed_by, note)` | Reject |
| `revoke_certificate(cert_id, revoked_by, reason)` | Revoke approved cert |
| `request_reversion_certificate(...)` | Canonical → contain reversion path |
| `get_certificate(cert_id)` | Retrieve single cert |
| `get_certificate_history(node_id)` | All certs for node (immutable) |
| `get_pending_certificates()` | Pending queue |

**Reversion is lawful and auditable.** `canonical → review → revert` also requires a certificate — no silent rollback. History is never deleted. `(1, 0)` and `(-1, 0)` reversion transitions are moderate-risk (min_q=0.70, min_c=0.60).

---

## DB schema (`app/db/connection.py`)

Two new tables with indexes:

```sql
certificates(
  certificate_id, node_id, from_d, to_d, from_mode, to_mode,
  reason, evidence_refs_json, issuer_type, review_required,
  risk_class, cost_of_wrong, q, c, valid_until, context_ref,
  created_at, status, reviewed_at, reviewed_by, review_note,
  plane_authority
)

lattice_events(
  id, event_type, certificate_id, node_id, from_d, to_d,
  from_mode, to_mode, reason, detected_at, severity, detail_json
)
```

Both tables are append-only. No delete functions are exposed.

---

## API routes (`app/api/routes/certificate_routes.py`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/certificate/request` | Request a transition certificate |
| POST | `/api/certificate/review` | Approve, reject, or revoke |
| GET | `/api/certificate/pending` | List pending certificates |
| GET | `/api/certificate/{cert_id}` | Get a single certificate |
| GET | `/api/node/{node_id}/certificate-history` | Full cert history (immutable) |
| POST | `/api/certificate/reversion` | Request canonical reversion |
| GET | `/api/lattice/events` | Global lattice event log (immutable) |
| GET | `/api/lattice/events/{node_id}` | Events for a specific node |
| GET | `/api/lattice/check` | Read-only legality check (no mutation) |

---

## UI changes (`index.html`, `app.js`, `style.css`)

### Certificate Review Queue (in Custodian Layer panel)
- Pending certificate table with: node, transition (d=X→Y), risk class, reason, q/c, expiry, approve/reject actions
- Explicit approve/reject with reviewer name and review note
- No automation — every action is a user gesture

### Request Certificate form
- Node ID, from/to d selectors, reason, evidence refs
- q/c inputs with validation
- valid_until date picker
- cost_of_wrong (optional)
- Submit creates pending certificate

### Node state badges (`.cert-badge-*`)
```
contained          amber pill
pending_review     blue pill
certified          green pill
canonical          bright green pill
expired            gray pill
reverted           slate pill
blocked            red pill
forced_collapse    pulsing red (CSS animation)
```

Locations: Custodian Layer panel, library rows (via `certStateBadge()` JS helper).

---

## Scope boundary (strictly observed)

This patch adds ONLY:
- ✓ Constraint lattice transition gate
- ✓ Certificate object, validation, CRUD
- ✓ Mutation permission enforcement
- ✓ Forced collapse detection and logging
- ✓ Promotion/reversion audit trail
- ✓ Certificate Review Queue UI
- ✓ Regression tests

This patch does NOT add:
- ✗ LLM autonomous approval
- ✗ Automatic canonical promotion
- ✗ Projection-driven mutation
- ✗ Scoring-based canon promotion
- ✗ Predictive mutation engine
- ✗ Membrane security
- ✗ External trust federation
- ✗ Multi-user delegation

---

## Tests: 57 new in `tests/test_phase20_certificate.py`

| Class | Tests | Covers |
|-------|-------|--------|
| `TestZeroToPositiveBlockedWithoutCert` | 5 | T1 |
| `TestZeroToNegativeBlockedWithoutCert` | 5 | T2 |
| `TestPromotionBlockedWithoutReview` | 4 | T3 |
| `TestProjectionCannotPromoteCanon` | 7 | T4 + T11 static |
| `TestExpiredCertificateBlocked` | 3 | T5 |
| `TestInvalidEvidenceBlocked` | 4 | T6 |
| `TestWrongPlaneAuthorityRejected` | 3 | T7 |
| `TestForcedCollapseLogged` | 4 | T8 |
| `TestReversionRequiresCertificate` | 4 | T9 |
| `TestCertificateHistoryImmutable` | 5 | T10 |
| `TestStaticProjectionNoMutation` | 2 | T11 |
| `TestStaticPromotionRequiresCert` | 5 | T12 |
| `TestCertificateCRUD` | 5 | Full lifecycle |

---

## Roadmap position

```
✓ Phase 18   — Daenary state contract
✓ Phase 19   — Plane Card storage
✓ Phase 19.5 — Projection manifest layer
✓ Phase 20   — Constraint lattice + certificate gate (this patch)
  Phase 21   — Plane interfaces (cross-plane translation)
  Phase 22   — Plane-aware retrieval
  Phase 23   — Membrane security
```
