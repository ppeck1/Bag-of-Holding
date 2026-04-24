# 📦 Bag of Holding v2
### Phase 12 — Constraint-Governed Operational Memory

**Local-first knowledge infrastructure for governed documents, reversible lifecycle history, and review-safe LLM assistance.**

---

Bag of Holding is not a notes app.

It is a constraint-governed operational memory system built for environments where documents carry consequence — clinical operations, systems architecture, research governance, and institutional decision-making.

Most tools help you store information.

BOH is built to help you decide what should be *trusted*, what *conflicts*, what is *stale*, what becomes *canonical*, and *why*.

The goal is not better note-taking.
The goal is coherent operational memory.

---

## The Problem

Organizations rarely fail because information is missing.

They fail because:

- decisions were never preserved
- conflicting documents silently coexist
- stale references continue driving live behavior
- ownership is unclear
- "tribal knowledge" disappears when the operator leaves
- no one can answer: *what actually governs this?*

Most systems optimize **storage**.

Very few optimize **stewardship**.

BOH is built for stewardship.

---

## What BOH Is Not

| Tool | Strength | What it lacks |
|------|----------|---------------|
| **Obsidian** | Personal cognition and note-linking | Governance, auditability, canonical enforcement, constrained LLM |
| **Notion** | Collaboration and presentation | Strict lifecycle control, provenance enforcement, review-safe mutation |
| **Jupyter** | Execution and experimentation | Long-term canonization, cross-document governance, decision lineage |
| **Git** | Code version control | Semantic conflict detection, document lifecycle, knowledge governance |
| **BOH** | **Operational cognition + institutional memory** | — |

BOH answers the question that comes *after* writing things down:
*"What should actually be trusted here, and by whom?"*

---

## System Philosophy

**LLM proposes. Human governs. System audits.**

BOH treats language models as assistants, not authorities.

The model **may**:
- summarize and classify documents
- suggest relationships and topics
- detect possible conflicts
- propose metadata and lifecycle state
- generate review artifacts

The model **may not**:
- silently overwrite canonical files
- auto-promote documents to canon
- bypass operator review
- apply any change without explicit user approval

This is not a safety limitation.
It is the architectural principle.

Epistemic integrity requires that *humans own the canon*.
BOH enforces this at the data layer.

---

## What BOH Does

| Area | Capability |
|------|-----------|
| **Library** | Index and browse Markdown documents with `boh:` YAML frontmatter |
| **Rubrix Lifecycle** | Governed state transitions with reversible backward movement and append-only history |
| **Canon Resolution** | Deterministic scoring to identify the authoritative document on any topic |
| **Conflict Detection** | Definition conflicts, canon collisions, planar conflicts — surfaces them, never auto-resolves |
| **LLM Review Queue** | Ollama-powered metadata proposals held for review; nothing applies without user approval |
| **Atlas** | Force-directed relationship graph with zoom, pan, node drag, edge hover, and performance controls |
| **Auto-Index** | Startup library scan with hash-based change detection; never blocks server boot |
| **Search** | FTS5 full-text search with explainable composite scoring and Daenary semantic filters |
| **Planar Math** | Directional fact storage and scoring across named planes, fields, and nodes |
| **Lineage** | Duplicate detection, supersession chains, and derivation tracking |
| **Daenary** | Optional epistemic state encoding: state(−1/0/+1), quality, confidence, mode, time validity |
| **DCNS** | Explicit relationship edge graph with per-node load diagnostics |
| **Audit Log** | Every significant mutation appended; never deleted; available via `/api/audit` |
| **System Status** | `/api/status` returns library health, Ollama availability, queue depth, index diagnostics |
| **Document Viewer** | Rendered markdown + KaTeX math in both Atlas and every document drawer |
| **Events** | Extract and export calendar events from documents as ICS data |

---

## Core Invariants (never violated)

- **Local-first** — SQLite + filesystem. No cloud dependency.
- **Deterministic scoring** — same inputs always produce same outputs. All formulas in `docs/math_authority.md`.
- **No silent canon overwrite** — canonical documents cannot be replaced without explicit workflow action.
- **No auto-resolution** — conflicts surface and remain until explicitly addressed.
- **LLM artifacts non-authoritative** — proposals go to review queue only; `non_authoritative: true` hardcoded.
- **Append-only lifecycle history** — undo and backward moves create new history records, never delete old ones.
- **Duplicates linked, never deleted** — lineage links created; both versions preserved.
- **Rubrix ≠ Daenary** — lifecycle governance and epistemic state are separate, non-overlapping systems.
- **Server startup never blocked** — auto-index and Ollama failures are caught, logged, and reported; server always boots.

