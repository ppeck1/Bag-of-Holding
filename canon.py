"""canon.py: Deterministic canon resolution engine for Bag of Holding v0P.

Patch v1.1: A1.3 topic LIKE query, A1.4 topic boost, B1 plane_scope filter, B2 collision fix.
"""

import json
import time

import db
from parser import parse_semver
from crawler import normalize_topic_token

AMBIGUITY_THRESHOLD = 0.05  # 5%


def canon_score(doc: dict) -> float:
    """Compute deterministic canon score for a document row."""
    score = 0.0

    status = doc.get("status", "")
    doc_type = doc.get("type", "")
    source_type = doc.get("source_type", "")
    version = doc.get("version")
    updated_ts = doc.get("updated_ts") or 0

    if status == "canonical":
        score += 100
    if doc_type == "canon":
        score += 50
    if source_type == "canon_folder" or "/canon/" in (doc.get("path") or ""):
        score += 30

    score += 10 * parse_semver(version)
    score += 0.000001 * updated_ts

    if status == "archived":
        score -= 40

    return score


def resolve_canon(topic: str = None, plane_scope: str = None) -> dict:
    """
    Resolve the canonical document for a given topic/plane.

    A1.3: Uses topics_tokens LIKE query instead of FTS.
    B1: Filters by plane_scope overlap when plane_scope param provided.
    """
    # A1.3: Use topics_tokens LIKE for topic matching (not FTS)
    if topic:
        normalized_topic = normalize_topic_token(topic)
        docs = db.fetchall(
            "SELECT * FROM docs WHERE topics_tokens LIKE ?",
            (f"%{normalized_topic}%",),
        )
    else:
        docs = db.fetchall(
            "SELECT * FROM docs WHERE status != 'archived' OR status IS NULL"
        )

    if not docs:
        return {"winner": None, "candidates": [], "ambiguity_conflicts": []}

    # B1: Filter by plane_scope overlap if provided
    if plane_scope:
        request_scope = set(plane_scope.split(",")) if "," in plane_scope else {plane_scope}
        filtered = []
        for doc in docs:
            doc_scope = set(json.loads(doc.get("plane_scope_json") or "[]"))
            if doc_scope & request_scope:  # non-empty intersection
                filtered.append(doc)
        docs = filtered

    if not docs:
        return {"winner": None, "candidates": [], "ambiguity_conflicts": []}

    scored = []
    for doc in docs:
        s = canon_score(doc)

        # A1.4: Topic boost — deterministic, only when topic filter is active
        if topic:
            normalized_topic = normalize_topic_token(topic)
            tokens = doc.get("topics_tokens") or ""
            topic_score = 1 if normalized_topic in tokens else 0
            s += 20 * topic_score  # add weighted topic boost

        scored.append({"doc": doc, "score": s})

    scored.sort(key=lambda x: x["score"], reverse=True)

    conflicts_created = []
    if len(scored) >= 2:
        top = scored[0]["score"]
        second = scored[1]["score"]
        if top > 0 and abs(top - second) / top <= AMBIGUITY_THRESHOLD:
            doc_ids = ",".join([scored[0]["doc"]["doc_id"], scored[1]["doc"]["doc_id"]])
            _ensure_conflict(
                conflict_type="canon_collision",
                doc_ids=doc_ids,
                term=topic or "",
                plane_path=plane_scope or "",
            )
            conflicts_created.append({
                "type": "canon_collision",
                "message": "Top two candidates within 5% ambiguity threshold.",
                "doc_ids": [scored[0]["doc"]["doc_id"], scored[1]["doc"]["doc_id"]],
            })

    winner = scored[0] if scored else None
    return {
        "winner": winner,
        "candidates": [
            {"doc_id": s["doc"]["doc_id"], "path": s["doc"]["path"], "score": s["score"]}
            for s in scored[:10]
        ],
        "ambiguity_conflicts": conflicts_created,
        "score_formula": {
            "status_canonical": "+100",
            "type_canon": "+50",
            "canon_folder": "+30",
            "version_rank": "+10 * semver_rank",
            "recency": "+0.000001 * updated_ts",
            "archived": "-40",
            "topic_boost": "+20 if normalized_topic in topics_tokens",
        },
    }


def _ensure_conflict(conflict_type: str, doc_ids: str, term: str, plane_path: str):
    existing = db.fetchone(
        "SELECT rowid FROM conflicts WHERE conflict_type=? AND doc_ids=? AND term=?",
        (conflict_type, doc_ids, term),
    )
    if not existing:
        db.execute(
            "INSERT INTO conflicts (conflict_type, doc_ids, term, plane_path, detected_ts) VALUES (?,?,?,?,?)",
            (conflict_type, doc_ids, term, plane_path, int(time.time())),
        )
