# RUN_INSTRUCTIONS.md
# Bag of Holding v2 — Phase 10 (Governed Cognitive Workbench)

## Prerequisites

Python 3.11 or 3.12, pip. Optional: Ollama for local model integration.

---

## Quickstart

```bash
cd boh_p10
pip install -r requirements.txt
python launcher.py
```

Opens at `http://127.0.0.1:8000`.

**Windows:** `launcher.bat`  
**macOS/Linux:** `chmod +x launcher.sh && ./launcher.sh`

---

## Launcher options

```bash
python launcher.py --port 9000
python launcher.py --library /my/notes
python launcher.py --db /my/notes/boh.db
python launcher.py --no-browser
python launcher.py --reload
```

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BOH_LIBRARY` | `./library` | Path to the markdown library |
| `BOH_DB` | `boh.db` | SQLite database path |
| `BOH_OLLAMA_URL` | `http://localhost:11434` | Ollama endpoint |
| `BOH_OLLAMA_MODEL` | `llama3.2` | Default Ollama model |

---

## Confirming Phase 10 is running

```bash
curl http://127.0.0.1:8000/api/health
# {"status":"ok","version":"2.0.0","phase":10,...}

# Browser console (DevTools → Console):
# 📦 Bag of Holding v2-phase10
```

---

## Run the test suite

```bash
cd boh_p10
python -m pytest tests/ -v
```

**Expected: 444 passed, 2 skipped, 0 failed**

| File | Tests | Notes |
|------|-------|-------|
| test_integration.py | 42 | Core v0P behaviors |
| test_new_routes.py | 32 | Phase 2 routes (2 skipped) |
| test_phase4.py | 28 | Corpus + lineage |
| test_phase5.py | 23 | Launcher + all routes |
| test_phase6.py | 26 | ICS, corpus UI, migration |
| test_phase7.py | 39 | Atlas, reader, graph (1 skipped) |
| test_phase8.py | 70 | Daenary, DCNS, search |
| test_phase9.py | 60 | Title/summary, review repair |
| test_phase10.py | 123 | Governance, execution, Ollama, fs_boundary |
| stubs (3 files) | 3 | Canon, conflict, Rubrix stubs |

---

## Governance rules in effect

### Canon protection (hardcoded — cannot be overridden)
- Documents with `status: canonical` cannot be saved over by any entity
- Paths inside `canon/` directories are always write-protected
- Models (`entity_type: model`) can never be granted `can_promote`
- These checks are enforced at `fs_boundary.assert_write_safe()` and `authoring.assert_not_canon()`

### Default permissions by entity type
| Entity | Read | Write | Execute | Propose | Promote |
|--------|------|-------|---------|---------|---------|
| human | ✓ | ✓ | ✓ | ✓ | ✓ |
| model | ✓ | ✗ | ✗ | ✓ | ✗ (always) |
| system | ✓ | ✓ | ✓ | ✓ | ✗ |

### Permission resolution order
1. Specific policy row (`workspace_policies`)
2. Wildcard policy row (`*`)
3. `system_edges`: `may-*` edges for entity → workspace
4. System defaults

`check_permission()` always returns a `source` field showing where the authority came from.

### DCNS + policy convergence
`upsert_policy()` automatically syncs granted permissions into `system_edges` as `may-*` edges.
`get_effective_policy()` falls back to `system_edges` when no policy row exists.
The two systems are coherent — they share the same authority model.

---

## Using Ollama

```bash
# Start Ollama with a model
ollama pull llama3.2
ollama serve

# Check availability
curl http://127.0.0.1:8000/api/ollama/health

# Run a task-scoped invocation
curl -X POST http://127.0.0.1:8000/api/ollama/invoke \
  -H "Content-Type: application/json" \
  -d '{"task_type":"summarize_doc","content":"...","scope":{"docs":["doc-id-1"]}}'
```

All outputs are `non_authoritative: true`. Scope enforcement: only documents listed in `scope.docs` are passed to the model.

### Supported task types
`summarize_doc`, `review_doc`, `extract_definitions`, `propose_metadata_patch`, `generate_code`, `explain_conflict`, `query_corpus`

---

## Using the document editor

```bash
# Load a document into the editor (returns source_hash)
GET /api/editor/{doc_id}

# Update the draft
PATCH /api/editor/{doc_id}
{"body_text": "...", "title": "...", "frontmatter_json": "..."}

# Save to disk (pass source_hash to detect external changes)
POST /api/editor/{doc_id}/save?source_hash=<hash_from_load>

# Discard without saving
DELETE /api/editor/{doc_id}/draft
```

---

## Running code blocks

```bash
POST /api/exec/run
{
  "doc_id": "my-doc",
  "block_id": "block-1",
  "language": "python",    # or "shell"
  "code": "print('hello')",
  "entity_type": "human",
  "entity_id": "*"
}
```

Enforced before execution:
1. Language must be `python` or `shell`
2. Code checked against denylist (`rm -rf`, `sudo`, `os.system()`, etc.)
3. Entity must have `can_execute` on the workspace
4. Workspace path must be inside `BOH_LIBRARY` (no path traversal)

---

## Managing workspace policies

```bash
# List all policies
GET /api/governance/policies

# Add a policy (model with read + propose, no write/execute/promote)
POST /api/governance/policy
{
  "workspace": "research/",
  "entity_type": "model",
  "entity_id": "llama3.2",
  "can_read": 1, "can_write": 0,
  "can_execute": 0, "can_propose": 1, "can_promote": 0
}

# Check a specific permission
GET /api/governance/check?workspace=research/&entity_type=model&permission=can_write

# Query system DCNS edges
GET /api/governance/edges?source_type=model&source_id=llama3.2
```

---

## Audit log

```bash
# All recent events
GET /api/audit

# Filter by event type
GET /api/audit?event_type=run&limit=20

# Filter by document
GET /api/audit?doc_id=<doc_id>
```

Audit log is append-only. Events: `index`, `edit`, `save`, `run`, `llm_call`, `promote`, `conflict`, `policy`.

---

## Document format

### Standard `boh:` frontmatter (required)

```yaml
---
boh:
  id: my-doc-001
  type: note      # note|canon|notebook|reference|log|event
  purpose: Purpose string
  topics: [topic-a, topic-b]
  status: draft   # draft|working|canonical|archived
  version: "0.1.0"
  updated: "2026-04-23T00:00:00Z"
  scope:
    plane_scope: []
    field_scope: []
    node_scope: []
  rubrix:
    operator_state: observe
    operator_intent: capture
---
```

### Executable notebook type

Use `type: notebook` for executable documents. Blocks are tracked with `block_id` and run via `POST /api/exec/run`.

### Daenary semantic state (additive)

```yaml
daenary:
  dimensions:
    - name: relevance
      state: 0        # -1 | 0 | +1
      quality: 0.80
      confidence: 0.30
      mode: contain   # only when state=0
      valid_until: "2026-05-01T00:00:00Z"
```

---

## Build a standalone executable

```bash
pip install pyinstaller
pyinstaller boh.spec
./dist/boh/boh
```