---

## Quickstart

```bash
cd boh_v2
pip install -r requirements.txt
python launcher.py
```

Opens at `http://127.0.0.1:8000` automatically.

**Windows:** double-click `launcher.bat`
**macOS / Linux:** `chmod +x launcher.sh && ./launcher.sh`

**Optional environment variables:**

```bash
BOH_LIBRARY=./library          # path to your document library
BOH_AUTO_INDEX=true            # scan and index on startup (default: false)
BOH_AUTO_INDEX_MAX_FILES=5000  # startup scan cap
BOH_OLLAMA_ENABLED=true        # enable LLM review queue
BOH_OLLAMA_URL=http://localhost:11434
BOH_OLLAMA_MODEL=mistral-small
```

Auto-index is **off by default**. Enable it explicitly when your library is ready.

---

## First-Use Workflow

```
1.  Drop your folder into the library path (BOH_LIBRARY=./your-folder)
2.  Open the dashboard — click "Re-index library" or set BOH_AUTO_INDEX=true
3.  Visit the Library panel — review what was indexed
4.  Open the LLM Queue panel — review any Ollama-proposed metadata
5.  Approve or reject each proposal individually
6.  Resolve any conflicts in the Canon & Conflicts panel
7.  Advance documents through the Rubrix lifecycle
8.  Use backward movement or undo if a state transition was premature
9.  Open Atlas to explore document relationships visually
10. Canonize intentionally — never automatically
```

Nothing in steps 4–10 happens without your explicit action. That is the design.

---

## Atlas — The Relationship Field

Atlas is not decorative graph visualization.

It is the operational visibility layer.

**Atlas answers:**

- **what depends on what** — lineage and derivation chains
- **what conflicts with what** — DCNS conflict edges (red)
- **what is stale** — amber halo on nodes with expired coordinates
- **what is trusted** — green = canon class; node size reflects canon score
- **what is becoming canonical** — lifecycle state visible on hover
- **where load collapses** — per-node load diagnostics from DCNS

**Interaction model:**

| Action | Effect |
|--------|--------|
| Scroll wheel | Zoom in/out centered on cursor |
| Drag empty canvas | Pan the view |
| Drag a node | Reposition node, re-energize physics |
| Click node | Open document in reader pane |
| Double-click node | Expand neighborhood one hop |
| Shift+click node | Expand neighborhood |
| Hover node | Title, status, conflict/stale indicators |
| Hover edge | Shared topics, edge type, confidence |

**Toolbar:**
`＋/－ Zoom` · `⟳ Reset` · `⊡ Fit` · `◎ Focus selected` · `⊕ Expand` · `↻ Refresh`
`Balanced / High Quality / Static` performance presets · `Ripples` / `Glow` effect toggles

**Performance:** Balanced mode uses batched edge rendering, no `shadowBlur`, and a 30fps cap.
Static mode renders only on-demand — eliminates continuous animation entirely.
Effects auto-reduce if any frame exceeds 28ms.

---

## Rubrix Lifecycle

Documents move through governed operational states:

```
observe → vessel → constraint → integrate → release
```

| State | Meaning |
|-------|---------|
| `observe` | Initial intake — seen, not yet classified |
| `vessel` | Captured and held — awaiting constraint |
| `constraint` | Constrained by scope — under active evaluation |
| `integrate` | Integrated — ready for canonical promotion |
| `release` | Released — canonical or archived |

**Intents:** `capture` · `triage` · `define` · `extract` · `reconcile` · `refactor` · `canonize` · `archive`

**Phase 12 lifecycle additions:**

- **Backward movement** — any state can move one step backward (e.g. `release → integrate`)
- **Undo last** — revert to the state before the most recent transition
- **Lifecycle history** — every transition recorded with timestamp, direction, actor, and optional reason
- **Append-only** — undo and backward create new records; prior history is never deleted

All controls are available in the document drawer under **Rubrix Lifecycle**.

---

## Document Format

