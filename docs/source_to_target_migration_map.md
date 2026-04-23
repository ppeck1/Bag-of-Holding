# Source-to-Target Migration Map — Bag of Holding v0P → v2
**Generated from:** Bag-of-Holding-main source + boh_codex_pack handoff (April 2026)
**Codex template:** `docs/source_to_target_migration_map_template.md`
**Purpose:** Every source module, route, table, and behavior mapped to its v2 destination. Explicit action for each. No silent moves.

---

## Target Architecture (v2)

```
boh_v2/
├── app/
│   ├── core/               # Pure logic — no FastAPI, no I/O side effects
│   │   ├── canon.py        # Canon scoring + resolution
│   │   ├── conflicts.py    # All three conflict detection passes
│   │   ├── planar.py       # Planar fact validation + alignment scoring
│   │   ├── search.py       # Search scoring composition
│   │   ├── rubrix.py       # Ontology constants + lifecycle validation
│   │   └── snapshot.py     # Snapshot ingest logic
│   ├── services/           # Orchestration — calls core, calls db, no HTTP
│   │   ├── indexer.py      # crawl_library + index_file (was crawler.py)
│   │   ├── reviewer.py     # LLM review artifact generation (was llm_review.py)
│   │   ├── events.py       # Event list + ICS export
│   │   └── parser.py       # Frontmatter parsing + extraction utilities
│   ├── api/                # FastAPI routers — thin HTTP shell only
│   │   ├── main.py         # App factory, middleware, router registration
│   │   ├── routes/
│   │   │   ├── index.py    # POST /api/index
│   │   │   ├── search.py   # GET  /api/search
│   │   │   ├── canon.py    # GET  /api/canon
│   │   │   ├── conflicts.py# GET  /api/conflicts, PATCH /api/conflicts/{id}
│   │   │   ├── library.py  # GET  /api/docs, GET /api/docs/{id}
│   │   │   ├── workflow.py # GET  /api/workflow, PATCH /api/workflow/{id}
│   │   │   ├── nodes.py    # GET/POST /api/nodes/{path}
│   │   │   ├── events.py   # GET /api/events, GET /api/events/export.ics
│   │   │   ├── review.py   # GET /api/review/{path}
│   │   │   └── ingest.py   # POST /api/ingest/snapshot
│   │   └── models.py       # Pydantic request/response models
│   ├── db/
│   │   ├── connection.py   # Was db.py — same WAL/FK config
│   │   └── schema.sql      # Unchanged schema + v2 migrations
│   └── ui/                 # SPA frontend
│       ├── index.html      # Shell + router
│       ├── app.js          # Main SPA entry
│       └── panels/
│           ├── dashboard.js
│           ├── library.js
│           ├── search.js
│           ├── canon_conflicts.js
│           └── import_ingest.js
├── docs/                   # This directory — migration and spec docs
├── tests/                  # Migrated from codex tests/
├── schema.sql              # Symlink to app/db/schema.sql
├── requirements.txt        # Updated deps
└── launcher.py             # Desktop launcher (phase 5)
```

---

## Module Migration Table

| Source File | Source Role | Target Path | Action | Behavior Preserved | Tests |
|-------------|-------------|-------------|--------|-------------------|-------|
| `main.py` | FastAPI app + all routes + inline UI | `app/api/main.py` + `app/api/routes/*.py` + `app/ui/` | **SPLIT** — routes → individual router files; UI → SPA; app factory stays | CORS, middleware, env vars | `test_api_routes.py` |
| `db.py` | DB connection + CRUD helpers | `app/db/connection.py` | **MOVE** — no logic changes | WAL, FK, Row factory, all helpers | `test_db.py` |
| `schema.sql` | SQLite schema | `app/db/schema.sql` | **MOVE** — schema unchanged; add `schema_version` table for future migrations | All tables + indexes | Verified at startup |
| `parser.py` | Frontmatter parsing + Rubrix validation | `app/services/parser.py` (parsing) + `app/core/rubrix.py` (ontology + validation) | **SPLIT** — pure parsing stays in services; constants + `validate_header()` move to core | All lint behaviors R1–R10, transition table | `test_rubrix_lifecycle.py` |
| `crawler.py` | Filesystem crawl + indexer | `app/services/indexer.py` | **MOVE + RENAME** — all logic identical | I1–I13, A1.1–A1.3, D1, D2 | `test_indexer.py` |
| `canon.py` | Canon scoring + resolution | `app/core/canon.py` | **MOVE** — identical logic | CS1–CS5, CR1–CR8, locked score formula | `test_canon_selection.py` |
| `conflicts.py` | Conflict detection (3 passes) | `app/core/conflicts.py` | **MOVE** — identical logic | DC1–DC2, CC1–CC5, PC1–PC4, CF1–CF3 | `test_conflict_detection.py` |
| `search.py` | FTS + composite scoring | `app/core/search.py` | **MOVE** — identical logic | SS1–SS7, locked score formula | `test_search.py` |
| `planar.py` | Planar fact validation + scoring | `app/core/planar.py` | **MOVE** — identical logic | PF1–PF9, PA1–PA6 | `test_planar.py` |
| `events.py` | Event list + ICS export | `app/services/events.py` | **MOVE** — ICS SUMMARY field adapted (use title) | IC1–IC5 (IC5 adapted) | `test_events.py` |
| `llm_review.py` | Review artifact generation | `app/services/reviewer.py` | **MOVE + RENAME** | LR1–LR10 | `test_reviewer.py` |
| `snapshot.py` | Snapshot ingest | `app/core/snapshot.py` | **MOVE** + close gap: add `POST /api/ingest/snapshot` route | SI1–SI8 | `test_snapshot.py` |
| `self_test.py` | Integration test runner | `tests/test_integration.py` | **MIGRATE** — convert to pytest; all 38 checks preserved as test functions | All patch validations | CI |

