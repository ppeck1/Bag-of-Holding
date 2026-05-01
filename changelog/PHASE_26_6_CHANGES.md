# PHASE_26_6_CHANGES.md
# Phase 26.6 — End-to-End Verification Harness

**Status: Applied. 130/130 tests pass (14 new + 19 Phase 26.5 + 21 Phase 26.4 + 21 Phase 26.3 + 31 Phase 26.2 + 24 Phase 26A).**

---

## Problem Addressed

The system could report "healthy" while user-facing flows failed. There was no way to verify the full workflow in a single action, and no visible pass/fail surface for each step. Confidence State metrics on the home screen were global aggregates with no way to scope by project.

---

## Fixes Applied

### 1. Graph Edge Visibility (Critical)

**Root cause:** The canvas batch-draw lines used opacity values of `0.10–0.13`, making all edges effectively invisible against the dark background.

**Fix in `app/ui/app.js`:**
```js
// Before (invisible):
batchLines(bgBucket.lineage, 'rgba(96,165,250,0.13)', 0.8, false);
batchLines(bgBucket.other,   'rgba(120,135,160,0.10)', 0.7, false);

// After (visible):
batchLines(bgBucket.lineage, 'rgba(96,165,250,0.35)', 1.0, false);
batchLines(bgBucket.other,   'rgba(120,135,160,0.22)', 0.8, false);
```

All four edge categories updated: lineage (blue), conflict (red), topic (gray dashed), other (gray).

---

### 2. Clean Test Workspace (One-Click)

**New button:** `⊕ Clean Test Workspace` in Inbox "Start here" section.

**`async function runCleanTestWorkspace()`** in `app/ui/app.js`:
1. `POST /api/workspace/reset-full` — full DB clear
2. `POST /api/workspace/seed-fixtures` — seed all 9 verification fixtures
3. `POST /api/autoindex/run` (changed_only=false) — reindex everything
4. Navigates to Status panel
5. Runs `loadVerificationDashboard()` — shows pass/fail for all workflow steps

One button. One clean state. One verified result.

---

### 3. Verification Dashboard

**New section in Status panel:** "Verification Dashboard"  
**`async function loadVerificationDashboard()`** in `app/ui/app.js`

Runs 8 checks in parallel:

| Check | What It Tests |
|-------|--------------|
| DB connected | `doc_count > 0` in workspace state |
| Library files | `library_file_count > 0` on disk |
| Reindex failures | `last_failed == 0` in autoindex status |
| Review artifacts | `artifacts_total > 0` in analysis status |
| AI Analysis pipeline | `status == ok` in analysis health |
| Lineage relationships | `lineage_records > 0` in dashboard |
| Activity log | `total events > 0` in activity log |
| HTML import safety | Translation API responsive (pipeline invariant) |

Renders as ✅/❌ cards with notes. If any fail: shows "→ Fix: click ⊕ Clean Test Workspace".

---

### 4. Import Report Viewer

**New section in Status panel:** "Import Report"  
**`async function loadImportReport()`** in `app/ui/app.js`

Shows from `GET /api/autoindex/log`:
- Header: `✓ N indexed / ✗ N failed / N total / elapsed_ms`
- **Failed files** (if any): path, reason, raw error, 💡 recommended fix
- **Indexed files**: path, `AI✓` badge if analysis ran, `⚠N` badge if lint warnings

---

### 5. Project-Scoped Confidence State

**Problem:** Home Confidence State showed global d/m/q counts across all projects — meaningless for multi-project corpora.

**Fix in `app/api/routes/dashboard.py`:**

All epistemic queries now accept `?project=X` filter:
- `doc_counts` WHERE clause
- `epistemic_d_counts` WHERE clause
- `epistemic_m_counts` WHERE clause
- `epistemic_no_state` WHERE clause
- `epistemic_expired` WHERE clause
- `custodian_lanes` WHERE clause

Also added `projects` list to response (for dropdown population).

**Fix in `app/ui/app.js` `loadDashboard()`:**
- Reads `dash-project-filter` value
- Passes `?project=...` to `/api/dashboard`
- Populates `<select>` from returned `projects` list

**Fix in `app/ui/index.html`:**
- `<select id="dash-project-filter">` added to Confidence State section header
- `onchange="loadDashboard()"` triggers re-filter

---

### 6. UI Additions in `index.html`

**Inbox Start Here section** — new buttons:
- `⊕ Clean Test Workspace` (primary — one-click full reset+seed+verify)
- `📋 Verify` (navigates to Status panel + runs verification dashboard)

**Status panel** — two new sections:
- **Verification Dashboard**: 8-check pass/fail surface with actionable fix
- **Import Report**: per-file indexed/failed table with reasons

---

## Files Changed

| File | Change |
|------|--------|
| `app/ui/app.js` | Edge opacity raised; `runCleanTestWorkspace()`, `loadVerificationDashboard()`, `loadImportReport()` added; `loadDashboard()` project filter support |
| `app/ui/index.html` | Clean Test Workspace button, Verify button, project filter select, Verification Dashboard section, Import Report section |
| `app/api/routes/dashboard.py` | `?project=` filter added to all epistemic/custodian queries; `projects` list in response |
| `tests/test_phase26_6_verification_harness.py` | 14 verification tests |

---

## Test Results

```
tests/test_phase26_6_verification_harness.py   — 14/14 PASS
tests/test_phase26_5_document_analysis_pipeline.py — 19/19 PASS
tests/test_phase26_4_verification.py           — 21/21 PASS
tests/test_phase26_3_verification.py           — 21/21 PASS
tests/test_phase26_2_verification.py           — 31/31 PASS
tests/test_phase26a_authority_proof.py         — 24/24 PASS
Total: 130/130 PASS
```
