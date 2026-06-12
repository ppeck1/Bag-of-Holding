"""Evidence Graph Service for the BOH Planar Storage layer (Phase 4).

Consumes EvidenceUnit records and produces a deterministic graph of evidence
nodes and typed relationship edges. Relationships that require semantic
judgement (e.g. whether one claim supports or contradicts another) are NOT
guessed -- they are emitted as EvidenceReviewItem records for a human to resolve.

Pure logic: no database access, no filesystem access, no route or UI wiring,
no LLM. Building the same input twice yields a byte-identical snapshot.

Doctrine preserved:
- canon_eligible is never set True.
- ambiguous relationships are surfaced for review, never silently chosen.
- every node retains provenance (span + text_hash) back to its EvidenceUnit.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from app.core.planar_service_schemas import (
    EvidenceGraphEdge,
    EvidenceGraphNode,
    EvidenceGraphSnapshot,
    EvidenceReviewItem,
    EvidenceUnit,
)

# Relations the service can derive unambiguously from existing unit fields.
RELATION_SAME_SOURCE = "same_source"
RELATION_DERIVES_FROM = "derives_from"

# Relations that require human judgement between two co-sourced claims.
AMBIGUOUS_CLAIM_RELATIONS = ["contradicts", "supports"]

_CLAIM_UNIT_TYPE = "claim"


def _node_from_unit(unit: EvidenceUnit) -> EvidenceGraphNode:
    """Derive a graph node from an evidence unit, preserving provenance."""
    node_type = _CLAIM_UNIT_TYPE if unit.unit_type == _CLAIM_UNIT_TYPE else "evidence"
    return EvidenceGraphNode(
        evidence_unit_id=unit.evidence_unit_id,
        normalized_artifact_id=unit.normalized_artifact_id,
        node_type=node_type,
        span_start=unit.span_start,
        span_end=unit.span_end,
        text_hash=unit.text_hash,
        authority_default=unit.authority_default,
    )


def build_graph(
    evidence_units: Iterable[EvidenceUnit],
    *,
    policy_snapshot_hash: str | None = None,
) -> EvidenceGraphSnapshot:
    """Build a deterministic evidence graph from EvidenceUnit records.

    Derivation rules (all deterministic, using only fields already on each unit):
      - same_source: any two nodes sharing a normalized_artifact_id are linked
        (directional source<target by node_id) -- a factual co-location edge.
      - derives_from: a claim node derives_from each evidence(body) node in the
        same artifact -- a claim is extracted from the body it came from.
      - ambiguous: the truth relation between two co-sourced claims (supports vs
        contradicts) is NOT guessed; it becomes an EvidenceReviewItem instead.

    Returns an EvidenceGraphSnapshot. The snapshot sorts nodes/edges/review_items
    by stable id and carries no wall-clock timestamp, so two calls on the same
    input produce byte-identical to_dict() output.
    """
    # Deduplicate nodes by stable node_id (identical units collapse to one node).
    nodes_by_id: dict[str, EvidenceGraphNode] = {}
    for unit in evidence_units:
        node = _node_from_unit(unit)
        nodes_by_id.setdefault(node.node_id, node)

    edges_by_id: dict[str, EvidenceGraphEdge] = {}
    review_by_id: dict[str, EvidenceReviewItem] = {}

    # Group nodes by source artifact so relationships stay within a document.
    by_artifact: dict[str, list[EvidenceGraphNode]] = defaultdict(list)
    for node in nodes_by_id.values():
        by_artifact[node.normalized_artifact_id].append(node)

    for artifact_id, group in by_artifact.items():
        group.sort(key=lambda n: n.node_id)
        claims = [n for n in group if n.node_type == _CLAIM_UNIT_TYPE]
        evidence_nodes = [n for n in group if n.node_type == "evidence"]

        # same_source: unordered pairs, emitted source<target for determinism.
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                edge = EvidenceGraphEdge(
                    source_node_id=a.node_id,
                    target_node_id=b.node_id,
                    relation=RELATION_SAME_SOURCE,
                    reason=f"both derived from normalized artifact {artifact_id}",
                )
                edges_by_id.setdefault(edge.edge_id, edge)

        # derives_from: each claim derives from each body node in the same artifact.
        for claim in claims:
            for body in evidence_nodes:
                edge = EvidenceGraphEdge(
                    source_node_id=claim.node_id,
                    target_node_id=body.node_id,
                    relation=RELATION_DERIVES_FROM,
                    reason="claim extracted from this body span",
                )
                edges_by_id.setdefault(edge.edge_id, edge)

        # ambiguous: truth relation between two co-sourced claims -> review item.
        for i, c1 in enumerate(claims):
            for c2 in claims[i + 1:]:
                item = EvidenceReviewItem(
                    node_ids=[c1.node_id, c2.node_id],
                    candidate_relations=list(AMBIGUOUS_CLAIM_RELATIONS),
                    reason=(
                        "relationship between two claims from the same source "
                        "requires human judgement; not auto-resolved"
                    ),
                )
                review_by_id.setdefault(item.review_item_id, item)

    return EvidenceGraphSnapshot(
        nodes=list(nodes_by_id.values()),
        edges=list(edges_by_id.values()),
        review_items=list(review_by_id.values()),
        policy_snapshot_hash=policy_snapshot_hash,
    )
