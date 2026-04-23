# Rewrite Execution Plan — Bag of Holding v2
**Derived from:** All five preceding analysis documents + boh_codex_pack
**Purpose:** Sequenced, phase-gated execution plan for the full v0P → v2 migration. Each phase has explicit entry criteria, deliverables, and exit criteria. No phase begins until the previous phase's exit criteria are verified.
**Status:** Execution authority document. Follow strictly.

---

## Phase Gate Summary

```
Phase 0: Analysis & Documentation          ← YOU ARE HERE (completing)
Phase 1: Mechanical Backend Restructure
Phase 2: API Standardization
Phase 3: UI Rewrite
Phase 4: Ingest / Lineage / Duplicate Systems
Phase 5: Launcher & Packaging Preparation
```

---

## Phase 0 — Analysis & Documentation

**Status:** In progress → completing now

### Deliverables (all required before Phase 1 begins)

- [x] `docs/current_route_inventory.md`
- [x] `docs/current_behavior_inventory.md`
- [x] `docs/source_to_target_migration_map.md`
- [x] `docs/math_authority.md`
- [x] `docs/corpus_migration_doctrine.md`
- [x] `docs/rewrite_execution_plan.md` (this document)

### Exit Criteria

- All six documents reviewed and approved by user
- No open questions about behavior preservation
- Migration map accepted as authoritative

---

## Phase 1 — Mechanical Backend Restructure

**Entry criteria:** Phase 0 exit criteria met
**Principle:** Move code. Do not rewrite logic. Every test must pass after this phase.

### Objective

Transform the flat module layout into the `app/core/`, `app/services/`, `app/api/`, `app/db/`, `app/ui/` structure defined in the migration map — without changing any function signatures, formulas, or behaviors.

### Steps (in order)

#### 1.1 Create Directory Structure
```
mkdir -p app/core app/services app/api/routes app/db app/ui/panels tests
```

#### 1.2 Move and Rename Database Layer
- Copy `db.py` → `app/db/connection.py`
- Copy `schema.sql` → `app/db/schema.sql`
- Add `schema_version` table to schema
- Add `acknowledged INTEGER DEFAULT 0` column to `conflicts` table (migration-safe `ALTER TABLE IF NOT EXISTS`)
- Update all `import db` references in moved modules to `from app.db import connection as db`

#### 1.3 Split `parser.py`
- Copy `parser.py` → `app/services/parser.py` (parsing functions: `parse_frontmatter`, `extract_definitions`, `extract_events`, `parse_iso_to_epoch`, `parse_semver`)
- Create `app/core/rubrix.py` with: `VALID_TYPES`, `VALID_STATUSES`, `OPERATOR_STATES`, `OPERATOR_INTENTS`, `ALLOWED_TRANSITIONS`, `validate_header()`
- Both files reference each other's constants only through explicit imports — no circular dependency

#### 1.4 Move Core Modules
Each module is copied to its target path. Logic is not changed. Only `import` statements are updated.

| Source | Target |
|--------|--------|
| `canon.py` | `app/core/canon.py` |
| `conflicts.py` | `app/core/conflicts.py` |
| `search.py` | `app/core/search.py` |
| `planar.py` | `app/core/planar.py` |
| `snapshot.py` | `app/core/snapshot.py` |

#### 1.5 Move Service Modules
| Source | Target |
|--------|--------|
| `crawler.py` | `app/services/indexer.py` |
| `events.py` | `app/services/events.py` |
| `llm_review.py` | `app/services/reviewer.py` |

#### 1.6 Create `app/api/main.py`
- Extract app factory from `main.py` (FastAPI init, middleware, router registration)
- Routes remain registered at their current paths for now (prefix added in Phase 2)
- Inline UI route (`GET /`) temporarily returns a "Migration in progress" placeholder

#### 1.7 Create Stub Route Files
Create one file per route group in `app/api/routes/`. Each file imports from the appropriate core/service module and registers the existing route. No new logic.

```
app/api/routes/index.py       — POST /index
app/api/routes/search.py      — GET /search
app/api/routes/canon.py       — GET /canon
app/api/routes/conflicts.py   — GET /conflicts
app/api/routes/library.py     — GET /docs/{id}
app/api/routes/workflow.py    — GET /workflow
app/api/routes/nodes.py       — GET/POST /nodes/{path}
app/api/routes/events.py      — GET /events, GET /events/export.ics
app/api/routes/review.py      — GET /review/{path}
app/api/routes/ingest.py      — (stub only — no logic yet)
```

#### 1.8 Migrate Tests
- Copy codex `tests/` → `tests/`
- Convert `self_test.py` to `tests/test_integration.py` (pytest format)
- All 38 original checks become individual `def test_*()` functions
- Update all import paths to reflect new structure

