# BOH Project Variable and Wiring Map

This map records the current source-level wiring for Bag of Holding. It focuses on runtime variables, request headers, storage surfaces, API routers, data tables, and known gaps. It is not a promise that every experimental panel is product-complete; it is a map of what the code currently exposes.

## Runtime Environment Variables

| Variable | Default | Read By | Purpose | Wired |
| --- | --- | --- | --- | --- |
| `BOH_LIBRARY` | `./library` | `app.core.fs_boundary`, `app.core.autoindex`, routes, launcher | Server-owned document library root. Filesystem reads/writes are expected to resolve under this root. | Yes |
| `BOH_DB` | `boh.db` | `app.db.connection`, launcher | SQLite database file path. | Yes |
| `BOH_OPERATOR_TOKEN` | unset | `app.core.auth` | Local privileged mutation/admin/execution boundary. Sent as `X-BOH-Operator-Token`. | Yes |
| `BOH_RETRIEVAL_TOKEN` | unset | `app.core.retrieval` | Separate read-only connector boundary for `/api/retrieve` and `/api/context-object`. Sent as `X-BOH-Retrieval-Token`. Fail-closed: routes return 403 when the variable is unset. | Yes |
| `BOH_RETRIEVAL_INCLUDE_PROMOTED` | `false` | `app.core.promoted_exposure` | Server half of the WO-2 dual exposure gate for promoted intake docs (`corpus_class = 'CORPUS_CLASS:PROMOTED_INTAKE'`). Only the literal value `true` (case-insensitive) opens the gate. Retrieval surfaces (`/api/retrieve`, `/api/context-object`) additionally require the per-request `include_promoted` flag — env AND request, fail-closed. Other read surfaces are env-gate-only. Mutation isolation of promoted docs is gate-independent. | Yes |
| `BOH_DEFAULT_ACTOR` | `local_operator` fallback | `app.core.actor_ledger` | Default actor identity when `X-BOH-Actor-ID` is not supplied. | Yes |
| `BOH_CORS_ORIGINS` | localhost allowlist | `app.api.main` | Comma-separated CORS origin override. | Yes |
| `BOH_AUTO_INDEX` | `false` | `app.core.autoindex`, startup lifespan | Enables background startup auto-index. | Yes |
| `BOH_AUTO_INDEX_MAX_FILES` | `5000` | `app.core.autoindex` | Caps startup/autoindex scan size. | Yes |
| `BOH_DETERMINISTIC_REVIEW_ON_INDEX` | `true` | `app.core.autoindex`, `app.core.document_analysis_pipeline` | Runs deterministic analysis/review during indexing unless false. | Yes |
| `BOH_LLM_REVIEW_ON_INDEX` | `false` | `app.core.autoindex`, `app.core.document_analysis_pipeline` | Enables LLM review on index when true. | Yes |
| `BOH_ANALYZE_ON_INDEX` | `false` | `app.core.autoindex`, `app.core.document_analysis_pipeline` | Umbrella flag for analysis on index. | Yes |
| `BOH_OLLAMA_ENABLED` | unset/false | `app.core.ollama`, `app.api.routes.ollama_routes` | Gates Ollama invocation. Health/model listing remains readable. | Yes |
| `BOH_OLLAMA_URL` | `http://localhost:11434` | `app.core.ollama` | Ollama base URL. | Yes |
| `BOH_OLLAMA_MODEL` | `llama3.2` | `app.core.ollama` | Default Ollama model. | Yes |
| `BOH_OLLAMA_MAX_CONTENT` | `20000` | `app.core.ollama`, `app.core.document_analysis_pipeline`, routes | Max characters sent to Ollama. | Yes |
| `BOH_EXEC_ALLOWED_COMMANDS` | `python,python3,py,echo,ls,pwd` | `app.core.execution` | Allowlist for legacy shell execution path. Operator auth and actor authority are still required. | Yes |

Notes:
- Strings such as `BOH_CANON_v3.7`, `BOH_PATCH_v2.19`, and `BOH_WORKER_v4` appear in ontology labels or provenance metadata. They are not runtime environment variables.
- `BOH_RETRIEVAL_TOKEN` is intentionally separate from `BOH_OPERATOR_TOKEN`. Connectors should never receive the operator token.

## HTTP Headers

| Header | Used By | Purpose | Required For |
| --- | --- | --- | --- |
| `X-BOH-Operator-Token` | `app.core.auth.require_operator` | Privileged local authorization. | Admin, reset, seed, execution, governance mutation, approvals, destructive/workflow mutations. |
| `X-BOH-Actor-ID` | Actor-aware routes and ledger helpers | Attribution identity recorded in the actor authority ledger. | Actor-scoped mutation attribution; defaults to `local_operator` in many paths. |
| `X-BOH-Retrieval-Token` | `app.core.retrieval.require_retrieval_token` | Read-only retrieval connector authorization. | `GET/POST /api/retrieve`, `GET/POST /api/context-object`. |
| `Content-Type: application/json` | FastAPI/Pydantic request models | JSON body parsing. | JSON POST/PATCH endpoints. |

CORS currently allows `Content-Type`, `Authorization`, `X-Request-ID`, `X-BOH-Operator-Token`, `X-BOH-Actor-ID`, and `X-BOH-Retrieval-Token`.

## Launcher Arguments

