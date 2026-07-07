import importlib


def _fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "boh.db"
    monkeypatch.setenv("BOH_DB", str(db_path))
    import app.db.connection as db
    db.DB_PATH = str(db_path)
    db.init_db()
    import app.core.correction_ledger as ledger
    importlib.reload(ledger)
    return db, ledger


def _mistake(ledger):
    return ledger.record_mistake_event(
        detected_from="fixture",
        operation="approve",
        actor_ref="approver_01",
        context_pack_ref="ctx_source_poisoning",
        expected_gate_result_ref="expected_gate_result:source_poisoning",
        actual_gate_result_ref="actual_gate_result:prepatch",
        mistake_class="source_poisoning",
        impacted_refs=["pc_unknown_source", "GateRule.source_trust"],
        severity="high",
        detail={"reason": "unknown trust source would have been allowed"},
    )


def _proposal(ledger):
    mistake = _mistake(ledger)
    return ledger.create_patch_proposal(
        proposed_from=mistake["mistake_id"],
        proposal_type="source_trust_patch",
        proposed_change="Unknown-trust imported sources must be quarantined.",
        evidence_refs=["FixtureCase.source_poisoning_quarantine"],
        blast_radius="domain",
        requires_review_by="authority_owner",
        detail={"forbidden_auto_apply": False},
        forbidden_auto_apply=False,
    )


def test_correction_ledger_tables_created_on_fresh_db(tmp_path, monkeypatch):
    db, _ledger = _fresh_db(tmp_path, monkeypatch)
    tables = {
        row["name"]
        for row in db.fetchall(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'planar_%'"
        )
    }
    assert {
        "planar_gate_results",
        "planar_mistake_events",
        "planar_patch_proposals",
        "planar_canon_change_records",
        "planar_information_residence_map",
        "planar_fixture_cases",
    } <= tables


def test_record_gate_result_creates_storage_event(tmp_path, monkeypatch):
    db, ledger = _fresh_db(tmp_path, monkeypatch)
    stored = ledger.record_gate_result(
        {"context_pack_id": "ctx_1", "query": "q", "operation": "answer_context", "actor_id": "retrieval_connector", "mode": "strict_answer"},
        {
            "gate_result_id": "gate_1",
            "context_pack_id": "ctx_1",
            "posture": "answerable",
            "blocking_reasons": [],
            "warning_reasons": [],
            "allowed_context_refs": ["chunk_1"],
            "withheld_context_refs": [],
            "trace_event_type": "gate_passed",
        },
    )
    assert stored["gate_result_id"] == "gate_1"
    events = db.fetchall("SELECT * FROM storage_events WHERE event_type = 'planar_gate_result_recorded'")
    assert len(events) == 1


def test_create_patch_proposal_forbidden_auto_apply_is_forced_true(tmp_path, monkeypatch):
    _db, ledger = _fresh_db(tmp_path, monkeypatch)
    proposal = _proposal(ledger)
    assert proposal["status"] == "proposed"
    assert proposal["forbidden_auto_apply"] == 1
    assert proposal["proposal_type"] == "source_trust_patch"


def test_approve_patch_requires_regression_fixture_refs(tmp_path, monkeypatch):
    _db, ledger = _fresh_db(tmp_path, monkeypatch)
    proposal = _proposal(ledger)
    result = ledger.approve_patch_proposal(
        proposal["patch_id"],
        approved_by="authority_owner_01",
        changed_objects=["GateRule.source_trust"],
        new_location_refs=["GateRule.source_trust.quarantine_unknown"],
        migration_note="Should fail without fixtures.",
    )
    assert result == {"success": False, "error": "regression_fixture_refs_required"}
    assert ledger.get_patch_proposal(proposal["patch_id"])["status"] == "proposed"


def test_approved_patch_creates_canon_change_record(tmp_path, monkeypatch):
    _db, ledger = _fresh_db(tmp_path, monkeypatch)
    proposal = _proposal(ledger)
    result = ledger.approve_patch_proposal(
        proposal["patch_id"],
        approved_by="authority_owner_01",
        changed_objects=["GateRule.source_trust"],
        old_location_refs=["GateRule.source_trust.prepatch"],
        new_location_refs=["GateRule.source_trust.quarantine_unknown"],
        supersedes_refs=["legacy:unknown_trust_imports_unclassified"],
        migration_note="Unknown-trust imported sources are quarantined.",
        regression_fixture_refs=["source_poisoning_quarantine"],
        trace_event_ref="trace_canon_change_source_trust_001",
    )
    assert result["success"] is True
    assert result["patch_proposal"]["status"] == "approved"
    assert result["patch_proposal"]["forbidden_auto_apply"] == 1
    change = result["canon_change_record"]
    assert change["patch_proposal_ref"] == proposal["patch_id"]
    assert change["changed_objects"] == ["GateRule.source_trust"]
    assert change["regression_fixture_refs"] == ["source_poisoning_quarantine"]


def test_information_residence_map_answers_current_location(tmp_path, monkeypatch):
    _db, ledger = _fresh_db(tmp_path, monkeypatch)
    proposal = _proposal(ledger)
    result = ledger.approve_patch_proposal(
        proposal["patch_id"],
        approved_by="authority_owner_01",
        changed_objects=["GateRule.source_trust"],
        new_location_refs=["GateRule.source_trust.quarantine_unknown"],
        migration_note="Unknown trust source rule moved.",
        regression_fixture_refs=["source_poisoning_quarantine"],
        residence_updates=[
            {
                "original_ref": "legacy:unknown_trust_imports_unclassified",
                "current_ref": "GateRule.source_trust.quarantine_unknown",
                "current_location": "GateRule",
                "status": "superseded",
                "reason": "Fixture caught source-poisoning false allow.",
                "human_readable_locator": "Current source-trust rule quarantines unknown imports.",
            }
        ],
    )
    assert result["success"] is True
    residence = ledger.get_information_residence("legacy:unknown_trust_imports_unclassified")
    assert residence["current_ref"] == "GateRule.source_trust.quarantine_unknown"
    assert residence["current_location"] == "GateRule"
    assert residence["status"] == "superseded"


def test_reject_patch_does_not_create_canon_change_record(tmp_path, monkeypatch):
    _db, ledger = _fresh_db(tmp_path, monkeypatch)
    proposal = _proposal(ledger)
    rejected = ledger.reject_patch_proposal(
        proposal["patch_id"],
        reviewed_by="authority_owner_01",
        review_note="Not accepted.",
    )
    assert rejected["success"] is True
    assert rejected["status"] == "rejected"
    assert ledger.list_canon_change_records() == []

