"""app/api/routes/fold_routes.py -- Current Fold View API routes.

GET /api/fold/node/{doc_id}                  -> CurrentFoldPacket (resolver-backed, full resolve)
GET /api/fold/node/{doc_id}/trace            -> Full resolver trace (stub; lazy-loaded by Advanced View)
GET /api/fold/library                        -> Lightweight batch fold summaries for all docs
GET /api/fold/cluster/{axis}/{value}         -> aggregate CurrentFoldPacket (project, plane, domain, batch)
GET /api/fold/corpus/{axis}                  -> corpus rollup of an axis's clusters (project, plane, domain, batch)
GET /api/fold/cluster/{axis}/{value}/trace   -> lazy aggregate-trace stub (available=false)

domain axis: no doc→domain linkage exists; returns empty clusters with
domain_membership_unresolvable unknown. diagnostic_only=True (temporary).

batch axis: membership via intake_capabilities.source_ref = docs.path, deduplicated
by doc_id per batch. diagnostic_only=True (ingestion provenance axis).

The existing /api/docs/{doc_id}/fold endpoint (folded-node packet) is preserved unchanged.
"""

from __future__ import annotations

import datetime
import json as _json
import time as _time
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.core.current_fold import FoldUnknown, current_fold_from_folded_node
from app.core.fold_aggregation import (
    FoldMemberInput,
    aggregate_cluster,
    aggregate_corpus,
)
from app.core.fold_metrics import compute_canon_variables_partial
from app.db import connection as db

router = APIRouter(prefix="/api/fold", tags=["fold"])

# All four supported cluster axes. domain and batch added in boh_fold_domain_batch_axes_v0_1.
_SUPPORTED_CLUSTER_AXES: frozenset[str] = frozenset({"project", "plane", "domain", "batch"})

# Injected into every domain cluster/corpus response to distinguish
# "unresolvable membership" from "genuinely empty cluster."
_DOMAIN_MEMBERSHIP_UNKNOWN = FoldUnknown(
    field="domain_membership_unresolvable",
    severity="medium",
    meaning=(
        "substrate_lattice_registry contains domain values but no doc→domain linkage "
        "exists in the current schema. This cluster is empty because document membership "
        "cannot be determined, not because no documents belong to this domain."
    ),
    blocks_currentness=False,
    blocks_canon_eligibility=True,
    blocks_queryability=False,
    resolution_action=(
        "Establish a doc→domain linkage (e.g. a docs.domain column or join table) "
        "to enable domain membership resolution."
    ),
)

# ---------------------------------------------------------------------------
# Scoring helpers (mirrors fold_metrics.py; inline here for batch efficiency)
# ---------------------------------------------------------------------------

_AUTHORITY_SCORES: dict[str, float] = {
    "canonical": 1.0, "trusted": 0.90, "approved": 0.80,
    "reviewed": 0.75, "under_review": 0.55, "custodian_review": 0.50,
    "draft": 0.35, "non_authoritative": 0.20, "unknown": 0.10,
}

_FRESHNESS_DECAY = [(7, 1.00), (30, 0.90), (90, 0.70), (180, 0.50), (365, 0.30)]


def _freshness_from_days(days: int | None) -> float:
    if days is None:
        return 0.0
    for threshold, score in _FRESHNESS_DECAY:
        if days <= threshold:
            return score
    return 0.10


def _safe_fetchall(q: str, params: tuple = ()) -> list[dict[str, Any]]:
    try:
        return [dict(r) for r in db.fetchall(q, params)]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/node/{doc_id}", summary="CurrentFoldPacket for a node")
def get_current_fold(doc_id: str):
    """Return a resolver-backed CurrentFoldPacket answering what is current and why.

    Distinct from /api/docs/{doc_id}/fold (which returns the raw folded-node packet).
    Includes scalar pressures, symbolic labels, compact trace, and unknowns.
    """
    packet = current_fold_from_folded_node(doc_id)
    if packet is None:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    return packet.as_dict()


@router.get("/node/{doc_id}/trace", summary="Full resolver trace for a node (lazy)")
def get_fold_trace(doc_id: str):
    """Full resolver trace stub. Compact trace is already in the main CurrentFoldPacket."""
    return {
        "doc_id": doc_id,
        "trace_id": None,
        "available": False,
        "reason": "Full trace deferred to Phase 6+. Use resolver_trace_summary in CurrentFoldPacket.",
        "compact_trace_ref": f"/api/fold/node/{doc_id}",
    }