| Argument | Default | Effect |
| --- | --- | --- |
| `--host` | `127.0.0.1` | Uvicorn bind host. |
| `--port` | `8000` | Uvicorn bind port. Launcher now checks whether the port is already in use before spawning the server. |
| `--library` | unset | Overrides `BOH_LIBRARY` for the launched process. |
| `--db` | unset | Overrides `BOH_DB` for the launched process. |
| `--reload` | false | Enables uvicorn reload mode for development. |
| `--no-browser` | false | Skips opening a browser automatically. |

## Browser-Side State Variables

| Key / Constant | Storage | Purpose | Wired |
| --- | --- | --- | --- |
| `BOH_VERSION` | JS constant | UI build/debug marker. Current value: `phase28.4-acceptance-repro-ui-hardening`. | Yes |
| `boh_operator_token` | `sessionStorage` | Per-tab operator token used by protected UI calls. | Yes |
| `boh_actor_id` | `sessionStorage` | Per-tab actor ID, usually `local_operator`. | Yes |
| `boh_active_library_root` | `sessionStorage` | UI-visible active library root hint. Server still owns the actual boundary. | Yes |
| `boh_ui_mode` | `localStorage` | Simple/advanced UI mode. | Yes |
| `boh_onboarding_dismissed` | `localStorage` | Hides onboarding card. | Yes |
| `boh_drawer_width` | `localStorage` | Document drawer width. | Yes |
| `boh_drawer_mode` | `sessionStorage` | Rendered/source drawer mode. | Yes |
| `boh_daenary_filters` | `localStorage` | Persisted Daenary search filters. | Yes |
| `atlas_reader_width` / `boh_atlas_reader_width` | `localStorage` | Atlas reader sizing. | Partially overlapping keys; both appear in UI code. |
| `boh_v2_phase_a` | `localStorage` | `/v2` app shell settings (density, mode, landing, diagnostics, `activeLibraryId`). Parsed in `app/ui2/js/app.js` `loadSettings()`. | Yes |

### `/v2` in-memory app state (`app/ui2/js/app.js` `state` object)

These are not persisted to storage; they reset on page load.

| Key | Default | Purpose |
|-----|---------|---------|
| `route` | `loadSettings().landing` | Current screen hash (`current`, `library`, `fold`, etc.) |
| `selection` | `null` | Inspector selection: `null` or object with `type` (one of `metric`, `doc`, `card`, `intake_capability`, `quarantine_record`, `duplicate_pair`, `audit_event`, `review_conflict`, `review_proposal`, `review_approval`, `review_queue`, `authority_integrity`, `authority_ledger`, `authority_gate`, `authority_residence`) and type-specific data fields (e.g., `{ type: "doc", doc }`, `{ type: "review_conflict", conflict }`) |
| `inspectorOpen` | `true` | Whether the Inspector panel is visible (`‹` collapse button clears it) |
| `inspectorWidth` | `320` | Inspector panel width in px (user-resizable via drag handle, min 240 max 700; resize disabled below 1280px where the panel becomes a fixed overlay) |
| `visiblePlanes` | all 8 plane keys | Plane-visibility browsing filter (`informational`…`archive`). Toggled by the TopBar `Planes:` popover. Filters Library PlaneCards tab and Fold node visibility ONLY. Does **not** affect retrieval, authority, intake, canon, or backend permissions. |
| `libraries` | `{ status: "idle", items: [{ id: "all", name: "All libraries", count: 0 }] }` | Cached `/api/libraries` response for the top-bar logical-library selector. |
| `libraryManagerOpen` | `false` | Whether the `/v2` Manage libraries modal is open. |
| `libraryManager` | `{ status: "idle", items: [] }` | Cached `/api/libraries?include_hidden=true` response for editing display labels, hidden state, and dropdown order. |
| `activeLibraryId` | `loadSettings().activeLibraryId || "all"` | Logical-library browsing selector. Applied by the Library screen to `/api/docs`, `/api/search`, and `/api/planes/cards`, and by the Fold Workspace to fold/graph reads; it is not retrieval ranking, intake, promotion, status, authority, or governance-context scope. |
| `overview` | `{ status: "idle" }` | Cached overview fetch state |
| `statusData` | `{ status: "idle" }` | Cached status fetch state |
| `fold` | `{ status: "idle" }` | Cached fold-graph fetch state |
| `pendingSearch` | `null` | Query pre-filled from TopBar global search (deep-link to Library) |

`state.scope` was **removed** (2026-06-09, commit `15219ef`). The prototype global "Scope: Project Atlas" selector and its fixture tree (`FX.scopeTree`) are gone. The TopBar now exposes a logical-library selector whose default is `Library: All libraries` plus the `Planes:` filter. The logical-library selector is browsing-only for Library and Fold Workspace views; internal/backend scope concepts (authority, retrieval ranking, intake, promotion, status, governance context) are unaffected. `Manage libraries` edits presentation metadata only: display label, hidden-from-dropdown state, order, and reset.

`normalizePlaneKey(p)` is exported from `app/ui2/js/ns.js` and used by `app.js`, `screens/library.js`, and `screens/fold.js` to compare `c.plane` / `node.plane` against `visiblePlanes` case-insensitively.

Not wired:
- There is no browser-side retrieval token field yet.
- There is no dedicated retrieval UI panel yet. Retrieval is API-first.
- `inspectorOpen`, `inspectorWidth`, `visiblePlanes`, and `libraries` are session-only (in-memory); they reset to defaults on page load.

## Filesystem Boundary Variables

