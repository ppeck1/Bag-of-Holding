# Phase 18 — Daenary Substrate Integration

## Test results: 739 passed, 3 skipped (43 new tests)

---

## Architectural Shift

    DAENARY → BOH → Applications

BOH is now the governed memory substrate for the Daenary cognition architecture.
Every node in the corpus carries an explicit epistemic state. The visualizations
project that state, not inferred document metadata.

---

## A. Epistemic State Model (`app/db/connection.py`)

Eleven new columns added to the `docs` table via `_add_column_if_missing`:

| Column | Type | Purpose |
|--------|------|---------|
| `epistemic_d` | INTEGER | Directional state: -1 / 0 / 1 |
| `epistemic_m` | TEXT | Zero-mode: contain / cancel / null |
| `epistemic_q` | REAL | Evidence quality: 0.0–1.0 |
| `epistemic_c` | REAL | Interpretation confidence: 0.0–1.0 |
| `epistemic_correction_status` | TEXT | accurate / incomplete / outdated / conflicting / likely_incorrect |
| `epistemic_valid_until` | TEXT | ISO date — required for non-canonical imported material |
| `epistemic_context_ref` | TEXT | Provenance context reference |
| `epistemic_source_ref` | TEXT | Source pipeline reference |
| `epistemic_last_evaluated` | TEXT | ISO timestamp of last epistemic assessment |
| `meaning_cost_json` | TEXT | JSON: processing/time/escalation/harm/reversal/opportunity/total |
| `custodian_review_state` | TEXT | Current custody routing state |

Migration is backward-compatible: all columns nullable, existing documents unaffected.
New indexes on `epistemic_d` and `custodian_review_state`.

---

## B. Custodian Layer (`app/core/custodian.py`)

New module implementing epistemic custody. Answers before any canonical mutation:

- What is being changed? (mutation_reason + evidence_refs)
- Why is it allowed? (contract validation)
- What confidence supports it? (epistemic_c gate)
- What evidence quality? (epistemic_q gate)
- What expires? (valid_until check)
- What gets contained? (d=0, m=contain routing)
- What gets canceled? (d=0, m=cancel routing)
- What is the cost if wrong? (meaning_cost gate)

### Invariants enforced

| Rule | Enforcement |
|------|-------------|
| Cannot canonicalize expired node | `valid_until < now` → `defer` |
| Cannot canonicalize d=0 without m | `errors` → `contain` |
| Cannot canonicalize m=cancel | `errors` → `reject` |
| Cannot canonicalize `likely_incorrect` | `errors` → `reject` |
| High-cost requires human_reviewed=true | `tier=high` gate |
| Critical cost blocks all auto-canonicalization | `tier=critical` gate |

### Key functions

- `can_canonicalize(doc, justification) → {allowed, errors, route, decision_mode, cost, tier}`
- `evaluate_mutation(doc, mutation_reason, ...) → full custodian verdict`
- `compute_meaning_cost(doc) → {processing, time, escalation, harm_if_wrong, reversal, opportunity, total}`
- `check_epistemic_contract(doc) → {valid, errors, warnings}`
- `get_custodian_lane(doc) → lane string`
- `route_zero_mode(doc) → 'contain' | 'cancel'`
- `cost_tier(total) → 'low' | 'moderate' | 'high' | 'critical'`

### Route priority (cancel beats escalate)

Contradiction (`m=cancel` or `correction=conflicting`) always routes to `reject`.
Escalation applies only when cost is high but no contradiction exists.

### Custodian lanes (8 governance states)

| Lane | Trigger |
|------|---------|
| `raw_imported` | No epistemic state |
| `expired` | `valid_until` in past |
| `canceled` | d=0, m=cancel |
| `contained` | d=0, m=contain |
| `under_review` | Has state, not meeting thresholds |
| `approved` | q≥0.65, c≥0.60, status=approved |
| `canonical` | canonical_layer=canonical |
| `archived` | Superseded / archived |

---

## C. Projection Endpoint — Phase 18 Daenary Modes

All four modes now consume real epistemic state. `get_projection_graph` passes
`epistemic_*` columns through from the DB to every node.

### Variable Overlay (real d/m/q/c values)

- **X axis**: epistemic_c (confidence)
- **Y axis**: epistemic_q (quality, top=high)
- **Color**: d-state (+1 green / 0 amber / -1 red / null dark)
- **Size**: epistemic_q
- **No-state nodes**: sentinel cluster lower-left
- **Sidebar**: d-state distribution, correction_status breakdown, mean q/c