### Required `boh:` frontmatter

```markdown
---
boh:
  id: unique-id-001
  type: note                    # note|canon|reference|log|event|person|ledger|project
  purpose: What this document is
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

Content here. **Term**: definitions are extracted automatically.
```

### Optional `daenary:` block — epistemic state encoding

```markdown
daenary:
  dimensions:
    - name: relevance
      state: 0          # -1 | 0 | +1
      quality: 0.80
      confidence: 0.30
      mode: contain     # 'contain'|'cancel' — only valid when state == 0
      observed_at: "2026-04-23T00:00:00Z"
      valid_until:  "2026-05-01T00:00:00Z"

    - name: canon_alignment
      state: 1
      quality: 0.90
      confidence: 0.85
      observed_at: "2026-04-23T00:00:00Z"
```

Documents without `daenary:` index and behave exactly as before. The block is entirely additive.

**Daenary state values:**

| state | Meaning |
|-------|---------|
| `+1` | Affirmed — positive epistemic signal |
| `0` | Unresolved — observation exists, certainty withheld |
| `−1` | Negative — contradicted or deprecated |

`mode` (only when `state=0`): `contain` = deliberately unresolved; `cancel` = signals cancel out.

---

## Scoring Formulas

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

## LLM Integration

BOH connects to a local **Ollama** instance. No data leaves your machine.

**Supported task types:**

| Task | Output schema |
|------|---------------|
| `summarize_doc` | `{"summary": "..."}` |
| `review_doc` | `{"issues": [...], "suggestions": [...], "quality_score": 0.0–1.0}` |
| `extract_definitions` | `{"definitions": [{"term": "", "definition": ""}]}` |
| `propose_metadata_patch` | `{"proposed_patch": {...}, "reasoning": "..."}` |
| `explain_conflict` | `{"explanation": "", "resolution_suggestions": [...]}` |
| `query_corpus` | `{"answer": "", "confidence": 0.0–1.0, "sources": [...]}` |

**Review Queue flow:**

```
Ollama analyzes document
        ↓
Proposal placed in LLM Queue (status: pending)
        ↓
User reviews: title, summary, topics, type, related docs, conflicts
        ↓
User approves or rejects each item individually
        ↓
Approved fields applied to DB record (title, summary, topics, type)
        ↓
status=canonical and operator_state=release are NEVER applied from queue
```

---

## API Reference

### System

```
GET  /api/health                         Service health (phase, db, library path)
GET  /api/status                         Full system diagnostics
GET  /api/dashboard                      Health summary for UI
GET  /api/audit?limit=50                 Audit event log
```

### Library & Indexing

```
POST /api/index                          Index library from filesystem
GET  /api/autoindex/status               Auto-index state and last-run stats
POST /api/autoindex/run                  Trigger index run {library_root, max_files, changed_only}
GET  /api/docs                           Document list (paginated + filterable)
GET  /api/docs/{id}                      Document detail + definitions + events
GET  /api/docs/{id}/content              Raw markdown body
GET  /api/docs/{id}/related              Semantically related documents (scored)
GET  /api/docs/{id}/coordinates          Daenary dimensions
```

### Lifecycle (Phase 12)

```
GET  /api/lifecycle/{id}/history         Full lifecycle event log
GET  /api/lifecycle/{id}/can-backward    Check if backward movement is possible
POST /api/lifecycle/{id}/backward        Move one step backward {reason, actor}
POST /api/lifecycle/{id}/undo            Undo most recent change {actor}
GET  /api/workflow                       All documents and their Rubrix states
PATCH /api/workflow/{id}                 Forward lifecycle transition
```

### Canon & Conflicts

```
GET  /api/canon?topic=&plane=            Canon resolution
GET  /api/conflicts                      Open conflict list
PATCH /api/conflicts/{id}/acknowledge    Acknowledge a conflict
GET  /api/duplicates                     Content duplicate pairs
GET  /api/lineage                        All lineage records
GET  /api/lineage/{doc_id}               Doc-specific lineage
POST /api/lineage                        Manual lineage link
```

### LLM Queue (Phase 12)

