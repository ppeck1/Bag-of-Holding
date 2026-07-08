"""Read-only retrieval and chunking support for BOH.

This module deliberately stays local and deterministic. It stores stable
document chunks for FTS retrieval and computes a lightweight hashed embedding
so a neural embedding backend can be added later without changing the API shape.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from collections import Counter
from typing import Any

from fastapi import Header, HTTPException, status

from app.db import connection as db
from app.core import fold_metrics
from app.core import promoted_exposure
from app.core.canon import canon_score
from app.core import planar_authority, planar_gate
from app.core.plane_card import get_card_for_doc, list_cards, log_storage_event

RETRIEVAL_HEADER = "X-BOH-Retrieval-Token"
EMBEDDING_MODEL = "boh-local-hash-embedding-v1"
EMBEDDING_DIMS = 64
WORD_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_\-]{1,}")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")
LINK_RE = re.compile(r"\[[^\]]+\]\([^)]+\)|https?://\S+")
STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "about",
    "your", "you", "are", "was", "were", "will", "would", "should", "could",
    "can", "not", "but", "or", "of", "to", "in", "on", "as", "is", "it",
}


def retrieval_status() -> dict:
    return {
        "configured": bool(os.environ.get("BOH_RETRIEVAL_TOKEN", "").strip()),
        "header_name": RETRIEVAL_HEADER,
        "read_only": True,
        "operator_token_required": False,
        "protected_routes_fail_closed": True,
    }


def require_retrieval_token(
    x_boh_retrieval_token: str | None = Header(default=None, alias=RETRIEVAL_HEADER),
) -> str:
    expected = os.environ.get("BOH_RETRIEVAL_TOKEN", "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="retrieval token is not configured; set BOH_RETRIEVAL_TOKEN before launch",
        )
    if not x_boh_retrieval_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"missing {RETRIEVAL_HEADER}",
        )
    if x_boh_retrieval_token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid retrieval token",
        )
    return "retrieval_connector"


def _terms(text: str) -> list[str]:
    return [t.lower() for t in WORD_RE.findall(text or "") if t.lower() not in STOPWORDS]


def _term_counter(text: str) -> Counter:
    return Counter(_terms(text))


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[k] * b[k] for k in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)


def _hash_embedding(text: str, dims: int = EMBEDDING_DIMS) -> list[float]:
    """Create a stable local embedding using signed feature hashing."""
    vec = [0.0] * dims
    for term, count in _term_counter(text).items():
        digest = hashlib.sha256(term.encode("utf-8", errors="replace")).digest()
        idx = int.from_bytes(digest[:4], "big") % dims
        sign = -1.0 if digest[4] & 1 else 1.0
        vec[idx] += sign * (1.0 + math.log(count))
    norm = math.sqrt(sum(v * v for v in vec))
    if not norm:
        return vec
    return [round(v / norm, 6) for v in vec]


def _vector_cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def _chunk_id(doc_id: str, text_hash: str, index: int, heading: str, text: str) -> str:
    seed = f"{doc_id}\n{text_hash}\n{index}\n{heading}\n{text[:80]}"
    return "chunk-" + hashlib.sha256(seed.encode("utf-8", errors="replace")).hexdigest()[:24]


def _line_type(line: str) -> str:
    if HEADING_RE.match(line):
        return "heading"
    if TABLE_RE.match(line):
        return "table"
    if LINK_RE.search(line):
        return "link"
    return "body"


def _token_offset(text: str, byte_pos: int) -> int:
    prefix = text.encode("utf-8")[:byte_pos].decode("utf-8", errors="ignore")
    return len(_terms(prefix))


def build_chunks(doc: dict, body: str, frontmatter_text: str = "",
                 max_chars: int = 1400) -> list[dict]:
    """Build stable chunks with heading paths and source offsets.

    Byte and token offsets are tracked incrementally (O(n) total) rather than
    recomputed per chunk (was O(n*k) — catastrophic for large files).
    """
    doc_id = doc.get("doc_id") or ""
    text_hash = doc.get("text_hash") or hashlib.sha256(body.encode("utf-8", errors="replace")).hexdigest()
    source_hash = doc.get("source_hash") or text_hash
    chunks: list[dict] = []
    created_ts = int(time.time())
    index = 0

    def add_chunk(text: str, heading_path: str, chunk_type: str,
                  byte_start: int, byte_end: int,
                  token_start: int, token_end: int):
        nonlocal index
        clean = text.strip()
        if not clean:
            return
        item = {
            "chunk_id": _chunk_id(doc_id, text_hash, index, heading_path, clean),
            "doc_id": doc_id,
            "path": doc.get("path") or "",
            "chunk_index": index,
            "heading_path": heading_path,
            "byte_start": byte_start,
            "byte_end": byte_end,
            "token_start": token_start,
            "token_end": token_end,
            "source_hash": source_hash,
            "text_hash": text_hash,
            "chunk_type": chunk_type,
            "text": clean,
            "lifecycle_state": doc.get("operator_state"),
            "authority_state": doc.get("authority_state"),
            "status": doc.get("status"),
            "canonical_layer": doc.get("canonical_layer"),
            "metadata_json": json.dumps({"source": "indexer", "retrieval_version": 1}),
            "created_ts": created_ts,
        }
        chunks.append(item)
        index += 1

    if frontmatter_text:
        add_chunk(frontmatter_text, "frontmatter", "frontmatter", 0, 0, 0, 0)

    heading_stack: list[str] = []
    buf: list[str] = []
    buf_byte_start = 0
    buf_token_start = 0
    buf_type = "body"
    byte_cursor = 0
    token_cursor = 0

    def flush(byte_end: int, token_end: int):
        nonlocal buf, buf_byte_start, buf_token_start, buf_type
        if buf:
            add_chunk("\n".join(buf), " > ".join(heading_stack), buf_type,
                      buf_byte_start, byte_end, buf_token_start, token_end)
            buf = []
            buf_type = "body"

    for raw_line in body.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        line_byte_start = byte_cursor
        line_token_start = token_cursor
        byte_cursor += len(raw_line.encode("utf-8"))
        token_cursor += len(_terms(line))
        m = HEADING_RE.match(line)
        if m:
            flush(line_byte_start, line_token_start)
            level = len(m.group(1))
            heading = m.group(2).strip()
            heading_stack = heading_stack[:level - 1] + [heading]
            add_chunk(line, " > ".join(heading_stack), "heading",
                      line_byte_start, byte_cursor, line_token_start, token_cursor)
            continue
        typ = _line_type(line)
        if not buf:
            buf_byte_start = line_byte_start
            buf_token_start = line_token_start
            buf_type = typ
        if typ != buf_type or sum(len(x) + 1 for x in buf) + len(line) > max_chars:
            flush(line_byte_start, line_token_start)
            buf_byte_start = line_byte_start
            buf_token_start = line_token_start
            buf_type = typ
        buf.append(line)

    flush(byte_cursor, token_cursor)
    return chunks


def replace_doc_chunks(conn, doc: dict, body: str, frontmatter_text: str = "") -> list[dict]:
    chunks = build_chunks(doc, body, frontmatter_text=frontmatter_text)
    doc_id = doc.get("doc_id")
    old_embeddings = conn.execute("SELECT chunk_id FROM doc_chunks WHERE doc_id = ?", (doc_id,)).fetchall()
    for row in old_embeddings:
        conn.execute("DELETE FROM doc_chunk_embeddings WHERE chunk_id = ?", (row["chunk_id"],))
    conn.execute("DELETE FROM doc_chunks WHERE doc_id = ?", (doc_id,))
    conn.execute("DELETE FROM doc_chunks_fts WHERE doc_id = ?", (doc_id,))
    for c in chunks:
        conn.execute(
            """INSERT INTO doc_chunks
               (chunk_id, doc_id, path, chunk_index, heading_path, byte_start, byte_end,
                token_start, token_end, source_hash, text_hash, chunk_type, text,
                lifecycle_state, authority_state, status, canonical_layer, metadata_json, created_ts)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                c["chunk_id"], c["doc_id"], c["path"], c["chunk_index"], c["heading_path"],
                c["byte_start"], c["byte_end"], c["token_start"], c["token_end"],
                c["source_hash"], c["text_hash"], c["chunk_type"], c["text"],
                c["lifecycle_state"], c["authority_state"], c["status"], c["canonical_layer"],
                c["metadata_json"], c["created_ts"],
            ),
        )
        conn.execute(
            "INSERT INTO doc_chunks_fts(chunk_id, doc_id, heading_path, content) VALUES (?,?,?,?)",
            (c["chunk_id"], c["doc_id"], c["heading_path"], c["text"]),
        )
        conn.execute(
            """INSERT OR REPLACE INTO doc_chunk_embeddings
               (chunk_id, embedding_model, dimensions, vector_json, text_hash, created_ts)
               VALUES (?,?,?,?,?,?)""",
            (
                c["chunk_id"],
                EMBEDDING_MODEL,
                EMBEDDING_DIMS,
                json.dumps(_hash_embedding(c["heading_path"] + "\n" + c["text"])),
                c["text_hash"],
                c["created_ts"],
            ),
        )
    return chunks


