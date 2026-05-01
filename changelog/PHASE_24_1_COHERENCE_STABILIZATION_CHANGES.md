# BOH v2 — Phase 24.1 Coherence Engine Stabilization

## Purpose

Phase 24 introduced the coherence decay engine. Phase 24.1 corrects its operational
semantics. The architecture was correct; the runtime behavior was not yet safe for
production use.

Seven patches applied in the priority order specified by the whitepage.

---

## P1 — Temporal Ambiguity Correction

**Problem:** Missing timestamps triggered epoch-0 fallback (1970-01-01), producing
20,000+ days of elapsed time and immediate `critical_decay` for any node without
explicit payload timestamps. Ambiguity was being converted into false certainty.

**Fix:**
- `_node_start_time()` returns `None` when no valid timestamp is found.
- `_parse_dt()` rejects epoch-0 and near-epoch values as sentinel non-timestamps.
- `evaluate_node_coherence()` detects `None` start and assigns `temporal_ambiguity`
  state instead of applying decay.
- `temporal_ambiguity` is now a first-class member of `DECAY_STATES`.
- `CoherenceScore` carries a `temporal_ambiguity: bool` field.
- `review_queue_resurfacing()` routes ambiguous nodes to `requires_temporal_review`
  queue instead of the standard `custodian_refresh_review` queue.

**Invariant:** Unknown time is ambiguity. It is not proof of decay.

---

## P2 — Decay Constant + Per-Plane Policy

**Problem:** Default `k = 0.035` put a well-sourced node (c0=0.75) into `stale` in
~5 days and `refresh_required` in ~11 days. This would immediately flood the review
queue and cause operators to ignore decay alarms, destroying the engine's utility.

**Fix:**
- Default `k` reduced to `0.007` (≈ quarterly review cadence; half-life ~99 days).
- `PLANE_DECAY_CONSTANTS` dict maps each plane to its appropriate daily decay rate:
  - `canonical`: `0.003` (slow)
  - `evidence`: `0.010` (fast)
  - `verification`: `0.008` (medium)
  - `operational` / `review`: `0.012–0.014` (medium-high)
  - `archive` / `constitutional`: `0.002` (very slow)
- `PLANE_DECAY_LABELS` provides human-readable labels for each plane policy.
- `plane_decay_constant(node)` resolves k and label from the node's plane.
- `evaluate_node_coherence()` uses plane-specific k unless caller overrides.
- `CoherenceScore` carries `decay_policy_label` field.
- `coherence_summary()` exposes the full `decay_policy` dict so operators can see
  why their plane's nodes decay at a particular rate.
- The reason string now includes `k`, the label, and `tau` for full traceability.

---

## P3 — Coherence Evaluation Performance Gate

**Problem:** `coherence_summary()` called `evaluate_all_coherence()` on every
invocation, which triggered `evaluate_node_coherence()` + `_persist_latest_score()`
for every node in the corpus. O(n) DB writes on every dashboard load.

**Fix:**
- `_summary_cache` dict + `_SUMMARY_CACHE_TTL = 300` seconds (5 minutes).
- `_summary_cache_valid()` checks cache age against monotonic clock.
- `coherence_summary()` returns cached result on cache hit (`from_cache: True`).
- `_invalidate_summary_cache()` called by `record_refresh_event()` so any actual
  governance action immediately triggers a fresh sweep on the next request.
- Full evaluation sweep only occurs on cache miss.

---

## P4 — Feedback Rewrite Idempotency

**Problem:** `create_constraint` used a timestamp-seeded ID, so every call produced
a new card even with identical parameters. Human retries created duplicate topology
mutations that could not be distinguished from distinct feedback events.

**Fix:**
- `IDEMPOTENCY_WINDOW_SECONDS = 1800` (30 minutes).
- `_find_recent_create_constraint(action, reason, actor, target)` queries
  `feedback_rewrites` for a matching non-reverted record within the window.
- `apply_feedback_rewrite()` checks for a duplicate before creating a new
  constraint card and returns `ok=False` with `existing_rewrite_id` on conflict.
- Different targets (different `constraint_target`) are not considered duplicates.

**Invariant:** The same feedback cannot create multiple topology mutations.

---

## P5 — Migration Order Normalization

**Problem:** In `connection.py`, Phase 23 (feedback_rewrites) and Phase 24
(coherence) tables were defined before Phase 22 (lattice_edges), even though
lattice_graph is a prerequisite for both. Migration order taught the wrong
architecture to future maintainers.

**Fix:** Migration executescript blocks reordered to reflect ontological dependency:

```
Phase 21 — plane_interfaces
Phase 22 — lattice_edges
Phase 23 — feedback_rewrites
Phase 24 — coherence_refresh_events, coherence_scores
```

