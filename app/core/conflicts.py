"""app/core/conflicts.py: Conflict detection for Bag of Holding v2.

Moved from conflicts.py (v0P). Logic unchanged.
Patch v1.1: B2 canon collision requires topic+scope, C1 planar 24h window fix.

Ontology label: BOH_PATCH_v2.19
No auto-resolution. Conflicts are append-only. See docs/corpus_migration_doctrine.md §6.
"""

import json
import time

from app.db import connection as db
from app.services.indexer import normalize_topic_token


def detect_all_conflicts() -> list[dict]:
    """Run all conflict detection passes. Return list of new conflicts detected.

    Three passes:
    1. Definition conflicts (same term + scope, different hash)
    2. Canon collisions (two canonical docs sharing topic + scope)
    3. Planar conflicts (same plane_path, conflicting d within 24h)

    No auto-resolution occurs here or anywhere. See math_authority.md §8, §9, §6.
    """
    found = []
    found.extend(_detect_definition_conflicts())
    found.extend(_detect_canon_collisions())
    found.extend(_detect_planar_conflicts())
    return found


def _detect_definition_conflicts() -> list[dict]:
    """Same term + same plane_scope_json + different block_hash → definition_conflict."""
    conflicts = []
    rows = db.fetchall(
        """
        SELECT term, plane_scope_json, GROUP_CONCAT(doc_id) as doc_ids,
               COUNT(DISTINCT block_hash) as hash_count
        FROM defs
        GROUP BY term, plane_scope_json
        HAVING hash_count > 1
        """
    )
    for row in rows:
        _upsert_conflict(
            conflict_type="definition_conflict",
            doc_ids=row["doc_ids"],
            term=row["term"],
            plane_path=row["plane_scope_json"] or "",
        )
        conflicts.append({
            "conflict_type": "definition_conflict",
            "term": row["term"],
            "plane_scope": row["plane_scope_json"],
            "doc_ids": row["doc_ids"],
        })
    return conflicts


def _detect_canon_collisions() -> list[dict]:
    """B2: Two canonical docs collide if they share at least one normalized topic token
    AND their plane_scope overlap (exact string match).
    If both plane_scopes are empty, treat as global → collision allowed if topics overlap.
    """
    conflicts = []
    canonical_docs = db.fetchall(
        "SELECT doc_id, path, plane_scope_json, topics_tokens FROM docs WHERE status='canonical'"
    )

    for i, doc_a in enumerate(canonical_docs):
        for doc_b in canonical_docs[i + 1:]:
            tokens_a = set((doc_a.get("topics_tokens") or "").split())
            tokens_b = set((doc_b.get("topics_tokens") or "").split())
            shared_tokens = tokens_a & tokens_b

            if not shared_tokens:
                continue  # B2: no shared topic → no collision

            scope_a = set(json.loads(doc_a.get("plane_scope_json") or "[]"))
            scope_b = set(json.loads(doc_b.get("plane_scope_json") or "[]"))

            both_empty = (not scope_a) and (not scope_b)
            scope_overlap = scope_a & scope_b

            if both_empty or scope_overlap:
                doc_ids = f"{doc_a['doc_id']},{doc_b['doc_id']}"
                shared_topic_str = " ".join(sorted(shared_tokens))
                plane_path = ",".join(sorted(scope_overlap)) if scope_overlap else "global"

                _upsert_conflict(
                    conflict_type="canon_collision",
                    doc_ids=doc_ids,
                    term=shared_topic_str,
                    plane_path=plane_path,
                )
                conflicts.append({
                    "conflict_type": "canon_collision",
                    "doc_ids": doc_ids,
                    "shared_topic_tokens": list(shared_tokens),
                    "overlapping_plane_scope": list(scope_overlap) if scope_overlap else ["global"],
                })

    return conflicts


def _detect_planar_conflicts() -> list[dict]:
    """C1: Same plane_path, facts within last 24h (ts >= cutoff), differing d,
    and (q + c) > 0.7 for conflicting facts.

    See math_authority.md §6 for thresholds.
    """
    conflicts = []
    now = int(time.time())
    cutoff = now - 86400  # C1: 24-hour window

    rows = db.fetchall(
        """
        SELECT plane_path,
               GROUP_CONCAT(subject_id) as subjects,
               GROUP_CONCAT(d) as ds,
               GROUP_CONCAT(q) as qs,
               GROUP_CONCAT(c) as cs
        FROM plane_facts
        WHERE ts >= ?
          AND (valid_until IS NULL OR valid_until > ?)
        GROUP BY plane_path
        HAVING COUNT(DISTINCT d) > 1
        """,
        (cutoff, now),
    )

    for row in rows:
        qs = [float(v) for v in (row["qs"] or "0").split(",")]
        cs = [float(v) for v in (row["cs"] or "0").split(",")]
        if any((q + c) > 0.7 for q, c in zip(qs, cs)):  # math_authority.md §6
            _upsert_conflict(
                conflict_type="planar_conflict",
                doc_ids=row["subjects"] or "",
                term="",
                plane_path=row["plane_path"],
            )
            conflicts.append({
                "conflict_type": "planar_conflict",
                "plane_path": row["plane_path"],
                "subjects": row["subjects"],
                "differing_d_values": row["ds"],
            })

    return conflicts


def _upsert_conflict(conflict_type: str, doc_ids: str, term: str, plane_path: str):
    """Insert conflict only if (conflict_type, doc_ids, term, plane_path) not already present.
    Conflicts are append-only — never deleted by detection. (corpus_migration_doctrine §6)
    """
    existing = db.fetchone(
        "SELECT rowid FROM conflicts WHERE conflict_type=? AND doc_ids=? AND term=? AND plane_path=?",
        (conflict_type, doc_ids, term, plane_path),
    )
    if not existing:
        db.execute(
            "INSERT INTO conflicts (conflict_type, doc_ids, term, plane_path, detected_ts) VALUES (?,?,?,?,?)",
            (conflict_type, doc_ids, term, plane_path, int(time.time())),
        )


def list_conflicts() -> list[dict]:
    """Return all conflicts ordered by detected_ts DESC."""
    return db.fetchall("SELECT rowid, * FROM conflicts ORDER BY detected_ts DESC")
