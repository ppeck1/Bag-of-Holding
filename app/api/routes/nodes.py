"""app/api/routes/nodes.py"""
import time
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from app.db import connection as db
from app.core import planar as planar_engine, conflicts as conflict_engine
from app.api.models import PlanarFactRequest

router = APIRouter(prefix="/api")


@router.get("/planes", summary="List all distinct plane paths with fact counts")
def list_planes():
    """Returns all distinct plane_paths from plane_facts. Closes v0P gap."""
    rows = db.fetchall(
        """
        SELECT plane_path, COUNT(*) as fact_count,
               MAX(ts) as last_updated_ts
        FROM plane_facts
        GROUP BY plane_path
        ORDER BY plane_path
        """
    )
    return {"count": len(rows), "planes": rows}


@router.get("/nodes/{node_path:path}", summary="Get planar node facts")
def get_node(node_path: str, include_expired: bool = Query(False)):
    now = int(time.time())
    if include_expired:
        facts = db.fetchall(
            "SELECT * FROM plane_facts WHERE plane_path = ? ORDER BY ts DESC",
            (node_path,),
        )
    else:
        facts = db.fetchall(
            "SELECT * FROM plane_facts WHERE plane_path = ? AND (valid_until IS NULL OR valid_until > ?) ORDER BY ts DESC",
            (node_path, now),
        )
    parts = node_path.split(".")
    parsed = {
        "plane": parts[0] if len(parts) > 0 else None,
        "field": parts[1] if len(parts) > 1 else None,
        "node": parts[2] if len(parts) > 2 else None,
    }
    return {
        "node_path": node_path,
        "parsed": parsed,
        "active_facts": len([f for f in facts if not f.get("valid_until") or f["valid_until"] > now]),
        "facts": facts,
    }


@router.post("/nodes/{node_path:path}", summary="Store a planar fact")
def store_node_fact(node_path: str, req: PlanarFactRequest):
    result = planar_engine.store_fact(
        plane_path=node_path,
        r=req.r, d=req.d, q=req.q, c=req.c,
        context_ref=req.context_ref or "",
        m=req.m, valid_until=req.valid_until, subject_id=req.subject_id,
    )
    if not result.get("stored"):
        raise HTTPException(status_code=422, detail=result.get("errors"))
    conflict_engine.detect_all_conflicts()
    return result
