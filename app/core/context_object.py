"""WO-R2 context-object assembler (roadmap §7; Levels 5 + 3).

Read-only ORCHESTRATION over existing verified components — the fold resolver, retrieval
internals, the conflicts table, and the WO-2 promotion ledger. No new epistemic scoring
primitive, no schema mutation, no write path. Determinism: same DB state + same request =>
identical response (every list has a stable ordering). Honesty: unresolved/empty scopes return
structured warnings, never fabricated state; `actions` are advisory and grounded in existing
governed endpoints; promoted docs inherit the WO-2 dual exposure gate.

Promoted-content contract (ALL scope forms, including query-scope POST): the STANDARD WO-2 dual
gate applies — `BOH_RETRIEVAL_INCLUDE_PROMOTED` (env) AND `include_promoted` (request) must both
be open for promoted docs to appear; they then surface through `evidence` packs and the
resolved-scope member count. Query-scope POST is NOT stricter. The one structurally stricter
form is `plane:` scope, whose membership derives from PlaneCards — promoted docs are never
card-wrapped, so they can never appear there regardless of the gates. Enforcement is exclusively
via the shared `promoted_exposure` predicate (no divergent filter exists in this module).
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.core import promoted_exposure, retrieval
from app.core.current_fold import current_fold_from_folded_node
from app.db import connection as db

SCOPE_TYPES = ("doc", "project", "plane", "query", "node")
QUESTION_TYPES = ("historical", "operational", "authority", "exploratory")

# WO-R4 verified traversal vocabulary — STORED edges only (inventory 2026-06-11):
# doc_edges.edge_type is schema-constrained to these five (real data: conflicts, derives,
# duplicate_content; doc_edges itself is DERIVED storage rebuilt by dcns from lineage+conflicts);
# lineage.relationship values are normalized below. Display-only taxonomy (topic_overlap,
# same_source, wrapped_as, indexed_from, review, rollback) is NOT traversable.
VERIFIED_EDGE_TYPES = ("duplicate_content", "supersedes", "superseded_by", "conflicts",
                       "canon_relates_to", "derives", "derived_from", "lineage")
AUTHORITY_EDGE_TYPES = ("supersedes", "superseded_by", "derives", "derived_from")
NEIGHBORHOOD_EDGE_CAP = 100


def _normalize_rel(rel: str) -> str:
    rel = (rel or "").lower()
    if "supersed" in rel:
        return "superseded_by" if "by" in rel else "supersedes"
    if "derive" in rel:
        return "derived_from" if "from" in rel else "derives"
    if rel in VERIFIED_EDGE_TYPES:
        return rel
    return "lineage"  # any other STORED relationship value, kept traversable but generic


def _stored_edges() -> list[dict]:
    """Every STORED edge (doc_edges + lineage), normalized to the verified vocabulary."""
    edges = [{"source": r["source_doc_id"], "target": r["target_doc_id"],
              "type": r["edge_type"], "origin": "doc_edges"}
             for r in db.fetchall(
                 "SELECT source_doc_id, target_doc_id, edge_type FROM doc_edges "
                 "ORDER BY source_doc_id, target_doc_id, edge_type")]
    edges += [{"source": r["doc_id"], "target": r["related_doc_id"],
               "type": _normalize_rel(r["relationship"]), "origin": "lineage"}
              for r in db.fetchall(
                  "SELECT doc_id, related_doc_id, relationship FROM lineage "
                  "ORDER BY doc_id, related_doc_id, relationship, id")]
    return edges


def _neighborhood(center: str, radius: int, edge_types: list[str] | None,
                  show_promoted: bool, warnings: list[str]) -> tuple[list[str], list[dict]]:
    """BFS over STORED edges only (bidirectional), promoted-excluded, deterministic."""
    allowed = set(edge_types) if edge_types else set(VERIFIED_EDGE_TYPES)
    edges = [e for e in _stored_edges() if e["type"] in allowed]
    adj: dict[str, set[str]] = {}
    for e in edges:
        adj.setdefault(e["source"], set()).add(e["target"])
        adj.setdefault(e["target"], set()).add(e["source"])
    seen, frontier = {center}, {center}
    for _ in range(radius):
        frontier = {n for f in sorted(frontier) for n in sorted(adj.get(f, ())) if n not in seen}
        seen |= frontier
    # Promoted-exposure filter on discovered members (the center was validated upstream).
    members = []
    for doc_id in sorted(seen):
        row = db.fetchone(
            "SELECT doc_id FROM docs WHERE doc_id = ?"
            + promoted_exposure.exclusion_sql("", show_promoted=show_promoted), (doc_id,))
        if row:
            members.append(doc_id)
    kept = [e for e in edges if e["source"] in set(members) and e["target"] in set(members)]
    if len(kept) > NEIGHBORHOOD_EDGE_CAP:
        kept = kept[:NEIGHBORHOOD_EDGE_CAP]
        warnings.append("edges_truncated")
    return members, kept


def _authority_paths(center: str, show_promoted: bool) -> list[list[dict]]:
    """Paths from the center along authority-bearing STORED edges (depth <= 3, max 10 paths),
    plus the promotion-ledger edge when the center is a promoted doc. Traversal honors the
    promoted-exposure predicate: a gate-hidden node can never appear in a path step."""
    auth = [e for e in _stored_edges() if e["type"] in AUTHORITY_EDGE_TYPES]
    paths: list[list[dict]] = []
    _vis: dict[str, bool] = {}

    def visible(doc_id: str) -> bool:
        if doc_id not in _vis:
            _vis[doc_id] = db.fetchone(
                "SELECT doc_id FROM docs WHERE doc_id = ?"
                + promoted_exposure.exclusion_sql("", show_promoted=show_promoted),
                (doc_id,)) is not None
        return _vis[doc_id]

    def walk(node: str, path: list[dict], visited: set[str]) -> None:
        if len(paths) >= 10 or len(path) >= 3:
            if path and path not in paths:
                paths.append(list(path))
            return
        extended = False
        for e in auth:
            nxt = e["target"] if e["source"] == node else (
                e["source"] if e["target"] == node else None)
            if nxt and nxt not in visited and visible(nxt):
                extended = True
                walk(nxt, path + [{"from": node, "to": nxt, "type": e["type"]}],
                     visited | {nxt})
        if not extended and path:
            paths.append(list(path))

    walk(center, [], {center})
    promo = db.fetchone(
        "SELECT promotion_id, source_revision_id FROM intake_promotions "
        "WHERE doc_id = ? AND status = 'active'", (center,))
    if promo:
        paths.append([{"from": center, "to": f"revision:{promo['source_revision_id']}",
                       "type": "promotion"}])
    paths.sort(key=lambda p: json.dumps(p, sort_keys=True))
    return paths[:10]
SECTION_CAP = 50      # conflicts / unknowns / actions / question-context rows per response
MEMBERSHIP_CAP = 500  # derived members per scope (deterministic ORDER BY doc_id truncation)


def _question_context(question_type: str, scope_type: str, value: str,
                      members: list[str], conflicts: list[dict],
                      warnings: list[str]) -> dict:
    """WO-R3 (Level 4): question type changes WHICH sources are assembled. Read-only; members
    are already promoted-exposure filtered upstream. The monotonic trace ordinal is excluded
    (separately gated): historical ordering uses existing timestamps and DISCLOSES ties."""
    out: dict[str, Any] = {"type": question_type}
    if not members:
        out["note"] = "no_members_in_scope"
        return out
    marks = ",".join("?" * len(members))

    if question_type == "historical":
        lineage = db.fetchall(
            f"SELECT id, doc_id, related_doc_id, relationship, detected_ts FROM lineage "
            f"WHERE doc_id IN ({marks}) OR related_doc_id IN ({marks}) "
            "ORDER BY detected_ts, id", tuple(members) * 2)
        events = db.fetchall(
            f"SELECT id, event_ts, event_type, actor_type, doc_id FROM audit_log "
            f"WHERE doc_id IN ({marks}) ORDER BY event_ts, id", tuple(members))
        timeline = (
            [{"ts": r["detected_ts"], "kind": "lineage",
              "what": r["relationship"], "doc_id": r["doc_id"],
              "related_doc_id": r["related_doc_id"], "ref": f"lineage:{r['id']}"}
             for r in lineage] +
            [{"ts": r["event_ts"], "kind": "audit", "what": r["event_type"],
              "doc_id": r["doc_id"], "actor_type": r["actor_type"],
              "ref": f"audit:{r['id']}"} for r in events])
        timeline.sort(key=lambda e: (e["ts"] or 0, e["ref"]))
        ts_seen = [e["ts"] for e in timeline]
        if len(ts_seen) != len(set(ts_seen)):
            warnings.append("trace_order_approximate")  # timestamp ties; no ordinal exists yet
        if len(timeline) > SECTION_CAP:
            timeline = timeline[:SECTION_CAP]
            warnings.append("timeline_truncated")
        out["timeline"] = timeline
        out["supersession_chain"] = [e for e in timeline
                                     if e["kind"] == "lineage"
                                     and "supersed" in (e["what"] or "")]

    elif question_type == "operational":
        out["open_items"] = db.fetchall(
            f"SELECT id, node_id, status, drift_priority, description, created_at, valid_until "
            f"FROM open_items WHERE node_id IN ({marks}) AND status = 'open' "
            "ORDER BY created_at, id", tuple(members))[:SECTION_CAP]
        out["active_promotions"] = db.fetchall(
            f"SELECT promotion_id, doc_id, source_revision_id, promoted_at "
            f"FROM intake_promotions WHERE doc_id IN ({marks}) AND status = 'active' "
            "ORDER BY promoted_at, promotion_id", tuple(members))[:SECTION_CAP]
        out["blocking_conditions"] = [
            {"blocker": "open_conflict", "source": f"conflict:{c['rowid']}",
             "provenance": "direct"}
            for c in conflicts if c["resolution_status"] == "open"][:SECTION_CAP]

    elif question_type == "authority":
        out["review_history"] = db.fetchall(
            f"SELECT artifact_id, document_id, action_type, from_state, to_state, "
            f"approved_by, approved_at FROM provenance_artifacts "
            f"WHERE document_id IN ({marks}) ORDER BY approved_at DESC, artifact_id",
            tuple(members))[:SECTION_CAP]
        out["certificates"] = db.fetchall(
            f"SELECT certificate_id, node_id, status, authority_plane, risk_class, "
            f"valid_until, created_at FROM certificates WHERE node_id IN ({marks}) "
            "ORDER BY created_at DESC, certificate_id", tuple(members))[:SECTION_CAP]
        out["open_conflicts"] = [f"conflict:{c['rowid']}" for c in conflicts
                                 if c["resolution_status"] == "open"][:SECTION_CAP]

    elif question_type == "exploratory":
        out["contradiction_pairs"] = [
            {"docs": c.get("doc_ids"), "term": c.get("term"),
             "ref": f"conflict:{c['rowid']}"}
            for c in conflicts if c["resolution_status"] == "open"][:SECTION_CAP]
        if scope_type == "doc":
            from app.core.related import get_neighborhood
            hood = get_neighborhood(value, depth=1, limit=20)
            out["neighbors"] = sorted(
                ({"id": n.get("id"), "title": n.get("title")}
                 for n in hood.get("nodes", []) if not n.get("isCenter")),
                key=lambda n: str(n["id"]))[:SECTION_CAP]
        else:
            warnings.append("exploratory_neighbors_doc_scope_only")
    return out


def _members_for(scope_type: str, value: str, show_promoted: bool,
                 warnings: list[str]) -> list[str]:
    excl = promoted_exposure.exclusion_sql("", show_promoted=show_promoted)
    if scope_type == "doc":
        row = db.fetchone(f"SELECT doc_id FROM docs WHERE doc_id = ?{excl}", (value,))
        return [row["doc_id"]] if row else []
    if scope_type == "project":
        rows = db.fetchall(
            f"SELECT doc_id FROM docs WHERE project = ?{excl} ORDER BY doc_id", (value,))
        return [r["doc_id"] for r in rows]
    if scope_type == "plane":
        # Membership via PlaneCards (the governed doc-level plane projection) — disclosed.
        warnings.append("plane_membership_via_planecards")
        rows = db.fetchall(
            "SELECT DISTINCT c.doc_id FROM cards c JOIN docs d ON d.doc_id = c.doc_id "
            f"WHERE c.plane = ? AND c.doc_id IS NOT NULL{promoted_exposure.exclusion_sql('d', show_promoted=show_promoted)} "
            "ORDER BY c.doc_id", (value,))
        return [r["doc_id"] for r in rows]
    return []  # query scope: members derive from evidence packs


def _conflicts_for_members(members: list[str]) -> list[dict]:
    if not members:
        return []
    member_set = set(members)
    rows = db.fetchall("SELECT rowid, * FROM conflicts ORDER BY detected_ts DESC, rowid DESC")
    out = []
    for r in rows:
        ids = (r.get("doc_ids") or "").split(",")
        if member_set.intersection(ids):
            c = dict(r)
            c["resolution_status"] = "acknowledged" if c.get("acknowledged") else "open"
            out.append(c)
    # Deterministic: open first, newest first, rowid tiebreak.
    out.sort(key=lambda c: (c["resolution_status"] != "open",
                            -(c.get("detected_ts") or 0), -c["rowid"]))
    return out


def _light_unknowns(members: list[str]) -> list[dict]:
    """Multi-doc scopes: structured per-member gaps from durable columns (no fabrication)."""
    if not members:
        return []
    marks = ",".join("?" * len(members))
    rows = db.fetchall(
        f"SELECT doc_id, authority_state, epistemic_last_evaluated FROM docs "
        f"WHERE doc_id IN ({marks}) ORDER BY doc_id", tuple(members))
    out = []
    for r in rows:
        if not r.get("authority_state"):
            out.append({"field": "authority_state", "doc_id": r["doc_id"],
                        "severity": "medium", "meaning": "authority state is unset",
                        "provenance": "direct"})
        if not r.get("epistemic_last_evaluated"):
            out.append({"field": "epistemic_last_evaluated", "doc_id": r["doc_id"],
                        "severity": "low", "meaning": "no epistemic evaluation timestamp",
                        "provenance": "direct"})
    return out


def _actions_for(conflicts: list[dict], node_unknowns: list[dict]) -> list[dict]:
    """Advisory only — every action is grounded in an existing governed endpoint or a
    resolver-suggested step. Never executed here."""
    actions = []
    for c in conflicts:
        if c["resolution_status"] == "open":
            actions.append({
                "action_type": "acknowledge_conflict",
                "reason": f"open {c.get('conflict_type') or 'conflict'} on term "
                          f"{c.get('term') or '?'}",
                "source_object": f"conflict:{c['rowid']}",
                "affected_object": f"docs:{c.get('doc_ids') or ''}",
                "required_authority": "operator_token",
                "requires_operator_approval": True,
                "executability": "executable_now",  # conflict-acknowledgment route exists
            })
    for u in node_unknowns:
        if u.get("resolution_action"):
            actions.append({
                "action_type": "resolve_unknown",
                "reason": u.get("meaning") or u.get("field") or "unknown",
                "source_object": f"fold_unknown:{u.get('field')}",
                "affected_object": "doc",
                "required_authority": "operator_token",
                "requires_operator_approval": True,
                "executability": "suggested_only",
            })
    actions.sort(key=lambda a: (a["action_type"], a["source_object"]))
    return actions


def assemble(scope_type: str, value: str, *, only: str | None = None,
             evidence_limit: int = 8, include_promoted: bool = False,
             question_type: str | None = None, radius: int = 1,
             edge_types: list[str] | None = None) -> dict:
    warnings: list[str] = []
    show_promoted = promoted_exposure.visible(include_promoted)
    requested = {"type": scope_type, "value": value}
    if scope_type not in SCOPE_TYPES:
        return {"scope": {"requested": requested, "resolved": None, "ambiguous": False,
                          "warnings": ["unsupported_scope_type"]},
                "state": {}, "evidence": [], "conflicts": [], "unknowns": [], "actions": []}

    neighborhood_edges: list[dict] = []
    if scope_type == "node":
        center = db.fetchone(
            "SELECT doc_id FROM docs WHERE doc_id = ?"
            + promoted_exposure.exclusion_sql("", show_promoted=show_promoted), (value,))
        members, neighborhood_edges = (
            _neighborhood(value, max(1, min(2, radius)), edge_types, show_promoted, warnings)
            if center else ([], []))
    else:
        members = _members_for(scope_type, value, show_promoted, warnings)
    if len(members) > MEMBERSHIP_CAP:
        members = members[:MEMBERSHIP_CAP]  # already ORDER BY doc_id -> deterministic
        warnings.append("membership_truncated")

    # Evidence via the existing retrieval engine (carries WO-R1/WO-2 provenance blocks).
    if scope_type in ("doc", "node"):
        doc_row = db.fetchone("SELECT title, summary FROM docs WHERE doc_id = ?", (value,))
        query = " ".join(filter(None, [(doc_row or {}).get("title"),
                                       (doc_row or {}).get("summary")])) or value
        filters: dict[str, Any] = {"doc_id": value} if scope_type == "doc" else {}
    elif scope_type == "project":
        query, filters = value, {"project": value}
    else:
        query, filters = value, {}
    packs = []
    if (members or scope_type == "query") and only != "blocking":
        # FTS5 treats '-', ':' etc. in barewords as operators (pre-existing retrieval
        # fragility, surfaced by the WO-R2 audit); sanitize the DERIVED query so scope ids
        # like 'promoted-ghost' cannot raise an FTS syntax error.
        safe_query = re.sub(r"[^A-Za-z0-9_ ]+", " ", query).strip() or "document"
        base = retrieval.retrieve(safe_query, limit=evidence_limit, filters=filters,
                                  show_promoted=show_promoted)
        packs = base.get("context_packs", [])
        if scope_type in ("plane", "node"):
            packs = [p for p in packs if p.get("doc_id") in set(members)]
        packs.sort(key=lambda p: (-(p.get("score") or 0.0),
                                  str(p.get("chunk_id") or p.get("card_id") or "")))
    if scope_type == "query":
        members = sorted({p.get("doc_id") for p in packs if p.get("doc_id")})

    if not members and scope_type != "query":
        warnings.append("scope_not_found" if scope_type in ("doc", "node") else "empty_scope")
    resolved = ({"type": scope_type, "value": value, "member_count": len(members)}
                if members or scope_type == "query" else None)

    conflicts = _conflicts_for_members(members)
    if len(conflicts) > SECTION_CAP:
        conflicts = conflicts[:SECTION_CAP]
        warnings.append("conflicts_truncated")

    node_unknowns: list[dict] = []
    state: dict[str, Any] = {}
    if scope_type == "doc" and members:
        packet = current_fold_from_folded_node(value)
        if packet is not None:
            pd = packet.as_dict()
            state = {"kind": "node",
                     "currentness_label": (pd.get("symbolic_state") or {}).get("currentness_label"),
                     "scalar_state": pd.get("scalar_state"),
                     "why_current": pd.get("why_current"),
                     "local_state": pd.get("local_state")}
            node_unknowns = pd.get("unknowns") or []
    if scope_type == "node" and members:
        # WO-R4: neighborhood state over STORED edges only, with pressure contributors
        # (the fold resolver's enumerated inputs, inverted) and authority paths.
        from app.core.retrieval import _freshness_for
        center_row = db.fetchone("SELECT * FROM docs WHERE doc_id = ?", (value,)) or {}
        paths = _authority_paths(value, show_promoted)
        state = {
            "kind": "neighborhood", "center": value,
            "radius": max(1, min(2, radius)),
            "edge_types_filter": sorted(edge_types) if edge_types else None,
            "edges": neighborhood_edges,
            "pressure_contributors": {
                "conflict_pressure": [f"conflict:{c['rowid']}" for c in conflicts
                                      if c["resolution_status"] == "open"][:SECTION_CAP],
                "connectivity": {"neighbor_count": len(members) - 1,
                                 "edge_count": len(neighborhood_edges)},
                "freshness": _freshness_for(dict(center_row)),
            },
            "authority_paths": paths,
        }
        if not paths:
            node_unknowns = list(node_unknowns) + [{
                "field": "authority_path", "doc_id": value, "severity": "low",
                "meaning": "authority_path_unresolvable: no stored authority-bearing edges "
                           "reach or leave this node",
                "provenance": "direct"}]
    if not state:
        state = {"kind": "membership", "members": len(members),
                 "open_conflicts": sum(1 for c in conflicts
                                       if c["resolution_status"] == "open")}
    unknowns = node_unknowns if node_unknowns else _light_unknowns(members)
    if len(unknowns) > SECTION_CAP:
        unknowns = unknowns[:SECTION_CAP]
        warnings.append("unknowns_truncated")

    actions = _actions_for(conflicts, node_unknowns)[:SECTION_CAP]

    question_context = None
    if question_type:
        if question_type not in QUESTION_TYPES:
            warnings.append("unsupported_question_type")
        else:
            question_context = _question_context(question_type, scope_type, value,
                                                 members, conflicts, warnings)

    result = {
        "scope": {"requested": requested, "resolved": resolved,
                  "ambiguous": False, "warnings": warnings},
        "state": state,
        "evidence": packs,
        "conflicts": conflicts,
        "unknowns": unknowns,
        "actions": actions,
    }
    if question_context is not None:
        result["question_context"] = question_context
    if only == "blocking":
        blockers = []
        for c in conflicts:
            if c["resolution_status"] == "open":
                blockers.append({"blocker": "open_conflict",
                                 "source": f"conflict:{c['rowid']}",
                                 "evidence_refs": [f"docs:{c.get('doc_ids') or ''}"],
                                 "provenance": "direct"})
        for u in node_unknowns:
            if u.get("blocks_currentness") or u.get("blocks_canon_eligibility") \
                    or u.get("blocks_queryability"):
                blockers.append({"blocker": f"unknown:{u.get('field')}",
                                 "source": f"fold_unknown:{u.get('field')}",
                                 "evidence_refs": [f"doc:{value}"],
                                 "provenance": "computed"})
        result["blockers"] = blockers
    return result
