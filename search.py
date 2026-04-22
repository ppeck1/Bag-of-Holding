"""search.py: Search engine with explainable scoring for Bag of Holding v0P."""

import json

import db
from canon import canon_score
from planar import planar_alignment_score


CONFLICT_PENALTY = -0.1


def search(query: str, plane_filter: str = None, limit: int = 20) -> list[dict]:
    """
    Full-text search with explainable scoring.

    final_score = 0.6 * text_score + 0.2 * canon_score + 0.2 * planar_alignment_score + conflict_penalty
    """
    if not query:
        return []

    # FTS search
    try:
        fts_rows = db.fetchall(
            """
            SELECT docs_fts.path, docs_fts.title,
                   bm25(docs_fts) as bm25_score
            FROM docs_fts
            WHERE docs_fts MATCH ?
            ORDER BY bm25_score
            LIMIT ?
            """,
            (query, limit * 2),
        )
    except Exception as e:
        return [{"error": str(e)}]

    if not fts_rows:
        return []

    paths = [r["path"] for r in fts_rows]
    bm25_map = {r["path"]: r["bm25_score"] for r in fts_rows}

    # Load full doc rows
    placeholders = ",".join("?" * len(paths))
    docs = db.fetchall(f"SELECT * FROM docs WHERE path IN ({placeholders})", tuple(paths))
    doc_map = {d["path"]: d for d in docs}

    # BM25 from SQLite is negative (lower = better), normalize to [0,1]
    bm25_scores = [bm25_map.get(p, 0) for p in paths]
    min_bm25 = min(bm25_scores)
    max_bm25 = max(bm25_scores)
    bm25_range = max_bm25 - min_bm25 if max_bm25 != min_bm25 else 1

    # Check which docs have conflicts
    conflict_doc_ids = set()
    all_conflicts = db.fetchall("SELECT doc_ids FROM conflicts")
    for c in all_conflicts:
        for did in (c["doc_ids"] or "").split(","):
            conflict_doc_ids.add(did.strip())

    results = []
    for path in paths:
        doc = doc_map.get(path)
        if not doc:
            continue

        # Text score: normalize BM25 (lower bm25 = better match in SQLite)
        raw_bm25 = bm25_map.get(path, 0)
        text_score = 1.0 - (raw_bm25 - min_bm25) / bm25_range if bm25_range else 1.0
        text_score = max(0.0, min(1.0, text_score))

        # Canon score: normalize to [0,1] using rough max of ~180
        c_raw = canon_score(doc)
        c_norm = max(0.0, min(1.0, c_raw / 180.0))

        # Planar alignment
        plane_scopes = json.loads(doc.get("plane_scope_json") or "[]")
        p_score = planar_alignment_score(plane_scopes, plane_filter)

        # Conflict penalty
        has_conflict = doc["doc_id"] in conflict_doc_ids
        penalty = CONFLICT_PENALTY if has_conflict else 0.0

        final = 0.6 * text_score + 0.2 * c_norm + 0.2 * p_score + penalty

        results.append({
            "doc_id": doc["doc_id"],
            "path": path,
            "title": fts_rows[paths.index(path)]["title"] if path in paths else "",
            "status": doc["status"],
            "type": doc["type"],
            "operator_state": doc["operator_state"],
            "final_score": round(final, 6),
            "score_breakdown": {
                "text_score": round(text_score, 4),
                "text_weight": 0.6,
                "canon_score_raw": round(c_raw, 2),
                "canon_score_normalized": round(c_norm, 4),
                "canon_weight": 0.2,
                "planar_alignment_score": round(p_score, 4),
                "planar_weight": 0.2,
                "conflict_penalty": penalty,
            },
            "has_conflict": has_conflict,
        })

    results.sort(key=lambda x: x["final_score"], reverse=True)
    return results[:limit]