@router.get("/library", summary="Lightweight fold state summary for the full library")
def get_fold_library(limit: int = Query(500, ge=1, le=2000, description="Max docs to include")):
    """Return batch-computed fold summaries for all indexed docs.

    Uses simplified scoring (no per-doc subqueries) so it can cover the full
    library in a single response. Suitable for the Fold View scatter canvas.
    The /api/fold/node/{doc_id} endpoint gives the full resolver output for any
    individual document.

    Dimensions returned per doc:
      authority_score   -- from authority_state mapping
      freshness_score   -- from epistemic_last_evaluated or updated_ts
      conflict_pressure -- from unresolved conflicts count
      canon_readiness   -- composite of authority + freshness + conflict
      currentness_label -- simplified precedence rules (no supersession check)
    """
    # Batch load all docs (promoted intake docs excluded unless the env gate is open — WO-2)
    from app.core import promoted_exposure
    raw_docs = _safe_fetchall(
        "SELECT doc_id, title, authority_state, status, "
        "updated_ts, epistemic_last_evaluated "
        "FROM docs WHERE 1=1"
        + promoted_exposure.exclusion_sql("", show_promoted=promoted_exposure.env_gate_open())
        + " LIMIT ?",
        (limit,),
    )

    # Batch load conflict counts: parse doc_ids JSON from each unresolved row
    all_conflicts = _safe_fetchall(
        "SELECT doc_ids FROM conflicts WHERE acknowledged IS NULL OR acknowledged = 0"
    )
    conflict_map: dict[str, int] = {}
    for row in all_conflicts:
        raw_ids = row.get("doc_ids") or ""
        try:
            ids = _json.loads(raw_ids)
            if isinstance(ids, str):
                ids = [ids]
        except Exception:
            ids = [raw_ids] if raw_ids else []
        for did in ids:
            if did:
                conflict_map[did] = conflict_map.get(did, 0) + 1

    now_ts = _time.time()
    results: list[dict[str, Any]] = []
    label_counts: dict[str, int] = {}

    for doc in raw_docs:
        doc_id = doc.get("doc_id") or ""
        authority_state = (doc.get("authority_state") or "unknown").lower()
        status = (doc.get("status") or "").lower()

        auth_score = _AUTHORITY_SCORES.get(authority_state, 0.10)

        # Freshness: epistemic_last_evaluated (ISO string) → updated_ts (unix int)
        freshness_age: int | None = None
        epistemic = doc.get("epistemic_last_evaluated")
        updated = doc.get("updated_ts")
        if epistemic:
            try:
                dt = datetime.datetime.fromisoformat(str(epistemic).replace("Z", "+00:00"))
                freshness_age = max(0, int((now_ts - dt.timestamp()) / 86400))
            except Exception:
                pass
        if freshness_age is None and updated:
            try:
                freshness_age = max(0, int((now_ts - float(updated)) / 86400))
            except Exception:
                pass
        fresh_score = _freshness_from_days(freshness_age)

        unresolved = conflict_map.get(doc_id, 0)
        conflict_pressure = round(min(unresolved / 6.0, 1.0), 3)

        canon_readiness = round(
            auth_score * 0.40
            + fresh_score * 0.20
            + (1.0 - conflict_pressure) * 0.20
            + 0.20,
            3,
        )

        # Simplified currentness label (no lineage walk or intake subqueries)
        if status == "quarantine":
            label = "quarantined"
        elif status == "hold":
            label = "held"
        elif unresolved > 0:
            label = "conflicted"
        elif fresh_score < 0.25:
            label = "stale"
        elif auth_score < 0.30:
            label = "unknown"
        elif authority_state in {"draft", "non_authoritative", "unknown", ""}:
            label = "draft_current"
        else:
            label = "current"

        canon_vars = compute_canon_variables_partial(
            auth_score=auth_score,
            freshness_score=fresh_score,
            conflict_pressure=conflict_pressure,
            canon_readiness=canon_readiness,
        )

        label_counts[label] = label_counts.get(label, 0) + 1
        results.append({
            "doc_id": doc_id,
            "title": doc.get("title") or doc_id,
            "authority_score": round(auth_score, 3),
            "freshness_score": round(fresh_score, 3),
            "conflict_pressure": conflict_pressure,
            "canon_readiness": canon_readiness,
            "currentness_label": label,
            "authority_state": authority_state,
            "canon_variables": canon_vars.as_dict(),
        })

    return {
        "docs": results,
        "label_counts": label_counts,
        "total": len(results),
        "policy": "FoldMetricPolicy.v0.1 / DefaultFoldSymbolicPolicy.v0_1 (batch mode — simplified)",
    }


# ---------------------------------------------------------------------------
# Phase 7b -- cluster / corpus aggregation routes (project + plane axes)
#
# Membership is resolved live from the DB and never cached as truth. Node
# packets are composed via current_fold_from_folded_node and handed to the
# frozen Phase 7a engine; these routes add no aggregation semantics of their
# own. The engine only dereferences node_packet for actual members, so packets
# for non-members are passed as None (project axis) to avoid needless resolves.
# ---------------------------------------------------------------------------

