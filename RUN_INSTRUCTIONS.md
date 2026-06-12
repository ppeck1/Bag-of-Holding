# RUN_INSTRUCTIONS.md
# Bag of Holding — Local Run Notes

## Prerequisites

- Python 3.11 or 3.12
- `pip install -r requirements.txt`
- Optional: Ollama for local LLM proposal generation

## Quickstart

```bash
cd Bag-of-Holding
pip install -r requirements.txt
python launcher.py
```

The launcher starts the server and opens the browser at `http://127.0.0.1:8000/` (the new governed UI).

**Windows:** double-click `launcher.bat` or run `python launcher.py`

**macOS / Linux:**
```bash
chmod +x launcher.sh
./launcher.sh
```

## Launcher Options

```bash
python launcher.py --port 9000        # custom port
python launcher.py --no-browser       # headless / server-only
python launcher.py --library ./library
python launcher.py --db ./boh.db
python launcher.py --reload           # uvicorn hot-reload (dev)
```

If port `8000` is already in use, the launcher detects it before spawning uvicorn and suggests `--port 9000`.

## URLs

| URL | Description |
| --- | --- |
| `http://127.0.0.1:8000/` | New governed UI — **primary** |
| `http://127.0.0.1:8000/classic` | Classic UI (deprecated; preserved for rollback) |
| `http://127.0.0.1:8000/v2/` | Backward-compat alias for the governed UI |
| `http://127.0.0.1:8000/docs` | FastAPI OpenAPI browser |
| `http://127.0.0.1:8000/api/health` | Health check |

UI assets at `/`, `/v2`, and `/classic` are served with `Cache-Control: no-cache, must-revalidate` (`_CachelessStaticFiles`) so the browser revalidates each ES module on every load and a stale cached module can't run against fresh siblings. Vendor libraries (`/vendor/...`) cache normally.

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `BOH_LIBRARY` | `./library` | Server-owned document library root |
| `BOH_DB` | `boh.db` | SQLite database path |
| `BOH_OPERATOR_TOKEN` | unset | Required for mutation routes (reset, seed, approval, governance) |
| `BOH_RETRIEVAL_TOKEN` | unset | Required for read-only `/api/retrieve` and `/api/context-object` connector access (403 fail-closed when unset) |
| `BOH_RETRIEVAL_INCLUDE_PROMOTED` | `false` | Server-side exposure gate for promoted intake documents. Retrieval surfaces show a promoted doc only when this is `true` AND the request opts in with `include_promoted` (dual gate, fail-closed) |
| `BOH_DATA_ROOT` | unset | Root for the governed-intake pipeline (RAW preservation, normalized artifacts). Required before `POST /api/intake/run` or scheduler activation |
| `BOH_INTAKE_SCHEDULER_ENABLED` | `false` | Intake scheduler master switch (inert by default; manual, process-scoped activation only) |
| `BOH_WATCH_PATH` | unset | Directory the intake scheduler scans; required when the scheduler is enabled |
| `BOH_INTAKE_IGNORE_PATTERNS` | unset | Comma-separated filename patterns the scheduler excludes from the watch root (keep paired with `BOH_WATCH_PATH` so the ingested set stays stable) |
| `BOH_INTAKE_SCAN_INTERVAL` | `30` | Seconds between scheduler scans (validated 1–86400; out-of-range fails closed) |
| `BOH_INTAKE_DRAIN_TIMEOUT` | `30.0` | Seconds to wait for in-flight intake work on stop (validated 0.001–3600; fails closed) |
| `BOH_DEFAULT_ACTOR` | `local_operator` | Default actor for ledger attribution |
| `BOH_AUTO_INDEX` | `false` | Run background autoindex on startup |
| `BOH_AUTO_INDEX_MAX_FILES` | `5000` | Autoindex scan cap |
| `BOH_DETERMINISTIC_REVIEW_ON_INDEX` | `true` | Run deterministic review during indexing |
| `BOH_LLM_REVIEW_ON_INDEX` | `false` | Run LLM review during indexing |
| `BOH_OLLAMA_ENABLED` | `false` | Gate Ollama invocation |
| `BOH_OLLAMA_URL` | `http://localhost:11434` | Ollama endpoint |
| `BOH_OLLAMA_MODEL` | `llama3.2` | Default Ollama model |

## Confirming the Build

```bash
curl http://127.0.0.1:8000/api/health
```

Expected response:

```json
{
  "status": "ok",
  "version": "2.28.4",
  "phase": "28.4",
  "status_label": "phase28.4-acceptance-repro-ui-hardening",
  "db": "connected",
  "library": "./library"
}
```

## Operator Authorization

Protected routes fail closed unless `BOH_OPERATOR_TOKEN` is set before launch.

**PowerShell:**
```powershell
$env:BOH_OPERATOR_TOKEN = "dev-local-only"
python launcher.py
```

**bash:**
```bash
BOH_OPERATOR_TOKEN=dev-local-only python launcher.py
```

Requests to protected routes must include:
- `X-BOH-Operator-Token`
- `X-BOH-Actor-ID`
- `Content-Type: application/json` (for JSON bodies)

## Read-Only Retrieval

```powershell
$env:BOH_RETRIEVAL_TOKEN = "dev-readonly"
python launcher.py
```

```bash
curl -X POST http://127.0.0.1:8000/api/retrieve \
  -H "Content-Type: application/json" \
  -H "X-BOH-Retrieval-Token: dev-readonly" \
  -d '{"query": "bounded context packs", "limit": 5}'
```

## Clean → Seed → Verify Workflow

1. Set `BOH_OPERATOR_TOKEN`.
2. Start BOH.
3. Enter the operator token in the browser (Settings → Security & Advanced, or the Status panel in the classic UI).
4. Confirm actor ID (default: `local_operator`).
5. Click Verify.
6. Click Clean Test Workspace.
7. Click Seed Fixtures.
8. Click Verify again.

Clean removes test fixtures, generated review artifacts, stale DB rows, and indexed candidates. Quarantine files are preserved.

## Run Tests

```bash
python -m pytest tests -q
```

## Live API Reference

- Browser: `http://127.0.0.1:8000/docs`
- JSON: `http://127.0.0.1:8000/openapi.json`

## Schema Note

`app/db/schema.sql` plus the idempotent `init_db()` body in `app/db/connection.py` form the immutable schema **baseline** (`0000_baseline`). A forward-migration architecture governs everything after it (`boh_db_migration_architecture_v0_1`): `app/db/migrations.py` adds a `schema_migrations` ledger + runner that applies numbered forward migrations once each, transactionally, with a WAL-safe `VACUUM INTO` backup before any forward migration (gated by `BOH_DB_BACKUP_BEFORE_MIGRATE`, default on). `MIGRATIONS` currently registers `0001_intake_orchestration_integrity` and `0002_intake_retrieval_promotion` (the `intake_handoffs`/`intake_promotions` ledgers) — new schema changes append a numbered migration rather than editing `init_db`/`schema.sql`. Migrations run automatically on first connection; no manual SQL required. See `docs/db_migrations.md` (tested by `tests/test_db_migrations.py`).
