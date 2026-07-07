# BOH Demo Runbook

Doctrine: **LLM proposes. Human governs. System audits.**

This runbook walks an operator through a local demo that surfaces the current
Bag of Holding (BOH) capabilities, surface by surface. Each step maps to the
capability it proves and to where to look in the UI/API.

> **Scope note.** This document and the optional `demo_showcase.py` orchestrator
> are documentation/orchestration only. They call **existing** seed entrypoints;
> they introduce no new seeding logic. The seeds themselves write to the runtime
> `library/` folder and the SQLite database. **You** run them — see the warnings
> on each step. Verify against `/docs` (the live FastAPI route authority) if any
> claim here looks stale; code wins over docs.

> **UI Note:** The `/v2` route is a backward-compatible alias to the new governed UI
> served at `/`. All `/v2` screens are fully wired to live API endpoints with inspector
> selection on all major table rows. The `/v2` Settings screen distinguishes between
> BROWSER LOCAL (editable), SESSION LOCAL (session-scoped), READ-ONLY ENV (env-backed),
> and NEEDS SETTINGS API (not yet connected). The Status screen includes a real
> Auto-Index panel with live rebuild button, immediate result display, and status polling.

---

## 0. What this demo proves (at a glance)

| Surface | Proven by | Where to look |
|---------|-----------|---------------|
| Dashboard | startup + any seed | `/` (Dashboard panel) |
| Inbox / Intake controls | START HERE toolbar | `/` (Inbox panel) |
| Library | demo-seed + productivity seed | `GET /api/docs`, Library panel |
| Search | demo-seed (Daenary terms) | `GET /api/search?q=...`, Search panel |
| Conflicts (no auto-resolution) | productivity seed advisory conflicts | `GET /api/conflicts`, Conflicts panel |
| Duplicate Review | hash detection on index | `GET /api/duplicates`, Duplicate Review panel |
| Bulk Import | re-index / upload | Bulk Import panel |
| Graph Lab (Web / Evidence / Risk / Authority) | `seed_visualization_demo.py` | `GET /api/graph`, Graph Lab panel |
| Fold Workspace projections and cluster expansion | productivity seed (9 authority states) | `GET /api/fold/library`, `/api/graph/projection`, Fold Workspace panel |
| Fold node packet + scale_actions | demo-seed folded-node anchor | `GET /api/fold/node/{doc_id}` |
| Resolution Center | demo-seed governance examples | Resolution Center panel |
| Proposed Changes | (deferred — requires LLM enqueue) | `GET /api/llm/queue` |
| System Status | startup diagnostics | `GET /api/status`, System Status panel |
| Domains (PlaneCards) | PlaneCard backfill | `GET /api/planes/cards`, Domains panel |
| Governed Intake pipeline | `POST /api/intake/run` | `GET /api/intake/*`, Intake panel |

---

## 0.5 One-command read-only capability tour

`demo_capability_tour.py` is a **read-only** tour that hits the full current
capability surface — including backend features that do not yet have a `/v2`
frontend (governed-intake substrate + scheduler-status block, dual-channel
fold cluster/corpus aggregation, the six CANON scalar-bridge variables,
SC3 plane inference, lattice, certificate workflow, Metis retrieval contract) —
and prints a `PASS / PARTIAL / EMPTY / SKIP / FAIL` matrix. It **writes nothing**.

```bash
# with a server running (python launcher.py):
python demo_capability_tour.py
python demo_capability_tour.py --base-url http://127.0.0.1:8000
python demo_capability_tour.py --json     # machine-readable
python demo_capability_tour.py --strict   # exit 1 if any surface FAILs
```

`EMPTY` means a surface is reachable but no rows are seeded — run
`python demo_showcase.py --execute` (operator opt-in; writes runtime data),
then re-run the tour to see those surfaces populate. The operator-gated intake
WRITE paths (`POST /api/intake/run`, `/replay`) are intentionally reported as
`SKIP`; the tour never mutates the database.

