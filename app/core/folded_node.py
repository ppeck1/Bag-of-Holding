"""Read-only folded-node packets for Atlas document facets."""

from __future__ import annotations

import json
from typing import Any

from app.db import connection as db
from app.core import planar_gate


def _row(row: Any) -> dict[str, Any]:
    return dict(row) if row else {}


def _json(value: Any, default: Any = None) -> Any:
    if value in (None, ""):
        return default if default is not None else {}
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default if default is not None else {}


def _select_existing(columns: list[str], table: str = "docs") -> list[str]:
    existing = {r["name"] for r in db.fetchall(f"PRAGMA table_info({table})")}
    return [c for c in columns if c in existing]


def _safe_fetchall(query: str, params: tuple = ()) -> list[dict[str, Any]]:
    try:
        return [dict(r) for r in db.fetchall(query, params)]
    except Exception:
        return []


def _safe_fetchone(query: str, params: tuple = ()) -> dict[str, Any]:
    try:
        return _row(db.fetchone(query, params))
    except Exception:
        return {}


def _conflict_rows(doc_id: str) -> list[dict[str, Any]]:
    rows = _safe_fetchall(
        "SELECT rowid, * FROM conflicts WHERE doc_ids LIKE ? ORDER BY detected_ts DESC LIMIT 12",
        (f"%{doc_id}%",),
    )
    matched = []
    for r in rows:
        ids = _json(r.get("doc_ids"), [])
        if isinstance(ids, str):
            ids = [ids]
        if doc_id in ids or not ids:
            matched.append(r)
    return matched


def _chunk_rows(doc_id: str) -> list[dict[str, Any]]:
    return _safe_fetchall(
        """SELECT chunk_id, chunk_index, heading_path, byte_start, byte_end,
                  token_start, token_end, source_hash, text_hash, chunk_type,
                  substr(text, 1, 360) AS snippet
           FROM doc_chunks
           WHERE doc_id = ?
           ORDER BY chunk_index ASC
           LIMIT 8""",
        (doc_id,),
    )


def _plane_card(doc_id: str) -> dict[str, Any]:
    card = _safe_fetchone("SELECT * FROM cards WHERE doc_id = ?", (doc_id,))
    if not card:
        return {"present": False, "note": "No PlaneCard has been generated for this document yet."}
    return {
        "present": True,
        "card_id": card.get("id"),
        "plane": card.get("plane"),
        "card_type": card.get("card_type"),
        "topic": card.get("topic"),
        "b": card.get("b"),
        "d": card.get("d"),
        "m": card.get("m"),
        "authority": _json(card.get("authority_json"), {}),
        "constraints": _json(card.get("constraints_json"), {}),
        "context_ref": _json(card.get("context_ref_json"), {}),
        "payload": _json(card.get("payload_json"), {}),
        "valid_until": card.get("valid_until"),
        "updated_ts": card.get("updated_ts"),
    }


def _planar_gate_facet(doc: dict[str, Any], card: dict[str, Any], conflicts: list[dict[str, Any]]) -> dict[str, Any]:
    pack = {
        "id": card.get("card_id") if card.get("present") else f"DOC:{doc.get('doc_id')}",
        "doc_id": doc.get("doc_id"),
        "plane": card.get("plane") or doc.get("canonical_layer") or "informational",
        "chunk_type": "folded_node",
        "authority_state": doc.get("authority_state") or "non_authoritative",
        "payload": {
            "title": doc.get("title") or doc.get("doc_id"),
            "status": doc.get("status"),
            "authority_state": doc.get("authority_state"),
            "canonical_layer": doc.get("canonical_layer"),
            "project": doc.get("project"),
            "non_authoritative": (doc.get("authority_state") not in {"approved", "trusted", "canonical"}),
            "source_trust": "unknown" if doc.get("status") in {"draft", "quarantine"} else "local",
            "object_status": doc.get("status"),
        },
        "authority": card.get("authority") or {"state": doc.get("authority_state") or "non_authoritative"},
        "conflicts": conflicts,
    }
    context, result = planar_gate.evaluate_context_pack(
        query=f"Folded node packet for {doc.get('title') or doc.get('doc_id')}",
        operation="answer_context",
        actor={"actor_type": "system", "actor_id": "atlas_fold", "role": "reader"},
        mode="audit_provenance",
        candidate_packs=[pack],
        governance_health={"conflict_set_ref": "fold_conflicts" if conflicts else None},
    )
    return {"context_pack": context, "gate_result": result}


