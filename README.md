# 📦 Bag of Holding v2

**Deterministic Local Knowledge Workbench — Phase 8**

A local-first knowledge management system with explicit canon resolution, Rubrix lifecycle governance, planar math scoring, Daenary semantic state encoding, and selective DCNS relationship edges. No cloud dependency. No auto-resolution. All scoring is deterministic and inspectable.

---

## Quickstart

```bash
cd boh_v2
pip install -r requirements.txt
python launcher.py
```

Opens at `http://127.0.0.1:8000` automatically.

**Windows:** double-click `launcher.bat`  
**macOS/Linux:** `chmod +x launcher.sh && ./launcher.sh`

---

## What it does

| Area | Capability |
|------|-----------|
| **Library** | Index and browse Markdown documents with `boh:` YAML frontmatter |
| **Canon** | Deterministic scoring to resolve the authoritative document on any topic |
| **Conflicts** | Detect definition conflicts, canon collisions, and planar conflicts — no auto-resolution |
| **Search** | Full-text FTS5 search with explainable composite scoring + optional Daenary filters |
| **Planar Math** | Store and score directional facts across named planes / fields / nodes |
| **Rubrix** | Explicit document lifecycle governance (`observe → vessel → constraint → integrate → release`) |
| **Corpus Classes** | Classify every document: Canon, Draft, Derived, Archive, or Evidence |
| **Lineage** | Track duplicate documents, supersessions, and derivation chains |
| **Daenary** | Optional semantic state encoding: `state(-1/0/+1)`, `quality`, `confidence`, `mode`, time validity |
| **DCNS** | Selective relationship edge graph derived from lineage and conflicts; per-node load diagnostics |
| **Atlas** | Force-directed knowledge graph with DCNS-aware edges and Daenary diagnostic halos |
| **Document Viewer** | Rendered markdown + KaTeX math reader in both Atlas and every document detail drawer |
| **Events** | Extract and export events from documents as ICS calendar data |
| **LLM Review** | Non-authoritative review artifacts — never auto-applied |

---

## Core principles (never violated)

- **Local-first** — SQLite + filesystem. No cloud calls.
- **Deterministic scoring** — same inputs always produce same outputs. All formulas in `docs/math_authority.md`.
- **No silent canon overwrite** — snapshot ingest cannot replace a canonical document.
- **No auto-resolution** — conflicts surface and stay until explicitly addressed.
- **Rubrix ≠ Daenary** — Rubrix is lifecycle / governance state. Daenary is epistemic / semantic state. Neither replaces the other.
- **Daenary is additive** — documents without a `daenary:` block index and behave exactly as before.
- **Anti-collapse invariant** — Daenary `state=0` is never automatically flipped to `±1`.
- **LLM artifacts non-authoritative** — `non_authoritative: true` is hardcoded.
- **Duplicates linked, never deleted** — lineage links created; both versions preserved.

---

## UI — Six panels

| Panel | Purpose |
|-------|---------|
| **Dashboard** | Health overview: doc counts, conflict badge, corpus class distribution, lineage stats |
| **Library** | Browse, filter, and inspect all documents. Click *Detail →* to open the document drawer with full rendered content, related docs, Rubrix transitions, and lineage. |
| **Search** | FTS search with expandable score breakdown per result. Collapsible Daenary filter panel: dimension, state, min quality/confidence, uncertain-only, stale-only, conflicts-only. |
| **Canon & Conflicts** | Resolve canon by topic/plane; view conflict list; acknowledge conflicts; view lineage records. |
| **Import / Ingest** | Index filesystem library, ingest snapshot exports, sync DCNS edges, generate migration report, export ICS. |
| **Atlas** | Force-directed knowledge graph. Nodes colored by corpus class, sized by canon score. DCNS halos: red ring = conflict, amber dashed = stale coordinates, blue dot = uncertain coordinates. Click any node to open the document reader. |

---

## Document format

### Standard `boh:` frontmatter (required)