All blocks use `IF NOT EXISTS`; no existing databases are affected.

---

## P6 — Diagnostic Explainability Layer

**Problem:** Runtime query results returned scores without explanation. Operators
could not determine *why* a node was flagged, what would break next, or what action
to take. Scored systems without explanation create false authority.

**Fix:** Four explanation fields added to every runtime query result:

```json
{
  "why_flagged": "high incoming dependency weight (3.20); low quality (q=0.40)",
  "what_constraint_is_load_bearing": "Node 'X' is load-bearing because ...",
  "what_breaks_next": "If this constraint fails, all depends_on nodes lose ...",
  "what_intervention_changes_state": "Raise q/c through evidence review, or ..."
}
```

Modified functions:
- `query_load_bearing_constraints()` — uses new `_explain_load_bearing()` helper.
- `query_intervention_expands_feasibility()` — per-node explanation inline.
- `query_harm_flow()` — per-relation harm narrative.
- `runtime_queries()` — adds `_meta.explanation_fields` so callers know which
  fields to surface in UI before displaying raw scores.

---

## P7 — Pre-Mutation Rewrite Preview

**Problem:** Operators approved feedback rewrites after seeing change history.
They needed to see the full topology diff before approving application.

**Fix:**
- `preview_feedback_rewrite()` added to `app/core/feedback_rewrite.py`.
  - Accepts identical parameters as `apply_feedback_rewrite()`.
  - Simulates the full weight/relation change without writing to the database.
  - Returns `before_state`, `after_state`, `affected_nodes`, `affected_flows`,
    `reversibility`, `revert_path`, `warnings`, and `simulation_only: True`.
  - Also checks idempotency window and surfaces warnings if apply would be blocked.
- `POST /api/feedback/preview` route added to `feedback_routes.py`.
  - Read-only. No DB writes. Returns the simulation preview.

**Invariant:** No blind approvals. Operators see the constraint diff before committing.

---

## Test Coverage

New file: `tests/test_phase24_1_coherence_stabilization.py`

19 regression tests, one or more per patch:

| Test | Patch |
|---|---|
| `test_p1_missing_timestamp_yields_temporal_ambiguity_not_critical_decay` | P1 |
| `test_p1_temporal_ambiguity_in_decay_states_enum` | P1 |
| `test_p1_epoch_zero_timestamp_treated_as_ambiguity` | P1 |
| `test_p2_canonical_plane_has_slower_decay_than_evidence` | P2 |
| `test_p2_canonical_decay_constant_within_slow_range` | P2 |
| `test_p2_default_decay_constant_is_conservative` | P2 |
| `test_p2_per_plane_k_applied_to_score` | P2 |
| `test_p2_per_plane_k_in_reason_string` | P2 |
| `test_p3_ttl_cache_returns_from_cache_on_second_call` | P3 |
| `test_p3_cache_invalidated_after_refresh_event` | P3 |
| `test_p4_duplicate_create_constraint_is_rejected` | P4 |
| `test_p4_different_target_is_not_duplicate` | P4 |
| `test_p5_migration_order_matches_architecture` | P5 |
| `test_p6_load_bearing_query_includes_explanation_fields` | P6 |
| `test_p6_harm_flow_query_includes_explanation_fields` | P6 |
| `test_p6_runtime_queries_include_meta_explanation_field` | P6 |
| `test_p7_preview_returns_before_and_after_state` | P7 |
| `test_p7_preview_does_not_write_to_database` | P7 |
| `test_p7_preview_api_endpoint_returns_simulation_only` | P7 |

All 19 pass.

---

## Files Modified

| File | Change |
|---|---|
| `app/core/coherence_decay.py` | P1 + P2 + P3 (full rewrite) |
| `app/core/feedback_rewrite.py` | P4 idempotency guard + P7 preview function |
| `app/core/lattice_graph.py` | P6 explanation fields on 3 query functions |
| `app/db/connection.py` | P5 migration block reorder |
| `app/api/routes/feedback_routes.py` | P7 preview route |
| `tests/test_phase24_1_coherence_stabilization.py` | New — 19 regression tests |

---

## Acceptance Status

| Criterion | Status |
|---|---|
| Missing timestamps no longer trigger false decay | PASS |
| Temporal ambiguity is explicit and visible | PASS |
| Decay cadence feels trustworthy (quarterly default) | PASS |
| Dashboard does not trigger write storms | PASS |
| Duplicate feedback cannot mutate topology twice | PASS |
| Diagnostics are explainable to operators | PASS |
| Rewrite approval is preview-first | PASS |
| Migration order teaches correct architecture | PASS |