| Name | Module | Meaning |
| --- | --- | --- |
| `get_library_root()` | `app.core.fs_boundary` | Resolves server-owned `BOH_LIBRARY`. |
| `normalize_library_relative_path(path_or_rel)` | `app.core.fs_boundary` | Rejects empty paths, NULs, Windows drive escapes, absolute paths, and `..` traversal. |
| `resolve_under_library(path_or_rel, library_root=None)` | `app.core.fs_boundary` | Resolves a library-relative path under the approved library root and rejects escape. |
| `ensure_request_root_allowed(request_root, library_root=None)` | `app.core.fs_boundary` | Allows omitted root or subdirectories under `BOH_LIBRARY`; rejects external roots. |
| `safe_write_text`, `safe_mkdir` | `app.core.fs_boundary` | Write helpers with governance/audit checks. |

Wired:
- Document content reads, review artifact writes, import staging, workspace reset, and index/root validation use the boundary helpers in the hardened paths.

Watch points:
- Future filesystem features should use `resolve_under_library` or a deliberately introduced staging-root resolver. Do not reintroduce `Path(doc["path"])` absolute-path trust.

## API Router Wiring

Routers are registered in `app.api.main` before the static UI mount. Current router families:

| Router | Prefix | Main Role | Operator Protected |
| --- | --- | --- | --- |
| `index.router` | `/api` | Library indexing. | Boundary protected; arbitrary external roots rejected. |
| `search.router` | `/api` | Document-level search. | Read-only. |
| `retrieval_router` | `/api` | Read-only LLM context packs. | Uses retrieval token, not operator token. |
| `library.router` | `/api` | List/read docs; patch metadata. | Metadata patch protected. |
| `libraries.router` | `/api/libraries` | Logical-library list derived from indexed `docs.path` values inside `BOH_LIBRARY`, plus operator-gated presentation overrides for dropdown label, visibility, order, and reset. | Mutations require operator token. |
| `reader.router` | `/api` | Document content, related docs, graph data, folded-node packets. | Read-only content path is boundary resolved; folded packets do not mutate PlaneCards. |
| `input_routes.router` | `/api/input` | Markdown/file/folder input and demo seeds. | Demo seed protected; uploads bounded to library. |
| `autoindex_routes.router` | `/api` | Autoindex status/run/report. | Run uses library boundary; reporting is read-only. |
| `workspace_router` | `/api/workspace` | Clean/reset/seed/activity/analysis health. | Reset/seed mutations protected. |
| `workflow.router`, `lifecycle_routes.router` | `/api` | Rubrix transitions, backward, undo, history. | Mutating transitions protected. |
| `governance_routes.router` | `/api` | Policies, system edges, governance resolve, audit. | Mutations protected. |
| `actor_router` | `/api` | Actors, grants, responsibility, attribution, ledger. | Mutations protected. |
| `execution_routes.router` | `/api` | Code/shell execution and artifacts. | Execution protected by operator token plus actor authority. |
| `approval_routes.router` | `/api/governance/approve` | Promotion/supersede/patch/edge approval workflow. | Mutations protected. |
| `certificate_router` | explicit `/api/...` paths | Certificate request/review/application. | Mutations protected. |
| `ollama_routes.router` | `/api` | Ollama health/models/tasks/invoke/toggle. | Invocation gated by env; toggle route exists. |
| `llm_queue_routes.router` | `/api` | LLM proposal queue and approve/reject. | Enqueue/approve/reject protected; queue reads are read-only. |
| `canon`, `conflicts`, `lineage` | `/api` | Canon resolution, conflicts, lineage. | Manual lineage/duplicate decisions protected. |
| `events`, `nodes`, `dashboard`, `status_routes` | `/api` | Read-oriented diagnostics and exports. | Mostly read-only. |
| `review.router` | `/api` | Review artifact status/regeneration. | Review artifacts must stay under library. |
| `ingest.router` | `/api` | Snapshot ingest. | Protected. |
| `plane_router`, `doc_card_router` | `/api/planes`, `/api/docs` | PlaneCards and card backfill. | Some mutations/backfill exposed. |
| Planar Storage bridge | `/api/planes/*`, `/api/retrieve` | Passive source wrapping, plane registry, storage trace events, subjective LLM cards, fail-closed authority decisions, governed retrieval modes, and experimental Planar Gate metadata. | Patches 1-3 wired for core/retrieval/fixtures; correction ledger routes/UI not yet wired. |
| `fold_router` | `/api/fold` | Current Fold View: CurrentFoldPacket resolver (`GET /api/fold/node/{doc_id}`), full-trace stub (`GET /api/fold/node/{doc_id}/trace`, `available:false`), batch scatter summary (`GET /api/fold/library`), and read-only cluster/corpus aggregation routes (`GET /api/fold/cluster/{axis}/{value}`, `GET /api/fold/corpus/{axis}`). | Read-only; no operator token required. |
| `lattice`, `feedback`, `coherence`, `temporal`, `authority`, `escalation`, `integrity`, `substrate`, `governance_metrics` | varied | Experimental/advanced governance and lattice surfaces. | Mixed; mutation surfaces should remain protected. |

## Retrieval Wiring

