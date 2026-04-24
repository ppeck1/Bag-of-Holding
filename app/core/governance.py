"""app/core/governance.py: Workspace policy and DCNS authority layer for Bag of Holding v2.

Phase 10 addition. Manages workspace access policies and system-level DCNS edges.

Policy model:
  - Workspaces are directory paths or logical names
  - Entities: 'human' | 'model' | 'system'
  - Permissions: read, write, execute, propose, promote
  - Canon protection: models cannot promote; can_promote defaults False for models
  - Wildcard entity_id '*' applies to all of that entity_type

System edges extend DCNS beyond documents:
  - may-read, may-write, may-execute, may-propose, may-promote
  - derives-from, depends-on, promoted-to, conflicts-with
  - Source/target types: doc, workspace, model, tool, role
"""

import json
import time
from typing import Optional

from app.db import connection as db
from app.core import audit


PERMISSION_FIELDS = ("can_read", "can_write", "can_execute", "can_propose", "can_promote")

# Map from system_edge edge_type to workspace_policies permission column
EDGE_TO_PERMISSION = {
    "may-read":    "can_read",
    "may-write":   "can_write",
    "may-execute": "can_execute",
    "may-propose": "can_propose",
    "may-promote": "can_promote",
}

PERMISSION_TO_EDGE = {v: k for k, v in EDGE_TO_PERMISSION.items()}

# Default permissions by entity type
DEFAULTS = {
    "human":  {"can_read": 1, "can_write": 1, "can_execute": 1, "can_propose": 1, "can_promote": 1},
    "model":  {"can_read": 1, "can_write": 0, "can_execute": 0, "can_propose": 1, "can_promote": 0},
    "system": {"can_read": 1, "can_write": 1, "can_execute": 1, "can_propose": 1, "can_promote": 0},
}

VALID_EDGE_TYPES = {
    "may-read", "may-write", "may-execute", "may-propose", "may-promote",
    "derives-from", "depends-on", "promoted-to", "conflicts-with",
}

VALID_NODE_TYPES = {"doc", "workspace", "model", "tool", "role"}


# ── Policy CRUD ───────────────────────────────────────────────────────────────

def get_policy(workspace: str, entity_type: str,
               entity_id: str = "*") -> dict | None:
    """Fetch the specific policy row, or None if not set."""
    return db.fetchone(
        "SELECT * FROM workspace_policies WHERE workspace=? AND entity_type=? AND entity_id=?",
        (workspace, entity_type, entity_id),
    )


def _effective_from_system_edges(workspace: str, entity_type: str,
                                  entity_id: str) -> dict | None:
    """Derive permissions from system_edges if no policy row exists.

    Looks for: source=(entity_type, entity_id) → target=(workspace, workspace)
    edge_types: may-read, may-write, may-execute, may-propose, may-promote

    Returns a permissions dict if any edges found, else None.
    This is the convergence point between system_edges and workspace_policies.
    """
    # Match by specific entity_id or wildcard entity_id '*'
    rows = db.fetchall(
        """
        SELECT edge_type FROM system_edges
        WHERE source_type = ?
          AND source_id IN (?, '*')
          AND target_type = 'workspace'
          AND target_id = ?
          AND edge_type IN ('may-read','may-write','may-execute','may-propose','may-promote')
        """,
        (entity_type, entity_id, workspace),
    )
    if not rows:
        return None

    # Build permissions from edges (presence of edge = permission granted)
    granted = {row["edge_type"] for row in rows}
    return {
        "workspace":   workspace,
        "entity_type": entity_type,
        "entity_id":   entity_id,
        "note":        "derived from system_edges",
        "can_read":    1 if "may-read"    in granted else 0,
        "can_write":   1 if "may-write"   in granted else 0,
        "can_execute": 1 if "may-execute" in granted else 0,
        "can_propose": 1 if "may-propose" in granted else 0,
        "can_promote": 1 if "may-promote" in granted else 0,
    }


