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
               plane_scope_json, version, updated_ts,
               title, summary
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
        basename = os.path.basename(doc["path"] or "").replace(".md", "") or doc["doc_id"][:12]
        display_title = doc.get("title") or basename
        nodes.append({
            "id": doc["doc_id"],
            "label": display_title[:28],
            "title": display_title,
            "summary": doc.get("summary") or "",
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
            edges.append(_enrich_edge({
                "source":       row["source_doc_id"],
                "target":       row["target_doc_id"],
                "type":         row["edge_type"],
                "relationship": row["edge_type"],
                "weight":       row.get("permeability") or 1.0,
                "state":        row.get("state"),
                "loadScore":    row.get("load_score"),
                "detail":       row.get("detail"),
            }, node_ids))

    # Fallback: lineage records not yet in doc_edges
    lineage_rows = db.fetchall(
        "SELECT doc_id, related_doc_id, relationship FROM lineage"
    )
    for row in lineage_rows:
        if row["doc_id"] in node_ids and row["related_doc_id"] in node_ids:
            key = tuple(sorted([row["doc_id"], row["related_doc_id"]]) + ["lineage"])
            if key not in seen_edges:
                seen_edges.add(key)
                edges.append(_enrich_edge({
                    "source":       row["doc_id"],
                    "target":       row["related_doc_id"],
                    "type":         "lineage",
                    "relationship": row["relationship"],
                    "weight":       1.0,
                    "state":        None,
                    "loadScore":    None,
                }, node_ids))

    # Topic similarity edges (inferred, only for small corpora)
    if len(docs) <= 80:
        doc_topic_map = {
            doc["doc_id"]: set((doc["topics_tokens"] or "").split()) - {""}
            for doc in docs
        }
        for i, doc_a in enumerate(docs):
            tokens_a = doc_topic_map[doc_a["doc_id"]]
            if not tokens_a:
                continue
            for doc_b in docs[i + 1:]:
                tokens_b = doc_topic_map[doc_b["doc_id"]]
                if not tokens_b:
                    continue
                j = _jaccard(tokens_a, tokens_b)
                if j >= 0.3:
                    key = tuple(sorted([doc_a["doc_id"], doc_b["doc_id"]]) + ["related"])
                    if key not in seen_edges:
                        seen_edges.add(key)
                        shared = sorted(tokens_a & tokens_b)[:8]
                        edges.append({
                            "source":        doc_a["doc_id"],
                            "target":        doc_b["doc_id"],
                            "type":          "related",
                            "relationship":  "topic_similarity",
                            "weight":        round(j, 3),
                            "label":         "shared topics",
                            "reasons":       [f"topic: {t}" for t in shared],
                            "shared_topics": shared,
                            "crossovers":    [{"kind": "topic", "value": t} for t in shared],
                            "state":         None,
                            "loadScore":     None,
                        })

    return {"nodes": nodes, "edges": edges}


def _enrich_edge(edge: dict, node_ids: set) -> dict:
    """Add reasons, shared_topics, crossovers, and label to an edge dict."""
    import json as _json

    edge_type = edge.get("type") or edge.get("relationship") or "link"

    # Parse detail JSON if present
    detail_obj: dict = {}
    try:
        raw = edge.get("detail")
        if raw and isinstance(raw, str):
            detail_obj = _json.loads(raw)
    except Exception:
        pass

    reasons: list[str] = []
    shared_topics: list[str] = []
    crossovers: list[dict] = []

    # Derive reasons from edge type
    if edge_type in ("duplicate_content",):
        reasons.append("content duplicate")
        crossovers.append({"kind": "content", "value": "identical"})
    elif edge_type in ("supersedes",):
        reasons.append("supersedes older version")
        crossovers.append({"kind": "lineage", "value": "supersession"})
    elif edge_type in ("derives", "derived_from"):
        reasons.append("derived from source")
        crossovers.append({"kind": "lineage", "value": "derivation"})
    elif edge_type in ("conflicts",):
        reasons.append("definition conflict")
        crossovers.append({"kind": "conflict", "value": "contradicts"})
    elif edge_type in ("canon_relates_to",):
        reasons.append("canon relation")
        ti = detail_obj.get("topic_jaccard")
        if ti:
            reasons.append(f"topic similarity: {ti:.2f}")

    # Shared topics from doc tokens
    src_id = edge.get("source")
    tgt_id = edge.get("target")
    if src_id and tgt_id and src_id in node_ids and tgt_id in node_ids:
        src_row = db.fetchone("SELECT topics_tokens FROM docs WHERE doc_id=?", (src_id,))
        tgt_row = db.fetchone("SELECT topics_tokens FROM docs WHERE doc_id=?", (tgt_id,))
        if src_row and tgt_row:
            a = set((src_row["topics_tokens"] or "").split()) - {""}
            b = set((tgt_row["topics_tokens"] or "").split()) - {""}
            shared_topics = sorted(a & b)[:8]
            for t in shared_topics:
                crossovers.append({"kind": "topic", "value": t})
                if f"topic: {t}" not in reasons:
                    reasons.append(f"topic: {t}")

    label_map = {
        "lineage": "lineage",
        "duplicate_content": "duplicate",
        "supersedes": "supersedes",
        "derives": "derives",
        "conflicts": "conflict",
        "canon_relates_to": "canon link",
        "related": "shared topics",
    }
    label = label_map.get(edge_type, edge_type)

    return {
        **edge,
        "label":         label,
        "reasons":       reasons,
        "shared_topics": shared_topics,
        "crossovers":    crossovers,
    }


def get_neighborhood(doc_id: str, depth: int = 1, limit: int = 40) -> dict:
    """Return the local neighborhood graph around a document.

    depth=1 — direct neighbors only
    depth=2 — neighbors of neighbors (limit applied aggressively)
    Nodes and edges include enrichment (reasons, shared_topics, crossovers).
    """
    import os
    depth = max(1, min(2, depth))   # clamp to [1, 2]
    limit = max(5, min(80, limit))  # clamp to [5, 80]

    center = db.fetchone(
        "SELECT doc_id, path, type, status, corpus_class, topics_tokens, "
        "title, summary, updated_ts FROM docs WHERE doc_id = ?",
        (doc_id,),
    )
    if not center:
        return {"error": f"Document {doc_id!r} not found", "nodes": [], "edges": []}

    # Collect neighbor doc_ids from doc_edges + lineage
    neighbor_ids: set[str] = set()

    edge_rows = db.fetchall(
        "SELECT source_doc_id, target_doc_id FROM doc_edges "
        "WHERE source_doc_id=? OR target_doc_id=?",
        (doc_id, doc_id),
    )
    for row in edge_rows:
        neighbor_ids.add(row["source_doc_id"])
        neighbor_ids.add(row["target_doc_id"])

    lineage_rows = db.fetchall(
        "SELECT doc_id, related_doc_id FROM lineage WHERE doc_id=? OR related_doc_id=?",
        (doc_id, doc_id),
    )
    for row in lineage_rows:
        neighbor_ids.add(row["doc_id"])
        neighbor_ids.add(row["related_doc_id"])

    neighbor_ids.discard(doc_id)

    if depth == 2 and len(neighbor_ids) < limit:
        # One more hop
        for nid in list(neighbor_ids):
            second_edges = db.fetchall(
                "SELECT source_doc_id, target_doc_id FROM doc_edges "
                "WHERE source_doc_id=? OR target_doc_id=?",
                (nid, nid),
            )
            for row in second_edges:
                neighbor_ids.add(row["source_doc_id"])
                neighbor_ids.add(row["target_doc_id"])
            if len(neighbor_ids) >= limit:
                break
        neighbor_ids.discard(doc_id)

    neighbor_ids = set(list(neighbor_ids)[:limit])

    all_ids = {doc_id} | neighbor_ids
    if not all_ids:
        return {"nodes": [], "edges": []}

    ph = ",".join("?" * len(all_ids))
    docs = db.fetchall(
        f"SELECT doc_id, path, type, status, corpus_class, topics_tokens, "
        f"title, summary, updated_ts FROM docs WHERE doc_id IN ({ph})",
        tuple(all_ids),
    )

    from app.core.canon import canon_score as _canon_score
    from app.core.dcns import get_node_diagnostics

    nodes = []
    for doc in docs:
        c_score = _canon_score(doc)
        diag    = get_node_diagnostics(doc["doc_id"])
        basename = os.path.basename(doc["path"] or "").replace(".md", "") or doc["doc_id"][:12]
        display_title = doc.get("title") or basename
        nodes.append({
            "id":           doc["doc_id"],
            "label":        display_title[:28],
            "title":        display_title,
            "summary":      doc.get("summary") or "",
            "path":         doc["path"],
            "type":         doc["type"],
            "status":       doc["status"],
            "corpusClass":  doc["corpus_class"],
            "canonScore":   round(c_score, 1),
            "topics":       doc["topics_tokens"] or "",
            "isCenter":     doc["doc_id"] == doc_id,
            "loadScore":    diag["load_score"],
            "conflictCount": diag["conflict_count"],
        })

    # Build enriched edges
    seen: set = set()
    edges: list[dict] = []

    from app.core.dcns import get_all_doc_edges
    for row in get_all_doc_edges(all_ids):
        key = tuple(sorted([row["source_doc_id"], row["target_doc_id"]]) + [row["edge_type"]])
        if key not in seen:
            seen.add(key)
            edges.append(_enrich_edge({
                "source":   row["source_doc_id"],
                "target":   row["target_doc_id"],
                "type":     row["edge_type"],
                "weight":   row.get("permeability") or 1.0,
                "state":    row.get("state"),
                "detail":   row.get("detail"),
            }, all_ids))

    for row in db.fetchall(
        "SELECT doc_id, related_doc_id, relationship FROM lineage "
        "WHERE (doc_id=? OR related_doc_id=?) AND doc_id IN ({ph}) AND related_doc_id IN ({ph})".format(ph=ph),
        (doc_id, doc_id, *tuple(all_ids), *tuple(all_ids)),
    ):
        key = tuple(sorted([row["doc_id"], row["related_doc_id"]]) + ["lineage"])
        if key not in seen:
            seen.add(key)
            edges.append(_enrich_edge({
                "source": row["doc_id"],
                "target": row["related_doc_id"],
                "type":   "lineage",
                "weight": 1.0,
            }, all_ids))

    return {"nodes": nodes, "edges": edges, "center_doc_id": doc_id}
