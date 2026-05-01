"""app/core/lattice_graph.py: Constraint-native lattice graph runtime.

Phase 22: stop treating Plane Cards as documents with metadata.

Frozen grammar mapping:
  Constraint -> node
  State      -> active subgraph
  Flow       -> traversal

This module provides a conservative runtime graph over existing PlaneCards plus
explicit lattice edges. It does not automate mutations; it exposes diagnostic
queries that are auditable and deterministic.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any

from app.db import connection as db
from app.core.plane_card import PlaneCard, get_card, get_card_for_doc, list_cards, upsert_card

REQUIRED_EDGE_RELATIONS: set[str] = {
    "enables",
    "limits",
    "bounds",
    "depends_on",
    "conflicts_with",
    "stabilizes",
    "destabilizes",
    "routes_to",
}

VALID_NODE_TYPES: set[str] = {
    "constraint",
    "claim",
    "evidence",
    "observation",
    "review",
    "reference",
    "import",
}

STATUS_ACTIVE = {"active", "draft", "approved", "canonical", "review_required", "contained"}


@dataclass
class LatticeNode:
    id: str
    type: str
    target: str
    status: str
    mode: str | None
    q_quality: float | None
    c_confidence: float | None
    valid_until: str | None
    context_refs: list[str] = field(default_factory=list)
    plane: str = "Internal"
    authority_plane: str = "verification"
    card_id: str | None = None
    doc_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LatticeEdge:
    edge_id: str
    source_id: str
    target_id: str
    relation: str
    weight: float = 1.0
    status: str = "active"
    created_at: str | None = None
    created_by: str = "human"
    reversible: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _iso_to_epoch(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        try:
            return float(value)
        except Exception:
            return None


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _context_refs(card: PlaneCard) -> list[str]:
    refs: list[str] = []
    context = card.context_ref or {}
    for key in ("source_id", "path", "project"):
        value = context.get(key)
        if value:
            refs.append(str(value))
    payload = card.payload or {}
    if payload.get("path") and str(payload["path"]) not in refs:
        refs.append(str(payload["path"]))
    return refs


def _authority_plane(card: PlaneCard, doc: dict[str, Any] | None = None) -> str:
    auth = card.authority or {}
    explicit = auth.get("authority_plane") or (doc or {}).get("authority_plane")
    if explicit:
        return str(explicit).lower()
    plane = (card.plane or "").lower()
    if plane == "canonical":
        return "constitutional"
    if plane == "evidence":
        return "verification"
    if plane in {"review", "conflict"}:
        return "governance"
    return "verification"


def node_from_card(card: PlaneCard) -> LatticeNode:
    doc = db.fetchone("SELECT * FROM docs WHERE doc_id=?", (card.doc_id,)) if card.doc_id else None
    docd = dict(doc) if doc else {}
    payload = card.payload or {}
    constraints = card.constraints or {}
    # Phase 22: every card becomes a lattice node; constraint-bearing cards are
    # typed as constraint when their header declares hard boundaries.
    node_type = "constraint" if constraints else (card.card_type or "observation")
    if node_type not in VALID_NODE_TYPES:
        node_type = "constraint" if constraints else "observation"
    q = _safe_float(payload.get("epistemic_q") if payload else None, _safe_float(docd.get("epistemic_q")))
    c = _safe_float(payload.get("epistemic_c") if payload else None, _safe_float(docd.get("epistemic_c")))
    status = str(payload.get("status") or docd.get("status") or "active")
    return LatticeNode(
        id=f"NODE:{card.id}",
        type=node_type,
        target=card.topic or payload.get("title") or card.doc_id or card.id,
        status=status,
        mode=card.m,
        q_quality=q,
        c_confidence=c,
        valid_until=card.valid_until or docd.get("epistemic_valid_until"),
        context_refs=_context_refs(card),
        plane=card.plane,
        authority_plane=_authority_plane(card, docd),
        card_id=card.id,
        doc_id=card.doc_id,
        metadata={
            "d": card.d,
            "b": card.b,
            "constraints": constraints,
            "payload": payload,
            "canonical_layer": payload.get("canonical_layer") or docd.get("canonical_layer"),
            "correction_status": payload.get("correction_status") or docd.get("epistemic_correction_status"),
        },
    )


def get_node(node_or_card_id: str) -> LatticeNode | None:
    ident = node_or_card_id
    if ident.startswith("NODE:"):
        ident = ident[5:]
    if ident.startswith("CARD:"):
        card = get_card(ident)
    else:
        card = get_card_for_doc(ident)
    return node_from_card(card) if card else None


def list_nodes(
    plane: str | None = None,
    node_type: str | None = None,
    active_only: bool = False,
    limit: int = 200,
    offset: int = 0,
) -> list[LatticeNode]:
    cards = list_cards(plane=plane, limit=limit, offset=offset)
    nodes = [node_from_card(c) for c in cards]
    if node_type:
        nodes = [n for n in nodes if n.type == node_type]
    if active_only:
        nodes = [n for n in nodes if (n.status or "").lower() in STATUS_ACTIVE]
    return nodes


def _edge_id(source_id: str, target_id: str, relation: str) -> str:
    import hashlib
    raw = f"{source_id}|{target_id}|{relation}".encode()
    return "EDGE_" + hashlib.sha1(raw).hexdigest()[:12]


def create_edge(
    source_id: str,
    target_id: str,
    relation: str,
    weight: float = 1.0,
    created_by: str = "human",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    relation = relation.strip().lower()
    errors: list[str] = []
    if relation not in REQUIRED_EDGE_RELATIONS:
        errors.append(f"relation must be one of {sorted(REQUIRED_EDGE_RELATIONS)}")
    if not get_node(source_id):
        errors.append(f"source node not found: {source_id}")
    if not get_node(target_id):
        errors.append(f"target node not found: {target_id}")
    if errors:
        return {"ok": False, "errors": errors}
    sid = source_id if source_id.startswith("NODE:") else f"NODE:{source_id}"
    tid = target_id if target_id.startswith("NODE:") else f"NODE:{target_id}"
    edge_id = _edge_id(sid, tid, relation)
    now = _now_iso()
    db.execute(
        """
        INSERT OR REPLACE INTO lattice_edges
          (edge_id, source_id, target_id, relation, weight, status, created_at, created_by, reversible, metadata_json)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (edge_id, sid, tid, relation, float(weight), "active", now, created_by, 1, json.dumps(metadata or {})),
    )
    return {"ok": True, "edge_id": edge_id, "edge": get_edge(edge_id)}


