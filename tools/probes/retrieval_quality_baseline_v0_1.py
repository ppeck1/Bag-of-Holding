"""RQ-2 synthetic judged retrieval baseline and surface characterization.

The probe has no real-database option.  Every run creates a disposable database,
library directory, and data root, seeds only the versioned synthetic deck, and
normalizes surface output to identifiers and policy metadata (never snippets).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


SURFACE_ORDER = (
    "api_retrieve",
    "current_context_brief",
    "query_context_object",
    "mcp_retrieve_context",
    "keyword_search",
)
SURFACE_CAPABILITIES = {
    "api_retrieve": {
        "role": "governed_answer_retrieval",
        "invocation_kind": "core_equivalent",
        "ranking": "governed_context_packs",
        "answerability": "derived_from_gate_allowed_refs",
        "withholding": "native_excluded_summary_and_gate",
        "filters": ["doc_id", "status", "authority_state", "canonical_layer", "project", "chunk_type"],
        "promoted_visibility": "dual_gate",
    },
    "current_context_brief": {
        "role": "governed_brief",
        "invocation_kind": "core_equivalent",
        "ranking": "best_evidence",
        "answerability": "native_answerable_now",
        "withholding": "native_withheld",
        "filters": [],
        "promoted_visibility": "dual_gate",
    },
    "query_context_object": {
        "role": "raw_query_context",
        "invocation_kind": "core_equivalent",
        "ranking": "raw_evidence",
        "answerability": "unsupported",
        "withholding": "unsupported",
        "filters": [],
        "promoted_visibility": "dual_gate",
    },
    "mcp_retrieve_context": {
        "role": "raw_mcp_candidates_plus_exploration_assembly",
        "invocation_kind": "core_equivalent",
        "ranking": "raw_context_packs",
        "answerability": "unsupported",
        "withholding": "aggregate_exploration_assembly",
        "filters": ["project"],
        "promoted_visibility": "dual_gate",
    },
    "keyword_search": {
        "role": "document_discovery",
        "invocation_kind": "core_equivalent",
        "ranking": "whole_document_results",
        "answerability": "unsupported",
        "withholding": "unsupported",
        "filters": [
            "library_id", "plane_filter", "dimension", "state", "min_quality",
            "min_confidence", "stale", "uncertain_only", "conflicts_only",
        ],
        "promoted_visibility": "environment_gate_only",
    },
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_deck_path() -> Path:
    return repo_root() / "tests" / "fixtures" / "retrieval_quality" / "judged_deck_v0_1.json"


def _force_repo_imports() -> None:
    root = str(repo_root())
    sys.path = [root] + [entry for entry in sys.path if entry != root]
    sys.meta_path = [finder for finder in sys.meta_path if finder.__class__.__name__ != "_EditableFinder"]


def load_deck(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    deck = json.loads(raw.decode("utf-8"))
    from app.core import retrieval_evaluation

    retrieval_evaluation.validate_deck(deck)
    return deck, hashlib.sha256(raw).hexdigest()


def _epoch(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def _seed_fixture(deck: dict[str, Any], db: Any) -> None:
    """Seed the judged IDs directly into the disposable database."""

    conn = db.get_conn()
    try:
        for document in deck["documents"]:
            texts = [str(chunk["text"]) for chunk in document["chunks"]]
            content = "\n\n".join(texts)
            updated_ts = _epoch(document.get("epistemic_last_evaluated")) or 1_735_689_600
            topics = " ".join(sorted(set(content.lower().split())))
            conn.execute(
                """
                INSERT INTO docs
                  (doc_id, path, type, status, version, updated_ts,
                   operator_state, operator_intent, plane_scope_json,
                   field_scope_json, node_scope_json, text_hash, source_type,
                   topics_tokens, corpus_class, title, summary, project,
                   document_class, canonical_layer, authority_state, review_state,
                   provenance_json, source_hash, document_id,
                   epistemic_last_evaluated, epistemic_valid_until)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    document["doc_id"], document["path"], "note", document["status"],
                    document.get("document_version") or "1.0.0", updated_ts,
                    "observe", "capture", "[]", "[]", "[]",
                    hashlib.sha256(content.encode("utf-8")).hexdigest(), "synthetic_fixture",
                    topics, document["corpus_class"], document["title"], content[:220],
                    document.get("project"), "note", document["canonical_layer"],
                    document["authority_state"], "none",
                    json.dumps({"mode": "synthetic_rq2_fixture", "deck_id": deck["deck_id"]}),
                    f"synthetic-{document['doc_id']}", document["doc_id"],
                    document.get("epistemic_last_evaluated"), document.get("epistemic_valid_until"),
                ),
            )
            conn.execute(
                "INSERT INTO docs_fts(content, title, path, topics) VALUES (?,?,?,?)",
                (content, document["title"], document["path"], topics),
            )
            for chunk in document["chunks"]:
                text_value = str(chunk["text"])
                token_count = len(text_value.split())
                text_hash = hashlib.sha256(text_value.encode("utf-8")).hexdigest()
                conn.execute(
                    """
                    INSERT INTO doc_chunks
                      (chunk_id, doc_id, path, chunk_index, heading_path,
                       byte_start, byte_end, token_start, token_end, source_hash,
                       text_hash, chunk_type, text, lifecycle_state, authority_state,
                       status, canonical_layer, metadata_json, created_ts)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        chunk["chunk_id"], document["doc_id"], document["path"],
                        int(chunk.get("chunk_index", 0)), chunk.get("heading_path") or "",
                        0, len(text_value.encode("utf-8")), 0, token_count,
                        f"synthetic-{document['doc_id']}", text_hash,
                        chunk.get("chunk_type") or "body", text_value, "current",
                        document["authority_state"], document["status"],
                        document["canonical_layer"], "{}", 1_735_689_600,
                    ),
                )
                conn.execute(
                    "INSERT INTO doc_chunks_fts(chunk_id, doc_id, heading_path, content) VALUES (?,?,?,?)",
                    (chunk["chunk_id"], document["doc_id"], chunk.get("heading_path") or "", text_value),
                )

            for coordinate in document.get("daenary") or []:
                conn.execute(
                    """
                    INSERT INTO doc_coordinates
                      (doc_id, dimension, state, quality, confidence, mode,
                       observed_ts, valid_until_ts, source)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        document["doc_id"], coordinate["dimension"], int(coordinate["state"]),
                        coordinate.get("quality"), coordinate.get("confidence"), coordinate.get("mode"),
                        updated_ts, _epoch(coordinate.get("valid_until")), "synthetic_rq2_fixture",
                    ),
                )

            card = document.get("plane_card")
            if card:
                payload = {
                    "title": document["title"],
                    "path": document["path"],
                    "status": document["status"],
                    "authority_state": document["authority_state"],
                    "canonical_layer": document["canonical_layer"],
                    "non_authoritative": bool(card.get("non_authoritative")),
                    "confidence": float(card.get("confidence", 0.5)),
                    "epistemic_c": float(card.get("confidence", 0.5)),
                    "state": "active",
                }
                conn.execute(
                    """
                    INSERT INTO cards
                      (id, plane, card_type, topic, b, d, m, delta_json,
                       constraints_json, authority_json, observed_at, valid_until,
                       context_ref_json, payload_json, doc_id, created_ts,
                       updated_ts, plane_card_version)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        f"fixture-card:{document['doc_id']}", str(card.get("plane") or "informational"),
                        "source_document", document["title"], 0, 0, "contain", "{}", "{}",
                        json.dumps({"state": document["authority_state"]}),
                        document.get("epistemic_last_evaluated"), card.get("valid_until"),
                        json.dumps({"source_id": f"DOC:synthetic:{document['doc_id']}"}),
                        json.dumps(payload), document["doc_id"], 1_735_689_600, 1_735_689_600, 1,
                    ),
                )

        conflict_pairs: set[tuple[str, str]] = set()
        for document in deck["documents"]:
            for related in document.get("conflicts_with") or []:
                pair = tuple(sorted((document["doc_id"], str(related))))
                if pair in conflict_pairs:
                    continue
                conflict_pairs.add(pair)
                conn.execute(
                    "INSERT INTO conflicts (conflict_type, doc_ids, term, plane_path, detected_ts, acknowledged) VALUES (?,?,?,?,?,?)",
                    ("definition_conflict", ",".join(pair), "synthetic_conflict", "synthetic", 1_735_689_600, 0),
                )
            superseded_by = document.get("superseded_by")
            if superseded_by:
                conn.execute(
                    "INSERT INTO lineage (doc_id, related_doc_id, relationship, detected_ts, detail) VALUES (?,?,?,?,?)",
                    (document["doc_id"], str(superseded_by), "superseded_by", 1_735_689_600, "synthetic_rq2_fixture"),
                )
        conn.commit()
    finally:
        conn.close()


@contextmanager
def _promoted_gate(enabled: bool):
    key = "BOH_RETRIEVAL_INCLUDE_PROMOTED"
    previous = os.environ.get(key)
    if enabled:
        os.environ[key] = "true"
    else:
        os.environ.pop(key, None)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def _supported_retrieval_filters(case: dict[str, Any]) -> dict[str, Any]:
    allowed = set(SURFACE_CAPABILITIES["api_retrieve"]["filters"])
    return {key: value for key, value in case["filters"].items() if key in allowed and value is not None}


def _search_library_id(requested: str | None) -> str | None:
    if not requested:
        return None
    if requested == "unfiled":
        return "unfiled"
    from app.core import logical_libraries

    suffix = requested.removeprefix("lib-")
    for library in logical_libraries.list_logical_libraries(include_hidden=True):
        if library.prefix == suffix or library.id == requested:
            return library.id
    return requested


def _invoke_surface(surface: str, case: dict[str, Any], limit: int) -> dict[str, Any] | list[dict[str, Any]]:
    from app.core import context_object, current_context_brief, retrieval
    from app.core import search as search_engine
    from tools.boh_mcp_adapter.adapter import BohMcpAdapter

    query = case["query"]
    request_promoted = bool(case["exposure"]["request_include_promoted"])
    if surface == "api_retrieve":
        return retrieval.retrieve_governed(
            query,
            mode=case["mode"],
            limit=limit,
            filters=_supported_retrieval_filters(case),
            max_context_chars=6000,
            include_promoted=request_promoted,
        )
    if surface == "current_context_brief":
        return current_context_brief.build_current_context_brief(
            query,
            limit=limit,
            mode=case["mode"],
            include_promoted=request_promoted,
            max_context_chars=6000,
        )
    if surface == "query_context_object":
        return context_object.assemble(
            "query", query, evidence_limit=limit, include_promoted=request_promoted,
            question_type="exploratory",
        )
    if surface == "mcp_retrieve_context":
        return BohMcpAdapter().retrieve_context(
            query,
            project=case["filters"].get("project"),
            limit=limit,
            include_promoted=request_promoted,
        )
    if surface == "keyword_search":
        filters = case["filters"]
        return search_engine.search(
            query,
            plane_filter=filters.get("plane_filter"),
            library_id=_search_library_id(filters.get("library_id")),
            limit=limit,
            dimension=filters.get("dimension"),
            state=filters.get("state"),
            min_quality=filters.get("min_quality"),
            min_confidence=filters.get("min_confidence"),
            stale=bool(filters.get("stale", False)),
            uncertain_only=bool(filters.get("uncertain_only", False)),
            conflicts_only=bool(filters.get("conflicts_only", False)),
        )
    raise ValueError(f"unknown surface: {surface}")


def _ranked_items(surface: str, response: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if surface == "api_retrieve":
        values = response.get("context_packs", [])  # type: ignore[union-attr]
    elif surface == "current_context_brief":
        values = response.get("best_evidence", [])  # type: ignore[union-attr]
    elif surface == "query_context_object":
        values = response.get("evidence", [])  # type: ignore[union-attr]
    elif surface == "mcp_retrieve_context":
        values = response.get("context_packs", [])  # type: ignore[union-attr]
    else:
        values = response
    items: list[dict[str, Any]] = []
    for value in values or []:
        if not isinstance(value, dict) or not value.get("doc_id"):
            continue
        item = {"doc_id": str(value["doc_id"]), "chunk_id": value.get("chunk_id")}
        if value.get("score") is not None:
            item["score"] = value.get("score")
        elif value.get("final_score") is not None:
            item["score"] = value.get("final_score")
        for key in ("status", "authority_state", "canonical_layer"):
            if value.get(key) is not None:
                item[key] = value.get(key)
        freshness = value.get("freshness")
        if isinstance(freshness, dict):
            item["freshness"] = {
                key: freshness.get(key)
                for key in ("age_days", "source", "valid_until", "superseded", "superseded_by")
                if freshness.get(key) is not None
            }
        if isinstance(value.get("conflicts"), list):
            item["conflict_count"] = len(value["conflicts"])
        items.append(item)
    return items


def _withheld_reasons(surface: str, response: dict[str, Any] | list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    if not isinstance(response, dict):
        return reasons
    if surface == "api_retrieve":
        reasons.extend(str(item.get("reason")) for item in response.get("excluded_summary", []) if item.get("reason"))
        gate = response.get("gate_result") or {}
        reasons.extend(str(value) for value in gate.get("blocking_reasons", []) if value)
    elif surface == "current_context_brief":
        reasons.extend(str(item.get("reason")) for item in response.get("withheld", []) if item.get("reason"))
    elif surface == "mcp_retrieve_context":
        assembled = response.get("assembled_context_pack") or {}
        withheld = assembled.get("withheld") or {}
        reasons.extend(str(value) for value in withheld.get("reasons", []) if value)
    return list(dict.fromkeys(reasons))


def _answerable(surface: str, response: dict[str, Any] | list[dict[str, Any]]) -> bool | None:
    if not isinstance(response, dict):
        return None
    if surface == "current_context_brief":
        value = response.get("answerable_now")
        return value if isinstance(value, bool) else None
    if surface == "api_retrieve":
        gate = response.get("gate_result") or {}
        if gate.get("posture") == "blocked":
            return False
        allowed = {str(value) for value in gate.get("allowed_context_refs", []) if value}
        packs = response.get("context_packs") or []
        returned = {
            str(pack.get("card_id") or pack.get("chunk_id") or pack.get("doc_id"))
            for pack in packs
            if pack.get("card_id") or pack.get("chunk_id") or pack.get("doc_id")
        }
        return bool(allowed & returned)
    return None


def _applicability(surface: str, case: dict[str, Any]) -> tuple[bool, str | None]:
    filters = set(case["filters"])
    supported = set(SURFACE_CAPABILITIES[surface]["filters"])
    unsupported = sorted(filters - supported)
    if unsupported:
        return False, "unsupported_filters:" + ",".join(unsupported)
    if surface in {"query_context_object", "mcp_retrieve_context", "keyword_search"} and case["mode"] != "exploration":
        return False, "surface_has_no_requested_governed_mode"
    if (
        surface == "keyword_search"
        and case["category"] == "promoted_only"
        and case["exposure"]["server_promoted_gate"]
        and not case["exposure"]["request_include_promoted"]
    ):
        return False, "surface_uses_environment_only_promoted_gate"
    return True, None


def _count_sql_reads(db: Any, call: Callable[[], Any]) -> tuple[Any, int]:
    original_get_conn = db.get_conn
    reads = 0

    def traced_get_conn():
        connection = original_get_conn()
        connection.execute("PRAGMA query_only=ON")

        def trace(statement: str) -> None:
            nonlocal reads
            token = statement.lstrip().split(None, 1)[0].upper() if statement.strip() else ""
            if token in {"SELECT", "WITH"}:
                reads += 1

        connection.set_trace_callback(trace)
        return connection

    db.get_conn = traced_get_conn
    try:
        return call(), reads
    finally:
        db.get_conn = original_get_conn


def _observe_case(db: Any, surface: str, case: dict[str, Any]) -> dict[str, Any]:
    applicable, reason = _applicability(surface, case)
    with _promoted_gate(bool(case["exposure"]["server_promoted_gate"])):
        response, reads = _count_sql_reads(db, lambda: _invoke_surface(surface, case, 5))
        results = _ranked_items(surface, response)
        observation: dict[str, Any] = {
            "case_id": case["case_id"],
            "surface": surface,
            "applicable": applicable,
            "not_applicable_reason": reason,
            "results": results,
            "answerable": _answerable(surface, response),
            "withheld_reasons": _withheld_reasons(surface, response),
            "withholding_supported": surface in {"api_retrieve", "current_context_brief", "mcp_retrieve_context"},
            "sql_read_statements": reads,
        }
        if surface == "api_retrieve":
            response_three, _ = _count_sql_reads(db, lambda: _invoke_surface(surface, case, 3))
            observation["limit_results"] = {
                "3": _ranked_items(surface, response_three),
                "5": results,
            }
        return observation


def _timing_summary(values: list[float]) -> dict[str, Any]:
    from app.core.retrieval_evaluation import percentile

    return {
        "sample_count": len(values),
        "p50_ms": percentile(values, 50),
        "p95_ms": percentile(values, 95),
        "min_ms": min(values) if values else None,
        "max_ms": max(values) if values else None,
    }


def _measure_timings(deck: dict[str, Any], iterations: int) -> dict[str, Any]:
    values: dict[str, list[float]] = {surface: [] for surface in SURFACE_ORDER}
    if iterations <= 0:
        return {"iterations_per_case": 0, "surfaces": {surface: _timing_summary([]) for surface in SURFACE_ORDER}}
    for surface in SURFACE_ORDER:
        for case in deck["cases"]:
            applicable, _ = _applicability(surface, case)
            if not applicable:
                continue
            for _ in range(iterations):
                with _promoted_gate(bool(case["exposure"]["server_promoted_gate"])):
                    started = time.perf_counter_ns()
                    _invoke_surface(surface, case, 5)
                    values[surface].append(round((time.perf_counter_ns() - started) / 1_000_000, 6))
    return {
        "report_version": "boh.retrieval-quality.timing/v0.1",
        "iterations_per_case": iterations,
        "latency_is_gate": False,
        "surfaces": {surface: _timing_summary(values[surface]) for surface in SURFACE_ORDER},
    }


def _surface_differences(observations: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    by_surface = {
        surface: {item["case_id"]: item for item in items}
        for surface, items in observations.items()
    }
    comparisons = []
    retrieval_surfaces = SURFACE_ORDER[:-1]
    case_ids = [
        item["case_id"]
        for item in observations["api_retrieve"]
        if all(by_surface[surface][item["case_id"]].get("applicable", True) for surface in retrieval_surfaces)
    ]
    for case_id in case_ids:
        top_docs = {
            surface: ((by_surface[surface][case_id].get("results") or [{}])[0].get("doc_id"))
            for surface in SURFACE_ORDER
        }
        retrieval_values = [top_docs[surface] for surface in retrieval_surfaces]
        comparisons.append({
            "case_id": case_id,
            "top_doc_by_surface": top_docs,
            "retrieval_surface_top_doc_equal": len(set(retrieval_values)) == 1,
            "keyword_search_compared_separately": True,
        })
    return {
        "retrieval_surface_equal_top_count": sum(item["retrieval_surface_top_doc_equal"] for item in comparisons),
        "common_applicable_case_count": len(comparisons),
        "cases": comparisons,
    }


def _build_report(deck: dict[str, Any], deck_sha256: str, db: Any) -> dict[str, Any]:
    from app.core import retrieval_evaluation
    observations = {
        surface: [_observe_case(db, surface, case) for case in deck["cases"]]
        for surface in SURFACE_ORDER
    }
    evaluations = {
        surface: retrieval_evaluation.evaluate_observations(deck, observations[surface])
        for surface in SURFACE_ORDER
    }
    return {
        "report_version": "boh.retrieval-quality.baseline/v0.1",
        "deck_id": deck["deck_id"],
        "deck_schema_version": deck["schema_version"],
        "as_of": deck["as_of"],
        "deck_sha256": deck_sha256,
        "fixture": {
            "synthetic_only": True,
            "document_count": len(deck["documents"]),
            "chunk_count": sum(len(document["chunks"]) for document in deck["documents"]),
            "case_count": len(deck["cases"]),
            "real_database_option_exposed": False,
        },
        "surface_order": list(SURFACE_ORDER),
        "surface_capabilities": SURFACE_CAPABILITIES,
        "evaluations": evaluations,
        "observations": observations,
        "surface_differences": _surface_differences(observations),
        "interpretation": {
            "keyword_search_is_discovery": True,
            "raw_surfaces_are_not_strict_answer_surfaces": ["query_context_object", "mcp_retrieve_context"],
            "unsupported_semantics_are_not_applicable": True,
            "private_boundary_normalized_field_exists": False,
            "timing_excluded_from_deterministic_report": True,
        },
    }


@contextmanager
def _temporary_fixture(deck: dict[str, Any]):
    with tempfile.TemporaryDirectory(prefix="boh_rq2_") as tmp:
        root = Path(tmp)
        library = root / "library"
        data_root = root / "data_root"
        library.mkdir()
        data_root.mkdir()
        db_path = root / "boh.db"
        previous = {key: os.environ.get(key) for key in ("BOH_DB", "BOH_LIBRARY", "BOH_DATA_ROOT")}
        os.environ["BOH_DB"] = str(db_path)
        os.environ["BOH_LIBRARY"] = str(library)
        os.environ["BOH_DATA_ROOT"] = str(data_root)
        try:
            from app.db import connection as db

            previous_db_path = db.DB_PATH
            db.DB_PATH = str(db_path)
            db.init_db()
            _seed_fixture(deck, db)
            yield db
        finally:
            if "db" in locals():
                db.DB_PATH = previous_db_path
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


@contextmanager
def _measurement_state(as_of_epoch: int):
    from app.core import retrieval

    original_logger = retrieval.log_storage_event
    original_time = time.time
    retrieval.log_storage_event = lambda *args, **kwargs: None
    time.time = lambda: float(as_of_epoch)
    try:
        yield
    finally:
        retrieval.log_storage_event = original_logger
        time.time = original_time


def run_baseline(deck_path: Path, *, timing_iterations: int = 1) -> tuple[dict[str, Any], dict[str, Any]]:
    _force_repo_imports()
    deck, digest = load_deck(deck_path)
    with _temporary_fixture(deck) as db:
        with _measurement_state(_epoch(deck["as_of"]) or 1_783_699_200):
            report = _build_report(deck, digest, db)
            timing = _measure_timings(deck, timing_iterations)
    timing["deck_sha256"] = digest
    return report, timing


def canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def render_markdown(report: dict[str, Any], timing: dict[str, Any]) -> str:
    lines = [
        "# BOH Judged Retrieval Baseline v0.1",
        "",
        "Status: **MEASURED SYNTHETIC BASELINE**",
        "",
        f"- Deck: `{report['deck_id']}`",
        f"- Deck SHA-256: `{report['deck_sha256']}`",
        f"- Evaluation as-of: `{report['as_of']}` (clock frozen for deterministic freshness/expiry)",
        f"- Fixture: {report['fixture']['document_count']} documents, {report['fixture']['chunk_count']} chunks, {report['fixture']['case_count']} cases",
        "- Invocation: direct core-equivalent calls against a disposable synthetic SQLite database",
        "- Real database option: not exposed",
        f"- Deterministic repeat: {'verified byte-identical' if (report.get('verification') or {}).get('deterministic_repeat_verified') else 'not recorded'}",
        "- Timing: reported separately and not used as the sole acceptance gate",
        f"- Timing samples: {timing.get('iterations_per_case', 0)} measured iteration(s) per applicable case",
        "",
        "| Surface | Role | Applicable | Recall@5 | MRR | nDCG@5 | Phrase top-1 | No-answer FP | Authority posture | Freshness posture | Forbidden relevance | Boundary leaks | SQL statements p50 / p95 | Time p50 / p95 ms |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: | ---: | --- | --- |",
    ]
    for surface in SURFACE_ORDER:
        evaluation = report["evaluations"][surface]
        metrics = evaluation["metrics"]
        forbidden_relevance = evaluation["failure_counts"].get("forbidden_relevance_hit", 0)
        boundary_leaks = evaluation["failure_counts"].get("policy_boundary_leak", 0)
        sql = metrics["sql_read_statements"]
        timed = timing["surfaces"][surface]
        lines.append(
            f"| `{surface}` | {SURFACE_CAPABILITIES[surface]['role']} | {evaluation['scored_case_count']} | "
            f"{metrics['recall_at_5']} | {metrics['mrr']} | {metrics['ndcg_at_5']} | "
            f"{metrics['exact_phrase_top1_accuracy']} | {metrics['no_answer_false_positive_rate']} | "
            f"{metrics['authority_posture']['match_rate']} ({metrics['authority_posture']['supported_cases']}) | "
            f"{metrics['freshness_posture']['match_rate']} ({metrics['freshness_posture']['supported_cases']}) | "
            f"{forbidden_relevance} | {boundary_leaks} | {sql['p50']} / {sql['p95']} | {timed['p50_ms']} / {timed['p95_ms']} |"
        )
    differences = report["surface_differences"]
    lines.extend([
        "",
        "## Surface characterization",
        "",
        f"The four retrieval-oriented surfaces shared the same top document in {differences['retrieval_surface_equal_top_count']} of {differences['common_applicable_case_count']} commonly applicable cases. This is characterization, not a parity assertion.",
        "",
        "- `/api/retrieve` is the governed answer surface and derives support from gate-allowed references.",
        "- CurrentContextBrief exposes native `answerable_now` over gate-allowed best evidence.",
        "- Query ContextObject and MCP `retrieve_context` expose raw candidates and do not implement the requested governed mode contract.",
        "- Keyword search is whole-document discovery; it is not scored as a chunk-citation or strict-answer surface.",
        "- Unsupported filters/modes are retained as N/A observations instead of being silently treated as parity.",
        "- Ordinary forbidden relevance hits are separated from policy-boundary leaks; only explicit surface-aware boundary violations affect the boundary gate.",
        "- Authority/freshness posture columns report rule-based matches over supported cases; the parenthesized value is the supported-case count, and unsupported posture is not treated as success.",
        "- Diagnostic N/A invocations are retained in JSON, but they are excluded from timing, scored metrics, and common-applicable surface comparison.",
        "- SQL counts are traced top-level `SELECT`/`WITH` statement counts, not SQLite page, row, or virtual-table internal-read counts.",
        f"- The three genuine no-answer queries produced a false-positive rate of {report['evaluations']['api_retrieve']['metrics']['no_answer_false_positive_rate']} on governed retrieval; the broader expected-unanswerable rate is reported separately in JSON.",
        "- The repository has no normalized private-boundary field across these surfaces; synthetic private exposure is reported, not redefined as an access model.",
        "",
        "## Gate interpretation",
        "",
    ])
    for surface in SURFACE_ORDER:
        evaluation = report["evaluations"][surface]
        lines.append(
            f"- `{surface}`: relevance gate `{evaluation['gates']['relevance_gate_passed']}`, "
            f"boundary gate `{evaluation['gates']['boundary_gate_passed']}`, "
            f"answerability check `{evaluation['gates']['answerability_passed']}`, "
            f"withholding check `{evaluation['gates']['withholding_passed']}`; "
            f"failures `{evaluation['failure_counts']}`."
        )
    lines.extend([
        "",
        "RQ-2 records these current differences and failures without changing ranking, gating, routes, schema, dependencies, corpus state, or MCP behavior.",
        "",
    ])
    return "\n".join(lines)


def _write_artifacts(output_dir: Path, report: dict[str, Any], timing: dict[str, Any]) -> None:
    root = repo_root().resolve()
    resolved = output_dir.resolve()
    if root not in (resolved, *resolved.parents):
        raise ValueError("output directory must stay inside the repository")
    resolved.mkdir(parents=True, exist_ok=True)
    (resolved / "RETRIEVAL_BASELINE_v0_1.json").write_text(canonical_json(report), encoding="utf-8")
    (resolved / "RETRIEVAL_BASELINE_v0_1.md").write_text(render_markdown(report, timing), encoding="utf-8")
    (resolved / "RETRIEVAL_TIMING_v0_1.json").write_text(canonical_json(timing), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deck", type=Path, default=default_deck_path())
    parser.add_argument("--timing-iterations", type=int, default=1)
    parser.add_argument("--verify-repeat", action="store_true", help="run deterministic baseline twice and compare canonical bytes")
    parser.add_argument("--output-dir", type=Path, help="write the three fixed RQ-2 artifact names inside this repository")
    parser.add_argument("--format", choices=("summary", "json", "markdown"), default="summary")
    args = parser.parse_args()
    if args.timing_iterations < 0:
        parser.error("--timing-iterations must be >= 0")

    report, timing = run_baseline(args.deck, timing_iterations=args.timing_iterations)
    repeat_verified = None
    if args.verify_repeat:
        repeated, _ = run_baseline(args.deck, timing_iterations=0)
        repeat_verified = canonical_json(report) == canonical_json(repeated)
        if not repeat_verified:
            print("deterministic baseline repeat mismatch", file=sys.stderr)
            return 2
        report["verification"] = {"deterministic_repeat_verified": True}
    if args.output_dir:
        _write_artifacts(args.output_dir, report, timing)

    if args.format == "json":
        print(canonical_json({"baseline": report, "timing": timing}), end="")
    elif args.format == "markdown":
        print(render_markdown(report, timing), end="")
    else:
        print(json.dumps({
            "deck_sha256": report["deck_sha256"],
            "repeat_verified": repeat_verified,
            "surface_metrics": {
                surface: {
                    "scored": report["evaluations"][surface]["scored_case_count"],
                    "not_applicable": report["evaluations"][surface]["not_applicable_count"],
                    "passed": report["evaluations"][surface]["passed"],
                    "failures": report["evaluations"][surface]["failure_counts"],
                    "metrics": report["evaluations"][surface]["metrics"],
                    "timing": timing["surfaces"][surface],
                }
                for surface in SURFACE_ORDER
            },
        }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
