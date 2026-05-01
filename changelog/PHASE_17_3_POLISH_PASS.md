# Phase 17.3 — Polish Pass: Bug Fixes, Determinism, and Basic/Advanced UI Split

## Test results: 696 passed, 3 skipped (41 new tests added)

---

## Bug Fixes

### `visual_projection.py`

**Π false positive via substring collision** (`CANON_PATTERNS`)
- `"pi pressure"` was matching `"api pressure"` because the haystack wraps the full field string
  without word boundaries. The pattern is now `" pi pressure "` (space-padded) to match how `" H "`
  was already guarded. `test_pi_not_triggered_by_api_pressure` confirms the fix.

**Non-deterministic `hash()` calls in layout functions**
- `_layout_constraint` and `_layout_constitutional` used Python's built-in `hash()` on strings for
  jitter offsets. Python's `hash()` is randomized per-process since Python 3.3 (`PYTHONHASHSEED`),
  causing node positions to shift on every server restart — a violation of the determinism invariant.
- Both sites now use `_stable_hash(key, modulus)` backed by MD5, which is process-stable and fast.
  New helper `_stable_hash()` added at module level.

**`mapping_source` hardcoded on all nodes**
- Was always `"lexical_fallback"` even for nodes with `dominant_variable=None`.
  Now correctly `"none"` for unmapped nodes and `"lexical_fallback"` for matched nodes.

**`display_label` trailing separator**
- `f"... · {n.get('canonical_layer','')}"` produced a trailing `" · "` when `canonical_layer`
  was empty. Now only appended when the field is present.

**`_sidebar_web` canonical_count ambiguous `or` logic**
- `(n.get("canonical_layer") or n.get("status")) == "canonical"` short-circuits on any truthy
  `canonical_layer`, even `"supporting"`. Rewritten as explicit:
  `n.get("canonical_layer") == "canonical" or n.get("status") == "canonical"`.

**`const_types` inline local variable → `AUTHORITY_EDGE_TYPES` module constant**
- The set of authority-bearing edge types was defined inline in `get_projection_graph` but is a
  domain concept referenced across edge filtering, lineage tracking, and the sidebar. Promoted to
  `AUTHORITY_EDGE_TYPES = frozenset({...})` at module level. Exported for tests.

### `app.js`

**Dead code in `drawModeDecorations` lane labels**
- The broken `fillStyle = col.replace(...).padEnd` chain (which evaluated to `undefined` and was
  silently ignored by the Canvas API) has been removed. The actual rendering already used
  `ctx.globalAlpha = 0.50; ctx.fillStyle = col;` immediately after, which is all that remains.

### `style.css`

**Stale Phase 17 pre-redesign CSS removed**
- The Phase 17 modal overlay style block (~13 classes: `.viz-instrument`, `.viz-project-strip`,
  `.viz-card-grid`, `.viz-card`, `.viz-var-row` (old grid version), `.geometry-field`,
  `.viability-core`, `.boundary-ring`, `.failure-zone`, `.constitutional-list`, etc.) was dead code
  after the Phase 17.3 redesign replaced the modal with the canvas-embedded instrument sidebar.
- Duplicate `.viz-var-row` definition is now resolved — only the Phase 17.3 flex version remains.

---

## Basic / Advanced UI Split

The `simple` ↔ `advanced` toggle previously had almost no effect — only 11 `.advanced-only` tags
existed, all in governance detail rows. The split is now meaningful.

### What Basic (Simple) mode hides

**Navigation**
- Duplicates panel
- Bulk Import panel
(Both replaced with a simple "Add Documents" nav item that links to Import)

**Search panel**
- Daenary semantic filters accordion (epistemic coordinate filtering)
- Score formula reference accordion

**Visualization (Atlas) toolbar**
- Corpus class filter
- Canonical layer filter
- Status filter
- Lineage-only toggle
- Topic edges toggle
- Labels toggle
- Performance controls (mode select, Ripples, Glow)

**Governance (Review Center) panel**
- Ollama / Local Model section
- Workspace Policies section
- Audit Log section
- Execution Runs section
(The Review Queue itself stays visible — it's the core user action)

**System Status panel**
- Ollama / LLM section
- Mutation Safety Rules section

**Inbox panel**
- Snapshot ingest & reports details section

### What Basic mode keeps

Dashboard, Inbox (full note creation), Library, Search (simple), Conflicts (full),
Visualization (full canvas + mode tabs + project scope), Review Center (approval queue),
Status (server health + library stats + index controls).

### Visual indicators added
- The active mode label in the toggle button is highlighted
- A subtle "Simple view — showing essentials only. Switch to Advanced" hint bar
  appears across the top of the main panel area in simple mode.
- Dashboard "Quick Actions" shows "Add Documents" in simple mode vs "Index Library" in advanced.

---

## New Tests (41 added)

| Class | Tests | What's covered |
|-------|-------|----------------|
| `TestConstraintZone` | 9 | All zone boundaries, both trigger dimensions |
| `TestGetLane` | 13 | All lane states, priority ordering |
| `TestDiagnostics` | 6 | Each diagnostic code + absence cases |
| `TestSidebarVariableGap` | 2 | Gap path and no-gap path |
| `TestCanonVariablesFixes` | 4 | Π false positive fix + pattern correctness |
| `TestStableHash` | 4 | Determinism, modulus, edge cases |
| `TestAuthorityEdgeTypes` | 3 | Module export, membership |
