"""Acceptance tests for the Phase 4 Evidence Graph Service.

Covers: deterministic output, ambiguous-relationship review items,
provenance/hash preservation, empty input, and the canon_eligible invariant.
"""

from app.core.planar_service_schemas import (
    EvidenceGraphSnapshot,
    EvidenceUnit,
)
from app.services.intake.evidence_graph import (
    AMBIGUOUS_CLAIM_RELATIONS,
    RELATION_DERIVES_FROM,
    RELATION_SAME_SOURCE,
    build_graph,
)


def _unit(artifact, start, end, unit_type, text_hash, authority="none"):
    return EvidenceUnit(
        normalized_artifact_id=artifact,
        span_start=start,
        span_end=end,
        unit_type=unit_type,
        text_hash=text_hash,
        authority_default=authority,
    )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_build_graph_is_deterministic():
    units = [
        _unit("art_a", 0, 10, "body", "h1"),
        _unit("art_a", 10, 20, "claim", "h2"),
        _unit("art_b", 0, 5, "body", "h3"),
    ]
    snap1 = build_graph(units)
    snap2 = build_graph(units)
    assert snap1.to_dict() == snap2.to_dict()
    assert snap1.snapshot_id == snap2.snapshot_id


def test_build_graph_deterministic_regardless_of_input_order():
    units = [
        _unit("art_a", 0, 10, "body", "h1"),
        _unit("art_a", 10, 20, "claim", "h2"),
        _unit("art_b", 0, 5, "body", "h3"),
    ]
    snap_forward = build_graph(units)
    snap_reversed = build_graph(list(reversed(units)))
    assert snap_forward.to_dict() == snap_reversed.to_dict()


def test_policy_snapshot_hash_changes_snapshot_id():
    units = [_unit("art_a", 0, 10, "body", "h1")]
    a = build_graph(units, policy_snapshot_hash="p1")
    b = build_graph(units, policy_snapshot_hash="p2")
    assert a.snapshot_id != b.snapshot_id


# ---------------------------------------------------------------------------
# Ambiguity -> review items (never a guessed edge)
# ---------------------------------------------------------------------------

def test_two_claims_same_source_produce_review_item_not_edge():
    units = [
        _unit("art_a", 0, 10, "claim", "h1"),
        _unit("art_a", 10, 20, "claim", "h2"),
    ]
    snap = build_graph(units)

    assert snap.review_item_count == 1
    item = snap.review_items[0]
    assert sorted(item.candidate_relations) == sorted(AMBIGUOUS_CLAIM_RELATIONS)
    assert len(item.node_ids) == 2

    # No guessed truth-relation edge was emitted between the two claims.
    relations = {e.relation for e in snap.edges}
    assert "supports" not in relations
    assert "contradicts" not in relations
    # The factual co-location edge is still present.
    assert RELATION_SAME_SOURCE in relations


def test_no_review_item_for_single_claim():
    units = [
        _unit("art_a", 0, 10, "body", "h1"),
        _unit("art_a", 10, 20, "claim", "h2"),
    ]
    snap = build_graph(units)
    assert snap.review_item_count == 0


# ---------------------------------------------------------------------------
# Edge derivation
# ---------------------------------------------------------------------------

def test_same_source_edge_within_artifact_only():
    units = [
        _unit("art_a", 0, 10, "body", "h1"),
        _unit("art_a", 10, 20, "body", "h2"),
        _unit("art_b", 0, 5, "body", "h3"),
    ]
    snap = build_graph(units)
    same_source = [e for e in snap.edges if e.relation == RELATION_SAME_SOURCE]
    # Only the two art_a nodes are co-sourced; art_b stands alone.
    assert len(same_source) == 1
    pair = {same_source[0].source_node_id, same_source[0].target_node_id}
    art_a_nodes = {n.node_id for n in snap.nodes if n.normalized_artifact_id == "art_a"}
    assert pair == art_a_nodes


def test_derives_from_edge_claim_to_body():
    units = [
        _unit("art_a", 0, 10, "body", "h1"),
        _unit("art_a", 10, 20, "claim", "h2"),
    ]
    snap = build_graph(units)
    derives = [e for e in snap.edges if e.relation == RELATION_DERIVES_FROM]
    assert len(derives) == 1
    claim_node = next(n for n in snap.nodes if n.node_type == "claim")
    body_node = next(n for n in snap.nodes if n.node_type == "evidence")
    assert derives[0].source_node_id == claim_node.node_id
    assert derives[0].target_node_id == body_node.node_id


# ---------------------------------------------------------------------------
# Provenance / hash preservation
# ---------------------------------------------------------------------------

def test_nodes_preserve_span_and_text_hash():
    units = [_unit("art_a", 3, 17, "body", "deadbeef", authority="advisory")]
    snap = build_graph(units)
    assert snap.node_count == 1
    node = snap.nodes[0]
    assert node.text_hash == "deadbeef"
    assert node.span_start == 3
    assert node.span_end == 17
    assert node.authority_default == "advisory"
    assert node.evidence_unit_id == units[0].evidence_unit_id


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------

def test_empty_input_yields_empty_snapshot():
    snap = build_graph([])
    assert snap.node_count == 0
    assert snap.edge_count == 0
    assert snap.review_item_count == 0
    assert snap.to_dict()["nodes"] == []


# ---------------------------------------------------------------------------
# canon_eligible invariant
# ---------------------------------------------------------------------------

def test_canon_eligible_never_true_on_nodes():
    units = [_unit("art_a", 0, 10, "claim", "h1")]
    snap = build_graph(units)
    assert all(n.canon_eligible is False for n in snap.nodes)
    assert snap.canon_eligible is False


def test_canon_eligible_forced_false_even_if_set():
    snap = EvidenceGraphSnapshot(canon_eligible=True)  # type: ignore[call-arg]
    assert snap.canon_eligible is False


def test_duplicate_units_collapse_to_one_node():
    u = _unit("art_a", 0, 10, "body", "h1")
    snap = build_graph([u, u])
    assert snap.node_count == 1
