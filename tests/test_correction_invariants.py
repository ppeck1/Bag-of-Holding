"""Negative-invariant coverage for the Phase 8 correction loop (TASK 1.3).

The buildspec implies but does not directly pin these guarantees: there is no
auto-apply path, forbidden_auto_apply cannot be overridden to False in storage,
a rejected proposal never produces a CanonChangeRecord, and the read-only loop
view never grants canon eligibility.
"""

import importlib

from app.core import correction_loop_service


def _fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "boh.db"
    monkeypatch.setenv("BOH_DB", str(db_path))
    import app.db.connection as db
    db.DB_PATH = str(db_path)
    db.init_db()
    import app.core.correction_ledger as ledger
    importlib.reload(ledger)
    return db, ledger


def _proposal(ledger, *, forbidden_auto_apply=False):
    mistake = ledger.record_mistake_event(
        detected_from="fixture",
        operation="approve",
        context_pack_ref="ctx_source_poisoning",
        mistake_class="source_poisoning",
    )
    return ledger.create_patch_proposal(
        proposed_from=mistake["mistake_id"],
        proposal_type="source_trust_patch",
        proposed_change="Quarantine unknown-trust imports.",
        evidence_refs=["FixtureCase.source_poisoning_quarantine"],
        forbidden_auto_apply=forbidden_auto_apply,
    )


# ---------------------------------------------------------------------------
# No auto-apply path exists (acceptance #2)
# ---------------------------------------------------------------------------

def test_correction_ledger_exposes_no_auto_apply_callable():
    import app.core.correction_ledger as ledger

    callables = {n for n in dir(ledger) if callable(getattr(ledger, n)) and not n.startswith("_")}
    # The only mutation that takes effect is human approval; nothing auto-applies.
    offenders = {n for n in callables if "auto_apply" in n or "apply_patch" in n or n == "apply"}
    assert not offenders, f"unexpected auto-apply callable(s): {offenders}"


def test_forbidden_auto_apply_cannot_be_set_false_in_storage(tmp_path, monkeypatch):
    _db, ledger = _fresh_db(tmp_path, monkeypatch)
    proposal = _proposal(ledger, forbidden_auto_apply=False)
    # Caller asked for False; storage forces the human-gate invariant.
    assert proposal["forbidden_auto_apply"] == 1
    assert ledger.get_patch_proposal(proposal["patch_id"])["forbidden_auto_apply"] == 1


# ---------------------------------------------------------------------------
# Approval is the only route to a CanonChangeRecord (acceptance #3)
# ---------------------------------------------------------------------------

def test_rejected_proposal_yields_no_canon_change_record(tmp_path, monkeypatch):
    _db, ledger = _fresh_db(tmp_path, monkeypatch)
    proposal = _proposal(ledger)
    ledger.reject_patch_proposal(
        proposal["patch_id"], reviewed_by="authority_owner_01", review_note="No."
    )
    assert ledger.list_canon_change_records() == []


# ---------------------------------------------------------------------------
# Read-only + never canon-eligible (acceptance #5)
# ---------------------------------------------------------------------------

def test_assemble_never_canon_eligible_and_writes_nothing(monkeypatch):
    import app.db.connection as db

    def _boom(*a, **k):
        raise AssertionError("correction loop facade must not execute writes")

    monkeypatch.setattr(db, "execute", _boom, raising=False)
    monkeypatch.setattr(db, "executemany", _boom, raising=False)

    view = correction_loop_service.assemble(
        {"mistake_id": "m1", "mistake_class": "x"},
        [{"patch_id": "p1", "proposed_from": "m1", "status": "approved"}],
        [{"canon_change_id": "c1", "patch_proposal_ref": "p1"}],
    )
    assert view.canon_eligible is False
    assert view.forbidden_auto_apply is True
    assert view.loop_stage in {
        correction_loop_service.STAGE_RECORDED,
        correction_loop_service.STAGE_RESOLVED,
    }