def _row_to_edge(row: dict[str, Any]) -> LatticeEdge:
    return LatticeEdge(
        edge_id=row["edge_id"],
        source_id=row["source_id"],
        target_id=row["target_id"],
        relation=row["relation"],
        weight=float(row["weight"] or 0),
        status=row["status"],
        created_at=row["created_at"],
        created_by=row["created_by"] or "human",
        reversible=bool(row["reversible"]),
        metadata=_json_loads(row.get("metadata_json"), {}),
    )


def get_edge(edge_id: str) -> dict[str, Any] | None:
    row = db.fetchone("SELECT * FROM lattice_edges WHERE edge_id=?", (edge_id,))
    return _row_to_edge(dict(row)).to_dict() if row else None


def list_edges(node_id: str | None = None, relation: str | None = None, active_only: bool = True) -> list[dict[str, Any]]:
    q = "SELECT * FROM lattice_edges"
    params: list[Any] = []
    wheres: list[str] = []
    if node_id:
        nid = node_id if node_id.startswith("NODE:") else f"NODE:{node_id}"
        wheres.append("(source_id=? OR target_id=?)")
        params.extend([nid, nid])
    if relation:
        wheres.append("relation=?")
        params.append(relation.strip().lower())
    if active_only:
        wheres.append("status='active'")
    if wheres:
        q += " WHERE " + " AND ".join(wheres)
    q += " ORDER BY created_at DESC"
    return [_row_to_edge(dict(r)).to_dict() for r in db.fetchall(q, tuple(params))]


def active_subgraph(plane: str | None = None) -> dict[str, Any]:
    nodes = list_nodes(plane=plane, active_only=True, limit=500)
    node_ids = {n.id for n in nodes}
    edges = [e for e in list_edges(active_only=True) if e["source_id"] in node_ids and e["target_id"] in node_ids]
    return {"nodes": [n.to_dict() for n in nodes], "edges": edges, "count": {"nodes": len(nodes), "edges": len(edges)}}


def traverse_flow(start_node_id: str, max_depth: int = 4) -> dict[str, Any]:
    start = get_node(start_node_id)
    if not start:
        return {"ok": False, "errors": [f"start node not found: {start_node_id}"]}
    start_id = start.id
    visited = {start_id}
    frontier = [(start_id, 0)]
    paths: list[dict[str, Any]] = []
    while frontier:
        node_id, depth = frontier.pop(0)
        if depth >= max_depth:
            continue
        outgoing = [e for e in list_edges(node_id=node_id) if e["source_id"] == node_id]
        for e in outgoing:
            nxt = e["target_id"]
            paths.append({"from": node_id, "to": nxt, "relation": e["relation"], "weight": e["weight"], "depth": depth + 1})
            if nxt not in visited:
                visited.add(nxt)
                frontier.append((nxt, depth + 1))
    nodes = [get_node(n) for n in visited]
    return {"ok": True, "start": start_id, "nodes": [n.to_dict() for n in nodes if n], "flow": paths}


