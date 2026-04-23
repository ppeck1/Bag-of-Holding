"""app/core/related.py: Related document scoring for Bag of Holding v2.

Implements blueprint §4 (Semantic Navigation System):
  - Topic token overlap (Jaccard)
  - Plane scope overlap
  - Lineage relationship bonus
  - Shared definition terms
  - Same type bonus

All scoring is deterministic. No ML inference.
Returns ranked candidates for a given document.
"""

import json
from app.db import connection as db


def _jaccard(set_a: set, set_b: set) -> float:
    """Jaccard similarity: |A∩B| / |A∪B|. Returns 0.0 if both empty."""
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def get_related(doc_id: str, limit: int = 8) -> dict:
    """Return ranked related documents for a given doc_id.

    Scoring components:
      0.45 × topic_jaccard       — normalized topic token overlap
      0.25 × scope_jaccard       — plane_scope set overlap
      0.20 × lineage_bonus       — 1.0 if any lineage link exists, else 0
      0.10 × shared_defs         — shared definition terms (capped at 1.0)
    """
    source = db.fetchone("SELECT * FROM docs WHERE doc_id = ?", (doc_id,))
    if not source:
        return {"doc_id": doc_id, "related": [], "error": "Document not found"}

    source_topics = set((source.get("topics_tokens") or "").split()) - {""}
    source_scope  = set(json.loads(source.get("plane_scope_json") or "[]"))
    source_type   = source.get("type") or ""

    # Get source definition terms
    source_defs = {r["term"] for r in db.fetchall(
        "SELECT DISTINCT term FROM defs WHERE doc_id = ?", (doc_id,)
    )}

    # All other docs
    candidates = db.fetchall(
        "SELECT doc_id, path, type, status, corpus_class, topics_tokens, "
        "plane_scope_json, version FROM docs WHERE doc_id != ?",
        (doc_id,),
    )

    # Lineage connections for this doc (both directions)
    lineage_connected = set()
    for row in db.fetchall(
        "SELECT related_doc_id FROM lineage WHERE doc_id = ?", (doc_id,)
    ):
        lineage_connected.add(row["related_doc_id"])
    for row in db.fetchall(
        "SELECT doc_id as related_doc_id FROM lineage WHERE related_doc_id = ?", (doc_id,)
    ):
        lineage_connected.add(row["related_doc_id"])

    scored = []
    for cand in candidates:
        cand_topics = set((cand.get("topics_tokens") or "").split()) - {""}
        cand_scope  = set(json.loads(cand.get("plane_scope_json") or "[]"))

        topic_j  = _jaccard(source_topics, cand_topics)
        scope_j  = _jaccard(source_scope, cand_scope) if (source_scope or cand_scope) else 0.0
        lineage  = 1.0 if cand["doc_id"] in lineage_connected else 0.0

        # Shared defs (capped at 1.0 normalized)
        cand_defs = {r["term"] for r in db.fetchall(
            "SELECT DISTINCT term FROM defs WHERE doc_id = ?", (cand["doc_id"],)
        )}
        shared_def_count = len(source_defs & cand_defs)
        def_score = min(1.0, shared_def_count / max(len(source_defs), 1)) if source_defs else 0.0

        total = (
            0.45 * topic_j +
            0.25 * scope_j +
            0.20 * lineage  +
            0.10 * def_score
        )

        if total > 0.0:
            scored.append({
                "doc_id": cand["doc_id"],
                "path": cand["path"],
                "type": cand["type"],
                "status": cand["status"],
                "corpus_class": cand["corpus_class"],
                "version": cand["version"],
                "score": round(total, 4),
                "score_breakdown": {
                    "topic_overlap": round(topic_j, 4),
                    "scope_overlap": round(scope_j, 4),
                    "lineage_bonus": lineage,
                    "shared_defs": round(def_score, 4),
                },
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return {
        "doc_id": doc_id,
        "source_path": source["path"],
        "related": scored[:limit],
        "total_candidates": len(candidates),
    }


def get_graph_data(max_nodes: int = 200) -> dict:
    """Return graph nodes and edges for the Atlas visualization.

    Phase 8: edges now sourced from doc_edges (explicit DCNS) first,
    falling back to lineage + topic-similarity inferred edges.
    Node payload enriched with DCNS diagnostics.

    Returns:
      { nodes: [...], edges: [...] }
    """
    from app.core.dcns import get_node_diagnostics, get_all_doc_edges

    docs = db.fetchall(
        """
        SELECT doc_id, path, type, status, corpus_class, topics_tokens,
               plane_scope_json, version, updated_ts
        FROM docs
        ORDER BY
          CASE corpus_class
            WHEN 'CORPUS_CLASS:CANON' THEN 0
            WHEN 'CORPUS_CLASS:DRAFT' THEN 1
            WHEN 'CORPUS_CLASS:DERIVED' THEN 2
            WHEN 'CORPUS_CLASS:EVIDENCE' THEN 3
            WHEN 'CORPUS_CLASS:ARCHIVE' THEN 4
            ELSE 5
          END,
          updated_ts DESC
        LIMIT ?
        """,
        (max_nodes,),
    )

    # Build node list with DCNS diagnostics
    import os
    nodes = []
    for doc in docs:
        from app.core.canon import canon_score
        c_score = canon_score(doc)
        diag = get_node_diagnostics(doc["doc_id"])
        nodes.append({
            "id": doc["doc_id"],
            "label": os.path.basename(doc["path"] or "").replace(".md", "") or doc["doc_id"][:12],
            "path": doc["path"],
            "type": doc["type"],
            "status": doc["status"],
            "corpusClass": doc["corpus_class"],
            "canonScore": round(c_score, 1),
            "topics": doc["topics_tokens"] or "",
            # DCNS diagnostics
            "loadScore":              diag["load_score"],
            "conflictCount":          diag["conflict_count"],
            "expiredCoordinates":     diag["expired_coordinate_count"],
            "uncertainCoordinates":   diag["uncertain_coordinate_count"],
        })

    node_ids = {n["id"] for n in nodes}

    # Phase 8: prefer explicit doc_edges over raw lineage
    seen_edges: set = set()
    edges: list[dict] = []

    explicit_edges = get_all_doc_edges(node_ids)
    for row in explicit_edges:
        key = tuple(sorted([row["source_doc_id"], row["target_doc_id"]]) + [row["edge_type"]])
        if key not in seen_edges:
            seen_edges.add(key)
            edges.append({
                "source":       row["source_doc_id"],
                "target":       row["target_doc_id"],
                "type":         row["edge_type"],
                "relationship": row["edge_type"],
                "weight":       row.get("permeability") or 1.0,
                "state":        row.get("state"),
                "loadScore":    row.get("load_score"),
            })

    # Fallback: lineage records not yet in doc_edges
    lineage_rows = db.fetchall(
        "SELECT doc_id, related_doc_id, relationship FROM lineage"
    )
    for row in lineage_rows:
        if row["doc_id"] in node_ids and row["related_doc_id"] in node_ids:
            key = tuple(sorted([row["doc_id"], row["related_doc_id"]]) + ["lineage"])
            if key not in seen_edges:
                seen_edges.add(key)
                edges.append({
                    "source":       row["doc_id"],
                    "target":       row["related_doc_id"],
                    "type":         "lineage",
                    "relationship": row["relationship"],
                    "weight":       1.0,
                    "state":        None,
                    "loadScore":    None,
                })

    # Topic similarity edges (inferred, only for small corpora)
    if len(docs) <= 80:
        for i, doc_a in enumerate(docs):
            tokens_a = set((doc_a["topics_tokens"] or "").split()) - {""}
            if not tokens_a:
                continue
            for doc_b in docs[i + 1:]:
                tokens_b = set((doc_b["topics_tokens"] or "").split()) - {""}
                if not tokens_b:
                    continue
                j = _jaccard(tokens_a, tokens_b)
                if j >= 0.3:
                    key = tuple(sorted([doc_a["doc_id"], doc_b["doc_id"]]) + ["related"])
                    if key not in seen_edges:
                        seen_edges.add(key)
                        edges.append({
                            "source":       doc_a["doc_id"],
                            "target":       doc_b["doc_id"],
                            "type":         "related",
                            "relationship": "topic_similarity",
                            "weight":       round(j, 3),
                            "state":        None,
                            "loadScore":    None,
                        })

    return {"nodes": nodes, "edges": edges}
