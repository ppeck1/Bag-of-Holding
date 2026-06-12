# BOH Current Fold View — Phased Variable and Wiring Map

Status: **mixed implementation record + forward plan** (updated 2026-05-29).

- Phases 0-5 (node-level read model) are COMPLETE.
- Phase 6 (additive node-level `scale_actions[]`) is COMPLETE.
- Phase 7a (cluster aggregation engine) is IMPLEMENTED as a pure, read-only internal module
  (no routes/UI/schema/DB writes), tested by `tests/test_fold_aggregation.py`.
- Phases 7b, 7c, and 8 are DEFERRED (authored design only; no application code).

This guide is both a wiring map for what is implemented and a forward reference for the
authored-but-deferred cluster/corpus/spatial design. Each section is explicitly labelled
CURRENT (implemented and, where noted, tested) or PLANNED (deferred design from the
buildspec). Treat PLANNED sections as a contract for a future work order, not as
shipped behavior.

Source of truth (verified for this map on 2026-05-29):
- `app/core/current_fold.py` — `CurrentFoldPacket`, `FoldScope`, `FoldUnknown`, `FoldScaleAction`, adapter, resolver.
- `app/core/fold_metrics.py` — policies, metric context loader, scalar computation, symbolic projection.
- `app/api/routes/fold_routes.py` — `/api/fold/node/{doc_id}`, `/trace`, `/library`.
- `app/core/folded_node.py` — `build_folded_node_packet` (structural facts input).
- `app/api/main.py` — `fold_router` registration.
- Verified state and test baseline — maintained in the private working repository's state snapshot.

Buildspec (the phase plan):
- `docs/specs/boh_current_fold_view_v0_3_phase6plus_cluster_aggregation_buildspec.md` — status `accepted_for_phase6`; defines cluster identity, aggregation, plane registry, and the Phase 6-9 plan. Its `target_spec` (`BOH-CURRENT-FOLD-VIEW-SCALAR-FRACTAL-BUILDSPEC-v0.3`) and patches 001/002 are referenced as provenance but are not present as files in `docs/specs/`.

Cross-reference `docs/project_variable_map.md` for the full current wiring baseline and
`docs/intake_layer_phased_variable_map.md` for the parallel intake-layer phase map (this
guide follows that format).

---

## Phase Legend

| Phase | Name | Status | Tests |
|---|---|---|---|
| Phase 0 | Graph Lab rename + scaffold | COMPLETE | — |
| Phase 1-5 | Node-level `CurrentFoldPacket` (resolver, scalars, symbolic, trace, unknowns) | COMPLETE | `test_current_fold_packet.py`, `test_folded_node_packet.py` |
| Phase 5 (UI) | Fold Snapshot + library scatter canvas | COMPLETE | `test_fold_view_ui.py` |
| Phase 6 | Node-level `scale_actions[]` (additive) | COMPLETE | see Phase 6 acceptance |
| Phase 7a | Cluster aggregation engine (`app/core/fold_aggregation.py`) | IMPLEMENTED | accepted acceptance spec + `tests/test_fold_aggregation.py` (31 tests) |
| Phase 7b | Cluster + corpus routes | DEFERRED (designed) | planned |
| Phase 7c | Cluster fold UI | DEFERRED (designed) | planned |
| Phase 8 | 2.5D/3D spatial placeholder only | DEFERRED (designed) | planned |
| Phase 9 | Tests + regression lock | DEFERRED (designed) | planned |

Note on numbering: the private state snapshot groups the shipped node-level work as "Phases 0-5"
and labels later work "Phases 6-8 deferred." The accepted buildspec refines that into
Phase 6 (scale actions, now done) plus Phases 7a-9. Both views agree on what is and is
not implemented; this guide uses the buildspec numbering.

---

## Phase 0 — Graph Lab rename + scaffold (CURRENT, COMPLETE)

No resolver behavior. UI-label and surface scaffolding only.

| Item | Where | Note |
|---|---|---|
| "Visualization" → "Graph Lab" label | `app/ui/index.html` (`aria-label`, nav text) | Internal route names (`atlas`, `/api/graph`) unchanged. |
| Fold Snapshot placement | `app/ui/index.html#reader-fold-snapshot` | Shown above the existing folded-node panel. |

No internal routes, panel IDs, or JS function names were renamed in this phase.

---

