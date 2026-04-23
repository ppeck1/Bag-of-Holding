# Current Route Inventory — Bag of Holding v0P
**Generated from:** Bag-of-Holding-main source (April 2026)
**Purpose:** Authoritative catalog of every HTTP endpoint in the v0P FastAPI surface before migration.
**Status:** READ-ONLY reference. Do not modify during migration.

---

## Route Table

| # | Method | Path | Module | Handler | Summary |
|---|--------|------|--------|---------|---------|
| 1 | `GET`  | `/` | `main.py` | `ui()` | Minimal monolithic HTML UI (inline string) |
| 2 | `POST` | `/index` | `main.py → crawler.py` | `index_library()` | Crawl filesystem, index all `.md` files, trigger conflict detection |
| 3 | `GET`  | `/search` | `main.py → search.py` | `search()` | FTS5 + composite scored search |
| 4 | `GET`  | `/canon` | `main.py → canon.py` | `resolve_canon()` | Resolve canonical document by topic and/or plane_scope |
| 5 | `GET`  | `/conflicts` | `main.py → conflicts.py` | `list_conflicts()` | List all detected conflicts (no auto-resolution) |
| 6 | `GET`  | `/nodes/{node_path}` | `main.py → db.py` | `get_node()` | Retrieve planar facts for a given plane_path |
| 7 | `POST` | `/nodes/{node_path}` | `main.py → planar.py` | `store_node_fact()` | Validate and store a new planar fact |
| 8 | `GET`  | `/workflow` | `main.py → db.py` | `workflow()` | List documents with Rubrix operator_state / status |
| 9 | `GET`  | `/events/export.ics` | `main.py → events.py` | `export_ics()` | Export events as ICS calendar data (PlainTextResponse) |
| 10 | `GET` | `/events` | `main.py → events.py` | `list_events()` | List all events, optionally filtered by doc_id |
| 11 | `GET` | `/review/{doc_path}` | `main.py → llm_review.py` | `generate_review()` | Generate non-authoritative LLM review artifact, writes `.review.json` to disk |
| 12 | `GET` | `/docs/{doc_id}` | `main.py → db.py` | `get_doc()` | Retrieve single document + its defs and events |
| 13 | `GET` | `/docs` (Swagger) | FastAPI auto | — | Auto-generated OpenAPI Swagger UI |
| 14 | `GET` | `/redoc` | FastAPI auto | — | ReDoc alternative API documentation |

---

## Route Detail

### 1. `GET /`
- **Response type:** `HTMLResponse`
- **Returns:** Entire single-page monolithic UI as an inline Python string (~130 lines of HTML + JS)
- **UI sections exposed:** Index Library, Search, Canon Resolution, Conflicts, Workflow
- **Weakness flagged:** Backend-first API surface feel; no navigation, no state, no orientation cues
- **Migration target:** Replace with proper 5-panel SPA routed to Dashboard / Library / Search / Canon & Conflicts / Import-Ingest

---

### 2. `POST /index`
- **Request body:** `IndexRequest { library_root?: str }` (optional; falls back to `BOH_LIBRARY` env var or `./library`)
- **Calls:** `crawler.crawl_library(root)` → then `conflict_engine.detect_all_conflicts()`
- **Returns:**
  ```json
  {
    "total_files": int,
    "indexed": int,
    "files_with_lint_errors": int,
    "results": [...per-file results...],
    "conflicts_detected": int,
    "new_conflicts": [...]
  }
  ```
- **Side effects:** Writes to `docs`, `docs_fts`, `defs`, `events` tables. Runs all three conflict detectors.
- **Critical behavior:** Skips `.review.md` files. Runs `_validate_event()` before inserting events (D2 hardening).

---

### 3. `GET /search`
- **Query params:** `q` (required), `plane` (optional), `limit` (1–100, default 20)
- **Returns:** Scored result list + `score_formula` explanation string
- **Scoring formula:** `0.6 * text_score + 0.2 * canon_score_normalized + 0.2 * planar_alignment + conflict_penalty`
- **All score components returned** in `score_breakdown` per result

---

### 4. `GET /canon`
- **Query params:** `topic` (optional), `plane` (optional)
- **Returns:** `{ winner, candidates[:10], ambiguity_conflicts, score_formula }`
- **Behavior:** Uses `topics_tokens LIKE %normalized_topic%` (not FTS). Filters by plane_scope intersection if `plane` provided. Detects and records ambiguity conflict if top two scores within 5% threshold.
- **No auto-resolution.** Winner is advisory.