| Variable / Field | Source | Meaning |
| --- | --- | --- |
| `chunk_id` | `app.core.retrieval._chunk_id` | Stable ID based on doc ID, text hash, chunk index, heading, and text prefix. |
| `doc_id` | Indexer/frontmatter contract | Owning document ID. |
| `heading_path` | Markdown heading stack | Human-readable chunk context. |
| `byte_start`, `byte_end` | Chunk builder | UTF-8 byte span in the extracted body. |
| `token_start`, `token_end` | Chunk builder | Lightweight token offsets based on local term parsing. |
| `source_hash`, `text_hash` | Metadata contract/indexer | Source and extracted text hashes. |
| `chunk_type` | Chunk builder | `frontmatter`, `heading`, `body`, `table`, or `link`. |
| `text` | Chunk builder | Extracted chunk text. |
| `lifecycle_state` | Inherited from document operator state | Rubrix lifecycle signal. |
| `authority_state` | Inherited from metadata contract | Governance authority signal. |
| `status`, `canonical_layer` | Inherited from metadata contract | Canon/status metadata. |
| `embedding_model` | `boh-local-hash-embedding-v1` | Deterministic local hashed embedding model name. |
| `dimensions` | `64` | Local embedding vector size. |
| `vector_json` | `doc_chunk_embeddings` | Stored local embedding vector. |

Retrieval response context-pack fields:
- `chunk_id`
- `doc_id`
- `title`
- `path`
- `snippet`
- `text`
- `source_span`
- `heading_path`
- `chunk_type`
- `lifecycle_state`
- `authority_state`
- `status`
- `canonical_layer`
- `provenance`
- `conflicts`
- `lineage`
- `citation`
- `warnings`
- `do_not_treat_as_canonical`
- `score`
- `why_selected`

Retrieval response gate fields:
- `planar_context_pack.context_pack_id`
- `planar_context_pack.query`
- `planar_context_pack.operation`
- `planar_context_pack.actor_id`
- `planar_context_pack.mode`
- `planar_context_pack.candidate_refs`
- `planar_context_pack.expected_planes`
- `planar_context_pack.retrieved_planes`
- `planar_context_pack.missing_planes`
- `gate_result.gate_result_id`
- `gate_result.posture`
- `gate_result.blocking_reasons`
- `gate_result.warning_reasons`
- `gate_result.allowed_context_refs`
- `gate_result.withheld_context_refs`
- `gate_result.required_route`
- `gate_result.trace_event_type`
- `gate_result.l6_proposal_allowed`
- `gate_result.l6_proposal_types`
- `gate_result.context_allowed_basis`

Ranking components:
- FTS5 BM25 over `doc_chunks_fts`
- local hash embedding similarity
- lexical fallback
- metadata filters
- lineage expansion
- canon score weighting
- authority weighting
- conflict penalty
- bounded context budget via `max_context_chars`

Not wired yet:
- Neural embeddings or vector database.
- Retrieval UI panel.
- External MCP/plugin connector package.
- Automatic backfill job for chunks on old databases; reindexing documents populates chunks.

## Planar Gate and Correction Ledger Wiring

Core modules:
- `app.core.context_pack`: deterministic `ContextPack` builder, operation-to-expected-plane aliases, candidate refs.
- `app.core.planar_gate`: deterministic `GateResult` evaluator and expected-vs-actual comparison.
- `app.core.correction_ledger`: audited correction record helpers. Approval records ledger/canon/residence objects only; it does not mutate runtime gate rules.
- `app.core.planar_fixtures`: loads the extracted atlas fixture pack, adapts fixture PlaneCards into retrieval-like packs, evaluates every fixture, and can emit `MistakeEvent` records on mismatch.

Fixture source:
- `tests/fixtures/planar_storage_v0_3_self_correction.json` is mechanically extracted from `planar_storage_flow_atlas_v1_10_5_6_display_no_loss.html`.
- It currently contains 25 fixture cases, 13 fixture PlaneCards, 1 MistakeEvent, 1 PatchProposal, 1 CanonChangeRecord, and 3 InformationResidenceMap entries.

Not wired yet:
- No `/api/planar/*` routes are registered yet.
- No Planar Gate UI panel is exposed yet.
- Fixture success only validates deterministic gate behavior. It does not prove classification quality, reviewer agreement, calibration stability, production readiness, or active self-improvement.

## Demo Wiring

The public demo surface is consolidated:
- `POST /api/input/demo-seed` is the single protected demo entrypoint.
- It seeds governance/refusal examples and Daenary epistemic-state examples.
- It is intended to make the main capability surfaces visibly non-empty: Library, Search, Visualization, Custodian Layer, Domains, and System Status.
- It returns `capability_surfaces[]` and `next_steps[]` so the UI can display what the demo proves and where to look next.
- It does not fabricate LLM proposal queue entries; the Proposed Changes panel becomes meaningful after an authenticated LLM enqueue or Ollama invocation.
- The previous separate epistemic-seed route/button is removed from the public API/UI surface.

Demo remains a local mutation and requires `X-BOH-Operator-Token`.

UI wiring:
- `app.ui.index.html`: single `Load Demo Project` button in the Inbox start toolbar.
- `app.ui.app.loadDemoProject`: calls `/api/input/demo-seed`, displays total created items, per-section counts, `capability_surfaces`, and the first `next_steps`.

Demo response fields:
- `ok`
- `project`
- `created`
- `items`
- `sections.governance_failure_cases`
- `sections.daenary_epistemic_demo`
- `errors`
- `includes_failure_cases`
- `includes_daenary_epistemic_state`
- `capability_surfaces[].surface`
- `capability_surfaces[].what_to_check`
- `capability_surfaces[].route_hint`
- `next_steps[]`
- `note`

Runtime data:
- Demo documents are written under managed library subfolders, not committed source fixtures.
- The source tree does not track `library/`; demo output should remain runtime state.

## UI Asset Wiring

Favicons:
- Source location: `app/ui/assets/favicons/`
- Active HTML links: `app/ui/index.html`
- Original runtime handoff zip noted by user: `library/boh_favicon_pack.zip`
- The zip remains runtime/library material and should not be committed from `library/`.

