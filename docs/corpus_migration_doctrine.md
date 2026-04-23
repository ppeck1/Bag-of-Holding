# Corpus Migration Doctrine — Bag of Holding v2
**Authority source:** boh_codex_pack `docs/corpus_migration_doctrine.md`
**Purpose:** Rules for classifying, handling, and preserving every document artifact encountered during migration. Defines how the corpus moves from v0P to v2 without data loss, silent overwrite, or lineage corruption.
**Status:** Authoritative. These rules govern all ingest, indexing, and triage operations in v2.

---

## Preamble

The Bag of Holding corpus is not just a collection of files — it is a governed knowledge graph with explicit provenance, lifecycle state, and conflict history. Every document has a classification. Every classification has rules. Nothing is discarded silently. Nothing is merged without labeling.

The five canonical corpus classes defined below are authoritative for all v2 operations. They replace any informal or unlabeled classification used in v0P.

---

## 1. Corpus Classification Schema

Every document in the corpus belongs to exactly one class at any given time. Classification is determined by the document's `status`, `type`, and `operator_state` fields, evaluated in the order below.

### Class Definitions

#### Class A: Canon
**Label:** `CORPUS_CLASS:CANON`

**Criteria:**
```
status == "canonical"
AND operator_state == "release"
AND type ∈ {canon, reference, note, project, person, ledger}
AND no open conflicts involving this doc
```

**Rules:**
- Treated as the authoritative source for its topic + plane_scope combination
- Cannot be silently overwritten by any ingest operation
- Any ingest of a document with the same `doc_id` as an existing Canon document must:
  1. Detect the collision
  2. Record it as a `canon_collision` conflict
  3. Surface it to the user for explicit resolution
  4. Preserve both versions with lineage links
- Removal requires explicit archival action — never automatic
- LLM review artifacts may suggest patches to Canon documents; those patches require explicit user confirmation before application

#### Class B: Draft
**Label:** `CORPUS_CLASS:DRAFT`

**Criteria:**
```
status ∈ {draft, working}
AND operator_state ∈ {observe, vessel, constraint, integrate}
```

**Rules:**
- May be freely updated by ingest (INSERT OR REPLACE is acceptable)
- Should be surfaced in triage workflows for promotion consideration
- Lint errors are non-blocking — document is stored with errors noted
- Not eligible for canon scoring winner; deprioritized in search results
- Must retain its `doc_id` across ingest cycles (no silent re-ID)

#### Class C: Derived
**Label:** `CORPUS_CLASS:DERIVED`

**Criteria:**
```
source_type == "snapshot"
OR source_type ∈ {worker_export, llm_extract, derived}
OR path matches *.review.json
```

**Rules:**
- Always marked `non_authoritative: true` in metadata or artifact
- Cannot promote itself to Canon unilaterally
- Must carry explicit `source_ref` linking to the originating document(s)
- `.review.json` files are never indexed into `docs` table (crawler skips them)
- Snapshot-ingested documents are Derived until explicitly promoted by user action

#### Class D: Archive
**Label:** `CORPUS_CLASS:ARCHIVE`

**Criteria:**
```
status == "archived"
AND operator_state == "release"
```

**Rules:**
- Cannot be promoted back to Canon without passing through the full Rubrix lifecycle
- Retained indefinitely — never deleted automatically
- Archive penalty (−40) applied in canon scoring (§1 of math_authority.md)
- Visible in Library panel with clear "Archived" labeling
- Not eligible for `resolve_canon()` winner unless no other candidates exist

#### Class E: Evidence
**Label:** `CORPUS_CLASS:EVIDENCE`

**Criteria:**
```
type ∈ {log, event}
OR path matches */evidence/* OR */logs/*
OR doc has no promotable structure (no topics, no defs, pure capture)
```

**Rules:**
- Captured as-is; no normalization pressure applied
- Events extracted and stored in `events` table per D1/D2 rules
- Not eligible for canon resolution
- May be linked to Canon documents via `plane_scope` or `context_ref`
- Preserved indefinitely as lineage artifacts

---

## 2. Duplicate Handling

**Principle:** Duplicates are linked, not deleted.

A duplicate is any document that shares one or more of:
- Same `doc_id` (identity collision)
- Same `text_hash` (content duplicate)
- Overlapping `topics_tokens` with `status == "canonical"` in same `plane_scope` (semantic near-duplicate)

### Duplicate Detection Rules

| Duplicate Type | Detection Method | Action |
|---------------|-----------------|--------|
| Identity duplicate (`doc_id` collision) | `INSERT OR REPLACE` catches it | Replace if incoming is Derived; create conflict if incoming is Canon |
| Content duplicate (`text_hash` match) | Query `docs` for same `text_hash` before insert | Log as lineage link; do not delete either copy |
| Semantic near-duplicate (topic + scope overlap) | Canon collision detection (§9 math_authority) | Create `canon_collision` conflict; surface to user |

### Duplicate Record Structure

When a content or semantic duplicate is detected, a conflict record is created:

```json
{
  "conflict_type": "duplicate_content",
  "doc_ids": "doc_a_id,doc_b_id",
  "term": "<shared topic token or 'content_hash'>",
  "plane_path": "<shared scope or 'global'>",
  "detected_ts": 1234567890
}
```

No document is deleted. Both are preserved. The conflict record is the lineage link.

---

## 3. Ingest Rules

### 3a. Filesystem Ingest (Crawler)

1. Discover all `*.md` files recursively under `library_root`
2. Skip `*.review.md` files (Derived artifacts — not indexable)
3. Parse frontmatter; classify document
4. Store to `docs` via `INSERT OR REPLACE` (identity-keyed on `doc_id`)
5. Re-derive `topics_tokens` from `topics` array (never trust a cached value)
6. Re-extract definitions and events (delete + reinsert per `doc_id`)
7. Run all three conflict detection passes after full crawl
8. Return per-file lint results; never suppress errors

