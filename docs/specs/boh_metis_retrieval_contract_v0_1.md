# BOH Metis Retrieval Contract v0.1

The retrieval contract provides read-only context packs for LLM consumers.

## Boundary

- Uses `BOH_RETRIEVAL_TOKEN`, not `BOH_OPERATOR_TOKEN`.
- Returns cited context and warnings.
- Does not mutate documents, lifecycle state, authority state, or canon.

## Context Item Fields

Typical fields include:

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
- `citation`
- `warnings`
- `score`
- `why_selected`

## Promotion Gate

Promoted intake documents are excluded from retrieval by default. Exposure
requires both the server setting `BOH_RETRIEVAL_INCLUDE_PROMOTED=true` and the
per-request `include_promoted` flag.
