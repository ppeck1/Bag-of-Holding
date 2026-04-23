# RUN_INSTRUCTIONS.md
# Bag of Holding v2 — Phase 8 Run Instructions

## Prerequisites

- Python 3.11 or 3.12
- pip

---

## Quickstart (recommended)

```bash
cd boh_v2
pip install -r requirements.txt
python launcher.py
```

The launcher runs a Phase 8 preflight check, starts the server, waits until it is ready, and opens your browser at `http://127.0.0.1:8000`.

---

## Manual start (development)

```bash
cd boh_v2
pip install -r requirements.txt
python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000 --reload
```

Then open: `http://127.0.0.1:8000`

---

## Platform launchers

**Windows:** Double-click `launcher.bat`

**macOS / Linux:**
```bash
chmod +x launcher.sh
./launcher.sh
```

---

## Launcher options

```
python launcher.py --port 9000          # custom port
python launcher.py --library /my/notes  # set library root
python launcher.py --db /my/boh.db      # set database path
python launcher.py --no-browser         # headless / server-only
python launcher.py --reload             # hot-reload (dev mode)
```

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BOH_LIBRARY` | `./library` | Path to the markdown library to index |
| `BOH_DB` | `boh.db` | Path to the SQLite database file |

```bash
BOH_LIBRARY=/my/notes BOH_DB=/my/notes/boh.db python launcher.py
```

---

## First use — index your library

**Via the UI:**
1. Click **Import / Ingest** in the left nav
2. Enter your library folder path in the *Index Filesystem Library* section
3. Click **Index Library**

After indexing completes, DCNS edges are synced automatically. You can also sync manually via **`POST /api/dcns/sync`**.

**Via API:**
```bash
curl -X POST http://127.0.0.1:8000/api/index \
  -H "Content-Type: application/json" \
  -d '{"library_root": "./library"}'
```

---

## Confirming Phase 8 is running

Three quick checks:

```bash
# 1. Health endpoint — should include "phase": 8
curl http://127.0.0.1:8000/api/health

# 2. New Phase 8 routes
curl http://127.0.0.1:8000/api/docs/<doc_id>/coordinates
curl -X POST http://127.0.0.1:8000/api/dcns/sync

# 3. Browser console
# Open DevTools → Console — should print:
# 📦 Bag of Holding v2-phase8  (in green)
```

---

## Run the test suite

```bash
cd boh_v2
python -m pytest tests/ -v
```

**Expected: 261 passed, 2 skipped, 0 failed**

| File | Tests | Notes |
|------|-------|-------|
| `test_integration.py` | 42 | Core v0P behaviors |
| `test_new_routes.py` | 32 | Phase 2 routes (2 skipped) |
| `test_phase4.py` | 28 | Corpus classification + lineage |
| `test_phase5.py` | 23 | Launcher + health + all routes |
| `test_phase6.py` | 26 | ICS, corpus UI, migration report |
| `test_phase7.py` | 39 | Atlas, reader, graph (1 skipped) |
| `test_phase8.py` | 70 | Daenary, DCNS, search filters, drawer viewer |
| `test_canon_selection.py` | 1 | Canon stub |
| `test_conflict_detection.py` | 1 | Conflict stub |
| `test_rubrix_lifecycle.py` | 1 | Rubrix stub |

---

## Service health check

```bash
curl http://127.0.0.1:8000/api/health
# {"status":"ok","version":"2.0.0","phase":8,"db":"connected","library":"./library"}
```

---

## API reference

Full interactive docs: `http://127.0.0.1:8000/docs`

### Key calls

```bash
# Index library
curl -X POST http://127.0.0.1:8000/api/index \
  -H "Content-Type: application/json" \
  -d '{"library_root": "./library"}'

# Search with Daenary filters
curl "http://127.0.0.1:8000/api/search?q=planar&uncertain_only=true"
curl "http://127.0.0.1:8000/api/search?q=canon&min_confidence=0.7"
curl "http://127.0.0.1:8000/api/search?q=model&stale=true"

# Daenary coordinates for a document
curl http://127.0.0.1:8000/api/docs/<doc_id>/coordinates

# DCNS edge sync
curl -X POST http://127.0.0.1:8000/api/dcns/sync

# Atlas graph data
curl http://127.0.0.1:8000/api/graph

# Canon resolution
curl "http://127.0.0.1:8000/api/canon?topic=planar+math"

# List conflicts
curl http://127.0.0.1:8000/api/conflicts

# Acknowledge a conflict
curl -X PATCH http://127.0.0.1:8000/api/conflicts/1/acknowledge

# Browse documents
curl "http://127.0.0.1:8000/api/docs?status=canonical&page=1&per_page=20"

# Document content (markdown body, frontmatter stripped)
curl http://127.0.0.1:8000/api/docs/<doc_id>/content

# Related documents
curl http://127.0.0.1:8000/api/docs/<doc_id>/related

# All lineage records
curl http://127.0.0.1:8000/api/lineage

# Workflow transition
curl -X PATCH http://127.0.0.1:8000/api/workflow/<doc_id> \
  -H "Content-Type: application/json" \
  -d '{"operator_state": "vessel", "operator_intent": "triage"}'

# ICS calendar export
curl http://127.0.0.1:8000/api/events/export.ics -o events.ics

# Migration report
curl -X POST http://127.0.0.1:8000/api/corpus/migration-report

# Snapshot ingest
curl -X POST http://127.0.0.1:8000/api/ingest/snapshot \
  -H "Content-Type: application/json" \
  -d '{"path": "/absolute/path/to/boh_export_run.json"}'

# Store a planar fact
curl -X POST http://127.0.0.1:8000/api/nodes/core.planar.coherence \
  -H "Content-Type: application/json" \
  -d '{"r": 1.0, "d": 1, "q": 0.9, "c": 0.8}'
```

---

## Document format

### Minimal (boh: only)

```markdown
---
boh:
  id: my-doc-001
  type: note
  purpose: My first document
  topics: [example, test]
  status: draft
  version: "0.1.0"
  updated: "2024-01-01T00:00:00Z"
  scope:
    plane_scope: []
    field_scope: []
    node_scope: []
  rubrix:
    operator_state: observe
    operator_intent: capture
---

# My Document

Content goes here.
```

### With Daenary semantic state (Phase 8)

```markdown
---
boh:
  id: my-doc-002
  # ... standard fields ...

daenary:
  dimensions:
    - name: relevance
      state: 0
      quality: 0.8
      confidence: 0.3
      mode: contain
      observed_at: "2026-04-23T00:00:00Z"
      valid_until: "2026-05-01T00:00:00Z"

    - name: canon_alignment
      state: 1
      quality: 0.9
      confidence: 0.85
      observed_at: "2026-04-23T00:00:00Z"
---
```

### Valid field values

| Field | Valid values |
|-------|-------------|
| `type` | `note`, `canon`, `reference`, `log`, `event`, `person`, `ledger`, `project` |
| `status` | `draft`, `working`, `canonical`, `archived` |
| `operator_state` | `observe`, `vessel`, `constraint`, `integrate`, `release` |
| `operator_intent` | `capture`, `triage`, `define`, `extract`, `reconcile`, `refactor`, `canonize`, `archive` |
| `daenary.state` | `-1`, `0`, `1` |
| `daenary.mode` | `contain`, `cancel` (only when `state == 0`) |

---

## Build a standalone executable (optional)

```bash
pip install pyinstaller
pyinstaller boh.spec
# Output: dist/boh/boh  (Linux/Mac) or dist/boh/boh.exe (Windows)
./dist/boh/boh
```
