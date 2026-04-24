# CURRENT_STATE_FILE_TREE.md
# Bag of Holding v2 — Current State After Phase 10 (Hardened)
# Tests: 444 passed, 2 skipped, 0 failed

## File Tree

```
boh_p10/
├── README.md
├── RUN_INSTRUCTIONS.md               ← Phase 10, 444 passed
├── CURRENT_STATE_FILE_TREE.md
├── app/
│   ├── api/
│   │   ├── main.py                   ← All routers registered; health phase:10
│   │   ├── models.py
│   │   └── routes/
│   │       ├── authoring.py          ← editor CRUD; save enforces write+canon+hash [Phase 10]
│   │       ├── canon.py
│   │       ├── conflicts.py          ← enriched with doc titles+paths [Phase 9]
│   │       ├── dashboard.py
│   │       ├── events.py
│   │       ├── execution_routes.py   ← run/runs/artifact; entity_type enforced [Phase 10]
│   │       ├── governance_routes.py  ← policies/check/edges/audit [Phase 10]
│   │       ├── index.py
│   │       ├── ingest.py
│   │       ├── library.py
│   │       ├── lineage.py
│   │       ├── nodes.py
│   │       ├── ollama_routes.py      ← health/models/tasks/invoke/invocations [Phase 10]
│   │       ├── reader.py             ← content/related/coordinates/graph/dcns-sync [Phase 7-8]
│   │       ├── review.py             ← GET (load/generate) + POST regenerate [Phase 9]
│   │       ├── search.py             ← + Daenary filter params [Phase 8]
│   │       └── workflow.py
│   ├── core/
│   │   ├── audit.py                  ← append-only audit log [Phase 10]
│   │   ├── authoring.py              ← draft CRUD; save via fs_boundary [Phase 10+hardened]
│   │   ├── canon.py
│   │   ├── conflicts.py
│   │   ├── corpus.py
│   │   ├── daenary.py                ← semantic state: validate/normalize/persist [Phase 8]
│   │   ├── dcns.py                   ← doc_edges: lineage+conflicts+canon edges [Phase 8]
│   │   ├── execution.py              ← Python/shell runner; denylist+scope+policy [Phase 10+hardened]
│   │   ├── fs_boundary.py            ← SINGLE WRITE GATE: traversal+canon+policy [Phase 10+hardened]
│   │   ├── governance.py             ← policies+system_edges; convergent authority [Phase 10+hardened]
│   │   ├── lineage.py
│   │   ├── ollama.py                 ← task-scoped Ollama adapter; scope enforced [Phase 10+hardened]
│   │   ├── planar.py
│   │   ├── related.py                ← related scoring + graph data builder [Phase 7-8]
│   │   ├── rubrix.py
│   │   ├── search.py                 ← + Daenary filter layer [Phase 8]
│   │   └── snapshot.py
│   ├── db/
│   │   ├── connection.py             ← schema v2.4.0; 7 Phase 10 tables migrated
│   │   └── schema.sql                ← 17 tables total
│   ├── services/
│   │   ├── events.py
│   │   ├── indexer.py                ← + title/summary/daenary/DCNS [Phase 9-10]
│   │   ├── migration_report.py
│   │   ├── parser.py                 ← parse_frontmatter_full() [Phase 8]
│   │   └── reviewer.py               ← load/exists/generate; enriched artifact [Phase 9]
│   └── ui/
│       ├── app.js                    ← v2-phase10; + Governance panel [Phase 10]
│       ├── index.html                ← 7 panels; ?v=10 [Phase 10]
│       ├── style.css                 ← Phase 10 governance panel styles
│       └── vendor/
│           ├── katex.min.js
│           ├── katex.min.css
│           ├── marked.min.js
│           └── fonts/
├── docs/
├── library/
├── tests/
│   ├── test_integration.py           ← 42 tests
│   ├── test_new_routes.py            ← 30 passed, 2 skipped
│   ├── test_phase4.py                ← 28 tests
│   ├── test_phase5.py                ← 23 tests
│   ├── test_phase6.py                ← 26 tests
│   ├── test_phase7.py                ← 38 passed, 1 skipped
│   ├── test_phase8.py                ← 70 tests
│   ├── test_phase9.py                ← 60 tests
│   ├── test_phase10.py               ← 123 tests (governance+hardening)
│   ├── test_canon_selection.py       ← 1 test
│   ├── test_conflict_detection.py    ← 1 test
│   └── test_rubrix_lifecycle.py      ← 1 test
├── launcher.py                       ← Phase 10 preflight check (14 files verified)
├── launcher.bat
└── launcher.sh
```