## Phases 1-5 — Node-level CurrentFoldPacket (CURRENT, COMPLETE)

**Scope:** the resolver read model that answers "what is current and why" for a single
document. Read-only. Composes existing DB state; does not read source file content.

### Modules and responsibilities

| Layer | Module / symbol | Responsibility |
|---|---|---|
| Structural facts | `app.core.folded_node.build_folded_node_packet` | Document + facet packet (source, lifecycle, authority, provenance, conflicts, chunks, plane_card, planar_gate, audit). Unchanged input. |
| Metric context loader | `app.core.fold_metrics.FoldMetricContextLoader` | Isolated DB lookups producing `FoldMetricContext` (edges, conflicts, supersession, lineage depth, freshness age, intake capability, epistemic). |
| Scalar computation | `app.core.fold_metrics.compute_fold_scalar_state` | Ten dimensional pressures in `[0.0, 1.0]`. Pure; no DB access. |
| Symbolic projection | `app.core.fold_metrics.project_symbolic_state` | Human-readable labels from scalar + policy. No DB access. |
| Adapter | `app.core.current_fold.adapt_folded_node_to_current_fold` | Assembles `CurrentFoldPacket`; registers unknowns; builds compact trace and scale actions. No DB access. |
| Canonical resolver | `app.core.current_fold.current_fold_from_folded_node` | Four-step entry point. Returns `None` for missing docs; degraded packet (with unknowns) on partial inputs. |

### Versioning constants (`current_fold.py`)

| Constant | Value |
|---|---|
| `schema_version` | `CurrentFoldPacket.v0.3` |
| `resolver_version` | `CurrentFoldResolver.v0.1` |
| `projection_version` | `DefaultFoldSymbolicPolicy.v0_1` |
| `visual_contract_version` | `FoldView.v0.1` |

### Scalar pressures (`FoldScalarState`, all clamped `[0.0, 1.0]`, NOT truth scores)

`authority_score`, `freshness_score`, `evidence_strength`, `conflict_pressure`,
`interpretability`, `queryability`, `canon_readiness`, `drift_risk`,
`resolution_confidence`, `blast_radius`.

`scores_are_truth_values` is always `False` in `as_dict()`. `metric_policy` defaults to
`FoldMetricPolicy.v0.1`.

### Symbolic labels (`FoldSymbolicState`)

- `currentness_label` precedence (highest wins):
  `quarantined` > `held` > `superseded` > `conflicted` > `stale` > `unknown` >
  `current_but_contested` > `draft_current` > `current`.
- Plus `authority_label`, `freshness_label`, `conflict_label`, `intake_label`, and
  `symbolic_policy` (`DefaultFoldSymbolicPolicy.v0_1`).

### Policies (`fold_metrics.py`, frozen dataclasses)

| Policy | Key fields |
|---|---|
| `FoldMetricPolicy.v0.1` | `freshness_source_priority = (epistemic_last_evaluated, updated_ts)`; `max_lineage_depth = 5`; `scalar_clamping = (0.0, 1.0)`; `scores_are_truth_values = False`; LLM/random scores disallowed. |
| `DefaultFoldSymbolicPolicy.v0_1` | `conflict_pressure_contested_threshold = 0.35`; `authority_score_minimum_for_current = 0.30`; `freshness_score_stale_threshold = 0.25`; `canon_readiness_minimum = 0.50`; `resolution_confidence_minimum = 0.40`. |

### Compact resolver trace — FROZEN at six events

1. `authority_state_checked`
2. `supersession_checked`
3. `conflicts_checked`
4. `freshness_checked`
5. `intake_capability_checked`
6. `scalar_state_computed` (`collapsed_by_default = True`)

No extra events may be added at node scale (patch_002 invariant, enforced in
`_build_compact_trace`).

### Unknowns (`FoldUnknown`, always present even when empty)

Fields: `field`, `severity`, `meaning`, `blocks_currentness`,
`blocks_canon_eligibility`, `blocks_queryability`, `resolution_action`.
Registered for: missing/`unknown` `authority_state`, missing `freshness_age_days`,
lineage depth capped, and absent `canon_eligible`. The adapter never invents state;
missing inputs become unknowns.

### Packet identity and scope

`FoldScope(scale="node", scope_id=doc_id)`. `cluster`/`corpus` scales are deferred.

### API routes (CURRENT)