def _metadata_where(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    clauses = []
    params: list[Any] = []
    for key in ("doc_id", "status", "authority_state", "canonical_layer", "chunk_type"):
        val = filters.get(key)
        if val:
            clauses.append(f"c.{key} = ?")
            params.append(val)
    project = filters.get("project")
    if project:
        clauses.append("d.project = ?")
        params.append(project)
    return (" AND " + " AND ".join(clauses)) if clauses else "", params


def _conflicts_for(doc_id: str) -> list[dict]:
    rows = db.fetchall(
        "SELECT rowid, * FROM conflicts WHERE doc_ids LIKE ? ORDER BY detected_ts DESC LIMIT 10",
        (f"%{doc_id}%",),
    )
    matched = []
    for r in rows:
        if doc_id not in (r.get("doc_ids") or "").split(","):
            continue
        c = dict(r)
        # NULL/0 means open — same predicate the fold resolver uses for unresolved conflicts.
        c["resolution_status"] = "acknowledged" if c.get("acknowledged") else "open"
        matched.append(c)
    return matched


def _lineage_for(doc_id: str) -> list[dict]:
    rows = db.fetchall(
        "SELECT * FROM lineage WHERE doc_id = ? OR related_doc_id = ? ORDER BY detected_ts DESC LIMIT 10",
        (doc_id, doc_id),
    )
    return [dict(r) for r in rows]


def _related_doc_ids(doc_id: str) -> list[str]:
    related = []
    for row in _lineage_for(doc_id):
        if row.get("doc_id") == doc_id and row.get("related_doc_id"):
            related.append(row["related_doc_id"])
        elif row.get("related_doc_id") == doc_id and row.get("doc_id"):
            related.append(row["doc_id"])
    return list(dict.fromkeys(related))


def _provenance_for(doc: dict) -> dict:
    provenance = {}
    try:
        provenance = json.loads(doc.get("provenance_json") or "{}")
    except Exception:
        provenance = {"raw": doc.get("provenance_json") or ""}
    artifacts = db.fetchall(
        "SELECT artifact_id, approval_id, approved_by, approved_at, action_type FROM provenance_artifacts "
        "WHERE document_id = ? ORDER BY approved_at DESC LIMIT 5",
        (doc.get("doc_id"),),
    )
    return {"frontmatter": provenance, "artifacts": [dict(a) for a in artifacts]}


def _review_state_for(doc_id: str) -> dict:
    last = db.fetchall(
        "SELECT action_type, from_state, to_state, approved_by, approved_at "
        "FROM provenance_artifacts WHERE document_id = ? "
        "ORDER BY approved_at DESC LIMIT 1",
        (doc_id,),
    )
    count_rows = db.fetchall(
        "SELECT COUNT(*) AS n FROM provenance_artifacts WHERE document_id = ?",
        (doc_id,),
    )
    return {
        "last_review": dict(last[0]) if last else None,
        "review_count": int(count_rows[0]["n"]) if count_rows else 0,
    }


def _freshness_for(item: dict) -> dict:
    # Column priority and parsing must match the fold resolver exactly so
    # retrieval freshness and fold freshness cannot drift.
    age_days = None
    source = None
    for column in ("epistemic_last_evaluated", "updated_ts"):
        days = fold_metrics._parse_freshness_days(item.get(column), column)
        if days is not None:
            age_days, source = days, column
            break
    superseding = db.fetchall(
        "SELECT related_doc_id FROM lineage WHERE doc_id = ? "
        "AND relationship IN ('superseded_by', 'superseded') "
        "ORDER BY detected_ts DESC LIMIT 1",
        (item.get("doc_id"),),
    )
    return {
        "age_days": age_days,
        "source": source,
        "valid_until": item.get("epistemic_valid_until"),
        "superseded": bool(superseding),
        "superseded_by": superseding[0]["related_doc_id"] if superseding else None,
    }


def _intake_provenance_for(doc_id: str) -> dict | None:
    """WO-2 evidence chain: the promotion-ledger back-link for a promoted doc (else None)."""
    try:
        rows = db.fetchall(
            "SELECT p.promotion_id, p.source_revision_id, p.intake_capability_id, p.handoff_id, "
            "p.normalized_artifact_id, p.normalized_hash, p.normalized_output_type, "
            "p.normalized_output_profile, p.adapter_id, p.adapter_version, "
            "p.adapter_registry_version, p.policy_snapshot_hash, p.promoted_by, p.promoted_at, "
            "h.intake_run_id "
            "FROM intake_promotions p "
            "LEFT JOIN intake_handoffs h ON h.handoff_id = p.handoff_id "
            "WHERE p.doc_id = ? AND p.status = 'active' LIMIT 1",
            (doc_id,),
        )
    except Exception:
        return None
    return dict(rows[0]) if rows else None


def _authority_weight(doc: dict) -> float:
    status = doc.get("status") or ""
    authority = doc.get("authority_state") or ""
    layer = doc.get("canonical_layer") or ""
    weight = 0.0
    if status == "canonical":
        weight += 0.20
    if authority in {"approved", "trusted", "canonical"}:
        weight += 0.15
    if layer == "canonical":
        weight += 0.10
    if authority in {"quarantined", "draft"}:
        weight -= 0.08
    return max(-0.15, min(0.35, weight))


def _snippet(text: str, query_terms: list[str], max_chars: int = 420) -> str:
    if len(text) <= max_chars:
        return text
    lower = text.lower()
    hit = min([lower.find(t) for t in query_terms if lower.find(t) >= 0] or [0])
    start = max(0, hit - max_chars // 3)
    end = min(len(text), start + max_chars)
    prefix = "..." if start else ""
    suffix = "..." if end < len(text) else ""
    return prefix + text[start:end].strip() + suffix


def _embedding_from_row(item: dict) -> list[float]:
    raw = item.get("embedding_vector_json")
    if raw:
        try:
            vec = json.loads(raw)
            if isinstance(vec, list):
                return [float(v) for v in vec]
        except Exception:
            pass
    return _hash_embedding((item.get("heading_path") or "") + "\n" + (item.get("text") or ""))


def _retrieval_metadata() -> dict:
    return {
        "mode": "hybrid_v1",
        "components": [
            "fts5_bm25",
            "local_hash_embedding",
            "local_lexical_semantic",
            "canon_authority",
            "lineage",
            "conflict_penalty",
            "bounded_context",
        ],
        "semantic_backend": EMBEDDING_MODEL,
        "embedding_backend": EMBEDDING_MODEL,
        "embedding_dimensions": EMBEDDING_DIMS,
        "read_only": True,
    }


def _card_pack(card, query: str, mode: str, score: float = 0.25) -> dict:
    c = card.to_dict() if hasattr(card, "to_dict") else dict(card)
    payload = c.get("payload") or {}
    context_ref = c.get("context_ref") or {}
    text = payload.get("text") or payload.get("summary") or payload.get("title") or c.get("topic") or ""
    decision = planar_authority.can_use("retrieval_connector", c, "answer_context", mode)
    warnings = []
    if c.get("plane", "").lower() == "subjective":
        warnings.append("subjective_card")
    if payload.get("non_authoritative"):
        warnings.append("do_not_treat_as_canonical")
    if not decision.allowed:
        warnings.append(f"blocked:{decision.reason}")
    return {
        "chunk_id": None,
        "card_id": c.get("id"),
        "doc_id": c.get("doc_id"),
        "title": payload.get("title") or c.get("topic"),
        "path": payload.get("path") or context_ref.get("path") or "",
        "snippet": _snippet(text, _terms(query)),
        "text": text,
        "source_span": None,
        "heading_path": "",
        "chunk_type": "plane_card",
        "plane": c.get("plane"),
        "card_type": c.get("card_type"),
        "lifecycle_state": None,
        "authority_state": (c.get("authority") or {}).get("state"),
        "status": payload.get("status"),
        "canonical_layer": payload.get("canonical_layer"),
        "provenance": {"context_ref": context_ref, "plane_card": c.get("id")},
        "review_state": None,
        "freshness": None,
        "intake_provenance": None,
        "conflicts": [],
        "lineage": [],
        "citation": {
            "card_id": c.get("id"),
            "doc_id": c.get("doc_id"),
            "path": payload.get("path") or context_ref.get("path") or "",
            "title": payload.get("title") or c.get("topic") or "",
            "source_hash": "",
        },
        "warnings": warnings,
        "eligibility": decision.to_dict(),
        "do_not_treat_as_canonical": payload.get("non_authoritative") is True or c.get("plane", "").lower() != "canonical",
        "score": score,
        "why_selected": {
            "retrieval_source": "plane_card",
            "mode": mode,
            "card_topic_match": query.lower() in (c.get("topic") or "").lower(),
        },
    }


def _card_matches_filters(card: dict, filters: dict[str, Any] | None) -> bool:
    payload = card.get("payload") or {}
    authority = card.get("authority") or {}
    values = {
        "doc_id": card.get("doc_id"),
        "status": payload.get("status"),
        "authority_state": payload.get("authority_state") or authority.get("state"),
        "canonical_layer": payload.get("canonical_layer"),
        "project": payload.get("project"),
        "chunk_type": "plane_card",
    }
    return all(values.get(k) == v for k, v in (filters or {}).items())


def _matching_card_packs(query: str, mode: str, limit: int,
                         filters: dict[str, Any] | None = None) -> list[dict]:
    q_terms = set(_terms(query))
    if not q_terms:
        return []
    packs = []
    cards = list_cards(limit=max(limit * 4, 25))
    for card in cards:
        c = card.to_dict()
        if not _card_matches_filters(c, filters):
            continue
        payload = c.get("payload") or {}
        haystack = " ".join([
            c.get("topic") or "",
            c.get("plane") or "",
            c.get("card_type") or "",
            str(payload.get("title") or ""),
            str(payload.get("summary") or ""),
            str(payload.get("text") or ""),
        ])
        overlap = q_terms & set(_terms(haystack))
        if not overlap:
            continue
        score = 0.20 + min(0.40, len(overlap) / max(len(q_terms), 1))
        packs.append(_card_pack(card, query, mode, score=round(score, 6)))
    packs.sort(key=lambda p: p["score"], reverse=True)
    return packs[:limit]


def _attach_card_authority(packs: list[dict], mode: str) -> list[dict]:
    out = []
    for pack in packs:
        if pack.get("card_id"):
            out.append(pack)
            continue
        card = get_card_for_doc(pack.get("doc_id"), auto_wrap=False) if pack.get("doc_id") else None
        if card:
            c = card.to_dict()
            decision = planar_authority.can_use("retrieval_connector", c, "answer_context", mode)
            pack["card_id"] = c.get("id")
            pack["plane"] = c.get("plane")
            pack["card_type"] = c.get("card_type")
            pack["eligibility"] = decision.to_dict()
            if not decision.allowed:
                pack.setdefault("warnings", []).append(f"blocked:{decision.reason}")
        else:
            decision = planar_authority.can_use("retrieval_connector", {}, "answer_context", mode)
            pack["eligibility"] = decision.to_dict()
        out.append(pack)
    return out


def _audit_objects(packs: list[dict]) -> dict:
    card_ids = [p.get("card_id") for p in packs if p.get("card_id")]
    doc_ids = [p.get("doc_id") for p in packs if p.get("doc_id")]
    events = []
    for card_id in card_ids[:10]:
        events.extend(db.fetchall("SELECT * FROM storage_events WHERE card_id = ? ORDER BY created_ts DESC LIMIT 10", (card_id,)))
    for doc_id in doc_ids[:10]:
        events.extend(db.fetchall("SELECT * FROM storage_events WHERE doc_id = ? ORDER BY created_ts DESC LIMIT 10", (doc_id,)))
    certificates = []
    for card_id in card_ids[:10]:
        certificates.extend(db.fetchall("SELECT * FROM certificates WHERE node_id = ? ORDER BY created_at DESC LIMIT 5", (card_id,)))
    interfaces = []
    for card_id in card_ids[:10]:
        interfaces.extend(db.fetchall("SELECT * FROM plane_interfaces WHERE node_id = ? ORDER BY created_at DESC LIMIT 5", (card_id,)))
    return {
        "storage_events": events[:30],
        "certificates": certificates[:20],
        "plane_interfaces": interfaces[:20],
    }


def retrieve_governed(query: str, mode: str = "strict_answer", limit: int = 8,
                      include_lineage: bool = True, filters: dict[str, Any] | None = None,
                      max_context_chars: int = 6000,
                      include_promoted: bool = False) -> dict:
    """Wrap retrieval with Planar Storage mode eligibility."""
    mode_key = (mode or "strict_answer").lower().replace(" ", "_").replace("-", "_")
    if mode_key not in {"strict_answer", "exploration", "audit_provenance", "canon_review", "low_b_worker_context"}:
        raise ValueError(f"unknown retrieval mode: {mode!r}")

    base = retrieve(
        query,
        limit=limit,
        include_lineage=include_lineage,
        filters=filters,
        max_context_chars=max_context_chars,
        # Dual gate (DEC-0004): server env AND request flag must both be open.
        show_promoted=promoted_exposure.visible(include_promoted),
    )
    packs = _attach_card_authority(base.get("context_packs", []), mode_key)
    existing_cards = {p.get("card_id") for p in packs}
    for pack in _matching_card_packs(query, mode_key, limit, filters=filters):
        if pack.get("card_id") not in existing_cards:
            packs.append(pack)
            existing_cards.add(pack.get("card_id"))

    included = []
    excluded = []
    for pack in packs:
        decision = pack.get("eligibility") or {"allowed": True}
        if decision.get("allowed"):
            included.append(pack)
        else:
            excluded.append({
                "card_id": pack.get("card_id"),
                "doc_id": pack.get("doc_id"),
                "title": pack.get("title"),
                "plane": pack.get("plane"),
                "reason": decision.get("reason"),
                "required_action": decision.get("required_action"),
                "visible_message": decision.get("visible_message"),
            })

    if mode_key == "canon_review":
        included.sort(key=lambda p: (p.get("plane") != "canonical", -float(p.get("score") or 0)))
    elif mode_key == "audit_provenance":
        included.sort(key=lambda p: (not p.get("provenance"), -float(p.get("score") or 0)))
    else:
        included.sort(key=lambda p: float(p.get("score") or 0), reverse=True)
    included = included[:limit]

    audit = _audit_objects(included) if mode_key == "audit_provenance" else {}
    log_storage_event(
        "retrieval_performed",
        subject_type="retrieval",
        subject_id=hashlib.sha256(f"{mode_key}:{query}".encode("utf-8", errors="replace")).hexdigest()[:24],
        actor_id="retrieval_connector",
        detail={
            "query": query,
            "mode": mode_key,
            "included": len(included),
            "excluded": len(excluded),
            "filters": filters or {},
        },
    )

    meta = base.get("retrieval", {})
    meta["context_chars"] = sum(len(p.get("text") or "") for p in included)
    meta["returned_count"] = len(included)
    meta["planar_mode"] = mode_key
    meta["eligibility_filtered"] = True
    meta["excluded_count"] = len(excluded)
    meta["mode_notes"] = {
        "strict_answer": "Excludes subjective, expired, blocked, low-confidence, and non-authoritative cards.",
        "exploration": "Includes weaker material but labels eligibility and canonicality warnings.",
        "audit_provenance": "Prioritizes trace/provenance objects and returns audit context.",
        "canon_review": "Ranks canonical/authority material first while preserving warnings.",
        "low_b_worker_context": "Allows broad context for worker tasks; callers must preserve warnings.",
    }.get(mode_key)
    context_pack, gate_result = planar_gate.evaluate_context_pack(
        query=query,
        operation="answer_context",
        actor={"actor_type": "system", "actor_id": "retrieval_connector", "role": "retrieval_connector"},
        mode=mode_key,
        candidate_packs=included,
        governance_health={},
    )
    gate_result["withheld_context_refs"] = list(dict.fromkeys(
        gate_result.get("withheld_context_refs", [])
        + [e.get("card_id") or e.get("doc_id") for e in excluded if e.get("card_id") or e.get("doc_id")]
    ))

    for pack in included:
        doc_id = pack.get("doc_id")
        chunk_id = pack.get("chunk_id")
        pack["citation_uri"] = f"boh://{doc_id}#{chunk_id}" if doc_id and chunk_id else None
        span = pack.get("source_span")
        pack["source_spans"] = [span] if isinstance(span, dict) else []

    top_warnings: list[str] = []

    def _add_warning(value: Any) -> None:
        if isinstance(value, str) and value and value not in top_warnings:
            top_warnings.append(value)

    for reason in gate_result.get("blocking_reasons", []) or []:
        _add_warning(reason)
    for reason in gate_result.get("warning_reasons", []) or []:
        _add_warning(reason)
    for pack in included:
        for warning in pack.get("warnings", []) or []:
            _add_warning(warning)
    for entry in excluded:
        _add_warning(entry.get("reason"))

    return {
        "query": query,
        "count": len(included),
        "context_packs": included,
        "excluded_summary": excluded,
        "audit_context": audit,
        "retrieval": meta,
        "planar_context_pack": context_pack,
        "gate_result": gate_result,
        "warnings": top_warnings,
    }


def retrieve(query: str, limit: int = 8, include_lineage: bool = True,
             filters: dict[str, Any] | None = None,
             max_context_chars: int = 6000,
             show_promoted: bool = False) -> dict:
    filters = filters or {}
    q_terms = _terms(query)
    q_vec = _term_counter(query)
    where, params = _metadata_where(filters)
    promo = promoted_exposure.exclusion_sql("d", show_promoted=show_promoted)
    # Each term is quoted as an FTS5 string literal: identical semantics for plain words, and
    # operator characters inside tokens ('-', ':') can no longer raise an FTS syntax error —
    # a hyphenated token matches as the phrase of its tokenizer sub-tokens
    # (boh_retrieval_fts_query_hyphen_hardening_v0_1).
    fts_query = " OR ".join(f'"{t}"' for t in q_terms[:12])
    rows = []
    if fts_query:
        rows = db.fetchall(
            f"""
            SELECT c.*, d.title, d.summary, d.type, d.project, d.document_class,
                   d.operator_state, d.operator_intent, d.provenance_json,
                   d.source_type, d.topics_tokens, d.updated_ts, d.corpus_class,
                   d.epistemic_last_evaluated, d.epistemic_valid_until,
                   e.vector_json AS embedding_vector_json,
                   bm25(doc_chunks_fts) AS bm25_score
            FROM doc_chunks_fts
            JOIN doc_chunks c ON c.chunk_id = doc_chunks_fts.chunk_id
            JOIN docs d ON d.doc_id = c.doc_id
            LEFT JOIN doc_chunk_embeddings e ON e.chunk_id = c.chunk_id
            WHERE doc_chunks_fts MATCH ? {where}{promo}
            ORDER BY bm25(doc_chunks_fts)
            LIMIT ?
            """,
            (fts_query, *params, max(limit * 4, 20)),
        )
        rows = [dict(r) | {"retrieval_source": "fts"} for r in rows]
    if not rows:
        fallback_rows = db.fetchall(
            f"""
            SELECT c.*, d.title, d.summary, d.type, d.project, d.document_class,
                   d.operator_state, d.operator_intent, d.provenance_json,
                   d.source_type, d.topics_tokens, d.updated_ts, d.corpus_class,
                   d.epistemic_last_evaluated, d.epistemic_valid_until,
                   e.vector_json AS embedding_vector_json,
                   0.0 AS bm25_score
            FROM doc_chunks c
            JOIN docs d ON d.doc_id = c.doc_id
            LEFT JOIN doc_chunk_embeddings e ON e.chunk_id = c.chunk_id
            WHERE 1 = 1 {where}{promo}
            LIMIT ?
            """,
            (*params, max(limit * 8, 40)),
        )
        rows = [
            dict(r) | {"retrieval_source": "lexical_fallback"} for r in fallback_rows
            if _cosine(q_vec, _term_counter(r["text"] + " " + (r["heading_path"] or ""))) > 0
        ]
    if not rows:
        return {
            "query": query,
            "count": 0,
            "context_packs": [],
            "retrieval": _retrieval_metadata(),
        }

    if include_lineage:
        seen_chunk_ids = {r["chunk_id"] for r in rows}
        seed_doc_ids = list(dict.fromkeys(r["doc_id"] for r in rows[:max(limit, 3)]))
        for doc_id in seed_doc_ids:
            for related_doc_id in _related_doc_ids(doc_id)[:3]:
                related_rows = db.fetchall(
                    f"""
                    SELECT c.*, d.title, d.summary, d.type, d.project, d.document_class,
                           d.operator_state, d.operator_intent, d.provenance_json,
                           d.source_type, d.topics_tokens, d.updated_ts, d.corpus_class,
                   d.epistemic_last_evaluated, d.epistemic_valid_until,
                           e.vector_json AS embedding_vector_json,
                           0.0 AS bm25_score
                    FROM doc_chunks c
                    JOIN docs d ON d.doc_id = c.doc_id
                    LEFT JOIN doc_chunk_embeddings e ON e.chunk_id = c.chunk_id
                    WHERE c.doc_id = ? {where}{promo}
                    ORDER BY c.chunk_index
                    LIMIT 2
                    """,
                    (related_doc_id, *params),
                )
                for row in related_rows:
                    item = dict(row)
                    if item["chunk_id"] in seen_chunk_ids:
                        continue
                    seen_chunk_ids.add(item["chunk_id"])
                    item["retrieval_source"] = f"lineage_expansion:{doc_id}"
                    rows.append(item)

    q_embedding = _hash_embedding(query)
    bm25_vals = [r["bm25_score"] for r in rows]
    min_b = min(bm25_vals)
    max_b = max(bm25_vals)
    span = max_b - min_b if max_b != min_b else 1.0

    packs = []
    seen = set()
    for row in rows:
        item = dict(row)
        if item["chunk_id"] in seen:
            continue
        seen.add(item["chunk_id"])
        text_score = 1.0 - ((item["bm25_score"] - min_b) / span)
        lexical_score = _cosine(q_vec, _term_counter(item["text"]))
        embedding_score = max(0.0, _vector_cosine(q_embedding, _embedding_from_row(item)))
        semantic_score = (0.65 * embedding_score) + (0.35 * lexical_score)
        doc_auth = _authority_weight(item)
        cscore = max(0.0, min(1.0, canon_score(item) / 180.0))
        lineages = _lineage_for(item["doc_id"]) if include_lineage else []
        lineage_bonus = 0.05 if lineages else 0.0
        if str(item.get("retrieval_source") or "").startswith("lineage_expansion"):
            lineage_bonus += 0.03
        conflicts = _conflicts_for(item["doc_id"])
        conflict_penalty = -0.12 if conflicts else 0.0
        final = (
            0.45 * text_score
            + 0.25 * semantic_score
            + 0.15 * cscore
            + doc_auth
            + lineage_bonus
            + conflict_penalty
        )
        do_not_treat_as_canonical = not (
            item.get("status") == "canonical"
            or item.get("authority_state") in {"approved", "trusted", "canonical"}
        )
        packs.append({
            "chunk_id": item["chunk_id"],
            "doc_id": item["doc_id"],
            "title": item.get("title") or item.get("path"),
            "path": item["path"],
            "snippet": _snippet(item["text"], q_terms),
            "text": item["text"],
            "source_span": {
                "byte_start": item["byte_start"],
                "byte_end": item["byte_end"],
                "token_start": item["token_start"],
                "token_end": item["token_end"],
            },
            "heading_path": item.get("heading_path") or "",
            "chunk_type": item["chunk_type"],
            "lifecycle_state": item.get("lifecycle_state") or item.get("operator_state"),
            "authority_state": item.get("authority_state"),
            "status": item.get("status"),
            "canonical_layer": item.get("canonical_layer"),
            "provenance": _provenance_for(item),
            "review_state": _review_state_for(item["doc_id"]),
            "freshness": _freshness_for(item),
            "intake_provenance": (
                _intake_provenance_for(item["doc_id"])
                if item.get("corpus_class") == promoted_exposure.PROMOTED_CORPUS_CLASS
                else None),
            "conflicts": conflicts,
            "lineage": lineages,
            "citation": {
                "doc_id": item["doc_id"],
                "path": item["path"],
                "title": item.get("title") or "",
                "heading_path": item.get("heading_path") or "",
                "source_hash": item.get("source_hash") or item.get("text_hash") or "",
                "chunk_id": item["chunk_id"],
            },
            "warnings": [
                "do_not_treat_as_canonical" if do_not_treat_as_canonical else "",
                "open_conflicts_present" if conflicts else "",
            ],
            "do_not_treat_as_canonical": do_not_treat_as_canonical,
            "score": round(final, 6),
            "why_selected": {
                "retrieval_source": item.get("retrieval_source") or "unknown",
                "text_score": round(text_score, 4),
                "semantic_score": round(semantic_score, 4),
                "embedding_score": round(embedding_score, 4),
                "lexical_score": round(lexical_score, 4),
                "canon_score": round(cscore, 4),
                "authority_weight": round(doc_auth, 4),
                "lineage_bonus": round(lineage_bonus, 4),
                "conflict_penalty": round(conflict_penalty, 4),
            },
        })

    packs.sort(key=lambda p: p["score"], reverse=True)
    bounded = []
    used_chars = 0
    for p in packs:
        if len(bounded) >= limit:
            break
        next_chars = len(p["text"])
        if bounded and used_chars + next_chars > max_context_chars:
            break
        bounded.append(p)
        used_chars += next_chars
    packs = bounded
    for p in packs:
        p["warnings"] = [w for w in p["warnings"] if w]
    meta = _retrieval_metadata()
    meta["max_context_chars"] = max_context_chars
    meta["context_chars"] = sum(len(p["text"]) for p in packs)
    return {
        "query": query,
        "count": len(packs),
        "context_packs": packs,
        "retrieval": meta,
    }