#### 1.9 Create `app/__init__.py`, `app/core/__init__.py`, etc.
Add empty `__init__.py` to all package directories.

#### 1.10 Verify `requirements.txt`
Confirm all existing dependencies are still listed. Add none yet.

### Exit Criteria — Phase 1

- [ ] `pytest tests/` runs all 38 original checks without failure
- [ ] `uvicorn app.api.main:app` starts without errors
- [ ] All original routes respond identically (smoke test with `tests/smoke_api.sh`)
- [ ] No behavior delta — all formulas, constants, and validations identical to v0P
- [ ] No v0P module files remain at root level (moved or symlinked)
- [ ] `git diff` (or equivalent) shows only file moves + import updates, no logic changes

---

## Phase 2 — API Standardization

**Entry criteria:** Phase 1 exit criteria met
**Principle:** Establish the clean `/api/` prefix, add the 5 missing routes, update smoke tests.

### Objective

Create the final v2 API surface. All routes get the `/api/` prefix. Five capability gaps identified in the route inventory are closed.

### Steps

#### 2.1 Add `/api/` Prefix to All Routes

Update each router file to register under `/api/`:
```python
router = APIRouter(prefix="/api")
```

Existing routes at root paths (`/search`, `/canon`, etc.) are **removed** — not kept as aliases. Clients must update to `/api/search`, etc.

The one exception: `GET /` continues to serve the UI shell (updated in Phase 3).

#### 2.2 Add Missing Routes

**2.2.1 `POST /api/ingest/snapshot`** (`app/api/routes/ingest.py`)
```
Body: { path: str }  — path to boh_export_*.json file
Calls: snapshot_engine.ingest_snapshot_export(path)
Returns: { run_id, inserted_docs, inserted_defs, inserted_events, skipped, conflicts_created }
```

**2.2.2 `GET /api/docs`** (`app/api/routes/library.py`)
```
Query params: status (optional), type (optional), operator_state (optional),
              page (int, default 1), per_page (int, default 50, max 200)
Returns: { count, page, per_page, docs: [...] }
```

**2.2.3 `GET /api/planes`** (`app/api/routes/nodes.py`)
```
Returns: { planes: [distinct plane_path values from plane_facts, ordered] }
```

**2.2.4 `PATCH /api/workflow/{doc_id}`** (`app/api/routes/workflow.py`)
```
Body: { operator_state: str, operator_intent: str }
Validation: new state must be in ALLOWED_TRANSITIONS[current_state]
            hard constraints (R6, R7, R8) re-checked after transition
Returns: { doc_id, previous_state, new_state, success: bool, errors: [...] }
```

**2.2.5 `PATCH /api/conflicts/{conflict_rowid}/acknowledge`** (`app/api/routes/conflicts.py`)
```
No body required
Sets conflicts.acknowledged = 1 for the given rowid
Does NOT delete the conflict record
Returns: { acknowledged: true, conflict_type, doc_ids, term }
```

**2.2.6 `GET /api/dashboard`** (`app/api/routes/dashboard.py`)
```
Returns: {
  total_docs: int,
  canonical_docs: int,
  draft_docs: int,
  archived_docs: int,
  open_conflicts: int,
  acknowledged_conflicts: int,
  total_events: int,
  indexed_planes: int,
  last_indexed_ts: int | null
}
```

#### 2.3 Create `app/api/models.py`
Consolidate all Pydantic request/response models. Remove inline `BaseModel` definitions from `main.py`.

#### 2.4 Update Smoke Tests
Update `tests/smoke_api.sh` to use `/api/` prefixed paths. Add smoke tests for the 6 new routes.

#### 2.5 Update OpenAPI metadata
```python
app = FastAPI(
    title="Bag of Holding v2",
    description="Deterministic Local Knowledge Workbench — Planar Math + Rubrix Governance",
    version="2.0.0",
)
```

### Exit Criteria — Phase 2

- [ ] All 38 original tests still pass
- [ ] All 6 new routes return valid responses (smoke tested)
- [ ] `GET /api/dashboard` returns correct counts matching DB state
- [ ] `PATCH /api/workflow/{id}` enforces `ALLOWED_TRANSITIONS` and hard constraints
- [ ] `PATCH /api/conflicts/{id}/acknowledge` sets flag without deleting record
- [ ] Old non-prefixed routes return 404 (not silently forwarding)
- [ ] OpenAPI spec at `/docs` reflects all routes with correct schemas

---

## Phase 3 — UI Rewrite

**Entry criteria:** Phase 2 exit criteria met
**Principle:** Replace the monolithic inline HTML string with a navigable 5-panel SPA. Backend is not touched.

### Objective

The new UI must feel like a desktop workbench, not an API console. Non-programmer users should be able to orient themselves, browse their library, triage conflicts, and import documents without knowing that FastAPI exists.

