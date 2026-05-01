# Phase 17.1 Visualization Projection Hardening

Applied patch items:

- Forced Atlas renderer to use `/api/graph/projection?mode=${mode}` for all visualization modes.
- Added frontend graph normalization from `edges` only, with `source`, `target`, `type`, `weight`, and `authority` defaults.
- Pinned projection coordinates using `fx = x * 1200` and `fy = y * 900`.
- Disabled projection-destroying random scatter and force-layout explosion for projection-rendered graphs.
- Kept graph canvas visible and interactive across web, variable, constraint, and constitutional modes.
- Preserved constitutional graph rendering; explanatory content remains sidebar/overlay only.
- Added hard debug logging for mode, node count, edge count, first node, and first edge.
- Added fatal visible error when projection returns zero nodes.
- Added defensive backend `safe_float()` serialization for constraint metrics:
  - `viability_margin`
  - `load_score`
  - `projection_loss`
  - `conflict_pressure`
  - `review_debt`
  - `drift_risk`
- Hardened edge weight/risk serialization.

Verification performed:

- `node --check app/ui/app.js` passed.
- `python3 -S -m py_compile app/core/visual_projection.py app/api/routes/reader.py` passed.

Note:

- A focused pytest command against visualization tests did not complete within the available execution window, so syntax verification was completed but full test execution was not confirmed here.
