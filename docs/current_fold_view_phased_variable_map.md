# Current Fold View Variable Map

The Fold view is a read-oriented projection over persisted document and
PlaneCard state.

## Core Values

- `authority_score`: normalized authority signal.
- `freshness_score`: currentness and validity-window signal.
- `conflict_pressure`: pressure from unresolved or advisory conflicts.
- `canon_readiness`: readiness estimate for canonical review.
- `currentness_label`: current, stale, expired, conflicted, or unknown.

## Cluster Semantics

Cluster rollups keep two channels:

- label precedence for worst-case or attention-driving states
- numeric aggregation for scan-friendly comparison

The UI may filter visible planes and libraries for browsing, but those filters
do not mutate retrieval, authority, intake, or canonical state.
