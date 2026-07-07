# Architecture Overview

Bag of Holding uses a small number of explicit boundaries:

- `app/api/` registers HTTP routes and request/response models.
- `app/core/` contains governance, retrieval, lifecycle, indexing, and Fold
  logic.
- `app/db/` owns SQLite connection and schema initialization/migrations.
- `app/ui2/` is the build-free governed browser UI.
- `tests/` exercises the local authority, retrieval, Fold, intake, and UI shell
  contracts.

The system is local-first. The backend owns the document library boundary, and
callers do not receive arbitrary filesystem access. Mutations require operator
authorization when `BOH_OPERATOR_TOKEN` is set. Retrieval connectors use a
separate read-only token.
