"""demo_capability_tour.py — read-only capability tour for Bag of Holding.

WHAT THIS IS
    A single-command, READ-ONLY tour that exercises the full current BOH
    capability surface against a running server and prints a PASS / PARTIAL /
    EMPTY / SKIP / FAIL matrix. It covers every major feature family, INCLUDING
    backend capabilities that do not yet have a /v2 frontend surface:

        - governed-intake substrate (capabilities, adapters, safety-lanes,
          quarantine, scheduler-status block on /api/status)
        - Current Fold View resolver + dual-channel cluster/corpus aggregation
          (project / plane / domain / batch axes)
        - CANON scalar bridge variables on the fold contract
        - Metis retrieval contract (citation_uri / source_spans / warnings)
        - SC3 plane inference, lattice, certificate workflow surfaces
        - authority ledger, residence, governance policies, audit

WHAT THIS WRITES
    Nothing. Every request is a GET (or a documented read-only POST that the
    server treats as a pure evaluation, e.g. /api/sc3/check). The runtime
    library/ and boh.db are never mutated by this script. To SEED demo data
    first, use the operator-run `demo_showcase.py --execute` (separate script).

USAGE
    # 1. start a server (any of):
    python launcher.py                      # opens the UI at /
    #    or point at an already-running instance with --base-url

    # 2. (optional) seed data so surfaces are populated, not just reachable:
    python demo_showcase.py --execute       # operator opt-in; writes runtime data

    # 3. run the tour:
    python demo_capability_tour.py
    python demo_capability_tour.py --base-url http://127.0.0.1:8000
    python demo_capability_tour.py --json    # machine-readable matrix to stdout
    python demo_capability_tour.py --strict  # exit 1 if any surface FAILs

EXIT CODE
    0 by default (a tour is informational). With --strict, exit 1 if any
    capability reports FAIL (a reachable surface that errored or threw). EMPTY
    (reachable but no seeded rows) and SKIP (dependency absent) are not failures.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

DEFAULT_BASE_URL = "http://127.0.0.1:8000"


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class Result:
    family: str
    surface: str
    verdict: str           # PASS | PARTIAL | EMPTY | SKIP | FAIL
    detail: str = ""
    http: Optional[int] = None


@dataclass
class Tour:
    base_url: str
    operator_token: Optional[str]
    retrieval_token: Optional[str]
    results: list[Result] = field(default_factory=list)
    _anchor_doc_id: Optional[str] = None
    _sample_doc_id: Optional[str] = None
    _sample_project: Optional[str] = None
    _sample_card_id: Optional[str] = None

    # -- HTTP ------------------------------------------------------------
    def _req(self, method: str, path: str, body: Optional[dict] = None,
             token: Optional[str] = None) -> dict:
        url = self.base_url.rstrip("/") + path
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-BOH-Operator-Token"] = token
        if self.retrieval_token and path.startswith(("/api/retrieve", "/api/context-object")):
            headers["X-BOH-Retrieval-Token"] = self.retrieval_token
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
                return {"status": resp.status, "body": json.loads(raw) if raw else {}}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(detail)
            except Exception:
                parsed = detail[:200]
            return {"status": e.code, "error": parsed}
        except Exception as e:
            return {"status": None, "error": str(e)}

    def get(self, path: str, token: Optional[str] = None) -> dict:
        return self._req("GET", path, None, token)

    def post(self, path: str, body: dict, token: Optional[str] = None) -> dict:
        return self._req("POST", path, body, token)

    # -- recording -------------------------------------------------------
    def rec(self, family: str, surface: str, verdict: str, detail: str = "",
            http: Optional[int] = None) -> None:
        self.results.append(Result(family, surface, verdict, detail, http))

    def check_list(self, family: str, surface: str, path: str,
                   list_keys: tuple[str, ...] = ("items", "docs", "results",
                                                 "events", "cards", "rows",
                                                 "conflicts", "duplicates",
                                                 "policies", "grants")) -> dict:
        """GET a list endpoint; PASS if rows present, EMPTY if reachable but empty."""
        res = self.get(path)
        st = res.get("status")
        if st is None:
            self.rec(family, surface, "FAIL", f"no response: {res.get('error')}")
            return res
        if "error" in res:
            self.rec(family, surface, "FAIL", f"HTTP {st}: {str(res['error'])[:80]}", st)
            return res
        body = res.get("body") or {}
        count = 0
        for k in list_keys:
            v = body.get(k)
            if isinstance(v, list):
                count = max(count, len(v))
        total = body.get("total")
        n = total if isinstance(total, int) else count
        if n and n > 0:
            self.rec(family, surface, "PASS", f"{n} rows", st)
        else:
            self.rec(family, surface, "EMPTY", "reachable, no seeded rows", st)
        return res


# ===========================================================================
# Capability families
# ===========================================================================

def tour_core(t: Tour) -> None:
    fam = "Core / Status"
    res = t.get("/api/status")
    st = res.get("status")
    if st == 200 and "error" not in res:
        body = res.get("body") or {}
        sched = body.get("intake_scheduler")
        t.rec(fam, "GET /api/status", "PASS", f"server={body.get('server','?')}", st)
        if isinstance(sched, dict):
            state = sched.get("state", "?")
            t.rec(fam, "  · intake_scheduler block", "PASS",
                  f"state={state} (WO-1.1 status surface)", st)
        else:
            t.rec(fam, "  · intake_scheduler block", "PARTIAL",
                  "block absent from /api/status", st)
    else:
        t.rec(fam, "GET /api/status", "FAIL", f"HTTP {st}", st)

    # dashboard + coherence are computed objects (not lists) — a 200 with a non-empty body is PASS.
    for path, surface in (("/api/dashboard", "GET /api/dashboard"),
                          ("/api/coherence/summary", "GET /api/coherence/summary")):
        r = t.get(path)
        body = r.get("body") or {}
        if r.get("status") == 200 and body:
            t.rec(fam, surface, "PASS", f"{len(body)} keys", r.get("status"))
        elif r.get("status") == 200:
            t.rec(fam, surface, "EMPTY", "reachable, empty body", r.get("status"))
        else:
            t.rec(fam, surface, "FAIL", f"HTTP {r.get('status')}", r.get("status"))
    # Health
    res = t.get("/api/health")
    t.rec(fam, "GET /api/health", "PASS" if res.get("status") == 200 else "FAIL",
          "", res.get("status"))


def tour_library(t: Tour) -> None:
    fam = "Library / Docs"
    res = t.check_list(fam, "GET /api/docs", "/api/docs?per_page=8")
    body = res.get("body") or {}
    docs = body.get("docs") or body.get("items") or []
    if docs:
        d0 = docs[0]
        t._sample_doc_id = d0.get("doc_id") or d0.get("id")
        t._sample_project = d0.get("project")
    if t._sample_doc_id:
        r = t.get(f"/api/docs/{t._sample_doc_id}")
        ok = r.get("status") == 200 and (r.get("body") or {}).get("doc")
        t.rec(fam, "GET /api/docs/{id}", "PASS" if ok else "EMPTY",
              f"doc + definitions + events" if ok else "no doc detail", r.get("status"))
        rc = t.get(f"/api/docs/{t._sample_doc_id}/content")
        t.rec(fam, "GET /api/docs/{id}/content", "PASS" if rc.get("status") == 200 else "EMPTY",
              "", rc.get("status"))
    else:
        t.rec(fam, "GET /api/docs/{id}", "SKIP", "no docs seeded")
    t.check_list(fam, "GET /api/search", "/api/search?q=a&limit=10")
    t.check_list(fam, "GET /api/duplicates", "/api/duplicates")


def tour_planecards(t: Tour) -> None:
    fam = "PlaneCards / PCDS"
    res = t.check_list(fam, "GET /api/planes/cards", "/api/planes/cards?limit=50", ("cards",))
    body = res.get("body") or {}
    cards = body.get("cards") or []
    if cards:
        t._sample_card_id = cards[0].get("id")
    if t._sample_card_id:
        r = t.get(f"/api/planes/cards/{t._sample_card_id}")
        t.rec(fam, "GET /api/planes/cards/{id}", "PASS" if r.get("status") == 200 else "EMPTY",
              "single card detail (frontend lazy-enrichment target)", r.get("status"))
    else:
        t.rec(fam, "GET /api/planes/cards/{id}", "SKIP", "no cards seeded")
    t.check_list(fam, "GET /api/planes", "/api/planes?limit=50", ("planes",))


def tour_fold(t: Tour) -> None:
    fam = "Current Fold View"
    t.check_list(fam, "GET /api/fold/library", "/api/fold/library", ("docs",))
    if t._sample_doc_id:
        r = t.get(f"/api/fold/node/{t._sample_doc_id}")
        body = r.get("body") or {}
        if r.get("status") == 200:
            cv = body.get("canon_variables") or {}
            present = [k for k in ("drift_rate", "entropy", "delta_c_star", "gamma",
                                   "omega_viability", "mismatch_gradient") if k in cv]
            t.rec(fam, "GET /api/fold/node/{id}", "PASS",
                  f"CurrentFoldPacket; canon_variables: {len(present)}/6", r.get("status"))
            t.rec(fam, "  · CANON scalar bridge", "PASS" if len(present) == 6 else "PARTIAL",
                  f"{', '.join(present)}", r.get("status"))
            has_actions = isinstance(body.get("scale_actions"), list)
            t.rec(fam, "  · scale_actions[] roll-up axes", "PASS" if has_actions else "PARTIAL",
                  "project/plane/domain", r.get("status"))
        else:
            t.rec(fam, "GET /api/fold/node/{id}", "EMPTY", "node not resolvable", r.get("status"))
    else:
        t.rec(fam, "GET /api/fold/node/{id}", "SKIP", "no docs seeded")
    # Cluster / corpus aggregation (dual-channel engine)
    if t._sample_project:
        proj = urllib.parse.quote(t._sample_project)
        rc = t.get(f"/api/fold/cluster/project/{proj}")
        t.rec(fam, "GET /api/fold/cluster/project/{v}",
              "PASS" if rc.get("status") == 200 else "EMPTY",
              "aggregate CurrentFoldPacket", rc.get("status"))
    else:
        t.rec(fam, "GET /api/fold/cluster/project/{v}", "SKIP", "no project on sample doc")
    rcorp = t.get("/api/fold/corpus/plane")
    t.rec(fam, "GET /api/fold/corpus/plane", "PASS" if rcorp.get("status") == 200 else "EMPTY",
          "axis-wide corpus rollup", rcorp.get("status"))
    # domain / batch diagnostic axes (return 200, diagnostic_only)
    for axis in ("domain", "batch"):
        rax = t.get(f"/api/fold/corpus/{axis}")
        t.rec(fam, f"GET /api/fold/corpus/{axis}",
              "PASS" if rax.get("status") == 200 else "PARTIAL",
              "diagnostic axis", rax.get("status"))


def tour_graph(t: Tour) -> None:
    fam = "Graph Lab / Projection"
    # Backend projection modes (the UI's Evidence/Risk/Authority views are computed
    # client-side from the web topology + fold library data, not separate backend modes).
    for mode in ("web", "structural", "constitutional", "constraint-geometry"):
        r = t.get(f"/api/graph/projection?mode={mode}&max_nodes=50")
        body = r.get("body") or {}
        n = len(body.get("nodes") or [])
        if r.get("status") == 200:
            t.rec(fam, f"projection?mode={mode}", "PASS" if n else "EMPTY",
                  f"{n} nodes", r.get("status"))
        else:
            t.rec(fam, f"projection?mode={mode}", "FAIL", f"HTTP {r.get('status')}", r.get("status"))


def tour_intake(t: Tour) -> None:
    fam = "Governed Intake (WO-1/1.1)"
    t.check_list(fam, "GET /api/intake/capabilities", "/api/intake/capabilities?limit=20")
    r = t.get("/api/intake/adapters")
    body = r.get("body") or {}
    cov = body.get("coverage_report") or {}
    cap = body.get("capability_summary") or {}
    if r.get("status") == 200 and (cov or cap):
        n = len(cov) if isinstance(cov, (list, dict)) else "?"
        t.rec(fam, "GET /api/intake/adapters", "PASS",
              f"coverage_report + capability_summary ({n} entries)", r.get("status"))
    elif r.get("status") == 200:
        t.rec(fam, "GET /api/intake/adapters", "PASS", "registry coverage", r.get("status"))
    else:
        t.rec(fam, "GET /api/intake/adapters", "FAIL", f"HTTP {r.get('status')}", r.get("status"))
    rs = t.get("/api/intake/safety-lanes")
    t.rec(fam, "GET /api/intake/safety-lanes",
          "PASS" if rs.get("status") == 200 else "FAIL",
          "lane summary", rs.get("status"))
    t.check_list(fam, "GET /api/intake/quarantine", "/api/intake/quarantine?limit=20")
    # Note: POST /api/intake/run and /replay are operator-gated WRITES — not exercised here.
    t.rec(fam, "POST /api/intake/run", "SKIP", "operator write — use demo_showcase --execute")
    t.rec(fam, "POST /api/intake/replay", "SKIP", "operator write — replay-vs-reprocess contract")


def tour_review(t: Tour) -> None:
    fam = "Review / Governance"
    t.check_list(fam, "GET /api/conflicts", "/api/conflicts")
    t.check_list(fam, "GET /api/llm/queue", "/api/llm/queue", ("items", "queue", "proposals"))
    t.check_list(fam, "GET /api/governance/policies", "/api/governance/policies", ("policies",))
    t.check_list(fam, "GET /api/audit", "/api/audit?limit=20", ("events",))
    t.check_list(fam, "GET /api/authority/grants", "/api/authority/grants", ("grants", "items"))
    t.check_list(fam, "GET /api/lineage", "/api/lineage", ("lineage", "items", "records"))


def tour_authority_advanced(t: Tour) -> None:
    fam = "Authority / SC3 / Lattice"
    # SC3 plane inference is a pure read-only evaluation POST (takes a metadata dict).
    r = t.post("/api/authority/sc3/infer-plane",
               {"metadata": {"corpus_class": "canon", "title": "Governance Charter"}})
    if r.get("status") == 200:
        plane = (r.get("body") or {}).get("plane", "?")
        t.rec(fam, "POST /api/authority/sc3/infer-plane", "PASS",
              f"deterministic plane inference -> {plane}", r.get("status"))
    elif r.get("status") == 422:
        t.rec(fam, "POST /api/authority/sc3/infer-plane", "PARTIAL",
              "reachable; body schema differs", r.get("status"))
    else:
        t.rec(fam, "POST /api/authority/sc3/infer-plane", "FAIL",
              f"HTTP {r.get('status')}", r.get("status"))
    r2 = t.get("/api/authority/sc3/mapping")
    t.rec(fam, "GET /api/authority/sc3/mapping",
          "PASS" if r2.get("status") == 200 else "FAIL",
          "constitutive/descriptive map", r2.get("status"))
    t.check_list(fam, "GET /api/authority/sc3/violations",
                 "/api/authority/sc3/violations", ("violations", "items"))
    t.check_list(fam, "GET /api/lattice/events", "/api/lattice/events", ("events", "items"))
    t.check_list(fam, "GET /api/certificate/pending", "/api/certificate/pending", ("items", "pending"))
    ri = t.get("/api/integrity/dashboard")
    t.rec(fam, "GET /api/integrity/dashboard",
          "PASS" if ri.get("status") == 200 else "FAIL",
          "integrity-first surface", ri.get("status"))


def tour_retrieval(t: Tour) -> None:
    fam = "Metis Retrieval Contract"
    rs = t.get("/api/retrieve/status")
    if rs.get("status") == 200:
        body = rs.get("body") or {}
        cfg = body.get("configured")
        t.rec(fam, "GET /api/retrieve/status", "PASS",
              f"configured={cfg} (no token needed for probe)", rs.get("status"))
    else:
        t.rec(fam, "GET /api/retrieve/status", "FAIL", f"HTTP {rs.get('status')}", rs.get("status"))
    # /api/retrieve itself needs BOH_RETRIEVAL_TOKEN — only exercise if supplied.
    if t.retrieval_token:
        r = t.post("/api/retrieve", {"query": "governance"}, token=None)
        body = r.get("body") or {}
        if r.get("status") == 200:
            has_warnings = "warnings" in body
            packs = body.get("packs") or body.get("results") or []
            has_cite = any("citation_uri" in p for p in packs) if packs else False
            t.rec(fam, "POST /api/retrieve", "PASS",
                  f"warnings={has_warnings} citation_uri={has_cite}", r.get("status"))
        else:
            t.rec(fam, "POST /api/retrieve", "PARTIAL",
                  f"HTTP {r.get('status')} (token may be wrong)", r.get("status"))
    else:
        t.rec(fam, "POST /api/retrieve", "SKIP",
              "needs --retrieval-token (BOH_RETRIEVAL_TOKEN)")


# ===========================================================================
# Rendering
# ===========================================================================

_ORDER = ["PASS", "PARTIAL", "EMPTY", "SKIP", "FAIL"]
_GLYPH = {"PASS": "[PASS]", "PARTIAL": "[PART]", "EMPTY": "[ -- ]",
          "SKIP": "[skip]", "FAIL": "[FAIL]"}


def render_text(t: Tour) -> None:
    print()
    print("=" * 78)
    print("  BAG OF HOLDING — CAPABILITY TOUR (read-only)")
    print(f"  base: {t.base_url}")
    print("=" * 78)
    fam = None
    for r in t.results:
        if r.family != fam:
            fam = r.family
            print(f"\n  {fam}")
            print("  " + "-" * 74)
        line = f"  {_GLYPH.get(r.verdict, '[????]')}  {r.surface}"
        if r.detail:
            line = f"{line:<54} {r.detail}"
        print(line)
    # summary
    counts = {k: 0 for k in _ORDER}
    for r in t.results:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1
    print()
    print("  " + "-" * 74)
    summary = "   ".join(f"{k}={counts.get(k, 0)}" for k in _ORDER)
    print(f"  SUMMARY: {summary}   (total {len(t.results)})")
    if counts.get("EMPTY"):
        print("  Note: EMPTY = surface reachable but no seeded rows. Run")
        print("        `python demo_showcase.py --execute` to populate, then re-run.")
    print("=" * 78)
    print()


def render_json(t: Tour) -> None:
    out = {
        "base_url": t.base_url,
        "results": [
            {"family": r.family, "surface": r.surface, "verdict": r.verdict,
             "detail": r.detail, "http": r.http}
            for r in t.results
        ],
    }
    counts: dict[str, int] = {}
    for r in t.results:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1
    out["summary"] = counts
    print(json.dumps(out, indent=2))


# ===========================================================================
# CLI
def tour_context_object(t: Tour) -> None:
    """Retrieval roadmap L3–L6: /api/context-object (WO-R2/R3/R4). Retrieval-token gated."""
    fam = "Context Objects (L3-L6)"
    if not t.retrieval_token:
        t.rec(fam, "GET/POST /api/context-object", "SKIP",
              "pass --retrieval-token to exercise (X-BOH-Retrieval-Token gated)")
        return
    doc_id = t._sample_doc_id
    if not doc_id:
        t.rec(fam, "doc scope", "EMPTY", "no sample doc available from the library tour")
        return

    def _verdict(surface: str, res: dict, expect_keys: tuple[str, ...]) -> None:
        st = res.get("status")
        if "error" in res or st != 200:
            t.rec(fam, surface, "FAIL", f"HTTP {st}: {str(res.get('error'))[:80]}", st)
            return
        body = res.get("body") or {}
        missing = [k for k in expect_keys if k not in body]
        if missing:
            t.rec(fam, surface, "FAIL", f"missing keys {missing}", st)
        elif (body.get("scope") or {}).get("resolved"):
            t.rec(fam, surface, "PASS",
                  f"members={body['scope']['resolved'].get('member_count')} "
                  f"evidence={len(body.get('evidence') or [])}", st)
        else:
            t.rec(fam, surface, "EMPTY", "reachable; scope unresolved on this seed", st)

    base = ("scope", "state", "evidence", "conflicts", "unknowns", "actions")
    _verdict("doc scope (L5)", t.get(f"/api/context-object?scope=doc:{doc_id}"), base)
    _verdict("blocking view (L3)",
             t.get(f"/api/context-object?scope=doc:{doc_id}&only=blocking"),
             base + ("blockers",))
    _verdict("question type: historical (L4)",
             t.get(f"/api/context-object?scope=doc:{doc_id}&question_type=historical"),
             base + ("question_context",))
    _verdict("node neighborhood (L6)",
             t.get(f"/api/context-object?scope=node:{doc_id}&radius=2"), base)
    _verdict("query scope (POST)",
             t.post("/api/context-object",
                    {"scope": {"type": "query", "query": "governed retrieval demo"}}), base)


# ===========================================================================

def main() -> int:
    p = argparse.ArgumentParser(
        description="Read-only capability tour for Bag of Holding. Writes nothing.")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--operator-token", default=None,
                   help="X-BOH-Operator-Token (only needed if enforcement is on).")
    p.add_argument("--retrieval-token", default=None,
                   help="X-BOH-Retrieval-Token to exercise POST /api/retrieve.")
    p.add_argument("--json", action="store_true", help="emit JSON instead of a table.")
    p.add_argument("--strict", action="store_true",
                   help="exit 1 if any surface reports FAIL.")
    args = p.parse_args()

    t = Tour(base_url=args.base_url, operator_token=args.operator_token,
             retrieval_token=args.retrieval_token)

    # Connectivity preflight.
    pre = t.get("/api/health")
    if pre.get("status") is None:
        print(f"\n  Cannot reach {args.base_url} — is the server running?")
        print("  Start it with: python launcher.py\n")
        return 2

    for fn in (tour_core, tour_library, tour_planecards, tour_fold, tour_graph,
               tour_intake, tour_review, tour_authority_advanced, tour_retrieval,
               tour_context_object):
        try:
            fn(t)
        except Exception as e:  # a tour family must never abort the whole run
            t.rec(fn.__name__, "(family)", "FAIL", f"tour error: {e}")

    if args.json:
        render_json(t)
    else:
        render_text(t)

    if args.strict and any(r.verdict == "FAIL" for r in t.results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