On a fully-seeded local instance every operationally-relevant surface reports
`PASS`; the only expected `SKIP` is `POST /api/retrieve` unless a
`--retrieval-token` (matching `BOH_RETRIEVAL_TOKEN`) is supplied.

---

## 1. Prerequisites

### 1.1 Python + dependencies

```bash
cd <repo-root>
pip install -r requirements.txt
```

`launcher.py` runs a dependency preflight and will print exact `pip install`
instructions if anything is missing.

### 1.2 Environment variables

All of these are **optional** for a local demo. The defaults are tuned so the
tool works out of the box.

| Variable | Demo recommendation | Effect |
|----------|--------------------|--------|
| `BOH_OPERATOR_TOKEN` | **leave unset** for dev-open demo | When unset, BOH runs in **dev-open mode**: protected routes (demo-seed, intake run, backfill, etc.) pass through automatically as actor `dev_operator`, and a one-time `RuntimeWarning` is emitted. A DEV-OPEN badge appears in the UI. Set it (and supply `X-BOH-Operator-Token` on protected calls) only if you want to demo enforcement (401 missing / 403 wrong). Source: `app/core/auth.py`. |
| `BOH_DATA_ROOT` | **set this** before launch to demo intake | Required for the Governed Intake pipeline (preservation/normalization/queryability/interpretation). Without it, `POST /api/intake/run` returns HTTP 422 `BOH_DATA_ROOT is not configured`. Source: `app/api/routes/intake_routes.py`. Note: `seed_full_demo.py` itself `setdefault`s `BOH_DATA_ROOT` to the repo root if you do not set it. |
| `BOH_LIBRARY` | default `./library` | Server-owned document authority root. |
| `BOH_DB` | default `boh.db` | SQLite database path. |
| `BOH_AUTO_INDEX` | off by default | Leave off; the demo seeds index explicitly. |

PowerShell, to also exercise intake:

```powershell
$env:BOH_DATA_ROOT = "<repo-root>\data"
# (intentionally NOT setting BOH_OPERATOR_TOKEN -> dev-open local demo)
```

### 1.3 Demo asset

The productivity-methods seed extracts from an operator-supplied zip — pass
`--zip <path>` or set the `BOH_DEMO_SEED_ZIP` environment variable; there is no
built-in default path. If no zip is configured or the file is missing, the
productivity seed reports this and seeds nothing.
Note: `app/api/main.py` lifespan auto-seeds this on startup **only if** a zip is
configured and present and the marker file
`library/.productivity_methods_seeded` is absent.

---

## 2. Launch

```powershell
python launcher.py
```

- Starts uvicorn on `http://127.0.0.1:8000`, waits for `/api/health`, opens the
  browser.
- Custom port: `python launcher.py --port 9000`. Headless: `--no-browser`.
- On startup the lifespan hook (`app/api/main.py`):
  1. starts the intake background scheduler **only if**
     `BOH_INTAKE_SCHEDULER_ENABLED=true` (default: off). When a real watch path is
     configured, `BOH_INTAKE_IGNORE_PATTERNS` (comma-separated; no-op when unset) can
     exclude files from discovery. When watching a real corpus, keep `BOH_WATCH_PATH`
     (e.g. `<watch-root>`) and `BOH_INTAKE_IGNORE_PATTERNS` paired so generated files
     stay out of the intake ledger (see `docs/project_variable_map.md`);
  2. calls `auto_seed_if_needed()` — auto-seeds the productivity library if the
     zip is present and not already seeded (failures are swallowed; startup is
     never blocked).

**Verify launch:** `GET /api/health` → 200. Open the Dashboard panel; the
DEV-OPEN badge confirms dev-open mode.

---

## 3. Seed steps (each lights up a surface)

> Each seed below **writes to runtime `library/` and/or `boh.db`**. Run them
> yourself. The optional `demo_showcase.py` orchestrator (Section 7) sequences
> these same entrypoints with a dry-run default.

### Step A — Consolidated demo project (governance + Daenary)

**Entrypoint:** `POST /api/input/demo-seed` (operator-gated; in dev-open mode it
passes through). UI equivalent: **Inbox → START HERE → Load Demo Project**.

