# PHASE_26_1_CHANGES.md
# Phase 26.1 — User-Facing Language Translation Layer

**Status: Applied. All routes pass. No architectural renames.**

---

## Core Principle

> Keep internal architecture names.
> Simplify only the user-facing operational surface.

Internal names unchanged: `Daenary`, `Rubrix`, `Atlas`, `canonical`, `SC3`, `contained`, `cancelled`

User-facing labels updated everywhere they appear in the UI.

---

## Translation Table (Canonical Reference)

| Internal Name | User-Facing Label |
|--------------|-------------------|
| Integrity Panel | **Authority Center** |
| Daenary State | **Confidence State** |
| Constitutional Mode | **Authority Path** |
| Constraint Geometry | **Risk Map** |
| Variable Overlay | **Evidence State** |
| Review Queue | **Resolution Center** |
| Suggested Changes | **Proposed Changes** |
| Planes | **Domains** |
| Canonical | **Trusted Source** |
| Contained | **Held for Resolution** |
| Cancelled / Canceled | **Contradiction Blocked** |

---

## Files Changed

### `app/ui/index.html`

| Location | Old Label | New Label |
|----------|-----------|-----------|
| Nav item | Integrity Panel | Authority Center |
| Nav item | Suggested Changes | Proposed Changes |
| Nav item | Planes | Domains |
| Panel `aria-label` | Integrity Panel | Authority Center |
| Panel title | Integrity Panel | Authority Center |
| Lifecycle ladder | Canonical | Trusted Source (+ better subtitle) |
| Stat card | Planes Indexed | Domains Indexed |
| Section head | Daenary substrate state | Confidence State |
| Viz mode button | Variable Overlay | Evidence State |
| Viz mode button | Constraint Geometry | Risk Map |
| Viz mode button | Constitutional | Authority Path |
| Governance prose | "contain" / "cancel" | Held for Resolution / Contradiction Blocked |
| Governance tab button | Review Queue | Resolution Center |
| Governance tab button | `loadReview CenterLedger()` *(broken)* | `loadResolutionLedger()` *(fixed)* |
| Certificate section | Certificate Review Queue | Certificate Resolution Center |
| Panel comment | Panel: Suggested Changes | Panel: Proposed Changes |
| Panel `aria-label` | Suggested Changes | Proposed Changes |
| Panel title | Suggested Changes | Proposed Changes |
| LLM queue warning | Canonical status can never be granted | Trusted Source status can never be granted |
| Panel comment | Panel: Planes | Panel: Domains |
| Panel `aria-label` | Plane Cards | Domain Cards |
| Panel title | Planes | Domains |
| Panel subtitle | PCDS Plane Card storage | Domain Card storage |

### `app/ui/app.js`

| Location | Old | New |
|----------|-----|-----|
| Nav copy fallback | `'Suggested Changes'` | `'Proposed Changes'` (×2) |
| Dashboard stat card | `Contained` | `Held for Resolution` |
| Authority Path panel question | "What is the custodian state…" | "What is the authority state…" |
| Authority Path panel no-data message | "No Daenary epistemic metadata" | "No Confidence State metadata" |
| Authority Path panel grammar grid | `canceled` / `contained` labels | `Contradiction Blocked` / `Held for Resolution` |
| Authority Path panel section headers | `Canonical` / `Contained` / `Canceled` | `Trusted Source` / `Held for Resolution` / `Contradiction Blocked` |
| Authority Path panel empty messages | "No canonical records" etc. | Translated to match user labels |
| `certStateBadge()` display labels | `contained` / `canonical` / `blocked` | `Held for Resolution` / `Trusted Source` / `Contradiction Blocked` |
| Comment | Phase 12 — LLM Review Queue panel | Phase 12 — Proposed Changes panel |
| Comment | Load Certificate Review Queue | Load Certificate Resolution Center |
| LLM queue approval warning | "Canonical status is never applied" | "Trusted Source status is never applied" |
| **New function** | *(broken ref)* | `loadResolutionLedger()` — Decision History |

### `app/core/translation.py` *(new)*

The authoritative backend translation module:

- `TRANSLATION_TABLE` — the canonical mapping (11 entries)
- `VIZ_MODE_LABELS` — visualization mode → user label
- `STATUS_LABELS` — all internal status values → user labels
- `CONFIDENCE_STATE_LABELS` — Daenary m-state → Confidence State labels
- `ZONE_LABELS` — governance zones → user labels
- `NAV_LABELS` — panel IDs → navigation labels
- `user_label(internal)` — translate a single label
- `translate_status(status)` — status → user label
- `translate_mode(mode)` — viz mode → user label
- `translate_confidence_state(m_state)` — Daenary m → Confidence State label
- `translate_zone(zone)` — governance zone → user label
- `apply_translations(data, fields)` — add `*_label` keys to any result dict
- `legibility_passes_test(label)` — True if label needs no decoding
- `full_translation_map()` — complete machine-readable mapping

### `app/api/routes/authority_routes.py`

New translation routes (under `/api/authority/translation/`):

| Route | Purpose |
|-------|---------|
| `GET /translation/map` | Full translation table — all mappings |
| `POST /translation/label` | Translate a single internal label |
| `POST /translation/status` | Translate an internal status value |
| `POST /translation/mode` | Translate a visualization mode key |

Also fixed: removed dangling unreachable code block after `return sc3_mapping_summary()`.

---

## Conceptual Distinctions Preserved

These are different. They must remain different:

| Concept | Definition |
|---------|-----------|
| **Authority** | Who may decide? Legitimacy. Causal. Creates trust. |
| **Confidence** | How strong is the evidence? Epistemic quality. Not permission. |
| **Trust** | Is this safe to rely on? Derived from: legitimate authority + sufficient confidence. |

---

## Legibility Test

Every visible surface must pass:

> Would a smart non-builder pause to decode this label?

| Old Label | Passes Test? | New Label |
|-----------|-------------|-----------|
| Integrity Panel | ❌ No | Authority Center |
| Daenary State | ❌ No | Confidence State |
| Constitutional Mode | ❌ No | Authority Path |
| Constraint Geometry | ❌ No | Risk Map |
| Variable Overlay | ❌ No | Evidence State |
| Review Queue | ⚠️  Ambiguous | Resolution Center |
| Suggested Changes | ⚠️  Passive | Proposed Changes |
| Planes | ❌ Architect language | Domains |
| Contained | ❌ Symbolic | Held for Resolution |
| Cancelled | ❌ Ambiguous | Contradiction Blocked |

---

## What Was NOT Changed

- Internal Python variable names (e.g., `custodian_state`, `canonical_layer`, `daenary_summary`)
- Database column names
- API route paths (e.g., `/api/authority/`, `/api/planes/`, `/api/governance/`)
- CSS class names (e.g., `ep-lane-contained`, `cert-badge-contained`)
- JS function names (e.g., `loadIntegrityDashboard`, `setVisualizationMode`)
- Internal `onclick` mode values (e.g., `setVisualizationMode('constitutional')`)
- The words "Daenary", "Rubrix", "Atlas", "SC3" in internal engine code
- Any backend logic, scoring, or enforcement

This is translation discipline. Not ontology drift.

---

## Test Results

```
app imports OK
translation/map  ✓
translation/label ✓
translation/status ✓
translation/mode  ✓
Phase 26A tests: 24/24 PASS (no regressions)
```
