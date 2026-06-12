# BOH ↔ Metis Retrieval Contract — v0.1 (PROPOSED)

> **STATUS: PROPOSED DRAFT.** Describes the intended wire contract between the BOH
> retrieval API (provider, source of truth) and the Metis Head consumer. The
> **additive fields** marked _(new in v0.1)_ are not yet implemented; they are authorized
> only under the approved work order (`boh_metis_retrieval_contract_v0_1`). All other
> fields document current behavior verified
> against `app/core/retrieval.py` and `app/api/routes/retrieval_routes.py`.

## 1. Roles and boundary

- **BOH** is the provider and single source of truth. It owns the corpus, ranking,
  governance gate, and audit.
- **Metis** is a read-only consumer. It MUST NOT mirror or own the BOH corpus, MUST NOT
  mutate BOH, and MUST NOT hold or send the BOH **operator** token.
- Retrieval is **read-only** and authenticated only by the retrieval token (below).

## 2. Authentication

- Header: `X-BOH-Retrieval-Token: <token>` on all protected retrieval calls.
- Validated against env `BOH_RETRIEVAL_TOKEN`.
  - No expected token configured → `403`.
  - Missing header → `401`.
  - Mismatch → `403`.
- The **operator** token (`BOH_OPERATOR_TOKEN`) is for mutations and is **never** accepted
  or required by any retrieval route. Metis never receives it.

## 3. Endpoints

| Method | Path | Auth | Purpose |
| ------ | ---- | ---- | ------- |
| GET | `/api/retrieve/status` | none | Liveness/config probe |
| POST | `/api/retrieve` | retrieval token | Governed retrieval (canonical) |
| GET | `/api/retrieve` | retrieval token | Query-param variant |

### 3.1 `GET /api/retrieve/status`

No auth. Returns:

```json
{
  "configured": true,
  "header_name": "X-BOH-Retrieval-Token",
  "read_only": true,
  "operator_token_required": false,
  "protected_routes_fail_closed": true
}
```

`configured` is `true` when `BOH_RETRIEVAL_TOKEN` is set. Metis Phase 0C uses this as its
health probe.

## 4. Request

`POST /api/retrieve` body (`RetrieveRequest`):

| Field | Type | Default | Notes |
| ----- | ---- | ------- | ----- |
| `query` | string | required | Search query |
| `limit` | int | impl default | Range 1–25 |
| `max_context_chars` | int | impl default | Range 500–30000 |
| `mode` | enum | `strict_answer` | See §5 |
| `include_lineage` | bool | true | Include lineage block per pack |
| `doc_id` | string? | null | Filter |
| `status` | string? | null | Filter |
| `authority_state` | string? | null | Filter |
| `canonical_layer` | string? | null | Filter |
| `project` | string? | null | Filter |
| `chunk_type` | string? | null | Filter |

Invalid input → `422`.

## 5. Modes

- `strict_answer` — tightest gating; only directly admissible canonical context.
- `exploration` — broader recall for ideation.
- `audit_provenance` — provenance/lineage emphasis.
- `canon_review` — canon-candidate review surface.
- `low_b_worker_context` — minimal worker context.

(Mode governs gate posture and selection; it does not change the response shape.)

## 6. Response

Top-level object:

```json
{
  "query": "...",
  "count": 0,
  "context_packs": [ /* see §6.1 */ ],
  "excluded_summary": [ /* existing: list of exclusion entries, each with a "reason" */ ],
  "audit_context": { /* existing */ },
  "retrieval": { /* existing echo: mode, limit, etc. */ },
  "planar_context_pack": { /* existing */ },
  "gate_result": { /* see §6.2 */ },
  "warnings": ["..."]            // (new in v0.1) rolled-up, de-duped, order-stable
}
```

### 6.1 Context pack

Existing keys (unchanged): `chunk_id`, `doc_id`, `title`, `path`, `snippet`, `text`,
`source_span` (single dict: `byte_start`/`byte_end`/`token_start`/`token_end`),
`heading_path`, `chunk_type`, `lifecycle_state`, `authority_state`, `status`,
`canonical_layer`, `provenance`, `conflicts`, `lineage`, `citation` (dict:
`doc_id`/`path`/`title`/`heading_path`/`source_hash`/`chunk_id`), `warnings` (list),
`do_not_treat_as_canonical`, `score`, `why_selected`.

Additive keys _(new in v0.1)_:

- `citation_uri` — string, `boh://{doc_id}#{chunk_id}`. Deterministic; derived from
  `citation`. Omitted/null only if `doc_id` or `chunk_id` is missing.
- `source_spans` — list of span dicts (`byte_start`/`byte_end`/`token_start`/`token_end`).
  Mirrors `source_span` as a length-0/1 list today; allows multi-span chunks later. The
  scalar `source_span` is retained unchanged.

**`plane_card` packs (null-case).** Plane-card packs have `chunk_id: null` and
`source_span: null` (they cite a card, not a document chunk). For these packs:
`citation_uri` MUST be `null` (omitted), because the `boh://{doc_id}#{chunk_id}` form
requires a chunk id; and `source_spans` MUST be `[]`. The existing `citation` dict (which
carries `card_id`) and `card_id` field remain the way to reference such packs.

### 6.2 `gate_result`

Existing keys (unchanged): `context_pack_id`, `posture`, `blocking_reasons`,
`warning_reasons`, `allowed_context_refs`, `withheld_context_refs`, `required_route`,
`trace_event_type`, `l6_proposal_allowed`, `l6_proposal_types`, `context_allowed_basis`,
`created_ts`.

> Note: there is no top-level `allowed` or `canon_eligible` boolean in `gate_result`.
> Consumers must derive admissibility from `posture` / `blocking_reasons`.

### 6.3 Top-level `warnings` _(new in v0.1)_

A list of strings rolling up, in stable order and de-duplicated:

1. `gate_result.blocking_reasons`
2. `gate_result.warning_reasons`
3. distinct per-pack `warnings`
4. exclusion reasons from `excluded_summary`

Intended as the single surface Metis shows to the user / injects into the prompt as
governance caveats. Source structures remain available unchanged.

## 7. Consumer expectations (Metis side, informative)

- Cite using `citation_uri`; fall back to building from `citation` if absent.
- Treat `do_not_treat_as_canonical: true` packs as non-authoritative.
- Surface top-level `warnings` to the user and/or the model context.
- Map transport/gate failures to its own `source_state` (`sourced` / `unsourced` /
  `degraded`); these are Metis-internal and not part of this contract.

## 8. Compatibility

- v0.1 is **additive only**. No existing key is removed or renamed.
- Consumers MUST ignore unknown keys.
- A bump to v0.2+ is required for any breaking change.
