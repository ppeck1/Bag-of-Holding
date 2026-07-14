"""CurrentContextBrief v0.1 builder.

Read-only orchestration over existing retrieval and context-object evidence. The
brief is deterministic and intentionally extractive: it summarizes what BOH can
currently support without inventing canon status, freshness, or authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core import context_object, promoted_exposure, retrieval

CONTRACT_NAME = "CurrentContextBrief"
CONTRACT_VERSION = "0.1"


def _clamp_limit(value: int | None, default: int = 8, high: int = 25) -> int:
    try:
        n = int(value if value is not None else default)
    except (TypeError, ValueError):
        n = default
    return max(1, min(high, n))


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    return value


def _dedupe_strings(values: list[Any]) -> list[str]:
    out: list[str] = []
    for value in values:
        if isinstance(value, str) and value and value not in out:
            out.append(value)
    return out


def _evidence_item(pack: Mapping[str, Any]) -> dict[str, Any]:
    citation = pack.get("citation") or {}
    source_span = pack.get("source_span") or {}
    return {
        "doc_id": pack.get("doc_id"),
        "chunk_id": pack.get("chunk_id"),
        "title": pack.get("title"),
        "path": pack.get("path"),
        "heading_path": pack.get("heading_path"),
        "snippet": pack.get("snippet") or pack.get("text"),
        "score": pack.get("score"),
        "authority_state": pack.get("authority_state"),
        "status": pack.get("status"),
        "canonical_layer": pack.get("canonical_layer"),
        "freshness": _jsonable(pack.get("freshness") or {}),
        "provenance": _jsonable(pack.get("provenance") or {}),
        "intake_provenance": _jsonable(pack.get("intake_provenance")),
        "citation_uri": pack.get("citation_uri")
            or (f"boh://{citation.get('doc_id')}#{citation.get('chunk_id')}"
                if citation.get("doc_id") and citation.get("chunk_id") else None),
        "source_span": _jsonable(source_span),
        "warnings": _dedupe_strings(list(pack.get("warnings") or [])),
        "why_selected": _jsonable(pack.get("why_selected") or {}),
    }


def _freshness_age(pack: Mapping[str, Any]) -> float | None:
    try:
        age = (pack.get("freshness") or {}).get("age_days")
        return None if age is None else float(age)
    except (TypeError, ValueError, AttributeError):
        return None


def _newest_first(packs: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    def key(pack: Mapping[str, Any]) -> tuple[int, float, float]:
        age = _freshness_age(pack)
        score = pack.get("score") or 0.0
        return (1 if age is None else 0, age if age is not None else 10**9, -float(score))

    return sorted(packs, key=key)


def _best_first(packs: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(packs, key=lambda p: float(p.get("score") or 0.0), reverse=True)


def _pack_ref(pack: Mapping[str, Any]) -> str:
    return str(
        pack.get("card_id")
        or pack.get("chunk_id")
        or pack.get("doc_id")
        or ""
    )


def _gate_allowed_packs(
    packs: list[Mapping[str, Any]],
    gate: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    if gate.get("posture") == "blocked":
        return []
    allowed_refs = {
        str(ref) for ref in (gate.get("allowed_context_refs") or []) if ref
    }
    if not allowed_refs:
        return []
    return [pack for pack in packs if _pack_ref(pack) in allowed_refs]


def _conflict_entries(packs: list[Mapping[str, Any]], context: Mapping[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for pack in packs:
        for conflict in pack.get("conflicts") or []:
            item = _jsonable(conflict)
            if isinstance(item, dict):
                item.setdefault("doc_id", pack.get("doc_id"))
                item.setdefault("source", "retrieval_pack")
                entries.append(item)
    for conflict in context.get("conflicts") or []:
        item = _jsonable(conflict)
        if isinstance(item, dict):
            item.setdefault("source", "context_object")
            entries.append(item)
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in entries:
        key = str(item.get("rowid") or item.get("conflict_id") or item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _withheld_entries(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in result.get("excluded_summary") or []:
        if isinstance(item, Mapping):
            out.append({"source": "retrieval_excluded", **_jsonable(item)})
    gate = result.get("gate_result") or {}
    for ref in gate.get("withheld_context_refs") or []:
        out.append({"source": "planar_gate", "ref": ref})
    return out


def _summary(topic: str, packs: list[Mapping[str, Any]], conflicts: list[dict[str, Any]],
             unknowns: list[Any], withheld: list[dict[str, Any]]) -> str:
    if not packs:
        return (
            f"No current BOH evidence was retrieved for '{topic}'. Treat the topic as "
            "not answerable from this bounded context."
        )
    top = packs[0]
    age = _freshness_age(top)
    age_text = f"; top evidence age {age:g} days" if age is not None else ""
    caveats = []
    if conflicts:
        caveats.append(f"{len(conflicts)} conflict/supersession signal(s)")
    if unknowns:
        caveats.append(f"{len(unknowns)} unknown(s)")
    if withheld:
        caveats.append(f"{len(withheld)} withheld/excluded item(s)")
    caveat_text = f" Caveats: {', '.join(caveats)}." if caveats else ""
    return (
        f"BOH retrieved {len(packs)} evidence pack(s) for '{topic}'. Top evidence: "
        f"{top.get('title') or top.get('doc_id') or 'untitled'}{age_text}."
        f"{caveat_text}"
    )


def build_current_context_brief(
    topic: str,
    *,
    limit: int | None = 8,
    mode: str = "exploration",
    include_promoted: bool = False,
    max_context_chars: int = 6000,
    governed_result: Any | None = None,
) -> dict[str, Any]:
    capped = _clamp_limit(limit)
    normalized = (
        governed_result
        if governed_result is not None
        else retrieval.retrieve_governed_result(
            topic,
            mode=mode,
            limit=capped,
            max_context_chars=max_context_chars,
            include_promoted=include_promoted,
        )
    )
    retrieval_result = (
        normalized.to_dict() if hasattr(normalized, "to_dict") else dict(normalized)
    )
    context_result = context_object.assemble(
        "query",
        topic,
        evidence_limit=capped,
        include_promoted=include_promoted,
        question_type="exploratory",
        governed_result=normalized,
    )
    gate = _jsonable(retrieval_result.get("gate_result") or {})
    retrieved_packs = [
        _jsonable(pack) for pack in retrieval_result.get("context_packs", [])
    ]
    packs = _gate_allowed_packs(retrieved_packs, gate)
    conflicts = _conflict_entries(packs, context_result)
    unknowns = _jsonable(context_result.get("unknowns") or [])
    withheld = _withheld_entries(retrieval_result)
    warnings = _dedupe_strings(
        list(retrieval_result.get("warnings") or [])
        + list((context_result.get("scope") or {}).get("warnings") or [])
        + [warning for pack in packs for warning in (pack.get("warnings") or [])]
    )
    promoted_visibility = {
        "env_gate_open": promoted_exposure.env_gate_open(),
        "request_opt_in": bool(include_promoted),
        "visible": promoted_exposure.visible(include_promoted),
    }
    best = [_evidence_item(pack) for pack in _best_first(packs)[:capped]]
    newest = [_evidence_item(pack) for pack in _newest_first(packs)[:capped]]
    return {
        "contract": f"{CONTRACT_NAME} v{CONTRACT_VERSION}",
        "topic": topic,
        "answerable_now": bool(best) and gate.get("posture") != "blocked",
        "current_context_summary": _summary(topic, packs, conflicts, unknowns, withheld),
        "newest_evidence": newest,
        "best_evidence": best,
        "superseded_or_conflicted": conflicts,
        "withheld": withheld,
        "unknowns": unknowns,
        "warnings": warnings,
        "promoted_visibility": promoted_visibility,
        "retrieval": _jsonable(retrieval_result.get("retrieval") or {}),
        "llm_instructions": {
            "treat_as": "bounded_context",
            "do_not_infer": ["canon status", "missing freshness", "unstated authority"],
            "preserve": ["warnings", "withheld", "unknowns", "provenance", "citations"],
            "answer_rule": "Use only returned evidence; label unsupported claims as unknown.",
        },
    }