def build_folded_node_packet(doc_id: str) -> dict[str, Any] | None:
    doc = _row(db.fetchone("SELECT * FROM docs WHERE doc_id = ?", (doc_id,)))
    if not doc:
        return None

    chunks = _chunk_rows(doc_id)
    conflicts = _conflict_rows(doc_id)
    card = _plane_card(doc_id)
    lineage = _safe_fetchall(
        """SELECT id, doc_id, related_doc_id, relationship, detected_ts, detail
           FROM lineage
           WHERE doc_id = ? OR related_doc_id = ?
           ORDER BY detected_ts DESC
           LIMIT 12""",
        (doc_id, doc_id),
    )
    lifecycle_cols = _select_existing(["id", "doc_id", "from_state", "to_state", "event_type", "actor_id", "created_ts", "detail"], "lifecycle_history")
    lifecycle = []
    if lifecycle_cols:
        lifecycle = _safe_fetchall(
            f"SELECT {', '.join(lifecycle_cols)} FROM lifecycle_history WHERE doc_id = ? ORDER BY rowid DESC LIMIT 8",
            (doc_id,),
        )
    audit = _safe_fetchall(
        """SELECT id, event_ts, event_type, actor_type, actor_id, detail
           FROM audit_log
           WHERE doc_id = ?
           ORDER BY event_ts DESC, id DESC
           LIMIT 8""",
        (doc_id,),
    )
    storage_events = _safe_fetchall(
        """SELECT event_id, event_type, subject_type, subject_id, actor_id, plane,
                  card_id, detail_json, created_ts
           FROM storage_events
           WHERE doc_id = ?
           ORDER BY created_ts DESC
           LIMIT 8""",
        (doc_id,),
    )

    packet = {
        "doc_id": doc_id,
        "title": doc.get("title") or doc_id,
        "summary": {
            "highest_risk_state": _highest_risk_state(doc, conflicts),
            "status": doc.get("status"),
            "lifecycle_state": doc.get("operator_state"),
            "authority_state": doc.get("authority_state"),
            "canonical_layer": doc.get("canonical_layer"),
            "project": doc.get("project"),
            "has_conflicts": bool(conflicts),
            "has_plane_card": bool(card.get("present")),
            "chunk_count": len(chunks),
        },
        "facets": {
            "source": {
                "path": doc.get("path"),
                "type": doc.get("type"),
                "source_hash": doc.get("source_hash") or doc.get("text_hash"),
                "text_hash": doc.get("text_hash"),
                "updated_ts": doc.get("updated_ts"),
            },
            "lifecycle": {
                "operator_state": doc.get("operator_state"),
                "operator_intent": doc.get("operator_intent"),
                "history": lifecycle,
            },
            "authority": {
                "authority_state": doc.get("authority_state"),
                "review_state": doc.get("review_state"),
                "canonical_layer": doc.get("canonical_layer"),
                "custodian_review_state": doc.get("custodian_review_state"),
                "status": doc.get("status"),
            },
            "provenance": {
                "lineage": lineage,
                "plane_scope": _json(doc.get("plane_scope_json"), []),
                "field_scope": _json(doc.get("field_scope_json"), []),
                "node_scope": _json(doc.get("node_scope_json"), []),
                "topics": _json(doc.get("topics_json") or doc.get("topics_tokens"), []),
            },
            "conflicts": {"count": len(conflicts), "items": conflicts},
            "chunks": {"count": len(chunks), "items": chunks},
            "plane_card": card,
            "planar_gate": _planar_gate_facet(doc, card, conflicts),
            "audit": {"audit_log": audit, "storage_events": storage_events},
        },
    }
    return packet


def _highest_risk_state(doc: dict[str, Any], conflicts: list[dict[str, Any]]) -> str:
    if conflicts:
        return "conflict"
    if doc.get("status") in {"quarantine", "conflict"}:
        return str(doc.get("status"))
    if doc.get("review_state") in {"needs_review", "pending", "review_required"}:
        return "review_required"
    if doc.get("authority_state") in {"canonical", "trusted", "approved"}:
        return str(doc.get("authority_state"))
    return str(doc.get("status") or doc.get("operator_state") or "unknown")