### Target Information Architecture

```
┌─────────────────────────────────────────────────────┐
│  📦 Bag of Holding                    [Panel Nav]   │
├────────┬────────────────────────────────────────────┤
│  Nav   │                                            │
│        │  Panel Content Area                        │
│  📊 Dashboard                                       │
│  📚 Library                                         │
│  🔍 Search                                          │
│  ⚖️  Canon & Conflicts                              │
│  📥 Import / Ingest                                 │
│        │                                            │
└────────┴────────────────────────────────────────────┘
```

### Panel Specifications

#### Panel 1: Dashboard (`/`)
- **Purpose:** At-a-glance health of the knowledge base
- **Data source:** `GET /api/dashboard`
- **Content:**
  - Counts: Total docs, Canonical, Draft, Archived, Open Conflicts, Events
  - Prominent conflict badge (red) if open conflicts > 0
  - "Last indexed" timestamp
  - Quick-action buttons: "Re-index Library", "Go to Conflicts", "Import Document"
  - Recent activity: last 5 indexed documents

#### Panel 2: Library (`/library`)
- **Purpose:** Browse, filter, and inspect all documents
- **Data source:** `GET /api/docs`, `GET /api/docs/{id}`
- **Content:**
  - Filterable table: by status, type, operator_state
  - Per-row: path, title (truncated), status badge, operator_state badge, conflict indicator
  - Click → document detail view showing full metadata, definitions, events, lint errors
  - Workflow transition control: dropdown to advance operator_state (calls `PATCH /api/workflow/{id}`)
  - LLM Review button: calls `GET /api/review/{path}`, shows result in-panel

#### Panel 3: Search (`/search`)
- **Purpose:** Full-text search with score transparency
- **Data source:** `GET /api/search`
- **Content:**
  - Search input + plane filter
  - Results as cards with: title, path, status, final_score (prominent)
  - Expandable score breakdown per result (text / canon / planar / penalty)
  - Conflict indicator on conflicted results
  - Click → opens document in Library panel

#### Panel 4: Canon & Conflicts (`/canon-conflicts`)
- **Purpose:** Canon resolution queries and conflict management
- **Data source:** `GET /api/canon`, `GET /api/conflicts`, `PATCH /api/conflicts/{id}/acknowledge`
- **Content:**
  - Canon resolution: topic + plane inputs → winner card + ranked candidates
  - Ambiguity conflicts shown inline with resolution
  - Conflicts list: type badge, term, plane, affected docs, detected date
  - Per-conflict: [Acknowledge] button (marks seen, does not resolve)
  - Clear label: "No auto-resolution. All conflicts require explicit user action."
  - Score formula always visible below winner card

#### Panel 5: Import / Ingest (`/import-ingest`)
- **Purpose:** Bring documents into the system
- **Data source:** `POST /api/index`, `POST /api/ingest/snapshot`, `GET /api/events/export.ics`
- **Content:**
  - Library path input + [Index Library] button → live result display
  - Snapshot file path input + [Ingest Snapshot] button
  - Per-file lint error accordion (expandable)
  - Conflict count from last index run
  - ICS export link
  - Ingest history: last 5 index runs with timestamps and counts

### UI Technical Specifications

- **Framework:** Vanilla JS + HTML + CSS (no build step required — serves directly from FastAPI static files)
- **Serving:** `app.mount("/", StaticFiles(directory="app/ui"), name="ui")` in FastAPI
- **State management:** `window.location.hash` for panel routing (`#dashboard`, `#library`, etc.)
- **API calls:** `fetch()` against `/api/*` endpoints
- **Dark mode:** GitHub dark palette retained (matching v0P aesthetic)
- **No external CDN dependencies** — all assets local (local-first principle extends to UI)
- **Accessibility:** ARIA labels on all navigation items; keyboard-navigable panel switching

### Exit Criteria — Phase 3

- [ ] All 5 panels render without errors
- [ ] Dashboard shows correct counts (verified against DB)
- [ ] Library panel can filter and display all documents
- [ ] Search returns results with visible score breakdown
- [ ] Canon & Conflicts panel shows winner + candidates + conflict list
- [ ] [Acknowledge] button works without resolving conflict
- [ ] Import / Ingest panel can trigger index and shows lint errors
- [ ] All 38 original tests + Phase 2 route tests still pass (UI is additive only)
- [ ] No backend logic changed during UI phase

---

## Phase 4 — Ingest / Lineage / Duplicate Systems

**Entry criteria:** Phase 3 exit criteria met
**Principle:** Harden the ingest path with explicit duplicate detection, lineage tracking, and corpus class labeling.

### Steps

#### 4.1 Add Corpus Class Column
```sql
ALTER TABLE docs ADD COLUMN corpus_class TEXT DEFAULT 'CORPUS_CLASS:DRAFT';
```
Migration: classify existing docs using the criteria in `corpus_migration_doctrine.md §1`.