## Graph Lab and Current Fold View

### Graph Lab (formerly Visualization)

The user-facing "Visualization" label was renamed to **Graph Lab** in Current Fold View Phase 0. Internal route names (`atlas`, `/api/graph`, etc.) are unchanged.

Current Graph Lab is graph-first with a two-layer selected-node reader:
- **Fold Snapshot** (new, from `CurrentFoldPacket`) — resolver-computed currentness label, 4 key pressure bars, unknowns count, and resolver metadata. Loaded from `GET /api/fold/node/{doc_id}`.
- **Folded-node facet packet** (existing) — source, lifecycle, authority, provenance, conflict, chunk, PlaneCard, retrieval gate, audit facets. Loaded from `GET /api/docs/{doc_id}/fold`.

Display model:
- Canvas role: topology and neighborhoods.
- Fold Snapshot role: what is current and why, resolver-provided.
- Folded-node role: local document structure and governance facets.
- Reader role: full document rendering.

Nav item renamed: `aria-label="Visualization"` → `aria-label="Graph Lab"`, nav text `Visualization` → `Graph Lab`.
No internal routes, panel IDs, or JS function names were renamed.

### Current Fold View (Phases 0-5)

Resolver contract and wiring (implemented 2026-05-28):

| Layer | Module | Responsibility |
| --- | --- | --- |
| Folded packet | `app.core.folded_node.build_folded_node_packet` | Structural and document facts (unchanged) |
| Metric context loader | `app.core.fold_metrics.FoldMetricContextLoader` | DB lookups for scalar inputs (isolated boundary) |
| Scalar computation | `app.core.fold_metrics.compute_fold_scalar_state` | 10 dimensional pressures [0.0, 1.0] — not truth scores |
| Symbolic projection | `app.core.fold_metrics.project_symbolic_state` | Human-readable labels from scalar + policy; no DB access |
| Adapter | `app.core.current_fold.adapt_folded_node_to_current_fold` | Packet normalization, unknown registration, compact trace |
| Canonical resolver | `app.core.current_fold.current_fold_from_folded_node` | Four-step entry point; returns None for missing docs |

Scalar fields (all clamped to [0.0, 1.0], never truth scores):
- `authority_score`, `freshness_score`, `evidence_strength`, `conflict_pressure`
- `interpretability`, `queryability`, `canon_readiness`, `drift_risk`
- `resolution_confidence`, `blast_radius`

Symbolic labels (precedence-ordered):
`quarantined` > `held` > `superseded` > `conflicted` > `stale` > `unknown` > `current_but_contested` > `draft_current` > `current`

Policy versions:
- `FoldMetricPolicy.v0.1` — freshness priority: epistemic_last_evaluated → updated_ts; lineage cap: 5 hops
- `DefaultFoldSymbolicPolicy.v0_1` — contested threshold: 0.35; authority minimum: 0.30; stale threshold: 0.25

Compact trace — frozen at 6 events:
1. `authority_state_checked`
2. `supersession_checked`
3. `conflicts_checked`
4. `freshness_checked`
5. `intake_capability_checked`
6. `scalar_state_computed` (collapsed by default)

FoldUnknown fields: `field`, `severity`, `meaning`, `blocks_currentness`, `blocks_canon_eligibility`, `blocks_queryability`, `resolution_action`.

API routes:
- `GET /api/fold/node/{doc_id}` → `CurrentFoldPacket` (resolver-backed)
- `GET /api/fold/node/{doc_id}/trace` → full trace stub (`available: false`, deferred to a later buildspec)
- `GET /api/fold/library` → batch scatter summary (simplified per-doc scoring: `authority_score`, `freshness_score`, `conflict_pressure`, `canon_readiness`, `currentness_label`; `limit` defaults 500, capped at 2000)
- `GET /api/fold/cluster/{axis}/{value}` → aggregate fold packet for supported axes
- `GET /api/fold/corpus/{axis}` → aggregate corpus packet for a supported axis
- `GET /api/fold/cluster/{axis}/{value}/trace` → cluster trace stub/compact aggregate trace surface

Scale actions (Phase 6, additive read-only):
- `CurrentFoldPacket.scale_actions: list[FoldScaleAction]` — declarative, navigation-only roll-up affordances; never imply a mutation.
- `FoldScaleAction` fields: `label`, `target_scale`, `target_axis`, `target_id`, `allowed`, `reason`, `filter`. `as_dict()` omits `reason`/`filter` when None.
- `target_id` uses the deterministic `"{axis}:{value}"` form (e.g. `project:boh`, `plane:authority`, `domain:clinical`). Built by `_build_node_scale_actions(base_packet)` from packet axis values plus read-only domain linkage.
- Node-scale axes: `project` (allowed when `docs.project` present), `plane` (allowed when a PlaneCard or `canonical_layer` resolves), `domain` (allowed only when exactly one registered domain token resolves from the doc/card topic linkage; disallowed with a clear reason when none or multiple resolve). Cluster endpoints consume the deterministic `target_id` axes for project/plane/domain and expose diagnostic-only batch behavior where source linkage is incomplete.

