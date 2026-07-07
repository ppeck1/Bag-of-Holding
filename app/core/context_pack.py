"""Deterministic context-pack objects for governed retrieval."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import time
from typing import Any, Literal


Operation = Literal[
    "explain",
    "summarize",
    "draft",
    "compare",
    "approve",
    "promote",
    "review",
    "review_request",
    "history",
    "explain_limits",
    "answer_context",
]

Posture = Literal["answerable", "bounded", "review_required", "blocked"]


EXPECTED_PLANES_BY_OPERATION: dict[str, list[str]] = {
    "explain": ["canonical"],
    "summarize": ["informational"],
    "draft": ["informational"],
    "compare": ["informational", "evidence"],
    "approve": ["canonical", "evidence", "trace", "decision"],
    "promote": ["canonical", "trace"],
    "review": ["canonical", "trace"],
    "review_request": ["review", "trace"],
    "history": ["trace"],
    "explain_limits": ["trace"],
    "answer_context": ["informational"],
}


PLANE_ALIASES: dict[str, str] = {
    "canon": "canonical",
    "canonical": "canonical",
    "source": "informational",
    "source_document": "informational",
    "informational": "informational",
    "internal": "internal",
    "evidence": "evidence",
    "review": "review",
    "subjective": "subjective",
    "interpretation": "subjective",
    "decision": "review",
    "trace": "internal",
    "schema_misfit": "review",
}


@dataclass
class ContextPack:
    context_pack_id: str
    query: str
    operation: str
    actor_id: str
    mode: str
    candidate_refs: list[str] = field(default_factory=list)
    expected_planes: list[str] = field(default_factory=list)
    retrieved_planes: list[str] = field(default_factory=list)
    missing_planes: list[str] = field(default_factory=list)
    dominance_policy_ref: str | None = None
    conflict_set_ref: str | None = None
    governance_health_ref: str | None = None
    created_ts: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def stable_context_pack_id(query: str, operation: str, actor_id: str, refs: list[str]) -> str:
    raw = "|".join([query or "", operation or "", actor_id or "", *refs])
    return "ctx_" + hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:24]


def normalize_plane(plane: str | None) -> str:
    key = str(plane or "").strip().lower().replace(" ", "_").replace("-", "_")
    return PLANE_ALIASES.get(key, key)


def expected_planes_for_operation(operation: str) -> list[str]:
    planes = EXPECTED_PLANES_BY_OPERATION.get(str(operation or "answer_context"), ["informational"])
    return list(dict.fromkeys(normalize_plane(p) for p in planes if p))


def pack_ref(pack: dict[str, Any]) -> str:
    return (
        str(pack.get("card_id") or "")
        or str(pack.get("chunk_id") or "")
        or str(pack.get("doc_id") or "")
        or str(pack.get("title") or "")
    )


def actor_id_from(actor: str | dict[str, Any] | None) -> str:
    if isinstance(actor, dict):
        return str(actor.get("actor_id") or actor.get("id") or actor.get("role") or "unknown_actor")
    return str(actor or "unknown_actor")


def plane_from_pack(pack: dict[str, Any]) -> str:
    plane = pack.get("plane")
    if not plane:
        chunk_type = str(pack.get("chunk_type") or "")
        if chunk_type and chunk_type != "plane_card":
            plane = pack.get("canonical_layer") or pack.get("status") or "informational"
        else:
            plane = "informational"
    return normalize_plane(str(plane))


def build_context_pack(
    *,
    query: str,
    operation: str,
    actor: str | dict[str, Any] | None,
    mode: str,
    candidate_packs: list[dict[str, Any]],
    dominance_policy_ref: str | None = None,
    conflict_set_ref: str | None = None,
    governance_health_ref: str | None = None,
) -> ContextPack:
    refs = [pack_ref(p) for p in candidate_packs if pack_ref(p)]
    expected = expected_planes_for_operation(operation)
    retrieved = list(dict.fromkeys(plane_from_pack(p) for p in candidate_packs if plane_from_pack(p)))
    missing = [p for p in expected if p not in retrieved]
    actor_id = actor_id_from(actor)
    return ContextPack(
        context_pack_id=stable_context_pack_id(query, operation, actor_id, refs),
        query=query,
        operation=operation,
        actor_id=actor_id,
        mode=mode,
        candidate_refs=refs,
        expected_planes=expected,
        retrieved_planes=retrieved,
        missing_planes=missing,
        dominance_policy_ref=dominance_policy_ref,
        conflict_set_ref=conflict_set_ref,
        governance_health_ref=governance_health_ref,
    )

