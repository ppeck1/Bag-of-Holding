# Bag of Holding v2 — Phase 15.6A
## Make The Patch Actually Visible

## Source Patch
Applied the user-provided Phase 15.6A verification patch against the Phase 15.6 product-legibility build.

## Purpose
Phase 15.6 added the product-legibility layer. Phase 15.6A verifies and hardens that the layer is actually mounted in the active UI, not merely present in the filesystem.

## Changes Applied

### 1. copy_map.js is actively loaded
- Verified `app/ui/index.html` loads `copy_map.js` from the active static UI root.
- Updated cache version from stale Phase 15.5/15.6 naming to:
  - `/copy_map.js?v=156A-visible`
  - `/app.js?v=156A-make-patch-visible`
  - `/style.css?v=156A-visible`

### 2. Simple / Advanced toggle is visibly rendered
- Replaced the single-state button text with a persistent visible toggle label:
  - `Simple | Advanced`
- Updated `applyUiMode()` so it no longer overwrites the button text.
- The active mode is now indicated with CSS classes:
  - `.is-simple`
  - `.is-advanced`

### 3. copy_map.js now executes, not merely exists
- Added `applyCopyMap()` to `app/ui/app.js`.
- It runs on `DOMContentLoaded` before normal UI initialization.
- It applies copy-map labels to active nav items and key panel titles.
- It adds visible runtime state classes:
  - `copy-map-loaded`
  - `copy-map-missing`
- It logs whether the copy map was actually applied.

### 4. Active app.js verified
- Verified there is only one active frontend application file:
  - `app/ui/app.js`
- The active `index.html` now references that file with the Phase 15.6A cache version.

### 5. Browser cache risk reduced
- Replaced the stale cache key with `v=156A-make-patch-visible`.
- This should force browsers to fetch the new UI files after a hard refresh.

### 6. Demo seed surface verified
- Confirmed active UI includes the visible `Load Demo Project` button.
- Confirmed active frontend calls:
  - `POST /api/input/demo-seed`
- Confirmed backend route exists:
  - `@router.post("/demo-seed")`

### 7. Human explanation rendering verified
- Confirmed `explainApprovalImpact(item)` is not dead code.
- Confirmed it is called inside the review-card rendering path:
  - `<div class="plain-impact"><strong>What this means:</strong> ...</div>`

## Verification Results

- `node --check app/ui/app.js` passed.
- `node --check app/ui/copy_map.js` passed.
- Active HTML contains `/copy_map.js?v=156A-visible`.
- Active HTML contains `Simple | Advanced`.
- Active HTML contains `/app.js?v=156A-make-patch-visible`.
- Only one `app.js` exists under the project tree: `app/ui/app.js`.
- Full pytest run was attempted but did not complete within the available execution window in this environment. No syntax errors were found in the modified JavaScript.

## Files Changed

- `app/ui/index.html`
- `app/ui/app.js`
- `app/ui/style.css`
- `PHASE_15_6A_MAKE_PATCH_VISIBLE_CHANGES.md`

## Guardrails Preserved

- No backend schema rename.
- No API route rename.
- No governance weakening.
- No auto-merge behavior added.
- No canonical promotion shortcut added.
- No CANON diagnostics removed.