```bash
curl -X POST http://127.0.0.1:8000/api/input/demo-seed
# If BOH_OPERATOR_TOKEN is set, add: -H "X-BOH-Operator-Token: <token>"
```

**What it seeds:** 13 governance/refusal example notes (Hospital LOS, E. coli
viability, Corporate Governance, Governance Failure Cases) plus a Daenary
epistemic-state set spanning canonical / contained / canceled / expired /
conflict / ambiguous states. It also wraps one anchor doc as a PlaneCard and
registers a demo lineage reference and an advisory `demo_fold_conflict` so one
graph node has meaningful folded-node facets.

**Surfaces lit:** Library, Search, Conflicts, Resolution Center / Custodian
Layer, Fold node packet. The response body returns `capability_surfaces[]`,
`next_steps[]`, and `folded_node_demo` (with `anchor_doc_id`) — note the
`anchor_doc_id` for Step E.

**Verify:**
- `GET /api/docs` → demo documents with project/lifecycle/status/authority.
- `GET /api/search?q=viability` and `q=contradiction` → scored results.
- Response `capability_surfaces` lists Library, Search, Visualization, Custodian
  Layer, Domains, Retrieval, System Status (matches
  `tests/test_demo_capability_manifest.py`).

### Step B — Full-capability demo library (Fold Workspace measured projections)

**Entrypoint:** `python seed_full_demo.py` (standalone; no server required; no
external files required — all content embedded; idempotent via
`library/.full_demo_seeded`; honors `BOH_DB`/`BOH_LIBRARY`/`BOH_DATA_ROOT`).

```bash
python seed_full_demo.py            # seed if not already seeded
python seed_full_demo.py --force    # clear demo projects and re-seed
python seed_full_demo.py --dry-run  # print the plan without writing
```

**What it seeds:** 50 self-contained markdown documents across all **8 planes**
and 4 projects, with the full authority spread (`canonical` … `unknown`),
a 3-year freshness/validity spread, 6 conflict pairs, and 4 supersession edges
recorded as stored lineage.

**Surfaces lit:** Library (volume + authority spread), **Fold Workspace** (all
six distinct projections, project clusters, Cluster Focus, Action Queue),
Conflicts, context-object retrieval.

**Verify:** `GET /api/fold/library` → `docs[]` each with `authority_score`,
`freshness_score`, `conflict_pressure`, `canon_readiness`, `currentness_label`,
plus `label_counts`. In the **Fold Workspace**, switch Web/Risk/Authority/
Evidence/Currentness/Timeline and confirm the axes/lanes visibly change; double-
click a project cluster and confirm members appear at their measured projection
coordinates. Open the View toolkit to try label modes, edge modes, fold axis,
Fit/Reset, Cluster Focus, and the Actions view.

### Step C — Visualization / Graph Lab corpus

**Entrypoint:** `python seed_visualization_demo.py` (standalone script; writes
directly to `boh.db`). It seeds 16 demo docs and 12 typed edges plus governance
stress fixtures (authority mismatches, locks, containments, escalations).

> This script has **no `--force`/idempotency guard**; it uses
> `INSERT OR REPLACE`. Re-running overwrites the demo rows. It does not touch
> your non-demo corpus rows.

**Surfaces lit:** Graph Lab — Web (typed edges: lineage/supersedes/derives/
conflict/topic), Evidence State (d/q/c scatter), Risk Map (viability quadrants),
Authority Path (custodian lanes). The seeded corpus is defined directly in
`seed_visualization_demo.py`.

**Verify:** `GET /api/graph` returns nodes + typed edges; open Graph Lab and
cycle Web → Evidence State → Risk Map → Authority Path.

### Step D — PlaneCards (Domains)

**Entrypoint:** `POST /api/planes/backfill` (operator-gated; dev-open passes
through). UI: **Domains → Backfill all**.

**Surfaces lit:** Domains panel — every indexed doc wrapped as a PlaneCard.

**Verify:** `GET /api/planes/cards` → PlaneCard rows with `plane`, `card_type`,
`topic`, `b/d/m`, `validity`, source ref preserved.

