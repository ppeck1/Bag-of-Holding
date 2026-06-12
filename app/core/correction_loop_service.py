"""CorrectionLoopService -- a single read-only deterministic view over Phase 8.

This is a thin composition layer over the existing, individually-tested Phase 8
correction-loop primitives. It introduces NO new policy logic and performs NO
writes: it reads the established records and aggregates them into one
CorrectionLoopView so downstream consumers (context assembly, UI: Trace Ledger,
Review Queue, Residence Map) read the loop status from one stable surface
instead of re-joining scattered accessors by hand.

Composed records (all from app.core.correction_ledger):
  - MistakeEvent             -> get_mistake_event
  - PatchProposal            -> list_patch_proposals (joined by proposed_from)
  - CanonChangeRecord        -> list_canon_change_records (joined by patch_proposal_ref)
  - InformationResidenceMap  -> list_information_residence (joined by location refs)

Read-only by contract: this service performs no writes, never mutates the DB,
and never sets canon_eligible. It is deterministic -- the same input records
yield an equal CorrectionLoopView.to_dict() (no wall-clock field is added).
The correction loop is human-gated: forbidden_auto_apply is always True.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from app.core import correction_ledger


# loop_stage values, lowest -> highest precedence.
STAGE_DETECTED = "detected"
STAGE_PROPOSED = "proposed"
STAGE_ADJUDICATED = "adjudicated"
STAGE_RECORDED = "recorded"
STAGE_RESOLVED = "resolved"

_RESOLVED_RESIDENCE_STATUSES = {"superseded", "merged", "split", "deprecated", "quarantined"}


def _stable_view_id(
    mistake_id: str,
    proposal_ids: list[str],
    canon_change_ids: list[str],
    residence_ids: list[str],
) -> str:
    raw = json.dumps(
        {
            "mistake_id": mistake_id,
            "proposal_ids": sorted(proposal_ids),
            "canon_change_ids": sorted(canon_change_ids),
            "residence_ids": sorted(residence_ids),
        },
        sort_keys=True,
        default=str,
    )
    return "clv_" + hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:24]


def _adjudication(proposals: list[dict[str, Any]]) -> str:
    statuses = {str(p.get("status") or "proposed") for p in proposals}
    if not statuses:
        return "none"
    if len(statuses) == 1:
        return next(iter(statuses))
    return "mixed"


def _loop_stage(
    mistake: dict[str, Any] | None,
    proposals: list[dict[str, Any]],
    canon_change_records: list[dict[str, Any]],
    residences: list[dict[str, Any]],
) -> str:
    if canon_change_records:
        if any(str(r.get("status")) in _RESOLVED_RESIDENCE_STATUSES for r in residences):
            return STAGE_RESOLVED
        return STAGE_RECORDED
    if any(str(p.get("status") or "proposed") != "proposed" for p in proposals):
        return STAGE_ADJUDICATED
    if proposals:
        return STAGE_PROPOSED
    return STAGE_DETECTED


@dataclass
class CorrectionLoopView:
    """Aggregated, deterministic read-only view of one correction loop.

    Carries no wall-clock field of its own so it is reproducible. canon_eligible
    is re-forced to False and forbidden_auto_apply to True -- this service never
    grants canon eligibility and the loop is always human-gated.
    """

    mistake_id: str
    mistake: dict[str, Any] | None = None
    proposals: list[dict[str, Any]] = field(default_factory=list)
    adjudication: str = "none"
    canon_change_records: list[dict[str, Any]] = field(default_factory=list)
    residence: list[dict[str, Any]] = field(default_factory=list)
    loop_stage: str = STAGE_DETECTED
    forbidden_auto_apply: bool = True  # INVARIANT: always True
    canon_eligible: bool = False  # INVARIANT: always False
    view_id: str = ""

    def __post_init__(self) -> None:
        self.forbidden_auto_apply = True
        self.canon_eligible = False
        if not self.view_id:
            self.view_id = _stable_view_id(
                self.mistake_id,
                [str(p.get("patch_id")) for p in self.proposals if p.get("patch_id")],
                [str(r.get("canon_change_id")) for r in self.canon_change_records if r.get("canon_change_id")],
                [str(r.get("residence_id")) for r in self.residence if r.get("residence_id")],
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assemble(
    mistake: dict[str, Any] | None,
    proposals: list[dict[str, Any]] | None = None,
    canon_change_records: list[dict[str, Any]] | None = None,
    residences: list[dict[str, Any]] | None = None,
    *,
    mistake_id: str | None = None,
) -> CorrectionLoopView:
    """Compose already-gathered Phase 8 records into one CorrectionLoopView.

    Pure: takes records as inputs, performs no I/O, and is deterministic for
    fixed inputs. `mistake_id` is taken from the mistake record when present,
    else from the explicit keyword (so a not-yet-emitted loop can still be keyed).
    """
    proposals = list(proposals or [])
    canon_change_records = list(canon_change_records or [])
    residences = list(residences or [])
    mid = str((mistake or {}).get("mistake_id") or mistake_id or "")

    return CorrectionLoopView(
        mistake_id=mid,
        mistake=mistake,
        proposals=proposals,
        adjudication=_adjudication(proposals),
        canon_change_records=canon_change_records,
        residence=residences,
        loop_stage=_loop_stage(mistake, proposals, canon_change_records, residences),
    )


def load(mistake_id: str, *, limit: int = 1000) -> CorrectionLoopView:
    """Read the loop's records via the existing ledger accessors and assemble them.

    Read-only: calls only `get_*`/`list_*` accessors and never writes. The joins
    are deterministic set-membership: proposals by `proposed_from == mistake_id`,
    canon-change records by `patch_proposal_ref` in the proposal ids, and
    residences whose `original_ref`/`current_ref` appears in any canon-change
    record's old/new/supersedes location refs.
    """
    mistake = correction_ledger.get_mistake_event(mistake_id)

    proposals = [
        p for p in correction_ledger.list_patch_proposals(limit=limit)
        if str(p.get("proposed_from")) == str(mistake_id)
    ]
    proposal_ids = {str(p.get("patch_id")) for p in proposals if p.get("patch_id")}

    canon_change_records = [
        r for r in correction_ledger.list_canon_change_records(limit=limit)
        if str(r.get("patch_proposal_ref")) in proposal_ids
    ]

    location_refs: set[str] = set()
    for r in canon_change_records:
        for key in ("old_location_refs", "new_location_refs", "supersedes_refs"):
            for ref in r.get(key) or []:
                location_refs.add(str(ref))

    residences = [
        res for res in correction_ledger.list_information_residence(limit=limit)
        if str(res.get("original_ref")) in location_refs
        or str(res.get("current_ref")) in location_refs
    ]

    return assemble(
        mistake, proposals, canon_change_records, residences, mistake_id=mistake_id
    )