---

## Phase 10 Changes

### New core modules
- **`audit.py`** — `log_event()` / `get_events()`. Append-only. Wired into authoring, execution, LLM calls, policy changes.
- **`authoring.py`** — draft CRUD, title/summary editing, save-to-disk. Now routes all writes through `fs_boundary.safe_write_text()`.
- **`execution.py`** — Python + shell runner. Shell denylist, Python denylist, `_resolve_workspace()` (no path traversal), `_check_execute_permission()`, `can_execute` enforced. Workspace is `cwd` for all subprocesses.
- **`ollama.py`** — Task-scoped Ollama adapter. `_build_scoped_context()` constructs prompt from `scope.docs` / `scope.dirs` only. No raw filesystem access. `scope_enforced` field in response. All outputs: `non_authoritative: true`.
- **`governance.py`** — `workspace_policies` CRUD + `system_edges` DCNS. **Convergent authority model**: `upsert_policy()` syncs to `system_edges`; `get_effective_policy()` falls back through policy → edge → default. `check_permission()` returns `_source` field showing authority origin. Canon promotion hardcoded denied for models.
- **`fs_boundary.py`** — Single choke point for all filesystem writes. `assert_write_safe()` enforces: path traversal check, `canon/` directory block, DB-status canonical block, write-permission check. `safe_write_text()` wraps the full gate + audit log.

### New API routes
- `GET /api/editor/new` — blank document template
- `GET /api/editor/{doc_id}` — load doc into editor (returns `source_hash`)
- `PATCH /api/editor/{doc_id}` — update draft fields
- `POST /api/editor/{doc_id}/save` — save to disk (entity_type + source_hash params)
- `DELETE /api/editor/{doc_id}/draft` — discard draft
- `POST /api/editor/{doc_id}/summary/regenerate` — deterministic summary regeneration
- `POST /api/exec/run` — run Python or shell block (safety + permission enforced)
- `GET /api/exec/runs/{doc_id}` — list runs for doc
- `GET /api/exec/run/{run_id}` — full run + artifacts
- `GET /api/exec/artifact/{artifact_id}` — artifact content
- `GET /api/ollama/health` — Ollama availability
- `GET /api/ollama/models` — model list
- `GET /api/ollama/tasks` — valid task types
- `POST /api/ollama/invoke` — task-scoped invocation
- `GET /api/ollama/invocations` — invocation history
- `GET /api/ollama/invocation/{id}` — single invocation record
- `GET /api/governance/policies` — list workspace policies
- `GET /api/governance/policy/{workspace}` — effective policy for entity
- `POST /api/governance/policy` — create/update policy (auto-syncs to system_edges)
- `GET /api/governance/check` — permission check with `source` field
- `GET /api/governance/edges` — query system DCNS edges
- `POST /api/governance/edges` — add system DCNS edge
- `GET /api/audit` — query audit log

### New schema tables (Phase 10, schema v2.4.0)
- `doc_drafts` — in-memory document drafts before save
- `exec_runs` — every code block execution record
- `exec_artifacts` — outputs attached to runs
- `llm_invocations` — every Ollama call record
- `workspace_policies` — read/write/execute/propose/promote per entity
- `audit_log` — append-only governance audit trail
- `system_edges` — DCNS extended beyond documents (authority/flow edges)

### Hardening changes (from review)
1. **Canon protection centralized** — `authoring.assert_not_canon()` + `fs_boundary.is_protected_path()` + `is_canonical_doc()`. Three independent checks; any one blocks the write.
2. **Source hash conflict detection** — `load_editor` returns `source_hash`; `save_draft_to_disk` compares current file hash before writing. Divergence → HTTP 409.
3. **Execution sandboxed** — shell denylist (regex), Python denylist (regex), `_resolve_workspace()` (no root escape), `can_execute` policy check before any subprocess.
4. **LLM scope enforced** — `_build_scoped_context()` builds prompt from DB metadata for explicitly listed doc IDs / directory listings only. No filesystem access.
5. **DCNS/policy convergence** — `upsert_policy()` syncs to `system_edges`; `get_effective_policy()` falls through policy→edge→default; `check_permission()` exposes `_source`.
6. **DB as control plane** — `fs_boundary.py` is the single gate for all disk writes; all governance checks happen there before bytes hit the filesystem.

