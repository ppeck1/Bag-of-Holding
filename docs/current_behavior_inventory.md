# Current Behavior Inventory — Bag of Holding v0P
**Generated from:** Bag-of-Holding-main source (April 2026)
**Purpose:** Authoritative catalog of every meaningful deterministic behavior. Each behavior is tagged for migration disposition.
**Status:** READ-ONLY reference. Each behavior must be explicitly retained, adapted, or replaced in v2.

---

## Index of Behavior Domains

1. [Topic Normalization](#1-topic-normalization)
2. [Frontmatter Parsing](#2-frontmatter-parsing)
3. [Rubrix Lifecycle Validation](#3-rubrix-lifecycle-validation)
4. [Document Indexing / Crawling](#4-document-indexing--crawling)
5. [Canon Scoring](#5-canon-scoring)
6. [Canon Resolution](#6-canon-resolution)
7. [Conflict Detection](#7-conflict-detection)
8. [Search Scoring](#8-search-scoring)
9. [Planar Fact Storage & Validation](#9-planar-fact-storage--validation)
10. [Planar Alignment Scoring](#10-planar-alignment-scoring)
11. [Event Extraction & Validation](#11-event-extraction--validation)
12. [ICS Export](#12-ics-export)
13. [LLM Review Artifact Generation](#13-llm-review-artifact-generation)
14. [Snapshot Ingest](#14-snapshot-ingest)
15. [Database Layer](#15-database-layer)
16. [UI Behaviors](#16-ui-behaviors)

---

## 1. Topic Normalization

**Module:** `crawler.py` — `normalize_topic_token()`, `derive_topics_tokens()`
**Patch:** v1.1 A1

### Behaviors

| ID | Behavior | Disposition |
|----|----------|-------------|
| A1.1 | `normalize_topic_token(s)`: lowercase + strip + collapse internal whitespace. No deletion, no mutation beyond case+spacing. | **PRESERVE** |
| A1.2 | `derive_topics_tokens(list)`: joins normalized tokens with single space. Empty list → `""`. | **PRESERVE** |
| A1.3 | `topics_tokens` column stored as space-delimited normalized string in `docs` table. | **PRESERVE** |
| A1.4 | Canon resolution queries use `topics_tokens LIKE %normalized_topic%` (not FTS). | **PRESERVE** |

**Invariant:** Topic normalization is deterministic. Same input always produces same output. No inference.

---

## 2. Frontmatter Parsing

**Module:** `parser.py` — `parse_frontmatter()`

### Behaviors

| ID | Behavior | Disposition |
|----|----------|-------------|
| P1 | Frontmatter must begin with `---\n` and end with `\n---\n`. Regex: `^---\s*\n(.*?)\n---\s*\n`. | **PRESERVE** |
| P2 | Missing frontmatter → `LINT_MISSING_HEADER` error; document body returned unchanged. | **PRESERVE** |
| P3 | YAML parse failure → `LINT_YAML_PARSE_ERROR` with exception detail. | **PRESERVE** |
| P4 | Frontmatter must contain `boh:` root key. Missing → `LINT_MISSING_BOH_KEY`. | **PRESERVE** |
| P5 | Body is everything after the closing `---`. | **PRESERVE** |
| P6 | Required `boh` fields: `id`, `type`, `purpose`, `status`, `updated`. Missing any → `LINT_MISSING_FIELD`. | **PRESERVE** |

---

## 3. Rubrix Lifecycle Validation

**Module:** `parser.py` — `validate_header()`

### Valid Ontology

```
VALID_TYPES      = {note, canon, reference, log, event, person, ledger, project}
VALID_STATUSES   = {draft, working, canonical, archived}
OPERATOR_STATES  = {observe, vessel, constraint, integrate, release}
OPERATOR_INTENTS = {capture, triage, define, extract, reconcile, refactor, canonize, archive}
```

### Behaviors

| ID | Behavior | Disposition |
|----|----------|-------------|
| R1 | Invalid `type` → `LINT_INVALID_TYPE` | **PRESERVE** |
| R2 | Invalid `status` → `LINT_INVALID_STATUS` | **PRESERVE** |
| R3 | Missing `rubrix` block → `LINT_MISSING_RUBRIX` | **PRESERVE** |
| R4 | Invalid `operator_state` → `LINT_INVALID_OPERATOR_STATE` | **PRESERVE** |
| R5 | Invalid `operator_intent` → `LINT_INVALID_OPERATOR_INTENT` | **PRESERVE** |
| R6 | `status=canonical` requires `operator_state=release` → `LINT_CONSTRAINT_VIOLATION` | **PRESERVE** (hard constraint) |
| R7 | `type=canon` cannot have `operator_state=observe` → `LINT_CONSTRAINT_VIOLATION` | **PRESERVE** (hard constraint) |
| R8 | `status=archived` requires `operator_state=release` → `LINT_CONSTRAINT_VIOLATION` | **PRESERVE** (hard constraint) |
| R9 | `updated` field must be ISO 8601 if present → `LINT_INVALID_DATE` | **PRESERVE** |
| R10 | Allowed state transitions: `observe→vessel→constraint→integrate→release→constraint(patch)` | **PRESERVE** |

### Transition Table (locked)
```
observe    → {vessel}
vessel     → {constraint}
constraint → {integrate}
integrate  → {release}
release    → {constraint}  ← patch-only re-entry
```

---

## 4. Document Indexing / Crawling

**Module:** `crawler.py` — `crawl_library()`, `index_file()`
**Patch:** v1.1 D1, D2, F

### Behaviors

| ID | Behavior | Disposition |
|----|----------|-------------|
| I1 | Crawls all `*.md` files recursively under `library_root`. | **PRESERVE** |
| I2 | Skips files ending in `.review.md` (artifact files). | **PRESERVE** |
| I3 | Files with parse errors (no frontmatter) are noted but not indexed. | **PRESERVE** |
| I4 | `doc_id` comes from `boh.id`; falls back to new UUID if missing. | **PRESERVE** |
| I5 | `INSERT OR REPLACE` into `docs` by `doc_id` (upsert semantics). | **PRESERVE** |
| I6 | FTS index: deletes old FTS row by `path` then reinserts. | **PRESERVE** |
| I7 | Definitions: delete then reinsert per `doc_id`. | **PRESERVE** |
| I8 | Events: delete then reinsert per `doc_id`. D2 hardening applies. | **PRESERVE** |
| I9 | `source_type` inferred as `"canon_folder"` if `/canon/` in path, else `"library"`. | **PRESERVE** |
| I10 | `title` extracted from `boh.purpose` (first 120 chars); fallback to first `#` heading. | **PRESERVE** |
| I11 | `text_hash` is SHA-256 of full file content. | **PRESERVE** |
| I12 | `plane_scope_json`, `field_scope_json`, `node_scope_json` stored as `json.dumps(list)`. | **PRESERVE** |
| I13 | Lint errors recorded per-file in results; indexing continues despite errors. | **PRESERVE** |

---

## 5. Canon Scoring

**Module:** `canon.py` — `canon_score()`
**Patch:** v1.1

### Score Formula (locked)

```
score = 0.0
if status == "canonical":     score += 100
if type == "canon":           score += 50
if source_type == "canon_folder"
   OR "/canon/" in path:      score += 30
score += 10 * parse_semver(version)     # higher semver → higher score
score += 0.000001 * updated_ts          # recency tiebreaker
if status == "archived":      score -= 40
```

### Behaviors

| ID | Behavior | Disposition |
|----|----------|-------------|
| CS1 | Score is purely additive/subtractive over discrete, documented components. No inference. | **PRESERVE** |
| CS2 | `parse_semver()` converts `vMAJOR.MINOR.PATCH` → `MAJOR*1_000_000 + MINOR*1_000 + PATCH`. Returns 0 on error. | **PRESERVE** |
| CS3 | Archived docs penalized -40 (can still win if no better candidates). | **PRESERVE** |
| CS4 | Topic boost (+20) applied only during `resolve_canon()` when `topic` param active. Not part of base `canon_score()`. | **PRESERVE** |
| CS5 | `score_formula` dict returned in every `resolve_canon()` response for transparency. | **PRESERVE** |

---

## 6. Canon Resolution

**Module:** `canon.py` — `resolve_canon()`

### Behaviors

| ID | Behavior | Disposition |
|----|----------|-------------|
| CR1 | If `topic` provided: filter `docs` by `topics_tokens LIKE %normalized_topic%`. | **PRESERVE** |
| CR2 | If no `topic`: select all docs where `status != 'archived'` (or null). | **PRESERVE** |
| CR3 | If `plane_scope` provided: intersect doc's `plane_scope_json` list with request scope (comma-split). Only docs with at least one overlap pass. | **PRESERVE** |
| CR4 | Returns up to 10 candidates sorted by score descending. | **PRESERVE** |
| CR5 | Ambiguity threshold = 5%. If `|top - second| / top <= 0.05`: creates `canon_collision` conflict in DB, returns it in `ambiguity_conflicts`. | **PRESERVE** |
| CR6 | Winner is first ranked candidate. Not authoritative — user must confirm. | **PRESERVE** |
| CR7 | Returns `{"winner": null, "candidates": [], ...}` if no docs match. | **PRESERVE** |
| CR8 | `_ensure_conflict()`: inserts conflict row only if same `(conflict_type, doc_ids, term)` not already present. | **PRESERVE** |

---

## 7. Conflict Detection

**Module:** `conflicts.py` — `detect_all_conflicts()`
**Patch:** v1.1 B2, C1

### Three Detection Passes

#### 7a. Definition Conflicts
| ID | Behavior | Disposition |
|----|----------|-------------|
| DC1 | Groups `defs` by `(term, plane_scope_json)`. If `COUNT(DISTINCT block_hash) > 1`: conflict. | **PRESERVE** |
| DC2 | Conflict type: `definition_conflict` | **PRESERVE** |

#### 7b. Canon Collisions
| ID | Behavior | Disposition |
|----|----------|-------------|
| CC1 | Compares all pairs of `status='canonical'` docs. | **PRESERVE** |
| CC2 | Shared normalized topic tokens required for collision (B2). | **PRESERVE** |
| CC3 | Plane scope must overlap (or both empty = global scope) for collision (B2). | **PRESERVE** |
| CC4 | Collision records `term` = space-joined sorted shared tokens. | **PRESERVE** |
| CC5 | `_upsert_conflict()`: inserts only if `(conflict_type, doc_ids, term, plane_path)` not already present. | **PRESERVE** |

#### 7c. Planar Conflicts
| ID | Behavior | Disposition |
|----|----------|-------------|
| PC1 | Window: `ts >= now - 86400` (last 24 hours) AND `valid_until IS NULL OR valid_until > now` (C1). | **PRESERVE** |
| PC2 | Groups by `plane_path`. Conflict requires `COUNT(DISTINCT d) > 1` within window. | **PRESERVE** |
| PC3 | At least one fact in group must have `(q + c) > 0.7` (confidence threshold). | **PRESERVE** |
| PC4 | Conflict type: `planar_conflict` | **PRESERVE** |

### Global Behaviors
| ID | Behavior | Disposition |
|----|----------|-------------|
| CF1 | No auto-resolution of any conflict type. | **PRESERVE** (core principle) |
| CF2 | `list_conflicts()` returns all rows ordered by `detected_ts DESC`. | **PRESERVE** |
| CF3 | Conflict detection triggered automatically after `/index` and after `POST /nodes/`. | **PRESERVE** |

---

## 8. Search Scoring

**Module:** `search.py` — `search()`

### Score Formula (locked)

```
text_score    = normalize(bm25_score) to [0,1]; higher = better match
canon_norm    = min(1.0, canon_score(doc) / 180.0)
planar_score  = planar_alignment_score(plane_scopes, query_plane)
conflict_pen  = -0.1 if doc has any conflict else 0.0
final_score   = 0.6*text_score + 0.2*canon_norm + 0.2*planar_score + conflict_pen
```

### Behaviors

| ID | Behavior | Disposition |
|----|----------|-------------|
| SS1 | Uses SQLite FTS5 with BM25. | **PRESERVE** |
| SS2 | BM25 normalized: `1.0 - (raw - min) / range`. Lower BM25 = better (SQLite convention). | **PRESERVE** |
| SS3 | Canon normalization max = 180 (hardcoded). | **PRESERVE** |
| SS4 | Conflict penalty applied if doc_id appears in any conflict row's `doc_ids` (comma-split). | **PRESERVE** |
| SS5 | Per-result `score_breakdown` always returned (explainability). | **PRESERVE** |
| SS6 | Results sorted descending by `final_score`. | **PRESERVE** |
| SS7 | Returns `[{"error": str}]` on FTS exception instead of crashing. | **PRESERVE** |

---

## 9. Planar Fact Storage & Validation

**Module:** `planar.py` — `store_fact()`, `validate_fact()`

### Behaviors

| ID | Behavior | Disposition |
|----|----------|-------------|
| PF1 | `d` must be `-1`, `0`, or `+1`. | **PRESERVE** |
| PF2 | `q` and `c` must be in `[0,1]`. | **PRESERVE** |
| PF3 | When `d=0`: `m` must be `"cancel"` or `"contain"`. | **PRESERVE** |
| PF4 | `plane_path` required. | **PRESERVE** |
| PF5 | `subject_id` generated as UUID if not provided. | **PRESERVE** |
| PF6 | `ts` set to `int(time.time())` at storage time. | **PRESERVE** |
| PF7 | `valid_until` is optional; facts without it never expire. | **PRESERVE** |
| PF8 | On validation error: returns `{"stored": False, "errors": [...]}`. | **PRESERVE** |
| PF9 | On success: returns `{"stored": True, "subject_id": ..., "ts": ...}`. | **PRESERVE** |

---

## 10. Planar Alignment Scoring

**Module:** `planar.py` — `planar_alignment_score()`

### Behaviors

| ID | Behavior | Disposition |
|----|----------|-------------|
| PA1 | Empty plane_scopes → score = `0.0`. | **PRESERVE** |
| PA2 | No active facts in any scope → score = `0.5` (neutral). | **PRESERVE** |
| PA3 | Direction normalization: `(d + 1) / 2.0` maps `-1→0`, `0→0.5`, `+1→1`. | **PRESERVE** |
| PA4 | Weight per fact: `q * c`. | **PRESERVE** |
| PA5 | `weighted_score / total_weight`, capped at 1.0. | **PRESERVE** |
| PA6 | Only active (non-expired) facts considered. | **PRESERVE** |

---

## 11. Event Extraction & Validation

**Module:** `crawler.py`, `parser.py`
**Patch:** v1.1 D1, D2

### Behaviors

| ID | Behavior | Disposition |
|----|----------|-------------|
| EV1 | Events extracted only from explicit `## Event:\n- key: value` blocks in body. | **PRESERVE** |
| EV2 | `type=event` in frontmatter does NOT infer start from `boh.updated` (D1 removed this behavior). | **PRESERVE** |
| EV3 | Event must have explicit `start` (ISO 8601) AND explicit `timezone` to be created (D2). | **PRESERVE** |
| EV4 | Events failing D2 validation are noted in `potential_events_detected` (not created). | **PRESERVE** |
| EV5 | `event_id` is a new UUID per event. | **PRESERVE** |
| EV6 | `confidence` stored as `1.0` for all crawler-extracted events. | **PRESERVE** |

---

## 12. ICS Export

**Module:** `events.py` — `export_ics()`

### Behaviors

| ID | Behavior | Disposition |
|----|----------|-------------|
| IC1 | Produces RFC 5545 VCALENDAR with `PRODID:-//Bag of Holding v0P//EN`. | **PRESERVE with update** (update version string) |
| IC2 | Timestamps formatted as `YYYYMMDDTHHMMSSz` (UTC). | **PRESERVE** |
| IC3 | Events without valid `start_ts` are silently skipped. | **PRESERVE** |
| IC4 | `DTEND` falls back to `DTSTART` if no end_ts. | **PRESERVE** |
| IC5 | `SUMMARY` uses `doc_id` (not title) — known limitation. | **ADAPT** (v2: use title or path) |

---

## 13. LLM Review Artifact Generation

**Module:** `llm_review.py` — `generate_review_artifact()`

### Behaviors

| ID | Behavior | Disposition |
|----|----------|-------------|
| LR1 | Artifact always has `non_authoritative: true`. Cannot be changed. | **PRESERVE** (core principle) |
| LR2 | Artifact always has `requires_explicit_confirmation: true`. | **PRESERVE** |
| LR3 | Reviewer string is `"BOH_WORKER_v4"`. | **PRESERVE** |
| LR4 | Artifact never writes to `docs` table or modifies canon. | **PRESERVE** |
| LR5 | Writes `.review.json` alongside source file on disk. | **PRESERVE** |
| LR6 | Path resolution: tries `library_root/doc_path` first; falls back to `library_root/basename(doc_path)`. No invention beyond this. | **PRESERVE** |
| LR7 | `recommended_metadata_patch` is suggestion only. Topics extracted from headings if missing. | **PRESERVE** |
| LR8 | `placement_suggestion` uses `status` and `type` only — deterministic, no inference beyond these fields. | **PRESERVE** |
| LR9 | `normalization_output_hash` = SHA-256 of sorted JSON of extracted topics + defs + vars. | **PRESERVE** |
| LR10 | `suspected_conflicts`: cross-references `defs` table for same term with different `block_hash`. | **PRESERVE** |

---

## 14. Snapshot Ingest

**Module:** `snapshot.py` — `ingest_snapshot_export()`

### Behaviors

| ID | Behavior | Disposition |
|----|----------|-------------|
| SI1 | Accepts `boh_export_<run_id>.json` format: `{ run_id, files: [{artifacts: {meta, defs, vars, events}}] }`. | **PRESERVE** |
| SI2 | Uses `sha256` or `text_hash` from meta — never recomputes hash. | **PRESERVE** |
| SI3 | `topics_tokens` derived via `derive_topics_tokens()` at ingest time (not stored in snapshot). | **PRESERVE** |
| SI4 | `plane_scope_json` always stored as `json.dumps(list)` (F fix). | **PRESERVE** |
| SI5 | Events: D2 rule enforced — no start or no timezone → skip silently. | **PRESERVE** |
| SI6 | Entries missing `artifacts.meta` are skipped; logged in `skipped` list. | **PRESERVE** |
| SI7 | `INSERT OR REPLACE INTO docs` — snapshot can overwrite existing doc by `doc_id`. | **PRESERVE** |
| SI8 | No HTTP endpoint for snapshot ingest in v0P (gap). | **CLOSE IN V2** |

---

## 15. Database Layer

**Module:** `db.py`, `schema.sql`

### Schema (locked)

```sql
docs        (doc_id PK, path UNIQUE, type, status, version, updated_ts,
             operator_state, operator_intent,
             plane_scope_json, field_scope_json, node_scope_json,
             text_hash, source_type, topics_tokens DEFAULT '')

docs_fts    VIRTUAL TABLE fts5(content, title, path, topics)

defs        (doc_id, term, block_hash, block_text, plane_scope_json)

plane_facts (subject_id, plane_path, r, d, q, c, m, ts, valid_until, context_ref)

events      (event_id PK, doc_id, start_ts, end_ts, timezone, status, confidence)

conflicts   (conflict_type, doc_ids, term, plane_path, detected_ts)
```

### Behaviors

| ID | Behavior | Disposition |
|----|----------|-------------|
| DB1 | WAL mode enabled (`PRAGMA journal_mode=WAL`). | **PRESERVE** |
| DB2 | Foreign keys enabled (`PRAGMA foreign_keys=ON`). | **PRESERVE** |
| DB3 | `sqlite3.Row` row factory — all results return as dicts. | **PRESERVE** |
| DB4 | Every `fetchall`, `fetchone`, `execute` opens and closes its own connection. | **ADAPT** (v2: consider connection pooling or context manager) |
| DB5 | `schema.sql` run with `executescript` at startup (idempotent via `CREATE IF NOT EXISTS`). | **PRESERVE** |

---

## 16. UI Behaviors

**Module:** `main.py` — `ui()` route (inline HTML string)

### Behaviors

| ID | Behavior | Disposition |
|----|----------|-------------|
| UI1 | Single page, no routing. | **REPLACE** |
| UI2 | Dark mode monospace (GitHub dark palette). | **RETAIN AESTHETIC** |
| UI3 | All API calls via vanilla `fetch()`. | **MIGRATE TO SPA** |
| UI4 | Outputs raw JSON in `<pre>` elements. | **REPLACE with structured views** |
| UI5 | Five functional areas present: Index, Search, Canon, Conflicts, Workflow. | **EXPAND to 5-panel IA** |
| UI6 | No document browser, no navigation, no triage flow. | **BUILD IN V2** |
| UI7 | Swagger `/docs` and ReDoc `/redoc` links exposed. | **RETAIN FOR DEV ACCESS** |

---

## Core Principles (Non-Negotiable)

These behaviors must survive the entire migration unchanged:

| Principle | Current Implementation | v2 Commitment |
|-----------|----------------------|---------------|
| Local-first | SQLite + filesystem, no cloud calls | Unchanged |
| Deterministic scoring | All formulas documented and locked | Unchanged |
| No silent canon overwrite | No endpoint mutates canon without explicit user action | Unchanged |
| No auto-resolution | `conflicts` table grows; no delete-on-detection | Unchanged |
| LLM artifacts non-authoritative | `non_authoritative: true` hardcoded | Unchanged |
| Explicit metadata governance | Lint errors surfaced, not suppressed | Unchanged |
| Rubrix lifecycle enforced | Hard constraints in `validate_header()` | Unchanged |
| Explainable search | `score_breakdown` always returned | Unchanged |
