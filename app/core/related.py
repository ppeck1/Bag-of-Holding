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
    """Return Phase 14 Atlas graph data grouped by project → class → layer.

    Suggested semantic/topic edges are never authoritative across projects.
    Cross-project edges are rendered as suggested, low-authority links until approved.
    """
    from app.core.dcns import get_node_diagnostics, get_all_doc_edges
    from app.core.authority_state import authority_score

    docs = db.fetchall(
        """
        SELECT doc_id, path, type, status, corpus_class, topics_tokens,
               plane_scope_json, version, updated_ts, title, summary,
               project, document_class, canonical_layer, authority_state,
               review_state, provenance_json, source_hash, document_id,
               epistemic_d, epistemic_m, epistemic_q, epistemic_c,
               epistemic_correction_status, epistemic_valid_until,
               epistemic_context_ref, epistemic_source_ref,
               epistemic_last_evaluated, meaning_cost_json,
               custodian_review_state
        FROM docs
        ORDER BY project, document_class,
          CASE canonical_layer
            WHEN 'canonical' THEN 0
            WHEN 'supporting' THEN 1
            WHEN 'evidence' THEN 2
            WHEN 'review' THEN 3
            WHEN 'conflict' THEN 4
            WHEN 'quarantine' THEN 5
            WHEN 'archive' THEN 6
            ELSE 7
          END,
          updated_ts DESC
        LIMIT ?
        """,
        (max_nodes,),
    )

    import os
    nodes = []
    projects, classes, layers = set(), set(), set()
    for doc in docs:
        diag = get_node_diagnostics(doc["doc_id"])
        project = doc.get("project") or "Quarantine / Legacy Import"
        document_class = doc.get("document_class") or doc.get("type") or "unknown"
        layer = doc.get("canonical_layer") or "quarantine"
        projects.add(project); classes.add(document_class); layers.add(layer)
        basename = os.path.basename(doc["path"] or "").replace(".md", "") or doc["doc_id"][:12]
        display_title = doc.get("title") or basename
        authority = authority_score(doc.get("status") or "", layer, doc.get("review_state") or "")
        # Compute canon score for node sizing
        try:
            from app.core.canon import canon_score as _cs
            c_score = _cs(dict(doc))
        except Exception:
            c_score = round(authority * 100, 1)
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
            "project": project,
            "projectId": project,
            "document_class": document_class,
            "documentClass": document_class,
            "canonical_layer": layer,
            "canonicalLayer": layer,
            "authority_state": doc.get("authority_state") or "quarantined",
            "authority": authority,
            "review_state": doc.get("review_state") or "unassigned",
            "version": doc.get("version"),
            "topics": doc["topics_tokens"] or "",
            "loadScore": diag["load_score"],
            "conflictCount": diag["conflict_count"],
            "expiredCoordinates": diag["expired_coordinate_count"],
            "uncertainCoordinates": diag["uncertain_coordinate_count"],
            # Phase 18: Daenary epistemic substrate
            "epistemic_d":                 doc.get("epistemic_d"),
            "epistemic_m":                 doc.get("epistemic_m"),
            "epistemic_q":                 doc.get("epistemic_q"),
            "epistemic_c":                 doc.get("epistemic_c"),
            "epistemic_correction_status": doc.get("epistemic_correction_status"),
            "epistemic_valid_until":       doc.get("epistemic_valid_until"),
            "meaning_cost_json":           doc.get("meaning_cost_json"),
            "custodian_review_state":      doc.get("custodian_review_state"),
        })

    node_ids = {n["id"] for n in nodes}
    node_project = {n["id"]: n["project"] for n in nodes}
    node_layer = {n["id"]: n["canonical_layer"] for n in nodes}
    seen_edges: set = set()
    edges: list[dict] = []

    def add_edge(edge: dict):
        src, tgt = edge.get("source"), edge.get("target")
        if src not in node_ids or tgt not in node_ids:
            return
        cross = node_project.get(src) != node_project.get(tgt)
        approved = bool(edge.get("approved", edge.get("authority") == "approved"))
        if cross and not approved:
            edge["type"] = edge.get("type") or "suggested"
            edge["authority"] = "suggested"
            edge["approved"] = False
            edge["suggested"] = True
            edge["weight"] = min(float(edge.get("weight") or 0.2), 0.25)
            edge["style"] = "low-opacity dashed"
        else:
            edge.setdefault("authority", "approved" if approved or edge.get("type") in {"lineage","supersedes","derived_from","derives"} else "suggested")
            edge.setdefault("approved", approved or edge["authority"] == "approved")
        edge["cross_project"] = cross
        key = tuple(sorted([src, tgt]) + [edge.get("type", "edge")])
        if key not in seen_edges:
            seen_edges.add(key)
            edges.append(edge)

    for row in get_all_doc_edges(node_ids):
        typ = row["edge_type"]
        # Normalize: "derived_from" -> "derives" for backward compat with existing tests
        norm_typ = "derives" if typ in ("derived_from", "derives") else typ
        add_edge(_enrich_edge({
            "source": row["source_doc_id"],
            "target": row["target_doc_id"],
            "type":   norm_typ,
            "relationship": typ,
            "strength": row.get("permeability") or 1.0,
            "weight":   row.get("permeability") or 1.0,
            "state":    row.get("state"),
            "loadScore": row.get("load_score"),
            "detail":   row.get("detail"),
            "approved": True,
            "authority": "approved",
        }, node_ids))

    for row in db.fetchall("SELECT doc_id, related_doc_id, relationship FROM lineage"):
        if row["doc_id"] in node_ids and row["related_doc_id"] in node_ids:
            rel = row["relationship"] or "lineage"
            add_edge(_enrich_edge({
                "source": row["doc_id"],
                "target": row["related_doc_id"],
                "type": "supersedes" if rel == "supersedes" else ("derives" if rel in {"derives", "derived_from"} else "lineage"),
                "relationship": rel,
                "strength": 1.0,
                "weight": 1.0,
                "approved": True,
                "authority": "approved",
            }, node_ids))

    # Topic overlap edges remain suggested and non-authoritative by default.
    n_docs = len(docs)
    if n_docs <= 500:
        threshold = 0.30 if n_docs <= 80 else (0.40 if n_docs <= 200 else 0.55)
        max_topic_edges = min(240, n_docs * 3)
        doc_topic_map = {doc["doc_id"]: set((doc["topics_tokens"] or "").split()) - {""} for doc in docs}
        candidates = []
        for i, doc_a in enumerate(docs):
            tokens_a = doc_topic_map[doc_a["doc_id"]]
            if not tokens_a: continue
            for doc_b in docs[i+1:]:
                tokens_b = doc_topic_map[doc_b["doc_id"]]
                if not tokens_b: continue
                j = _jaccard(tokens_a, tokens_b)
                if j >= threshold:
                    candidates.append((j, doc_a["doc_id"], doc_b["doc_id"], sorted(tokens_a & tokens_b)[:8]))
        for j, aid, bid, shared in sorted(candidates, key=lambda x: x[0], reverse=True)[:max_topic_edges]:
            add_edge({
                "source": aid, "target": bid,
                "type": "related",          # normalized from topic_overlap for test compat
                "relationship": "topic_similarity",
                "strength": round(j, 3),
                "weight":   round(j, 3),
                "label":    "shared topics",
                "reasons":  [f"topic: {t}" for t in shared],
                "shared_topics": shared,
                "crossovers":    [{"kind": "topic", "value": t} for t in shared],
                "authority": "suggested",
                "approved":  False,
            })

    clusters = []
    for project in sorted(projects):
        for klass in sorted({n["document_class"] for n in nodes if n["project"] == project}):
            ids = [n["id"] for n in nodes if n["project"] == project and n["document_class"] == klass]
            if ids:
                clusters.append({"project": project, "class": klass, "node_ids": ids, "count": len(ids)})

    return {
        "projects": sorted(projects),
        "classes": sorted(classes),
        "layers": sorted(layers),
        "clusters": clusters,
        "nodes": nodes,
        "edges": edges,
    }



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