```
GET  /api/llm/queue?status=pending       Review queue
GET  /api/llm/queue/count                Pending proposal count
POST /api/llm/queue                      Enqueue a proposal
POST /api/llm/queue/{id}/approve         Approve (safe fields only)
POST /api/llm/queue/{id}/reject          Reject (no document changes)
GET  /api/ollama/health                  Ollama availability
POST /api/ollama/invoke                  Invoke a task
GET  /api/ollama/invocations             Invocation history
```

### Search & Graph

```
GET  /api/search?q=                      FTS search with Daenary filters
GET  /api/graph?max_nodes=200            Atlas graph data
GET  /api/graph/neighborhood?doc_id=     Local neighborhood subgraph
POST /api/dcns/sync                      Rebuild DCNS edges
```

### Governance & Execution

```
GET  /api/governance/policies            Workspace policies
POST /api/governance/policy              Create/update policy
POST /api/exec/run                       Execute code block
GET  /api/exec/runs/{doc_id}             Execution history
```

### Content & Events

```
GET  /api/review/{path}                  LLM review artifact (non-authoritative)
GET  /api/events                         Event list
GET  /api/events/export.ics              ICS calendar export
GET  /api/nodes/{path}                   Planar facts
POST /api/nodes/{path}                   Store planar fact
GET  /api/planes                         Distinct plane paths
GET  /api/corpus/classes                 Corpus class distribution
POST /api/ingest/snapshot                Snapshot ingest (canon guard active)
```

Interactive docs: `http://127.0.0.1:8000/docs`

---

## Running Tests

```bash
python -m pytest tests/ -v
```

Phase 12 tests specifically:

```bash
python -m pytest tests/test_phase12.py -v
# 36 tests: lifecycle, autoindex, LLM queue, status API, backward/undo
```

---

## Project Structure

```
boh_v2/
├── app/
│   ├── api/
│   │   ├── main.py                FastAPI app factory + lifespan startup
│   │   ├── models.py              Pydantic request/response models
│   │   └── routes/
│   │       ├── autoindex_routes.py    Auto-index (Phase 12)
│   │       ├── authoring.py           Document editor
│   │       ├── canon.py               Canon resolution
│   │       ├── conflicts.py           Conflict management
│   │       ├── dashboard.py           Health summary
│   │       ├── events.py              Calendar events + ICS
│   │       ├── execution_routes.py    Code block execution
│   │       ├── governance_routes.py   Workspace policies
│   │       ├── index.py               Library indexer
│   │       ├── ingest.py              Snapshot ingest
│   │       ├── input_routes.py        Markdown/file/folder input
│   │       ├── lifecycle_routes.py    Lifecycle backward/undo/history (Phase 12)
│   │       ├── library.py             Document list
│   │       ├── lineage.py             Lineage records
│   │       ├── llm_queue_routes.py    LLM review queue (Phase 12)
│   │       ├── nodes.py               Planar nodes
│   │       ├── ollama_routes.py       Ollama invocation
│   │       ├── reader.py              Document content
│   │       ├── review.py              LLM review artifacts
│   │       ├── search.py              FTS + Daenary search
│   │       ├── status_routes.py       System diagnostics (Phase 12)
│   │       └── workflow.py            Rubrix transitions
│   │
│   ├── core/
│   │   ├── audit.py               Append-only audit log
│   │   ├── autoindex.py           Startup library scanner (Phase 12)
│   │   ├── canon.py               Canon scoring + resolution
│   │   ├── conflicts.py           3-pass conflict detection
│   │   ├── corpus.py              5-class deterministic classifier
│   │   ├── daenary.py             Epistemic state encoding
│   │   ├── dcns.py                Relationship edge graph
│   │   ├── execution.py           Code block execution
│   │   ├── governance.py          Workspace policy engine
│   │   ├── lifecycle.py           Lifecycle history + backward/undo (Phase 12)
│   │   ├── lineage.py             Lineage + duplicate/supersession
│   │   ├── llm_queue.py           LLM steward review queue (Phase 12)
│   │   ├── ollama.py              Ollama adapter + task dispatch
│   │   ├── planar.py              Planar fact scoring
│   │   ├── related.py             Related doc scoring + graph builder
│   │   ├── rubrix.py              Lifecycle ontology + validation
│   │   ├── search.py              FTS + composite scoring
│   │   └── snapshot.py            Snapshot ingest + canon guard
│   │
│   ├── db/
│   │   ├── connection.py          SQLite + migration-safe init
│   │   └── schema.sql             Base schema
│   │
│   ├── services/
│   │   ├── events.py              Event extraction
│   │   ├── indexer.py             Filesystem crawler + document indexer
│   │   ├── migration_report.py    Corpus migration reporter
│   │   ├── parser.py              Frontmatter + definition parser
│   │   └── reviewer.py            LLM review artifact builder
│   │
│   └── ui/
│       ├── app.js                 SPA logic (Phase 12)
│       ├── index.html             All panels
│       ├── style.css              Dark theme
│       └── vendor/                Local KaTeX + marked.js (no CDN)
│
├── docs/                          Math authority, route inventory, migration docs
├── library/                       Sample documents
├── tests/                         pytest suite (300+ tests, 15 files)
├── launcher.py                    Cross-platform desktop launcher
├── launcher.sh / launcher.bat     Platform launchers
├── requirements.txt               Python dependencies
└── boh.spec                       PyInstaller standalone build spec
```