| Route | Returns |
|---|---|
| `GET /api/fold/node/{doc_id}` | Resolver-backed `CurrentFoldPacket.as_dict()`; 404 when the doc is absent. |
| `GET /api/fold/node/{doc_id}/trace` | Stub: `available: false` (full trace deferred). Compact trace is already in the main packet. |
| `GET /api/fold/library` | Batch scatter summary using simplified per-doc scoring (no per-doc subqueries). `limit` defaults 500, capped at 2000. Per-doc fields: `authority_score`, `freshness_score`, `conflict_pressure`, `canon_readiness`, `currentness_label`, `authority_state`. Also returns `label_counts`, `total`, `policy`. |

`fold_router` is registered in `app/api/main.py`. All routes are read-only; no operator
token required.

### UI (CURRENT)

| Symbol / element | Role |
|---|---|
| `app/ui/index.html#reader-fold-snapshot` | Fold Snapshot above the folded-node panel. |
| `app/ui/app.js` `renderFoldSnapshot` | Fetches and renders the snapshot from `/api/fold/node/{doc_id}`. |
| `app/ui/app.js` `loadFoldLibraryView`, `_foldDrawLibrary`, `_foldHitTest`, `FOLD_LABEL_COLORS` | Library scatter canvas (HTML5 Canvas 2D, devicePixelRatio scaling, ResizeObserver, legend toggles, click-to-inspect). |
| `app/ui/index.html#panel-fold-view` | Standalone Fold View nav panel; auto-loads scatter on activation. |

The `/api/docs/{doc_id}/fold` folded-node endpoint is preserved unchanged and is distinct
from `/api/fold/node/{doc_id}`.

---

## Phase 6 — Node-level scale_actions[] (CURRENT, COMPLETE)

**Scope:** additive `scale_actions[]` field on the node `CurrentFoldPacket`. Declarative
roll-up affordances only — navigation, never mutation. No aggregation in this phase.

### New type — `FoldScaleAction` (`current_fold.py`)

| Field | Type | Notes |
|---|---|---|
| `label` | `str` | Human-readable action label. |
| `target_scale` | `str` | `"cluster"` for the node-scale roll-up actions. |
| `target_axis` | `str` | `project` \| `plane` \| `domain`. |
| `target_id` | `str \| None` | Deterministic `"{axis}:{value}"` (e.g. `project:boh`, `plane:authority`). `None` when not allowed. |
| `allowed` | `bool` | Whether the roll-up target resolves at node scale. |
| `reason` | `str \| None` | Required (by convention) when `allowed=False`; omitted from `as_dict()` when `None`. |
| `filter` | `str \| None` | Optional member filter hint; omitted from `as_dict()` when `None`. |

`as_dict()` always emits `label`, `target_scale`, `target_axis`, `target_id`, `allowed`;
it omits `reason` and `filter` when they are `None`.

### Packet field

`CurrentFoldPacket.scale_actions: list[FoldScaleAction]` (default empty list), serialized
in `as_dict()` as `scale_actions: [...]`.

### Builder — `_build_node_scale_actions(base_packet)`

Reads only the packet (no DB access, no mutation). Produces exactly three node-scale
roll-up actions:

| Axis | Allowed when | `target_id` | Reason when blocked |
|---|---|---|---|
| `project` | `summary.project` present | `project:{project}` | "This node has no project value to roll up to." |
| `plane` | PlaneCard `plane` present, else `authority.canonical_layer` resolves | `plane:{plane}` | "No plane is resolvable for this node at node scale." |
| `domain` | never at node scale (deliberate) | — | "Domain membership is not resolved at node scale (deferred to Phase 7)." |

Domain is the deliberate missing-axis case: it is always `allowed: false` at node scale.
The cluster endpoints that would consume `target_id` values are Phase 7b (deferred).

### Phase 6 acceptance / invariants

- Additive and read-only; existing node packet fields, routes, and the frozen six-event
  trace are unchanged.
- `target_id` derivation is the deterministic `"{axis}:{value}"` form (buildspec §2.1).
- `allowed=false` actions carry a `reason`.
- No action implies a write; there is no promote/merge/resolve action.

---

## Phase 7a — Cluster aggregation engine (CURRENT, IMPLEMENTED)