def get_effective_policy(workspace: str, entity_type: str,
                          entity_id: str = "*") -> dict:
    """Return the effective permissions for an entity on a workspace.

    Resolution order (first match wins):
      1. Specific policy row (workspace, entity_type, entity_id)
      2. Wildcard policy row (workspace, entity_type, '*')
      3. system_edges: may-* edges for (entity_type, entity_id) → workspace
      4. system_edges: may-* edges for (entity_type, '*') → workspace
      5. System defaults by entity_type

    This is the authority convergence point — both policy rows and DCNS edges
    can grant access; explicit policy rows always take precedence.
    """
    # 1. Specific policy row
    specific = db.fetchone(
        "SELECT * FROM workspace_policies "
        "WHERE workspace=? AND entity_type=? AND entity_id=?",
        (workspace, entity_type, entity_id),
    )
    if specific:
        return {**specific, "_source": "policy:specific"}

    # 2. Wildcard policy row
    wildcard = db.fetchone(
        "SELECT * FROM workspace_policies "
        "WHERE workspace=? AND entity_type=? AND entity_id='*'",
        (workspace, entity_type),
    )
    if wildcard:
        return {**wildcard, "_source": "policy:wildcard"}

    # 3. system_edges for specific entity
    edge_specific = _effective_from_system_edges(workspace, entity_type, entity_id)
    if edge_specific:
        return {**edge_specific, "_source": "edge:specific"}

    # 4. system_edges for wildcard ('*')
    edge_wildcard = _effective_from_system_edges(workspace, entity_type, "*")
    if edge_wildcard:
        return {**edge_wildcard, "_source": "edge:wildcard"}

    # 5. System default
    defaults = DEFAULTS.get(entity_type, DEFAULTS["system"])
    return {
        "workspace":   workspace,
        "entity_type": entity_type,
        "entity_id":   "*",
        "note":        "system default",
        "_source":     "default",
        **defaults,
    }


def upsert_policy(workspace: str, entity_type: str, entity_id: str = "*",
                  can_read: int = 1, can_write: int = 0,
                  can_execute: int = 0, can_propose: int = 1,
                  can_promote: int = 0, note: str = "") -> dict:
    """Create or replace a workspace policy.

    Also syncs the granted permissions into system_edges so the DCNS graph
    reflects the same authority structure as the policy table.
    """
    if entity_type == "model" and can_promote:
        raise ValueError("Models cannot be granted promotion rights. Canon remains human-gated.")

    now = int(time.time())
    conn = db.get_conn()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO workspace_policies
              (workspace, entity_type, entity_id, can_read, can_write,
               can_execute, can_propose, can_promote, note, created_ts)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (workspace, entity_type, entity_id, can_read, can_write,
             can_execute, can_propose, can_promote, note, now),
        )
        conn.commit()
    finally:
        conn.close()

    # Sync granted permissions into system_edges for DCNS coherence
    _sync_policy_to_edges(workspace, entity_type, entity_id,
                          can_read, can_write, can_execute,
                          can_propose, can_promote)

    audit.log_event(
        event_type="policy",
        actor_type="human",
        workspace=workspace,
        detail=json.dumps({
            "entity_type": entity_type, "entity_id": entity_id,
            "can_write": can_write, "can_promote": can_promote,
        }),
    )
    return get_effective_policy(workspace, entity_type, entity_id)


def _sync_policy_to_edges(workspace: str, entity_type: str, entity_id: str,
                           can_read: int, can_write: int, can_execute: int,
                           can_propose: int, can_promote: int) -> None:
    """Sync a policy row into system_edges. Called automatically by upsert_policy.

    Granted permissions become may-* edges; denied permissions are not recorded.
    This keeps the DCNS graph coherent with the policy table without duplication.
    """
    permission_map = {
        "may-read":    can_read,
        "may-write":   can_write,
        "may-execute": can_execute,
        "may-propose": can_propose,
        "may-promote": can_promote,
    }
    now = int(time.time())
    conn = db.get_conn()
    try:
        for edge_type, granted in permission_map.items():
            if granted:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO system_edges
                      (source_type, source_id, target_type, target_id,
                       edge_type, state, detail, created_ts)
                    VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (entity_type, entity_id, "workspace", workspace,
                     edge_type, 1,
                     json.dumps({"synced_from": "workspace_policies"}),
                     now),
                )
            else:
                # Remove revoked edge if present
                conn.execute(
                    "DELETE FROM system_edges "
                    "WHERE source_type=? AND source_id=? "
                    "AND target_type='workspace' AND target_id=? AND edge_type=?",
                    (entity_type, entity_id, workspace, edge_type),
                )
        conn.commit()
    finally:
        conn.close()