---

## Database Schema

| Table | Purpose | Added |
|-------|---------|-------|
| `docs` | Document registry | v1 |
| `docs_fts` | FTS5 full-text index | v1 |
| `defs` | Extracted definitions | v1 |
| `plane_facts` | Planar math facts | v1 |
| `events` | Calendar events | v1 |
| `conflicts` | Conflict records | v1 |
| `lineage` | Lineage links | v2.1 |
| `doc_coordinates` | Daenary epistemic dimensions | v2.2 |
| `doc_edges` | DCNS relationship edges | v2.2 |
| `audit_log` | Append-only mutation history | v2.3 |
| `llm_invocations` | Ollama invocation records | v2.4 |
| `governance_policies` | Workspace access policies | v2.4 |
| `lifecycle_history` | Per-document lifecycle event log | **Phase 12** |
| `autoindex_state` | Auto-index run stats | **Phase 12** |
| `llm_review_queue` | LLM proposal review queue | **Phase 12** |
| `schema_version` | Migration history | v2.0 |

Schema migrations applied automatically on first run. No manual SQL required.

---

## DCNS Relationship Layer

| Edge type | State | Permeability |
|-----------|-------|-------------|
| `duplicate_content` | 0 | 0.95 |
| `supersedes` | +1 | 0.90 |
| `canon_relates_to` | +1 | 0.75 |
| `derives` | +1 | 0.80 |
| `conflicts` | −1 | 0.40 |

Sync: `POST /api/dcns/sync` — also runs automatically after a full library index.

---

## Building a Standalone Executable

```bash
pip install pyinstaller
pyinstaller boh.spec
./dist/boh/boh       # Linux/macOS
dist\boh\boh.exe     # Windows
```

---

## Phase History

| Phase | Summary |
|-------|---------|
| 1–3 | Core indexer, FTS search, canon resolution, conflict detection, Rubrix lifecycle, SPA shell |
| 4 | Corpus classification, lineage tracking, content duplicate detection |
| 5 | Cross-platform launcher with health check, full route coverage |
| 6 | ICS calendar export, corpus class UI, migration report generator |
| 7 | Atlas force-directed graph, document reader pane, KaTeX math rendering, local vendor libs |
| 8 | Daenary semantic state, DCNS edge graph, document drawer viewer, Daenary search filters, Atlas node diagnostic halos |
| 9 | Title/summary extraction, review repair, Daenary filter panel |
| 10 | Ollama LLM adapter, governance policies, code block execution, audit log |
| 11 | Input surface (markdown/upload/folder), Atlas edge fix for large corpora, related doc scoring improvements |
| **12** | **Lifecycle backward movement + undo + append-only history · Auto-index on startup · LLM steward review queue · `/api/status` diagnostics · Atlas zoom/pan/drag + performance presets · Batched edge rendering · Duplicate router registration fix** |

---

## Design Principle

**Constraint first. Not feature first.**

Built around:

- stewardship over storage
- clarity over convenience
- explicit governance over hidden automation
- reversible operations over destructive shortcuts
- institutional memory over temporary productivity

Every design decision in BOH bends toward one question:

*Can you trust what this system tells you?*

If the answer requires you to check manually, the design has failed.

The goal is **coherence**. Not novelty.

---

*Interactive API docs: `http://127.0.0.1:8000/docs`*
*Scoring formulas: `docs/math_authority.md`*