---

## Route Migration Table

| v0P Route | v0P Handler | v2 Route | v2 Handler | Change | Behavior Delta |
|-----------|-------------|----------|------------|--------|---------------|
| `GET /` | Inline HTML UI | `GET /` → serves `app/ui/index.html` | Static file serve | **REPLACE** UI only; logic unchanged | None — backend same |
| `POST /index` | `index_library()` | `POST /api/index` | `routes/index.py` | **MOVE + PREFIX** `/api/` | None |
| `GET /search` | `search()` | `GET /api/search` | `routes/search.py` | **MOVE + PREFIX** | None |
| `GET /canon` | `resolve_canon()` | `GET /api/canon` | `routes/canon.py` | **MOVE + PREFIX** | None |
| `GET /conflicts` | `list_conflicts()` | `GET /api/conflicts` | `routes/conflicts.py` | **MOVE + PREFIX** | None |
| *(missing)* | — | `PATCH /api/conflicts/{id}/acknowledge` | `routes/conflicts.py` | **NEW** — marks conflict seen, does not resolve | Closes v0P gap; no auto-resolution |
| `GET /nodes/{path}` | `get_node()` | `GET /api/nodes/{path}` | `routes/nodes.py` | **MOVE + PREFIX** | None |
| `POST /nodes/{path}` | `store_node_fact()` | `POST /api/nodes/{path}` | `routes/nodes.py` | **MOVE + PREFIX** | None |
| `GET /workflow` | `workflow()` | `GET /api/workflow` | `routes/workflow.py` | **MOVE + PREFIX** | None |
| *(missing)* | — | `PATCH /api/workflow/{doc_id}` | `routes/workflow.py` | **NEW** — explicit operator_state transition | Closes v0P gap; enforces ALLOWED_TRANSITIONS |
| `GET /events/export.ics` | `export_ics()` | `GET /api/events/export.ics` | `routes/events.py` | **MOVE + PREFIX** | SUMMARY uses title (IC5 adapt) |
| `GET /events` | `list_events()` | `GET /api/events` | `routes/events.py` | **MOVE + PREFIX** | None |
| `GET /review/{path}` | `generate_review()` | `GET /api/review/{path}` | `routes/review.py` | **MOVE + PREFIX** | None |
| `GET /docs/{id}` | `get_doc()` | `GET /api/docs/{id}` | `routes/library.py` | **MOVE + PREFIX** | None |
| *(missing)* | — | `GET /api/docs` | `routes/library.py` | **NEW** — paginated doc list | Closes v0P gap |
| *(missing)* | — | `POST /api/ingest/snapshot` | `routes/ingest.py` | **NEW** — HTTP endpoint for snapshot_engine | Closes v0P gap |
| *(missing)* | — | `GET /api/planes` | `routes/nodes.py` | **NEW** — list distinct plane_paths | Closes v0P gap |

---

## Database Migration Table

| Table | v0P State | v2 State | Migration Action |
|-------|-----------|----------|-----------------|
| `docs` | As defined in schema.sql | **UNCHANGED** | None required |
| `docs_fts` | FTS5 virtual table | **UNCHANGED** | None required |
| `defs` | As defined | **UNCHANGED** | None required |
| `plane_facts` | As defined | **UNCHANGED** | None required |
| `events` | As defined | **UNCHANGED** | None required |
| `conflicts` | No `acknowledged` field | **ADD** `acknowledged INTEGER DEFAULT 0` | Migration: `ALTER TABLE conflicts ADD COLUMN acknowledged INTEGER DEFAULT 0` |
| *(new)* | — | `schema_version (version TEXT, applied_ts INTEGER)` | Migration table for future safety |

**Schema constraint:** All existing data survives migration. No column dropped. No row deleted.

---

## Behavior Migration Table

### Behaviors That Change (Adaptations Only)

| Behavior ID | v0P Behavior | v2 Behavior | Justification |
|-------------|-------------|-------------|---------------|
| IC5 | ICS SUMMARY = `doc_id` | ICS SUMMARY = `title` or `path` if no title | More useful calendar entry; no logic change |
| UI1–UI7 | Monolithic inline HTML | 5-panel SPA (Dashboard, Library, Search, Canon & Conflicts, Import/Ingest) | Core migration goal; backend logic unchanged |
| DB4 | New connection per call | Context-manager connection with WAL retained | Performance; WAL and FK preserved |
| SI8 | No HTTP route for snapshot ingest | `POST /api/ingest/snapshot` added | Closes critical gap |

