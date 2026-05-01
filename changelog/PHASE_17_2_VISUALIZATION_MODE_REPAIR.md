# Phase 17.2 Visualization Mode Repair

## Issue confirmed from screenshots

The visualization repair was only partial.

Constraint Geometry still returned `HTTP 422: [object Object]` because the frontend button sent `geometry`, while the backend projection endpoint only accepted `constraint`.

Variable Overlay and Constitutional did return data, but the visual mode overlay was acting like the primary surface and not an instrument panel. It obscured the graph and only showed thin aggregate counts, so the modes technically loaded but did not communicate much.

## Patch applied

### 1. Mode contract normalized

Frontend now normalizes visualization modes before requesting projection data:

- `geometry` -> `constraint`
- `constraint-geometry` -> `constraint`
- `structural` -> `web`
- valid modes retained: `web`, `variable`, `constraint`, `constitutional`

The Constraint Geometry button now uses:

```js
setVisualizationMode('constraint')
```

The backend projection endpoint now accepts the old aliases defensively:

```txt
geometry
constraint-geometry
```

and maps them to `constraint`.

### 2. Constraint Geometry 422 repair

The 422 was not a metric serializer failure in this case. It was a route/query contract mismatch.

The query parameter validator rejected `mode=geometry`.

This is now repaired in both frontend and backend.

### 3. Overlay no longer hides the graph

The non-web visualization overlay is now transparent and pointer-passive outside the instrument panel.

The graph remains visible and interactive behind the mode explanation.

### 4. Mode panels now explain more

Variable Overlay, Constraint Geometry, and Constitutional now show:

- node count
- edge count
- canonical count
- high-risk count
- approved edge count
- suggested edge count
- variable hit summary
- highest-risk node table with risk/loss values
- projection loss summary

This makes the mode answer something operational instead of merely saying the mode name.

## Remaining design note

These modes are still heuristic v1 projections. They are now wired correctly, but their value will depend on richer imported metadata:

- real project assignment
- document class assignment
- canonical/supporting/evidence layer assignment
- authority state
- review state
- lineage and promotion records
- variable tagging beyond lexical fallback

Without that metadata, the visualizations will load but remain semantically thin.
