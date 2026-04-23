# CURRENT_STATE_FILE_TREE.md
# Bag of Holding v2 — Current State After Phase 8
# Tests: 261 passed, 2 skipped, 0 failed

## File Tree

```
boh_v2/
├── README.md                              ← Full Phase 8 documentation
├── RUN_INSTRUCTIONS.md                    ← Run guide with correct test counts (261 passed)
├── CURRENT_STATE_FILE_TREE.md             ← This file
├── app/
│   ├── api/
│   │   ├── main.py                        ← App factory: all routers + StaticFiles + /api/health (phase:8)
│   │   ├── models.py                      ← Pydantic models
│   │   └── routes/
│   │       ├── canon.py                   ← GET /api/canon
│   │       ├── conflicts.py               ← GET /api/conflicts  PATCH /api/conflicts/{id}/acknowledge
│   │       ├── dashboard.py               ← GET /api/dashboard
│   │       ├── events.py                  ← GET /api/events  GET /api/events/export.ics
│   │       ├── index.py                   ← POST /api/index  (triggers DCNS sync on completion)
│   │       ├── ingest.py                  ← POST /api/ingest/snapshot
│   │       ├── library.py                 ← GET /api/docs  GET /api/docs/{id}
│   │       ├── lineage.py                 ← GET/POST /api/lineage  GET /api/lineage/{doc_id}
│   │       │                                  GET /api/duplicates  GET/POST /api/corpus/*
│   │       ├── nodes.py                   ← GET /api/planes  GET/POST /api/nodes/{path}
│   │       ├── reader.py                  ← GET /api/docs/{id}/content           [Phase 7]
│   │       │                                  GET /api/docs/{id}/related          [Phase 7]
│   │       │                                  GET /api/graph                      [Phase 7+8]
│   │       │                                  GET /api/docs/{id}/coordinates      [Phase 8]
│   │       │                                  POST /api/dcns/sync                 [Phase 8]
│   │       ├── review.py                  ← GET /api/review/{path}
│   │       ├── search.py                  ← GET /api/search (+ Phase 8 Daenary filter params)
│   │       └── workflow.py                ← GET /api/workflow  PATCH /api/workflow/{id}
│   ├── core/
│   │   ├── canon.py                       ← Canon scoring + resolution [BOH_CANON_v3.7]
│   │   ├── conflicts.py                   ← 3-pass conflict detection [BOH_PATCH_v2.19]
│   │   ├── corpus.py                      ← 5-class deterministic corpus classifier
│   │   ├── daenary.py                     ← Daenary semantic state: validate/normalize/persist/query [Phase 8]
│   │   ├── dcns.py                        ← Selective DCNS edge graph: build/sync/load diagnostics [Phase 8]
│   │   ├── lineage.py                     ← Lineage links + duplicate/supersession detection
│   │   ├── planar.py                      ← Planar fact storage + alignment scoring
│   │   ├── related.py                     ← Related doc scoring + graph data builder [Phase 7+8]
│   │   ├── rubrix.py                      ← Rubrix ontology + validate_header [RUBRIX_LIFECYCLE_v1]
│   │   ├── search.py                      ← FTS + composite scoring + Daenary filter layer [Phase 8]
│   │   └── snapshot.py                    ← Snapshot ingest + canon guard + corpus class
│   ├── db/
│   │   ├── connection.py                  ← DB init + WAL + migration-safe ALTER TABLE [schema v2.2.0]
│   │   └── schema.sql                     ← 8 tables + doc_coordinates + doc_edges [Phase 8]
│   ├── services/
│   │   ├── events.py                      ← Event list + ICS export
│   │   ├── indexer.py                     ← Filesystem crawler + Daenary coordinate persistence [Phase 8]
│   │   ├── migration_report.py            ← Corpus migration report generator
│   │   ├── parser.py                      ← parse_frontmatter() + parse_frontmatter_full() [Phase 8]
│   │   └── reviewer.py                    ← LLM review artifact generation (non-authoritative)
│   └── ui/
│       ├── app.js                         ← SPA: 6 panels + ForceGraph + shared reader helpers
│       │                                      + drawer viewer + Daenary search + DCNS halos [Phase 8]
│       ├── index.html                     ← SPA shell: Atlas panel + Daenary search controls
│       │                                      + DCNS legend + Phase 8 title [Phase 8]
│       ├── style.css                      ← Full design system + drawer viewer + coord badges
│       │                                      + Daenary summary styles [Phase 8]
│       └── vendor/
│           ├── katex.min.js               ← Local KaTeX (math rendering)
│           ├── katex.min.css
│           ├── marked.min.js              ← Local marked.js (markdown rendering)
│           └── fonts/                     ← KaTeX font files
├── docs/
│   ├── corpus_migration_doctrine.md
│   ├── current_behavior_inventory.md
│   ├── current_route_inventory.md
│   ├── math_authority.md
│   ├── rewrite_execution_plan.md
│   └── source_to_target_migration_map.md
├── library/
│   ├── planar-math.md
│   ├── planar-math.review.json
│   └── rubrix-lifecycle.md
├── tests/
│   ├── test_integration.py                ← 42 tests — core v0P behaviors
│   ├── test_new_routes.py                 ← 30 passed, 2 skipped — Phase 2 routes
│   ├── test_phase4.py                     ← 28 tests — corpus class, lineage, duplicates
│   ├── test_phase5.py                     ← 23 tests — launcher, health, all GET routes
│   ├── test_phase6.py                     ← 26 tests — ICS, corpus UI, migration report
│   ├── test_phase7.py                     ← 38 passed, 1 skipped — Atlas, reader, graph
│   ├── test_phase8.py                     ← 70 tests — Daenary, DCNS, search, drawer
│   ├── test_canon_selection.py            ← 1 test (stub)
│   ├── test_conflict_detection.py         ← 1 test (stub)
│   └── test_rubrix_lifecycle.py           ← 1 test (stub)
├── boh.spec
├── launcher.py                            ← Phase 8 preflight check (daenary.py + dcns.py verified)
├── launcher.bat
└── launcher.sh
```

