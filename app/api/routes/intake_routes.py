"""app/api/routes/intake_routes.py: Intake layer read-only API + operator-gated mutations.

GET   /api/intake/capabilities                        — list IntakeCapabilities (filterable)
GET   /api/intake/capabilities/{id}                   — single capability detail
GET   /api/intake/adapters                            — adapter coverage report
GET   /api/intake/safety-lanes                        — lane summary
GET   /api/intake/quarantine                          — active quarantine records (Model A)
POST  /api/intake/run                                 — trigger a batch ingestion run
PATCH /api/intake/capabilities/{id}/operator-disposition — hold or release (operator only)

All read routes are unauthenticated (read-only, local-first tool).
POST /api/intake/run and PATCH .../operator-disposition require the operator token.

operator-disposition contract:
  Only safety_lane is mutated; lifecycle_state remains pipeline-owned.
  action='hold'    → safety_lane='hold'   (allowed source: quarantine, accept)
  action='release' → safety_lane='accept' (allowed source: quarantine, hold;
                     blocks on lifecycle_state='failed' unless force=true)
  actor_id is always server-set ('local_operator'); never accepted from the client.
  UPDATE and audit INSERT execute in one transaction.
  Downstream: safety_lane='accept' makes the capability eligible for list_replayable().
  Release is a lane-change only; reprocessing requires an explicit /api/intake/run call.
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.auth import require_operator
from app.db import connection as db
from app.services.intake.adapter_registry import get_registry

# Frozen allowed source lanes per action.
_HOLD_ALLOWED_LANES: frozenset[str] = frozenset({"quarantine", "accept"})
_RELEASE_ALLOWED_LANES: frozenset[str] = frozenset({"quarantine", "hold"})

router = APIRouter(prefix="/api/intake", tags=["intake"])


# ── WO-2 promotion bridge (operator-gated mutations; read-only listing) ──────────


class PromoteRequest(BaseModel):
    source_revision_id: Optional[str] = None
    intake_capability_id: Optional[str] = None
    batch_id: Optional[str] = None


class DemoteRequest(BaseModel):
    reason: Optional[str] = None


@router.get("/promotable", summary="List promotable handoffs (operator-gated)")
def list_promotable_route(_actor: str = Depends(require_operator)):
    # Operator-gated by audit decision (2026-06-10 pre-commit audit, item B): the payload carries
    # source revision ids, artifact ids, output paths context, and safety metadata — promotion is
    # an operator workflow, so the listing follows the operator boundary (an exception to the
    # module's open-read default, recorded here deliberately).
    from app.services.intake import promotion
    return {"promotable": promotion.list_promotable()}


@router.post("/promote", summary="Promote one completed intake revision to an advisory doc")
def promote_route(req: PromoteRequest, _actor: str = Depends(require_operator)):
    from app.services.intake import promotion
    if not (req.source_revision_id or req.intake_capability_id):
        raise HTTPException(status_code=422,
                            detail="source_revision_id or intake_capability_id required")
    result = promotion.promote(source_revision_id=req.source_revision_id,
                               intake_capability_id=req.intake_capability_id,
                               batch_id=req.batch_id)
    if not result.get("promoted") and not result.get("idempotent"):
        raise HTTPException(status_code=409, detail=result)
    return result


@router.post("/promotions/{promotion_id}/demote",
             summary="Demote (reversibly remove) one promoted doc, scoped by the ledger")
def demote_route(promotion_id: str, req: DemoteRequest | None = None,
                 _actor: str = Depends(require_operator)):
    from app.services.intake import promotion
    result = promotion.demote(promotion_id, reason=(req.reason if req else None))
    if not result.get("demoted") and not result.get("idempotent"):
        raise HTTPException(status_code=404 if "promotion_not_found" in
                            (result.get("reasons") or []) else 409, detail=result)
    return result


# ---------------------------------------------------------------------------
# Read routes
# ---------------------------------------------------------------------------

@router.get("/capabilities", summary="List intake capabilities")
def list_capabilities(
    lifecycle_state: Optional[str] = None,
    safety_lane: Optional[str] = None,
    batch_id: Optional[str] = None,
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
):
    """Return paginated intake capabilities, optionally filtered."""
    clauses = []
    params: list = []
    if lifecycle_state:
        clauses.append("lifecycle_state = ?")
        params.append(lifecycle_state)
    if safety_lane:
        clauses.append("safety_lane = ?")
        params.append(safety_lane)
    if batch_id:
        clauses.append("batch_id = ?")
        params.append(batch_id)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db.fetchall(
        f"SELECT * FROM intake_capabilities {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    total_row = db.fetchone(f"SELECT COUNT(*) AS n FROM intake_capabilities {where}", params)
    total = total_row["n"] if total_row else 0
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


@router.get("/capabilities/{capability_id}", summary="Get single intake capability")
def get_capability(capability_id: str):
    row = db.fetchone(
        "SELECT * FROM intake_capabilities WHERE intake_capability_id = ?",
        (capability_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Capability not found")
    return row


@router.get("/adapters", summary="Adapter coverage report")
def list_adapters():
    """Return the adapter registry coverage report."""
    registry = get_registry()
    return {
        "coverage_report": registry.coverage_report(),
        "capability_summary": registry.capability_summary(),
    }


@router.get("/safety-lanes", summary="Safety lane summary")
def get_safety_lanes():
    """Return counts of capabilities grouped by safety lane."""
    rows = db.fetchall(
        "SELECT safety_lane, COUNT(*) AS count FROM intake_capabilities GROUP BY safety_lane"
    )
    total_row = db.fetchone("SELECT COUNT(*) AS n FROM intake_capabilities")
    total = total_row["n"] if total_row else 0
    return {
        "lanes": {row["safety_lane"]: row["count"] for row in rows},
        "total": total,
    }


@router.get("/quarantine", summary="List active quarantine records (Model A)")
def list_quarantine(limit: int = Query(50, ge=1), offset: int = Query(0, ge=0)):
    """Return quarantine records whose associated capability is still active.

    Model A: only capabilities with safety_lane IN ('quarantine', 'hold') are shown.
    Released capabilities (safety_lane='accept') are excluded. Each row includes
    the current lifecycle_state and current_safety_lane from the capability row.
    """
    rows = db.fetchall(
        """SELECT qr.*, ic.lifecycle_state, ic.safety_lane AS current_safety_lane
           FROM intake_quarantine_records qr
           JOIN intake_capabilities ic
             ON ic.intake_capability_id = qr.intake_capability_id
           WHERE ic.safety_lane IN ('quarantine', 'hold')
           ORDER BY qr.created_at DESC LIMIT ? OFFSET ?""",
        (limit, offset),
    )
    total_row = db.fetchone(
        """SELECT COUNT(*) AS n
           FROM intake_quarantine_records qr
           JOIN intake_capabilities ic
             ON ic.intake_capability_id = qr.intake_capability_id
           WHERE ic.safety_lane IN ('quarantine', 'hold')"""
    )
    total = total_row["n"] if total_row else 0
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


# ---------------------------------------------------------------------------
# Operator-gated: disposition (hold / release)
# ---------------------------------------------------------------------------

class OperatorDispositionRequest(BaseModel):
    action: str        # "hold" | "release"
    reason: str        # required; logged in audit event
    force: bool = False  # only meaningful for release of a failed capability


@router.patch(
    "/capabilities/{capability_id}/operator-disposition",
    summary="Hold or release a capability (operator only)",
)
def operator_disposition(
    capability_id: str,
    req: OperatorDispositionRequest,
    _operator: str = Depends(require_operator),
):
    """Update a capability's safety_lane via an explicit operator action.

    action='hold'    → safety_lane='hold'   (source: quarantine or accept)
    action='release' → safety_lane='accept' (source: quarantine or hold;
                       requires force=true when lifecycle_state='failed')

    lifecycle_state is never modified by this endpoint (pipeline-owned).
    actor_id is always 'local_operator'; it is never accepted from the client.
    The UPDATE and audit INSERT execute in one DB transaction.
    """
    if req.action not in ("hold", "release"):
        raise HTTPException(status_code=422, detail=f"Invalid action '{req.action}'. Must be 'hold' or 'release'.")
    if not (req.reason or "").strip():
        raise HTTPException(status_code=422, detail="reason is required and must not be blank.")

    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM intake_capabilities WHERE intake_capability_id = ?",
            (capability_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Capability not found.")

        row_dict = dict(row)
        current_lane = row_dict["safety_lane"]
        current_lifecycle = row_dict["lifecycle_state"]
        canon_eligible = bool(row_dict.get("canon_eligible", 0))

        # Invariant guard — canon_eligible must never be True on intake rows.
        if canon_eligible:
            conn.execute(
                "INSERT INTO audit_log (event_ts, event_type, actor_type, actor_id, detail) VALUES (?,?,?,?,?)",
                (int(time.time()), "canon_eligible_invariant_violation", "operator", "local_operator",
                 json.dumps({"intake_capability_id": capability_id, "canon_eligible": True})),
            )
            conn.commit()
            raise HTTPException(
                status_code=409,
                detail="canon_eligible invariant violated: this capability has canon_eligible=True. No mutation performed.",
            )

        # Determine target lane.
        target_lane = "hold" if req.action == "hold" else "accept"

        # Idempotency: already in target state — short-circuit before transition validation.
        if current_lane == target_lane:
            return {
                "ok": True,
                "idempotent": True,
                "intake_capability_id": capability_id,
                "action": req.action,
                "safety_lane": current_lane,
            }

        # Validate transition from current state.
        if req.action == "hold":
            if current_lane not in _HOLD_ALLOWED_LANES:
                raise HTTPException(
                    status_code=422,
                    detail=f"Cannot hold a capability with safety_lane='{current_lane}'. "
                           f"Allowed source lanes: {sorted(_HOLD_ALLOWED_LANES)}.",
                )
        else:  # release
            if current_lane not in _RELEASE_ALLOWED_LANES:
                raise HTTPException(
                    status_code=422,
                    detail=f"Cannot release a capability with safety_lane='{current_lane}'. "
                           f"Allowed source lanes: {sorted(_RELEASE_ALLOWED_LANES)}.",
                )
            if current_lifecycle == "failed" and not req.force:
                raise HTTPException(
                    status_code=422,
                    detail="Cannot release a failed capability without force=true. "
                           "Set force=true and provide an explicit reason to override.",
                )

        # Look up the most recent quarantine record for audit context.
        qr_row = conn.execute(
            """SELECT quarantine_record_id FROM intake_quarantine_records
               WHERE intake_capability_id = ? ORDER BY created_at DESC LIMIT 1""",
            (capability_id,),
        ).fetchone()
        quarantine_record_id = dict(qr_row)["quarantine_record_id"] if qr_row else None

        # CAS update — WHERE clause guards against concurrent pipeline mutation.
        result = conn.execute(
            "UPDATE intake_capabilities SET safety_lane = ? WHERE intake_capability_id = ? AND safety_lane = ?",
            (target_lane, capability_id, current_lane),
        )
        if result.rowcount == 0:
            raise HTTPException(
                status_code=409,
                detail="Concurrent state change detected. Read the current state and retry.",
            )

        # Audit event in the same transaction.
        conn.execute(
            "INSERT INTO audit_log (event_ts, event_type, actor_type, actor_id, detail) VALUES (?,?,?,?,?)",
            (
                int(time.time()),
                "intake_operator_disposition_changed",
                "operator",
                "local_operator",
                json.dumps({
                    "intake_capability_id": capability_id,
                    "quarantine_record_id": quarantine_record_id,
                    "action": req.action,
                    "reason": req.reason,
                    "forced": req.force,
                    "before": {
                        "lifecycle_state": current_lifecycle,
                        "safety_lane": current_lane,
                        "canon_eligible": False,
                    },
                    "after": {
                        "lifecycle_state": current_lifecycle,
                        "safety_lane": target_lane,
                        "canon_eligible": False,
                    },
                }),
            ),
        )
        conn.commit()

        return {
            "ok": True,
            "intake_capability_id": capability_id,
            "action": req.action,
            "safety_lane_before": current_lane,
            "safety_lane_after": target_lane,
        }

    except HTTPException:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Operator-gated run trigger
# ---------------------------------------------------------------------------

class IntakeRunRequest(BaseModel):
    source_ref: str
    batch_id: str


@router.post("/run", summary="Trigger a batch ingestion run (operator only)")
def trigger_intake_run(req: IntakeRunRequest, _operator: str = Depends(require_operator)):
    """Run the full intake pipeline for a single source_ref.

    Runs: capability initialization → preservation → translation routing
    → normalization → queryability → interpretation → handoff → DB write.

    Requires BOH_DATA_ROOT to be set.
    """
    from pathlib import Path

    from app.services.intake.orchestrator import execute_intake

    data_root = os.environ.get("BOH_DATA_ROOT", "")
    if not data_root:
        raise HTTPException(
            status_code=422,
            detail="BOH_DATA_ROOT is not configured. Cannot run intake pipeline.",
        )

    if not Path(req.source_ref).exists():
        raise HTTPException(status_code=422, detail=f"Source file not found: {req.source_ref}")

    # Delegate to the shared intake orchestrator (WO-1). Manual intake is idempotent: a known
    # revision returns `already_seen` and creates no new run — use replay for an explicit retry.
    result = execute_intake(source_ref=req.source_ref, batch_id=req.batch_id,
                            trigger_kind="manual", data_root=data_root)

    status_map = {
        "processed": "complete",
        "already_seen": "already_seen",
        "held": "held_or_quarantined",
        "quarantined": "held_or_quarantined",
        "failed": "failed",
    }
    return {
        "status": status_map.get(result.outcome, result.outcome),
        "outcome": result.outcome,
        "intake_capability_id": result.intake_capability_id,
        "source_revision_id": result.source_revision_id,
        "run_id": result.run_id,
        "failure_code": result.failure_code,
        "canon_eligible": False,
    }


class IntakeReplayRequest(BaseModel):
    intake_capability_id: str


@router.post("/replay", summary="Replay a held/failed intake capability (operator only)")
def trigger_intake_replay(req: IntakeReplayRequest, _operator: str = Depends(require_operator)):
    """Explicit governed retry of a previously-ingested capability. WO-1 made `/run` idempotent,
    so a re-POST of a known revision is a no-op; this is the dedicated retry path. Eligibility is
    enforced server-side: only held/failed/complete revisions are reclaimable — quarantined
    (blocked) content is never re-run. `canon_eligible` is never true."""
    from app.services.intake.replay import reprocess, ReplayConfigError
    try:
        result = reprocess(req.intake_capability_id)
    except ReplayConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "status": "complete" if result.success else "not_reprocessed",
        "success": result.success,
        "stage_reached": result.stage_reached,
        "intake_capability_id": result.intake_capability_id,
        "failure_reason": result.failure_reason,
        "canon_eligible": False,
    }
