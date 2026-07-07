"""Phase 28 actor registry, authority grants, ledger, and attribution."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.db import connection as db


ACTOR_TYPES = {"human", "llm", "system", "importer", "external_contact", "team", "role", "service", "unknown"}
AUTHORITY_RESULTS = {"allowed", "denied", "proposed", "approved", "rejected", "reverted", "escalated", "quarantined", "system_recorded"}
RESTRICTED_ACTIONS = {"promote_canonical", "resolve_governance_state", "mutate_policy", "execute_code", "reset_workspace", "import_contacts"}
DEFAULT_ACTORS = [
    ("boh_system", "BOH System", "system", "seed"),
    ("local_operator", "Local Operator", "human", "seed"),
    ("bulk_importer", "Bulk Importer", "importer", "seed"),
    ("unknown_actor", "Unknown Actor", "unknown", "seed"),
    ("codex", "Codex", "llm", "seed"),
    ("ollama_local", "Ollama Local", "llm", "seed"),
]
_SEEDED_DB_PATH: str | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def ensure_schema_and_seed() -> None:
    global _SEEDED_DB_PATH
    if _SEEDED_DB_PATH == db.DB_PATH:
        return
    now = now_iso()
    for actor_id, display_name, actor_type, source in DEFAULT_ACTORS:
        db.execute(
            """INSERT OR IGNORE INTO actors
               (actor_id, display_name, actor_type, source, active, created_at, updated_at)
               VALUES (?,?,?,?,1,?,?)""",
            (actor_id, display_name, actor_type, source, now, now),
        )
    # Local operator gets bootstrap grants so existing local dev workflows continue.
    for action in sorted(RESTRICTED_ACTIONS | {
        "clean_workspace",
        "seed_fixtures",
        "load_demo_project",
        "verify_protected_route",
        "import_document",
        "edit_document",
        "approve_proposal",
        "reject_proposal",
    }):
        db.execute(
            """INSERT OR IGNORE INTO authority_grants
               (grant_id, actor_id, action, scope_type, scope_id, authority_level,
                constraints_json, granted_by, active, created_at)
               VALUES (?,?,?,?,?,?,?,?,1,?)""",
            (f"grant-bootstrap-local-operator-{action}", "local_operator", action, "global", None,
             "operator", "{}", "boh_system", now),
        )
    _SEEDED_DB_PATH = db.DB_PATH


def get_actor(actor_id: str | None) -> Optional[dict]:
    if not actor_id:
        return None
    ensure_schema_and_seed()
    row = db.fetchone("SELECT * FROM actors WHERE actor_id = ?", (actor_id,))
    return dict(row) if row else None


def resolve_actor(actor_id: str | None = None, fallback: str = "local_operator") -> dict:
    ensure_schema_and_seed()
    actor = get_actor(actor_id)
    if actor:
        return actor
    actor = get_actor(fallback) or get_actor("unknown_actor")
    return actor or {"actor_id": "unknown_actor", "actor_type": "unknown", "display_name": "Unknown Actor"}


def list_actors(actor_type: str | None = None, active: int | None = None) -> list[dict]:
    ensure_schema_and_seed()
    query = "SELECT * FROM actors WHERE 1=1"
    params: list[Any] = []
    if actor_type:
        query += " AND actor_type = ?"
        params.append(actor_type)
    if active is not None:
        query += " AND active = ?"
        params.append(active)
    query += " ORDER BY actor_type, display_name"
    return [dict(r) for r in db.fetchall(query, tuple(params))]


def create_actor(data: dict) -> dict:
    ensure_schema_and_seed()
    actor_id = (data.get("actor_id") or new_id("actor")).strip()
    actor_type = (data.get("actor_type") or "unknown").strip()
    if actor_type not in ACTOR_TYPES:
        raise ValueError(f"actor_type must be one of {sorted(ACTOR_TYPES)}")
    now = now_iso()
    db.execute(
        """INSERT INTO actors
           (actor_id, display_name, actor_type, source, external_ref, email, notes, active, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            actor_id,
            (data.get("display_name") or actor_id).strip(),
            actor_type,
            data.get("source"),
            data.get("external_ref"),
            data.get("email"),
            data.get("notes"),
            1 if data.get("active", True) else 0,
            now,
            now,
        ),
    )
    return get_actor(actor_id) or {}


def update_actor(actor_id: str, data: dict) -> dict:
    ensure_schema_and_seed()
    if not get_actor(actor_id):
        raise KeyError(actor_id)
    allowed = ["display_name", "source", "external_ref", "email", "notes", "active"]
    updates = {k: data[k] for k in allowed if k in data and data[k] is not None}
    if not updates:
        return get_actor(actor_id) or {}
    updates["updated_at"] = now_iso()
    set_clause = ", ".join(f"{k}=?" for k in updates)
    db.execute(f"UPDATE actors SET {set_clause} WHERE actor_id = ?", (*updates.values(), actor_id))
    return get_actor(actor_id) or {}


