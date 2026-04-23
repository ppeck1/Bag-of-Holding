"""app/core/dcns.py: Selective DCNS relationship layer for Bag of Holding v2.

Phase 8 addition. Builds constrained doc_edges from existing lineage + conflicts.
Does NOT implement full vessel/flow simulation.

DCNS edge types:
    duplicate_content  — content-identical documents
    supersedes         — document supersedes another
    conflicts          — documents in conflict (state=-1)
    canon_relates_to   — high topic+plane overlap with a canonical document
    derives            — derived_from lineage records

Edge state semantics (trinary):
    +1 = reinforces / derives / supports
     0 = unresolved / ambiguous
    -1 = conflicts / contradicts

Permeability = flow affordance (diagnostic only, not a simulation).
Load score   = incident edge count + conflict/dependency penalties.

Design invariants (safety rails):
    - Only explicit edges from lineage/conflicts — no full inferred graph
    - Inferred edges (canon_relates_to) are labeled 'inferred' in detail
    - No automatic state flips
    - No vessel simulation
"""

import json
import time
from typing import Any

from app.db import connection as db

# Default permeability per edge type
PERMEABILITY = {
    "duplicate_content": 0.95,
    "supersedes":        0.90,
    "canon_relates_to":  0.75,
    "derives":           0.80,
    "conflicts":         0.40,
}

# State encoding per edge type
EDGE_STATE = {
    "duplicate_content": 0,   # unresolved — duplicates need human review
    "supersedes":        +1,  # positive — explicit advancement
    "canon_relates_to":  +1,  # positive — reinforces canon
    "derives":           +1,  # positive — explicit derivation
    "conflicts":         -1,  # negative — contradiction
}


# ── Edge builders ─────────────────────────────────────────────────────────────

def _edges_from_lineage() -> list[dict]:
    """Derive doc_edges from the lineage table."""
    lineage_rows = db.fetchall(
        "SELECT doc_id, related_doc_id, relationship, detected_ts, detail FROM lineage"
    )
    edges = []
    now = int(time.time())
    for row in lineage_rows:
        rel = row["relationship"]
        # Map lineage relationship names to edge_type
        if rel == "duplicate_content":
            etype = "duplicate_content"
        elif rel in ("supersedes", "supersession"):
            etype = "supersedes"
        elif rel in ("derived_from", "derives"):
            etype = "derives"
        elif rel == "snapshot_source":
            etype = "derives"
        else:
            continue  # unknown relationship — skip

        edges.append({
            "source_doc_id": row["doc_id"],
            "target_doc_id": row["related_doc_id"],
            "edge_type":     etype,
            "state":         EDGE_STATE.get(etype, 0),
            "permeability":  PERMEABILITY.get(etype, 0.5),
            "load_score":    None,   # computed later
            "detected_ts":   row["detected_ts"] or now,
            "detail":        row["detail"] or "",
        })
    return edges


def _edges_from_conflicts() -> list[dict]:
    """Derive doc_edges from the conflicts table (state = -1)."""
    conflict_rows = db.fetchall(
        "SELECT conflict_type, doc_ids, detected_ts FROM conflicts"
    )
    edges = []
    now = int(time.time())
    for row in conflict_rows:
        doc_ids = [d.strip() for d in (row["doc_ids"] or "").split(",") if d.strip()]
        if len(doc_ids) < 2:
            continue
        # Create edges between all pairs — conflicts are bidirectional
        for i in range(len(doc_ids)):
            for j in range(i + 1, len(doc_ids)):
                edges.append({
                    "source_doc_id": doc_ids[i],
                    "target_doc_id": doc_ids[j],
                    "edge_type":     "conflicts",
                    "state":         -1,
                    "permeability":  PERMEABILITY["conflicts"],
                    "load_score":    None,
                    "detected_ts":   row["detected_ts"] or now,
                    "detail":        json.dumps({"conflict_type": row["conflict_type"]}),
                })
    return edges


def _edges_canon_relates_to(max_pairs: int = 200) -> list[dict]:
    """Derive optional canon_relates_to edges for high topic+plane overlap pairs.

    Only runs when corpus is small enough (≤ 150 docs) to keep complexity bounded.
    Edges are labeled 'inferred' in detail to distinguish from explicit lineage.
    """
    docs = db.fetchall(
        "SELECT doc_id, corpus_class, topics_tokens, plane_scope_json "
        "FROM docs WHERE corpus_class = 'CORPUS_CLASS:CANON'"
    )
    all_docs = db.fetchall(
        "SELECT doc_id, corpus_class, topics_tokens, plane_scope_json FROM docs"
    )

    if len(all_docs) > 150:
        return []

    now = int(time.time())
    edges = []
    seen = set()

    for canon in docs:
        canon_topics = set((canon["topics_tokens"] or "").split()) - {""}
        canon_scope  = set(json.loads(canon["plane_scope_json"] or "[]"))

        for other in all_docs:
            if other["doc_id"] == canon["doc_id"]:
                continue
            if other["corpus_class"] == "CORPUS_CLASS:CANON":
                continue  # canon↔canon handled by lineage / conflicts

            key = tuple(sorted([canon["doc_id"], other["doc_id"]]) + ["canon_relates_to"])
            if key in seen:
                continue

            other_topics = set((other["topics_tokens"] or "").split()) - {""}
            other_scope  = set(json.loads(other["plane_scope_json"] or "[]"))

            topic_union = canon_topics | other_topics
            if not topic_union:
                continue
            topic_j = len(canon_topics & other_topics) / len(topic_union)
            scope_union = canon_scope | other_scope
            scope_j = (len(canon_scope & other_scope) / len(scope_union)) if scope_union else 0.0

            # Only create edge for high overlap — conservative threshold
            if topic_j >= 0.4 and scope_j >= 0.3:
                seen.add(key)
                edges.append({
                    "source_doc_id": canon["doc_id"],
                    "target_doc_id": other["doc_id"],
                    "edge_type":     "canon_relates_to",
                    "state":         +1,
                    "permeability":  PERMEABILITY["canon_relates_to"],
                    "load_score":    None,
                    "detected_ts":   now,
                    "detail":        json.dumps({
                        "origin": "inferred",
                        "topic_jaccard": round(topic_j, 3),
                        "scope_jaccard": round(scope_j, 3),
                    }),
                })
                if len(edges) >= max_pairs:
                    return edges

    return edges


