# Phase 17.3 — Visualization Redesign: Semantic Mode Separation

## Problem Addressed

All four visualization modes (Web, Variable Overlay, Constraint Geometry, Constitutional) were
rendering the same organic relationship graph with different labels — "mode collapse." Position,
color, size, edge filtering, and sidebar interpretation were identical across modes.

## Design Principle

Each mode now answers a distinct operational question:

| Mode | Question | Primary Structure |
|------|----------|-------------------|
| Web | What is connected? | relationship network |
| Variable Overlay | Where do modeled variables appear? | variable intensity map |
| Constraint Geometry | Where is instability forming? | risk/pressure geometry |
| Constitutional | What can be trusted or changed? | authority/provenance lanes |

---

## Backend Changes — `app/core/visual_projection.py`

### Projection Contract
`get_projection_graph()` now returns a full semantic contract:

```json
{
  "mode": "constraint",
  "projection_id": "constraint_geometry_v1",
  "nodes": [],
  "edges": [],
  "layout": { "type": "geometry", "x_semantic": "...", "y_semantic": "...", "scale": {} },
  "legend": {},
  "sidebar": {},
  "diagnostics": [],
  "projection": {}
}
```

No frontend guessing. The backend declares what each axis, color, and size means.

### Constants Added
- `PROJECTION_IDS` — maps mode → projection_id string
- `LANE_X` — constitutional lane center positions `{draft:0.10, review:0.28, approved:0.50, canonical:0.72, archived:0.90}`
- `LANE_BOUNDARY_X` — divider positions `[0.19, 0.39, 0.61, 0.81]`
- `CONSTRAINT_ZONE_COLORS` — `{critical:#ef4444, high-risk:#f97316, watch:#f59e0b, stable:#22c55e}`

### Mode-Specific Layout Functions
- `_layout_web()` — organic project/class cluster (unchanged)
- `_layout_variable()` — same positions as web; signal carried by color and size
- `_layout_constraint()` — x = project band (0.1–0.9), y = `1.0 − risk_score` so highest risk nodes float to top
- `_layout_constitutional()` — x = `LANE_X` center for each node's authority lane, y = evenly distributed within lane

### Node Field Helpers
- `_variable_node_fields(variables)` → `{dominant_variable, variable_hits, variable_confidence, size_metric}`
- `_constraint_zone(metrics)` → `critical | high-risk | watch | stable` from drift_risk / conflict_pressure thresholds
- `_get_lane(node)` → `canonical | archived | approved | review | draft`
- `_get_mutation_state(lane)` → `locked | restricted | mutable`
- `_get_approval_state(node)` → `approved | pending | draft`
- `_constitutional_node_fields(node, has_lineage_out)` → full authority envelope

### All Mode Fields on Every Node
Every node now carries the complete field set regardless of mode so the frontend can switch
rendering without a new API call:
`dominant_variable`, `variable_hits`, `variable_confidence`, `size_metric`,
`constraint_zone`, `conflict_pressure`, `review_debt`, `drift_risk`,
`lane`, `mutation_state`, `approval_state`, `rollback_available`

### Sidebar Builders
`_sidebar_web`, `_sidebar_variable`, `_sidebar_constraint`, `_sidebar_constitutional`
each return a structured dict consumed by the frontend instrument panel.

### Legend Builders
`_legend_web`, `_legend_variable`, `_legend_constraint`, `_legend_constitutional`
each return mode-specific color/size/axis semantics.

### Diagnostics
`_diagnostics(mode, nodes, edges)` emits named warnings:
- `ZERO_NODES`
- `NO_VARIABLE_DATA`
- `NO_RISK_FIELDS`
- `NO_AUTHORITY_FIELDS`
- `NO_AUTHORITY_EDGES`

These surface in the UI rather than silently rendering a degraded graph.

---

## Frontend Changes — `app/ui/app.js`

### `_nodeColor(node)` — Mode-Aware
Checked before role-based fallback:

| Mode | Color logic |
|------|-------------|
| constraint | Zone palette: critical `#ef4444` → stable `#22c55e` |
| constitutional | Lane palette: canonical `#34d399`, approved `#60a5fa`, review `#f59e0b`, draft `#94a3b8`, archived `#475569` |
| variable | Variable palette by `dominant_variable`; `#2d3f57` for unmapped |
| web | Existing role-based logic (unchanged) |

### `_nodeRadius(node)` — Mode-Aware
- variable mode: `5 + size_metric × 1.2` (clamped 4–22)
- constraint mode: `5 + load_score × 17` (clamped 5–22)
- web / constitutional: existing authority/layer logic

### Tooltip Content — Mode-Specific
Each mode shows a distinct line set:
- **constraint**: Zone, Risk score, Load score, Conflict pressure, Review debt flag
- **constitutional**: Lane, Approval state, Mutation state, Rollback available
- **variable**: Dominant variable, Confidence %, Hit counts
- **web**: Layer, Authority, Review status, Projection loss, Load score

### Conflict Halo — Constraint Mode
Constraint mode renders a dashed ring sized by `conflict_pressure` value in `rgba(239,68,68,cp)`.

### `drawModeDecorations()` — New Canvas Overlay
Called after each frame render:
- **constraint mode**: Dashed horizontal viability threshold line at graph-y ≈ 450, labelled "VIABILITY THRESHOLD"; zone labels (HIGH RISK / STABLE) on right margin
- **constitutional mode**: Vertical lane dividers at boundary x positions (19%, 39%, 61%, 81% of 1200px); lane name headers at top of canvas

### `renderVisualizationOverlay()` — Complete Replacement
Now a mode-dispatched instrument panel replacing the prior generic description card.

Each panel includes:
- Question answered
- Coordinate / color / size / halo semantics
- "Look for" operational tip
- Top findings (from `_graphData.sidebar`)
- Diagnostic banners (from `_graphData.diagnostics`)

Panel renderers:
- `_vizDiagnosticBanner(diagnostics)` — severity-colored banners (error/warn/info)
- `_renderVariablePanel()` — variable distribution bars, mapped/unmapped counts, top variable-bearing nodes table
- `_renderConstraintPanel()` — zone pills, grammar grid, look-for tip, top risk nodes table
- `_renderConstitutionalPanel()` — lane pills, canonical sources, unresolved conflicts, rollback targets

---

## CSS Changes — `app/ui/style.css`

New classes appended:

| Class | Purpose |
|-------|---------|
| `.viz-overlay` | Flex row, right-justified (graph visible on left) |
| `.viz-instrument-sidebar` | 320px right panel, max-height with scroll |
| `.viz-panel-header`, `.viz-panel-badge`, `.viz-panel-question` | Panel header block |
| `.viz-grammar-grid` | Monospace label + value rows for coordinate semantics |
| `.viz-section-head` | Uppercase section dividers |
| `.viz-mini-stats` | 3-column stat pills |
| `.viz-zone-bar`, `.viz-zone-pill` | Zone/lane distribution pills |
| `.viz-const-list`, `.viz-const-item` | Constitutional list grid rows |
| `.viz-tip-block` | Amber left-border "look for" callout |
| `.viz-gap-notice` | Missing-data warning banner |
| `.viz-proj-footer` | Projection metadata footer |

---

## Test Results

```
655 passed, 3 skipped
```

All existing tests pass. Visual projection contract tested in `tests/test_visual_projection.py`:
- `test_projection_contract_and_metrics` — verifies all four modes return required contract fields
- `test_variable_and_constitutional_modes` — verifies mode-specific node fields and sidebar structure