def add_alias(actor_id: str, alias: str, source: str | None = None) -> dict:
    ensure_schema_and_seed()
    if not get_actor(actor_id):
        raise KeyError(actor_id)
    alias_id = new_id("alias")
    db.execute(
        "INSERT INTO actor_aliases (alias_id, actor_id, alias, source, created_at) VALUES (?,?,?,?,?)",
        (alias_id, actor_id, alias.strip(), source, now_iso()),
    )
    return {"alias_id": alias_id, "actor_id": actor_id, "alias": alias.strip(), "source": source}


def actor_aliases(actor_id: str) -> list[dict]:
    ensure_schema_and_seed()
    return [dict(r) for r in db.fetchall("SELECT * FROM actor_aliases WHERE actor_id = ? ORDER BY created_at DESC", (actor_id,))]


def create_grant(data: dict) -> dict:
    ensure_schema_and_seed()
    if not get_actor(data.get("actor_id")):
        raise ValueError("actor_id does not exist")
    grant_id = data.get("grant_id") or new_id("grant")
    constraints = data.get("constraints_json")
    if constraints is None:
        constraints = {}
    if not isinstance(constraints, str):
        constraints = json.dumps(constraints)
    db.execute(
        """INSERT INTO authority_grants
           (grant_id, actor_id, action, scope_type, scope_id, authority_level, constraints_json,
            granted_by, starts_at, ends_at, active, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            grant_id, data["actor_id"], data["action"], data.get("scope_type") or "global",
            data.get("scope_id"), data.get("authority_level") or "operator", constraints,
            data.get("granted_by"), data.get("starts_at"), data.get("ends_at"),
            1 if data.get("active", True) else 0, now_iso(),
        ),
    )
    return get_grant(grant_id) or {}


def get_grant(grant_id: str) -> Optional[dict]:
    ensure_schema_and_seed()
    row = db.fetchone("SELECT * FROM authority_grants WHERE grant_id = ?", (grant_id,))
    return dict(row) if row else None


def list_grants(actor_id: str | None = None, action: str | None = None,
                scope_type: str | None = None, scope_id: str | None = None) -> list[dict]:
    ensure_schema_and_seed()
    query = "SELECT * FROM authority_grants WHERE 1=1"
    params: list[Any] = []
    for col, value in [("actor_id", actor_id), ("action", action), ("scope_type", scope_type), ("scope_id", scope_id)]:
        if value is not None:
            query += f" AND {col} = ?"
            params.append(value)
    query += " ORDER BY created_at DESC"
    return [dict(r) for r in db.fetchall(query, tuple(params))]


def update_grant(grant_id: str, data: dict) -> dict:
    ensure_schema_and_seed()
    if not get_grant(grant_id):
        raise KeyError(grant_id)
    allowed = ["authority_level", "constraints_json", "starts_at", "ends_at", "active"]
    updates = {k: data[k] for k in allowed if k in data and data[k] is not None}
    if not updates:
        return get_grant(grant_id) or {}
    if "constraints_json" in updates and not isinstance(updates["constraints_json"], str):
        updates["constraints_json"] = json.dumps(updates["constraints_json"])
    set_clause = ", ".join(f"{k}=?" for k in updates)
    db.execute(f"UPDATE authority_grants SET {set_clause} WHERE grant_id = ?", (*updates.values(), grant_id))
    return get_grant(grant_id) or {}


def active_grant_for(actor_id: str, action: str, scope_type: str = "global", scope_id: str | None = None) -> Optional[dict]:
    ensure_schema_and_seed()
    now = now_iso()
    rows = db.fetchall(
        """SELECT * FROM authority_grants
           WHERE actor_id = ? AND action = ? AND active = 1
             AND (scope_type = 'global' OR scope_type = ?)
             AND (scope_id IS NULL OR scope_id = ?)
             AND (starts_at IS NULL OR starts_at <= ?)
             AND (ends_at IS NULL OR ends_at >= ?)
           ORDER BY CASE WHEN scope_id IS NULL THEN 1 ELSE 0 END, created_at DESC""",
        (actor_id, action, scope_type, scope_id, now, now),
    )
    return dict(rows[0]) if rows else None


def evaluate_authority(actor_id: str, action: str, scope_type: str = "global",
                       scope_id: str | None = None, operator_authorized: bool = False) -> tuple[bool, str]:
    grant = active_grant_for(actor_id, action, scope_type, scope_id)
    if grant:
        return True, f"grant:{grant['grant_id']}"
    if action in RESTRICTED_ACTIONS:
        return False, "missing_required_grant"
    if operator_authorized:
        return True, "operator_token_fallback"
    return True, "unrestricted_local_read"


def ledger_event(action: str, target_type: str, target_id: str | None = None,
                 actor_id: str | None = None, authority_result: str = "allowed",
                 authority_basis: str | None = None, project_id: str | None = None,
                 before: Any = None, after: Any = None, request_id: str | None = None,
                 source_route: str | None = None, source_tool: str | None = None,
                 ip_hint: str | None = None, user_agent_hint: str | None = None) -> dict:
    ensure_schema_and_seed()
    actor = resolve_actor(actor_id)
    if authority_result not in AUTHORITY_RESULTS:
        authority_result = "system_recorded"
    event_id = new_id("led")
    db.execute(
        """INSERT INTO action_ledger
           (event_id, actor_id, actor_type, action, target_type, target_id, project_id,
            authority_basis, authority_result, before_json, after_json, request_id,
            source_route, source_tool, ip_hint, user_agent_hint, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            event_id, actor.get("actor_id"), actor.get("actor_type"), action, target_type, target_id,
            project_id, authority_basis, authority_result,
            json.dumps(before) if before is not None else None,
            json.dumps(after) if after is not None else None,
            request_id, source_route, source_tool, ip_hint, user_agent_hint, now_iso(),
        ),
    )
    return get_ledger_event(event_id) or {}


