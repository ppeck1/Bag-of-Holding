# Bag of Holding v0P

**Deterministic Local Knowledge Engine with Planar Math + Rubrix Governance**
**Patch v1.1 Applied**

A local-first, deterministic knowledge engine that indexes a filesystem library, resolves canonical state, stores and queries structured Planar math (Plane/Field/Node), enforces Rubrix operator lifecycle constraints, and surfaces contradictions explicitly.

---

## Project Structure

```
bag_of_holding/
├── main.py            # FastAPI application + web UI
├── db.py              # SQLite connection + helpers
├── schema.sql         # Database schema (6 tables + topics_tokens)
├── parser.py          # Markdown header parser + Rubrix validator
├── crawler.py         # Filesystem crawler + document indexer
├── canon.py           # Deterministic canon resolution engine
├── conflicts.py       # Conflict detection (definitions, canon, planar)
├── planar.py          # Planar math (Plane/Field/Node) storage + scoring
├── search.py          # FTS search with explainable scoring
├── events.py          # Event management + ICS export
├── llm_review.py      # LLM review artifact generation (non-authoritative)
├── snapshot.py        # BOH_WORKER snapshot export ingest
├── requirements.txt   # Python dependencies
├── self_test.py       # Self-test script (covers patch v1.1)
└── library/           # Sample document library (shipped)
    ├── canon/
    │   └── planar-math.md     # Canonical definition (status=canonical, type=canon)
    ├── notes/
    │   ├── rubrix-lifecycle.md  # Working notes with explicit Event block
    │   └── lint-test.md         # Intentional LINT_CONSTRAINT_VIOLATION for testing
    └── refs/
        └── planar-alt.md        # Alternative reference (triggers definition conflict)
```

---

## Setup

### Requirements

- Python 3.11+
- pip

### Install

```bash
cd bag_of_holding
pip install -r requirements.txt
```

---

## Running

```bash
# Start the API server (default port 8000)
uvicorn main:app --reload

# With custom library root and DB path
BOH_LIBRARY=./my-library BOH_DB=my.db uvicorn main:app --reload
```

Open `http://localhost:8000` for the web UI.
Open `http://localhost:8000/docs` for the Swagger API documentation.

---

## Self-Test

```bash
python self_test.py
```

The self-test:
1. Initializes the database
2. Validates the header parser and Rubrix lint rules
3. Crawls and indexes the sample library
4. Demonstrates FTS search with explainable scoring
5. Resolves canonical documents
6. Detects conflicts
7. Stores and validates planar facts
8. Exports events as ICS
9. Generates LLM review artifacts (non-authoritative)

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/index` | Index the filesystem library |
| `GET` | `/search?q=...` | Full-text search with scoring breakdown |
| `GET` | `/canon?topic=...` | Resolve canonical document |
| `GET` | `/conflicts` | List all detected conflicts |
| `GET` | `/nodes/{node_path}` | Get planar facts for a node |
| `POST` | `/nodes/{node_path}` | Store a planar fact |
| `GET` | `/workflow` | List documents by Rubrix workflow state |
| `GET` | `/events` | List all events |
| `GET` | `/events/export.ics` | Export events as ICS (no external writes) |
| `GET` | `/review/{path}` | Generate LLM review artifact |
| `GET` | `/docs/{doc_id}` | Get a single document |

---

## Document Format

Every markdown document must begin with a `boh:` YAML frontmatter block:

```yaml
---
boh:
  id: unique-id-string
  type: note           # note|canon|reference|log|event|person|ledger|project
  purpose: Description of this document's purpose
  topics:
    - topic1
    - topic2
  status: draft        # draft|working|canonical|archived
  version: "1.0.0"     # semver or null
  updated: "2024-01-15T10:00:00Z"  # ISO8601

  scope:
    plane_scope:
      - plane.field    # dot-path syntax
    field_scope:
      - plane.field.subfield
    node_scope:
      - plane.field.node

  rubrix:
    operator_state: observe   # observe|vessel|constraint|integrate|release
    operator_intent: capture  # capture|triage|define|extract|reconcile|refactor|canonize|archive
    next_operator: null
---
```

### Hard Constraints (enforced at lint time)

- `status=canonical` ⇒ `operator_state` must be `release`
- `type=canon` ⇒ `operator_state` cannot be `observe`
- `status=archived` ⇒ `operator_state` must be `release`

### Allowed Rubrix Transitions

```
observe → vessel → constraint → integrate → release → constraint (patch only)
```

---

## Planar Math

Planar facts are stored via `POST /nodes/{plane.field.node}`:

```json
{
  "r": 1.0,
  "d": 1,
  "q": 0.9,
  "c": 0.85,
  "context_ref": "source document",
  "m": null
}
```

- `d` ∈ {-1, 0, +1} (direction/alignment)
- `q`, `c` ∈ [0, 1] (quality, coherence)
- `m` is required (and must be "cancel" or "contain") when `d = 0`
- Expired facts (past `valid_until`) are excluded from scoring

---

## Search Scoring

```
final_score = 0.6 * text_score
            + 0.2 * canon_score
            + 0.2 * planar_alignment_score
            + conflict_penalty
```

All score components are returned in the API response under `score_breakdown`.

---

## Canon Resolution

```
canon_score = +100 if status=canonical
            + +50 if type=canon
            + +30 if in /canon/ folder
            + +10 * semver_rank(version)
            + +0.000001 * updated_ts
            + -40 if archived
```

If top two candidates are within 5% of each other, a `canon_collision` conflict is created.

---

## Conflict Detection

| Type | Trigger |
|------|---------|
| `definition_conflict` | Same term + same plane_scope + different block_hash |
| `canon_collision` | 2+ canonical docs with overlapping topic + plane_scope |
| `planar_conflict` | Same plane_path within 24h, differing `d`, both `q` and `c` > 0.7 |

**No auto-resolution.** All conflicts require explicit user action.

---

## LLM Review Artifacts

Generated at `GET /review/{path}` and saved as `{document}.review.json`:

```json
{
  "non_authoritative": true,
  "requires_explicit_confirmation": true,
  "extracted_topics": [...],
  "extracted_definitions": [...],
  "extracted_variables": [...],
  "suspected_conflicts": [...],
  "recommended_metadata_patch": {...},
  "normalization_output_hash": "..."
}
```

Review artifacts **cannot** overwrite canon automatically. Metadata patches require explicit confirmation. Canon changes require explicit user action.

---

## Design Principles

- **Deterministic > intelligent**: All scoring is rule-based and explainable
- **Structured > inferred**: Explicit schema over magic
- **Explicit > magical**: All violations produce visible lint errors
- **LLM output is non-authoritative**: Review artifacts never auto-write canon
- Not agentic · Not cloud-based · Not vector-driven · Not probabilistic