UI:
- `app.ui.index.html#reader-fold-snapshot` — Fold Snapshot shown above folded-node panel
- `app.ui.app.renderFoldSnapshot` — fetches and renders the Fold Snapshot
- `app.ui.app.loadFoldView` — Fold View fixture panel lookup by doc_id
- `app.ui.index.html#panel-fold-view` — standalone Fold View nav panel (fixture access)
- `app.ui2.js.screens.fold.FoldWorkspace` — `/v2#fold` SVG workspace over `/api/fold/library`, `/api/graph/projection`, `/api/fold/node/{id}`, and existing cluster/corpus routes; project and linked-domain folds use `/api/fold/cluster/{axis}/{value}` when selected.
- `app.ui2.js.api.fetchFoldGraph` — client-side join/normalization of fold library rows, graph projection nodes, and read-only domain corpus/cluster packets; preserves existing semantic fields when present but does not invent backend CANON values.

Implemented (Phase 6):
- `scale_actions[]` on the node packet (see above). Pure additive field; no aggregation.

Implemented (Phase 7a) — `app.core.fold_aggregation` (pure, read-only; internal/test-only — NO routes, NO UI, NO schema/migration, NO DB writes; exercised by `tests/test_fold_aggregation.py`):
- Entry points: `aggregate_cluster(axis, value, members: list[FoldMemberInput]) -> AggregateFoldPacket`, `aggregate_corpus(axis, clusters) -> AggregateFoldPacket`. Scope helpers: `cluster_scope_id(axis, value)` → `"{axis}:{value}"`, `corpus_scope_id(axis)` → `"corpus:{axis}"`.
- Types: `FoldAggregateScope(scale, scope_id, axis, axis_value)`, `FoldMemberInput(node_packet, axis_value)`, `FoldContributor(scope_id, authority_score, weight, included, excluded_reason)`, `AggregateFoldPacket` (`as_dict()`).
- Module constants: `CLUSTER_LABEL_PRECEDENCE` (9), `EXCLUSION_REASONS` (6), `SCALAR_PRESSURES` (10), `AGGREGATE_TRACE_EVENTS` (6).
- Dual-channel rollup (`method="dual_channel_v1"`). Label channel (`label_channel="worst_case_precedence"`) = worst-case over the frozen node 9-label order `quarantined > held > superseded > conflicted > stale > unknown > current_but_contested > draft_current > current`; tie-break = lowest `scope_id` lexicographically; sees excluded members. The buildspec-invented `expired`/`advisory` are NOT emitted. Numeric channel (`numeric_channel="authority_weighted_mean"`) = per-pressure `Σ(w_i·S_i)/Σ w_i` (weight = member `authority_score`); equal-weight fallback when `Σ weights == 0` (`numeric_fallback_used=true`); rounded 3 dp; clamped `[0,1]`; `scores_are_truth_values=false`.
- Exclusion is numeric-only. Reason enum: `quarantined, held, preserved_only, missing_axis_value, superseded, expired_validity` (currentness `quarantined`/`held`/`superseded` → same reason; intake `preserved_not_interpreted` → `preserved_only`).
- `aggregation` object fields: `method`, `label_channel`, `numeric_channel`, `inputs_count`, `included_count`, `excluded_count`, `excluded_reasons` (sorted), `label_driver` ({scope_id,label} or null), `numeric_fallback_used`, `diagnostic_only`. Invariant `inputs_count == included_count + excluded_count`.
- NULL-axis nodes are not counted and register `cluster_membership_ambiguous`. All-excluded → null numeric pressures + `numeric_channel_no_included_members`. Empty cluster → `currentness_label="unknown"`, null pressures, zeroed counts, `empty_cluster`. Batch axis → `aggregation.diagnostic_only=true`. `canon_eligible` never surfaces true at aggregate scale. Aggregate compact trace frozen at 6 events: `cluster_membership_resolved, members_loaded, label_precedence_applied, numeric_rollup_computed, exclusions_recorded, aggregate_state_emitted`.
- Accepted spec: `docs/specs/fold_phase7a_aggregation_acceptance_spec.md`.

Implemented (Phase 7b):
- `app.api.routes.fold_routes` exposes read-only cluster/corpus aggregation routes: `GET /api/fold/cluster/{axis}/{value}`, `GET /api/fold/corpus/{axis}`, and `GET /api/fold/cluster/{axis}/{value}/trace`.
- Project, plane, and domain axes are operational. Domain linkage is read-only and deterministic: registered values from `substrate_lattice_registry.domain` are matched against `docs.topics_tokens`, PlaneCard `topic`, and PlaneCard payload `topics`. Batch remains diagnostic-only and derives membership from intake capability source references.

Implemented (Phase 7c):
- `/v2#fold` creates project cluster nodes client-side and linked-domain fold nodes from `/api/fold/corpus/domain` plus `/api/fold/cluster/domain/{value}`. The View toolkit exposes a `Folds` segmented control for project/domain grouping. Member nodes hide while collapsed, expand at their measured projection coordinates, load aggregate cluster packets for the cluster inspector, and support double-click expand/collapse.

Implemented (Fold Workspace usability 0.1, 2026-06-22):
- Projection coordinates are split from overlays: Web keeps topology, Risk Map plots risk pressure vs readiness gap, Authority Path uses authority/state lanes, Evidence State uses plane/evidence lanes, Currentness Map plots authority vs freshness, and Timeline uses time/evidence lanes.
- Expanded cluster members are displayed at measured projection coordinates instead of synthetic radial/ring positions around the opened cluster anchor.
- The view toolkit stores session-scoped label mode, edge mode, fold axis, Cluster Focus, and toolkit-open preferences in `boh_fold_view_v1`.
- Canvas/List/Actions views now include an Action Queue for conflicted, stale, unknown, review-marked, or high-risk nodes.
- Fold Workspace domain visuals (2026-06-23): the same toolkit now stores `clusterAxis` (`project` by default, `domain` optional). Domain fold nodes are created only when existing domain cluster packets report linked document contributors; empty registered domains are not visualized.