Replaced: lexical keyword detection is demoted to fallback for legacy corpora.
Label added: "Lexical fallback: no Daenary metadata found."

### Viability Surface / Constraint Geometry (q × c axes)

- **X axis**: epistemic_c (confidence, right=high)
- **Y axis**: epistemic_q (quality, top=high)
- **Size**: meaning_cost.total (larger = costlier if wrong)
- **Color**: correction_status
- **Canvas**: q=0.65 and c=0.60 threshold lines define viability quadrant
- **Zones**: viable / contain_zone / weak_zone / low_zone / no_data
- **Sidebar**: quadrant counts, correction_status breakdown, top high-cost nodes

Replaced: project-band × risk-pressure layout (deterministic but shallow).

### Governance-State Topology / Constitutional (8 custodian lanes)

- **All nodes included** — no edge-based filtering (Phase 18 spec: F)
- **X axis**: custodian lane (raw_imported → expired → canceled → contained → under_review → approved → canonical → archived)
- **Color**: custodian lane color
- **Lane assignment**: `get_custodian_lane(node)` — epistemic state drives placement
- **Canvas**: 8 lane dividers + labels
- **Sidebar**: per-lane counts, canonical / contained / canceled / expired node lists

Replaced: 5-lane authority hierarchy (draft/review/approved/canonical/archived).

### Web mode: unchanged

---

## D. Demo Seed (`POST /api/input/demo-seed/daenary`)

25 documents covering the full epistemic state space:
high-quality canonical, contained, canceled, expired, escalated, approved,
ambiguous, likely-incorrect, cross-project contradiction, source mismatch,
overconfident weak evidence, moderate both axes, archived superseded, etc.

Each document has real `epistemic_d/m/q/c/correction_status/valid_until` values
that make all four visualization modes produce distinctly different layouts.

Existing `POST /api/input/demo-seed` (Phase 16.1) preserved unchanged.

---

## E. Frontend Changes (`app.js`, `style.css`, `index.html`)

### Canvas rendering

- `_nodeColor()`: mode-aware for variable (d-state), constraint (correction_status), constitutional (custodian lane)
- `_nodeRadius()`: variable mode = epistemic_q, constraint mode = meaning_cost.total
- `drawModeDecorations()`: variable/constraint show q/c axis labels; constitutional shows 8 labeled custodian lanes
- Tooltips: all modes show `ε: d=… m=… q=… c=…` epistemic badge

### Instrument panels

Three panels rebuilt to use real Daenary data:
- Variable Overlay: d-state bar chart, correction_status breakdown, priority node table
- Viability Surface: quadrant pills, correction distribution, high-cost node table
- Governance Topology: 8 lane pills, canonical/contained/canceled/expired node lists

All panels show "Load Daenary Demo" button when no epistemic data is present.

### New CSS classes (Phase 18)

`.ep-badge`, `.ep-d`, `.ep-d-pos/zero/neg/none`, `.ep-m-contain/cancel`,
`.ep-qc`, `.ep-correction-*`, `.ep-lane-*`, `.ep-zone-*`

### UI additions

- "⊛ Daenary Demo" button added to Inbox panel Start Here section
- `loadDaenaryDemoSeed()` JS function

---

## F. Tests (43 new tests in `tests/test_phase18_daenary.py`)

| Class | Tests | Covers |
|-------|-------|--------|
| `TestExpiredNode` | 4 | K1 — cannot canonicalize expired |
| `TestZeroModeRequired` | 4 | K2 — d=0 requires m |
| `TestCancelState` | 5 | K3 — cancel blocks promotion |
| `TestMeaningCostGate` | 4 | K4 — high-cost requires review |
| `TestContainSearchable` | 2 | K5 — contain remains visible |
| `TestCancelVisible` | 3 | K6 — cancel remains visible |
| `TestProjectionEpistemicFields` | 2 | K7 — projection returns epistemic fields |
| `TestConstitutionalAllNodes` | 2 | K8 — constitutional includes all nodes |
| `TestVariableOverlayEpistemicValues` | 3 | K9 — variable overlay uses real values |
| `TestConstraintGeometryAxes` | 3 | K10 — constraint uses q/c axes |
| `TestCustodianHelpers` | 11 | Contract helpers, colors, constants |

Phase 17.3 tests updated for Phase 18 interface changes:
- `test_variable_and_constitutional_modes` — checks custodian_lane instead of edge filtering
- `TestDiagnostics` — `NO_CUSTODIAN_DATA` replaces `NO_AUTHORITY_EDGES`
- `TestSidebarVariableGap` — reads epistemic fields instead of _var_fields
