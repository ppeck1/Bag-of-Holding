# PHASE_26_2_CHANGES.md
# Phase 26.2 — Label Consistency + Document Detail Legibility + Import Reliability

**Status: Applied. 55/55 tests pass (31 new + 24 Phase 26A regression).**

---

## Root Cause: Why Nav Labels Persisted After Phase 26.1

`copy_map.js` is the true source of truth for nav labels. It sets `window.COPY` at load time and app.js reads from it with fallbacks. Phase 26.1 changed the fallback strings in `app.js` but not `copy_map.js`, so the copy map always won.

**Fix:** Updated `copy_map.js` directly — this is the only place nav labels need to be changed.

---

## Changes by Area

### Label Consistency

**`copy_map.js`** (root cause fix):
- `governance: "Resolution Center"` (was "Review Center")
- `llmQueue: "Proposed Changes"` (was "Suggested Changes")
- `approvalQueue: "Resolution Center"`, `approval: "Resolution Decision"`, `pending: "Needs Resolution"`, `canonicalArtifact: "Trusted Source Version"`, `reviewPatch: "Proposed Change"`, `provenance: "Custody History"`

**`app/ui/app.js`**:
- `statusBadge()`: canonical → "Trusted Source", contained → "Held for Resolution"
- Governance fallback `"Review Center"` → `"Resolution Center"` (×2)

**`app/ui/index.html`**:
- "Confidence State" promoted to primary section heading on dashboard
- `ε epistemic` demoted to `advanced-only` subtitle

### Document Detail (Drawer) Rewrite

Replaced the entire drawer HTML block with a modernized layout:

**New: Custody & Ownership block** — first thing users see:
- Project: from `doc.project` DB field, with inline edit button
- Responsible Authority: from `doc.resolution_authority || doc.authority_state`
- Version: from `doc.version`
- Last Changed: `doc.updated_ts` formatted timestamp
- Source, Topics
- Path/doc_id moved to `advanced-only`

**Confidence State section** (was "ε Epistemic State"):
- Primary label: "Confidence State"
- `advanced-only` subtitle: "ε epistemic"
- Custodian lane label translated via `_custodianLabels` map

**Lineage accordion** — now includes inline definition:
> *"Lineage = document-to-document relationships: derives from, supersedes, duplicates, conflicts with, references."*

**Provenance accordion** — now includes inline definition:
> *"Provenance = custody history: who created this, who edited it, when it changed, what authority approved it, what certificates exist."*

**Lifecycle section** — dual-label:
- Simple mode: "Lifecycle"
- Advanced mode: "Rubrix Lifecycle"

**AI Analysis** (was "LLM Review Artifact"):
- New label: "AI Analysis"
- `advanced-only` subtitle: "(LLM Proposal · non-authoritative)"
- Health status indicator shown inline
- Non-authoritative warning updated: "Cannot grant Trusted Source status"

**Promotion section**: "Request Trusted Source Promotion" (was "Request Canonical Promotion Certificate")

### LLM Analysis / AI Analysis Fix

**Root cause:** `encodeURIComponent(docPath)` encoded `/` as `%2F`, which FastAPI's `/{path:path}` parameter cannot match. The route expects actual `/` separators in the URL.

**Fix in `loadReview()`:**
```js
// Before (broken):
const encoded = encodeURIComponent(docPath);  // foo%2Fbar%2Ffile.md
const url = `/api/review/${encoded}`;

// After (fixed):
const safePath = (docPath || '').replace(/^\/+/, '');  // foo/bar/file.md
const url = `/api/review/${safePath}`;
```

**Also:** The AI Analysis feature is deterministic — it does NOT require Ollama. It extracts topics, definitions, variables, and conflict candidates from the file system. The "LLM" label was misleading.

### Project Inline Edit

**New API endpoint:** `PATCH /api/docs/{doc_id}/metadata`
- Accepts: `project`, `title`, `summary`, `authority_state`
- Non-destructive: only updates provided fields
- Returns: updated doc record

**New JS functions:** `editDocProject()`, `saveDocProject()`, `cancelDocProjectEdit()`

### Import Reliability

**HTML preprocessing improvements (`app/services/indexer.py`):**
- Before stripping all tags, now removes entire content of: `<script>`, `<style>`, `<nav>`, `<header>`, `<footer>` blocks
- Extracts headings (`<h1>`–`<h4>`) as Markdown `##` headers before body strip
- This enables topic extraction from headings and prevents JS/CSS text polluting search

**JSON failure handling (`app/services/indexer.py`):**
- Before: `except: data = {"raw": text[:500]}` — silent corruption
- After: `data = {"_parse_error": str(exc), "_raw_preview": text[:200]}` — explicit error in output
- `validity_note` line added to indexed body so error is visible in document viewer

### Visualization Improvements

**Evidence State panel** (`_renderVariablePanel`):
- Badge: "EVIDENCE STATE" (was "VARIABLE OVERLAY")
- Purpose line: *"See which nodes have confirmed direction, need resolution, or have been negated. Use this to identify knowledge gaps — not to assess overall risk."*
- Grammar grid relabeled for clarity (q/c described in plain English)
- Priority nodes table: "Contradiction Blocked / Held for Resolution / negated first"

**Risk Map panel** (`_renderConstraintPanel`):
- Badge: "RISK MAP" (was "VIABILITY SURFACE")
- Purpose line: *"Identify nodes that need intervention vs. nodes that are operationally safe. This is a decision surface — use it to prioritize correction work."*
- 🎯 Target callout with color-coded quadrant guide (upper-right = viable, lower-left = intervention required)
- High-cost table labeled: "Highest-cost nodes — prioritize these corrections"

**Authority Path lane labels**:
- Font: 8px → 11px sans-serif
- Position: y=12 → y=24 (clears the top edge)
- Added dark text halo (stroke before fill) for contrast

**Graph node labels** (all modes):
- Added text halo (dark stroke before fill) for contrast against busy graph backgrounds
- Font: 10px monospace → 10px sans-serif (more readable)
- Show-label threshold: ≤25 nodes → ≤40 nodes (more labels visible)
- Zoom threshold lowered: scale≥1.5 → scale≥1.2

### CSS

**`app/ui/style.css`**:
- `.viz-panel-purpose`: purpose differentiation line below panel question

---

## Test Corpus Created

`tests/fixtures/import_reliability/` (9 files):

| File | Tests |
|------|-------|
| `known_good_markdown.md` | Full frontmatter parsing, title/topics indexing |
| `known_good_json.json` | JSON title extraction, clean indexing |
| `known_good_html.html` | Title from `<title>`, body preservation, headings, script/style stripping |
| `broken_json.json` | Graceful failure — no crash, error recorded |
| `html_with_noise.html` | Tracking/analytics/nav stripped; article preserved |
| `lineage_source.md` | Parent in lineage relationship |
| `lineage_child.md` | Child in lineage relationship; relationship seedable |
| `provenance_seed.md` | Custody metadata in frontmatter, versioned |
| `llm_known_good.md` | AI Analysis deterministic extraction |

---

## Test Results

```
tests/test_phase26_2_verification.py  — 31/31 PASS
tests/test_phase26a_authority_proof.py — 24/24 PASS
Total: 55/55 PASS
```
