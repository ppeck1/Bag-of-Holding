# Database Migrations

BOH treats the initialized schema as baseline migration `0000_baseline`.
Forward changes are tracked in the `schema_migrations` ledger.

## Principles

- Migrations are forward-only.
- Schema state is persisted in SQLite.
- Runtime database files are local data and are not committed.
- Tests cover migration application and idempotency where implemented.

## Implemented Migration Families

- `0001_intake_orchestration_integrity`: intake lifecycle and orchestration
  hardening.
- `0002_intake_retrieval_promotion`: governed promotion/demotion ledgers for
  intake material that becomes retrieval-visible only through explicit gates.

The migration code is in `app/db/` and related core modules.