#### 4.2 Corpus Class Assignment During Indexing
`app/services/indexer.py` assigns `corpus_class` based on `status`, `type`, `operator_state`, `source_type` after parsing. Assignment is deterministic (same as doctrine §1 criteria).

#### 4.3 Duplicate Detection in Indexer
Before `INSERT OR REPLACE`, check for:
1. `text_hash` match → log as `duplicate_content` conflict
2. `doc_id` collision with existing Canon doc → do NOT replace; create `canon_collision` conflict; add to `skipped`

#### 4.4 Lineage Table
```sql
CREATE TABLE IF NOT EXISTS lineage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL,
    related_doc_id TEXT NOT NULL,
    relationship TEXT NOT NULL,  -- 'duplicate_content', 'snapshot_source', 'supersedes', 'derived_from'
    detected_ts INTEGER NOT NULL
);
```

#### 4.5 Snapshot Ingest Canon Guard
In `app/core/snapshot.py`: before inserting a snapshot doc, check if `doc_id` already exists with `status=canonical`. If so: skip insert, create conflict record, return in `skipped` with reason `"would_overwrite_canon"`.

#### 4.6 Corpus Migration Report
Generate `docs/migration_report.md` at end of first full v2 index run:
- Count of each corpus class
- List of all conflicts detected
- List of duplicates found
- List of any Canon protection events

### Exit Criteria — Phase 4

- [ ] `corpus_class` column populated for all docs after indexing
- [ ] Content duplicates create `duplicate_content` conflict records (not deleted)
- [ ] Snapshot ingest cannot silently overwrite a Canon doc
- [ ] `lineage` table populated with relationships found during ingest
- [ ] `docs/migration_report.md` generated after first full v2 index
- [ ] All prior tests still pass

---

## Phase 5 — Launcher & Packaging Preparation

**Entry criteria:** Phase 4 exit criteria met
**Principle:** Wrap the application for desktop-like usage. The user should be able to double-click to start.

### Steps

#### 5.1 `launcher.py`
```python
# launcher.py — starts uvicorn and opens browser automatically
import subprocess, webbrowser, time, sys

PORT = 8000
proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.api.main:app",
                         "--host", "127.0.0.1", "--port", str(PORT)])
time.sleep(1.5)
webbrowser.open(f"http://127.0.0.1:{PORT}")
proc.wait()
```

#### 5.2 `launcher.bat` / `launcher.sh`
Shell wrappers for Windows and macOS/Linux respectively. Double-click to start.

#### 5.3 `boh.spec` (PyInstaller)
PyInstaller spec file for creating a single-directory executable. Bundles:
- Python runtime
- All `app/` modules
- `app/ui/` static files
- `app/db/schema.sql`
- `requirements.txt` dependencies (frozen)

#### 5.4 Startup Health Check
`GET /api/health` route added:
```json
{ "status": "ok", "version": "2.0.0", "db": "connected", "library": "<path>" }
```

#### 5.5 Documentation Update
Update `README.md` with:
- v2 architecture overview
- How to run: `python launcher.py`
- How to run for development: `uvicorn app.api.main:app --reload`
- Panel navigation guide

### Exit Criteria — Phase 5

- [ ] `python launcher.py` starts server and opens browser without manual steps
- [ ] `launcher.bat` / `launcher.sh` work on their respective platforms
- [ ] `GET /api/health` returns `{"status": "ok"}`
- [ ] PyInstaller spec produces working executable (local test)
- [ ] README updated
- [ ] All tests still pass in packaged context

---

## Cross-Phase Invariants

These rules apply across all phases and must never be violated:

| Invariant | Verified By |
|-----------|-------------|
| No test that was passing may regress between phases | `pytest tests/` before each phase exit |
| No formula in `math_authority.md` may change without a versioned change log entry | Code review at each phase |
| `non_authoritative: true` on all LLM artifacts | `test_reviewer.py` |
| No auto-resolution of conflicts | `test_conflict_detection.py` |
| Canon docs cannot be silently overwritten | Phase 4 guard + `test_snapshot.py` |
| `topics_tokens` always re-derived, never trusted from source | `test_integration.py` |
| `defs.plane_scope_json` always valid JSON array | `test_integration.py` |
| D2 event hardening: no start/timezone → no event | `test_integration.py` |

---

## Approval Gate

**Before Phase 1 begins, the following must be confirmed by the user:**

1. All 6 analysis documents reviewed and accepted
2. Migration map accepted as the authoritative restructure target
3. Math authority document accepted as the locked formula reference
4. Corpus migration doctrine accepted as the data governance framework
5. Execution plan accepted — phase order locked

**Upon approval: Phase 1 begins immediately with directory creation.**