---

### 5. `GET /conflicts`
- **Returns:** `{ count, conflicts: [...], note: "No auto-resolution..." }`
- **Note field** is a hard constraint reminder embedded in every response

---

### 6. `GET /nodes/{node_path}`
- **Path param:** `node_path` — dot-notation plane path (e.g. `core.planar.coherence`)
- **Query param:** `include_expired` (bool, default false)
- **Returns:** Parsed node path components + `active_facts` count + full fact rows

---

### 7. `POST /nodes/{node_path}`
- **Body:** `PlanarFactRequest { plane_path, r, d, q, c, context_ref, m, valid_until, subject_id }`
- **Validation:** `d ∈ {-1, 0, 1}`, `q ∈ [0,1]`, `c ∈ [0,1]`, `m ∈ {"cancel","contain"}` when `d=0`
- **Side effect:** Triggers `conflict_engine.detect_all_conflicts()` after every store
- **Returns 422** on validation failure

---

### 8. `GET /workflow`
- **Query params:** `operator_state`, `status`, `doc_type` (all optional, all string filters)
- **Returns:** Filtered doc list + full `rubrix_schema` (valid states, intents, transitions, hard constraints)
- **Hard constraints exposed in response:**
  - `status=canonical ⇒ operator_state=release`
  - `type=canon ⇒ operator_state≠observe`
  - `status=archived ⇒ operator_state=release`

---

### 9. `GET /events/export.ics`
- **Query param:** `doc_id` (optional filter)
- **Response type:** `PlainTextResponse`
- **Returns:** RFC 5545 ICS calendar data
- **Only includes events with valid `start_ts`**

---

### 10. `GET /events`
- **Query param:** `doc_id` (optional)
- **Returns:** `{ count, events: [...] }` ordered by `start_ts`

---

### 11. `GET /review/{doc_path}`
- **Path param:** `doc_path` — relative path within library
- **Query param:** `library_root` (optional override)
- **Side effect:** Writes `<doc_path>.review.json` artifact to disk alongside source
- **Returns:** Full review artifact dict including:
  - `non_authoritative: true` (always)
  - `requires_explicit_confirmation: true` (always)
  - `reviewer: "BOH_WORKER_v4"`
  - `extracted_topics`, `extracted_definitions`, `extracted_variables`
  - `suspected_conflicts`
  - `recommended_metadata_patch`
  - `placement_suggestion` (v4 folder routing based on status/type only)
- **Returns 404** if file not found (tries basename fallback first)

---

### 12. `GET /docs/{doc_id}`
- **Returns:** `{ doc, definitions, events }` for a single document
- **Returns 404** if doc_id not found

---

## Query Parameter Summary

| Route | Required Params | Optional Params |
|-------|----------------|-----------------|
| `/index` | — | `library_root` |
| `/search` | `q` | `plane`, `limit` |
| `/canon` | — | `topic`, `plane` |
| `/conflicts` | — | — |
| `/nodes/{path}` GET | — | `include_expired` |
| `/nodes/{path}` POST | body fields | — |
| `/workflow` | — | `operator_state`, `status`, `doc_type` |
| `/events/export.ics` | — | `doc_id` |
| `/events` | — | `doc_id` |
| `/review/{path}` | — | `library_root` |
| `/docs/{id}` | — | — |

---

## Environment Variables

| Variable | Default | Effect |
|----------|---------|--------|
| `BOH_LIBRARY` | `./library` | Default library root for indexing and review |
| `BOH_DB` | `boh.db` | SQLite database file path |

---

## CORS Configuration
- `allow_origins=["*"]` — all origins allowed (local-only intent, no auth)
- `allow_methods=["*"]`
- `allow_headers=["*"]`

---

## Missing Routes (v0P Gaps)
The following capabilities exist in backend modules but have **no dedicated HTTP endpoint**:

| Capability | Module | Gap |
|-----------|--------|-----|
| Snapshot ingest | `snapshot.py` | No `/ingest` route — must call Python directly |
| Transition doc operator_state | `parser.py` `ALLOWED_TRANSITIONS` | No `PATCH /docs/{id}/workflow` endpoint |
| List planar planes | `db.py` | No `GET /planes` endpoint |
| Dismiss / acknowledge conflict | `conflicts.py` | No mutation endpoint |
| Export snapshot | — | No `GET /snapshot/export` route |

These gaps must be closed in v2 API standardization phase.