```markdown
---
boh:
  id: unique-id-001
  type: note                    # note|canon|reference|log|event|person|ledger|project
  purpose: What this doc is
  topics: [topic one, topic two]
  status: draft                 # draft|working|canonical|archived
  version: "0.1.0"
  updated: "2024-01-01T00:00:00Z"
  scope:
    plane_scope: [core.knowledge]
    field_scope: []
    node_scope: []
  rubrix:
    operator_state: observe     # observe→vessel→constraint→integrate→release
    operator_intent: capture    # capture|triage|define|extract|reconcile|refactor|canonize|archive
---

# Document Title

Content goes here. **Term**: definitions are extracted automatically.
```

### Optional `daenary:` block (Phase 8)

Attach alongside `boh:` to encode epistemic state. Documents without this block are unaffected.

```markdown
daenary:
  dimensions:
    - name: relevance
      state: 0          # -1 | 0 | +1
      quality: 0.80     # [0,1] signal quality
      confidence: 0.30  # [0,1] encoding certainty
      mode: contain     # 'contain'|'cancel' — only valid when state == 0
      observed_at: "2026-04-23T00:00:00Z"
      valid_until: "2026-05-01T00:00:00Z"

    - name: canon_alignment
      state: 1
      quality: 0.90
      confidence: 0.85
      observed_at: "2026-04-23T00:00:00Z"
```

**Validation:** malformed dimensions produce lint warnings but never block indexing.

---

## Scoring formulas

### Search composite score

```
base  = 0.6 × text_score + 0.2 × canon_score_normalized + 0.2 × planar_alignment + conflict_penalty
final = base + daenary_adjustment   (range: −0.05 to +0.05, never dominant)
```

### Canon score

```
+100  status == "canonical"
+50   type == "canon"
+30   source_type == "canon_folder" OR "/canon/" in path
+10 × semver_rank(version)
+0.000001 × updated_ts
−40   status == "archived"
```

Full formula reference: `docs/math_authority.md`

---

## Daenary semantic state (Phase 8)

| state | Meaning |
|-------|---------|
| `+1` | Affirmed — positive epistemic signal |
| `0` | Unresolved — observation exists, certainty withheld |
| `−1` | Negative — contradicted or deprecated |

`mode` (only when `state=0`): `contain` = deliberately held unresolved; `cancel` = signals cancel out.

**Example search queries enabled by Daenary:**

```bash
# High signal, low certainty
GET /api/search?q=canon&uncertain_only=true&min_quality=0.7

# Stale canon candidates
GET /api/search?q=model&stale=true

# High-confidence docs in a specific dimension
GET /api/search?q=latent&dimension=canon_alignment&min_confidence=0.8
```

---

## DCNS relationship layer (Phase 8)

Explicit relationship edges derived from lineage and conflicts. Not a full propagation engine.

| Edge type | State | Permeability |
|-----------|-------|-------------|
| `duplicate_content` | 0 | 0.95 |
| `supersedes` | +1 | 0.90 |
| `canon_relates_to` | +1 | 0.75 |
| `derives` | +1 | 0.80 |
| `conflicts` | −1 | 0.40 |

Sync manually: `POST /api/dcns/sync` — also runs automatically after a full library index.

---

## API reference

```
POST /api/index                         Index library (syncs DCNS edges on completion)
GET  /api/health                        Service health (includes "phase": 8)
GET  /api/dashboard                     Health summary

GET  /api/search?q=                     Search (all Daenary filters optional)
GET  /api/canon?topic=&plane=           Canon resolution
GET  /api/conflicts                     List conflicts
PATCH /api/conflicts/{id}/acknowledge   Acknowledge conflict

GET  /api/docs                          Document list (paginated + filterable)
GET  /api/docs/{id}                     Document detail + defs + events
GET  /api/docs/{id}/content             Raw markdown body
GET  /api/docs/{id}/related             Semantically related documents
GET  /api/docs/{id}/coordinates         Daenary coordinates

GET  /api/graph                         Atlas graph data (nodes + DCNS edges + diagnostics)
POST /api/dcns/sync                     Rebuild doc_edges

GET  /api/workflow                      Rubrix workflow listing
PATCH /api/workflow/{id}                Transition operator_state

GET  /api/nodes/{path}                  Planar facts
POST /api/nodes/{path}                  Store planar fact
GET  /api/planes                        Distinct plane paths

GET  /api/events                        Event list
GET  /api/events/export.ics             ICS calendar export

GET  /api/lineage                       All lineage records
GET  /api/lineage/{doc_id}              Doc-specific lineage
POST /api/lineage                       Manual lineage link
GET  /api/duplicates                    Content duplicate pairs
GET  /api/corpus/classes                Corpus class distribution
POST /api/corpus/migration-report       Write migration_report.md

GET  /api/review/{path}                 LLM review artifact (non-authoritative)
POST /api/ingest/snapshot               Snapshot ingest (canon guard active)
```