Deferred (remaining Fold View work):
- 2.5D/3D Spatial Lab placeholder (8), full resolver trace endpoint depth, and backend-backed batch corpus UX beyond diagnostic surfaces.
- Full trace stub returns `available: false`; compact trace is in the main packet.
- Multi-axis cluster identity remains `scope_id = "{axis}:{value}"`; aggregate rollups keep dual-channel semantics (worst-case label precedence + authority-weighted numeric mean, equal-weight fallback). See `docs/current_fold_view_phased_variable_map.md` and `docs/specs/boh_current_fold_view_v0_3_phase6plus_cluster_aggregation_buildspec.md`.

Still rough:
- The Fold Snapshot is shown in the reader pane, not literally unfolded inside the canvas node.
- No pinning or multi-node comparison exists yet.
- The endpoint composes existing DB state and does not read source file content.

## Database Storage Map

Core document/index tables:
- `docs`
- `docs_fts`
- `doc_chunks`
- `doc_chunks_fts`
- `doc_chunk_embeddings`
- `defs`
- `doc_drafts`

Governance and lifecycle tables:
- `audit_log`
- `governance_events`
- `workspace_policies`
- `system_edges`
- `approval_requests`
- `edge_approval_requests`
- `provenance_artifacts`
- `certificates`
- `lifecycle_history` (created/migrated in connection code)
- `canonical_locks`

Actor authority ledger tables:
- `actors`
- `actor_aliases`
- `actor_roles`
- `authority_grants`
- `responsibility_assignments`
- `action_ledger`
- `document_attribution`
- `contact_imports`

Corpus relationship and analysis tables:
- `conflicts`
- `lineage`
- `events`
- `doc_coordinates`
- `doc_edges`
- `plane_facts`
- `planes`
- `plane_cards` / `cards`
- `storage_events`
- `plane_interfaces`
- `planar_gate_results`
- `planar_mistake_events`
- `planar_patch_proposals`
- `planar_canon_change_records`
- `planar_information_residence_map`
- `planar_fixture_cases`

Execution and LLM tables:
- `exec_runs`
- `exec_artifacts`
- `llm_invocations`
- `llm_review_queue` (created/migrated in connection code)

Advanced lattice/governance tables:
- `lattice_events`
- `lattice_edges`
- `feedback_rewrites`
- `coherence_refresh_events`
- `coherence_scores`
- `anchor_events`
- `open_items`
- `authority_resolution_log`
- `authority_promotions`
- `escalation_registry`
- `escalation_events`
- `substrate_lattice_registry`
- `sc3_violations`
- `schema_version`
- `system_config`
  - `logical_library_overrides_v1` stores operator-managed logical-library display overrides as JSON. It does not move files or rewrite `docs.path`.

## Import and Indexing Flow

1. UI uploads or creates content through `/api/input/*`, or the operator triggers indexing through `/api/index` or `/api/autoindex/run`.
2. Path/root requests are normalized against `BOH_LIBRARY`; external roots are rejected by default.
3. `app.services.indexer.index_file` parses frontmatter, extracts/normalizes content, computes hashes, validates metadata, and upserts `docs` plus `docs_fts`.
4. The indexer rebuilds retrieval chunks through `app.core.retrieval.replace_doc_chunks`.
5. Retrieval chunk data is inserted into `doc_chunks`, `doc_chunks_fts`, and `doc_chunk_embeddings`.
6. The indexer records definitions, coordinates, lineage, duplicate/supersession relationships, activity, and optional analysis depending on flags.

## Authority Flow

1. Privileged HTTP request includes `X-BOH-Operator-Token`.
2. `require_operator` verifies the token against `BOH_OPERATOR_TOKEN`; unset config fails closed.
3. Actor-aware routes read `X-BOH-Actor-ID` or default to `local_operator`.
4. Phase 28 actor authority checks evaluate whether the actor has the required grant.
5. Successful mutations record audit/action ledger entries where implemented.

Not wired:
- There is no multi-user session login system.
- The operator token is local process configuration, not a remote identity provider.

## LLM and Retrieval Boundary

LLM proposal path:
- Ollama invocation is gated by `BOH_OLLAMA_ENABLED=true`.
- LLM outputs are written as proposals/review artifacts and should not directly promote canon.
- Review queue enqueue, approval, and rejection are operator protected because they mutate persistent queue, ledger, and attribution state.
- No narrower write-capable LLM connector role exists yet.

LLM retrieval path:
- `/api/retrieve` is read-only.
- It requires `BOH_RETRIEVAL_TOKEN`, not `BOH_OPERATOR_TOKEN`.
- It returns bounded context with citations and authority/canon warnings.

Not wired:
- Retrieval does not mutate lifecycle, authority, canon, files, or DB governance state.
- Retrieval does not execute code.
- Retrieval does not issue approvals.
- There is no external connector role that can enqueue LLM proposals without the operator token.

Planar Storage bridge path:
- Existing sources stay in `docs` and on disk.
- A source can be wrapped as a PlaneCard without rewriting the source.
- `planes` records the stable plane vocabulary.
- `storage_events` records source registration, card wrapping/update, candidate creation, LLM output recording, and future retrieval/promotion/interface events as they are wired.
- LLM output is stored as `plane=subjective`, `card_type=llm_synthesis`, and `non_authoritative=true`.
- `app.core.planar_authority` provides pure fail-closed `can_use`, `can_promote`, and `can_translate` decisions with visible reasons and required actions.
- `/api/retrieve` accepts `mode` and applies eligibility filtering. Strict mode excludes subjective/non-authoritative material; exploration can include it with warnings; audit mode returns storage trace context.