def _axis_value_from_packet(packet_dict: dict[str, Any], axis: str) -> Any:
    """Read a node's value on `axis` from its Phase 6 scale_actions.

    Returns the `value` portion of an allowed `"{axis}:{value}"` target_id, or
    None when the node has no resolvable value on that axis.
    """
    for action in packet_dict.get("scale_actions", []) or []:
        if action.get("target_axis") == axis and action.get("allowed"):
            target_id = action.get("target_id") or ""
            prefix = f"{axis}:"
            if target_id.startswith(prefix):
                return target_id[len(prefix):]
    return None


def _cluster_members_batch(value: str) -> list[FoldMemberInput]:
    """Batch-axis membership via intake_capabilities.source_ref = docs.path.

    Membership rule: a doc belongs to batch B iff at least one intake_capabilities
    record links source_ref to docs.path with batch_id = B.  Each doc_id contributes
    at most once (SET semantics over the deduplication query).

    Non-members that have an intake record for a different batch carry that batch_id
    as their axis_value (not ambiguous). Docs with no intake record at all carry
    axis_value=None (registers cluster_membership_ambiguous).
    """
    # Deduplicated set of doc_ids in the requested batch.
    member_ids: set[str] = {
        row["doc_id"]
        for row in _safe_fetchall(
            """SELECT DISTINCT d.doc_id
               FROM docs d
               JOIN intake_capabilities ic ON ic.source_ref = d.path
               WHERE NULLIF(TRIM(ic.batch_id), '') = ?""",
            (value,),
        )
    }
    # For non-members: resolve a representative batch_id from other batches so they
    # are not mistakenly marked cluster_membership_ambiguous (only truly unlinked
    # docs should be ambiguous).
    other_batch: dict[str, str] = {}
    for row in _safe_fetchall(
        """SELECT d.doc_id, ic.batch_id
           FROM docs d
           JOIN intake_capabilities ic ON ic.source_ref = d.path
           WHERE NULLIF(TRIM(ic.batch_id), '') IS NOT NULL
             AND NULLIF(TRIM(ic.batch_id), '') != ?""",
        (value,),
    ):
        # First encountered batch_id wins; any non-None value prevents ambiguous marking.
        doc_id = row.get("doc_id") or ""
        if doc_id not in other_batch:
            other_batch[doc_id] = row["batch_id"]

    members: list[FoldMemberInput] = []
    for row in _safe_fetchall("SELECT doc_id FROM docs"):
        doc_id = row.get("doc_id") or ""
        if doc_id in member_ids:
            members.append(FoldMemberInput(
                node_packet=current_fold_from_folded_node(doc_id),
                axis_value=value,
            ))
        else:
            members.append(FoldMemberInput(
                node_packet=None,
                axis_value=other_batch.get(doc_id),  # None → ambiguous if no intake record
            ))
    return members


def _cluster_members_domain(_value: str) -> list[FoldMemberInput]:
    """Domain-axis membership: returns an empty list (no doc→domain linkage exists).

    The route layer injects a domain_membership_unresolvable FoldUnknown into the
    returned packet to distinguish this from an ordinary empty cluster.
    """
    return []


def _cluster_members(axis: str, value: str) -> list[FoldMemberInput]:
    """Build engine member inputs over all candidate nodes for `axis`.

    A candidate whose axis value is None reaches the engine as `axis_value=None`
    (it registers cluster_membership_ambiguous, never a silent member). Only
    members whose value equals `value` carry a composed node packet.
    """
    members: list[FoldMemberInput] = []
    if axis == "project":
        # docs.project is authoritative; compose a packet only for real members.
        for row in _safe_fetchall("SELECT doc_id, project FROM docs"):
            axis_value = row.get("project")
            packet = (
                current_fold_from_folded_node(row.get("doc_id") or "")
                if axis_value == value else None
            )
            members.append(FoldMemberInput(node_packet=packet, axis_value=axis_value))
    elif axis == "plane":
        for row in _safe_fetchall("SELECT doc_id FROM docs"):
            doc_id = row.get("doc_id") or ""
            packet = current_fold_from_folded_node(doc_id)
            if packet is None:
                continue
            axis_value = _axis_value_from_packet(packet.as_dict(), "plane")
            members.append(FoldMemberInput(
                node_packet=packet if axis_value == value else None,
                axis_value=axis_value,
            ))
    elif axis == "batch":
        return _cluster_members_batch(value)
    elif axis == "domain":
        return _cluster_members_domain(value)
    return members


