# Planar Gate + Correction Ledger

Status: experimental branch work for `experimental/planar-storage-v1105-gate-evaluator`.

## Scope

This layer adds deterministic retrieval governance and audited correction records around BOH's existing retrieval and PlaneCard substrate.

It does not replace:

- `docs`
- `cards`
- `plane_cards`
- `/api/retrieve`
- actor authority
- operator-token authorization
- LLM proposal review

## Runtime Objects

`ContextPack` names the query, operation, actor, mode, candidate refs, expected planes, retrieved planes, and missing planes.

`GateResult` records the deterministic gate outcome:

- `answerable`
- `bounded`
- `review_required`
- `blocked`

It also records allowed refs, withheld refs, blocking reasons, warning reasons, required route, trace event type, L6 proposal flags, and per-ref allowed basis.

## Correction Records

The correction ledger stores:

- `planar_gate_results`
- `planar_mistake_events`
- `planar_patch_proposals`
- `planar_canon_change_records`
- `planar_information_residence_map`
- `planar_fixture_cases`

Hard rules:

- `PatchProposal.forbidden_auto_apply` is always forced true.
- Approved corrections require reviewer/owner adjudication.
- Patch approval creates correction records only.
- Approval does not silently mutate canon, schema, routing, source trust, scalar thresholds, dominance policy, validity windows, or gate rules.
- Non-schema behavior corrections require regression fixture refs.

## Fixture Boundary

The fixture pack is mechanically extracted from:

`planar_storage_flow_atlas_v1_10_5_6_display_no_loss.html`

into:

`tests/fixtures/planar_storage_v0_3_self_correction.json`

The fixture evaluator guarantees that every fixture case is evaluated and mismatches are explicit. Passing fixtures prove deterministic gate behavior for those cases only. They do not prove production classification quality, calibration stability, reviewer agreement, labor burden, or active self-improvement.

## Not Wired Yet

- `/api/planar/*` route module
- Planar Gate UI panel
- Correction Ledger UI panel
- Residence Map UI panel
- Active L6 behavior