Interactive docs: `http://127.0.0.1:8000/docs`

---

## Running tests

```bash
cd boh_v2
python -m pytest tests/ -v
# Expected: 261 passed, 2 skipped, 0 failed
```

Phase-by-phase:

```bash
python -m pytest tests/test_integration.py -v   # 42  — core v0P behaviors
python -m pytest tests/test_new_routes.py  -v   # 32  — Phase 2 routes (2 skipped)
python -m pytest tests/test_phase4.py      -v   # 28  — corpus + lineage
python -m pytest tests/test_phase5.py      -v   # 23  — launcher + all routes
python -m pytest tests/test_phase6.py      -v   # 26  — ICS, corpus UI, migration report
python -m pytest tests/test_phase7.py      -v   # 39  — Atlas, reader, graph (1 skipped)
python -m pytest tests/test_phase8.py      -v   # 70  — Daenary, DCNS, search, drawer
```

---

## Building a standalone executable

```bash
pip install pyinstaller
pyinstaller boh.spec
./dist/boh/boh       # Linux/macOS
dist\boh\boh.exe     # Windows
```

---

## Project structure

```
boh_v2/
├── app/
│   ├── api/           FastAPI app + route files (one per domain)
│   ├── core/
│   │   ├── canon.py       Canon scoring + resolution
│   │   ├── conflicts.py   3-pass conflict detection
│   │   ├── corpus.py      5-class deterministic classifier
│   │   ├── daenary.py     Semantic state encoding (Phase 8)
│   │   ├── dcns.py        Relationship edge graph (Phase 8)
│   │   ├── lineage.py     Lineage + duplicate/supersession detection
│   │   ├── planar.py      Planar fact storage + alignment scoring
│   │   ├── related.py     Related doc scoring + graph data builder
│   │   ├── rubrix.py      Lifecycle ontology + validation
│   │   ├── search.py      FTS + composite scoring + Daenary filters
│   │   └── snapshot.py    Snapshot ingest + canon guard
│   ├── db/            SQLite connection + schema
│   ├── services/      Indexer, parser, reviewer, events, migration_report
│   └── ui/            SPA frontend (vanilla JS, no build step)
│       └── vendor/    Local KaTeX + marked.js (no CDN)
├── docs/              Analysis docs and migration maps
├── library/           Sample documents (planar-math.md, rubrix-lifecycle.md)
├── tests/             pytest suite — 261 tests across 9 files
├── launcher.py        Desktop launcher with Phase 8 preflight check
└── boh.spec           PyInstaller spec
```

---

## Database schema

| Table | Purpose |
|-------|---------|
| `docs` | Document registry |
| `docs_fts` | FTS5 full-text search index |
| `defs` | Extracted definition terms |
| `plane_facts` | Planar math directional facts |
| `events` | Extracted calendar events |
| `conflicts` | Conflict records |
| `lineage` | Lineage links (duplicate, supersession, derivation) |
| `doc_coordinates` | Daenary semantic dimensions per document **(Phase 8)** |
| `doc_edges` | DCNS explicit relationship edges **(Phase 8)** |
| `schema_version` | Migration history (current: v2.2.0) |

---

## Phase history

| Phase | Summary |
|-------|---------|
| 1–3 | Core indexer, FTS search, canon resolution, conflict detection, Rubrix lifecycle, SPA shell |
| 4 | Corpus classification, lineage tracking, content duplicate detection |
| 5 | Launcher with health check, full route coverage |
| 6 | ICS calendar export, corpus class UI, migration report generator |
| 7 | Atlas force-directed graph, document reader pane, KaTeX math rendering, related docs, local vendor libs |
| **8** | **Daenary semantic state, DCNS edge graph, document drawer viewer, Daenary search filters, Atlas node diagnostic halos** |