### Step E — Fold node packet with `scale_actions`

**Entrypoint (read-only):** `GET /api/fold/node/{doc_id}` using the
`anchor_doc_id` from Step A's `folded_node_demo` (or any seeded doc_id).

```bash
curl http://127.0.0.1:8000/api/fold/node/<anchor_doc_id>
```

**What it proves:** the resolver-backed `CurrentFoldPacket` — currentness label,
scalar **pressures** (authority / freshness / conflict / canon-readiness — these
are dimensional pressures, **not** truth values), registered unknowns, a compact
trace, and `scale_actions` (governance actions the resolver surfaces for the
node). In the UI, selecting a node in Graph Lab loads the live **Fold Snapshot**
above the reader pane.

**Verify:** packet includes `currentness_label`, scalar fields, `unknowns`, the
compact trace, and `scale_actions`. The full trace endpoint
`GET /api/fold/node/{doc_id}/trace` intentionally returns
`available: false` (full trace deferred — see Section 8).

### Step F — Governance Approval Workflow

**Precondition:** Requires a document that can be amended and one pending approval request. Use the demo-seeded docs (from Step A).

#### Sub-step F.1: Create a supersede approval request

```bash
curl -X POST http://127.0.0.1:8000/api/governance/approve/request-supersede \
  -H "Content-Type: application/json" \
  -d '{
    "current_doc_id": "doc-hospital-los",
    "replacement_doc_id": "doc-hospital-los-v2",
    "requested_by": "local_operator",
    "reason": "Updated with 2026 guidelines and validation",
    "affected_count": 3
  }'
# If BOH_OPERATOR_TOKEN is set, add: -H "X-BOH-Operator-Token: <token>"
```

**Expected response:**
```json
{
  "ok": true,
  "approval_id": "apr-abc12345",
  "status": "pending",
  "created_ts": 1718620800
}
```

**Verify:** `GET /api/governance/approve/pending` → approval appears with status `pending`.

#### Sub-step F.2: Preview impact of the supersede

Before approving, check what documents reference the current canonical:

```bash
curl http://127.0.0.1:8000/api/governance/approve/doc-hospital-los/impact
```

**Expected response:**
```json
{
  "doc_id": "doc-hospital-los",
  "impact_count": 3,
  "impacted_docs": [
    {"doc_id": "related-doc-1", "title": "Intake Protocol A", "relationship": "superseded_by"},
    {"doc_id": "related-doc-2", "title": "Intake Protocol B", "relationship": "superseded_by"},
    {"doc_id": "related-doc-3", "title": "Intake Protocol C", "relationship": "superseded_by"}
  ]
}
```

#### Sub-step F.3: Approve the request

```bash
curl -X POST http://127.0.0.1:8000/api/governance/approve/apr-abc12345/approve \
  -H "Content-Type: application/json" \
  -d '{
    "reviewed_by": "local_operator",
    "review_note": "Approved — updated content validated against 2026 guidelines, no inconsistencies detected"
  }'
# If BOH_OPERATOR_TOKEN is set, add: -H "X-BOH-Operator-Token: <token>"
```

**Expected response:**
```json
{
  "ok": true,
  "approval_id": "apr-abc12345",
  "authority_result": "approved",
  "provenance_artifact": "prov-xyz789",
  "state_changed_ts": 1718621000
}
```

**Verify:**
- `GET /api/governance/approve/pending` → approval no longer appears (status now `approved`)
- `GET /api/governance/approve/doc-hospital-los/provenance` → approval appears in the full provenance chain

#### Sub-step F.4 (alternative): Reject a request

Create another request (e.g., for a patch) and reject it instead:

```bash
curl -X POST http://127.0.0.1:8000/api/governance/approve/request-patch \
  -H "Content-Type: application/json" \
  -d '{
    "doc_id": "doc-hospital-los",
    "patch_summary": "Fix typo in section 2.3",
    "diff_hash": "abc123def456...",
    "requested_by": "local_operator",
    "reason": "Minor typo correction"
  }'
# If BOH_OPERATOR_TOKEN is set, add: -H "X-BOH-Operator-Token: <token>"
# Capture the approval_id from response
```

