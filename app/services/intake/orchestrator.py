"""Shared intake orchestrator for WO-1 (Gate B / B3, Gate B.5 corrections).

One execution substrate used by the scheduler, manual intake, and replay. It owns the pipeline
AFTER each caller's own validation: run creation, capability init, preservation, routing,
normalization, queryability, interpretation, handoff, and the terminal run + revision + lease
state — persisting EVERY emitted trace (success and failure), atomically per stage.

Gate B.5 corrections:
- The orchestrator holds the claim token and REFRESHES the lease at each stage while it still
  owns the claim. If a refresh loses ownership (a reconciler expired the lease), it FAILS CLOSED:
  it marks only its own run as `lost_lease` and does NOT write terminal revision state.
- Replay reclaims atomically (terminal -> claimed) via the service, never exposing 'discovered'.

`canon_eligible` stays False on every path (asserted by the writer).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Callable

from app.core.planar_service_schemas import QuarantineRecord
from app.db import connection as db
from app.services.intake import intake_writer as W
from app.services.intake import source_revision_service as revsvc
from app.services.intake import trace as trace_module
from app.services.intake.adapter_registry import adapter_registry_fingerprint
from app.services.intake.capability import initialize_capability
from app.services.intake.clock import utc_now_iso
from app.services.intake.governance_handoff import assemble_handoff
from app.services.intake.hashing import sha256_file
from app.services.intake.interpretation import produce_evidence_units
from app.services.intake.normalization import normalize
from app.services.intake.preservation import invalidate_registry_entry, preserve_file
from app.services.intake.queryability import assess
from app.services.intake.source_revision import (
    canonicalize_source_ref, compute_source_revision_id, resolve_policy_snapshot)
from app.services.intake.translation_router import route

logger = logging.getLogger(__name__)

ConnFactory = Callable[[], sqlite3.Connection]
_DETAIL_MAX = 500


class LostLeaseError(Exception):
    """Raised when a stage-boundary lease refresh finds this token no longer owns the claim."""


@dataclass
class IntakeExecutionResult:
    outcome: str  # processed | already_seen | failed | held | quarantined
    source_revision_id: str | None = None
    run_id: str | None = None
    intake_capability_id: str | None = None
    failure_code: str | None = None
    failure_detail: str | None = None
    canon_eligible: bool = False  # always False


def _factory(conn_factory: ConnFactory | None) -> ConnFactory:
    return conn_factory or db.get_conn


def active_policy_snapshot() -> str | None:
    """The currently-configured active policy snapshot (WO-1.1 Phase B). Scheduler and manual intake
    resolve the SAME active contract pair (this + `adapter_registry_fingerprint()`), so identical
    bytes under the same active contract get the same source-revision identity regardless of caller."""
    return os.environ.get("BOH_INTAKE_POLICY_SNAPSHOT_BIND") or None


def _ensure_ownership(srid: str, claim_token: str | None, cf: ConnFactory) -> None:
    """Refresh + verify the lease. Raises LostLeaseError if ownership was lost."""
    if claim_token is None:
        return  # ownership tracking disabled (no token supplied)
    if not revsvc.refresh_lease(srid, claim_token, conn_factory=cf):
        raise LostLeaseError(srid)


def _ledger_source_hash(conn, source_revision_id: str) -> str | None:
    """Authoritative claimed-revision content hash from the DURABLE ledger row (positional access so
    it is independent of the connection's row_factory). Returns None if the revision can't be loaded
    or has no stored hash."""
    try:
        row = conn.execute(
            "SELECT source_hash_sha256 FROM intake_source_revisions WHERE source_revision_id=?",
            (source_revision_id,)).fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    return row[0] or None


def _safe_remove_preserved(pres, data_root: str | None) -> bool:
    """Delete the on-disk RAW copy from a preserve we are REJECTING (the source changed after claim).
    Returns True iff no ordinary RAW file remains at the success location. Called ONLY after a durable
    invalidation tombstone exists; the bytes are not retained as an ordinary RAW artifact."""
    if pres is None or getattr(pres, "raw_artifact", None) is None:
        return True
    p = pres.raw_artifact.preservation_path
    root = data_root or os.environ.get("BOH_DATA_ROOT", "")
    abs_path = p if os.path.isabs(p) else os.path.join(root, p)
    try:
        if os.path.exists(abs_path):
            os.remove(abs_path)
        return not os.path.exists(abs_path)
    except OSError:
        logger.exception("failed to remove orphaned RAW copy at %s", abs_path)
        return False


_QUARANTINE_CATEGORY = {
    "executable_block": "executable_blocked",
    "archive_hold": "archive_pending_review",
}


def _finalize(conn, *, run_id, source_revision_id, capability, claim_token, run_state, rev_state,
              failure_code=None, failure_detail=None) -> None:
    """Token-conditioned, atomic terminal transition. Raises LostLeaseError (fail closed) if this
    worker no longer owns the claim, so it cannot overwrite a reconciler transition."""
    owned = W.finalize_owned(
        conn,
        source_revision_id=source_revision_id, claim_token=claim_token, rev_state=rev_state,
        run_update={
            "run_id": run_id, "lifecycle_state": run_state, "stage_reached": "terminal",
            "failure_code": failure_code, "failure_detail": failure_detail,
            "finished_at": utc_now_iso(),
        },
        capability=capability,
    )
    if not owned:
        raise LostLeaseError(source_revision_id)


def run_pipeline_for_claimed_revision(
    *,
    source_ref: str,
    batch_id: str,
    source_revision_id: str,
    trigger_kind: str,
    claim_token: str | None = None,
    policy_snapshot_hash: str | None = None,
    data_root: str | None = None,
    expected_source_hash: str | None = None,
    conn_factory: ConnFactory | None = None,
) -> IntakeExecutionResult:
    """Run the full pipeline for a revision the caller has ALREADY claimed (passing its
    `claim_token`). Persists every stage + trace, refreshes the lease at each stage, and sets
    terminal run/revision/lease state. Fails closed on lost ownership.

    Byte-binding (WO-1.1 P0 + addendum): the claimed revision's `source_hash_sha256` is loaded from
    the DURABLE `intake_source_revisions` ledger and is AUTHORITATIVE — the preserved bytes MUST hash
    to it on every claimed path (scheduler/manual/replay), regardless of whether a caller supplied a
    hash. `expected_source_hash`, if given, is only an ASSERTION that must equal the ledger value.
    Inability to load the claimed revision, a caller assertion mismatch, or a post-claim content
    change all fail closed with a structured code; a rejected preserve leaves NO RAW artifact (and no
    orphaned copy) on the stale identity. A later scan mints the correct new revision."""
    cf = _factory(conn_factory)
    conn = cf()
    run_id = uuid.uuid4().hex
    cap = None
    try:
        # Authoritative claimed-revision hash from the durable ledger (loaded BEFORE create_run so an
        # unloadable revision fails closed cleanly without tripping the runs->revisions foreign key).
        ledger_hash = _ledger_source_hash(conn, source_revision_id)
        if not ledger_hash:
            code = "claimed_revision_not_found"
            W.create_run(conn, run_id=run_id, source_ref_snapshot=source_ref,
                         trigger_kind=trigger_kind, batch_id=batch_id)  # no source_revision_id (FK-safe)
            W.persist_stage_transition(conn, run_update={
                "run_id": run_id, "lifecycle_state": "failed", "stage_reached": "terminal",
                "failure_code": code,
                "failure_detail": f"no ledger source hash for revision {source_revision_id}"[:_DETAIL_MAX],
                "finished_at": utc_now_iso()})
            return IntakeExecutionResult("failed", source_revision_id, run_id, None, failure_code=code)

        W.create_run(conn, run_id=run_id, source_ref_snapshot=source_ref,
                     trigger_kind=trigger_kind, source_revision_id=source_revision_id,
                     batch_id=batch_id)

        _ensure_ownership(source_revision_id, claim_token, cf)
        init = initialize_capability(source_ref=source_ref, batch_id=batch_id,
                                     policy_snapshot_hash=policy_snapshot_hash)
        cap = init.capability
        W.persist_stage_transition(
            conn,
            run_update={"run_id": run_id, "stage_reached": "capability",
                        "intake_capability_id": cap.intake_capability_id},
            capability=cap, trace_events=[init.trace_event],
        )

        # A caller-supplied expected hash is an assertion only: it must equal the ledger value.
        if expected_source_hash is not None and expected_source_hash != ledger_hash:
            code = "expected_hash_mismatch"
            te = trace_module.emit(code, intake_capability_id=cap.intake_capability_id,
                                   detail={"expected_source_hash": expected_source_hash,
                                           "ledger_source_hash": ledger_hash})
            cap.trace_event_refs.append(te.trace_event_id)
            cap.lifecycle_state = "failed"
            W.persist_stage_transition(
                conn, run_update={"run_id": run_id, "stage_reached": "binding"},
                capability=cap, trace_events=[te])
            _finalize(conn, run_id=run_id, source_revision_id=source_revision_id, capability=cap,
                      claim_token=claim_token, run_state="failed", rev_state="failed",
                      failure_code=code,
                      failure_detail=(f"caller expected {expected_source_hash[:12]} != "
                                      f"ledger {ledger_hash[:12]}")[:_DETAIL_MAX])
            return IntakeExecutionResult("failed", source_revision_id, run_id,
                                         cap.intake_capability_id, failure_code=code)

        # Route BEFORE preservation: adapters for hold/quarantine/ignore declare can_preserve=False,
        # so blocked/held files must NOT be copied into RAW. Decide first; finalize metadata-only.
        _ensure_ownership(source_revision_id, claim_token, cf)
        decision = route(cap)
        if decision.route in ("quarantine", "hold", "ignore"):
            if decision.route == "quarantine":
                cap.safety_lane = "quarantine"
                cap.lifecycle_state = "quarantined"
                qr = QuarantineRecord(
                    intake_capability_id=cap.intake_capability_id,
                    quarantine_reason=decision.reason,
                    quarantine_category=_QUARANTINE_CATEGORY.get(decision.adapter_id, "unsupported"),
                )
                te = trace_module.emit(
                    "metadata_only_quarantine", intake_capability_id=cap.intake_capability_id,
                    detail={"adapter": decision.adapter_id, "route": "quarantine",
                            "preserved": False, "reason": decision.reason})
                cap.trace_event_refs.append(te.trace_event_id)
                W.persist_stage_transition(
                    conn, run_update={"run_id": run_id, "stage_reached": "routing"},
                    capability=cap, trace_events=[te], quarantine_record=qr)
                rev_state = "quarantined"
            else:  # hold / ignore — metadata only, no content copy
                cap.lifecycle_state = "held"
                te = trace_module.emit(
                    "metadata_only_hold", intake_capability_id=cap.intake_capability_id,
                    detail={"adapter": decision.adapter_id, "route": decision.route,
                            "preserved": False, "reason": decision.reason})
                cap.trace_event_refs.append(te.trace_event_id)
                W.persist_stage_transition(
                    conn, run_update={"run_id": run_id, "stage_reached": "routing"},
                    capability=cap, trace_events=[te])
                rev_state = "held"
            _finalize(conn, run_id=run_id, source_revision_id=source_revision_id, capability=cap,
                      claim_token=claim_token, run_state=rev_state, rev_state=rev_state,
                      failure_code=f"route_{rev_state}")
            return IntakeExecutionResult(rev_state, source_revision_id, run_id,
                                         cap.intake_capability_id, failure_code=f"route_{rev_state}")

        # direct_stage / html_neutralize — preservation is permitted (can_preserve=True)
        _ensure_ownership(source_revision_id, claim_token, cf)
        pres = preserve_file(cap, data_root=data_root, policy_snapshot_hash=policy_snapshot_hash)

        # Bind the claimed revision identity to the preserved bytes using the AUTHORITATIVE ledger
        # hash. If the source changed between claim and copy, the preserved hash won't match — fail
        # closed, delete the orphaned copy (no ordinary RAW artifact left at the success location),
        # and attach NO RAW row to the stale identity. SQLite is the ledger of record.
        if (pres.success and pres.raw_artifact is not None
                and pres.raw_artifact.preserved_hash_sha256 != ledger_hash):
            # preserve_file already appended a success-looking source_registry.jsonl record. Reconcile
            # CRASH-SAFELY: durably tombstone the registry FIRST, and only after the durable tombstone
            # exists delete the orphan RAW file — so a crash can never leave a success-looking record
            # without a dominating tombstone.
            tombstoned = invalidate_registry_entry(
                data_root, cap.batch_id, pres.raw_artifact, "source_changed_before_preservation")
            if not tombstoned:
                # Tombstone not durable: do NOT delete the orphan; fail closed with a distinct reason.
                code = "registry_invalidation_failed"
                detail = f"registry tombstone append failed for {pres.raw_artifact.raw_artifact_id}"
            else:
                code = "source_changed_before_preservation"
                detail = f"ledger {ledger_hash[:12]} got {pres.raw_artifact.preserved_hash_sha256[:12]}"
                if not _safe_remove_preserved(pres, data_root):
                    # Tombstone is durable; the orphan is retained as explicitly-invalidated evidence.
                    detail += "; orphan_cleanup_failed_retained_as_invalidated_evidence"
            te = trace_module.emit(
                code, intake_capability_id=cap.intake_capability_id,
                detail={"ledger_source_hash": ledger_hash,
                        "preserved_hash": pres.raw_artifact.preserved_hash_sha256,
                        "preserved": False, "reason": code})
            cap.trace_event_refs.append(te.trace_event_id)
            cap.lifecycle_state = "failed"
            W.persist_stage_transition(
                conn, run_update={"run_id": run_id, "stage_reached": "preservation"},
                capability=cap, trace_events=[te])  # no raw_artifact: not attached to the old identity
            _finalize(conn, run_id=run_id, source_revision_id=source_revision_id, capability=cap,
                      claim_token=claim_token, run_state="failed", rev_state="failed",
                      failure_code=code, failure_detail=detail[:_DETAIL_MAX])
            return IntakeExecutionResult("failed", source_revision_id, run_id,
                                         cap.intake_capability_id, failure_code=code)
        W.persist_stage_transition(
            conn,
            run_update={"run_id": run_id, "stage_reached": "preservation"},
            capability=cap, trace_events=pres.trace_events,
            raw_artifact=pres.raw_artifact, quarantine_record=pres.quarantine_record,
        )
        if not pres.success:
            state = "quarantined" if pres.quarantine_record else "failed"
            code = "preservation_quarantine" if pres.quarantine_record else "preservation_failed"
            _finalize(conn, run_id=run_id, source_revision_id=source_revision_id, capability=cap,
                      claim_token=claim_token, run_state=state, rev_state=state, failure_code=code,
                      failure_detail=(pres.failure_reason or "")[:_DETAIL_MAX])
            return IntakeExecutionResult(state, source_revision_id, run_id,
                                         cap.intake_capability_id, failure_code=code)

        _ensure_ownership(source_revision_id, claim_token, cf)
        norm = normalize(pres.raw_artifact, cap, decision, data_root=data_root)
        W.persist_stage_transition(
            conn,
            run_update={"run_id": run_id, "stage_reached": "normalization"},
            capability=cap, trace_events=norm.trace_events,
            normalized_artifact=norm.normalized_artifact, adapter_run=norm.adapter_run,
        )
        if not norm.success:
            _finalize(conn, run_id=run_id, source_revision_id=source_revision_id, capability=cap,
                      claim_token=claim_token, run_state="failed", rev_state="failed",
                      failure_code="normalization_failed",
                      failure_detail=(norm.failure_reason or "")[:_DETAIL_MAX])
            return IntakeExecutionResult("failed", source_revision_id, run_id,
                                         cap.intake_capability_id, failure_code="normalization_failed")

        _ensure_ownership(source_revision_id, claim_token, cf)
        q = assess(norm.normalized_artifact, cap, data_root=data_root)
        W.persist_stage_transition(
            conn,
            run_update={"run_id": run_id, "stage_reached": "queryability"},
            capability=cap, trace_events=q.trace_events,
        )

        evidence_units = []
        if cap.queryable:
            interp = produce_evidence_units(norm.normalized_artifact, cap, data_root=data_root)
            evidence_units = interp.evidence_units
            W.persist_stage_transition(
                conn,
                run_update={"run_id": run_id, "stage_reached": "interpretation"},
                capability=cap, trace_events=interp.trace_events,
            )

        _ensure_ownership(source_revision_id, claim_token, cf)
        handoff = assemble_handoff(capability=cap, raw_artifact=pres.raw_artifact,
                                   normalized_artifact=norm.normalized_artifact,
                                   evidence_units=evidence_units)
        handoff_row = None
        if (handoff.success and handoff.handoff_packet is not None
                and norm.normalized_artifact is not None
                and cap.queryable and cap.normalizable):
            # Durable promotability source of truth (WO-2 / DEC-0003): carries the full new-era
            # chain (capability -> run -> revision) plus the content-keyed artifact identity,
            # which may belong to an earlier fingerprint era. Contract values come from the
            # durable revision ledger, never from in-memory state.
            rev_contract = conn.execute(
                "SELECT policy_snapshot_hash, adapter_registry_version "
                "FROM intake_source_revisions WHERE source_revision_id = ?",
                (source_revision_id,),
            ).fetchone()
            now = utc_now_iso()
            handoff_row = {
                # Row id is unique per handoff EVENT (reassessments append; the packet's
                # deterministic per-capability id would collide on reprocess).
                "handoff_id": f"ho_{uuid.uuid4().hex[:20]}",
                "intake_capability_id": cap.intake_capability_id,
                "intake_run_id": run_id,
                "source_revision_id": source_revision_id,
                "normalized_artifact_id": norm.normalized_artifact.normalized_artifact_id,
                "handoff_ready": 1,
                "handoff_at": now,
                "adapter_id": (norm.adapter_run.adapter_id if norm.adapter_run
                               else decision.adapter_id or ""),
                "adapter_version": (norm.adapter_run.adapter_version if norm.adapter_run else ""),
                "adapter_registry_version": rev_contract[1],
                "policy_snapshot_hash": rev_contract[0],
                "normalized_output_type": norm.normalized_artifact.output_type,
                # DEC-0004.2: the explicit transformation-visible classification lives HERE,
                # never in the core artifact output_type.
                "normalized_output_profile": ("html_neutralized_markdown"
                                              if decision.route == "html_neutralize" else None),
                "warnings_json": json.dumps(list(handoff.handoff_packet.warnings or [])),
                "created_at": now,
            }
        W.persist_stage_transition(
            conn,
            run_update={"run_id": run_id, "stage_reached": "handoff"},
            capability=cap, trace_events=handoff.trace_events,
            handoff_row=handoff_row,
        )

        _ensure_ownership(source_revision_id, claim_token, cf)
        _finalize(conn, run_id=run_id, source_revision_id=source_revision_id, capability=cap,
                  claim_token=claim_token, run_state="complete", rev_state="complete")
        return IntakeExecutionResult("processed", source_revision_id, run_id,
                                     cap.intake_capability_id)

    except LostLeaseError:
        # Ownership lost: another process (reconciler) now owns the revision. Mark ONLY our run;
        # do NOT write terminal revision/lease state we no longer own.
        logger.warning("intake run %s lost its lease for revision %s; failing closed",
                       run_id, source_revision_id)
        try:
            W.persist_stage_transition(conn, run_update={
                "run_id": run_id, "lifecycle_state": "failed", "stage_reached": "terminal",
                "failure_code": "lost_lease", "failure_detail": "claim no longer owned",
                "finished_at": utc_now_iso()})
        except Exception:
            logger.exception("failed to record lost-lease run state for %s", run_id)
        return IntakeExecutionResult("failed", source_revision_id, run_id,
                                     cap.intake_capability_id if cap else None,
                                     failure_code="lost_lease")
    except Exception as exc:  # noqa: BLE001 — record + log, never swallow
        logger.exception("intake orchestration failed (trigger=%s source=%s revision=%s)",
                         trigger_kind, source_ref, source_revision_id)
        detail = f"{type(exc).__name__}: {exc}"[:_DETAIL_MAX]
        try:
            _finalize(conn, run_id=run_id, source_revision_id=source_revision_id, capability=cap,
                      claim_token=claim_token, run_state="failed", rev_state="failed",
                      failure_code="unexpected_exception", failure_detail=detail)
        except LostLeaseError:
            try:
                W.persist_stage_transition(conn, run_update={
                    "run_id": run_id, "lifecycle_state": "failed", "stage_reached": "terminal",
                    "failure_code": "lost_lease", "failure_detail": "claim lost during failure",
                    "finished_at": utc_now_iso()})
            except Exception:
                logger.exception("failed to record lost-lease run state for %s", run_id)
        except Exception:
            logger.exception("intake finalize failed for run %s", run_id)
        return IntakeExecutionResult("failed", source_revision_id, run_id,
                                     cap.intake_capability_id if cap else None,
                                     failure_code="unexpected_exception", failure_detail=detail)
    finally:
        conn.close()


def execute_intake(
    *,
    source_ref: str,
    batch_id: str,
    trigger_kind: str,
    policy_snapshot_hash: str | None = None,
    data_root: str | None = None,
    source_hash: str | None = None,
    claimed_by: str | None = None,
    conn_factory: ConnFactory | None = None,
) -> IntakeExecutionResult:
    """Entry for MANUAL / fresh-discovery callers: register/observe the revision under the CURRENT
    active contract, apply idempotency, claim, then run the pipeline. The scheduler claims itself and
    calls `run_pipeline_for_claimed_revision` directly.

    REPLAY is NOT permitted through this path — it would (re)register a new identity under the current
    contract. Strict replay must begin from a stored revision via `replay_revision()`.

    - manual: a known terminal/claimed revision returns `already_seen` (no new run).
    """
    cf = _factory(conn_factory)
    if trigger_kind == "replay":
        # Fail closed: do not let replay register a fresh identity here. No row is written.
        return IntakeExecutionResult(
            "failed", None, None, None, failure_code="replay_via_execute_intake_forbidden",
            failure_detail="use orchestrator.replay_revision() for strict stored-revision replay")
    # New discovery binds the ACTIVE policy snapshot (paired with the adapter fingerprint below) so
    # manual and scheduler produce the same identity under the same active contract.
    if policy_snapshot_hash is None:
        policy_snapshot_hash = active_policy_snapshot()

    if source_hash is None:
        try:
            source_hash = sha256_file(source_ref)
        except OSError as exc:
            run_id = uuid.uuid4().hex
            conn = cf()
            try:
                W.create_run(conn, run_id=run_id, source_ref_snapshot=source_ref,
                             trigger_kind=trigger_kind)
                W.persist_stage_transition(conn, run_update={
                    "run_id": run_id, "lifecycle_state": "failed", "stage_reached": "terminal",
                    "failure_code": "source_unreadable", "failure_detail": str(exc)[:_DETAIL_MAX],
                    "finished_at": utc_now_iso()})
            finally:
                conn.close()
            return IntakeExecutionResult("failed", None, run_id, None,
                                         failure_code="source_unreadable")

    try:
        byte_size = max(0, os.path.getsize(source_ref))
    except OSError:
        byte_size = 0

    row, _created = revsvc.register_or_observe_revision(
        source_ref=source_ref, source_hash_sha256=source_hash, byte_size=byte_size,
        policy_snapshot_hash=policy_snapshot_hash,
        adapter_registry_version=adapter_registry_fingerprint(), conn_factory=cf,
    )
    srid = row["source_revision_id"]
    state = row["lifecycle_state"]

    # Non-replay (manual / fresh discovery): a known terminal/claimed revision is idempotent.
    if state in revsvc.TERMINAL_STATES or state == "claimed":
        return IntakeExecutionResult("already_seen", srid, None, None)
    token = revsvc.try_claim_revision(srid, claimed_by=claimed_by or trigger_kind, conn_factory=cf)
    if not token:
        return IntakeExecutionResult("already_seen", srid, None, None)

    return run_pipeline_for_claimed_revision(
        source_ref=source_ref, batch_id=batch_id, source_revision_id=srid,
        trigger_kind=trigger_kind, claim_token=token, policy_snapshot_hash=policy_snapshot_hash,
        data_root=data_root, expected_source_hash=source_hash, conn_factory=cf,
    )


def replay_revision(
    *,
    source_revision_id: str,
    source_ref: str,
    batch_id: str,
    data_root: str | None = None,
    conn_factory: ConnFactory | None = None,
) -> IntakeExecutionResult:
    """Strict REPLAY (WO-1.1 Phase B): re-run the EXACT stored revision identity.

    Begins from the stored `source_revision_id`, loads the durable row, and requires the stored
    execution contract (adapter-registry fingerprint + policy snapshot) to be reproducible by the
    currently-executable contract — there is no historical contract resolver. It reclaims the SAME
    stored revision (never minting a replacement) and binds preserved bytes to the STORED source
    hash. Fails closed with a structured reason if the contract cannot be reproduced (so a run is
    never executed under current adapter behavior while labelled with an older fingerprint)."""
    cf = _factory(conn_factory)
    conn = cf()
    try:
        row = conn.execute(
            "SELECT canonical_source_ref, source_hash_sha256, policy_snapshot_hash, "
            "adapter_registry_version FROM intake_source_revisions WHERE source_revision_id=?",
            (source_revision_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return IntakeExecutionResult("failed", source_revision_id, None, None,
                                     failure_code="replay_revision_not_found")
    stored_canonical, stored_hash, stored_policy, stored_adapter = row[0], row[1], row[2], row[3]

    # The canonical source PATH is part of srid-v1 identity: identical bytes from a different path are
    # a different revision and must not be replayed under this identity.
    if canonicalize_source_ref(source_ref) != stored_canonical:
        return IntakeExecutionResult("failed", source_revision_id, None, None,
                                     failure_code="replay_source_ref_mismatch")

    # Reproduce the stored contract EXACTLY or fail closed. (Sentinel-era revisions stored the
    # unversioned adapter sentinel, which never equals a real fingerprint -> fail closed.)
    if stored_adapter != adapter_registry_fingerprint():
        return IntakeExecutionResult("failed", source_revision_id, None, None,
                                     failure_code="replay_adapter_contract_unavailable")
    if stored_policy != resolve_policy_snapshot(active_policy_snapshot()):
        return IntakeExecutionResult("failed", source_revision_id, None, None,
                                     failure_code="replay_policy_contract_unavailable")
    # Defensive identity integrity: the stored row must hash back to its own id.
    if compute_source_revision_id(
            canonical_source_ref=stored_canonical, source_hash_sha256=stored_hash,
            policy_snapshot_hash=stored_policy, adapter_registry_version=stored_adapter,
    ) != source_revision_id:
        return IntakeExecutionResult("failed", source_revision_id, None, None,
                                     failure_code="replay_contract_mismatch")

    token = revsvc.reopen_and_claim_for_replay(source_revision_id, claimed_by="replay", conn_factory=cf)
    if not token:
        return IntakeExecutionResult("already_seen", source_revision_id, None, None)
    # Re-run the SAME identity, bind preserved bytes to the STORED hash, run under the STORED policy.
    return run_pipeline_for_claimed_revision(
        source_ref=source_ref, batch_id=batch_id, source_revision_id=source_revision_id,
        trigger_kind="replay", claim_token=token, policy_snapshot_hash=stored_policy,
        data_root=data_root, expected_source_hash=stored_hash, conn_factory=cf)


def link_reprocess_trace(
    *,
    prior_source_revision_id: str,
    new_source_revision_id: str,
    new_capability_id: str,
    conn_factory: ConnFactory | None = None,
) -> None:
    """Record a durable prior->new revision link for an explicit reprocess. Stored as an
    `intake_trace_events` row (`event_type='reprocessed_from'`, link in `detail_json`) — no schema
    migration required."""
    te = trace_module.emit(
        "reprocessed_from", intake_capability_id=new_capability_id,
        detail={"prior_source_revision_id": prior_source_revision_id,
                "new_source_revision_id": new_source_revision_id})
    conn = _factory(conn_factory)()
    try:
        W.persist_stage_transition(conn, trace_events=[te])
    finally:
        conn.close()
