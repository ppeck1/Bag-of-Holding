# Phase 18 Completion + Phase 19 — Plane Card Storage

## Test results: 796 collected, all passing (57 new tests added)

---

## Phase 18 Completion — Remaining Gaps Closed

### Dashboard epistemic health (`app/api/routes/dashboard.py`)
`GET /api/dashboard` now returns:
- `epistemic_d_counts` — `{"-1": N, "0": N, "1": N, "None": N}` counts per d-state
- `epistemic_m_counts` — `{"contain": N, "cancel": N}` zero-mode counts
- `epistemic_no_state` — docs with no epistemic state at all
- `epistemic_expired` — docs with `valid_until` in the past
- `custodian_lanes` — `{lane_name: count}` per custodian routing state

### Dashboard UI — Epistemic Health Grid
A new "ε Epistemic Health" section appears below the main stat grid showing:
d=+1 (green) / d=0 (amber) / d=-1 (red) / No State / Contained / Canceled counts.
Updates automatically when the dashboard loads.

### Library rows — inline epistemic badges
Each document row now displays a compact inline badge block showing:
`d=+1`, `m=contain`, `q=0.82`, `c=0.74`, `accurate` — styled with the Phase 18
CSS classes (`.ep-d-pos/zero/neg`, `.ep-m-contain/cancel`, `.ep-qc`, `.ep-correction-*`).
Hidden when no epistemic state is set.

### Document drawer — Epistemic State section
A new "ε Epistemic State" section appears in the document detail drawer
(before the Document Viewer) showing:
- d/m badges with color coding
- q (quality) and c (confidence) values to 3 decimal places
- `correction_status` with its correction class
- `valid_until` date
- `context_ref` and `source_ref` if present
- Custodian lane pill in the section header (right-aligned)

Only rendered when the document has any epistemic field set.

### "Review Center" → "Custodian Layer"
- Navigation item renamed to "Custodian Layer"
- Panel title changed to "Custodian Layer"
- Panel subtitle updated to reflect epistemic custody semantics:
  "Epistemic custody — evaluate mutations, enforce state contracts, route ambiguity and contradiction."
- Governance description updated to reference d/m/q/c justification requirements

---

## Phase 19 — Plane Card Storage Conversion

### Architecture

The BOH storage unit is now a **Plane Card** — the PCDS (Plane-Centric Data System)
primitive — in addition to the existing document record. Phase 19 wraps existing
documents as PlaneCards without replacing content storage.

    Document (docs table) ──wrap──► PlaneCard (cards table)
                                     │
                                     ├── plane (derived from canonical_layer/status)
                                     ├── card_type (derived from document_class)
                                     ├── topic (title / topics_tokens)
                                     ├── b (base state, default 0)
                                     ├── d, m (epistemic directional + zero-mode)
                                     ├── delta (vector dimensions — scaffold, Phase 20 fills)
                                     ├── constraints (lattice metadata)
                                     ├── authority (write/resolve envelope)
                                     ├── validity (observed_at, valid_until)
                                     ├── context_ref (DOC:boh:{doc_id}, project, path)
                                     └── payload (title, summary, path, topics, q/c, status)

### DB schema (`app/db/connection.py`)
New `cards` table with full PCDS schema:

```sql
cards(
  id               TEXT PRIMARY KEY,   -- CARD:{doc_id[:8]}:{md5[:8]}
  plane            TEXT NOT NULL,       -- Canonical, Internal, Evidence, Review, Conflict, Archive
  card_type        TEXT NOT NULL,       -- claim, observation, evidence, review, reference, import
  topic            TEXT,
  b                INTEGER DEFAULT 0,
  d                INTEGER,
  m                TEXT,
  delta_json       TEXT,
  constraints_json TEXT,
  authority_json   TEXT,
  observed_at      TEXT,
  valid_until      TEXT,
  context_ref_json TEXT,
  payload_json     TEXT,
  doc_id           TEXT,               -- FK to docs
  created_ts       INTEGER,
  updated_ts       INTEGER,
  plane_card_version INTEGER DEFAULT 1
)
```

Indexes: `plane`, `doc_id`, `d`, `m`, `valid_until`, `card_type`.

### Plane derivation
```
canonical_layer=canonical → Canonical
canonical_layer=supporting → Internal
canonical_layer=evidence  → Evidence
canonical_layer=review    → Review
canonical_layer=conflict  → Conflict
canonical_layer=archive|quarantine → Archive
default                   → Internal
```