# ── Load score computation ────────────────────────────────────────────────────

def _compute_load_scores(edges: list[dict]) -> dict[str, float]:
    """Compute per-node load diagnostic scores.

    Load = incident_edges + (2 × conflict_count) + (0.5 × depends_on_count)
    Returns: {doc_id: load_score}
    """
    incident: dict[str, int] = {}
    conflicts: dict[str, int] = {}
    depends_on: dict[str, int] = {}

    for e in edges:
        for did in (e["source_doc_id"], e["target_doc_id"]):
            incident[did] = incident.get(did, 0) + 1
        if e["edge_type"] == "conflicts":
            for did in (e["source_doc_id"], e["target_doc_id"]):
                conflicts[did] = conflicts.get(did, 0) + 1
        if e["edge_type"] == "canon_relates_to":
            # Canon node accumulates dependency load from related docs
            depends_on[e["source_doc_id"]] = depends_on.get(e["source_doc_id"], 0) + 1

    all_ids = set(incident) | set(conflicts) | set(depends_on)
    scores = {}
    for did in all_ids:
        scores[did] = (
            incident.get(did, 0)
            + 2 * conflicts.get(did, 0)
            + 0.5 * depends_on.get(did, 0)
        )
    return scores


# ── Sync ─────────────────────────────────────────────────────────────────────

def sync_edges() -> dict:
    """Rebuild doc_edges from lineage + conflicts + optional canon edges.

    Called after crawl_library() completes. Idempotent via INSERT OR REPLACE.
    Returns summary dict.
    """
    all_edges = (
        _edges_from_lineage()
        + _edges_from_conflicts()
        + _edges_canon_relates_to()
    )

    load_scores = _compute_load_scores(all_edges)

    # Inject load scores into edges
    for e in all_edges:
        src_load = load_scores.get(e["source_doc_id"], 0.0)
        tgt_load = load_scores.get(e["target_doc_id"], 0.0)
        e["load_score"] = round(max(src_load, tgt_load), 2)

    # Write to DB (INSERT OR REPLACE via UNIQUE constraint)
    conn = db.get_conn()
    try:
        written = 0
        for e in all_edges:
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO doc_edges
                        (source_doc_id, target_doc_id, edge_type, state,
                         permeability, load_score, detected_ts, detail)
                    VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (
                        e["source_doc_id"], e["target_doc_id"], e["edge_type"],
                        e["state"], e["permeability"], e["load_score"],
                        e["detected_ts"], e["detail"],
                    ),
                )
                written += 1
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()

    return {
        "edges_written": written,
        "total_candidates": len(all_edges),
        "load_scores_computed": len(load_scores),
    }


# ── Node diagnostics ─────────────────────────────────────────────────────────

def get_node_diagnostics(doc_id: str) -> dict:
    """Return DCNS diagnostics for a single document node.

    Used by the graph endpoint to enrich node payloads.
    """
    # Incident edges
    edges = db.fetchall(
        "SELECT edge_type, state FROM doc_edges "
        "WHERE source_doc_id = ? OR target_doc_id = ?",
        (doc_id, doc_id),
    )

    conflict_count  = sum(1 for e in edges if e["edge_type"] == "conflicts")
    total_edges     = len(edges)

    # Daenary coordinate diagnostics
    coords = db.fetchall(
        "SELECT state, confidence, valid_until_ts FROM doc_coordinates WHERE doc_id = ?",
        (doc_id,),
    )
    now = int(time.time())
    expired_count   = sum(1 for c in coords if c["valid_until_ts"] and now > c["valid_until_ts"])
    uncertain_count = sum(1 for c in coords if c["state"] == 0)
    low_conf_count  = sum(1 for c in coords if c.get("confidence") is not None and c["confidence"] < 0.5)

    # Load score from doc_edges (take max incident load)
    load_rows = db.fetchall(
        "SELECT load_score FROM doc_edges "
        "WHERE source_doc_id = ? OR target_doc_id = ?",
        (doc_id, doc_id),
    )
    load_score = max((r["load_score"] or 0.0 for r in load_rows), default=0.0)

    return {
        "load_score":                round(load_score, 2),
        "conflict_count":            conflict_count,
        "expired_coordinate_count":  expired_count,
        "uncertain_coordinate_count": uncertain_count,
        "low_confidence_count":       low_conf_count,
        "total_dcns_edges":          total_edges,
    }


def get_all_doc_edges(doc_ids_set: set | None = None) -> list[dict]:
    """Return all doc_edges, optionally filtered to a set of doc_ids."""
    rows = db.fetchall(
        "SELECT source_doc_id, target_doc_id, edge_type, state, permeability, "
        "load_score, detected_ts, detail FROM doc_edges"
    )
    if doc_ids_set is None:
        return rows
    return [
        r for r in rows
        if r["source_doc_id"] in doc_ids_set and r["target_doc_id"] in doc_ids_set
    ]