def list_policies(workspace: Optional[str] = None) -> list[dict]:
    """List all policies, optionally filtered by workspace."""
    if workspace:
        return db.fetchall(
            "SELECT * FROM workspace_policies WHERE workspace=? ORDER BY workspace, entity_type",
            (workspace,),
        )
    return db.fetchall(
        "SELECT * FROM workspace_policies ORDER BY workspace, entity_type"
    )


def check_permission(workspace: str, entity_type: str,
                     permission: str, entity_id: str = "*") -> dict:
    """Check whether an entity has a specific permission on a workspace.

    Returns {allowed: bool, reason: str, source: str, policy: dict}

    source tells you where the permission came from:
      'policy:specific' | 'policy:wildcard' | 'edge:specific' | 'edge:wildcard' | 'default'
    """
    if permission not in PERMISSION_FIELDS:
        return {"allowed": False, "reason": f"Unknown permission: {permission}",
                "source": "error", "policy": {}}

    # Canon protection hardcoded: models never get can_promote
    if permission == "can_promote" and entity_type == "model":
        return {
            "allowed": False,
            "reason":  "Canon protection: models cannot promote documents. Human action required.",
            "source":  "hardcoded",
            "policy":  {},
        }

    policy = get_effective_policy(workspace, entity_type, entity_id)
    allowed = bool(policy.get(permission, 0))
    source  = policy.get("_source", "unknown")
    reason  = (
        f"Allowed via {source}"
        if allowed else
        f"Denied: {permission}=0 for {entity_type}:{entity_id} on {workspace} (source: {source})"
    )
    return {"allowed": allowed, "reason": reason, "source": source, "policy": policy}


# ── System edge CRUD ──────────────────────────────────────────────────────────

def add_system_edge(source_type: str, source_id: str,
                    target_type: str, target_id: str,
                    edge_type: str,
                    state: Optional[int] = None,
                    detail: Optional[str] = None) -> dict:
    """Add a DCNS-style authority/flow edge between any system node types."""
    if source_type not in VALID_NODE_TYPES:
        raise ValueError(f"Invalid source_type: {source_type}")
    if target_type not in VALID_NODE_TYPES:
        raise ValueError(f"Invalid target_type: {target_type}")
    if edge_type not in VALID_EDGE_TYPES:
        raise ValueError(f"Invalid edge_type: {edge_type}")

    now = int(time.time())
    conn = db.get_conn()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO system_edges
              (source_type, source_id, target_type, target_id,
               edge_type, state, detail, created_ts)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (source_type, source_id, target_type, target_id,
             edge_type, state, detail, now),
        )
        conn.commit()
    finally:
        conn.close()
    return get_system_edges(source_type, source_id, edge_type=edge_type)[0]


def get_system_edges(source_type: Optional[str] = None,
                     source_id: Optional[str] = None,
                     target_type: Optional[str] = None,
                     target_id: Optional[str] = None,
                     edge_type: Optional[str] = None) -> list[dict]:
    """Query system edges with optional filters."""
    query = "SELECT * FROM system_edges WHERE 1=1"
    params: list = []
    if source_type:
        query += " AND source_type=?"; params.append(source_type)
    if source_id:
        query += " AND source_id=?"; params.append(source_id)
    if target_type:
        query += " AND target_type=?"; params.append(target_type)
    if target_id:
        query += " AND target_id=?"; params.append(target_id)
    if edge_type:
        query += " AND edge_type=?"; params.append(edge_type)
    query += " ORDER BY created_ts DESC"
    return db.fetchall(query, tuple(params))


def what_can_access(target_type: str, target_id: str) -> dict:
    """Return all entities that have any access edge to a target."""
    edges = get_system_edges(target_type=target_type, target_id=target_id)
    return {
        "target": {"type": target_type, "id": target_id},
        "edges": edges,
        "count": len(edges),
    }


def promotion_path(doc_id: str) -> list[dict]:
    """Return the promotion lineage chain for a document."""
    return get_system_edges(source_type="doc", source_id=doc_id,
                            edge_type="promoted-to")