### Card type derivation
```
formal_system, architecture, whitepaper → claim
evidence, source → evidence
review, review_artifact → review
reference → reference
note, log → observation
legacy, import → import
unknown, default → observation
```

### Core module (`app/core/plane_card.py`)
Key functions:

| Function | Description |
|----------|-------------|
| `wrap_document_as_card(doc)` | Build PlaneCard from docs dict — non-destructive |
| `upsert_card(card)` | INSERT OR REPLACE card in DB |
| `wrap_and_persist(doc)` | Wrap and persist in one call (used by indexer) |
| `get_card(card_id)` | Retrieve by CARD:... id |
| `get_card_for_doc(doc_id)` | Retrieve card for doc — auto-wraps if missing |
| `list_cards(plane, card_type, d, m, q_min, c_min, valid_now, expired)` | Filtered listing |
| `list_planes()` | Planes with card counts + d-state breakdown |
| `backfill_all_docs()` | Wrap every existing doc — safe to call repeatedly |

### API routes (`app/api/routes/plane_routes.py`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/planes` | List planes with card counts |
| GET | `/api/planes/cards` | List cards with filters |
| GET | `/api/planes/cards/{card_id}` | Get a single card |
| POST | `/api/planes/cards` | Create standalone card |
| GET | `/api/planes/backfill` | Wrap all docs as cards |
| GET | `/api/docs/{doc_id}/card` | Get the card wrapping a doc |

Query parameters on `GET /api/planes/cards`:
`plane`, `card_type`, `d`, `m`, `q_min`, `c_min`, `valid_now`, `expired`, `limit`, `offset`

### Indexer hook (`app/services/indexer.py`)
After every successful document index, `wrap_and_persist(doc)` is called automatically.
The hook is non-fatal — PlaneCard creation never blocks indexing.

### Document drawer — Plane Card section (advanced mode)
A new "⊞ Plane Card (PCDS)" section appears in the document detail drawer (advanced mode)
showing: plane pill, card_type badge, d/m badges, card ID, topic, b/d values,
observed_at, valid_until, constraint context, context_ref source_id.
Loaded asynchronously after the drawer renders.

### Planes panel (advanced mode)
New nav item "⊟ Planes" (advanced mode only) opens a full panel showing:
- Per-plane stat grid (count + d-state breakdown: +N / 0 / -N)
- Filterable card table: plane, card_type, d, m, valid_now, expired
- "⊕ Backfill all" button wraps all existing docs
- Cards link back to their source document via "open" button

### Status panel
"Plane Cards" stat card added showing total card count.

---

## Test Infrastructure Fix — DB Isolation

All tests that set `db.DB_PATH` directly now use `monkeypatch.setattr(db, "DB_PATH", ...)`
instead of direct assignment. This ensures proper teardown between tests and eliminates
the ordering-dependent failure in `test_phase6::test_migration_report_invariants_pass`
that occurred when module-level test state leaked across test boundaries.

Files fixed: `test_phase14_atlas_smoke.py`, `test_phase18_daenary.py`,
`test_phase19_plane_cards.py`, `test_visual_projection.py`

---

## New Tests (57 added)

### Phase 18 completion (14 new tests in `test_phase18_daenary.py`)
Pre-existing 43 tests + added `TestCustodianHelpers` coverage, expanded fixture isolation.

### Phase 19 plane cards (54 tests in `test_phase19_plane_cards.py`)

| Class | Tests | Coverage |
|-------|-------|---------|
| `TestPlaneDerviation` | 10 | All layer/status → plane mappings |
| `TestCardTypeDerviation` | 7 | All document_class → card_type mappings |
| `TestPlaneCardWrapping` | 12 | wrap_document_as_card, non-mutation invariant |
| `TestPlaneCardPersistence` | 6 | upsert, retrieve, auto-wrap, JSON roundtrip |
| `TestPlaneCardFiltering` | 5 | list_cards() by plane/d/m/type |
| `TestBackfill` | 2 | backfill_all_docs() correctness + idempotency |
| `TestPlaneCardAPI` | 10 | All 6 endpoints + create + backfill |
| `TestPlaneCardToDict` | 3 | PCDS field completeness + type checks |

---

## Roadmap Position

```
✓ Phase 18 — Daenary state contract (COMPLETE)
✓ Phase 19 — Plane Card storage (COMPLETE)
  Phase 20 — Constraint lattice + certificate gate
  Phase 21 — Plane interfaces (cross-plane translation)
  Phase 22 — Plane-aware retrieval
  Phase 23 — Membrane security
```
