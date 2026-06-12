# Database migrations

Status: authoritative. Implemented by `app/db/migrations.py`, invoked from
`app/db/connection.py` `init_db()`.

## Model: baseline + forward migrations

`init_db()` is an idempotent, declarative schema builder: it converges any database — fresh
or existing — to the current full schema via `CREATE TABLE IF NOT EXISTS` and
`_add_column_if_missing`. **That schema is the immutable baseline** (`0000_baseline`). The
baseline is never re-expressed as migration steps.

`app/db/migrations.py` governs everything **forward** from the baseline:

- A `schema_migrations` ledger table: `(migration_id, applied_ts, checksum)`. This is the
  authoritative migration record. (The legacy `schema_version` table is cosmetic stamping
  and is kept for history only.)
- An ordered `MIGRATIONS: list[Migration]`, applied after the baseline. It is **empty**
  today — the current schema is the baseline.
- `run_migrations(conn_factory, db_path)` — called at the end of `init_db()` (after the
  baseline is committed, so the on-disk DB is consistent). It:
  1. ensures `schema_migrations`,
  2. stamps `0000_baseline` once (O(1); existing DBs are recognized, never re-created),
  3. takes a backup if any forward migration is pending,
  4. applies each pending migration in its own transaction.

A fresh DB and an existing DB converge to the identical schema.

## Safety properties (all tested in `tests/test_db_migrations.py`)

- **Schema-neutral baseline.** Introducing the runner adds only the `schema_migrations`
  table; the rest of the schema is byte-identical to the prior `init_db` output.
- **Existing DBs.** Recognized at baseline with no re-creation; data preserved; baseline
  stamped exactly once.
- **Interrupted migration.** Each migration runs `BEGIN → up(conn) → record → COMMIT`. On
  any error it `ROLLBACK`s and raises. SQLite DDL is transactional, so a failed migration
  leaves the DB at the last fully-applied version with no partial change and no false
  ledger row.
- **Idempotent.** Applied migrations are skipped on re-run.

## Backup

Before applying any **pending forward migration** (and only then — no churn on ordinary
startups), `run_migrations` takes a consistent, WAL-safe single-file backup with
`VACUUM INTO`, written next to the DB as `<db>.bak-<YYYYMMDD-HHMMSS>`. A backup failure
**aborts** the migration (fail-closed): nothing is applied.

- Disable with `BOH_DB_BACKUP_BEFORE_MIGRATE=0` (e.g. for ephemeral/test DBs).
- In-memory DBs are not backed up.
- Operator guidance: before a release that adds forward migrations, ensure the DB directory
  has free space for a full copy of `boh.db`; the automatic backup is a safety net, not a
  substitute for your own backups.

## Adding a migration

1. Append to `MIGRATIONS` in `app/db/migrations.py`:
   ```python
   def _0001_add_foo(conn):
       conn.execute("ALTER TABLE docs ADD COLUMN foo TEXT DEFAULT ''")

   MIGRATIONS = [
       Migration("0001_add_foo", "add docs.foo", _0001_add_foo),
   ]
   ```
2. `id` must be unique and lexically ordered (zero-padded numeric prefix). **Never edit or
   reorder a shipped migration** — append a new one to change course.
3. `up(conn)` performs DDL only. Do **not** commit or touch `schema_migrations` inside it —
   the runner owns the transaction and the ledger.
4. If a migration needs `PRAGMA foreign_keys=OFF` (e.g. a table rebuild), toggle it inside
   `up` and restore it; the runner's connection has `foreign_keys` at the `get_conn`
   default.
5. Add a test in `tests/test_db_migrations.py` (apply-once, skip-on-rerun, and any data
   transform you perform).

## Not in scope (by design)

- The existing ~960-line `init_db` schema is the baseline; it is not converted into numbered
  migrations.
- Tables created lazily by other modules (`llm_queue`, `sc3_constitutive`, `autoindex`,
  `lifecycle`) are unchanged; they are not migration-managed.
