# Bag of Holding v2 — Phase 14 Patch Changes

Applied prompt: governed intake, metadata validation, canonical authority protection, Atlas reorganization, and review artifact regression coverage.

## Files added

- `app/core/metadata_contract.py` — Phase 14 metadata contract, enum validation, path containment checks, legacy quarantine fallback, and authority transition rules.
- `app/core/authority_state.py` — canonical transition enforcement and deterministic authority scoring.
- `tests/test_llm_review_artifacts.py` — regression coverage for review artifact safety and path handling.
- `tests/test_phase14_atlas_smoke.py` — smoke coverage for the Phase 14 Atlas graph contract and cross-project suggested edges.

## Files modified

### `app/db/connection.py`

- Added migration-safe Phase 14 columns to `docs`: `project`, `document_class`, `canonical_layer`, `authority_state`, `review_state`, `provenance_json`, `source_hash`, and `document_id`.
- Added indexes for project, document class, canonical layer, and authority state.
- Added schema marker `v2.5.0-phase14`.

### `app/services/indexer.py`

- Integrated Phase 14 metadata contract extraction.
- Existing documents missing governed metadata now index into `Quarantine / Legacy Import` rather than silently entering governed topology.
- Contract errors surface in `lint_errors`.
- DB writes now persist project/class/layer/authority/review/provenance/source hash/document ID.
- Added authority transition enforcement before import writes.
- Canonical state cannot be overwritten or promoted by ordinary import without explicit approval.

### `app/core/input_surface.py`

- Scratch Capture is now the default lane.
- Browser notes receive scratch/quarantine metadata.
- Uploads support Scratch Capture and Governed Entry modes.
- Governed upload mode validates required metadata before saving.
- Source hashes are computed from upload bytes.
- Path safety remains based on `pathlib.resolve()` containment checks.

### `app/api/routes/input_routes.py`

- Upload endpoint now accepts `intake_mode`, `project`, `document_class`, `status`, `canonical_layer`, `title`, `provenance`, `document_id`, and `source_hash`.
- Validation failures return structured rejection records.

### `app/core/related.py`

- Refactored `/api/graph` data into Phase 14 structure: `projects`, `classes`, `nodes`, `edges`, `clusters`, and `layers`.
- Nodes now include project, document class, canonical layer, authority, authority state, and review state.
- Cross-project topic-overlap edges are forced to suggested/non-authoritative status unless explicitly approved.
- Project → class → layer grouping is now represented in the graph payload.

### `app/services/reviewer.py`

- Review artifacts now explicitly declare `review_artifact`, `canonical_layer: review`, `authority_state: non_authoritative`, and `review_state: pending`.
- Review artifacts now declare `may_overwrite_source: false` and `may_promote_canonical: false`.
- Review artifacts preserve lineage metadata and source hash.

### `app/ui/index.html`

- Added Atlas filters for canonical layer and status.
- Updated app script cache-busting to `v=140`.

### `app/ui/app.js`

- Atlas filtering now understands project, corpus class, document class, status, and canonical layer.
- Reader title now uses `doc.title` when available.
- Atlas node radius and color now reflect status/layer/authority rather than only corpus class.
- Node tooltip now includes project and canonical layer.
- Topic/suggested edges can be hidden with the existing Topic Edges toggle.

## Validation performed

Executed targeted Phase 14 tests:

```text
9 passed in 0.30s
```

Command used:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_llm_review_artifacts.py \
  tests/test_phase14_atlas_smoke.py \
  -q -p no:cacheprovider
```

## Important limitations

This is a structural Phase 14 patch, not a complete UI redesign.

The patch adds the governed substrate, contract persistence, Atlas payload structure, filters, and regression tests. It does not fully split `app/ui/app.js` into `atlas.js`; that remains the next cleanup target because preserving Phase 13 interaction behavior was prioritized.

Atlas remains canvas-based 2D with simulated hierarchy/depth, not WebGL.

## Recommended next patch

1. Split Atlas logic into `app/ui/atlas.js`.
2. Add a full Governed Entry form in the Import panel.
3. Add explicit human approval endpoint for `review_artifact → approved_patch → canonical`.
4. Add UI affordance for approving/rejecting cross-project suggested edges.
5. Add migration command to bulk assign quarantined documents to project/class/layer.
