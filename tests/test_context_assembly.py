"""Acceptance tests for the Context Assembly service (Phase 6 / TASK 2.1).

The assembler composes the gate decision into one labeled AssembledContextPack;
these tests verify the five section labels, withheld declaration + disjointness,
no-bypass on blocked posture, read-only/no-canon, and determinism.
"""

from app.core.context_assembly import (
    SECTION_LABELS,
    AssembledContextPack,
    assemble,
)


def _pack(ref="card-1", plane="canonical", **overrides):
    pack = {
        "card_id": ref,
        "doc_id": f"doc-{ref}",
        "title": ref,
        "snippet": f"text for {ref}",
        "path": f"library/{ref}.md",
        "plane": plane,
        "authority_state": "approved",
        "source_trust": "local",
        "scalar_basis_ref": "sb-1",
        "why_selected": {"semantic_score": 0.9},
    }
    pack.update(overrides)
    return pack


def _assemble(packs, *, actor="reader", operation="answer_context", mode="exploration"):
    return assemble(
        query="q", operation=operation, actor=actor, mode=mode, candidate_packs=packs
    )


# ---------------------------------------------------------------------------
# Acceptance #1 -- five section labels, correct placement
# ---------------------------------------------------------------------------

def test_all_five_section_labels_present():
    a = _assemble([_pack()])
    assert set(a.to_dict()["sections"].keys()) == set(SECTION_LABELS)


def test_planes_land_in_expected_sections():
    a = _assemble([
        _pack(ref="c", plane="canonical"),
        _pack(ref="e", plane="evidence"),
        _pack(ref="i", plane="subjective"),
        _pack(ref="s", plane="informational"),
    ])
    refs = {label: [x["ref"] for x in entries] for label, entries in a.sections.items()}
    assert refs["canon"] == ["c"]
    assert sorted(refs["evidence"]) == ["e", "s"]  # informational -> evidence
    assert refs["interpretation"] == ["i"]


def test_conflict_pack_cross_listed_under_conflict():
    a = _assemble([_pack(ref="x", plane="evidence", conflict_set_ref="cs-1")])
    assert [e["ref"] for e in a.sections["conflict"]] == ["x"]
    # still present in its plane section too
    assert [e["ref"] for e in a.sections["evidence"]] == ["x"]


def test_missing_expected_plane_becomes_open_question():
    # answer_context expects "informational"; supplying only a canonical pack
    # leaves informational missing -> declared as an open question.
    a = _assemble([_pack(ref="c", plane="canonical")])
    assert "informational" in a.missing_planes
    open_planes = [e.get("plane") for e in a.sections["open_questions"] if e.get("type") == "missing_plane"]
    assert "informational" in open_planes
    assert a.posture == "bounded"  # warning-only, not blocked


# ---------------------------------------------------------------------------
# Acceptance #2 -- withheld declared and disjoint from content
# ---------------------------------------------------------------------------

def test_withheld_declared_and_disjoint_from_content():
    allowed = _pack(ref="ok", plane="canonical")
    withheld = _pack(ref="no", plane="evidence", blocked_use=["explain"])
    a = _assemble([allowed, withheld], operation="explain")

    assert a.posture == "review_required"  # routed, not blocked
    assert "no" in a.withheld["refs"]
    assert a.withheld["reasons"]

    # The withheld ref must not appear in any content section or the source map.
    in_sections = {e.get("ref") for entries in a.sections.values() for e in entries}
    assert "no" not in in_sections
    assert "no" not in a.source_map
    # The allowed ref is present.
    assert "ok" in a.source_map


# ---------------------------------------------------------------------------
# Acceptance #3 -- no context pack bypasses a failed gate
# ---------------------------------------------------------------------------

def test_blocked_posture_yields_empty_content():
    # reader attempting to promote is role-denied -> blocked.
    a = assemble(
        query="q", operation="promote", actor="reader", mode="strict",
        candidate_packs=[_pack()],
    )
    assert a.posture == "blocked"
    assert all(a.sections[label] == [] for label in SECTION_LABELS)
    assert a.source_map == {}
    # Only the withheld declaration carries information.
    assert a.withheld["reasons"]
    assert "actor_role_operation_denied" in a.withheld["reasons"]


# ---------------------------------------------------------------------------
# Acceptance #4 -- read-only, never canon-eligible
# ---------------------------------------------------------------------------

def test_assemble_performs_no_db_writes(monkeypatch):
    import app.db.connection as db

    def _boom(*a, **k):
        raise AssertionError("context assembly must not execute writes")

    monkeypatch.setattr(db, "execute", _boom, raising=False)
    monkeypatch.setattr(db, "executemany", _boom, raising=False)
    a = _assemble([_pack()])
    assert a.canon_eligible is False


def test_canon_eligible_forced_false_even_if_set():
    a = AssembledContextPack(
        context_pack_id="c", posture="answerable", operation="answer_context",
        canon_eligible=True,  # type: ignore[call-arg]
    )
    assert a.canon_eligible is False
    assert a.to_dict()["canon_eligible"] is False


# ---------------------------------------------------------------------------
# Acceptance #5 -- deterministic
# ---------------------------------------------------------------------------

def test_assembly_is_deterministic():
    packs = [_pack(ref="c", plane="canonical"), _pack(ref="e", plane="evidence")]
    a = _assemble(packs)
    b = _assemble(packs)
    assert a.to_dict() == b.to_dict()
    assert a.assembled_pack_id == b.assembled_pack_id


def test_assembled_pack_id_changes_with_content():
    base = _assemble([_pack(ref="c", plane="canonical")])
    grown = _assemble([_pack(ref="c", plane="canonical"), _pack(ref="e", plane="evidence")])
    assert base.assembled_pack_id != grown.assembled_pack_id
