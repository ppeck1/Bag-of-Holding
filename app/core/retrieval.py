"""Read-only retrieval and chunking support for BOH.

This module deliberately stays local and deterministic. It stores stable
document chunks for FTS retrieval and computes a lightweight hashed embedding
so a neural embedding backend can be added later without changing the API shape.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import re
import time
import copy
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import Header, HTTPException, Request, status

from app.db import connection as db
from app.core import fold_metrics, source_lifecycle, exact_lookup
from app.core import promoted_exposure
from app.core import token_config
from app.core.canon import canon_score
from app.core import planar_authority, planar_gate
from app.core.plane_card import (
    PlaneCard,
    _row_to_card,
    get_card_for_doc,
    list_cards,
    log_storage_event,
)

RETRIEVAL_HEADER = "X-BOH-Retrieval-Token"
EMBEDDING_MODEL = "boh-local-hash-embedding-v1"
EMBEDDING_DIMS = 64
RETRIEVAL_AUTHORITY_COMPONENT_BUDGET = 0.15
GOVERNED_SELECTION_LIMIT = 25  # Existing public API/MCP maximum.
WORD_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_\-]{1,}")
STRONG_IDENTIFIER_RE = re.compile(
    r"(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+$"
)
# Query-only literals: do not change stored chunk tokens or hashed embeddings.
LITERAL_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+(?:[.-][A-Za-z0-9_]+)*")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")
LINK_RE = re.compile(r"\[[^\]]+\]\([^)]+\)|https?://\S+")
STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "about",
    "your", "you", "are", "was", "were", "will", "would", "should", "could",
    "can", "not", "but", "or", "of", "to", "in", "on", "as", "is", "it",
}


@dataclass(frozen=True)
class GovernedRetrievalResult(Mapping[str, Any]):
    """Normalized internal result with a backward-compatible wire projection."""

    query: str
    context_packs: list[dict]
    excluded_summary: list[dict]
    audit_context: dict
    retrieval: dict
    planar_context_pack: dict
    gate_result: dict
    warnings: list[str]
    context_conflicts: list[dict]

    @property
    def count(self) -> int:
        return len(self.context_packs)

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy({
            "query": self.query,
            "count": self.count,
            "context_packs": self.context_packs,
            "excluded_summary": self.excluded_summary,
            "audit_context": self.audit_context,
            "retrieval": self.retrieval,
            "planar_context_pack": self.planar_context_pack,
            "gate_result": self.gate_result,
            "warnings": self.warnings,
        })

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())


class _RetrievalReadSnapshot:
    """One deterministic SQLite read transaction for a retrieval request."""

    def __init__(self) -> None:
        self.conn = None

    def __enter__(self) -> "_RetrievalReadSnapshot":
        self.conn = db.get_conn()
        try:
            self.conn.execute("PRAGMA query_only=ON")
            self.conn.execute("BEGIN")
        except Exception:
            self.conn.close()
            self.conn = None
            raise
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self.conn is not None:
            connection = self.conn
            self.conn = None
            try:
                connection.rollback()
            finally:
                connection.close()

    def fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[dict]:
        if self.conn is None:
            raise RuntimeError("retrieval snapshot is not active")
        budget = getattr(self, 'exact_budget', None)
        if budget is not None:
            return exact_lookup.read(self.conn, query, params, budget)
        return [dict(row) for row in self.conn.execute(query, params).fetchall()]

    def fetchone(self, query: str, params: tuple[Any, ...] = ()) -> dict | None:
        if self.conn is None:
            raise RuntimeError("retrieval snapshot is not active")
        budget = getattr(self, 'exact_budget', None)
        if budget is not None:
            return exact_lookup.read(self.conn, query, params, budget, one=True)
        row = self.conn.execute(query, params).fetchone()
        return dict(row) if row else None


def _in_marks(values: list[Any]) -> str:
    return ",".join("?" for _ in values)


def retrieval_status() -> dict:
    state = token_config.get_state("retrieval")
    return {
        "configured": state.configured,
        "header_name": RETRIEVAL_HEADER,
        "read_only": True,
        "operator_token_required": False,
        "protected_routes_fail_closed": True,
        "source": state.source,
        "record_valid": state.record_valid,
        "managed_by_environment": state.managed_by_environment,
        "restart_required": state.restart_required,
    }


def _is_loopback_peer(host: str | None) -> bool:
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.casefold() == "localhost"


def require_retrieval_token(
    request: Request,
    x_boh_retrieval_token: str | None = Header(default=None, alias=RETRIEVAL_HEADER),
) -> str:
    state = token_config.get_state("retrieval")
    if not state.configured:
        if request.client and _is_loopback_peer(request.client.host):
            return "local_dev_retrieval"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="retrieval token is not configured for non-local access",
        )
    if not x_boh_retrieval_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"missing {RETRIEVAL_HEADER}",
        )
    if not token_config.verify("retrieval", x_boh_retrieval_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid retrieval token",
        )
    return "retrieval_connector"


def _terms(text: str) -> list[str]:
    return [t.lower() for t in WORD_RE.findall(text or "") if t.lower() not in STOPWORDS]


def _strong_identifier_terms(terms: list[str]) -> list[str]:
    """Return identifier-shaped terms that should not degrade to generic matches."""
    return [term for term in terms if STRONG_IDENTIFIER_RE.fullmatch(term)]


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


FILTER_KEYS = frozenset({'doc_id','status','authority_state','canonical_layer','project','chunk_type','library_id'})


def validate_filters(filters: dict[str, Any] | None) -> dict[str, str]:
    if filters is None:
        return {}
    if not isinstance(filters, dict) or set(filters) - FILTER_KEYS:
        raise ValueError('unsupported retrieval filter')
    if any(value is not None and (not isinstance(value,str) or not value.strip()) for value in filters.values()):
        raise ValueError('retrieval filters require nonempty string values')
    normalized = {key:value for key,value in filters.items() if value is not None}
    if 'library_id' in normalized:
        normalized['library_id'] = normalized['library_id'].strip()
        if normalized['library_id'] == 'all':
            del normalized['library_id']
    return normalized


def require_matching_scope(filters: dict[str, Any] | None, result: Any) -> dict[str, str]:
    requested = validate_filters(filters)
    if requested and requested != (result.get('retrieval') or {}).get('filters', {}):
        raise ValueError('supplied retrieval result does not match requested scope')
    return requested


def _quoted_phrases(query: str) -> list[str]:
    # FTS retains stopwords and single-character tokens inside literal phrases.
    return [' '.join(re.findall(r'[A-Za-z0-9_]+',value.lower()))
            for value in re.findall(r'"([^"]+)"', query)
            if re.search(r'[A-Za-z0-9_]',value)]


def _query_identifiers(query: str) -> list[str]:
    """Keep clear code identifiers literal without constraining ordinary prose."""
    identifiers = _strong_identifier_terms(_terms(query))
    identifiers.extend(
        token.lower() for token in LITERAL_TOKEN_RE.findall(query or "")
        if ("." in token or "_" in token) and re.search(r"[A-Za-z]", token)
        # Initialisms such as e.g./U.S. remain prose unless explicitly backticked.
        and not re.fullmatch(r"[A-Za-z](?:\.[A-Za-z])+", token)
    )
    identifiers.extend(
        value.lower() for value in re.findall(r"`([^`]+)`", query or "")
        if LITERAL_TOKEN_RE.fullmatch(value)
    )
    return list(dict.fromkeys(identifiers))


def _matches_query_constraints(query: str, *texts: str) -> bool:
    identifiers = set(_query_identifiers(query))
    phrases = _quoted_phrases(query)
    if not identifiers and not phrases:
        return True
    tokens = {token.lower() for text in texts for token in LITERAL_TOKEN_RE.findall(text or "")}
    normalized = [' ' + ' '.join(re.findall(r'[A-Za-z0-9_]+', (text or '').lower())) + ' '
                  for text in texts]
    # Each phrase must occur within a field; concatenating headings/chunks or
    # separate card fields can manufacture an adjacency absent from the source.
    return identifiers.issubset(tokens) and all(
        any(' ' + phrase + ' ' in field for field in normalized)
        for phrase in phrases
    )


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
    clause = (" AND " + " AND ".join(clauses)) if clauses else ""
    return clause, params


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


@dataclass
class _BatchedMetadata:
    lineage: dict[str, list[dict]]
    conflicts: dict[str, list[dict]]
    context_conflicts: dict[str, list[dict]]
    provenance: dict[str, dict]
    review_state: dict[str, dict]
    intake_provenance: dict[str, dict]
    cards_by_doc: dict[str, PlaneCard]
    recent_cards: list[PlaneCard]
    source_lifecycle: dict[str, dict] | None = None


def _batch_metadata(
    snapshot: _RetrievalReadSnapshot,
    doc_ids: list[str],
    *,
    recent_card_limit: int,
    recent_card_query: tuple[str, tuple] | None = None,
) -> _BatchedMetadata:
    """Load all candidate metadata in one traced read statement."""
    unique_ids = list(dict.fromkeys(doc_id for doc_id in doc_ids if doc_id))
    card_query, card_params = recent_card_query or (
        'SELECT id FROM cards ORDER BY updated_ts DESC LIMIT ?', (recent_card_limit,))
    if not unique_ids:
        rows = snapshot.fetchall(
            f"SELECT c.*, {source_lifecycle.payload_sql('c.doc_id')} AS source_lifecycle_json FROM cards c WHERE id IN ({card_query}) ORDER BY updated_ts DESC",
            card_params,
        )
        cards = [_row_to_card(row) for row in rows]
        return _BatchedMetadata(
            {}, {}, {}, {}, {}, {},
            {card.doc_id: card for card in cards if card.doc_id},
            cards,
            {row['doc_id']: source_lifecycle.decode_status(row['source_lifecycle_json']) for row in rows if row.get('doc_id')},
        )

    marks = _in_marks(unique_ids)
    conflict_predicate = " OR ".join("x.doc_ids LIKE ?" for _ in unique_ids)
    conflict_params = tuple(f"%{doc_id}%" for doc_id in unique_ids)
    params: list[Any] = []
    parts: list[str] = []

    parts.append(
        "SELECT 'lineage' AS kind, l.doc_id AS object_id, "
        "json_object('id', l.id, 'doc_id', l.doc_id, 'related_doc_id', l.related_doc_id, "
        "'relationship', l.relationship, 'detected_ts', l.detected_ts, 'detail', l.detail) AS payload "
        f"FROM lineage l WHERE l.doc_id IN ({marks}) OR l.related_doc_id IN ({marks})"
    )
    params.extend(unique_ids)
    params.extend(unique_ids)

    parts.append(
        "SELECT 'conflict' AS kind, NULL AS object_id, "
        "json_object('rowid', x.rowid, 'conflict_type', x.conflict_type, 'doc_ids', x.doc_ids, "
        "'term', x.term, 'plane_path', x.plane_path, 'detected_ts', x.detected_ts, "
        "'acknowledged', x.acknowledged) AS payload "
        f"FROM conflicts x WHERE {conflict_predicate}"
    )
    params.extend(conflict_params)

    parts.append(
        "SELECT 'artifact' AS kind, p.document_id AS object_id, "
        "json_object('artifact_id', p.artifact_id, 'approval_id', p.approval_id, "
        "'action_type', p.action_type, 'document_id', p.document_id, "
        "'from_state', p.from_state, 'to_state', p.to_state, "
        "'approved_by', p.approved_by, 'approved_at', p.approved_at) AS payload "
        f"FROM provenance_artifacts p WHERE p.document_id IN ({marks})"
    )
    params.extend(unique_ids)

    parts.append(
        "SELECT 'intake' AS kind, p.doc_id AS object_id, "
        "json_object('promotion_id', p.promotion_id, 'source_revision_id', p.source_revision_id, "
        "'intake_capability_id', p.intake_capability_id, 'handoff_id', p.handoff_id, "
        "'normalized_artifact_id', p.normalized_artifact_id, 'normalized_hash', p.normalized_hash, "
        "'normalized_output_type', p.normalized_output_type, "
        "'normalized_output_profile', p.normalized_output_profile, 'adapter_id', p.adapter_id, "
        "'adapter_version', p.adapter_version, 'adapter_registry_version', p.adapter_registry_version, "
        "'policy_snapshot_hash', p.policy_snapshot_hash, 'promoted_by', p.promoted_by, "
        "'promoted_at', p.promoted_at, 'intake_run_id', h.intake_run_id) AS payload "
        "FROM intake_promotions p LEFT JOIN intake_handoffs h ON h.handoff_id = p.handoff_id "
        f"WHERE p.doc_id IN ({marks}) AND p.status = 'active'"
    )
    params.extend(unique_ids)

    parts.append(
        "SELECT 'card' AS kind, c.doc_id AS object_id, "
        "json_object('rowid', c.rowid, 'id', c.id, 'plane', c.plane, 'card_type', c.card_type, "
        "'topic', c.topic, 'b', c.b, 'd', c.d, 'm', c.m, 'delta_json', c.delta_json, "
        "'constraints_json', c.constraints_json, 'authority_json', c.authority_json, "
        "'observed_at', c.observed_at, 'valid_until', c.valid_until, "
        "'context_ref_json', c.context_ref_json, 'payload_json', c.payload_json, "
        "'doc_id', c.doc_id, 'created_ts', c.created_ts, 'updated_ts', c.updated_ts, "
        "'plane_card_version', c.plane_card_version, "
        f"'recent', CASE WHEN c.id IN ({card_query}) "
        "THEN 1 ELSE 0 END) AS payload FROM cards c "
        f"WHERE (c.doc_id IN ({marks}) OR c.id IN "
        f"({card_query})){source_lifecycle.card_clause('c')}"
    )
    params.extend(card_params)
    params.extend(unique_ids)
    params.extend(card_params)

    parts.append("SELECT 'source_lifecycle' AS kind,d.doc_id AS object_id, "
                 + source_lifecycle.payload_sql('d.doc_id') + " AS payload FROM docs d "
                 + f"WHERE d.doc_id IN ({marks}) OR d.doc_id IN (SELECT doc_id FROM cards WHERE id IN ({card_query}))")
    params.extend(unique_ids)
    params.extend(card_params)
    try:
        rows = snapshot.fetchall(" UNION ALL ".join(parts), tuple(params))
    except Exception as exc:
        # Old databases may predate the intake tables. Preserve the established
        # fail-soft intake-provenance behavior without hiding other SQL defects.
        if "intake_" not in str(exc).lower() or "no such table" not in str(exc).lower():
            raise
        intake_index = next(i for i, part in enumerate(parts) if "'intake' AS kind" in part)
        del parts[intake_index]
        intake_param_start = len(unique_ids) * 2 + len(conflict_params) + len(unique_ids)
        del params[intake_param_start:intake_param_start + len(unique_ids)]
        rows = snapshot.fetchall(" UNION ALL ".join(parts), tuple(params))

    lineage_rows: list[dict] = []
    conflict_rows: list[dict] = []
    artifacts: dict[str, list[dict]] = defaultdict(list)
    intake: dict[str, dict] = {}
    card_rows: list[dict] = []
    source_statuses = {}
    for row in rows:
        if row.get('kind') == 'source_lifecycle':
            source_statuses[row['object_id']] = source_lifecycle.decode_status(row.get('payload'))
            continue
        payload = json.loads(row.get("payload") or "{}")
        kind = row.get("kind")
        if kind == "lineage":
            lineage_rows.append(payload)
        elif kind == "conflict":
            conflict_rows.append(payload)
        elif kind == "artifact":
            artifacts[str(row.get("object_id") or "")].append(payload)
        elif kind == "intake":
            intake.setdefault(str(row.get("object_id") or ""), payload)
        elif kind == "card":
            card_rows.append(payload)

    lineage_rows.sort(key=lambda row: (-(row.get("detected_ts") or 0), row.get("id") or 0))
    lineage_by_doc: dict[str, list[dict]] = {}
    for doc_id in unique_ids:
        lineage_by_doc[doc_id] = [
            row for row in lineage_rows
            if row.get("doc_id") == doc_id or row.get("related_doc_id") == doc_id
        ]

    conflict_rows.sort(key=lambda row: (-(row.get("detected_ts") or 0), row.get("rowid") or 0))
    conflicts_by_doc: dict[str, list[dict]] = {}
    context_conflicts_by_doc: dict[str, list[dict]] = {}
    for doc_id in unique_ids:
        # Preserve the legacy retrieval order: SQL LIKE + LIMIT 10 happened
        # before exact CSV membership filtering. ContextObject historically
        # used the full exact member set, so keep that separately.
        legacy_like_rows = [
            row for row in conflict_rows if doc_id in str(row.get("doc_ids") or "")
        ][:10]
        matched = []
        for row in legacy_like_rows:
            if doc_id not in str(row.get("doc_ids") or "").split(","):
                continue
            item = dict(row)
            item["resolution_status"] = "acknowledged" if item.get("acknowledged") else "open"
            matched.append(item)
        conflicts_by_doc[doc_id] = matched
        full_exact = []
        for row in conflict_rows:
            if doc_id not in str(row.get("doc_ids") or "").split(","):
                continue
            item = dict(row)
            item["resolution_status"] = "acknowledged" if item.get("acknowledged") else "open"
            full_exact.append(item)
        context_conflicts_by_doc[doc_id] = full_exact

    provenance: dict[str, dict] = {}
    review_state: dict[str, dict] = {}
    for doc_id in unique_ids:
        ordered = sorted(
            artifacts.get(doc_id, []),
            key=lambda row: -(row.get("approved_at") or 0),
        )
        provenance[doc_id] = {"artifacts": [
            {key: row.get(key) for key in (
                "artifact_id", "approval_id", "approved_by", "approved_at", "action_type"
            )}
            for row in ordered[:5]
        ]}
        review_state[doc_id] = {
            "last_review": ({key: ordered[0].get(key) for key in (
                "action_type", "from_state", "to_state", "approved_by", "approved_at"
            )} if ordered else None),
            "review_count": len(ordered),
        }

    cards_by_doc: dict[str, PlaneCard] = {}
    recent_rows = []
    for row in card_rows:
        is_recent = bool(row.pop("recent", 0))
        row.pop("rowid", None)
        card = _row_to_card(row)
        if card.doc_id and card.doc_id not in cards_by_doc:
            cards_by_doc[card.doc_id] = card
        if is_recent:
            recent_rows.append((row.get("updated_ts") or 0, card))
    recent_rows.sort(key=lambda item: item[0], reverse=True)

    return _BatchedMetadata(
        lineage=lineage_by_doc,
        conflicts=conflicts_by_doc,
        context_conflicts=context_conflicts_by_doc,
        provenance=provenance,
        review_state=review_state,
        intake_provenance=intake,
        cards_by_doc=cards_by_doc,
        recent_cards=[card for _updated, card in recent_rows[:recent_card_limit]],
        source_lifecycle=source_statuses,
    )


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
    # status, authority_state, and canonical_layer are correlated projections of
    # authority. Preserve their existing tier signals without letting the three
    # aliases stack beyond the retrieval component's 0.15 score budget.
    return max(
        -RETRIEVAL_AUTHORITY_COMPONENT_BUDGET,
        min(RETRIEVAL_AUTHORITY_COMPONENT_BUDGET, weight),
    )


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
    # Library scope has already constrained the backing-doc card pool in SQL.
    return all(values.get(k) == v for k, v in (filters or {}).items() if k != 'library_id')


def _matching_card_packs(query: str, mode: str, limit: int,
                         filters: dict[str, Any] | None = None,
                         cards: list[PlaneCard] | None = None,
                         source_statuses: dict[str, dict] | None = None) -> list[dict]:
    q_terms = set(_terms(query))
    has_constraints = bool(_query_identifiers(query) or _quoted_phrases(query))
    if not q_terms and not has_constraints:
        return []
    packs = []
    card_pool = cards if cards is not None else list_cards(limit=max(limit * 4, 25))
    for card in card_pool:
        c = card.to_dict()
        if not _card_matches_filters(c, filters):
            continue
        payload = c.get("payload") or {}
        fields = [
            c.get("topic") or "",
            c.get("plane") or "",
            c.get("card_type") or "",
            str(payload.get("title") or ""),
            str(payload.get("summary") or ""),
            str(payload.get("text") or ""),
        ]
        haystack_terms = set(_terms(" ".join(fields)))
        if not _matches_query_constraints(query, *fields):
            continue
        overlap = q_terms & haystack_terms
        # Literal phrases containing only stopwords/one-character tokens can
        # satisfy constraints even though the ordinary scorer has no terms.
        if not overlap and not has_constraints:
            continue
        score = 0.20 + min(0.40, len(overlap) / max(len(q_terms), 1))
        pack = _card_pack(card, query, mode, score=round(score, 6))
        state = (source_statuses or {}).get(c.get('doc_id'), source_lifecycle.decode_status(None))
        pack['source_lifecycle'] = state
        if state['current_evidence'] is False:
            pack['do_not_treat_as_canonical'] = True
            pack['warnings'].append('historical_source_evidence')
        packs.append(pack)
    packs.sort(key=lambda p: p["score"], reverse=True)
    return packs[:limit]


def _attach_card_authority(
    packs: list[dict],
    mode: str,
    cards_by_doc: dict[str, PlaneCard] | None = None,
) -> list[dict]:
    out = []
    for pack in packs:
        if pack.get("card_id"):
            out.append(pack)
            continue
        card = (
            (cards_by_doc or {}).get(pack.get("doc_id"))
            if cards_by_doc is not None
            else (get_card_for_doc(pack.get("doc_id"), auto_wrap=False) if pack.get("doc_id") else None)
        )
        if card:
            c = card.to_dict()
            payload = dict(c.get("payload") or {})
            payload["non_authoritative"] = bool(
                payload.get("non_authoritative")
                or pack.get("do_not_treat_as_canonical")
            )
            if payload.get("confidence") is None:
                semantic_score = (pack.get("why_selected") or {}).get("semantic_score")
                if semantic_score is not None:
                    payload["confidence"] = semantic_score
            c["payload"] = payload
            authority = dict(c.get("authority") or {})
            if not authority.get("state") and pack.get("authority_state"):
                authority["state"] = pack.get("authority_state")
            c["authority"] = authority
            decision = planar_authority.can_use(
                "retrieval_connector",
                c,
                "answer_context",
                mode,
            )
            pack["card_id"] = c.get("id")
            pack["plane"] = c.get("plane")
            pack["card_type"] = c.get("card_type")
        else:
            mode_key = str(mode or "").lower().replace(" ", "_").replace("-", "_")
            if mode_key in {"strict_answer", "strict"}:
                decision = planar_authority.Decision(
                    allowed=False,
                    reason="missing_plane_card",
                    required_action="review_card",
                    visible_message=(
                        "This evidence has no PlaneCard and cannot support a strict answer."
                    ),
                )
            else:
                freshness = pack.get("freshness") or {}
                card_like = {
                    "id": None,
                    "doc_id": pack.get("doc_id"),
                    "plane": pack.get("plane"),
                    "payload": {
                        "non_authoritative": bool(
                            pack.get("do_not_treat_as_canonical")
                        ),
                        "confidence": (
                            pack.get("why_selected") or {}
                        ).get("semantic_score"),
                    },
                    "authority": {"state": pack.get("authority_state")},
                    "valid_until": freshness.get("valid_until"),
                }
                decision = planar_authority.can_use(
                    "retrieval_connector",
                    card_like,
                    "answer_context",
                    mode,
                )
        pack["eligibility"] = decision.to_dict()
        if not decision.allowed:
            warning = f"blocked:{decision.reason}"
            if warning not in pack.setdefault("warnings", []):
                pack["warnings"].append(warning)
        out.append(pack)
    return out


def _audit_objects(
    packs: list[dict],
    snapshot: _RetrievalReadSnapshot | None = None,
) -> dict:
    card_ids = [p.get("card_id") for p in packs if p.get("card_id")]
    doc_ids = [p.get("doc_id") for p in packs if p.get("doc_id")]
    if snapshot is not None:
        card_query_ids = list(dict.fromkeys(card_ids[:10]))
        doc_query_ids = list(dict.fromkeys(doc_ids[:10]))
        event_clauses = []
        event_params: list[Any] = []
        if card_query_ids:
            event_clauses.append(f"card_id IN ({_in_marks(card_query_ids)})")
            event_params.extend(card_query_ids)
        if doc_query_ids:
            event_clauses.append(f"doc_id IN ({_in_marks(doc_query_ids)})")
            event_params.extend(doc_query_ids)
        event_rows = snapshot.fetchall(
            "SELECT * FROM storage_events WHERE " + " OR ".join(event_clauses)
            + " ORDER BY created_ts DESC",
            tuple(event_params),
        ) if event_clauses else []
        events = []
        for card_id in card_ids[:10]:
            events.extend([row for row in event_rows if row.get("card_id") == card_id][:10])
        for doc_id in doc_ids[:10]:
            events.extend([row for row in event_rows if row.get("doc_id") == doc_id][:10])
        certificate_rows = snapshot.fetchall(
            f"SELECT * FROM certificates WHERE node_id IN ({_in_marks(card_query_ids)}) "
            "ORDER BY created_at DESC",
            tuple(card_query_ids),
        ) if card_query_ids else []
        interface_rows = snapshot.fetchall(
            f"SELECT * FROM plane_interfaces WHERE node_id IN ({_in_marks(card_query_ids)}) "
            "ORDER BY created_at DESC",
            tuple(card_query_ids),
        ) if card_query_ids else []
        certificates = []
        interfaces = []
        for card_id in card_ids[:10]:
            certificates.extend([
                row for row in certificate_rows if row.get("node_id") == card_id
            ][:5])
            interfaces.extend([
                row for row in interface_rows if row.get("node_id") == card_id
            ][:5])
        return {
            "storage_events": events[:30],
            "certificates": certificates[:20],
            "plane_interfaces": interfaces[:20],
        }
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


def retrieve_governed_result(
    query: str,
    mode: str = "strict_answer",
    limit: int = 8,
    include_lineage: bool = True,
    filters: dict[str, Any] | None = None,
    max_context_chars: int = 6000,
    include_promoted: bool = False,
    emit_audit_event: bool = True,
) -> GovernedRetrievalResult:
    """Build one normalized governed result for all answer-oriented consumers."""
    filters = validate_filters(filters)
    mode_key = (mode or "strict_answer").lower().replace(" ", "_").replace("-", "_")
    if mode_key not in {"strict_answer", "exploration", "audit_provenance", "canon_review", "low_b_worker_context"}:
        raise ValueError(f"unknown retrieval mode: {mode!r}")

    # Admit one bounded population before applying the caller's output limit.
    # Otherwise chunk/card de-duplication can replace an earlier card when a
    # larger request admits another chunk from its document. The fixed public
    # horizon also stabilizes FTS normalization, lineage and recent-card reads.
    selection_limit = max(GOVERNED_SELECTION_LIMIT, limit)
    exact = (exact_lookup.Budget(lambda *fields: _matches_query_constraints(query, *fields))
             if _query_identifiers(query) or _quoted_phrases(query) else None)
    included, excluded, context_conflicts, audit = [], [], [], {}
    base = {"retrieval": _retrieval_metadata()}
    with _RetrievalReadSnapshot() as snapshot, exact_lookup.guard(exact):
        snapshot.exact_budget = exact
        if exact is not None:
            exact.register(snapshot.conn)
        base, metadata = retrieve(
            query,
            limit=selection_limit,
            include_lineage=include_lineage,
            filters=filters,
            max_context_chars=max_context_chars,
            # Dual gate (DEC-0004): server env AND request flag must both be open.
            show_promoted=promoted_exposure.visible(include_promoted),
            _snapshot=snapshot,
            _return_metadata=True,
            include_source_history=mode_key == 'audit_provenance',
        )
        packs = _attach_card_authority(
            base.get("context_packs", []), mode_key, metadata.cards_by_doc
        )
        existing_cards = {p.get("card_id") for p in packs}
        for pack in _matching_card_packs(
            query,
            mode_key,
            exact.match_limit if exact is not None else selection_limit,
            filters=filters,
            cards=metadata.recent_cards,
            source_statuses=metadata.source_lifecycle,
        ):
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
                    # Preserve the established response key without leaking title/content.
                    "title": None,
                    "plane": pack.get("plane"),
                    "mode": mode_key,
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
        # Card augmentation participates in the same final character budget.
        # Stop at the first over-budget successor so every smaller limit keeps
        # this prefix; preserve raw retrieval's first-pack oversize convention.
        bounded = []
        used_chars = 0
        for pack in included:
            if len(bounded) >= limit:
                break
            next_chars = len(pack.get("text") or "")
            if bounded and used_chars + next_chars > max_context_chars:
                break
            bounded.append(pack)
            used_chars += next_chars
        included = bounded

        context_conflict_map: dict[str, dict] = {}
        for doc_id in dict.fromkeys(
            pack.get("doc_id") for pack in included if pack.get("doc_id")
        ):
            for conflict in metadata.context_conflicts.get(doc_id, []):
                key = str(conflict.get("rowid") or conflict.get("conflict_id") or conflict)
                context_conflict_map.setdefault(key, conflict)
        context_conflicts = list(context_conflict_map.values())
        context_conflicts.sort(
            key=lambda conflict: (
                conflict.get("resolution_status") != "open",
                -(conflict.get("detected_ts") or 0),
                -(conflict.get("rowid") or 0),
            )
        )
        context_conflicts = context_conflicts[:50]

        audit = _audit_objects(included, snapshot) if mode_key == "audit_provenance" else {}
    if exact is not None and exact.failure:
        included, excluded, context_conflicts, audit = [], [], [], {}
        base = {"retrieval": _retrieval_metadata()}
    if emit_audit_event:
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
    if exact is not None:
        meta['exact_lookup'] = exact.public()
    meta["context_chars"] = sum(len(p.get("text") or "") for p in included)
    meta["returned_count"] = len(included)
    meta["planar_mode"] = mode_key
    meta["eligibility_filtered"] = True
    meta["excluded_count"] = len(excluded)
    meta["mode_notes"] = {
        "strict_answer": "Excludes missing-card, subjective, expired, blocked, low-confidence, and non-authoritative evidence.",
        "exploration": "Includes weaker material but labels eligibility and canonicality warnings.",
        "audit_provenance": "Prioritizes trace/provenance objects and returns audit context.",
        "canon_review": "Ranks canonical/authority material first while preserving warnings.",
        "low_b_worker_context": "Allows broad context for worker tasks; callers must preserve warnings.",
    }.get(mode_key)
    meta['source_lifecycle_policy'] = 'labelled_history' if mode_key == 'audit_provenance' else 'current_managed_sources'
    meta['filters'] = filters
    meta['promoted_visibility'] = {
        'env_gate_open': promoted_exposure.env_gate_open(),
        'request_opt_in': bool(include_promoted),
        'visible': promoted_exposure.visible(include_promoted),
    }
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
    if exact is not None and exact.public()['state'] != 'complete':
        top_warnings.append('exact_lookup_incomplete')

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

    return GovernedRetrievalResult(
        query=query,
        context_packs=included,
        excluded_summary=excluded,
        audit_context=audit,
        retrieval=meta,
        planar_context_pack=context_pack,
        gate_result=gate_result,
        warnings=top_warnings,
        context_conflicts=context_conflicts,
    )


def retrieve_governed(query: str, mode: str = "strict_answer", limit: int = 8,
                      include_lineage: bool = True, filters: dict[str, Any] | None = None,
                      max_context_chars: int = 6000,
                      include_promoted: bool = False) -> dict:
    """Backward-compatible wire adapter for the normalized governed result."""
    return retrieve_governed_result(
        query,
        mode=mode,
        limit=limit,
        include_lineage=include_lineage,
        filters=filters,
        max_context_chars=max_context_chars,
        include_promoted=include_promoted,
    ).to_dict()


def retrieve(query: str, limit: int = 8, include_lineage: bool = True,
             filters: dict[str, Any] | None = None,
             max_context_chars: int = 6000,
             show_promoted: bool = False,
             *,
             _snapshot: _RetrievalReadSnapshot | None = None,
             _return_metadata: bool = False,
             include_source_history: bool = False) -> Any:
    """Return raw retrieval wire data, optionally reusing an owned read snapshot."""
    filters = validate_filters(filters)
    if _snapshot is None:
        with _RetrievalReadSnapshot() as snapshot:
            result, metadata = _retrieve_in_snapshot(
                query,
                limit=limit,
                include_lineage=include_lineage,
                filters=filters,
                max_context_chars=max_context_chars,
                show_promoted=show_promoted,
                snapshot=snapshot,
                include_source_history=include_source_history,
            )
    else:
        result, metadata = _retrieve_in_snapshot(
            query,
            limit=limit,
            include_lineage=include_lineage,
            filters=filters,
            max_context_chars=max_context_chars,
            show_promoted=show_promoted,
            snapshot=_snapshot,
            include_source_history=include_source_history,
        )
    return (result, metadata) if _return_metadata else result


def _retrieve_in_snapshot(
    query: str,
    *,
    limit: int,
    include_lineage: bool,
    filters: dict[str, Any] | None,
    max_context_chars: int,
    show_promoted: bool,
    snapshot: _RetrievalReadSnapshot,
    include_source_history: bool = False,
) -> tuple[dict, _BatchedMetadata]:
    filters = filters or {}
    q_terms = _terms(query)
    strong_identifiers = _query_identifiers(query)
    q_vec = _term_counter(query)
    where, params = _metadata_where(filters)
    source_clause = '' if include_source_history else source_lifecycle.current_clause('d.doc_id')
    where += source_clause
    library_clause, library_params = '', []
    if filters.get('library_id'):
        from app.core.logical_libraries import docs_where_clause
        library_clause, library_params, _ = docs_where_clause(filters['library_id'], alias='d')
        where += library_clause
        params.extend(library_params)
    promo = promoted_exposure.exclusion_sql("d", show_promoted=show_promoted)
    # Each term is quoted as an FTS5 string literal: identical semantics for plain words, and
    # operator characters inside tokens ('-', ':') can no longer raise an FTS syntax error —
    # a hyphenated token matches as the phrase of its tokenizer sub-tokens
    # (boh_retrieval_fts_query_hyphen_hardening_v0_1).
    phrases = _quoted_phrases(query)
    candidate_terms = list(dict.fromkeys(phrases + strong_identifiers)) or q_terms[:12]
    candidate_joiner = " AND " if strong_identifiers or phrases else " OR "
    fts_query = candidate_joiner.join(f'"{t}"' for t in candidate_terms)
    exact = getattr(snapshot, 'exact_budget', None)
    exact_supplement = []
    recent_card_limit = exact.match_limit + 1 if exact is not None else max(limit * 4, 25)
    card_filter_clause, card_filter_params = exact_lookup.card_filters(filters) if exact is not None else ('', [])
    card_scope_params = list(library_params) + card_filter_params
    card_scope = f"1=1{library_clause}{promo}{source_clause}{source_lifecycle.card_clause('card')}{card_filter_clause}"
    card_exact_clause = (exact.predicate(
        'card.topic', 'card.plane', 'card.card_type', 'card.payload_json',
        guard=card_scope, function='boh_exact_card') if exact is not None else '')
    recent_card_query = (
        'SELECT card.id FROM cards card LEFT JOIN docs d ON d.doc_id=card.doc_id '
        f"WHERE 1=1{library_clause}{promo}{source_clause}{source_lifecycle.card_clause('card')}{card_filter_clause}{card_exact_clause} "
        'ORDER BY card.updated_ts DESC LIMIT ?', (*card_scope_params, *(card_scope_params if exact is not None else []), recent_card_limit),
    )
    rows = []
    if fts_query:
        if exact is not None:
            rows, exact_supplement = exact_lookup.candidates(
                snapshot, f"""
            SELECT c.*, d.title, d.summary, d.type, d.project, d.document_class,
                   d.operator_state, d.operator_intent, d.provenance_json,
                   d.source_type, d.topics_tokens, d.updated_ts, d.corpus_class,
                   d.epistemic_last_evaluated, d.epistemic_valid_until,
                   {source_lifecycle.payload_sql('d.doc_id')} AS source_lifecycle_json,
                   e.vector_json AS embedding_vector_json,
                   bm25(doc_chunks_fts) AS bm25_score, 0 AS _exact_scan
            FROM doc_chunks_fts
            JOIN doc_chunks c ON c.chunk_id = doc_chunks_fts.chunk_id
            JOIN docs d ON d.doc_id = c.doc_id
            LEFT JOIN doc_chunk_embeddings e ON e.chunk_id = c.chunk_id
            WHERE doc_chunks_fts MATCH ? {where}{promo}{exact.predicate("c.text", "c.heading_path", guard="1=1"+where+promo)}
            ORDER BY bm25(doc_chunks_fts)
            LIMIT ?
            """, (fts_query, *params, *params, max(limit * 4, 20)),
                f"""
            SELECT c.*, d.title, d.summary, d.type, d.project, d.document_class,
                   d.operator_state, d.operator_intent, d.provenance_json,
                   d.source_type, d.topics_tokens, d.updated_ts, d.corpus_class,
                   d.epistemic_last_evaluated, d.epistemic_valid_until,
                   {source_lifecycle.payload_sql('d.doc_id')} AS source_lifecycle_json,
                   e.vector_json AS embedding_vector_json,
                   0.0 AS bm25_score, 1 AS _exact_scan
            FROM doc_chunks c
            JOIN docs d ON d.doc_id = c.doc_id
            LEFT JOIN doc_chunk_embeddings e ON e.chunk_id = c.chunk_id
            WHERE 1=1 {where}{promo}{exact.predicate("c.text", "c.heading_path", guard="1=1"+where+promo)}
            ORDER BY c.rowid
            LIMIT ?
            """, (*params, *params, exact.match_limit + 1), exact)
        else:
            rows = snapshot.fetchall(f"""
            SELECT c.*, d.title, d.summary, d.type, d.project, d.document_class,
                   d.operator_state, d.operator_intent, d.provenance_json,
                   d.source_type, d.topics_tokens, d.updated_ts, d.corpus_class,
                   d.epistemic_last_evaluated, d.epistemic_valid_until,
                   {source_lifecycle.payload_sql('d.doc_id')} AS source_lifecycle_json,
                   e.vector_json AS embedding_vector_json,
                   bm25(doc_chunks_fts) AS bm25_score
            FROM doc_chunks_fts
            JOIN doc_chunks c ON c.chunk_id = doc_chunks_fts.chunk_id
            JOIN docs d ON d.doc_id = c.doc_id
            LEFT JOIN doc_chunk_embeddings e ON e.chunk_id = c.chunk_id
            WHERE doc_chunks_fts MATCH ? {where}{promo}
            ORDER BY bm25(doc_chunks_fts)
            LIMIT ?
            """, (fts_query, *params, max(limit * 4, 20)))
            rows = [dict(r) | {"retrieval_source": "fts"} for r in rows
                    if _matches_query_constraints(query, r['text'], r['heading_path'] or '')]
    if not rows and not strong_identifiers and not phrases:
        fallback_rows = snapshot.fetchall(
            f"""
            SELECT c.*, d.title, d.summary, d.type, d.project, d.document_class,
                   d.operator_state, d.operator_intent, d.provenance_json,
                   d.source_type, d.topics_tokens, d.updated_ts, d.corpus_class,
                   d.epistemic_last_evaluated, d.epistemic_valid_until,
                   {source_lifecycle.payload_sql('d.doc_id')} AS source_lifecycle_json,
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
    if not rows and not exact_supplement:
        metadata = _batch_metadata(snapshot, [], recent_card_limit=recent_card_limit, recent_card_query=recent_card_query)
        if exact is not None:
            exact.cards = len(metadata.recent_cards) <= exact.match_limit
            metadata.recent_cards = metadata.recent_cards[:exact.match_limit]
        return {
            "query": query,
            "count": 0,
            "context_packs": [],
            "retrieval": _retrieval_metadata(),
        }, metadata

    if include_lineage:
        seen_chunk_ids = {r["chunk_id"] for r in rows}
        seed_doc_ids = list(dict.fromkeys(r["doc_id"] for r in rows[:max(limit, 3)]))
        seed_marks = _in_marks(seed_doc_ids)
        seed_lineage = snapshot.fetchall(
            f"SELECT * FROM lineage WHERE doc_id IN ({seed_marks}) "
            f"OR related_doc_id IN ({seed_marks}) ORDER BY detected_ts DESC",
            tuple(seed_doc_ids + seed_doc_ids),
        )
        related_by_seed: dict[str, list[str]] = {}
        for doc_id in seed_doc_ids:
            related = []
            for lineage_row in seed_lineage:
                related_doc_id = None
                if lineage_row.get("doc_id") == doc_id:
                    related_doc_id = lineage_row.get("related_doc_id")
                elif lineage_row.get("related_doc_id") == doc_id:
                    related_doc_id = lineage_row.get("doc_id")
                if related_doc_id and related_doc_id not in related:
                    related.append(related_doc_id)
            related_by_seed[doc_id] = related[:3]
        related_doc_ids = list(dict.fromkeys(
            related_doc_id
            for doc_id in seed_doc_ids
            for related_doc_id in related_by_seed.get(doc_id, [])
        ))
        related_by_doc: dict[str, list[dict]] = defaultdict(list)
        if related_doc_ids:
            exact_lineage_clause = (
                " AND c.chunk_id IN (SELECT lc.chunk_id FROM doc_chunks lc WHERE lc.doc_id=c.doc_id "
                "ORDER BY lc.chunk_index LIMIT 2)" + exact.predicate('c.text', 'c.heading_path', guard='1=1'+where+promo)
                if exact is not None else '')
            related_marks = _in_marks(related_doc_ids)
            related_rows = snapshot.fetchall(
                f"""
                SELECT c.*, d.title, d.summary, d.type, d.project, d.document_class,
                       d.operator_state, d.operator_intent, d.provenance_json,
                       d.source_type, d.topics_tokens, d.updated_ts, d.corpus_class,
                       d.epistemic_last_evaluated, d.epistemic_valid_until,
                       {source_lifecycle.payload_sql('d.doc_id')} AS source_lifecycle_json,
                       e.vector_json AS embedding_vector_json,
                       0.0 AS bm25_score
                FROM doc_chunks c
                JOIN docs d ON d.doc_id = c.doc_id
                LEFT JOIN doc_chunk_embeddings e ON e.chunk_id = c.chunk_id
                WHERE c.doc_id IN ({related_marks}) {where}{promo}{exact_lineage_clause}
                ORDER BY c.doc_id, c.chunk_index
                """,
                tuple(related_doc_ids + params + (params if exact is not None else [])),
            )
            for related_row in related_rows:
                if len(related_by_doc[related_row["doc_id"]]) < 2:
                    related_by_doc[related_row["doc_id"]].append(related_row)
        for doc_id in seed_doc_ids:
            for related_doc_id in related_by_seed.get(doc_id, []):
                for row in related_by_doc.get(related_doc_id, []):
                    item = dict(row)
                    if not _matches_query_constraints(query, item['text'], item['heading_path'] or ''):
                        continue
                    if item["chunk_id"] in seen_chunk_ids:
                        continue
                    seen_chunk_ids.add(item["chunk_id"])
                    item["retrieval_source"] = f"lineage_expansion:{doc_id}"
                    rows.append(item)

    if exact_supplement:
        admitted = {row['chunk_id'] for row in rows}
        rows.extend(row for row in exact_supplement if row['chunk_id'] not in admitted)
    metadata = _batch_metadata(
        snapshot,
        [row["doc_id"] for row in rows],
        recent_card_limit=recent_card_limit,
        recent_card_query=recent_card_query,
    )

    if exact is not None:
        exact.cards = len(metadata.recent_cards) <= exact.match_limit
        metadata.recent_cards = metadata.recent_cards[:exact.match_limit]
    q_embedding = _hash_embedding(query)
    bm25_vals = [r["bm25_score"] for r in rows]
    min_b = min(bm25_vals)
    max_b = max(bm25_vals)
    span = max_b - min_b if max_b != min_b else 1.0

    packs = []
    seen = set()
    for row in rows:
        if exact is not None:
            exact.check()
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
        all_lineages = metadata.lineage.get(item["doc_id"], [])
        lineages = all_lineages[:10] if include_lineage else []
        lineage_bonus = 0.05 if lineages else 0.0
        if str(item.get("retrieval_source") or "").startswith("lineage_expansion"):
            lineage_bonus += 0.03
        conflicts = metadata.conflicts.get(item["doc_id"], [])[:10]
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
        lifecycle_state = source_lifecycle.decode_status(item.get('source_lifecycle_json'))
        if lifecycle_state['current_evidence'] is False:
            do_not_treat_as_canonical = True
        try:
            frontmatter_provenance = json.loads(item.get("provenance_json") or "{}")
        except Exception:
            frontmatter_provenance = {"raw": item.get("provenance_json") or ""}
        superseding = next((
            row for row in all_lineages
            if row.get("doc_id") == item["doc_id"]
            and row.get("relationship") in {"superseded_by", "superseded"}
        ), None)
        age_days = None
        freshness_source = None
        for column in ("epistemic_last_evaluated", "updated_ts"):
            days = fold_metrics._parse_freshness_days(item.get(column), column)
            if days is not None:
                age_days, freshness_source = days, column
                break
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
            "provenance": {
                "frontmatter": frontmatter_provenance,
                "artifacts": metadata.provenance.get(item["doc_id"], {}).get("artifacts", []),
            },
            "review_state": metadata.review_state.get(
                item["doc_id"], {"last_review": None, "review_count": 0}
            ),
            "freshness": {
                "age_days": age_days,
                "source": freshness_source,
                "valid_until": item.get("epistemic_valid_until"),
                "superseded": bool(superseding) or lifecycle_state['superseded'],
                "superseded_by": superseding.get("related_doc_id") if superseding else lifecycle_state.get('superseded_by'),
            },
            "source_lifecycle": source_lifecycle.decode_status(item.get('source_lifecycle_json')),
            "intake_provenance": (
                metadata.intake_provenance.get(item["doc_id"])
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
                "historical_source_evidence" if lifecycle_state['current_evidence'] is False else "",
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
        if exact is None and len(bounded) >= limit:
            break
        next_chars = len(p["text"])
        if exact is None and bounded and used_chars + next_chars > max_context_chars:
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
    }, metadata