def _corpus_clusters(axis: str) -> list[Any]:
    """Compose one cluster packet per distinct value on `axis`."""
    if axis == "project":
        rows = _safe_fetchall(
            "SELECT DISTINCT project FROM docs WHERE project IS NOT NULL ORDER BY project"
        )
        return [
            aggregate_cluster("project", r["project"], _cluster_members("project", r["project"]))
            for r in rows if r.get("project") is not None
        ]
    if axis == "plane":
        # Plane has no column; compose each packet once and group by resolved plane.
        members_by_value: dict[str, list[FoldMemberInput]] = {}
        for row in _safe_fetchall("SELECT doc_id FROM docs"):
            packet = current_fold_from_folded_node(row.get("doc_id") or "")
            if packet is None:
                continue
            axis_value = _axis_value_from_packet(packet.as_dict(), "plane")
            if axis_value is None:
                continue
            members_by_value.setdefault(axis_value, []).append(
                FoldMemberInput(node_packet=packet, axis_value=axis_value)
            )
        return [
            aggregate_cluster("plane", value, members_by_value[value])
            for value in sorted(members_by_value)
        ]
    if axis == "batch":
        rows = _safe_fetchall(
            """SELECT DISTINCT batch_id FROM intake_capabilities
               WHERE NULLIF(TRIM(batch_id), '') IS NOT NULL ORDER BY batch_id"""
        )
        return [
            aggregate_cluster("batch", r["batch_id"], _cluster_members_batch(r["batch_id"]))
            for r in rows if r.get("batch_id")
        ]
    if axis == "domain":
        rows = _safe_fetchall(
            """SELECT DISTINCT domain FROM substrate_lattice_registry
               WHERE NULLIF(TRIM(domain), '') IS NOT NULL ORDER BY domain"""
        )
        clusters = []
        for r in rows:
            if not r.get("domain"):
                continue
            packet = aggregate_cluster("domain", r["domain"], [])
            packet.unknowns.append(_DOMAIN_MEMBERSHIP_UNKNOWN)
            clusters.append(packet)
        return clusters
    return []


@router.get("/cluster/{axis}/{value}", summary="Aggregate CurrentFoldPacket for a cluster")
def get_fold_cluster(axis: str, value: str):
    """Roll the nodes belonging to cluster `{axis}:{value}` up to one aggregate packet.

    Supported axes: `project`, `plane`, `domain`, `batch`.
    Membership is resolved live from the DB. An empty cluster returns 200, not 404.

    domain: no doc→domain linkage exists; always returns an empty cluster with a
    domain_membership_unresolvable unknown. diagnostic_only=True.

    batch: membership via intake_capabilities.source_ref = docs.path, deduplicated by
    doc_id. diagnostic_only=True (ingestion provenance axis only).
    """
    if axis not in _SUPPORTED_CLUSTER_AXES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported cluster axis '{axis}'. "
                   f"Supported: {', '.join(sorted(_SUPPORTED_CLUSTER_AXES))}.",
        )
    members = _cluster_members(axis, value)
    packet = aggregate_cluster(axis, value, members)
    if axis == "domain":
        packet.unknowns.append(_DOMAIN_MEMBERSHIP_UNKNOWN)
    return packet.as_dict()


@router.get("/corpus/{axis}", summary="Corpus rollup of an axis's clusters")
def get_fold_corpus(axis: str):
    """Roll all clusters on `axis` up to an axis-wide corpus packet.

    Supported axes: `project`, `plane`, `domain`, `batch`.

    domain: enumerates distinct domain values from substrate_lattice_registry.
    Each domain cluster is empty (domain_membership_unresolvable unknown injected).
    diagnostic_only=True.

    batch: enumerates distinct batch_ids from intake_capabilities. diagnostic_only=True.
    """
    if axis not in _SUPPORTED_CLUSTER_AXES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported corpus axis '{axis}'. "
                   f"Supported: {', '.join(sorted(_SUPPORTED_CLUSTER_AXES))}.",
        )
    clusters = _corpus_clusters(axis)
    packet = aggregate_corpus(axis, clusters)
    if axis == "domain":
        packet.unknowns.append(_DOMAIN_MEMBERSHIP_UNKNOWN)
    return packet.as_dict()


@router.get("/cluster/{axis}/{value}/trace", summary="Aggregate resolver trace (lazy stub)")
def get_fold_cluster_trace(axis: str, value: str):
    """Full aggregate trace stub. The frozen six-event compact trace is in the cluster packet."""
    if axis not in _SUPPORTED_CLUSTER_AXES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported cluster axis '{axis}'. "
                   f"Supported: {', '.join(sorted(_SUPPORTED_CLUSTER_AXES))}.",
        )
    return {
        "scope_id": f"{axis}:{value}",
        "trace_id": None,
        "available": False,
        "reason": "Full aggregate trace deferred. Use resolver_trace_summary in the cluster packet.",
        "compact_trace_ref": f"/api/fold/cluster/{axis}/{value}",
    }
