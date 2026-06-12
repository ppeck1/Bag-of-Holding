# Headless /v2 UI drive

Exercises the real `app/ui2/` ES-module screens against a LIVE running server, with a
Node DOM stub + real `fetch`. No browser needed. Catches the class of bugs that pure
Python tests and `node --check` miss: ES-module link/parse errors that blank the SPA,
broken endpoints, un-rendered data, and dead interactions (clicks, tab switches).

## Run — one command (recommended)
From the repo root:
```
python tools/ui_drive/run_drive.py
```
Spins up a throwaway server on a free port against a TEMP db + library (your real `boh.db`
is never touched), seeds the full demo data (`seed_ui_demo.py` self-seeds a varied doc set
when the DB is empty), drives the real `/v2` UI, prints the PASS/FAIL report, and tears
everything down. Exit code 0 iff every check passes. `--keep` leaves the server up;
`--port N` pins the port. Needs `node` on PATH.

## Run — manual (against an existing server)
```
python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8141 &
python seed_ui_demo.py          # governance/intake/trace/residence (+docs if DB empty)
cd tools/ui_drive && BOH_BASE=http://127.0.0.1:8141 node drive_all.mjs
```
Prints a PASS/FAIL line per screen + interaction. Reads `app/ui2/js` directly (no copy).

## Components
- `run_drive.py` — one-command orchestrator (server + seed + drive + teardown).
- `drive_all.mjs` — the interactive drive (every screen/tab/interaction).
- `render_check.mjs` — server-free boot-render guard (used by `tests/test_ui2_phase_a.py`).
- `dom.mjs` — DOM stub + real-fetch shim.

## What it covers
Current State, Fold (render + node click→inspector + breadcrumb + all 6 projections +
Canvas/List), Library (+search), Review (all 4 tabs + Admit/Reject), Authority (all 4
tabs incl. Trace & Gates), Capture (all 6 tabs + forms), Context Pack, Settings, Activity
(+Export), Shell (Sidebar/TopBar/AlertsDrawer).
