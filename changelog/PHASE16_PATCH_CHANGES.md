# Bag of Holding v2 — Phase 16 Patch Applied

Source patch: Phase 16 Visualization Layer + Lifecycle Clarity.

## Applied changes

- Renamed **Connections** to **Visualization** across active UI copy and copy_map.js.
- Added Visualization mode controls:
  - Web
  - Variable Overlay
  - Constraint Geometry
  - Constitutional
- Preserved the existing graph as the default Web View.
- Added non-destructive overlay renderers for Variable Overlay, Constraint Geometry, and Constitutional views.
- Added a visible lifecycle ladder on Dashboard:
  - Inbox → Review → Stable → Canonical → Archive
- Made Simple / Advanced behavior more meaningful:
  - Simple mode hides lower-level graph filters and performance machinery.
  - Advanced mode keeps the instrumentation visible.
- Added Duplicate Review surface:
  - Lists duplicate candidates from `/api/duplicates`.
  - Shows original path, duplicate path, similarity basis, and authority state.
  - Offers Mark Canonical, Mark Duplicate, Mark Ignored, Copy File Path, and Open in Visualization.
  - Does not delete files.
- Added compatibility aliases so renamed Visualization buttons still delegate to the existing Atlas graph functions.
- Updated asset cache query strings to `v=16-visualization`.

## Notes

This patch is intentionally UI-first and non-destructive. It does not rewrite the database schema or perform filesystem deletion. Duplicate disposition persistence is currently local-session only and should be wired to governance/audit storage in a later backend patch.

## Verification performed

- `node --check app/ui/app.js` passed.
- Active `index.html` includes `/copy_map.js?v=16-visualization`.
- Active `index.html` includes Visualization mode buttons.
- Active `index.html` includes Duplicate Review panel and navigation item.
