# Bag of Holding v2 — Phase 15.5 Applied Changes

## Patch target
Applied the attached Phase 15.5 Governance Legibility whitepaper requirements against `BOH_v2_Phase15_applied.zip`.

## Files changed

- `app/core/approval.py`
- `app/api/routes/approval_routes.py`
- `app/ui/index.html`
- `app/ui/app.js`
- `app/ui/style.css`

## Backend changes

### Approval severity + blast radius
Added computed approval impact profiling for:

- `impact_score`
- `severity`
- `downstream_references_affected`
- `projects_touched`
- `canonical_dependencies`
- `rollback_complexity`
- `cross_project_exposure`
- `governance_tier`

Pending approval responses now return these fields so the UI can show consequence before approval.

### Human-readable provenance
Approved requests now include a `human_readable` provenance block in the signed artifact JSON:

- approved by
- reason
- replacing / transition context
- approval timestamp
- affected document count
- rollback availability
- short signature
- artifact ID
- review note

The cryptographic signature remains intact, but the user-facing layer now presents meaning before checksum.

### Constitutional ledger endpoint
Added:

```http
GET /api/governance/approve/ledger
```

Supports optional filters:

- `status`
- `action_type`
- `doc_id`
- `limit`

This makes approvals queryable as constitutional history, not only as a pending task queue.

### Review diff endpoint
Added:

```http
GET /api/governance/approve/{approval_id}/review-diff
```

Returns line-oriented original/proposed review-patch context with:

- source document
- review artifact reference
- LLM source disclosure
- diff hash
- blast radius
- per-line changed/unchanged state

### Review patch request enrichment
`POST /api/governance/approve/request-patch` now accepts optional:

- `original_text`
- `proposed_text`
- `llm_source`
- `review_artifact`

These are packed into the review patch impact payload so the diff UI can reconstruct the approval context.

## UI changes

### Approval queue
Approval cards now display:

- severity pill
- impact score
- downstream references
- rollback complexity
- governance tier
- cross-project exposure
- escalation warning for high/extreme approvals

### Constitutional diff UI
Review patch approvals now expose a first-class diff surface:

- original canonical source
- proposed review artifact
- LLM source disclosure
- diff hash
- changed-line count
- line-by-line old/new comparison

This does not silently merge content. It makes the approval boundary visible before the reviewer approves.

### Constitutional ledger
Added a ledger view beside the pending queue, showing:

- request time
- action type
- status
- severity / impact score
- document
- reviewer

### Request review patch form
Added a UI form for submitting review artifact patch requests with original/proposed text and LLM source disclosure.

## Styling changes

Added Phase 15.5 governance-legibility styles:

- severity-weighted approval cards
- low / medium / high / extreme visual states
- blast-radius grid
- escalation warning block
- constitutional diff table
- ledger table

## Validation

Targeted tests run:

```text
tests/test_phase15_approval.py
tests/test_llm_review_artifacts.py
```

Result:

```text
39 passed, 1 warning
```

The startup warning came from the notebook artifact runtime warmup, not from the Bag of Holding test suite.
