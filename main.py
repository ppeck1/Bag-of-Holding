"""main.py: FastAPI application for Bag of Holding v0P."""

import json
import os
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, HTMLResponse
from pydantic import BaseModel

import db
import crawler
import canon
import conflicts as conflict_engine
import search as search_engine
import planar as planar_engine
import events as event_engine
import llm_review

# ── Init ─────────────────────────────────────────────────────────────────────
db.init_db()

LIBRARY_ROOT = os.environ.get("BOH_LIBRARY", "./library")

app = FastAPI(
    title="Bag of Holding v0P",
    description="Deterministic Local Knowledge Engine with Planar Math + Rubrix Governance",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Models ───────────────────────────────────────────────────────────────────

class IndexRequest(BaseModel):
    library_root: Optional[str] = None


class PlanarFactRequest(BaseModel):
    plane_path: str
    r: float
    d: int
    q: float
    c: float
    context_ref: Optional[str] = ""
    m: Optional[str] = None
    valid_until: Optional[int] = None
    subject_id: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/index", summary="Index the filesystem library")
def index_library(req: IndexRequest = None):
    root = (req.library_root if req and req.library_root else None) or LIBRARY_ROOT
    result = crawler.crawl_library(root)
    # After indexing, run conflict detection
    new_conflicts = conflict_engine.detect_all_conflicts()
    result["conflicts_detected"] = len(new_conflicts)
    result["new_conflicts"] = new_conflicts
    return result


@app.get("/search", summary="Full-text search with explainable scoring")
def search(
    q: str = Query(..., description="Search query"),
    plane: Optional[str] = Query(None, description="Filter by plane_scope path"),
    limit: int = Query(20, ge=1, le=100),
):
    results = search_engine.search(q, plane_filter=plane, limit=limit)
    return {
        "query": q,
        "plane_filter": plane,
        "count": len(results),
        "results": results,
        "score_formula": "0.6*text_score + 0.2*canon_score + 0.2*planar_alignment + conflict_penalty",
    }


@app.get("/canon", summary="Resolve canonical document")
def resolve_canon(
    topic: Optional[str] = Query(None),
    plane: Optional[str] = Query(None),
):
    result = canon.resolve_canon(topic=topic, plane_scope=plane)
    return result


@app.get("/conflicts", summary="List all detected conflicts")
def list_conflicts():
    all_conflicts = conflict_engine.list_conflicts()
    return {
        "count": len(all_conflicts),
        "conflicts": all_conflicts,
        "note": "No auto-resolution. All conflicts require explicit user action.",
    }


@app.get("/nodes/{node_path:path}", summary="Get planar node facts")
def get_node(
    node_path: str,
    include_expired: bool = Query(False),
):
    now = int(time.time())
    if include_expired:
        facts = db.fetchall(
            "SELECT * FROM plane_facts WHERE plane_path = ? ORDER BY ts DESC",
            (node_path,),
        )
    else:
        facts = db.fetchall(
            "SELECT * FROM plane_facts WHERE plane_path = ? AND (valid_until IS NULL OR valid_until > ?) ORDER BY ts DESC",
            (node_path, now),
        )

    # Parse node path: plane.field.node
    parts = node_path.split(".")
    parsed = {
        "plane": parts[0] if len(parts) > 0 else None,
        "field": parts[1] if len(parts) > 1 else None,
        "node": parts[2] if len(parts) > 2 else None,
    }

    return {
        "node_path": node_path,
        "parsed": parsed,
        "active_facts": len([f for f in facts if not f.get("valid_until") or f["valid_until"] > now]),
        "facts": facts,
    }


@app.post("/nodes/{node_path:path}", summary="Store a planar fact")
def store_node_fact(node_path: str, req: PlanarFactRequest):
    req.plane_path = node_path  # override with URL path
    result = planar_engine.store_fact(
        plane_path=node_path,
        r=req.r,
        d=req.d,
        q=req.q,
        c=req.c,
        context_ref=req.context_ref or "",
        m=req.m,
        valid_until=req.valid_until,
        subject_id=req.subject_id,
    )
    if not result.get("stored"):
        raise HTTPException(status_code=422, detail=result.get("errors"))
    # Check for new planar conflicts
    conflict_engine.detect_all_conflicts()
    return result


@app.get("/workflow", summary="List documents and their Rubrix workflow states")
def workflow(
    operator_state: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    doc_type: Optional[str] = Query(None),
):
    query = "SELECT doc_id, path, type, status, operator_state, operator_intent, version FROM docs WHERE 1=1"
    params = []
    if operator_state:
        query += " AND operator_state = ?"
        params.append(operator_state)
    if status:
        query += " AND status = ?"
        params.append(status)
    if doc_type:
        query += " AND type = ?"
        params.append(doc_type)
    query += " ORDER BY operator_state, status"
    docs = db.fetchall(query, tuple(params))

    from parser import ALLOWED_TRANSITIONS, OPERATOR_STATES, OPERATOR_INTENTS
    return {
        "count": len(docs),
        "docs": docs,
        "rubrix_schema": {
            "operator_states": list(OPERATOR_STATES),
            "operator_intents": list(OPERATOR_INTENTS),
            "allowed_transitions": {k: list(v) for k, v in ALLOWED_TRANSITIONS.items()},
            "hard_constraints": [
                "status=canonical ⇒ operator_state=release",
                "type=canon ⇒ operator_state≠observe",
                "status=archived ⇒ operator_state=release",
            ],
        },
    }


@app.get("/events/export.ics", response_class=PlainTextResponse, summary="Export events as ICS")
def export_ics(doc_id: Optional[str] = Query(None)):
    return event_engine.export_ics(doc_id=doc_id)


@app.get("/events", summary="List all events")
def list_events(doc_id: Optional[str] = Query(None)):
    evs = event_engine.list_events(doc_id=doc_id)
    return {"count": len(evs), "events": evs}


@app.get("/review/{doc_path:path}", summary="Generate LLM review artifact (non-authoritative)")
def generate_review(doc_path: str, library_root: Optional[str] = Query(None)):
    root = library_root or LIBRARY_ROOT
    artifact = llm_review.generate_review_artifact(doc_path, root)
    if "error" in artifact:
        raise HTTPException(status_code=404, detail=artifact["error"])
    return artifact


@app.get("/docs/{doc_id}", summary="Get a single document by ID")
def get_doc(doc_id: str):
    doc = db.fetchone("SELECT * FROM docs WHERE doc_id = ?", (doc_id,))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    defs = db.fetchall("SELECT * FROM defs WHERE doc_id = ?", (doc_id,))
    evs = event_engine.list_events(doc_id=doc_id)
    return {"doc": doc, "definitions": defs, "events": evs}


@app.get("/", response_class=HTMLResponse, summary="Minimal web UI")
def ui():
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Bag of Holding v0P</title>
<style>
  body { font-family: monospace; background: #0d1117; color: #e6edf3; padding: 2rem; }
  h1 { color: #58a6ff; } h2 { color: #79c0ff; border-bottom: 1px solid #30363d; padding-bottom:.3rem; }
  input, select { background:#161b22; color:#e6edf3; border:1px solid #30363d; padding:.4rem .6rem; border-radius:4px; }
  button { background:#1f6feb; color:#fff; border:none; padding:.4rem 1rem; border-radius:4px; cursor:pointer; }
  button:hover { background:#388bfd; }
  pre { background:#161b22; padding:1rem; border-radius:6px; overflow:auto; font-size:.85rem; border:1px solid #30363d; }
  .section { margin-bottom:2rem; }
  .grid { display:grid; grid-template-columns:1fr 1fr; gap:1rem; }
  a { color:#58a6ff; }
</style>
</head>
<body>
<h1>📦 Bag of Holding v0P</h1>
<p>Deterministic Local Knowledge Engine · Planar Math · Rubrix Governance</p>

<div class="section">
  <h2>Index Library</h2>
  <input id="libRoot" placeholder="./library" style="width:300px">
  <button onclick="doIndex()">Index</button>
  <pre id="indexOut"></pre>
</div>

<div class="section">
  <h2>Search</h2>
  <input id="searchQ" placeholder="query..." style="width:300px">
  <input id="planeFilter" placeholder="plane filter (optional)" style="width:200px">
  <button onclick="doSearch()">Search</button>
  <pre id="searchOut"></pre>
</div>

<div class="section">
  <h2>Canon Resolution</h2>
  <input id="canonTopic" placeholder="topic..." style="width:300px">
  <button onclick="doCanon()">Resolve</button>
  <pre id="canonOut"></pre>
</div>

<div class="section grid">
  <div>
    <h2>Conflicts</h2>
    <button onclick="doConflicts()">List Conflicts</button>
    <pre id="conflictsOut"></pre>
  </div>
  <div>
    <h2>Workflow</h2>
    <select id="wfState"><option value="">All states</option>
      <option>observe</option><option>vessel</option><option>constraint</option>
      <option>integrate</option><option>release</option>
    </select>
    <button onclick="doWorkflow()">View</button>
    <pre id="workflowOut"></pre>
  </div>
</div>

<div class="section">
  <h2>API Docs</h2>
  <a href="/docs" target="_blank">/docs (Swagger UI)</a> &nbsp;
  <a href="/redoc" target="_blank">/redoc</a> &nbsp;
  <a href="/events/export.ics">/events/export.ics</a>
</div>

<script>
async function api(path, opts={}) {
  const r = await fetch(path, opts);
  return r.json();
}
async function doIndex() {
  const root = document.getElementById('libRoot').value || './library';
  const d = await api('/index', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({library_root: root})
  });
  document.getElementById('indexOut').textContent = JSON.stringify(d, null, 2);
}
async function doSearch() {
  const q = document.getElementById('searchQ').value;
  const plane = document.getElementById('planeFilter').value;
  const url = `/search?q=${encodeURIComponent(q)}${plane ? '&plane='+encodeURIComponent(plane) : ''}`;
  const d = await api(url);
  document.getElementById('searchOut').textContent = JSON.stringify(d, null, 2);
}
async function doCanon() {
  const topic = document.getElementById('canonTopic').value;
  const d = await api(`/canon?topic=${encodeURIComponent(topic)}`);
  document.getElementById('canonOut').textContent = JSON.stringify(d, null, 2);
}
async function doConflicts() {
  const d = await api('/conflicts');
  document.getElementById('conflictsOut').textContent = JSON.stringify(d, null, 2);
}
async function doWorkflow() {
  const state = document.getElementById('wfState').value;
  const d = await api(`/workflow${state ? '?operator_state='+state : ''}`);
  document.getElementById('workflowOut').textContent = JSON.stringify(d, null, 2);
}
</script>
</body>
</html>"""