Then reject:

```bash
curl -X POST http://127.0.0.1:8000/api/governance/approve/apr-def67890/reject \
  -H "Content-Type: application/json" \
  -d '{
    "reviewed_by": "local_operator",
    "review_note": "Rejected — patch introduces unnecessary whitespace changes; defer to next release cycle"
  }'
# If BOH_OPERATOR_TOKEN is set, add: -H "X-BOH-Operator-Token: <token>"
```

**Expected response:**
```json
{
  "ok": true,
  "approval_id": "apr-def67890",
  "authority_result": "rejected",
  "state_changed_ts": 1718621200
}
```

**Surfaces lit:**
- Approval workflow with immutable provenance
- Impact preview before destructive changes
- Rejection (non-destructive path)

**Verify:**
- `GET /api/governance/approve/ledger?status=rejected` → shows rejected approval
- `GET /api/governance/approve/ledger?action_type=supersede` → shows all supersede approvals

### Step G — Duplicate Review Workflow

**Precondition:** Requires two documents with similar content (hash-detected duplicates). The demo-seed does not auto-create duplicates; you may run a second demo-seed or use existing demo docs.

#### Sub-step G.1: List candidate duplicates

```bash
curl http://127.0.0.1:8000/api/duplicates
```

**Expected response:**
```json
{
  "count": 2,
  "duplicates": [
    {
      "lineage_id": "lin-abc123",
      "doc_id": "doc-xyz789",
      "related_doc_id": "doc-uvw456",
      "relationship": "duplicate_content",
      "detected_ts": 1718620000,
      "doc_path": "library/docs/file1.md",
      "related_path": "library/docs/file1_backup.md"
    }
  ]
}
```

#### Sub-step G.2: Record a decision (canonical)

Choose one as canonical, keep the other as supplementary:

```bash
curl -X POST http://127.0.0.1:8000/api/duplicates/decision \
  -H "Content-Type: application/json" \
  -d '{
    "doc_id": "doc-xyz789",
    "related_doc_id": "doc-uvw456",
    "decision": "canonical",
    "note": "file1.md is the authoritative version; file1_backup.md is a mirror"
  }'
# If BOH_OPERATOR_TOKEN is set, add: -H "X-BOH-Operator-Token: <token>"
```

**Expected response:**
```json
{
  "ok": true,
  "decision": "canonical",
  "reviewed_ts": 1718621000,
  "deletes_files": false
}
```

**Verify:**
- `GET /api/docs/doc-xyz789` → authority should reflect canonical preference (in audit ledger)
- File `library/docs/file1_backup.md` **still exists** — no deletion occurred

#### Sub-step G.3 (alternative): Mark as ignored

If the duplicate is a false positive (documents are semantically different despite hash collision):

```bash
curl -X POST http://127.0.0.1:8000/api/duplicates/decision \
  -H "Content-Type: application/json" \
  -d '{
    "doc_id": "doc-abc999",
    "related_doc_id": "doc-def888",
    "decision": "ignored",
    "note": "Hash collision; documents are semantically distinct (one is template, one is instance)"
  }'
# If BOH_OPERATOR_TOKEN is set, add: -H "X-BOH-Operator-Token: <token>"
```

#### Sub-step G.4 (containment): Quarantine duplicates

If both copies are unreliable and should be held from retrieval:

```bash
curl -X POST http://127.0.0.1:8000/api/duplicates/decision \
  -H "Content-Type: application/json" \
  -d '{
    "doc_id": "doc-corrupt1",
    "related_doc_id": "doc-corrupt2",
    "decision": "quarantine",
    "note": "Both copies failed validation; both isolated to quarantine pending review"
  }'
# If BOH_OPERATOR_TOKEN is set, add: -H "X-BOH-Operator-Token: <token>"
```

**Result:**
- Both docs marked with `canonical_layer='quarantine'` and `authority_state='quarantined'`
- Both excluded from retrieval and Fold calculations
- **Files remain on disk** — containment is logical, not destructive

