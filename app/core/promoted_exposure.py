"""Shared promoted-document exposure control (WO-2 bridge; leak-proof by default).

Promoted intake-derived docs carry ``corpus_class = 'CORPUS_CLASS:PROMOTED_INTAKE'`` (set
explicitly by the promotion service, never by the classifier). Every consumer that enumerates
docs for user-facing output excludes them through THIS module so default-off is enforced in one
place, not per-route if-statements.

Dual gate (roadmap §5 / DEC-0004): promoted docs surface on ``/api/retrieve`` only when BOTH the
server env gate ``BOH_RETRIEVAL_INCLUDE_PROMOTED`` (default off) AND the per-request
``include_promoted`` flag (default false) are on. All other read surfaces are env-gate-only.
"""

from __future__ import annotations

import os
from typing import Any, Iterable

PROMOTED_CORPUS_CLASS = "CORPUS_CLASS:PROMOTED_INTAKE"

# Structured fail-closed reason for ORDINARY mutations of promoted managed documents.
# Mutation isolation is gate-independent: only governed promote()/demote()/supersession may
# mutate promoted managed-document state, even when the read-exposure gate is open.
MUTATION_BLOCK_REASON = "promoted_intake_managed_document"


def env_gate_open() -> bool:
    return os.environ.get("BOH_RETRIEVAL_INCLUDE_PROMOTED", "false").lower() == "true"


def visible(include_promoted_request: bool = False) -> bool:
    """Retrieval dual gate: server env AND request flag must both be open."""
    return env_gate_open() and bool(include_promoted_request)


def exclusion_sql(alias: str = "d", *, show_promoted: bool = False) -> str:
    """SQL fragment (leading ' AND ') excluding promoted docs unless visibility is granted.

    NULL-safe: rows with NULL corpus_class are never excluded by this predicate.
    """
    if show_promoted:
        return ""
    col = f"{alias}.corpus_class" if alias else "corpus_class"
    return f" AND ({col} IS NULL OR {col} <> '{PROMOTED_CORPUS_CLASS}')"


def is_promoted_row(row: Any) -> bool:
    try:
        value = row.get("corpus_class") if isinstance(row, dict) else row["corpus_class"]
    except (KeyError, IndexError, TypeError):
        return False
    return value == PROMOTED_CORPUS_CLASS


def filter_rows(rows: Iterable[Any], *, show_promoted: bool = False) -> list[Any]:
    if show_promoted:
        return list(rows)
    return [r for r in rows if not is_promoted_row(r)]


def is_promoted_doc_id(doc_id: str | None) -> bool:
    """DB-backed check for MUTATION guards (gate-independent, fail-closed on lookup error
    only in the permissive direction: an unknown doc is not promoted)."""
    if not doc_id:
        return False
    from app.db import connection as db
    try:
        row = db.fetchone("SELECT corpus_class FROM docs WHERE doc_id = ?", (doc_id,))
    except Exception:
        return False
    return bool(row) and row.get("corpus_class") == PROMOTED_CORPUS_CLASS
