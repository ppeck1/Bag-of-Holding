# Data Model

This is a detected-data scaffold, not a complete schema reference.

## Persistence

- SQLite database configured by `BOH_DB`.
- Managed document files under `BOH_LIBRARY`.

## Key Tables Seen In Schema/Code

- `docs`
- `docs_fts`
- `doc_chunks`
- `doc_chunks_fts`
- `doc_chunk_embeddings`
- `plane_facts`
- `cards` / `plane_cards` compatibility view
- `storage_events`
- `audit_log`
- `lineage`
- `conflicts`
- `doc_coordinates`
- `workspace_policies`
- `actor_*` tables
- `planar_gate_results`
- `planar_mistake_events`
- `planar_patch_proposals`
- `planar_canon_change_records`
- `planar_information_residence_map`
- `planar_fixture_cases`

## Caveat

Schema growth is split between `app/db/schema.sql` and initialization/migration-style logic in `app/db/connection.py`. Check both before changing persistence.