---

## Phase 8 Changes

### New: `app/core/daenary.py`
Daenary semantic state layer. Completely additive — does not touch Rubrix.
- `validate_dimension()` — lint codes: `LINT_INVALID_DAENARY_STATE/QUALITY/CONFIDENCE/MODE/TIMESTAMP`
- `extract_coordinates()` — normalize and filter a `daenary:` block into storable dicts
- `upsert_coordinates()` — DELETE + INSERT for a doc_id (called by indexer)
- `get_coordinates()` — query `doc_coordinates` for a doc
- `format_coordinate_summary()` — human-readable string for search result cards
- `is_stale()` — check if `valid_until_ts` is in the past

### New: `app/core/dcns.py`
Selective DCNS relationship edge graph. Not a vessel simulation.
- `sync_edges()` — derive `doc_edges` from lineage + conflicts + optional `canon_relates_to` pairs; compute load scores; idempotent via INSERT OR REPLACE
- `get_node_diagnostics()` — per-node: `load_score`, `conflict_count`, `expired_coordinate_count`, `uncertain_coordinate_count`
- `get_all_doc_edges()` — return edge rows filtered to a set of node IDs

### `app/services/parser.py`
- `parse_frontmatter_full()` added — returns `(boh, raw_header, body, lint_errors)`
- `parse_frontmatter()` unchanged — all existing callers unaffected

### `app/services/indexer.py`
- Uses `parse_frontmatter_full()` to capture optional `daenary:` block
- Calls `upsert_coordinates()` inside the DB transaction after doc insert
- Calls `dcns.sync_edges()` at end of `crawl_library()`
- Reports `daenary_coordinates` and `dcns_edges_synced` in crawl summary

### `app/db/schema.sql`
- `doc_coordinates` table + 4 indexes
- `doc_edges` table + 3 indexes

### `app/db/connection.py`
- Phase 8 explicit table creation in `init_db()` (migration-safe for existing DBs)
- Schema version stamped `v2.2.0`

### `app/core/search.py`
- New optional params: `dimension`, `state`, `min_quality`, `min_confidence`, `stale`, `uncertain_only`, `conflicts_only`
- Daenary pre-filter: queries `doc_coordinates` and reduces candidate set
- `_daenary_adjustment()` — additive-only, clamped `[−0.05, +0.05]`
- `daenary_summary` attached to result rows when coordinates exist
- `daenary_adjustment` added to `score_breakdown`

### `app/api/routes/search.py`
- Exposes all 7 new Daenary filter params via FastAPI Query params
- Response includes `daenary_filters` dict showing active filters

### `app/core/related.py` — `get_graph_data()`
- Nodes enriched with DCNS diagnostics (`loadScore`, `conflictCount`, `expiredCoordinates`, `uncertainCoordinates`)
- Edges sourced from `doc_edges` first, then lineage fallback, then inferred topic-similarity

### `app/api/routes/reader.py`
- `GET /api/docs/{id}/coordinates` — new endpoint
- `POST /api/dcns/sync` — new endpoint
- `get_doc_content()` updated to use `parse_frontmatter_full()`
- `/api/graph` doc updated to reflect Phase 8 node/edge payloads