> Implemented in `app/core/fold_aggregation.py` as a pure, read-only dual-channel
> cluster/corpus aggregation engine: **no routes, no UI, no schema, no migration, no DB
> writes, and no clusters table**. It is internal-only and exercised solely by
> `tests/test_fold_aggregation.py` (31 tests). The contract is frozen by the accepted
> acceptance spec `docs/specs/fold_phase7a_aggregation_acceptance_spec.md` (status accepted).
> Public API: `aggregate_cluster(axis, value, members)`, `aggregate_corpus(axis, clusters)`,
> `cluster_scope_id(axis, value)` → `"{axis}:{value}"`, `corpus_scope_id(axis)` → `"corpus:{axis}"`.

### Cluster identity (buildspec §2)

- A cluster is a derived `(axis, value)` selection over existing repo objects — **no new
  clusters table**.
- Supported axes and their backing columns:
  - `project` → `docs.project`
  - `plane` → `planes.plane_id` (membership via the doc's resolved authority plane)
  - `domain` → `substrate_lattice_registry.domain`
  - `batch` → `intake_capabilities.batch_id` (corpus-diagnostic axis only; never a canon/authority grouping)
- `scope_id` = `"{axis}:{value}"` (cluster) and `"corpus:{axis}"` (corpus).
- Membership computed at resolve time from the live row; a node with a NULL/missing axis
  value is NOT a silent member — it registers `FoldUnknown(field="cluster_membership_ambiguous")`.

### Dual-channel aggregation (buildspec §3 / acceptance spec §2 — FROZEN, IMPLEMENTED)

- **Label channel** — worst-case precedence over the frozen node 9-label order:
  `quarantined > held > superseded > conflicted > stale > unknown > current_but_contested >
  draft_current > current`, applied over member `symbolic_state.currentness_label`. Ties
  among equal worst labels break on the lowest `scope_id` lexicographically. Reuses
  node-level `DefaultFoldSymbolicPolicy`; no new cluster-scale thresholds. The
  buildspec-invented terms `expired` and `advisory` are **NOT** emitted (`expired` is
  subsumed by `superseded`; `advisory` is the umbrella over `draft_current` /
  `current_but_contested`). See accepted acceptance spec §2.
- **Numeric channel** — authority-weighted mean per pressure:
  `S_cluster,p = Σ_i (authority_score_i × S_i,p) / Σ_i (authority_score_i)`, rounded to 3 dp
  and clamped `[0.0, 1.0]`. If `Σ authority_score_i == 0` or all weights missing, fall back
  to equal-weighted arithmetic mean (numeric channel only; label channel still applies full
  precedence).
- All cluster scalars stay clamped `[0.0, 1.0]` and `scores_are_truth_values: false`.

### Aggregation packet contract (buildspec §4 — IMPLEMENTED)

The engine reuses `CurrentFoldPacket` with `scope.scale ∈ {cluster, corpus}` plus an
`aggregation` object that discloses every input (no hidden rollups):

| Field | Meaning |
|---|---|
| `method` | `dual_channel_v1` |
| `label_channel` | `worst_case_precedence` |
| `numeric_channel` | `authority_weighted_mean` |
| `numeric_fallback_used` | bool (equal-weight fallback taken) |
| `inputs_count`, `included_count`, `excluded_count` | `inputs_count == included_count + excluded_count` must always hold |
| `excluded_reasons` | enum: `quarantined`, `held`, `preserved_only`, `missing_axis_value`, `superseded`, `expired_validity` |
| `label_driver` | the member node that drove the worst-case label (`scope_id`, `label`) |
| `contributors[]` | per-node `scale`, `scope_id`, `weight`, `authority_score` |

Exclusion removes a member from the **numeric** channel only; the **label** channel still
considers excluded members for worst-case precedence.

### Aggregate compact trace (buildspec §6 — FROZEN at six aggregate events, IMPLEMENTED)

1. `cluster_membership_resolved`
2. `members_loaded`
3. `label_precedence_applied`
4. `numeric_rollup_computed`
5. `exclusions_recorded`
6. `aggregate_state_emitted` (collapsed by default)

The node-level six-event trace stays separately frozen. Full per-contributor trace stays
lazy via `resolver_trace_ref`.

---

## Phase 7b — Cluster + corpus routes (PLANNED, DEFERRED)

> Designed; **not implemented**. No cluster/corpus routes are registered.

| Planned route | Returns |
|---|---|
| `GET /api/fold/cluster/{axis}/{value}` | Aggregate `CurrentFoldPacket` (cluster scale). |
| `GET /api/fold/corpus/{axis}` | Corpus rollup of clusters across the axis. |
| `GET /api/fold/cluster/{axis}/{value}/trace` | Lazy stub (`available: false`), mirroring the node `/trace` stub. |

Read-only GETs; no operator token; mirror existing fold route style. Corpus packets
aggregate cluster packets (not raw nodes) so the rollup is associative.

---

## Phase 7c — Cluster fold UI (PLANNED, DEFERRED)

> Designed; **not implemented**.

Cluster card showing BOTH the worst-case label and the numeric scalar rollup strip,
included/excluded counts, `label_driver`, contributor list, and `scale_actions`. Reuses
existing fold UI patterns; node identity round-trips with `scale_actions` (following an
action then reading the resulting packet yields `scope.scope_id == target_id`).

Plane registry note (buildspec §7): cluster work reuses the existing `planes` table as the
plane registry; metric/visual metadata read from each plane's `mode_policy_json` with
documented fallbacks. A schema migration to first-class columns is out of scope and would
require frozen-scope approval.

---

## Phase 8 — 2.5D/3D spatial placeholder only (PLANNED, DEFERRED)

> Designed as a **non-functional placeholder only**; not implemented.

Documents four read-only scalar axis spaces (Authority Space, Risk Space, Canon Readiness
Space, Intake Capability Space) and renders a clearly labelled "not yet implemented"
surface. It MUST NOT implement true 3D, write or persist spatial coordinates (may read
existing `doc_coordinates`), present layout as authority, or use LLM-generated placement.

---

## Phase 9 — Tests + regression lock (PLANNED, DEFERRED)

> Planned acceptance for the deferred phases (buildspec §11).

Note: the aggregation acceptance cases below are already implemented and exercised in
`tests/test_fold_aggregation.py` (31 tests, frozen by the accepted Phase 7a acceptance
spec). The route- and UI-level acceptance (Phases 7b/7c) remains deferred.

Aggregation: single quarantined member → cluster label `quarantined`; single conflicted
member → `conflicted` unless quarantined present; numeric scalars equal the
authority-weighted mean (exact arithmetic); all-missing weights → equal-weighted numeric
mean with label channel unaffected; `inputs_count == included_count + excluded_count`
always; excluded contributors carry a reason and a quarantined excluded member still drives
the label. Scale-action `target_scale`/`target_id` round-trip to the resulting packet
`scope_id`. Existing node tests stay green.

---

## Cross-Phase Invariants (All Scales)

These rules apply at every scale and must never be violated:

```
Scalar scores are dimensional pressures, not truth values, at every scale.
unknowns[] is always present on every packet, including aggregates, even when empty.
canon_eligible is NEVER surfaced as true. It is always false by design; an aggregate is
  never canon-eligible, and only individual nodes carry the field, only as resolved.
No hidden rollups: every aggregate discloses inclusion/exclusion, weighting, contributors,
  and the label driver; inputs_count == included_count + excluded_count.
No auto-resolution: Fold View never resolves a conflict, promotes authority, or writes
  canon. All mutations remain proposal-only governance routes (out of scope here).
scale_actions are navigation-only; they never imply a write.
Spatial layout is a projection, never authority.
The node compact trace is frozen at six events; the aggregate trace is frozen at six
  aggregate events. No extra events may be added at either scale.
Resolvers never default silently on missing inputs; missing inputs become FoldUnknowns.
The metric loader never projects symbolic state; the symbolic projector never touches the DB.
Existing node-level CurrentFoldPacket, /api/fold/node, /api/fold/node/{id}/trace,
  /api/fold/library, and /api/docs/{id}/fold are preserved unchanged by later phases.
```

---

## What is deliberately NOT defined (buildspec §12)

```
A clusters database table or persisted cluster IDs (clusters are derived selections).
Graph community / conflict-neighborhood clustering (a later axis, if wanted).
Authority-plane recomputation (plane membership reads the existing resolved plane).
A schema migration for plane metric/visual columns (read from mode_policy_json for now).
True 3D, persistent spatial coordinates, or any spatial write path.
Any governance mutation: promote, merge, resolve-all, canon write (proposal-only, elsewhere).
LLM-derived scores or placements at any scale.
```