**Prohibited during filesystem ingest:**
- Modifying file contents on disk
- Promoting a document's status or operator_state
- Creating new `doc_id` values for documents that already have one
- Deleting existing `doc_id` records without explicit user instruction

### 3b. Snapshot Ingest

1. Parse `boh_export_<run_id>.json`
2. Classify each entry as `CORPUS_CLASS:DERIVED` (source_type = "snapshot")
3. For each entry: apply identity duplicate check
4. Store via `INSERT OR REPLACE` (snapshot can update Derived docs)
5. If incoming `doc_id` matches an existing Canon doc:
   - **Do not replace** — create `canon_collision` conflict instead
   - Log in `skipped` list with reason `"would_overwrite_canon"`
6. Re-derive `topics_tokens` (A1.2 rule)
7. Apply D2 event hardening (no timezone → skip)
8. Return `{ inserted_docs, inserted_defs, inserted_events, skipped, conflicts_created }`

### 3c. Manual Document Promotion

The corpus migration doctrine does not permit automatic promotion. A document moves between classes only via:

1. **Explicit Rubrix state transition** — user POSTs to `PATCH /api/workflow/{doc_id}` with the new `operator_state`
2. **Status update** — user edits the `status` field in the source markdown and re-indexes
3. **Conflict resolution** — user explicitly adjudicates a `canon_collision` conflict and selects the winner

No ingest operation, LLM review, or background job may promote a document automatically.

---

## 4. Lineage Requirements

Every document in the corpus must carry enough metadata to reconstruct its history. The following fields are required for lineage tracing:

| Field | Source | Required For |
|-------|--------|-------------|
| `doc_id` | `boh.id` in frontmatter | All classes |
| `text_hash` | SHA-256 of full file content | All classes (filesystem ingest) |
| `source_type` | Inferred from path or set during snapshot ingest | All classes |
| `updated_ts` | Parsed from `boh.updated` | All classes |
| `operator_state` | From `boh.rubrix.operator_state` | All classes |
| `version` | From `boh.version` | Canon, Draft |
| `plane_scope_json` | From `boh.scope.plane_scope` | All classes |

**Lineage invariant:** A document's `doc_id` never changes. If a re-ingested document has the same `doc_id` as a stored document, it is an update to the same lineage chain — not a new document.

---

## 5. Historical Artifact Preservation

**Principle:** No historical artifact is discarded without labeling.

The following artifact types must be preserved during migration:

| Artifact | Preservation Rule |
|----------|-----------------|
| `*.review.json` files | Leave on disk; never indexed; never deleted |
| `*.bak_*` files (e.g., `llm_review.py.bak_20260226`) | Leave in place; document in Library panel as "backup artifact" |
| Old `boh.db` database | Rename to `boh_v0P_<timestamp>.db`; preserve alongside `boh_v2.db` |
| Conflict records | Never deleted; `acknowledged` flag added in v2 (does not delete record) |
| Archived documents (`status=archived`) | Preserved forever in DB and on disk |

---

## 6. Conflict Record Doctrine

**From core principles:** No auto-resolution. No silent dismissal.

Conflict records in the `conflicts` table follow these rules:

1. **Conflicts are append-only.** The `_upsert_conflict()` function only inserts — never updates existing conflicts.
2. **Acknowledgment is not resolution.** The new `acknowledged` field (v2 addition) allows a user to mark a conflict as "seen" — it does not remove the record or resolve the underlying issue.
3. **Conflict display must be prominent.** In the v2 UI, unacknowledged conflicts must surface in the Dashboard panel as a count badge and in the Canon & Conflicts panel as a prioritized list.
4. **Conflict records survive schema migrations.** The `conflicts` table is never truncated during a migration.
5. **Conflict records are never auto-closed** by subsequent indexing runs. A conflict can only be closed by explicit user action (future feature).

---

## 7. LLM Review Artifact Doctrine

LLM review artifacts (`*.review.json`) are `CORPUS_CLASS:DERIVED` and subject to all Derived rules plus the following:

1. `non_authoritative: true` — always, forever, cannot be overridden by any configuration
2. `requires_explicit_confirmation: true` — always
3. Artifact patches (`recommended_metadata_patch`) are suggestions only. Applying them requires the user to edit the source markdown and re-index.
4. Artifacts are written to disk but never indexed. They are invisible to canon resolution and search.
5. The reviewer string (`BOH_WORKER_v4`) identifies the artifact generation version. Future versions must increment this identifier.
6. Suspected conflicts in review artifacts are informational only. They do not create entries in the `conflicts` table (only `detect_all_conflicts()` does that).

---

## 8. v0P → v2 Corpus Migration Checklist

The following steps must be completed before any v2 ingest operations begin:

- [ ] Rename `boh.db` to `boh_v0P_<datestamp>.db` and keep in project root
- [ ] Run schema migration to create `boh_v2.db` with `conflicts.acknowledged` column and `schema_version` table
- [ ] Verify all existing `plane_scope_json` values in `defs` table are valid JSON arrays (F invariant)
- [ ] Verify all `topics_tokens` values are space-delimited lowercase strings (A1.2 invariant)
- [ ] Run `detect_all_conflicts()` on imported data; log all conflicts to migration report
- [ ] Confirm no Canon documents were silently overwritten during migration
- [ ] Confirm all `*.review.json` files are excluded from `docs` table
- [ ] Run full test suite; confirm 38 v0P checks + new v2 checks all pass
- [ ] Document corpus class distribution (count of each class in the migrated DB) in migration report
