"""Acceptance tests for the read-only CorrectionLoopService facade (TASK 1.3).

The facade composes existing Phase 8 records into one CorrectionLoopView; these
tests verify the aggregation is deterministic, read-only, derives the loop stage
correctly, surfaces residence, and never grants canon.
"""

import importlib

from app.core.correction_loop_service import (
    STAGE_ADJUDICATED,
    STAGE_DETECTED,
    STAGE_PROPOSED,
    STAGE_RECORDED,
    STAGE_RESOLVED,
    CorrectionLoopView,
    assemble,
    load,
)


def _mistake(mistake_id="mistake_1"):
    return {"mistake_id": mistake_id, "mistake_class": "source_poisoning", "severity": "high"}


def _proposal(patch_id="patch_1", status="proposed", proposed_from="mistake_1"):
    return {
        "patch_id": patch_id,
        "proposed_from": proposed_from,
        "proposal_type": "source_trust_patch",
        "status": status,
        "forbidden_auto_apply": 1,
    }


def _canon_change(canon_change_id="canon_change_1", patch_proposal_ref="patch_1"):
    return {
        "canon_change_id": canon_change_id,
        "patch_proposal_ref": patch_proposal_ref,
        "changed_objects": ["GateRule.source_trust"],
        "new_location_refs": ["GateRule.source_trust.quarantine_unknown"],
    }


def _residence(residence_id="residence_1", status="superseded"):
    return {
        "residence_id": residence_id,
        "original_ref": "legacy:unknown_trust_imports_unclassified",
        "current_ref": "GateRule.source_trust.quarantine_unknown",
        "current_location": "GateRule",
        "status": status,
        "human_readable_locator": "Current source-trust rule quarantines unknown imports.",
    }


# ---------------------------------------------------------------------------
# Loop-stage derivation
# ---------------------------------------------------------------------------

def test_stage_detected_when_mistake_only():
    v = assemble(_mistake())
    assert v.loop_stage == STAGE_DETECTED
    assert v.adjudication == "none"


def test_stage_proposed_when_unreviewed_proposal():
    v = assemble(_mistake(), [_proposal(status="proposed")])
    assert v.loop_stage == STAGE_PROPOSED
    assert v.adjudication == "proposed"


def test_stage_adjudicated_when_rejected_without_canon_change():
    v = assemble(_mistake(), [_proposal(status="rejected")])
    assert v.loop_stage == STAGE_ADJUDICATED
    assert v.adjudication == "rejected"


def test_stage_recorded_when_canon_change_present():
    v = assemble(_mistake(), [_proposal(status="approved")], [_canon_change()])
    assert v.loop_stage == STAGE_RECORDED


def test_stage_resolved_when_residence_supersedes():
    v = assemble(
        _mistake(), [_proposal(status="approved")], [_canon_change()], [_residence()]
    )
    assert v.loop_stage == STAGE_RESOLVED


def test_adjudication_mixed_when_statuses_differ():
    v = assemble(
        _mistake(),
        [_proposal(patch_id="p1", status="approved"), _proposal(patch_id="p2", status="rejected")],
        [_canon_change(patch_proposal_ref="p1")],
    )
    assert v.adjudication == "mixed"


# ---------------------------------------------------------------------------
# Residence surfaced (acceptance #4)
# ---------------------------------------------------------------------------

def test_residence_surfaced_in_view():
    v = assemble(
        _mistake(), [_proposal(status="approved")], [_canon_change()], [_residence()]
    )
    assert v.residence
    assert v.residence[0]["current_location"] == "GateRule"
    assert v.residence[0]["human_readable_locator"]


# ---------------------------------------------------------------------------
# No auto-canon (acceptance #5)
# ---------------------------------------------------------------------------