def get_ledger_event(event_id: str) -> Optional[dict]:
    row = db.fetchone("SELECT * FROM action_ledger WHERE event_id = ?", (event_id,))
    return dict(row) if row else None


def recent_ledger(limit: int = 100, actor_id: str | None = None,
                  target_type: str | None = None, target_id: str | None = None) -> list[dict]:
    ensure_schema_and_seed()
    query = "SELECT * FROM action_ledger WHERE 1=1"
    params: list[Any] = []
    for col, value in [("actor_id", actor_id), ("target_type", target_type), ("target_id", target_id)]:
        if value is not None:
            query += f" AND {col} = ?"
            params.append(value)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in db.fetchall(query, tuple(params))]


def assign_responsibility(data: dict) -> dict:
    ensure_schema_and_seed()
    assignment_id = data.get("assignment_id") or new_id("resp")
    now = now_iso()
    db.execute(
        """INSERT INTO responsibility_assignments
           (assignment_id, actor_id, target_type, target_id, responsibility_type,
            scope_type, scope_id, status, assigned_by, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            assignment_id, data["actor_id"], data["target_type"], data["target_id"],
            data["responsibility_type"], data.get("scope_type"), data.get("scope_id"),
            data.get("status") or "active", data.get("assigned_by"), now, now,
        ),
    )
    return get_responsibility(assignment_id) or {}


def get_responsibility(assignment_id: str) -> Optional[dict]:
    row = db.fetchone("SELECT * FROM responsibility_assignments WHERE assignment_id = ?", (assignment_id,))
    return dict(row) if row else None


def list_responsibility(actor_id: str | None = None, target_type: str | None = None,
                        target_id: str | None = None) -> list[dict]:
    ensure_schema_and_seed()
    query = "SELECT * FROM responsibility_assignments WHERE 1=1"
    params: list[Any] = []
    for col, value in [("actor_id", actor_id), ("target_type", target_type), ("target_id", target_id)]:
        if value is not None:
            query += f" AND {col} = ?"
            params.append(value)
    query += " ORDER BY created_at DESC"
    return [dict(r) for r in db.fetchall(query, tuple(params))]


def add_document_attribution(doc_id: str, attribution_type: str, actor_id: str | None,
                             confidence: float | None = 1.0, source: str | None = None,
                             evidence: Any = None) -> dict:
    ensure_schema_and_seed()
    actor = resolve_actor(actor_id)
    attribution_id = new_id("attr")
    db.execute(
        """INSERT INTO document_attribution
           (attribution_id, doc_id, actor_id, attribution_type, confidence, source, evidence_json, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            attribution_id, doc_id, actor.get("actor_id"), attribution_type,
            confidence, source, json.dumps(evidence) if evidence is not None else None, now_iso(),
        ),
    )
    return get_document_attribution(doc_id)[0]


def get_document_attribution(doc_id: str) -> list[dict]:
    ensure_schema_and_seed()
    rows = db.fetchall(
        """SELECT da.*, a.display_name, a.actor_type
           FROM document_attribution da
           LEFT JOIN actors a ON da.actor_id = a.actor_id
           WHERE da.doc_id = ?
           ORDER BY da.created_at DESC""",
        (doc_id,),
    )
    return [dict(r) for r in rows]


def actor_from_env_or_header(header_actor: str | None = None, default: str = "local_operator") -> str:
    return (header_actor or os.environ.get("BOH_DEFAULT_ACTOR") or default).strip() or default