## Current Known Gaps

Retrieval:
- Local hashed embeddings are implemented; neural embeddings are not.
- No vector database or ANN index exists yet.
- No dedicated browser retrieval UI exists yet.
- No connector package exists yet for another program; the HTTP API is ready for one.
- Planar Storage retrieval modes are wired. Card promotion endpoints and enforced interface receipts are not fully wired yet.

Documentation/UI:
- README still describes some advanced surfaces at a high level; this map is the more precise wiring view.
- Some advanced route families are experimental and may be more "available API" than polished workflow.

Runtime cleanup:
- `.pytest_cache` may remain on Windows if the OS denies deletion. It is ignored runtime cache.

Security posture:
- The first filesystem/operator/retrieval boundaries are in place.
- New write, import, execution, or connector routes should be reviewed against `fs_boundary`, `require_operator`, actor grants, and retrieval-token separation before merging.

## Intake Scheduler Environment Variables (Phase 8)

| Variable | Default | Read By | Purpose | Wired |
| --- | --- | --- | --- | --- |
| `BOH_DATA_ROOT` | unset | `app.services.intake.*` | Root for preserved/normalized intake artifacts. Required for preservation, normalization, and interpretation; `PreservationConfigError` when unset. | Yes |
| `BOH_INTAKE_SCHEDULER_ENABLED` | `false` | `app.services.intake.scheduler_manager` | Enables the managed background scan loop (disabled by default). | Yes |
| `BOH_WATCH_PATH` | unset | `app.services.intake.scheduler_manager` | **Single directory** to watch when the scheduler is enabled (not colon-separated). | Yes |
| `BOH_INTAKE_SCAN_INTERVAL` | `30` (s) | `app.services.intake.scheduler_manager` | Seconds between scans. Validated `1–86400`. | Yes |
| `BOH_INTAKE_BACKPRESSURE_MAX` | `10` | `app.services.intake.scheduler_manager` | Max queued-plus-running intake work (bounded cap). Validated `1–4096`. | Yes |
| `BOH_INTAKE_IGNORE_PATTERNS` | unset | `app.services.intake.scheduler_manager` | Comma-separated discovery ignore patterns (fnmatch), added to the built-in defaults; **no-op when unset/blank**. Keeps generated/non-authoritative files (e.g. a SQLite index) out of the intake ledger. When watching a real corpus, keep `BOH_WATCH_PATH` (e.g. `<watch-root>`) and `BOH_INTAKE_IGNORE_PATTERNS` paired so the ingested set stays stable. Validated at start: set-but-no-valid-patterns fails closed. | Yes |
| `BOH_INTAKE_DRAIN_TIMEOUT` | `30` (s) | `app.services.intake.scheduler_manager` | Bounded drain timeout for `stop()`. Validated `0.001–3600`. | Yes |

**Scheduler config validation (Phase B item 4):** `start_if_enabled` fails closed before worker startup on an invalid `BOH_INTAKE_SCAN_INTERVAL` (range `1–86400`), `BOH_INTAKE_BACKPRESSURE_MAX` (range `1–4096`), `BOH_INTAKE_DRAIN_TIMEOUT` (range `0.001–3600`), malformed `BOH_INTAKE_IGNORE_PATTERNS`, an absent/nondeterministic adapter fingerprint, inconsistent policy binding, or an unsafe/uncreatable/unwritable/overlapping watch/data/library/DB layout — each surfaced as a structured `state="error"` + `last_error` on `/api/status`.

## New UI (/v2/) Browser-Side State Variables

| Key | Storage | Purpose |
| --- | --- | --- |
| `boh_v2_phase_a` | `localStorage` | Settings persisted by the new governed UI (density, mode, landing, diagnostics, active logical library). |
| `boh_fold_cam_v1` | `sessionStorage` | Fold Workspace camera state (zoom, pan, projection) — persists across tab navigation. |
| `boh_fold_view_v1` | `sessionStorage` | Fold Workspace view preferences: label mode, edge mode, fold axis, Cluster Focus, and toolkit-open state. |

## New UI (/v2/) Route Map

The new governed UI at `/v2/` is served as a vanilla ES module SPA from `app/ui2/`. Routes are hash-based:

| Hash | Screen | Primary data endpoints |
| --- | --- | --- |
| `#current` | Current State / Overview | `/api/dashboard`, `/api/coherence/summary`, `/api/docs`, `/api/status` |
| `#fold` | Fold Workspace | `/api/fold/library`, `/api/graph/projection`, `/api/fold/node/{id}`, `/api/fold/cluster/project/{value}` |
| `#library` | Library | `/api/libraries`, `/api/docs`, `/api/search`, `/api/planes/cards` |
| `#review` | Review Center | `/api/conflicts`, `/api/llm/queue`, `/api/approvals`, `/api/review-queue` |
| `#authority` | Authority & Audit | `/api/integrity/dashboard`, `/api/authority/*`, `/api/trace/log`, `/api/residence/*` |
| `#intake` | Capture & Intake | `/api/input/recent`, `/api/intake/capabilities`, `/api/quarantine`, `/api/duplicates` |
| `#settings` | Settings | `localStorage` + `/api/status` |
| `#status` | Status | `/api/status` |
| `#log` | Activity Log | `/api/audit` |