### Behaviors That Are New (v2 Additions)

| New Behavior | Rationale | Preserves Core Principles? |
|-------------|-----------|---------------------------|
| `PATCH /api/conflicts/{id}/acknowledge` — marks conflict as "seen" without resolving | Users need a way to note they've reviewed a conflict without resolving it | Yes — no auto-resolution; conflict record remains |
| `PATCH /api/workflow/{doc_id}` — explicit state transition | Completes the Rubrix lifecycle as an API operation | Yes — ALLOWED_TRANSITIONS enforced; hard constraints validated |
| `GET /api/docs` — paginated document list | Library panel needs a browsable list | Yes — read-only |
| `GET /api/planes` — distinct plane paths | Planar panel navigation | Yes — read-only |
| Dashboard stats endpoint (`GET /api/dashboard`) | Overview counts for new UI | Yes — read-only |

---

## UI Information Architecture Map

| v0P UI Section | v2 Panel | Route | Primary Data Sources |
|----------------|----------|-------|---------------------|
| Index Library (POST) | Import / Ingest | `/import-ingest` | `POST /api/index`, `POST /api/ingest/snapshot` |
| Search | Search | `/search` | `GET /api/search` |
| Canon Resolution | Canon & Conflicts | `/canon-conflicts` | `GET /api/canon` |
| Conflicts | Canon & Conflicts | `/canon-conflicts` | `GET /api/conflicts` |
| Workflow | Library (filtered) | `/library?filter=workflow` | `GET /api/workflow` |
| *(none)* | Dashboard | `/` | `GET /api/dashboard` |
| *(none)* | Library (doc browser) | `/library` | `GET /api/docs` |

---

## Dependency Migration

| v0P Dependency | Version | v2 Disposition | Note |
|---------------|---------|----------------|------|
| `fastapi` | 0.115.5 | **RETAIN** | Core framework |
| `uvicorn` | 0.32.1 | **RETAIN** | ASGI server; wrapped in launcher.py |
| `PyYAML` | 6.0.2 | **RETAIN** | Frontmatter parsing |
| `pydantic` | 2.10.3 | **RETAIN** | Request/response models |
| `pydantic_core` | 2.27.1 | **RETAIN** | Pydantic dependency |
| `annotated-types` | 0.7.0 | **RETAIN** | Pydantic dependency |
| `python-dotenv` | 1.2.1 | **RETAIN** | Env config |
| `anyio` | 4.12.1 | **RETAIN** | FastAPI dependency |
| `h11` | 0.16.0 | **RETAIN** | HTTP/1.1 |
| `httptools` | 0.7.1 | **RETAIN** | uvicorn dep |
| `starlette` | 0.41.3 | **RETAIN** | FastAPI foundation |
| `websockets` | 16.0 | **RETAIN** | uvicorn dep |
| `watchfiles` | 1.1.1 | **RETAIN** (dev only) | Hot reload |
| `typing_extensions` | 4.15.0 | **RETAIN** | Type hints |
| `click` | 8.3.1 | **RETAIN** | CLI |
| `colorama` | 0.4.6 | **RETAIN** | Windows color |
| `idna` | 3.11 | **RETAIN** | URL handling |
| *(new)* | — | `pyinstaller` | Launcher packaging (phase 5 only) |

---

## Test Migration Table

| Codex Test File | Maps To | v2 Test File | Status |
|----------------|---------|--------------|--------|
| `tests/test_canon_selection.py` | `canon.py` → `app/core/canon.py` | `tests/test_canon_selection.py` | **MIGRATE** |
| `tests/test_conflict_detection.py` | `conflicts.py` → `app/core/conflicts.py` | `tests/test_conflict_detection.py` | **MIGRATE** |
| `tests/test_rubrix_lifecycle.py` | `parser.py` → `app/core/rubrix.py` | `tests/test_rubrix_lifecycle.py` | **MIGRATE** |
| `tests/smoke_api.sh` | All routes | `tests/smoke_api.sh` (updated paths to `/api/`) | **UPDATE PATHS** |
| `self_test.py` (38 checks) | All modules | `tests/test_integration.py` | **CONVERT TO PYTEST** |
| *(new)* | New routes | `tests/test_new_routes.py` | **CREATE** |

---

## Execution Order

1. **Phase 0 (now):** All 6 analysis docs written → reviewed → approved
2. **Phase 1:** Mechanical restructure — create `app/` directory tree; move modules; verify all 38 tests still pass
3. **Phase 2:** API standardization — add `/api/` prefix; add 5 missing routes; update smoke tests
4. **Phase 3:** UI rewrite — 5-panel SPA replacing inline HTML
5. **Phase 4:** Ingest/lineage/duplicate systems — snapshot HTTP endpoint; duplicate linking; lineage metadata
6. **Phase 5:** Launcher and packaging preparation — `launcher.py`, pyinstaller config

**At no point between phases should any test that was previously passing be allowed to fail.**