**Surfaces lit:**
- Duplicate detection and decision recording
- Four decision types (`canonical` / `duplicate` / `ignored` / `quarantine`)
- Audit trail for duplicate reviews
- **No file deletion guarantee** — files are always preserved

**Verify:**
- `GET /api/docs` → check `canonical_layer` and `authority_state` fields
- `GET /api/governance/log?action_type=duplicate_decision` → shows decision audit trail

### Step H — Events Export (Optional)

**Precondition:** Requires at least one document with lifecycle events (created by any seed step).

#### Sub-step H.1: Export all system events

```bash
curl http://127.0.0.1:8000/api/events/export.ics -o system_events.ics
cat system_events.ics | head -20
```

**Expected output (ICS format):**
```
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Bag of Holding//BOH Calendar//EN
CALSCALE:GREGORIAN
METHOD:PUBLISH
BEGIN:VEVENT
UID:evt-abc123@boh
DTSTART:20260612T150000Z
DTEND:20260612T150100Z
SUMMARY:Created doc-hospital-los
DESCRIPTION:New document created by local_operator
STATUS:CONFIRMED
END:VEVENT
...
END:VCALENDAR
```

**Use case:** Import into calendar app to track approval milestones, freshness windows, or validity expirations.

#### Sub-step H.2: Export events for one document

```bash
curl 'http://127.0.0.1:8000/api/events/export.ics?doc_id=doc-hospital-los' -o doc_events.ics
```

**Expected response:** ICS stream with only events for that document.

**Verify:** Import into Apple Calendar, Google Calendar, or Outlook to visualize events.

**Surfaces lit:**
- Event lifecycle visibility
- Calendar integration
- Document-scoped event filtering

---

## 4. Intake pipeline demo (optional, needs `BOH_DATA_ROOT`)

The Governed Intake Layer (Phases 0–8) is a separate internal pipeline. It does
**not** produce canon — `canon_eligible` is **always false** by design and is
enforced at the schema level.

**Run a single-file pipeline:**

```bash
curl -X POST http://127.0.0.1:8000/api/intake/run \
  -H "Content-Type: application/json" \
  -d '{"source_ref": "<repo-root>\\data\\sample.md", "batch_id": "demo-batch-1"}'
# If BOH_OPERATOR_TOKEN is set, add: -H "X-BOH-Operator-Token: <token>"
```

The pipeline runs: capability init → preservation → translation routing →
normalization → queryability → interpretation → handoff → DB write. The response
includes `route`, `normalizable`, `queryable`, `handoff_id`,
`evidence_unit_count`, and `canon_eligible: false`.

> **`BOH_DATA_ROOT` must be set** (Section 1.2) or this returns 422.

**No-server alternative:** `python demo_intake.py` (`--keep` to retain temp
files) runs the full pipeline against a temp directory and prints every stage,
no server and no runtime-library writes.

**Read surfaces (unauthenticated):**
- `GET /api/intake/capabilities` (filter by `lifecycle_state`, `safety_lane`,
  `batch_id`)
- `GET /api/intake/adapters` (coverage report)
- `GET /api/intake/safety-lanes`
- `GET /api/intake/quarantine`

---

## 5. UI walkthrough order (after seeding)

1. **Dashboard** — swimlanes, Confidence/Epistemic Health, Corpus Class
   Distribution.
2. **Inbox** — START HERE toolbar (Clean / Load Demo Project / Seed Fixtures /
   Reset / Verify).
3. **Library** — use the top-bar logical-library selector, then inspect
   Documents, Search, and PlaneCards under that browsing filter.
4. **Search** — `viability`, `contradiction`, `governance`, Daenary filters;
   Score Formula Reference.
5. **Conflicts** — advisory pairs surface; **Acknowledge ≠ resolve**; no
   auto-resolution.
6. **Duplicate Review** — hash-detected candidates (Step G); four decision types;
   files never deleted.
7. **Bulk Import** — re-index / upload paths; repeated identical upload is
   skipped as unchanged rather than duplicated.
