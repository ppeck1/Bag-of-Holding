# ROADMAP.md

This roadmap is restrained and must not be treated as implemented behavior.

## Implemented

### Retrieval roadmap L1–L6 — COMPLETE (2026-06-10 → 2026-06-11)

All six levels of the retrieval roadmap proposal (internal planning record) are implemented
and committed: **L1** document retrieval (pre-existing) · **L2** provenance retrieval (WO-R1
`e8006f4`: review_state/freshness/resolution_status pack blocks; intake evidence chain via WO-2)
· **WO-2** intake→retrieval bridge (migration `0002` applied to the real DB; pre-existing durable
handoffs backfilled; first governed promotion + exposure + demotion proven reversibly; commits
`99a6974`/`a83b4b7`/`65b36aa` + gate evidence) · **L5+L3** context-object assembler
(`/api/context-object`, WO-R2 `15f2db8`) · FTS hyphen hardening (`35fce2b`) · **L4** question-type
dispatch (WO-R3 `8bf20d4`) · **L6** fold-neighborhood retrieval (WO-R4 `3534505`, node scope over
the verified stored-edge vocabulary). Supporting hardening shipped along the way: mechanical
test-to-prod DB isolation (`eaec6da`), promoted-content exposure/mutation isolation, DEC-0002/3/4
governance. Remaining operational (separate gates): batch CANON promotion;
`boh_runtime_launch_origin_audit_v0_1` before production server validation/unattended use.

### Core platform
- Local FastAPI knowledge workbench (`app/api/`, `app/core/`).
- Server-owned library boundary (`BOH_LIBRARY`).
- Operator authorization (`BOH_OPERATOR_TOKEN`, dev-open when unset).
- Read-only retrieval token boundary (`BOH_RETRIEVAL_TOKEN`).
- Chunk-level retrieval and context packs (`/api/retrieve`).
- PlaneCard/domain bridge and Planar Gate metadata.
- Folded-node packet with scalar pressures, symbolic state, unknowns.
- Current Fold View (Phases 0-7b): scatter canvas, cluster/corpus aggregation engine, project/plane cluster routes.
- Governed ingestion and translation layer (Phases 1-8): adapter registry, discovery, preservation, normalization, interpretation, queryability, DB writer, API routes, replay, background scheduler.
- Intake orchestration integrity (WO-1, `boh_intake_orchestration_integrity_v0_1`) — **COMPLETE; Gate C4 CLOSED — PASS (2026-06-08)**. Idempotent/bounded/atomic/auditable/lifecycle-safe intake shared by all callers; migration `0001`; `BOH_INTAKE_IGNORE_PATTERNS`. Real corpus activation verified: the production DB holds the filtered corpus intake revisions ingested from the watch root (e.g. `<watch-root>`) plus synthetic/representative canary revisions; scheduler inert. The intake→retrieval bridge, originally left unwired here, was later delivered as WO-2 (see the retrieval section above). Gate evidence is kept in internal operational records.
- Scheduler operational hardening (WO-1.1, Phases A+B complete 2026-06-09): ledger-authoritative byte-binding, crash-safe registry reconciliation, root-overlap rejection, generation-safe stop/restart, deterministic adapter-registry fingerprint in revision identity, policy-binding consistency, strict replay vs explicit reprocess, scheduler status surface, fail-closed config validation. Phase C (scan-state caching, doc reconcile) optional and deferred.
- Versioned migration architecture: `init_db()` schema is the immutable `0000_baseline`; the `schema_migrations` ledger governs forward changes; migrations `0001` (intake orchestration integrity) and `0002` (intake→retrieval promotion ledgers) shipped.
- Metis retrieval contract v0.1 (citation_uri, source_spans, warnings on /api/retrieve).
- Demo library auto-seeding for first-run local dev.
- Governed work-order process scaffold (authority order, scoped rules, single active work order — maintained privately).

## Historical milestones (superseded arrangements, kept for context)

These entries describe earlier arrangements that later work replaced. They are recorded so the
delivery history reads coherently; none of them describe the current layout.

- **Governed UI built at `/v2/` (Phase A–C, 2026-06-01)** — build-free vanilla ES module SPA
  (component foundry, Fold Workspace with all 6 projections, Library/Review/Authority/Intake/
  Status/Activity screens wired to live endpoints), initially served alongside the classic UI
  at `/`. **Superseded 2026-06-02 by the root cutover:** the governed UI now serves `/` (with
  `/v2/` as a compatibility alias) and the classic UI is deprecated at `/classic`.