---

## Invariants (never violated)

| Invariant | Enforcement location |
|-----------|---------------------|
| Models cannot promote to canon | `governance.upsert_policy()` + `check_permission()` hardcode |
| Canonical docs cannot be overwritten | `fs_boundary.assert_write_safe()` + `authoring.assert_not_canon()` |
| `canon/` paths always write-protected | `fs_boundary.is_protected_path()` |
| Models cannot write by default | `governance.DEFAULTS["model"]["can_write"] = 0` |
| Models cannot execute by default | `governance.DEFAULTS["model"]["can_execute"] = 0` |
| All LLM outputs non-authoritative | `ollama.invoke()` always sets `non_authoritative: True` |
| All review artifacts non-authoritative | `reviewer.generate_review_artifact()` always sets flag |
| Execution timeout | `execution.EXEC_TIMEOUT_S = 30` |
| No raw filesystem access in LLM scope | `ollama._build_scoped_context()` uses DB only |
| No path traversal in execution | `execution._resolve_workspace()` + `fs_boundary` |
| Audit log is append-only | No DELETE on audit_log table; no route exposes deletion |

---

## Complete Route Table

| Method | Path | Phase |
|--------|------|-------|
| GET | /api/health | 5 |
| GET | /api/dashboard | 2 |
| POST | /api/index | 1 |
| GET | /api/search | 1+8 |
| GET | /api/canon | 1 |
| GET | /api/conflicts | 1+9 |
| PATCH | /api/conflicts/{id}/acknowledge | 2 |
| GET | /api/docs | 2 |
| GET | /api/docs/{id} | 1 |
| GET | /api/docs/{id}/content | 7 |
| GET | /api/docs/{id}/related | 7 |
| GET | /api/docs/{id}/coordinates | 8 |
| GET | /api/graph | 7+8 |
| POST | /api/dcns/sync | 8 |
| GET | /api/workflow | 1 |
| PATCH | /api/workflow/{id} | 2 |
| GET | /api/nodes/{path} | 1 |
| POST | /api/nodes/{path} | 1 |
| GET | /api/planes | 2 |
| GET | /api/events | 1 |
| GET | /api/events/export.ics | 1 |
| GET | /api/review/{path} | 1+9 |
| POST | /api/review/{path}/regenerate | 9 |
| POST | /api/ingest/snapshot | 2 |
| GET | /api/lineage | 4 |
| GET | /api/lineage/{doc_id} | 4 |
| POST | /api/lineage | 4 |
| GET | /api/duplicates | 4 |
| GET | /api/corpus/classes | 4 |
| POST | /api/corpus/reclassify | 4 |
| GET | /api/corpus/migration-report | 4 |
| POST | /api/corpus/migration-report | 4 |
| GET | /api/editor/new | **10** |
| GET | /api/editor/{doc_id} | **10** |
| PATCH | /api/editor/{doc_id} | **10** |
| POST | /api/editor/{doc_id}/save | **10** |
| DELETE | /api/editor/{doc_id}/draft | **10** |
| POST | /api/editor/{doc_id}/summary/regenerate | **10** |
| POST | /api/exec/run | **10** |
| GET | /api/exec/runs/{doc_id} | **10** |
| GET | /api/exec/run/{run_id} | **10** |
| GET | /api/exec/artifact/{artifact_id} | **10** |
| GET | /api/ollama/health | **10** |
| GET | /api/ollama/models | **10** |
| GET | /api/ollama/tasks | **10** |
| POST | /api/ollama/invoke | **10** |
| GET | /api/ollama/invocations | **10** |
| GET | /api/ollama/invocation/{id} | **10** |
| GET | /api/governance/policies | **10** |
| GET | /api/governance/policy/{workspace} | **10** |
| POST | /api/governance/policy | **10** |
| GET | /api/governance/check | **10** |
| GET | /api/governance/edges | **10** |
| POST | /api/governance/edges | **10** |
| GET | /api/audit | **10** |