8. **Graph Lab** — Web → Evidence State → Risk Map → Authority Path; select a
   node to load the Fold Snapshot.
9. **Fold Workspace** — Web / Risk Map / Authority Path / Evidence State /
   Currentness Map / Timeline; expand a project cluster, adjust View toolkit
   label/edge/fold controls, then open Actions.
10. **Resolution Center** — Canon Resolution, Approval ledger (Step F),
    Certification, Policies, Audit Log.
11. **Proposed Changes** — see Section 8 (deferred for demo seed).
12. **System Status** — diagnostics + Verification Dashboard (run Verify).
13. **Domains** — PlaneCard table after Step D.
14. **Intake** — capabilities / adapters / safety-lanes / quarantine.
15. **Activity Log** — audit trail; corpus/audit JSON export; ICS calendar export
    (Step H).

---

## 6. What this proves vs. what is deferred

### Proven (verified against code)

- Governed library writes, indexing, FTS search with explainable scoring.
- Logical-library browsing filters for Library Documents/Search/PlaneCards and
  Fold Workspace, without changing retrieval, intake, promotion, authority, or governance
  context.
- Bulk upload idempotency for unchanged same filename/content/target uploads.
- Authority-state spread and Fold Workspace projections (`/api/fold/library` +
  `/api/graph/projection`).
- Read-only project cluster UI, measured-coordinate cluster expansion, Cluster Focus, and Action
  Queue over existing fold/graph endpoints.
- Resolver-backed `CurrentFoldPacket` per node with `scale_actions`, scalar
  pressures, unknowns, and a compact trace.
- Conflict surfacing with **no auto-resolution**; Acknowledge is not resolve.
- PlaneCard (PCDS) wrapping/backfill with preserved source refs.
- Graph Lab Web / Evidence State / Risk Map / Authority Path projections.
- Governed Intake pipeline end-to-end with `canon_eligible` permanently false.
- **Approval workflow** (Step F): request supersede/patch/edge, impact preview,
  approve/reject with immutable provenance artifacts, audit trail.
- **Duplicate decision** (Step G): detect hash-based duplicates, four decision
  types (canonical/duplicate/ignored/quarantine), no file deletion, containment
  (not destructive).
- **Events export** (Step H): ICS calendar format for lifecycle events, doc-scoped
  filtering, calendar app integration.
- Operator boundary: enforced when `BOH_OPERATOR_TOKEN` set, dev-open when unset.

### Deferred / not claimed

- **Fold View remaining work**: full resolver trace endpoint depth and 3D
  Spatial Lab are **deferred**. `GET /api/fold/node/{doc_id}/trace` returns
  `available: false` by design. Cluster/corpus aggregation plus project and
  linked-domain Fold Workspace folds exist. Batch corpus UX remains beyond the
  current demo scope.
- **Proposed Changes queue**: the demo seed **does not fabricate** LLM proposals.
  `Proposed Changes` becomes meaningful only after an authenticated LLM proposal
  enqueue (`POST /api/llm/queue`) or an Ollama invocation. Ollama is optional and
  off unless configured.
- **Canon from intake**: intake **never** produces canon. `canon_eligible` is
  always `false` (schema-enforced). The demo must not imply otherwise.
- Correction-ledger API/UI exposure, certificate-backed card promotion, and
  enforced plane-interface receipts are intentionally deferred.

---

## 7. Optional orchestrator

`demo_showcase.py` (repo root) is a thin, operator-run orchestrator that
sequences the existing entrypoints above. It defaults to `--dry-run` (prints the
plan, runs nothing). See its top docstring. It implements no new seeding logic.

```bash
python demo_showcase.py            # dry-run: prints the plan, no writes
python demo_showcase.py --execute  # operator opt-in: runs the existing seeds
```

---

## 8. Reference

- Live route authority: `http://127.0.0.1:8000/docs` and `/openapi.json`.
- Capability expectations: `tests/test_demo_capability_manifest.py`.
- Folded-node view: `docs/visualization_folded_node_view.md`.
- Scoring formulas: `docs/math_authority.md`.
- Current state of record is maintained in the private working repository's
  operational records.
