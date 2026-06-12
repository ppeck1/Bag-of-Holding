import importlib
from pathlib import Path

from app.core import planar_fixtures


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "planar_storage_v0_3_self_correction.json"


def test_fixture_pack_loads_extracted_atlas_data():
    pack = planar_fixtures.load_fixture_pack(FIXTURE_PATH)
    assert pack["fixture_pack_id"]
    assert len(pack["fixture_cases"]) == 25
    assert len(pack["plane_cards"]) == 13
    assert pack["coverage_summary"]["fixture_count"] == 25


def test_all_fixture_families_are_evaluated_with_explicit_mismatches():
    pack = planar_fixtures.load_fixture_pack(FIXTURE_PATH)
    report = planar_fixtures.evaluate_fixture_pack(pack)
    expected_families = {
        "baseline_pass",
        "scalar_theater",
        "temporal_gate",
        "authority_gate",
        "conflict_gate",
        "verification_gate",
        "schema_gate",
        "governance_health_gate",
        "dominance_policy_regression",
        "positive_edge",
        "role_mismatch",
        "source_trust_gate",
    }
    assert report["count"] == 25
    assert set(report["families"]) == expected_families
    assert report["passed"] + report["failed"] == 25
    for result in report["results"]:
        assert result["fixture_id"]
        assert result["actual"]["posture"] in {"answerable", "bounded", "review_required", "blocked"}
        assert isinstance(result["mismatches"], list)
        if not result["passed"]:
            assert result["mismatches"], result["fixture_id"]


def test_high_risk_fixture_families_are_not_skipped():
    pack = planar_fixtures.load_fixture_pack(FIXTURE_PATH)
    report = planar_fixtures.evaluate_fixture_pack(pack)
    by_family = {}
    for result in report["results"]:
        by_family.setdefault(result["family"], []).append(result)
    for family in {
        "source_trust_gate",
        "temporal_gate",
        "role_mismatch",
        "conflict_gate",
        "scalar_theater",
        "positive_edge",
    }:
        assert family in by_family
        assert all(r["actual"]["gate_result_id"] for r in by_family[family])


def test_fixture_mismatch_can_emit_mistake_event(tmp_path, monkeypatch):
    db_path = tmp_path / "boh.db"
    monkeypatch.setenv("BOH_DB", str(db_path))
    import app.db.connection as db
    db.DB_PATH = str(db_path)
    db.init_db()
    import app.core.correction_ledger as ledger
    importlib.reload(ledger)

    pack = planar_fixtures.load_fixture_pack(FIXTURE_PATH)
    case = dict(pack["fixture_cases"][0])
    case["expected_gate_result"] = {
        **case["expected_gate_result"],
        "posture": "blocked" if case["expected_gate_result"]["posture"] != "blocked" else "answerable",
    }
    result = planar_fixtures.evaluate_fixture_case(case, pack, emit_mistake=True)
    assert result["passed"] is False
    assert result["mistake_event"]
    events = db.fetchall("SELECT * FROM storage_events WHERE event_type = 'mistake_event_recorded'")
    assert len(events) == 1

