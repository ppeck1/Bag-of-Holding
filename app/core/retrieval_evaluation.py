"""Deterministic judged-retrieval evaluation for RQ-2.

This module is measurement-only.  It consumes synthetic judgments and normalized
surface observations; it never calls retrieval, opens a database, or mutates
runtime state.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any


SCHEMA_VERSION = "boh.retrieval-quality.judged-deck.v0.1"
REQUIRED_CATEGORIES = (
    "exact_phrase",
    "identifier_lookup",
    "natural_language",
    "no_answer",
    "conflict_supersession",
    "promoted_only",
    "strict_answer_disallowed_source",
    "logical_library",
    "daenary_private_boundary",
    "stale_vs_current",
)
VALID_MODES = {
    "strict_answer",
    "exploration",
    "audit_provenance",
    "canon_review",
    "low_b_worker_context",
}


class DeckValidationError(ValueError):
    """A judged deck is incomplete, ambiguous, or internally inconsistent."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DeckValidationError(message)


def _is_relative_fixture_path(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    return not path.is_absolute() and ".." not in path.parts


def validate_deck(deck: Mapping[str, Any]) -> None:
    """Fail closed unless *deck* contains complete, resolvable judgments."""

    _require(isinstance(deck, Mapping), "deck must be an object")
    _require(deck.get("schema_version") == SCHEMA_VERSION, "unsupported schema_version")
    _require(isinstance(deck.get("deck_id"), str) and bool(deck["deck_id"]), "deck_id is required")
    as_of = deck.get("as_of")
    _require(isinstance(as_of, str) and bool(as_of), "as_of is required")
    try:
        from datetime import datetime
        datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise DeckValidationError("as_of must be an ISO-8601 timestamp") from exc

    categories = deck.get("categories")
    _require(isinstance(categories, list), "categories must be a list")
    category_values: list[str] = []
    for entry in categories:
        if isinstance(entry, str):
            category_values.append(entry)
        elif isinstance(entry, Mapping) and isinstance(entry.get("id"), str):
            category_values.append(str(entry["id"]))
        else:
            raise DeckValidationError("every category must be a string or an object with id")
    _require(set(category_values) == set(REQUIRED_CATEGORIES), "categories must name the exact RQ-2 set")

    documents = deck.get("documents")
    _require(isinstance(documents, list) and bool(documents), "documents must be a nonempty list")
    doc_ids: set[str] = set()
    chunk_owner: dict[str, str] = {}
    for index, document in enumerate(documents):
        _require(isinstance(document, Mapping), f"documents[{index}] must be an object")
        doc_id = document.get("doc_id")
        _require(isinstance(doc_id, str) and bool(doc_id), f"documents[{index}].doc_id is required")
        _require(doc_id not in doc_ids, f"duplicate document id: {doc_id}")
        doc_ids.add(doc_id)
        _require(_is_relative_fixture_path(document.get("path")), f"unsafe fixture path for {doc_id}")
        _require(isinstance(document.get("private"), bool), f"{doc_id}.private must be boolean")
        chunks = document.get("chunks")
        _require(isinstance(chunks, list) and bool(chunks), f"{doc_id}.chunks must be nonempty")
        for chunk_index, chunk in enumerate(chunks):
            _require(isinstance(chunk, Mapping), f"{doc_id}.chunks[{chunk_index}] must be an object")
            chunk_id = chunk.get("chunk_id")
            _require(isinstance(chunk_id, str) and bool(chunk_id), f"{doc_id} chunk_id is required")
            _require(chunk_id not in chunk_owner, f"duplicate chunk id: {chunk_id}")
            chunk_owner[chunk_id] = doc_id
            _require(isinstance(chunk.get("text"), str) and bool(chunk["text"]), f"{chunk_id}.text is required")

    cases = deck.get("cases")
    _require(isinstance(cases, list) and len(cases) >= 30, "at least 30 judged cases are required")
    case_ids: set[str] = set()
    category_counts: Counter[str] = Counter()
    for index, case in enumerate(cases):
        _require(isinstance(case, Mapping), f"cases[{index}] must be an object")
        case_id = case.get("case_id")
        _require(isinstance(case_id, str) and bool(case_id), f"cases[{index}].case_id is required")
        _require(case_id not in case_ids, f"duplicate case id: {case_id}")
        case_ids.add(case_id)
        category = case.get("category")
        _require(category in REQUIRED_CATEGORIES, f"{case_id}: unknown category")
        category_counts[str(category)] += 1
        _require(isinstance(case.get("query"), str) and bool(case["query"].strip()), f"{case_id}: query required")
        _require(case.get("mode") in VALID_MODES, f"{case_id}: invalid retrieval mode")
        _require(isinstance(case.get("filters"), Mapping), f"{case_id}: filters must be an object")

        exposure = case.get("exposure")
        _require(isinstance(exposure, Mapping), f"{case_id}: exposure must be an object")
        for key in ("server_promoted_gate", "request_include_promoted", "private_access"):
            _require(isinstance(exposure.get(key), bool), f"{case_id}: exposure.{key} must be boolean")

        expected = case.get("expected")
        _require(isinstance(expected, Mapping), f"{case_id}: expected must be an object")
        graded = expected.get("graded_relevance")
        _require(isinstance(graded, list), f"{case_id}: graded_relevance must be a list")
        seen_judgments: set[tuple[str, str]] = set()
        for judgment in graded:
            _require(isinstance(judgment, Mapping), f"{case_id}: judgment must be an object")
            doc_id = judgment.get("doc_id")
            chunk_id = judgment.get("chunk_id")
            grade = judgment.get("grade")
            _require(doc_id in doc_ids, f"{case_id}: unknown judged doc {doc_id}")
            _require(chunk_id in chunk_owner, f"{case_id}: unknown judged chunk {chunk_id}")
            _require(chunk_owner[str(chunk_id)] == doc_id, f"{case_id}: chunk/doc judgment mismatch")
            _require(isinstance(grade, int) and 1 <= grade <= 3, f"{case_id}: grade must be 1..3")
            key = (str(doc_id), str(chunk_id))
            _require(key not in seen_judgments, f"{case_id}: duplicate graded judgment")
            seen_judgments.add(key)

        forbidden = expected.get("forbidden_doc_ids")
        _require(isinstance(forbidden, list) and bool(forbidden), f"{case_id}: forbidden_doc_ids must be nonempty")
        _require(len(forbidden) == len(set(forbidden)), f"{case_id}: duplicate forbidden doc id")
        for doc_id in forbidden:
            _require(doc_id in doc_ids, f"{case_id}: unknown forbidden doc {doc_id}")
        # Relevant-but-forbidden overlap is intentional for strict/private cases.
        _require(isinstance(expected.get("answerable"), bool), f"{case_id}: answerable must be boolean")
        _require(isinstance(expected.get("withheld_reasons"), list), f"{case_id}: withheld_reasons must be a list")
        _require(all(isinstance(v, str) and v for v in expected["withheld_reasons"]), f"{case_id}: invalid withheld reason")
        for key in ("authority_posture", "freshness_posture"):
            _require(isinstance(expected.get(key), str) and bool(expected[key]), f"{case_id}: {key} required")

    for category in REQUIRED_CATEGORIES:
        _require(category_counts[category] >= 3, f"category {category} requires at least three cases")


def percentile(values: Sequence[float | int], percentile_value: float) -> float | None:
    """Return a deterministic nearest-rank percentile."""

    if not values:
        return None
    if not 0 <= percentile_value <= 100:
        raise ValueError("percentile must be between 0 and 100")
    ordered = sorted(float(value) for value in values)
    rank = max(1, math.ceil((percentile_value / 100.0) * len(ordered)))
    return ordered[rank - 1]


def _round(value: float) -> float:
    return round(float(value), 6)


def _result_key(item: Mapping[str, Any]) -> tuple[str | None, str | None]:
    doc_id = item.get("doc_id")
    chunk_id = item.get("chunk_id")
    return (str(doc_id) if doc_id is not None else None, str(chunk_id) if chunk_id is not None else None)


def _judgment_maps(case: Mapping[str, Any]) -> tuple[dict[tuple[str, str], int], dict[str, int]]:
    exact: dict[tuple[str, str], int] = {}
    by_doc: dict[str, int] = {}
    forbidden = {str(value) for value in case["expected"]["forbidden_doc_ids"]}
    for judgment in case["expected"]["graded_relevance"]:
        key = (str(judgment["doc_id"]), str(judgment["chunk_id"]))
        # A document can be a relevant match and still be policy-forbidden.
        # Governed-output relevance metrics score only allowed expected evidence;
        # the forbidden match remains covered by the separate leakage gate.
        if key[0] in forbidden:
            continue
        exact[key] = int(judgment["grade"])
        by_doc[key[0]] = max(by_doc.get(key[0], 0), int(judgment["grade"]))
    return exact, by_doc


def _grade_result(item: Mapping[str, Any], exact: Mapping[tuple[str, str], int], by_doc: Mapping[str, int]) -> int:
    doc_id, chunk_id = _result_key(item)
    if doc_id is None:
        return 0
    if chunk_id is None:  # document-only discovery surfaces
        return int(by_doc.get(doc_id, 0))
    return int(exact.get((doc_id, chunk_id), 0))


def _case_metrics(case: Mapping[str, Any], observation: Mapping[str, Any], k: int = 5) -> dict[str, Any]:
    exact, by_doc = _judgment_maps(case)
    results = [item for item in (observation.get("results") or []) if isinstance(item, Mapping)][:k]
    document_level = bool(results) and all(item.get("chunk_id") is None for item in results)
    if document_level:
        relevant_total = len(by_doc)
        hits = {str(item.get("doc_id")) for item in results if str(item.get("doc_id")) in by_doc}
        recall = len(hits) / relevant_total if relevant_total else 1.0
    else:
        relevant_total = len(exact)
        hits = {_result_key(item) for item in results if _result_key(item) in exact}
        recall = len(hits) / relevant_total if relevant_total else 1.0

    grades: list[int] = []
    seen_ranked_judgments: set[Any] = set()
    for item in results:
        doc_id, chunk_id = _result_key(item)
        identity: Any = doc_id if document_level else (doc_id, chunk_id)
        if identity in seen_ranked_judgments:
            grades.append(0)
            continue
        seen_ranked_judgments.add(identity)
        grades.append(_grade_result(item, exact, by_doc))
    reciprocal_rank = next((1.0 / rank for rank, grade in enumerate(grades, start=1) if grade > 0), 0.0)
    dcg = sum((2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(grades, start=1))
    ideal_grades = sorted((by_doc.values() if document_level else exact.values()), reverse=True)[:k]
    idcg = sum((2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(ideal_grades, start=1))
    ndcg = dcg / idcg if idcg else 1.0

    doc_counts = Counter(str(item.get("doc_id")) for item in results if item.get("doc_id") is not None)
    concentration = (max(doc_counts.values()) / len(results)) if results and doc_counts else 0.0
    max_grade = max(exact.values(), default=0)
    top_grade = grades[0] if grades else 0
    return {
        "recall_at_5": _round(recall),
        "reciprocal_rank": _round(reciprocal_rank),
        "ndcg_at_5": _round(ndcg),
        "duplicate_document_concentration": _round(concentration),
        "top_is_max_grade": bool(max_grade == 0 or top_grade == max_grade),
    }


def _prefix_stable(observation: Mapping[str, Any]) -> bool | None:
    limit_results = observation.get("limit_results")
    if not isinstance(limit_results, Mapping) or len(limit_results) < 2:
        return None
    parsed: list[tuple[int, list[tuple[str | None, str | None]]]] = []
    for raw_limit, items in limit_results.items():
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            continue
        if not isinstance(items, list):
            continue
        parsed.append((limit, [_result_key(item) for item in items if isinstance(item, Mapping)]))
    if len(parsed) < 2:
        return None
    parsed.sort(key=lambda value: value[0])
    small = parsed[0][1]
    large = parsed[-1][1]
    return small == large[: len(small)]


def _policy_boundary_kind(
    case: Mapping[str, Any],
    doc_id: str,
    document: Mapping[str, Any],
    surface: str,
) -> str | None:
    category = case["category"]
    graded_docs = {str(item["doc_id"]) for item in case["expected"]["graded_relevance"]}
    if category == "strict_answer_disallowed_source" and doc_id in graded_docs:
        return "authority"
    if category == "logical_library":
        return "logical_library_scope"
    if category == "daenary_private_boundary":
        if case.get("filters", {}).get("private") is False and document.get("private"):
            return "private_unmodeled"
        return "daenary_scope"
    if category == "promoted_only" and document.get("corpus_class") == "CORPUS_CLASS:PROMOTED_INTAKE":
        exposure = case["exposure"]
        if surface == "keyword_search":
            return "promoted" if not exposure["server_promoted_gate"] else None
        if not (exposure["server_promoted_gate"] and exposure["request_include_promoted"]):
            return "promoted"
    return None


def _posture_checks(
    case: Mapping[str, Any],
    observation: Mapping[str, Any],
    documents: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    expected = case["expected"]
    results = [item for item in (observation.get("results") or []) if isinstance(item, Mapping)]
    top = results[0] if results else None
    top_doc = documents.get(str(top.get("doc_id"))) if top else None
    graded = expected["graded_relevance"]
    max_grade = max((int(item["grade"]) for item in graded), default=0)
    max_docs = {str(item["doc_id"]) for item in graded if int(item["grade"]) == max_grade}
    relevant_docs = {str(item["doc_id"]) for item in graded}
    returned_docs = {str(item.get("doc_id")) for item in results if item.get("doc_id")}
    required_reasons = set(str(value) for value in expected["withheld_reasons"])
    observed_reasons = set(str(value) for value in (observation.get("withheld_reasons") or []))
    withheld_match = bool(required_reasons) and required_reasons.issubset(observed_reasons)

    authority_label = str(expected["authority_posture"])
    authority_match: bool | None
    if authority_label == "no_evidence":
        authority_match = not results
    elif "withheld" in authority_label:
        authority_match = not bool(relevant_docs & returned_docs) and withheld_match
    elif authority_label == "promoted_advisory":
        authority_match = bool(top_doc and top_doc.get("corpus_class") == "CORPUS_CLASS:PROMOTED_INTAKE" and top.get("doc_id") in max_docs)
    elif authority_label == "conflicted_bounded":
        authority_match = bool(top_doc and top_doc.get("conflicts_with") and top.get("doc_id") in max_docs)
    elif authority_label == "exploratory_noncanonical":
        authority_match = bool(top_doc and top_doc.get("authority_state") not in {"approved", "trusted", "canonical"})
    elif "canonical" in authority_label:
        if not top:
            authority_match = False
        else:
            authoritative = (
                top.get("status") == "canonical"
                or top.get("authority_state") in {"approved", "trusted", "canonical"}
                or (top_doc and top_doc.get("authority_state") in {"approved", "trusted", "canonical"})
            )
            authority_match = bool(authoritative and top.get("doc_id") in max_docs)
    else:
        authority_match = None

    freshness_label = str(expected["freshness_posture"])
    freshness_match: bool | None
    if freshness_label == "no_evidence":
        freshness_match = not results
    elif freshness_label == "current_but_withheld":
        freshness_match = not bool(relevant_docs & returned_docs) and withheld_match
    elif freshness_label == "current_preferred_over_stale":
        freshness_match = bool(top and top.get("doc_id") in max_docs and not (returned_docs & set(expected["forbidden_doc_ids"])))
    elif freshness_label == "historical_mixed":
        freshness_match = bool(top and top.get("doc_id") in max_docs)
    elif freshness_label == "stale" and not expected["answerable"]:
        freshness_match = not bool(relevant_docs & returned_docs) and withheld_match
    elif freshness_label == "stale":
        freshness = top.get("freshness") if top else None
        age = freshness.get("age_days") if isinstance(freshness, Mapping) else None
        freshness_match = bool(
            top
            and top.get("doc_id") in max_docs
            and ((isinstance(age, (int, float)) and age > 365) or (top_doc and top_doc.get("superseded_by")))
        ) if freshness is not None else None
    elif freshness_label == "unknown":
        freshness = top.get("freshness") if top else None
        freshness_match = not results or not freshness
    elif freshness_label == "current":
        freshness = top.get("freshness") if top else None
        age = freshness.get("age_days") if isinstance(freshness, Mapping) else None
        freshness_match = bool(
            top
            and top.get("doc_id") in max_docs
            and isinstance(age, (int, float))
            and age <= 30
            and not freshness.get("superseded", False)
        ) if freshness is not None else None
    else:
        freshness_match = None
    return {
        "case_id": case["case_id"],
        "expected_authority_posture": authority_label,
        "authority_match": authority_match,
        "expected_freshness_posture": freshness_label,
        "freshness_match": freshness_match,
    }


def _validate_observation(
    observation: Mapping[str, Any],
    cases: Mapping[str, Mapping[str, Any]],
    documents: Mapping[str, Mapping[str, Any]],
    chunk_owner: Mapping[str, str],
) -> None:
    case_id = observation.get("case_id")
    if not isinstance(case_id, str) or case_id not in cases:
        raise ValueError(f"observation references unknown case: {case_id or ''}")
    if not isinstance(observation.get("applicable", True), bool):
        raise ValueError(f"{case_id}: applicable must be boolean")
    surface = observation.get("surface", "api_retrieve")
    if not isinstance(surface, str) or not surface:
        raise ValueError(f"{case_id}: surface must be a nonempty string")
    def validate_result_items(items: Any, label: str) -> None:
        if not isinstance(items, list):
            raise ValueError(f"{case_id}: {label} must be a list")
        for item in items:
            if not isinstance(item, Mapping):
                raise ValueError(f"{case_id}: each {label} item must be an object")
            doc_id = item.get("doc_id")
            if not isinstance(doc_id, str) or doc_id not in documents:
                raise ValueError(f"{case_id}: {label} references unknown document")
            chunk_id = item.get("chunk_id")
            if chunk_id is not None and (not isinstance(chunk_id, str) or chunk_owner.get(chunk_id) != doc_id):
                raise ValueError(f"{case_id}: {label} chunk/document mismatch")
            score = item.get("score")
            if score is not None and (not isinstance(score, (int, float)) or not math.isfinite(float(score))):
                raise ValueError(f"{case_id}: {label} score must be finite")

    results = observation.get("results")
    validate_result_items(results, "results")
    answerable = observation.get("answerable")
    if answerable is not None and not isinstance(answerable, bool):
        raise ValueError(f"{case_id}: answerable must be boolean or null")
    if not isinstance(observation.get("withholding_supported", True), bool):
        raise ValueError(f"{case_id}: withholding_supported must be boolean")
    reasons = observation.get("withheld_reasons", [])
    if not isinstance(reasons, list) or not all(isinstance(value, str) and value for value in reasons):
        raise ValueError(f"{case_id}: withheld_reasons must contain strings")
    for key in ("sql_read_statements", "sql_read_calls", "elapsed_ms"):
        value = observation.get(key)
        if value is not None and (
            not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
        ):
            raise ValueError(f"{case_id}: {key} must be a nonnegative finite number")
    limit_results = observation.get("limit_results")
    if limit_results is not None:
        if not isinstance(limit_results, Mapping):
            raise ValueError(f"{case_id}: limit_results must be an object")
        for raw_limit, items in limit_results.items():
            try:
                limit = int(raw_limit)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{case_id}: invalid limit_results key") from exc
            if limit < 1 or not isinstance(items, list):
                raise ValueError(f"{case_id}: invalid limit_results entry")
            validate_result_items(items, f"limit_results[{limit}]")


def evaluate_observations(
    deck: Mapping[str, Any],
    observations: Sequence[Mapping[str, Any]],
    *,
    relevance_gate: bool = True,
    boundary_gate: bool = True,
) -> dict[str, Any]:
    """Evaluate one normalized observation per judged case.

    Observations with ``applicable=false`` are retained as N/A counts and are
    excluded from scored aggregates.  Extra surface metadata is ignored.
    """

    validate_deck(deck)
    cases = {str(case["case_id"]): case for case in deck["cases"]}
    documents = {str(document["doc_id"]): document for document in deck["documents"]}
    chunk_owner = {
        str(chunk["chunk_id"]): str(document["doc_id"])
        for document in deck["documents"]
        for chunk in document["chunks"]
    }
    by_case: dict[str, Mapping[str, Any]] = {}
    for observation in observations:
        _validate_observation(observation, cases, documents, chunk_owner)
        case_id = str(observation["case_id"])
        if case_id in by_case:
            raise ValueError(f"duplicate observation for case: {case_id}")
        by_case[case_id] = observation

    missing = sorted(set(cases) - set(by_case))
    if missing:
        raise ValueError(f"missing observations for {len(missing)} case(s): {', '.join(missing[:3])}")

    scored: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    policy_leak_counts: Counter[str] = Counter()
    policy_case_counts: Counter[str] = Counter()
    observed_exposure_counts: Counter[str] = Counter()
    observed_exposure_case_counts: Counter[str] = Counter()
    observed_exposure_case_ids: defaultdict[str, list[str]] = defaultdict(list)
    prefix_values: list[bool] = []
    sql_values: list[float] = []
    diagnostic_sql_values: list[float] = []
    elapsed_values: list[float] = []
    phrase_values: list[bool] = []
    no_answer_values: list[bool] = []
    expected_unanswerable_values: list[bool] = []
    withheld_values: list[bool] = []
    not_applicable: Counter[str] = Counter()
    posture_checks: list[dict[str, Any]] = []

    for case_id, case in cases.items():
        observation = by_case[case_id]
        # SQL counts characterize actual invocations even when a surface cannot
        # support the requested semantics and the quality judgment is N/A.
        sql_value = observation.get("sql_read_statements", observation.get("sql_read_calls"))
        if isinstance(sql_value, (int, float)):
            diagnostic_sql_values.append(float(sql_value))
        if isinstance(observation.get("elapsed_ms"), (int, float)):
            elapsed_values.append(float(observation["elapsed_ms"]))

        results = [item for item in (observation.get("results") or []) if isinstance(item, Mapping)]
        result_doc_ids = {str(item.get("doc_id")) for item in results if item.get("doc_id") is not None}
        forbidden = set(str(value) for value in case["expected"]["forbidden_doc_ids"])
        observed_leaks = sorted(result_doc_ids & forbidden)
        surface = str(observation.get("surface") or "api_retrieve")
        potential_kinds = {
            _policy_boundary_kind(case, doc_id, documents[doc_id], surface) or "relevance"
            for doc_id in forbidden
        }
        observed_kinds: set[str] = set()
        for doc_id in observed_leaks:
            kind = _policy_boundary_kind(case, doc_id, documents[doc_id], surface) or "relevance"
            observed_kinds.add(kind)
        for kind in potential_kinds:
            observed_exposure_case_counts[kind] += 1
            if kind in observed_kinds:
                observed_exposure_counts[kind] += 1
                observed_exposure_case_ids[kind].append(case_id)

        if observation.get("applicable", True) is False:
            not_applicable[str(observation.get("not_applicable_reason") or "unspecified")] += 1
            continue
        metrics = _case_metrics(case, observation)
        scored.append({"case_id": case_id, **metrics})
        posture_checks.append(_posture_checks(case, observation, documents))
        expected = case["expected"]
        leaked = sorted(result_doc_ids & forbidden)
        for kind in potential_kinds & {"promoted", "authority", "logical_library_scope", "daenary_scope"}:
            policy_case_counts[kind] += 1
        for doc_id in leaked:
            kind = _policy_boundary_kind(case, doc_id, documents[doc_id], surface)
            if kind in {"promoted", "authority", "logical_library_scope", "daenary_scope"}:
                policy_leak_counts[str(kind)] += 1
                failures.append({
                    "case_id": case_id,
                    "code": "policy_boundary_leak",
                    "boundary": kind,
                    "doc_ids": [doc_id],
                })
            else:
                failures.append({
                    "case_id": case_id,
                    "code": "forbidden_relevance_hit",
                    "doc_ids": [doc_id],
                })

        if expected["answerable"] and expected["graded_relevance"] and not metrics["top_is_max_grade"]:
            failures.append({"case_id": case_id, "code": "wrong_top_result"})
        observed_answerable = observation.get("answerable")
        if isinstance(observed_answerable, bool) and observed_answerable != expected["answerable"]:
            failures.append({
                "case_id": case_id,
                "code": "answerability_mismatch",
                "expected": expected["answerable"],
                "actual": observed_answerable,
            })
        if not expected["answerable"] and isinstance(observed_answerable, bool):
            expected_unanswerable_values.append(observed_answerable)
            if case["category"] == "no_answer":
                no_answer_values.append(observed_answerable)

        if case["category"] == "exact_phrase" and expected["answerable"]:
            phrase_values.append(metrics["top_is_max_grade"])

        observed_withheld = set(str(value) for value in (observation.get("withheld_reasons") or []))
        required_withheld = set(str(value) for value in expected["withheld_reasons"])
        if required_withheld and observation.get("withholding_supported", True):
            matched = required_withheld.issubset(observed_withheld)
            withheld_values.append(matched)
            if not matched:
                failures.append({
                    "case_id": case_id,
                    "code": "withheld_reason_missing",
                    "missing": sorted(required_withheld - observed_withheld),
                })

        prefix = _prefix_stable(observation)
        if prefix is not None:
            prefix_values.append(prefix)
        if isinstance(sql_value, (int, float)):
            sql_values.append(float(sql_value))

    metric_rows = [row for row in scored if cases[row["case_id"]]["expected"]["answerable"]]
    def average(key: str) -> float:
        return _round(sum(float(row[key]) for row in metric_rows) / len(metric_rows)) if metric_rows else 0.0

    policy_leakage = {
        bucket: {
            "cases": policy_case_counts[bucket],
            "leaked_results": policy_leak_counts[bucket],
            "rate": _round(policy_leak_counts[bucket] / policy_case_counts[bucket]) if policy_case_counts[bucket] else 0.0,
        }
        for bucket in ("promoted", "authority", "logical_library_scope", "daenary_scope")
    }
    observed_exposure = {
        bucket: {
            "cases": observed_exposure_case_counts[bucket],
            "exposed_cases": observed_exposure_counts[bucket],
            "rate": _round(observed_exposure_counts[bucket] / observed_exposure_case_counts[bucket])
            if observed_exposure_case_counts[bucket] else 0.0,
            "case_ids": sorted(observed_exposure_case_ids[bucket]),
        }
        for bucket in ("relevance", "promoted", "authority", "logical_library_scope", "daenary_scope", "private_unmodeled")
    }
    wrong_top = [failure for failure in failures if failure["code"] == "wrong_top_result"]
    forbidden_relevance = [failure for failure in failures if failure["code"] == "forbidden_relevance_hit"]
    boundary_failures = [failure for failure in failures if failure["code"] == "policy_boundary_leak"]
    answerability_failures = [failure for failure in failures if failure["code"] == "answerability_mismatch"]
    withholding_failures = [failure for failure in failures if failure["code"] == "withheld_reason_missing"]
    passed = (
        (not relevance_gate or (not wrong_top and not forbidden_relevance))
        and (not boundary_gate or not boundary_failures)
        and not answerability_failures
        and not withholding_failures
    )
    return {
        "case_count": len(cases),
        "scored_case_count": len(scored),
        "not_applicable_count": sum(not_applicable.values()),
        "not_applicable_reasons": dict(sorted(not_applicable.items())),
        "metrics": {
            "recall_at_5": average("recall_at_5"),
            "mrr": average("reciprocal_rank"),
            "ndcg_at_5": average("ndcg_at_5"),
            "exact_phrase_top1_accuracy": _round(sum(phrase_values) / len(phrase_values)) if phrase_values else None,
            "no_answer_false_positive_rate": _round(sum(no_answer_values) / len(no_answer_values)) if no_answer_values else None,
            "expected_unanswerable_false_positive_rate": (
                _round(sum(expected_unanswerable_values) / len(expected_unanswerable_values))
                if expected_unanswerable_values else None
            ),
            "duplicate_document_concentration": average("duplicate_document_concentration"),
            "top_k_prefix_stability": _round(sum(prefix_values) / len(prefix_values)) if prefix_values else None,
            "withheld_reason_match_rate": _round(sum(withheld_values) / len(withheld_values)) if withheld_values else None,
            "sql_read_statements": {
                "sample_count": len(sql_values),
                "total": int(sum(sql_values)),
                "p50": percentile(sql_values, 50),
                "p95": percentile(sql_values, 95),
            },
            "diagnostic_sql_read_statements_all_invocations": {
                "sample_count": len(diagnostic_sql_values),
                "total": int(sum(diagnostic_sql_values)),
                "p50": percentile(diagnostic_sql_values, 50),
                "p95": percentile(diagnostic_sql_values, 95),
            },
            "elapsed_ms": {
                "sample_count": len(elapsed_values),
                "p50": percentile(elapsed_values, 50),
                "p95": percentile(elapsed_values, 95),
            },
            "policy_boundary_leakage": policy_leakage,
            "observed_forbidden_exposure_all_cases": observed_exposure,
            "authority_posture": {
                "supported_cases": sum(item["authority_match"] is not None for item in posture_checks),
                "match_rate": (
                    _round(sum(item["authority_match"] is True for item in posture_checks) /
                           sum(item["authority_match"] is not None for item in posture_checks))
                    if any(item["authority_match"] is not None for item in posture_checks) else None
                ),
            },
            "freshness_posture": {
                "supported_cases": sum(item["freshness_match"] is not None for item in posture_checks),
                "match_rate": (
                    _round(sum(item["freshness_match"] is True for item in posture_checks) /
                           sum(item["freshness_match"] is not None for item in posture_checks))
                    if any(item["freshness_match"] is not None for item in posture_checks) else None
                ),
            },
        },
        "posture_checks": posture_checks,
        "failures": failures,
        "failure_counts": dict(sorted(Counter(failure["code"] for failure in failures).items())),
        "gates": {
            "relevance_gate_enabled": relevance_gate,
            "boundary_gate_enabled": boundary_gate,
            "relevance_gate_passed": not wrong_top and not forbidden_relevance,
            "boundary_gate_passed": not boundary_failures,
            "answerability_passed": not answerability_failures,
            "withholding_passed": not withholding_failures,
        },
        "passed": passed,
    }
