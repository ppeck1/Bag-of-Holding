"""Read-only doc-to-domain linkage helpers for Fold domain aggregation.

The current repository has no persistent doc-domain join table. This module
therefore resolves domain membership deterministically from existing read-model
surfaces only: registered substrate domains plus indexed document/PlaneCard
topic tokens. It never writes and never creates new domain facts.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.db import connection as db


def normalize_domain(value: Any) -> str:
    """Normalize domain labels the same way topic tokens are normalized."""
    return " ".join(str(value or "").strip().lower().split())


def registered_domains() -> tuple[str, ...]:
    """Return distinct non-blank registered substrate domain values."""
    rows = db.fetchall(
        """SELECT DISTINCT domain FROM substrate_lattice_registry
           WHERE NULLIF(TRIM(domain), '') IS NOT NULL"""
    )
    domains = {normalize_domain(r["domain"]) for r in rows if normalize_domain(r["domain"])}
    return tuple(sorted(domains))


def _json_loads(value: Any, default: Any = None) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def _tokenize(value: Any, *, include_whole: bool = False) -> set[str]:
    """Extract normalized topic/domain tokens from a string or list.

    For list-like sources, each item is an explicit topic. For free text sources
    such as PlaneCard.topic, the whole normalized value and its whitespace/punct
    tokens are both useful because manual cards often use a short domain label
    as the topic.
    """
    out: set[str] = set()
    if value in (None, ""):
        return out
    if isinstance(value, (list, tuple, set)):
        for item in value:
            out.update(_tokenize(item, include_whole=True))
        return out
    text = normalize_domain(value)
    if not text:
        return out
    if include_whole:
        out.add(text)
    out.update(t for t in re.split(r"[\s,;|/]+", text) if t)
    return out


def _payload_topics(payload_json: Any) -> set[str]:
    payload = _json_loads(payload_json, {})
    if not isinstance(payload, dict):
        return set()
    topics = payload.get("topics")
    if topics is None:
        return set()
    parsed = _json_loads(topics, None) if isinstance(topics, str) else topics
    if parsed is not None:
        return _tokenize(parsed, include_whole=False)
    return _tokenize(topics, include_whole=False)


def domains_for_doc(doc_id: str, registered: tuple[str, ...] | None = None) -> tuple[str, ...]:
    """Resolve registered domains for one doc from existing topic surfaces."""
    if registered is None:
        registered = registered_domains()
    if not registered:
        return ()

    observed: set[str] = set()
    doc = db.fetchone("SELECT topics_tokens, title, path FROM docs WHERE doc_id = ?", (doc_id,))
    if doc:
        observed.update(_tokenize(doc["topics_tokens"], include_whole=False))

    cards = db.fetchall(
        "SELECT topic, payload_json FROM cards WHERE doc_id = ? ORDER BY id",
        (doc_id,),
    )
    for card in cards:
        observed.update(_tokenize(card["topic"], include_whole=True))
        observed.update(_payload_topics(card["payload_json"]))

    matched = [domain for domain in registered if domain in observed]
    return tuple(sorted(set(matched)))


def doc_domain_map() -> dict[str, tuple[str, ...]]:
    """Resolve registered domains for every indexed doc."""
    registered = registered_domains()
    rows = db.fetchall("SELECT doc_id FROM docs ORDER BY doc_id")
    return {
        row["doc_id"]: domains_for_doc(row["doc_id"], registered)
        for row in rows
        if row["doc_id"]
    }
