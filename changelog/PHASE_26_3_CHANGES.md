# PHASE_26_3_CHANGES.md
# Phase 26.3 — Clean Import + Reindex Diagnostics + Render Verification

**Status: Applied. 76/76 tests pass (21 new + 31 Phase 26.2 + 24 Phase 26A regression).**

---

## Root Cause: The 38 Failed Files

`autoindex.run_auto_index()` called `crawler.index_file(path, root)` where `path` was a
raw Python string from `scan_library()`. `index_file()` expects `pathlib.Path` objects and
immediately calls `path.relative_to(library_root)` — an attribute that doesn't exist on `str`.

**Result:** `AttributeError: 'str' object has no attribute 'relative_to'` on every file. 38
files = 38 failures. Every single reindex call silently failed to index anything.

**Fix in `autoindex.run_auto_index()`:**
```python
root_path = Path(root).resolve()
for path in paths:
    path_obj = Path(path)                    # ← was: path (raw string)
    result = crawler.index_file(path_obj, root_path)   # ← was: crawler.index_file(path, root)
```

---

## Changes by File

### `app/core/autoindex.py`

1. **Bug fix:** Convert string paths to `Path` objects before calling `index_file()`
2. **Expand extensions:** `SUPPORTED_EXTENSIONS` now includes `.html`, `.htm`, `.json`
   (was `.md`, `.txt`, `.markdown` only — HTML and JSON were silently never auto-indexed)
3. **Skip review artifacts:** `.review.md` and `.review.json` excluded from scan
4. **Failure classification:** Each exception now produces `reason` + `recommended_fix`:
   - `path_type_error` → "Report this bug"
   - `file_missing` → "Check if file was deleted or moved"
   - `encoding_error` → "Re-save as UTF-8"
   - `permission_denied` → "Check file permissions"
   - `frontmatter_parse_error` → "Check YAML for tabs, bad indentation, unclosed quotes"
   - `canon_protection` → "Use the governance workflow"
   - `db_error` → "Try resetting the workspace"
5. **Lint warnings in log:** Indexed files with lint warnings now include `lint_warnings[]`
6. **New functions:** `get_failure_log()`, `get_full_log()`

### `app/api/routes/autoindex_routes.py`

Three new endpoints:
- `GET /api/autoindex/failures` — per-file failure log with reason + recommended_fix
- `GET /api/autoindex/log` — full per-file log (all statuses)
- `GET /api/autoindex/report` — exportable diagnostic report (health, failures by reason, actions)

### `app/api/routes/workspace_routes.py` (new)

Full workspace management:
- `GET /api/workspace/state` — health summary (doc count, library status, last index stats, issues)
- `POST /api/workspace/reset` — clear state tables (open_items, escalations, locks, coherence, etc.); preserves indexed docs
- `POST /api/workspace/reset-full` — nuclear: clear all DB tables; library files untouched
- `POST /api/workspace/seed-fixtures` — import Phase 26.3 verification fixture pack into library
- `POST /api/workspace/seed-lineage` — seed lineage relationship between two doc IDs
- `POST /api/workspace/seed-provenance` — seed provenance/custody record for a doc

### `app/api/main.py`

Registered `workspace_router`.

### `app/ui/app.js`

**`triggerAutoIndex()`** upgraded:
- Shows failure count with amber warning (not silent green summary)
- On failures: fetches `/api/autoindex/failures` and renders per-file drill-down
- Each failed entry shows: path, reason, error message, recommended fix
- Buttons: "Export report" (downloads JSON), "Reset workspace" (prompts for RESET)

**New functions:**
- `loadWorkspaceHealth()` — fetches `/api/workspace/state`, renders health badge + issues
- `downloadIndexReport()` — fetches `/api/autoindex/report`, triggers JSON download
- `showResetWorkspaceModal()` — prompts for RESET confirm, calls `/api/workspace/reset`
- `seedVerificationFixtures()` — calls `/api/workspace/seed-fixtures`

**`loadStatus()`** — now calls `loadWorkspaceHealth()` on every status panel load.

### `app/ui/index.html`

**Status panel:**
- New "Workspace Health" section: health badge, issue list, recommended action
- Buttons: "Check health", "Seed fixtures", "Reset state"
- Library section renamed "Library & Reindex" with added "Export report" button

**Import panel:**
- New "Seed Verification Fixtures" button in "Start here" section
- New "Reset Workspace State" button in "Start here" section

---

## Fresh-Start Testing Flow

```
1. POST /api/workspace/reset          {"confirm": "RESET"}
   → Clears governance state, preserves indexed docs

2. POST /api/workspace/seed-fixtures  {"fixture_dir": "tests/fixtures/import_reliability"}
   → Imports all 9 test fixtures, seeds lineage pair automatically

3. POST /api/autoindex/run            {"changed_only": false}
   → Reindex full library, now 0 failures (bug fixed)

4. GET /api/workspace/state
   → Health = ok, N docs, N lineage links

5. POST /api/workspace/seed-lineage   {source_doc_id, child_doc_id, relationship}
   → Seeds any additional lineage for verification

6. POST /api/workspace/seed-provenance {doc_id, created_by, last_edited_by, change_summary}
   → Seeds custody record visible in Provenance Chain
```

All 6 steps have corresponding API tests in `test_phase26_3_verification.py`.

---

## Test Results

```
tests/test_phase26_3_verification.py  — 21/21 PASS
tests/test_phase26_2_verification.py  — 31/31 PASS
tests/test_phase26a_authority_proof.py — 24/24 PASS
Total: 76/76 PASS
```
