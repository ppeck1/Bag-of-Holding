"""app/core/search.py: Search engine with explainable scoring for Bag of Holding v2.

Moved from search.py (v0P). Logic unchanged.
Phase 8 additions (Daenary):
  - Optional Daenary filter params (dimension, state, min_quality, min_confidence,
    stale, uncertain_only, conflicts_only)
  - Coordinate summary attached to results when coordinates exist
  - Small additive ranking adjustment from Daenary (does not override canon scoring)

Score formula (math_authority.md §4):
    base  = 0.6 * text_score + 0.2 * canon_score_normalized + 0.2 * planar_alignment + conflict_penalty
    final = base + daenary_adjustment   (adjustment range: -0.05 to +0.05)
"""

import json
import time

from app.db import connection as db
from app.core.canon import canon_score
from app.core.planar import planar_alignment_score
from app.core.daenary import format_coordinate_summary, is_stale


CONFLICT_PENALTY = -0.1  # math_authority.md §4d


def _daenary_adjustment(coords: list[dict], uncertain_only: bool = False) -> float:
    """Small additive adjustment from Daenary coordinates.
    Range: -0.05 to +0.05. Does not override canon scoring.
    """
    if not coords:
        return 0.0

    now = int(time.time())
    adj = 0.0
    for c in coords:
        conf = c.get("confidence")
        qual = c.get("quality")
        vut  = c.get("valid_until_ts")

        # Stale penalty
        if vut and now > vut:
            adj -= 0.05
            continue

        if conf is not None and qual is not None:
            if conf >= 0.7:
                adj += 0.05   # high confidence dimension
            elif uncertain_only and c.get("state") == 0 and qual >= 0.6:
                adj += 0.03   # high-quality uncertain doc explicitly requested

    # Clamp to safe range
    return max(-0.05, min(0.05, adj))


def search(
    query: str,
    plane_filter: str = None,
    limit: int = 20,
    # Phase 8 Daenary filter params
    dimension: str = None,
    state: int | None = None,
    min_quality: float | None = None,
    min_confidence: float | None = None,
    stale: bool = False,
    uncertain_only: bool = False,
    conflicts_only: bool = False,
) -> list[dict]:
    """Full-text search with explainable composite scoring.

    Returns results sorted by final_score descending.
    Every result includes score_breakdown (explainability requirement).

    Base formula: 0.6*text_score + 0.2*canon_norm + 0.2*planar_alignment + conflict_penalty
    Phase 8 addition: + daenary_adjustment (additive, range [-0.05, +0.05])
    See math_authority.md §4 for all component definitions.
    """
    if not query:
        return []

    # FTS5 BM25 search
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

    # Load full doc rows for scoring
    placeholders = ",".join("?" * len(paths))
    docs = db.fetchall(f"SELECT * FROM docs WHERE path IN ({placeholders})", tuple(paths))
    doc_map = {d["path"]: d for d in docs}

    # Normalize BM25 scores: SQLite BM25 is negative (lower = better)
    bm25_scores = [bm25_map.get(p, 0) for p in paths]
    min_bm25 = min(bm25_scores)
    max_bm25 = max(bm25_scores)
    bm25_range = max_bm25 - min_bm25 if max_bm25 != min_bm25 else 1

    # Build conflict doc_id set for penalty application
    conflict_doc_ids = set()
    all_conflicts = db.fetchall("SELECT doc_ids FROM conflicts")
    for c in all_conflicts:
        for did in (c["doc_ids"] or "").split(","):
            conflict_doc_ids.add(did.strip())

    # Phase 8: apply conflicts_only pre-filter if requested
    if conflicts_only:
        docs = [d for d in docs if d["doc_id"] in conflict_doc_ids]
        doc_map = {d["path"]: d for d in docs}

    # Phase 8: Daenary pre-filter — build eligible doc_id set
    daenary_eligible: set | None = None
    now_ts = int(time.time())

    if any(f is not None and f is not False for f in [dimension, state, min_quality, min_confidence, stale, uncertain_only]):
        coord_clauses = []
        coord_params: list = []

        if dimension:
            coord_clauses.append("dimension = ?")
            coord_params.append(dimension.strip().lower())
        if state is not None:
            coord_clauses.append("state = ?")
            coord_params.append(int(state))
        if min_quality is not None:
            coord_clauses.append("quality >= ?")
            coord_params.append(float(min_quality))
        if min_confidence is not None:
            coord_clauses.append("confidence >= ?")
            coord_params.append(float(min_confidence))
        if stale:
            coord_clauses.append("valid_until_ts IS NOT NULL AND valid_until_ts < ?")
            coord_params.append(now_ts)
        if uncertain_only:
            coord_clauses.append("state = 0")
            if "mode = 'contain'" not in " ".join(coord_clauses):
                coord_clauses.append("(mode = 'contain' OR mode IS NULL)")

        where = " AND ".join(coord_clauses) if coord_clauses else "1=1"
        coord_rows = db.fetchall(
            f"SELECT DISTINCT doc_id FROM doc_coordinates WHERE {where}",
            tuple(coord_params),
        )
        daenary_eligible = {r["doc_id"] for r in coord_rows}

    results = []
    for path in paths:
        doc = doc_map.get(path)
        if not doc:
            continue

        # Phase 8: apply Daenary pre-filter
        if daenary_eligible is not None and doc["doc_id"] not in daenary_eligible:
            continue

        # 4a: text_score — normalize BM25 to [0,1]
        raw_bm25 = bm25_map.get(path, 0)
        text_score = 1.0 - (raw_bm25 - min_bm25) / bm25_range if bm25_range else 1.0
        text_score = max(0.0, min(1.0, text_score))

        # 4b: canon_score normalized — max 180 (math_authority.md §4b)
        c_raw = canon_score(doc)
        c_norm = max(0.0, min(1.0, c_raw / 180.0))

        # 4c: planar alignment
        plane_scopes = json.loads(doc.get("plane_scope_json") or "[]")
        p_score = planar_alignment_score(plane_scopes, plane_filter)

        # 4d: conflict penalty
        has_conflict = doc["doc_id"] in conflict_doc_ids
        penalty = CONFLICT_PENALTY if has_conflict else 0.0

        base_score = 0.6 * text_score + 0.2 * c_norm + 0.2 * p_score + penalty

        # Phase 8: fetch coordinates for this doc and compute adjustment
        coords = db.fetchall(
            "SELECT * FROM doc_coordinates WHERE doc_id = ?", (doc["doc_id"],)
        )
        daenary_adj = _daenary_adjustment(coords, uncertain_only=uncertain_only)
        final = base_score + daenary_adj

        coord_summary = format_coordinate_summary(coords) if coords else None

        result_row = {
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
                "daenary_adjustment": round(daenary_adj, 4),
            },
            "has_conflict": has_conflict,
        }
        if coord_summary:
            result_row["daenary_summary"] = coord_summary

        results.append(result_row)

    results.sort(key=lambda x: x["final_score"], reverse=True)
    return results[:limit]