def test_view_never_canon_eligible_and_always_forbidden_auto_apply():
    v = assemble(_mistake(), [_proposal(status="approved")], [_canon_change()])
    assert v.canon_eligible is False
    assert v.forbidden_auto_apply is True
    assert v.to_dict()["canon_eligible"] is False
    assert v.to_dict()["forbidden_auto_apply"] is True


def test_view_forced_non_canon_even_if_set():
    v = CorrectionLoopView(
        mistake_id="m", canon_eligible=True, forbidden_auto_apply=False  # type: ignore[call-arg]
    )
    assert v.canon_eligible is False
    assert v.forbidden_auto_apply is True


# ---------------------------------------------------------------------------
# Determinism (acceptance #6)
# ---------------------------------------------------------------------------

def test_assemble_is_deterministic():
    args = (_mistake(), [_proposal(status="approved")], [_canon_change()], [_residence()])
    a = assemble(*args)
    b = assemble(*args)
    assert a.to_dict() == b.to_dict()
    assert a.view_id == b.view_id


def test_view_id_changes_with_chain():
    base = assemble(_mistake())
    grown = assemble(_mistake(), [_proposal()])
    assert base.view_id != grown.view_id


# ---------------------------------------------------------------------------
# Read-only loader over the real ledger
# ---------------------------------------------------------------------------

def _fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "boh.db"
    monkeypatch.setenv("BOH_DB", str(db_path))
    import app.db.connection as db
    db.DB_PATH = str(db_path)
    db.init_db()
    import app.core.correction_ledger as ledger
    importlib.reload(ledger)
    return db, ledger


def test_load_composes_full_chain_from_ledger(tmp_path, monkeypatch):
    db, ledger = _fresh_db(tmp_path, monkeypatch)
    mistake = ledger.record_mistake_event(
        detected_from="fixture",
        operation="approve",
        context_pack_ref="ctx_source_poisoning",
        mistake_class="source_poisoning",
    )
    proposal = ledger.create_patch_proposal(
        proposed_from=mistake["mistake_id"],
        proposal_type="source_trust_patch",
        proposed_change="Quarantine unknown-trust imports.",
        evidence_refs=["FixtureCase.source_poisoning_quarantine"],
    )
    ledger.approve_patch_proposal(
        proposal["patch_id"],
        approved_by="authority_owner_01",
        changed_objects=["GateRule.source_trust"],
        new_location_refs=["GateRule.source_trust.quarantine_unknown"],
        migration_note="Unknown-trust imports quarantined.",
        regression_fixture_refs=["source_poisoning_quarantine"],
        residence_updates=[{
            "original_ref": "GateRule.source_trust.quarantine_unknown",
            "current_ref": "GateRule.source_trust.quarantine_unknown",
            "current_location": "GateRule",
            "status": "superseded",
            "reason": "Fixture caught source-poisoning false allow.",
            "human_readable_locator": "Current source-trust rule quarantines unknown imports.",
        }],
    )

    view = load(mistake["mistake_id"])
    assert view.mistake_id == mistake["mistake_id"]
    assert len(view.proposals) == 1
    assert len(view.canon_change_records) == 1
    assert view.loop_stage == STAGE_RESOLVED
    assert view.residence and view.residence[0]["current_location"] == "GateRule"


def test_load_performs_no_db_writes(tmp_path, monkeypatch):
    db, ledger = _fresh_db(tmp_path, monkeypatch)
    mistake = ledger.record_mistake_event(
        detected_from="fixture",
        operation="approve",
        context_pack_ref="ctx_1",
        mistake_class="source_poisoning",
    )
    # After setup, any write must raise -- load() reads only.
    def _boom(*a, **k):
        raise AssertionError("correction loop facade must not execute writes")

    monkeypatch.setattr(db, "execute", _boom, raising=False)
    monkeypatch.setattr(db, "executemany", _boom, raising=False)
    view = load(mistake["mistake_id"])
    assert view.mistake_id == mistake["mistake_id"]
    assert view.loop_stage == STAGE_DETECTED
