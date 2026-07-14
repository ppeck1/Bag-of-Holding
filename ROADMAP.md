# Bag of Holding Roadmap

This roadmap describes product direction, not implemented behavior. Current
capabilities are documented in `README.md` and verified by the test suite.

## Delivered foundation

- Local-first FastAPI application with SQLite persistence and a build-free UI.
- Governed capture, preservation, normalization, quarantine, replay, and
  explicit promotion boundaries.
- Authority-aware document retrieval with citations, source spans, provenance,
  freshness, conflicts, lineage, and content-safe withholding.
- Current Context Brief and context-object assembly for document, project,
  plane, query, and graph-neighborhood scopes.
- Human-facing Library, Review, Authority, Intake, Status, Activity, and Fold
  Workspace surfaces.
- Versioned schema migration support and deterministic demo environments.
- Separate operator and retrieval credential boundaries.
- App-side lifecycle and credential-scrubbing controls for the complete
  deployment's fixed eight-tool read-only MCP profile. Operational MCP tooling
  is outside the sanitized public source boundary.
- Fail-closed sanitized public-export workflow.

## Near-term directions

### Knowledge health

Add deterministic read models for duplicate concentration, orphaned evidence,
conflict and canon drift, evidence coverage, aging, and compression
opportunities. Measurements should remain explainable and must not
automatically rewrite or promote knowledge.

### Browser and accessibility verification

Expand interaction testing for narrow layouts, keyboard navigation, focus
management, drawers, and the remaining browser-only Fold workflows.

### Retrieval evaluation

Grow the synthetic judged deck, add more policy-boundary cases, and keep
relevance improvements gated on authority, privacy, no-answer, parity, and
performance checks.

### Operational clarity

Improve user-facing scheduler, intake-lane, and promotion-state explanations so
an operator can distinguish preservation, queryability, review, and canonical
admission at a glance.

## Later exploration

- Optional 2.5D/3D spatial views for Fold data.
- Larger-corpus performance work after measured baselines exist.
- Additional import adapters that preserve the current fail-closed safety
  lanes.
- More portable packaging once runtime expectations are frozen.

## Non-goals without a separate design and security review

- Automatic canon promotion or conflict resolution.
- A write-capable remote AI connector.
- Silent background ingestion enabled by default.
- Weakening operator, retrieval, filesystem, redaction, or audit boundaries.
- Treating speculative plans as shipped product behavior.