def _incoming_weight(node_id: str, relations: set[str] | None = None) -> float:
    edges = list_edges(node_id=node_id)
    total = 0.0
    for e in edges:
        if e["target_id"] == node_id and (relations is None or e["relation"] in relations):
            total += abs(float(e.get("weight") or 0))
    return total


def _explain_load_bearing(n: "LatticeNode", incoming: float, score: float) -> dict[str, str]:
    """P6: Human-readable explanation for a load-bearing constraint result."""
    q = n.q_quality if n.q_quality is not None else 0.5
    c = n.c_confidence if n.c_confidence is not None else 0.5
    reasons: list[str] = []
    if incoming > 2.0:
        reasons.append(f"high incoming dependency weight ({incoming:.2f})")
    if q < 0.5:
        reasons.append(f"low epistemic quality (q={q:.2f})")
    if c < 0.5:
        reasons.append(f"low confidence (c={c:.2f})")
    if not reasons:
        reasons.append("moderate dependency load relative to peers")
    return {
        "why_flagged": "; ".join(reasons),
        "what_constraint_is_load_bearing": (
            f"Node '{n.target}' (plane: {n.plane}) is load-bearing because "
            f"{'; '.join(reasons)}."
        ),
        "what_breaks_next": (
            "If this constraint fails, all nodes with depends_on, bounds, limits, or "
            "stabilizes edges pointing here lose their governing constraint. "
            "Review downstream nodes via /api/lattice/flow/{node_id}."
        ),
        "what_intervention_changes_state": (
            "Raise q/c scores through evidence review, reduce incoming dependency weight "
            "by splitting the constraint, or harden with a certificate-backed plane interface."
        ),
    }


def query_load_bearing_constraints(limit: int = 10) -> list[dict[str, Any]]:
    nodes = list_nodes(node_type="constraint", active_only=True, limit=500)
    out: list[dict[str, Any]] = []
    for n in nodes:
        incoming = _incoming_weight(n.id, {"depends_on", "bounds", "limits", "stabilizes"})
        q = n.q_quality if n.q_quality is not None else 0.5
        c = n.c_confidence if n.c_confidence is not None else 0.5
        score = incoming + (1.0 - q) * 0.5 + (1.0 - c) * 0.5
        out.append({
            "node": n.to_dict(),
            "load_bearing_score": round(score, 4),
            "incoming_constraint_weight": incoming,
            **_explain_load_bearing(n, incoming, score),
        })
    return sorted(out, key=lambda x: x["load_bearing_score"], reverse=True)[:limit]


def query_intervention_expands_feasibility(limit: int = 10) -> list[dict[str, Any]]:
    nodes = list_nodes(active_only=True, limit=500)
    candidates: list[dict[str, Any]] = []
    for n in nodes:
        q = n.q_quality if n.q_quality is not None else 0.5
        c = n.c_confidence if n.c_confidence is not None else 0.5
        stale_penalty = 1.0 if _is_stale(n) else 0.0
        constraint_load = _incoming_weight(n.id, {"limits", "bounds", "conflicts_with", "destabilizes"})
        score = (1.0 - q) + (1.0 - c) + stale_penalty + constraint_load
        if score > 0:
            # P6: human-readable explanation per result
            reasons: list[str] = []
            if stale_penalty:
                reasons.append("valid_until elapsed (stale)")
            if q < 0.6:
                reasons.append(f"low quality (q={q:.2f})")
            if c < 0.6:
                reasons.append(f"low confidence (c={c:.2f})")
            if constraint_load > 1.0:
                reasons.append(f"high constraint load ({constraint_load:.2f})")
            intervention = "refresh_or_review" if stale_penalty else "reduce_constraint_load"
            candidates.append({
                "node": n.to_dict(),
                "feasibility_gain_score": round(score, 4),
                "recommended_intervention_type": intervention,
                "why_flagged": "; ".join(reasons) if reasons else "moderate degradation relative to peers",
                "what_constraint_is_load_bearing": (
                    f"Node '{n.target}' has degraded quality or stale truth that is "
                    f"limiting the system's feasibility envelope."
                ),
                "what_breaks_next": (
                    "Downstream flows relying on this node may route through stale or "
                    "low-confidence constraints, producing unreliable governance outcomes."
                ),
                "what_intervention_changes_state": (
                    f"Recommended: {intervention.replace('_', ' ')}. "
                    "Either refresh via a bounded evidence review, or relieve constraint "
                    "load by splitting or hardening the boundary."
                ),
            })
    return sorted(candidates, key=lambda x: x["feasibility_gain_score"], reverse=True)[:limit]