- **2026-06-02 session** — root cutover; CANON scalar bridge (drift_rate, entropy, delta_c_star,
  gamma, omega_viability, mismatch_gradient with graph/Fold parity); operator-token threading in
  the UI; backend why-current provenance rows; global search deep-link; Fold Phase 7c cluster UI;
  Context Pack Builder; route authority hardening + policy scanner.
- **WO-2 `boh_intake_retrieval_bridge_v0_1`** — drafted 2026-06-08 as a proposal, delivered
  2026-06-10/11 as part of the retrieval roadmap (migration `0002`, durable `intake_handoffs`,
  promotion ledger with adapter+policy snapshots, dual-gated `include_promoted` exposure,
  DEC-0003 era-convergent artifact identity). See "Retrieval roadmap L1–L6" above for the
  delivered form; the original proposal text is kept in internal records.

## Next (priority order)

1. Knowledge Health read model. Deterministic metrics from existing persisted tables only:
   duplication, orphan rate, canon drift/conflicts, retrieval confidence, evidence coverage,
   aging, and compression opportunities. No routes, no MCP surface, no mutation, and no automatic
   normalization. Findings should create review queues/proposals only after the read model is stable
   and separately authorized.
2. /v2 browser-interaction regression (Layer 3 checklist, internal record) — needs browser
   tooling (playwright) approval or a human session. Gates classic unmount.
3. Responsive / accessibility pass — narrow-screen drawers below 1280px (CSS + minimal JS
   for drawer state / focus / keyboard if required).
4. Classic UI unmount + archive — after browser interaction regression passes.

## Proposed next work orders — drafted, NOT authorized

- **WO-3 `boh_intake_historical_conversation_importer` (proposed; not yet drafted)** — supervised
  staging-folder ingestion of historical conversations into the governed intake substrate. Does NOT
  require an always-on watcher. Imports flow through intake + governed promotion only.
- **Persistent/background scheduler activation** — a SEPARATE branch of work (limited activation
  policy → editing-window test → soak test → enablement decision); today the scheduler is inert by
  default with manual, process-scoped activation only.
- **WO-1.1 Phase C** (scan-state caching + per-scan budget, doc reconcile) — optional, deferred.

  **Do not implement any of these without a separate explicit authorization.**

### Deferred follow-ups from the 2026-06-10 re-mint gate (recorded, NOT implemented)

- Explicit retention/cleanup policy for unreferenced filesystem duplicates under the data root
  (scan #1 of the re-mint gate wrote inert RAW/normalized copies under
  `<data-root>\01_RAW\<date>\` that no SQLite ledger row references — see DEC-0003;
  inert under the SQLite-authoritative rule, but they need a deliberate keep/prune decision).
- Document artifact-row dedup semantics (DEC-0003) in the intake layer docs so the next gate
  forecast models artifact rows as content-keyed, not per-ingest.

### Deferred follow-ups from WO-R1 (2026-06-10; recorded, NOT implemented)

- Promote `fold_metrics._parse_freshness_days` to a public shared helper (retrieval's `_freshness_for`
  intentionally reuses it cross-module to prevent fold/retrieval freshness drift; the private import
  is fragile against renames).
- Establish a retrieval query-count and latency baseline BEFORE WO-R2 context-object assembly
  (WO-R1 added 3 small indexed queries per document pack; the assembler must be measured against a
  recorded baseline, not anecdote).

### Deferred follow-ups from WO-1 closure (each its own future work order)

- Persistent/background scheduler activation policy (today: manual, process-scoped activation only).
- Explicit monotonic trace-event ordinal (don't rely on SQLite `rowid`/UUID for external ordering).
- UI/operator-doc clarification: HTML `safety_lane=hold` is an advisory tag, not a lifecycle hold.
- Later canary-retention review (synthetic + representative canary rows from the C3/C4 gates).
- Later snapshot-retention review (rollback snapshots retained from the gate sequence).

## Later

- Fold Phase 8: 2.5D/3D Spatial Lab (parked — no committed design).
- Retrieval quality evaluation expansion.
- mismatch_gradient governing-spec confirmation (mapping currently PROVISIONAL).

## Parked

- Dependency changes.
- New conceptual governance layers beyond current spec.
- Compiler/DSL integration.