### `app/ui/app.js`
- Version constant: `BOH_VERSION = 'v2-phase8'`
- Console fingerprint updated
- **Shared reader helpers** (new): `loadDocPayload()`, `renderDocBodyInto()`, `renderRelatedInto()`, `renderCoordBadges()`
- **Drawer viewer** (new): `openDrawer()` now fetches content + related docs and injects them into the drawer; `setDrawerMode()` toggles rendered/raw
- **Daenary search** (new): `doSearch()` collects all 7 filter inputs; `daenary_summary` rendered as `◈ dim=state(q/c)` line on result cards; `daenary_adjustment` shown in breakdown
- **DCNS node halos** (new): ForceGraph `draw()` adds red ring for conflicts, amber dashed for stale, blue dot for uncertain

### `app/ui/index.html`
- Page title: `Bag of Holding v2 — Phase 8`
- Topbar wordmark: `Phase 8` label
- Daenary filter accordion added to Search panel (`sf-dimension`, `sf-state`, `sf-min-quality`, `sf-min-conf`, `sf-uncertain`, `sf-stale`, `sf-conflicts`)
- Score formula reference updated to include `daenary_adjustment`
- Atlas legend updated: conflict, stale, uncertain halo indicators
- All static asset URLs bumped to `?v=8`

### `app/ui/style.css`
- Drawer width: `min(680px, 92vw)` (widened from narrow metadata drawer)
- `#drawer-reader-toggle`, `#drawer-reader-content`, `#drawer-reader-related` styles
- `.coord-badge` variants: `.state-pos` (green), `.state-zero` (amber), `.state-neg` (red), `.stale` (dimmed + strikethrough)
- `.daenary-summary` monospace compact display
- `#search-daenary-panel` collapsible filter area

### `launcher.py`
- Preflight check updated: `daenary.py` and `dcns.py` added to required file list
- Phase references updated to Phase 8

### `tests/test_phase8.py` — 70 new tests
- `TestParseFrontmatterFull` (6) — full parser
- `TestValidateDimension` (8) — all lint codes
- `TestExtractCoordinates` (6) — normalization + malformed skipping
- `TestFormatCoordinateSummary` (3) — summary string format
- `TestIsStale` (3) — temporal validity
- `TestIndexerDaenary` (6) — integration: indexing + coordinate persistence + re-index
- `TestSearchDaenaryFilters` (9) — all filter params + response structure
- `TestGraphDCNS` (5) — graph node diagnostics + table existence
- `TestCoordinatesEndpoint` (2) — 200 / 404
- `TestDCNSSync` (2) — sync endpoint
- `TestPhase8UIFiles` (12) — HTML / JS / CSS smoke tests
- `TestPhase8Regression` (7) — all prior routes unbroken

---

## Complete Route Table (Phase 8)

| Method | Path | Phase |
|--------|------|-------|
| GET | / | 3 |
| GET | /style.css | 3 |
| GET | /app.js | 3 |
| GET | /vendor/* | 7 |
| GET | /api/health | 5 |
| GET | /api/dashboard | 2+4 |
| POST | /api/index | 1 |
| GET | /api/search | 1+**8** |
| GET | /api/canon | 1 |
| GET | /api/conflicts | 1 |
| PATCH | /api/conflicts/{id}/acknowledge | 2 |
| GET | /api/docs | 2 |
| GET | /api/docs/{id} | 1 |
| GET | /api/docs/{id}/content | 7 |
| GET | /api/docs/{id}/related | 7 |
| GET | /api/docs/{id}/coordinates | **8** |
| GET | /api/graph | 7+**8** |
| POST | /api/dcns/sync | **8** |
| GET | /api/workflow | 1 |
| PATCH | /api/workflow/{id} | 2 |
| GET | /api/nodes/{path} | 1 |
| POST | /api/nodes/{path} | 1 |
| GET | /api/planes | 2 |
| GET | /api/events | 1 |
| GET | /api/events/export.ics | 1 |
| GET | /api/review/{path} | 1 |
| POST | /api/ingest/snapshot | 2 |
| GET | /api/lineage | 4 |
| GET | /api/lineage/{doc_id} | 4 |
| POST | /api/lineage | 4 |
| GET | /api/duplicates | 4 |
| GET | /api/corpus/classes | 4 |
| POST | /api/corpus/reclassify | 4 |
| GET | /api/corpus/migration-report | 4 |
| POST | /api/corpus/migration-report | 4 |

---

## Test Count (Phase 8)

| File | Tests | Result |
|------|-------|--------|
| test_integration.py | 42 | 42 passed |
| test_new_routes.py | 32 | 30 passed, 2 skipped |
| test_phase4.py | 28 | 28 passed |
| test_phase5.py | 23 | 23 passed |
| test_phase6.py | 26 | 26 passed |
| test_phase7.py | 39 | 38 passed, 1 skipped |
| test_phase8.py | 70 | 70 passed |
| test_canon_selection.py | 1 | 1 passed |
| test_conflict_detection.py | 1 | 1 passed |
| test_rubrix_lifecycle.py | 1 | 1 passed |
| **Total** | **263** | **261 passed, 2 skipped, 0 failed** |
