# PHASE_26_4_CHANGES.md
# Phase 26.4 — Fresh Start + Import Safety + Trace Log

**Status: Applied. 97/97 tests pass (21 new + 21 Phase 26.3 + 31 Phase 26.2 + 24 Phase 26A).**

---

## Critical: HTML Injection Fixed

**Problem:** Imported HTML files (e.g. CANON registry) could contain `<style>` blocks with
`:root { --bg-void: hotpink }` that would be injected directly into the BOH DOM via
`innerHTML`, contaminating the app's font and color system.

**Two-layer fix:**

**Layer 1 — Python (server-side, `app/services/indexer.py`):**
Already existed from Phase 26.2: strips `<script>`, `<style>`, `<nav>`, `<header>`, `<footer>`
blocks with their content before indexing. `:root` CSS values never reach the search index.

**Layer 2 — JS (client-side, `app/ui/app.js`):**
New `sanitizeHtml()` function applied inside `renderMarkdown()` after `marked.parse()`:
- Removes any remaining `<script>...</script>` blocks
- Removes any remaining `<style>...</style>` blocks
- Removes `<link>` and `<meta>` tags
- Strips `on*` event attributes (`onclick`, `onload`, `onerror`, etc.)
- Strips `javascript:` href values
- Removes `:root { }` and `@import` patterns from any inline styles

Result: a CANON registry file with hostile CSS, fonts, and scripts can be imported and
rendered in the document reader without any visual contamination of the BOH UI.

---

## API Error Display: [object Object] Fixed

**Problem:** FastAPI validation errors (422) return `detail` as an array of objects.
When `r.detail` is `[{loc:..., msg:..., type:...}]`, JavaScript string interpolation
produces `[object Object]`.

**Fix:** New `formatApiError(r)` function:
```js
function formatApiError(r) {
  if (Array.isArray(r.detail))
    return r.detail.map(e => e.msg || e.message || JSON.stringify(e)).join('; ');
  if (typeof r.detail === 'string') return r.detail;
  if (r.error) return String(r.error);
  return JSON.stringify(r);
}
```
Applied in `doReset()`, `seedVerificationFixtures()`, and all error displays.

---

## Three-Level Reset Modal

**Problem:** `window.prompt()` was sending a POST without `Content-Type: application/json`,
causing FastAPI to return 422 Unprocessable Entity.

**Fix:** Replaced `window.prompt()` with an inline CSS modal (`boh-reset-modal` div) that:
- Shows three clearly-labelled levels with warnings
- Sends proper `headers: {'Content-Type': 'application/json'}` on every POST
- Uses `formatApiError()` for error display
- Auto-dismisses and triggers reindex on success

**Three levels:**
1. **Level 1 — Reset State:** Clears governance tables (escalations, locks, open items, coherence, SC3 violations). Indexed docs preserved. → `POST /api/workspace/reset`
2. **Level 2 — Reset DB:** Clears all indexed docs and governance state. Library files untouched. → `POST /api/workspace/reset-full`
3. **Level 3 — Reset DB + Seed Fixtures:** Full DB clear then immediately seeds verification fixtures and reruns reindex. Clean slate for testing. → reset-full then seed-fixtures then autoindex.

---

## Activity Log

**New API:** `GET /api/workspace/activity-log?limit=100`
- Unified timeline pulling from `audit_log` table
- Friendly labels: "📄 File imported", "🔍 Library indexed", "⟳ Workspace reset", etc.
- Decoded `detail` JSON for structured preview

**New UI:** "Workspace Activity Log" section in System Status panel
- Auto-loads on Status panel open
- Shows timestamp, event label, actor, doc ID, detail preview
- Scrollable (max-height: 320px)

---

## AI Analysis Health Check

**New API:** `GET /api/workspace/analysis-health?doc_id={id}`
- Tests with the most recently indexed doc (or a specific doc_id)
- Returns: `status`, `endpoint_ok`, `doc_found`, `file_found`, `text_length`,
  `topics_extracted`, `defs_extracted`, `non_authoritative`
- Status values: `ok`, `file_missing`, `no_docs`, `error`
- Explains that AI Analysis is **deterministic** (no Ollama required)

**New UI:** "AI Analysis Health" section in System Status panel
- "▶ Run health check" button
- Shows text length, topics, defs, non-authoritative flag
- Error cases show actionable fix instructions

---

## Simple/Advanced Pill Toggle

Replaced the "Simple | Advanced" text button with a pill switch:
- Both labels visible; active mode highlighted with background + color
- Simple: white pill on bg-card
- Advanced: blue pill on rgba(96,165,250,.18)
- Much clearer visual state than colored text

---

## Hostile HTML Fixture

**New fixture:** `tests/fixtures/import_reliability/hostile_html.html`

The "CANON registry" stress test — contains:
- `<link>` to Google Fonts (Comic Sans)
- `<style>` with `:root { --bg-void: hotpink !important }`
- `<script>` setting `window.BOH_COMPROMISED = true`
- `<script>` injecting GTM analytics
- `<script>` attempting `fetch()` to evil.example.com
- `onclick` event on nav element
- `.sidebar` overlay (position:fixed, z-index:99999)

All dangerous content is stripped. Article text is preserved.
Tested by 6 tests in Phase 26.4 suite.

**New fixture:** `tests/fixtures/import_reliability/bad_encoding_binary.md`
Binary file with raw 0xFF/0xFE bytes mid-document. Indexed gracefully with `errors=replace`.

---

## Files Changed

| File | Change |
|------|--------|
| `app/ui/app.js` | `sanitizeHtml()`, `formatApiError()`, 3-level reset modal, `doReset()`, `checkAnalysisHealth()`, `loadActivityLog()`, fixed `seedVerificationFixtures()` |
| `app/ui/index.html` | Pill switch HTML, AI Analysis Health section, Activity Log section |
| `app/ui/style.css` | Pill switch CSS (`.mode-pill`, `.mode-simple-label`, `.mode-advanced-label`) |
| `app/api/routes/workspace_routes.py` | `GET /api/workspace/activity-log`, `GET /api/workspace/analysis-health` |
| `tests/fixtures/import_reliability/hostile_html.html` | Hostile CSS/script/font injection stress test |
| `tests/fixtures/import_reliability/bad_encoding_binary.md` | Binary bad-encoding fixture |
| `tests/fixtures/import_reliability/bad_encoding_warning.md` | UTF-8 warning fixture |
| `tests/test_phase26_4_verification.py` | 21 verification tests |

---

## Test Results

```
tests/test_phase26_4_verification.py  — 21/21 PASS
tests/test_phase26_3_verification.py  — 21/21 PASS
tests/test_phase26_2_verification.py  — 31/31 PASS
tests/test_phase26a_authority_proof.py — 24/24 PASS
Total: 97/97 PASS
```
