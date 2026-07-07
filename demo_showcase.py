"""demo_showcase.py -- OPTIONAL operator-run orchestrator for the BOH demo.

WHAT THIS IS
    A thin sequencer that runs the EXISTING BOH demo entrypoints in order so an
    operator can bring up a full capability demo with one command. It contains
    NO new seeding logic: every step shells out to a script that already exists
    or calls an endpoint that already exists. See docs/DEMO_RUNBOOK.md for the
    surface-by-surface mapping.

WHAT THIS WRITES
    When run with --execute, the steps it triggers WRITE TO THE RUNTIME
    library/ FOLDER AND THE SQLite DATABASE (boh.db). This script itself writes
    nothing; the existing seeds it calls do. It is intended to be run by a
    HUMAN OPERATOR, not by an automated agent. Per the repository's frozen-scope
    rules, runtime data writes require explicit operator action -- which is
    exactly what invoking this with --execute is.

DEFAULT IS DRY-RUN
    With no flags (or --dry-run) this prints the plan and runs NOTHING. You must
    pass --execute to actually run the seeds.

EXISTING ENTRYPOINTS SEQUENCED (nothing here is new):
    1. POST /api/input/demo-seed          (app/api/routes/input_routes.py)
    2. python seed_demo_library.py        (standalone, idempotent)
    3. python seed_visualization_demo.py  (standalone, writes boh.db)
    4. POST /api/planes/backfill          (Domains PlaneCard backfill)
    5. GET  /api/fold/library             (read-only verification)
    6. GET  /api/fold/node/{anchor}       (read-only verification; scale_actions)
    7. POST /api/intake/run               (optional; requires BOH_DATA_ROOT)

Usage:
    python demo_showcase.py                       # dry-run: print plan, no writes
    python demo_showcase.py --execute             # operator opt-in: run the seeds
    python demo_showcase.py --base-url http://127.0.0.1:8000
    python demo_showcase.py --execute --with-intake --intake-source path\to\file.md
    python demo_showcase.py --execute --operator-token <token>   # if enforcing
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).parent.resolve()
DEFAULT_BASE_URL = "http://127.0.0.1:8000"


# ---------------------------------------------------------------------------
# Plan model -- each step names an EXISTING entrypoint; this file adds no logic.
# ---------------------------------------------------------------------------

def build_plan(args) -> list[dict]:
    """Return the ordered list of steps. Pure data; no side effects."""
    plan: list[dict] = [
        {
            "id": "A",
            "name": "Consolidated demo project (governance + Daenary)",
            "kind": "http",
            "method": "POST",
            "path": "/api/input/demo-seed",
            "protected": True,
            "writes": "library/ + boh.db (governance/refusal + Daenary docs)",
            "surfaces": "Library, Search, Conflicts, Resolution Center, Fold node",
        },
        {
            "id": "B",
            "name": "Productivity-methods library (Fold View spread)",
            "kind": "script",
            "argv": [sys.executable, "seed_demo_library.py"],
            "protected": False,
            "writes": "library/productivity-methods/ + boh.db (idempotent)",
            "surfaces": "Library, Fold View scatter, Conflicts",
        },
        {
            "id": "C",
            "name": "Visualization / Graph Lab corpus",
            "kind": "script",
            "argv": [sys.executable, "seed_visualization_demo.py"],
            "protected": False,
            "writes": "boh.db (16 demo docs, 12 edges, governance fixtures)",
            "surfaces": "Graph Lab Web / Evidence / Risk / Authority",
        },
        {
            "id": "D",
            "name": "PlaneCard backfill (Domains)",
            "kind": "http",
            "method": "POST",
            "path": "/api/planes/backfill",
            "protected": True,
            "writes": "boh.db (plane_cards)",
            "surfaces": "Domains",
        },
        {
            "id": "E1",
            "name": "Verify Fold View scatter (read-only)",
            "kind": "http",
            "method": "GET",
            "path": "/api/fold/library",
            "protected": False,
            "writes": "none (read-only)",
            "surfaces": "Fold View",
        },
        {
            "id": "E2",
            "name": "Verify Fold node packet + scale_actions (read-only)",
            "kind": "fold_node",
            "protected": False,
            "writes": "none (read-only)",
            "surfaces": "Fold node packet",
        },
    ]
    if args.with_intake:
        plan.append({
            "id": "F",
            "name": "Governed Intake pipeline (single file)",
            "kind": "intake_run",
            "protected": True,
            "writes": "BOH_DATA_ROOT/* + boh.db (intake tables); canon_eligible always false",
            "surfaces": "Intake (capabilities / adapters / safety-lanes / quarantine)",
            "note": "Requires BOH_DATA_ROOT to be set or returns HTTP 422.",
        })
    return plan


# ---------------------------------------------------------------------------
# HTTP helpers (used only in --execute mode)
# ---------------------------------------------------------------------------

def _headers(args) -> dict:
    h = {"Content-Type": "application/json"}
    if args.operator_token:
        h["X-BOH-Operator-Token"] = args.operator_token
    return h


def _http(args, method: str, path: str, body: dict | None = None) -> dict:
    url = args.base_url.rstrip("/") + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=_headers(args))
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
            return {"status": resp.status, "body": json.loads(raw) if raw else {}}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        return {"status": e.code, "error": detail}
    except Exception as e:  # connection refused, etc.
        return {"status": None, "error": str(e)}


def _run_script(argv: list[str]) -> int:
    print(f"    $ {' '.join(argv)}")
    return subprocess.call(argv, cwd=str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Execution (only reached when --execute is passed)
# ---------------------------------------------------------------------------

def execute_step(args, step: dict) -> None:
    kind = step["kind"]

    if kind == "script":
        rc = _run_script(step["argv"])
        print(f"    -> exit code {rc}")
        return

    if kind == "http":
        res = _http(args, step["method"], step["path"])
        _print_http_result(step["path"], res)
        # Capture the demo-seed anchor for the later fold-node verification.
        if step["path"] == "/api/input/demo-seed":
            anchor = (res.get("body") or {}).get("folded_node_demo", {}).get("anchor_doc_id")
            if anchor:
                args._anchor_doc_id = anchor
                print(f"    -> captured anchor_doc_id = {anchor}")
        return

    if kind == "fold_node":
        anchor = getattr(args, "_anchor_doc_id", None) or args.anchor_doc_id
        if not anchor:
            print("    -> SKIP: no anchor_doc_id (run Step A first, or pass --anchor-doc-id)")
            return
        res = _http(args, "GET", f"/api/fold/node/{anchor}")
        _print_http_result(f"/api/fold/node/{anchor}", res)
        body = res.get("body") or {}
        has_actions = "scale_actions" in body
        print(f"    -> scale_actions present: {has_actions}")
        return

    if kind == "intake_run":
        if not args.intake_source:
            print("    -> SKIP: --intake-source not provided")
            return
        body = {"source_ref": args.intake_source, "batch_id": args.intake_batch}
        res = _http(args, "POST", "/api/intake/run", body)
        _print_http_result("/api/intake/run", res)
        return

    # GET verification fallthrough for read-only steps modeled as http GET
    if step.get("method") == "GET":
        res = _http(args, "GET", step["path"])
        _print_http_result(step["path"], res)
        return


def _print_http_result(path: str, res: dict) -> None:
    status = res.get("status")
    if status is None:
        print(f"    -> {path}: NO RESPONSE ({res.get('error')})")
        return
    if "error" in res:
        print(f"    -> {path}: HTTP {status} :: {res['error'][:200]}")
        return
    print(f"    -> {path}: HTTP {status} OK")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def print_plan(args, plan: list[dict]) -> None:
    print()
    print("=" * 72)
    print("  BOH DEMO SHOWCASE -- PLAN")
    print("=" * 72)
    mode = "EXECUTE (will write to runtime library/ and boh.db)" if args.execute \
        else "DRY-RUN (no writes; pass --execute to run)"
    print(f"  Mode:      {mode}")
    print(f"  Base URL:  {args.base_url}")
    print(f"  Operator:  {'token supplied' if args.operator_token else 'none (dev-open assumed)'}")
    print("-" * 72)
    for step in plan:
        gate = "operator-gated" if step["protected"] else "open"
        print(f"  [{step['id']}] {step['name']}  ({gate})")
        if step["kind"] == "script":
            print(f"       run:      {' '.join(step['argv'])}")
        elif step["kind"] in ("http",) or step.get("method"):
            print(f"       call:     {step.get('method','')} {step.get('path','')}")
        elif step["kind"] == "fold_node":
            print(f"       call:     GET /api/fold/node/{{anchor_doc_id}}")
        elif step["kind"] == "intake_run":
            print(f"       call:     POST /api/intake/run")
        print(f"       writes:   {step['writes']}")
        print(f"       surfaces: {step['surfaces']}")
        if step.get("note"):
            print(f"       note:     {step['note']}")
    print("-" * 72)
    print("  This orchestrator adds NO seeding logic; it sequences existing")
    print("  entrypoints only. See docs/DEMO_RUNBOOK.md.")
    print("=" * 72)
    print()


def main() -> int:
    p = argparse.ArgumentParser(
        description="Operator-run orchestrator that sequences existing BOH demo seeds. "
                    "Defaults to dry-run (no writes).",
    )
    p.add_argument("--execute", action="store_true",
                   help="Actually run the existing seeds (writes runtime data). "
                        "Without this, the script only prints the plan.")
    p.add_argument("--dry-run", action="store_true",
                   help="Explicitly request dry-run (this is the default).")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL,
                   help=f"BOH server base URL (default: {DEFAULT_BASE_URL}).")
    p.add_argument("--operator-token", default=None,
                   help="X-BOH-Operator-Token value, only needed if enforcement is on.")
    p.add_argument("--anchor-doc-id", default=None,
                   help="doc_id for the fold-node verification step "
                        "(otherwise captured from Step A's response).")
    p.add_argument("--with-intake", action="store_true",
                   help="Include the optional Governed Intake pipeline step.")
    p.add_argument("--intake-source", default=None,
                   help="source_ref file path for POST /api/intake/run.")
    p.add_argument("--intake-batch", default="demo-showcase-batch",
                   help="batch_id for POST /api/intake/run.")
    args = p.parse_args()
    args._anchor_doc_id = None

    plan = build_plan(args)
    print_plan(args, plan)

    if not args.execute:
        print("  Dry-run complete. Re-run with --execute to perform the seeds.")
        print("  (You, the operator, are responsible for the runtime writes.)")
        print()
        return 0

    print("  EXECUTING. This writes to runtime library/ and boh.db.\n")
    for step in plan:
        print(f"  [{step['id']}] {step['name']}")
        execute_step(args, step)
        print()

    print("  Showcase execute pass complete. Open the UI surfaces listed in")
    print("  docs/DEMO_RUNBOOK.md to review each capability.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