def query_harm_flow(start_node_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    harmful = {"depends_on", "conflicts_with", "destabilizes", "routes_to", "limits"}
    edges = list_edges(node_id=start_node_id, active_only=True) if start_node_id else list_edges(active_only=True)
    flows = []
    for e in edges:
        if e["relation"] in harmful:
            relation = e["relation"]
            # P6: per-relation harm explanation
            if relation == "conflicts_with":
                what_breaks = "These two nodes are in active conflict. A resolution failure here propagates as contradictory authority."
            elif relation == "destabilizes":
                what_breaks = "The source is actively undermining the target's stability. Failure here cascades into the target's dependent subgraph."
            elif relation == "depends_on":
                what_breaks = "The source requires the target to hold. If the target is revoked or decays, the source loses its governing constraint."
            elif relation == "limits":
                what_breaks = "The source constrains the target's operational boundary. Failure relaxes a hard limit with unknown downstream effects."
            else:
                what_breaks = "Flow disruption here propagates along routes_to edges to downstream nodes."
            flows.append({
                "from": e["source_id"],
                "to": e["target_id"],
                "relation": relation,
                "harm_flow_weight": abs(float(e.get("weight") or 0)),
                "why_flagged": f"Relation '{relation}' carries failure propagation risk.",
                "what_breaks_next": what_breaks,
                "what_intervention_changes_state": (
                    "Add a stabilizes edge from a high-confidence node, reduce edge weight "
                    "via dampening feedback, or resolve the conflict with a certificate-backed "
                    "plane interface."
                ),
            })
    return sorted(flows, key=lambda x: x["harm_flow_weight"], reverse=True)[:limit]


def _is_stale(n: LatticeNode) -> bool:
    exp = _iso_to_epoch(n.valid_until)
    return exp is not None and exp < time.time()


def query_stale_truths(limit: int = 50) -> list[dict[str, Any]]:
    stale = []
    for n in list_nodes(active_only=False, limit=500):
        if _is_stale(n):
            stale.append({"node": n.to_dict(), "stale_reason": "valid_until elapsed"})
    return stale[:limit]


def query_collapsing_planes() -> list[dict[str, Any]]:
    nodes = list_nodes(active_only=False, limit=1000)
    by_plane: dict[str, list[LatticeNode]] = {}
    for n in nodes:
        by_plane.setdefault(n.plane or "Unknown", []).append(n)
    results = []
    for plane, items in by_plane.items():
        total = len(items)
        if not total:
            continue
        stale = sum(1 for n in items if _is_stale(n))
        low_q = sum(1 for n in items if (n.q_quality is not None and n.q_quality < 0.5))
        contained = sum(1 for n in items if n.mode == "contain")
        conflicts = 0
        ids = {n.id for n in items}
        for e in list_edges(active_only=True):
            if (e["source_id"] in ids or e["target_id"] in ids) and e["relation"] in {"conflicts_with", "destabilizes"}:
                conflicts += 1
        collapse_score = (stale / total) + (low_q / total) + (contained / total) * 0.5 + conflicts * 0.1
        if collapse_score > 0:
            results.append({
                "plane": plane,
                "collapse_score": round(collapse_score, 4),
                "total_nodes": total,
                "stale_nodes": stale,
                "low_quality_nodes": low_q,
                "contained_nodes": contained,
                "destabilizing_edges": conflicts,
            })
    return sorted(results, key=lambda x: x["collapse_score"], reverse=True)


def runtime_queries() -> dict[str, Any]:
    """P6: All results include why_flagged and explanation fields."""
    return {
        "load_bearing_constraints": query_load_bearing_constraints(),
        "feasibility_interventions": query_intervention_expands_feasibility(),
        "harm_flow": query_harm_flow(),
        "stale_truths": query_stale_truths(),
        "collapsing_planes": query_collapsing_planes(),
        "_meta": {
            "explanation_fields": [
                "why_flagged",
                "what_constraint_is_load_bearing",
                "what_breaks_next",
                "what_intervention_changes_state",
            ],
            "description": "Every result includes human-readable diagnosis fields. Read these before acting on scores.",
        },
    }
