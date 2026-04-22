"""crawler.py: Filesystem crawler and document indexer for Bag of Holding v0P.

Patch v1.1: A1 topics_tokens, D1/D2 event hardening, F defs json fix.
"""

import hashlib
import json
import os
import time
import uuid
from pathlib import Path

import db
from parser import (
    parse_frontmatter,
    validate_header,
    extract_definitions,
    extract_events,
    parse_iso_to_epoch,
)


# ── A1.1: Deterministic topic normalization ───────────────────────────────────

def normalize_topic_token(topic: str) -> str:
    """Lowercase, trim, collapse internal whitespace. No deletion or mutation."""
    return " ".join(topic.strip().lower().split())


def derive_topics_tokens(topics_array: list) -> str:
    """A1.2: Derive topics_tokens string from topics array. Always deterministic."""
    if not topics_array:
        return ""
    return " ".join(normalize_topic_token(t) for t in topics_array if t)


# ── Helpers ───────────────────────────────────────────────────────────────────

def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def extract_title(boh: dict, body: str) -> str:
    if "purpose" in boh:
        return boh["purpose"][:120]
    for line in body.splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip()[:120]
    return ""


def infer_source_type(path: Path) -> str:
    if "/canon/" in str(path):
        return "canon_folder"
    return "library"


# ── D2: Validate event has explicit start + timezone ─────────────────────────

def _validate_event(ev: dict) -> bool:
    """Return True only if event has explicit start (ISO8601) and timezone."""
    start = ev.get("start")
    tz = ev.get("timezone")
    if not start or not tz:
        return False
    ts = parse_iso_to_epoch(start)
    return ts is not None


# ── Main indexer ──────────────────────────────────────────────────────────────

def index_file(path: Path, library_root: Path) -> dict:
    """Index a single markdown file. Returns result dict with lint_errors."""
    rel_path = str(path.relative_to(library_root))
    text = path.read_text(encoding="utf-8", errors="replace")
    boh, body, parse_errors = parse_frontmatter(text)

    if boh is None:
        return {
            "path": rel_path,
            "doc_id": None,
            "lint_errors": parse_errors,
            "indexed": False,
        }

    lint_errors = parse_errors + validate_header(boh)
    doc_id = boh.get("id") or str(uuid.uuid4())
    scope = boh.get("scope", {}) or {}
    rubrix = boh.get("rubrix", {}) or {}

    plane_scope = scope.get("plane_scope") or []
    field_scope = scope.get("field_scope") or []
    node_scope = scope.get("node_scope") or []

    updated_ts = parse_iso_to_epoch(boh.get("updated")) or int(time.time())
    source_type = infer_source_type(path)
    title = extract_title(boh, body)
    topics = boh.get("topics") or []
    text_hash = hash_text(text)

    # A1.2: Derive topics_tokens deterministically
    topics_tokens = derive_topics_tokens(topics)

    conn = db.get_conn()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO docs
              (doc_id, path, type, status, version, updated_ts,
               operator_state, operator_intent,
               plane_scope_json, field_scope_json, node_scope_json,
               text_hash, source_type, topics_tokens)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                doc_id, rel_path,
                boh.get("type"), boh.get("status"),
                boh.get("version"), updated_ts,
                rubrix.get("operator_state"), rubrix.get("operator_intent"),
                json.dumps(plane_scope), json.dumps(field_scope), json.dumps(node_scope),
                text_hash, source_type, topics_tokens,
            ),
        )

        # FTS
        conn.execute("DELETE FROM docs_fts WHERE path = ?", (rel_path,))
        conn.execute(
            "INSERT INTO docs_fts(content, title, path, topics) VALUES (?,?,?,?)",
            (body, title, rel_path, json.dumps(topics)),
        )

        # F: Definitions — always use json.dumps for plane_scope_json
        conn.execute("DELETE FROM defs WHERE doc_id = ?", (doc_id,))
        defs = extract_definitions(body, plane_scope)
        for d in defs:
            conn.execute(
                "INSERT INTO defs (doc_id, term, block_hash, block_text, plane_scope_json) VALUES (?,?,?,?,?)",
                (doc_id, d["term"], d["block_hash"], d["block_text"], json.dumps(d["plane_scope"])),
            )

        # D1 + D2: Events — no inference from updated; require explicit start + timezone
        conn.execute("DELETE FROM events WHERE doc_id = ?", (doc_id,))
        raw_events = extract_events(body)

        # D1: type=event header NO LONGER infers start from boh["updated"]
        # All events must come from explicit ## Event: blocks

        potential_events_detected = []
        for ev in raw_events:
            if _validate_event(ev):
                event_id = str(uuid.uuid4())
                start_ts = parse_iso_to_epoch(ev["start"])
                end_ts = parse_iso_to_epoch(ev.get("end"))
                conn.execute(
                    "INSERT INTO events (event_id, doc_id, start_ts, end_ts, timezone, status, confidence) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (event_id, doc_id, start_ts, end_ts, ev["timezone"], "confirmed", 1.0),
                )
            else:
                # D2: Missing start or timezone — log as potential, do not create
                potential_events_detected.append(ev)

        conn.commit()
    finally:
        conn.close()

    result = {
        "path": rel_path,
        "doc_id": doc_id,
        "lint_errors": lint_errors,
        "indexed": True,
        "title": title,
        "topics_tokens": topics_tokens,
    }
    if potential_events_detected:
        result["potential_events_detected"] = potential_events_detected
    return result


def crawl_library(library_root: str) -> dict:
    """Crawl all markdown files under library_root. Returns summary."""
    root = Path(library_root).resolve()
    if not root.exists():
        return {"error": f"Library root does not exist: {library_root}"}

    results = []
    for path in sorted(root.rglob("*.md")):
        if path.name.endswith(".review.md"):
            continue
        result = index_file(path, root)
        results.append(result)

    indexed = [r for r in results if r["indexed"]]
    errors = [r for r in results if r["lint_errors"]]

    return {
        "total_files": len(results),
        "indexed": len(indexed),
        "files_with_lint_errors": len(errors),
        "results": results,
    }
