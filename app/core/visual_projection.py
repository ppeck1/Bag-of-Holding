"""Projection-ready Atlas graph model for BOH visualization.

Phase 17.3: Mode-specific projection semantics.
Each mode answers a different operational question and returns a distinct
coordinate space, color contract, and sidebar payload.

Modes
-----
web          — relationship network (organic cluster layout)
variable     — variable intensity map (same positions; color/size = variable signal)
constraint   — instability geometry  (x = project band, y = risk pressure)
constitutional — authority lanes      (draft → review → approved → canonical → archived)
"""
from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from statistics import mean
from typing import Any

from app.core.related import get_graph_data

MODES = {"web", "variable", "constraint", "constitutional"}

PROJECTION_IDS = {
    "web":           "web_relationship_graph_v1",
    "variable":      "variable_overlay_v1",
    "constraint":    "constraint_geometry_v1",
    "constitutional": "constitutional_authority_v1",
}

# Authority-bearing edge types — used for constitutional filtering and lineage tracking.
AUTHORITY_EDGE_TYPES = frozenset({
    "lineage", "supersedes", "derives", "derived_from",
    "promotion", "review", "rollback",
})

CANON_PATTERNS = {
    "ΩV":  ["ΩV", "omega_v", "viability margin", "viability_margin"],
    "Π":   ["Π", " pi pressure ", "regulatory pressure", "constraint pressure"],
    "H":   [" H ", "accumulated load", "load", "handoff load"],
    "L_P": ["L_P", "projection loss", "projection_loss"],
    "Δc*": ["Δc*", "delta c", "stability signal", "dc star"],
}

VARIABLE_COLORS = {
    "ΩV":  "#22c55e",
    "Π":   "#f59e0b",
    "H":   "#fb7185",
    "L_P": "#60a5fa",
    "Δc*": "#a78bfa",
}

LAYER_RANK = {
    "canonical": 0, "supporting": 1, "evidence": 2,
    "review": 3, "conflict": 4, "quarantine": 5, "archive": 6,
}

# Constitutional lane x-centers (normalised 0-1; frontend multiplies by 1200)
LANE_X = {
    "draft":      0.10,
    "review":     0.28,
    "approved":   0.50,
    "canonical":  0.72,
    "archived":   0.90,
}
LANE_BOUNDARY_X = [0.19, 0.39, 0.61, 0.81]

CONSTRAINT_ZONE_COLORS = {
    "critical":  "#ef4444",
    "high-risk": "#f97316",
    "watch":     "#f59e0b",
    "stable":    "#22c55e",
}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def safe_float(v, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except Exception:
        return default


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, safe_float(v, default=lo)))


def _norm(v: float, denom: float = 5.0) -> float:
    return _clamp(float(v or 0) / denom)


def _metadata_completeness(n: dict) -> float:
    fields = [
        "title", "project", "document_class", "canonical_layer",
        "authority_state", "review_state", "status", "summary",
    ]
    present = sum(1 for f in fields if n.get(f) not in (None, "", "unassigned", "unknown"))
    return present / len(fields)


# ---------------------------------------------------------------------------
# Variable extraction
# ---------------------------------------------------------------------------

def _canon_variables(n: dict) -> dict[str, dict]:
    hay = " ".join(str(n.get(k) or "") for k in (
        "title", "summary", "topics", "type", "document_class", "canonical_layer"
    ))
    hay_l = f" {hay.lower()} "
    out: dict[str, dict] = {}
    for key, pats in CANON_PATTERNS.items():
        hits = sum(1 for p in pats if p in hay or p.lower() in hay_l)
        present = hits > 0
        out[key] = {
            "present":    present,
            "hits":       hits,
            "confidence": round(min(0.95, 0.45 + hits * 0.18) if present else 0.0, 2),
            "source":     "lexical_fallback" if present else "none",
        }
    return out


def _variable_node_fields(variables: dict[str, dict]) -> dict:
    hit_counts = {k: v["hits"] for k, v in variables.items()}
    total_hits = sum(hit_counts.values())
    present = [(k, v["confidence"]) for k, v in variables.items() if v["present"]]
    dominant = sorted(present, key=lambda kv: kv[1], reverse=True)[0][0] if present else None
    conf = variables[dominant]["confidence"] if dominant else 0.0
    return {
        "dominant_variable":   dominant,
        "variable_hits":       hit_counts,
        "variable_confidence": round(conf, 2),
        "size_metric":         total_hits,
    }


# ---------------------------------------------------------------------------
# Risk metrics
# ---------------------------------------------------------------------------

def _metrics(n: dict, edge_count: int, cross_unapproved: int) -> dict[str, float]:
    authority_score = safe_float(n.get("authority") or 0.0)
    conflicts       = safe_float(n.get("conflictCount") or 0)
    review_state    = (n.get("review_state") or "").lower()
    layer           = (n.get("canonical_layer") or "").lower()
    status          = (n.get("status") or "").lower()
    expired         = safe_float(n.get("expiredCoordinates") or 0)
    uncertain       = safe_float(n.get("uncertainCoordinates") or 0)
    completeness    = _metadata_completeness(n)

    viability = _clamp(
        authority_score
        - _norm(conflicts, 4) * 0.35
        - _norm(expired + uncertain, 6) * 0.20
        - (1.0 - completeness) * 0.25
    )
    is_unreviewed    = review_state in {"unreviewed", "review_required", "pending", "none", "unassigned"}
    review_debt      = 1.0 if is_unreviewed else 0.0
    load_score       = _clamp((edge_count + conflicts + review_debt) / 10.0)
    projection_loss  = _clamp(1.0 - completeness)
    conflict_pressure = _clamp(
        (conflicts + (1 if layer in {"conflict"} or status == "conflict" else 0)) / 5.0
    )
    drift_risk = _clamp(
        (1.0 - authority_score) * 0.25
        + projection_loss * 0.25
        + conflict_pressure * 0.25
        + _norm(expired + uncertain, 5) * 0.15
        + _norm(cross_unapproved, 3) * 0.10
    )
    return {
        "viability_margin":   round(viability, 3),
        "load_score":         round(load_score, 3),
        "projection_loss":    round(projection_loss, 3),
        "conflict_pressure":  round(conflict_pressure, 3),
        "review_debt":        round(review_debt, 3),
        "drift_risk":         round(drift_risk, 3),
    }


def _constraint_zone(m: dict) -> str:
    dr = m["drift_risk"]
    cp = m["conflict_pressure"]
    if dr >= 0.75 or cp >= 0.80:   return "critical"
    if dr >= 0.50 or cp >= 0.50:   return "high-risk"
    if dr >= 0.25 or m["review_debt"] > 0: return "watch"
    return "stable"


# ---------------------------------------------------------------------------
# Constitutional helpers
# ---------------------------------------------------------------------------

def _get_lane(n: dict) -> str:
    layer  = (n.get("canonical_layer") or "").lower()
    status = (n.get("status") or "").lower()
    auth   = (n.get("authority_state") or "").lower()
    review = (n.get("review_state") or "").lower()
    if layer == "canonical" or status == "canonical" or auth == "canonical":
        return "canonical"
    if layer in {"archive", "quarantine"} or status in {"archived", "legacy", "superseded", "scratch"}:
        return "archived"
    if auth == "approved" or review == "approved":
        return "approved"
    if review in {"pending", "review_required", "unreviewed"} or layer == "review":
        return "review"
    return "draft"


def _get_mutation_state(lane: str) -> str:
    return {"canonical": "locked", "archived": "immutable", "review": "pending"}.get(lane, "mutable")


def _get_approval_state(n: dict) -> str:
    auth   = (n.get("authority_state") or "").lower()
    review = (n.get("review_state") or "").lower()
    if auth == "approved" or review == "approved":    return "approved"
    if review in {"pending", "review_required"}:      return "pending"
    return "unreviewed"


def _constitutional_node_fields(n: dict, has_lineage_out: bool) -> dict:
    lane = _get_lane(n)
    return {
        "lane":              lane,
        "authority_state":   n.get("authority_state") or "non_authoritative",
        "mutation_state":    _get_mutation_state(lane),
        "approval_state":    _get_approval_state(n),
        "rollback_available": has_lineage_out and lane not in {"draft", "archived"},
    }


# ---------------------------------------------------------------------------
# Color role (web / variable modes)
# ---------------------------------------------------------------------------

def _role(n: dict, mode: str, variables: dict) -> str:
    if mode == "variable":
        present = [(k, v["confidence"]) for k, v in variables.items() if v.get("present")]
        if present:
            dom = sorted(present, key=lambda kv: kv[1], reverse=True)[0][0]
            return f"variable_{dom}"
    layer  = (n.get("canonical_layer") or "").lower()
    status = (n.get("status") or "").lower()
    if (n.get("conflictCount") or 0) > 0 or layer == "conflict" or status == "conflict":
        return "conflict_pressure"
    if layer == "canonical" or status == "canonical":
        return "canonical_anchor"
    if layer == "evidence":
        return "evidence_node"
    if layer == "review" or status == "review_artifact":
        return "review_gate"
    if layer in {"archive", "quarantine"} or status in {"archived", "legacy", "scratch", "superseded"}:
        return "quarantine_archive"
    return "supporting_context"


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def _project_angles(projects: list) -> dict:
    if not projects:
        return {}
    return {p: ((i / len(projects)) * math.tau - math.pi / 2) for i, p in enumerate(projects)}


def _stable_hash(s: str, modulus: int) -> int:
    """Deterministic integer hash, stable across Python process restarts.
    Uses MD5 for speed; this is purely for jitter seeding, not security."""
    return int(hashlib.md5(s.encode("utf-8", errors="replace")).hexdigest(), 16) % modulus


def _layout_web(nodes: list) -> None:
    projects  = sorted({n.get("project") or "Unassigned" for n in nodes})
    classes   = sorted({n.get("document_class") or "unknown" for n in nodes})
    p_angles  = _project_angles(projects)
    class_idx = {c: i for i, c in enumerate(classes)}
    for i, n in enumerate(nodes):
        p     = n.get("project") or "Unassigned"
        layer = (n.get("canonical_layer") or "quarantine").lower()
        rank  = LAYER_RANK.get(layer, 5)
        m     = n["constraint_metrics"]
        a     = p_angles.get(p, 0.0)
        ci    = class_idx.get(n.get("document_class") or "unknown", 0)
        off   = ((ci % 7) - 3) * 0.075
        gold  = (i * 2.399963229728653) % math.tau
        radius = 0.18 + rank * 0.095 + m["drift_risk"] * 0.10
        angle  = a + off + math.sin(gold) * 0.18
        n["x"] = round(math.cos(angle) * radius, 4)
        n["y"] = round(math.sin(angle) * radius, 4)
        n["z"] = round(m["load_score"], 4)


def _layout_variable(nodes: list) -> None:
    """Phase 18: Variable Overlay — position by epistemic d/q/c values.

    x = epistemic_c (confidence, left=low, right=high)
    y = epistemic_q (quality, bottom=low, top=high, so y=1-q for screen)
    Nodes without epistemic data are scattered in a holding cluster at bottom-left.
    """
    has_data = [n for n in nodes if n.get("epistemic_q") is not None]
    no_data  = [n for n in nodes if n.get("epistemic_q") is None]

    for i, n in enumerate(has_data):
        c  = float(n.get("epistemic_c") or 0.0)
        q  = float(n.get("epistemic_q") or 0.0)
        h  = _stable_hash(str(n.get("id", i)), 997)
        jx = math.sin(h) * 0.025
        jy = math.cos(h) * 0.025
        n["x"] = round(_clamp(c + jx, 0.04, 0.96), 4)
        n["y"] = round(_clamp((1.0 - q) + jy, 0.04, 0.96), 4)   # inverted: high q → top
        n["z"] = round(float(n.get("epistemic_q") or 0.0), 4)

    # No-data cluster: bottom-left quadrant with golden-angle spread
    for i, n in enumerate(no_data):
        gold = (i * 2.399963) % math.tau
        r    = 0.07 + (i % 5) * 0.012
        n["x"] = round(_clamp(0.08 + math.cos(gold) * r, 0.01, 0.22), 4)
        n["y"] = round(_clamp(0.85 + math.sin(gold) * r, 0.75, 0.97), 4)
        n["z"] = 0.0


def _layout_constraint(nodes: list) -> None:
    """Phase 18: Viability Surface — x=confidence, y=quality.

    x = epistemic_c (confidence, 0=left/low, 1=right/high)
    y = epistemic_q (quality, screen: 0=top/high, 1=bottom/low)
    Size encodes meaning_cost.total (see node builder).
    Color encodes correction_status.

    Nodes without epistemic data are placed in a sentinel cluster at top-right.
    """
    import json as _json
    has_data = [n for n in nodes if n.get("epistemic_q") is not None]
    no_data  = [n for n in nodes if n.get("epistemic_q") is None]

    for i, n in enumerate(has_data):
        c  = float(n.get("epistemic_c") or 0.0)
        q  = float(n.get("epistemic_q") or 0.0)
        h  = _stable_hash(str(n.get("id", i)), 997)
        jx = math.sin(h) * 0.022
        jy = math.cos(h) * 0.022
        n["x"] = round(_clamp(c + jx, 0.04, 0.96), 4)     # x = confidence
        n["y"] = round(_clamp((1.0 - q) + jy, 0.04, 0.96), 4)  # y inverted: high q → top
        # z = meaning_cost.total for depth / sizing
        try:
            cost = _json.loads(n.get("meaning_cost_json") or "{}")
            n["z"] = round(float(cost.get("total", 0.0)), 4)
        except Exception:
            n["z"] = round(n["constraint_metrics"]["drift_risk"], 4)

    # No-data nodes: sentinel zone bottom-left (low confidence, unknown quality)
    for i, n in enumerate(no_data):
        gold = (i * 2.399963) % math.tau
        r    = 0.06 + (i % 5) * 0.01
        n["x"] = round(_clamp(0.07 + math.cos(gold) * r, 0.01, 0.20), 4)
        n["y"] = round(_clamp(0.88 + math.sin(gold) * r, 0.78, 0.97), 4)
        n["z"] = 0.0


def _layout_constitutional(nodes: list) -> None:
    """Phase 18: Governance-State Topology — 8 custodian lanes.

    Uses custodian.get_custodian_lane() to assign each node its lane.
    ALL nodes are included regardless of edge presence.
    x = CUSTODIAN_LANE_X[lane], y = evenly spread within lane.
    """
    from app.core.custodian import CUSTODIAN_LANE_X, get_custodian_lane
    lane_groups: dict = defaultdict(list)
    for n in nodes:
        lane = get_custodian_lane(n)
        n["_cust_lane"] = lane
        lane_groups[lane].append(n)
    for lane, lnodes in lane_groups.items():
        lx   = CUSTODIAN_LANE_X.get(lane, 0.5)
        n_in = len(lnodes)
        for j, n in enumerate(lnodes):
            y  = 0.08 + (j / max(n_in - 1, 1)) * 0.84 if n_in > 1 else 0.5
            h  = _stable_hash(str(n.get("id", j)), 997)
            jx = math.sin(h) * 0.016
            jy = math.cos(h) * 0.016
            n["x"] = round(_clamp(lx + jx, 0.01, 0.99), 4)
            n["y"] = round(_clamp(y + jy, 0.02, 0.98), 4)
            n["z"] = round(float(n.get("epistemic_q") or n["constraint_metrics"]["drift_risk"]), 4)


def _layout(nodes: list, mode: str) -> None:
    {"web": _layout_web, "variable": _layout_variable,
     "constraint": _layout_constraint, "constitutional": _layout_constitutional
     }.get(mode, _layout_web)(nodes)


# ---------------------------------------------------------------------------
# Edge styling
# ---------------------------------------------------------------------------

def _edge_style(e: dict) -> dict:
    typ  = e.get("type") or "related"
    auth = e.get("authority") or ("approved" if e.get("approved") else "suggested")
    risk = 0.0
    role = "suggested_semantic"
    if typ in {"lineage", "supersedes", "derives", "derived_from"} or auth == "approved":
        role = "approved_lineage"
    if typ in {"conflicts", "duplicate_content"}:
        role = "conflict_tension"; risk = 0.75
    if auth in {"rejected", "rollback", "superseded", "pending"}:
        role = auth
    return {
        **e,
        "authority":  auth,
        "risk":       safe_float(risk),
        "style_role": role,
        "reversible": typ in {"lineage", "supersedes", "derives"},
        "weight":     safe_float(e.get("weight") or e.get("strength") or 0.5, 0.5),
    }


# ---------------------------------------------------------------------------
# Sidebar builders
# ---------------------------------------------------------------------------

def _sidebar_web(nodes: list, edges: list) -> dict:
    return {
        "node_count":      len(nodes),
        "edge_count":      len(edges),
        "canonical_count": sum(1 for n in nodes if n.get("canonical_layer") == "canonical" or n.get("status") == "canonical"),
        "conflict_count":  sum(1 for n in nodes if (n.get("conflictCount") or 0) > 0),
        "project_count":   len({n.get("project") or "Unassigned" for n in nodes}),
    }


def _sidebar_variable(nodes: list) -> dict:
    """Phase 18: Variable Overlay sidebar — real Daenary d/m/q/c values."""
    from app.core.custodian import D_STATE_COLORS
    d_counts = {1: 0, 0: 0, -1: 0, None: 0}
    m_counts = {"contain": 0, "cancel": 0, None: 0}
    q_vals, c_vals = [], []
    correction_counts: dict = {}
    no_data = 0
    top_nodes: list = []

    for n in nodes:
        d  = n.get("epistemic_d")
        m  = n.get("epistemic_m")
        q  = n.get("epistemic_q")
        c  = n.get("epistemic_c")
        cs = n.get("epistemic_correction_status")

        if q is None and c is None and d is None:
            no_data += 1
            continue

        d_counts[d if d in d_counts else None] += 1
        m_counts[m if m in m_counts else None] += 1
        if q is not None: q_vals.append(float(q))
        if c is not None: c_vals.append(float(c))
        correction_counts[cs or "unknown"] = correction_counts.get(cs or "unknown", 0) + 1

        top_nodes.append({
            "id":                n.get("id"),
            "title":             n.get("title") or n.get("id"),
            "epistemic_d":       d,
            "epistemic_m":       m,
            "epistemic_q":       round(float(q), 2) if q is not None else None,
            "epistemic_c":       round(float(c), 2) if c is not None else None,
            "correction_status": cs,
        })

    has_data = (len(q_vals) > 0 or len(c_vals) > 0)

    # Sort: most uncertain first (d=0 and m=cancel top)
    def sort_key(n):
        d, m = n["epistemic_d"], n["epistemic_m"]
        if m == "cancel":  return (0, d or 0)
        if m == "contain": return (1, d or 0)
        if d == -1:        return (2, 0)
        if d == 0:         return (3, 0)
        return (4, 0)

    top_nodes.sort(key=sort_key)

    return {
        "has_epistemic_data":  has_data,
        "d_counts":            d_counts,
        "m_counts":            m_counts,
        "correction_counts":   correction_counts,
        "mean_q":              round(sum(q_vals) / len(q_vals), 3) if q_vals else None,
        "mean_c":              round(sum(c_vals) / len(c_vals), 3) if c_vals else None,
        "no_data_count":       no_data,
        "top_nodes":           top_nodes[:10],
        "gap": (None if has_data
                else "No Daenary epistemic metadata found. Load the Daenary demo seed "
                     "or add epistemic_state frontmatter to documents."),
    }


def _risk_reason(m: dict, zone: str) -> str:
    parts = []
    if m["conflict_pressure"] >= 0.5: parts.append("conflict pressure")
    if m["review_debt"] > 0:          parts.append("unreviewed")
    if m["projection_loss"] >= 0.5:   parts.append("incomplete metadata")
    if m["drift_risk"] >= 0.5:        parts.append("high drift risk")
    return ", ".join(parts) if parts else zone


def _sidebar_constraint(nodes: list) -> dict:
    """Phase 18: Viability Surface sidebar — q/c quadrant analysis."""
    import json as _json
    from app.core.custodian import CORRECTION_STATUS_COLORS

    quadrants = {
        "viable":        0,   # high q AND high c → canonical viability zone
        "contain_zone":  0,   # high q, low c → contain (ambiguous but evidence-strong)
        "weak_zone":     0,   # low q, high c → overconfident but weak evidence
        "low_zone":      0,   # low q AND low c → raw/noisy
        "no_data":       0,
    }
    correction_counts: dict = {}
    expired_count = 0
    high_cost: list = []

    for n in nodes:
        q  = n.get("epistemic_q")
        c  = n.get("epistemic_c")
        cs = n.get("epistemic_correction_status")
        vuntil = n.get("epistemic_valid_until")

        if q is None and c is None:
            quadrants["no_data"] += 1
            continue

        qf = float(q) if q is not None else 0.0
        cf = float(c) if c is not None else 0.0

        if qf >= 0.65 and cf >= 0.60:    quadrants["viable"] += 1
        elif qf >= 0.65:                  quadrants["contain_zone"] += 1
        elif cf >= 0.60:                  quadrants["weak_zone"] += 1
        else:                             quadrants["low_zone"] += 1

        correction_counts[cs or "unknown"] = correction_counts.get(cs or "unknown", 0) + 1

        # Check expired
        if vuntil:
            try:
                from datetime import datetime, timezone
                exp = datetime.fromisoformat(vuntil.replace("Z", "+00:00"))
                if exp < datetime.now(tz=timezone.utc):
                    expired_count += 1
            except Exception:
                pass

        # High-cost node?
        try:
            cost = _json.loads(n.get("meaning_cost_json") or "{}")
            total = float(cost.get("total", 0.0))
        except Exception:
            total = 0.0

        if total >= 0.55 or cs in {"conflicting", "likely_incorrect"}:
            high_cost.append({
                "id":                n.get("id"),
                "title":             n.get("title") or n.get("id"),
                "epistemic_q":       round(float(q), 2) if q is not None else None,
                "epistemic_c":       round(float(c), 2) if c is not None else None,
                "correction_status": cs,
                "cost_total":        round(total, 3),
                "custodian_state":   n.get("custodian_review_state"),
            })

    high_cost.sort(key=lambda x: x["cost_total"], reverse=True)

    return {
        "quadrants":           quadrants,
        "correction_counts":   correction_counts,
        "expired_count":       expired_count,
        "high_cost_nodes":     high_cost[:8],
        "viability_axes":      {"x": "confidence (c)", "y": "quality (q)"},
    }


def _sidebar_constitutional(nodes: list, edges: list) -> dict:
    """Phase 18: Governance-State Topology sidebar — custodian lane counts."""
    from app.core.custodian import CUSTODIAN_LANES, get_custodian_lane, CORRECTION_STATUS_COLORS

    lane_counts: dict = {k: 0 for k in CUSTODIAN_LANES}
    canonical_nodes: list = []
    contained_nodes: list = []
    canceled_nodes:  list = []
    expired_nodes:   list = []

    for n in nodes:
        lane = n.get("_cust_lane") or get_custodian_lane(n)
        lane_counts[lane] = lane_counts.get(lane, 0) + 1

        entry = {
            "id":                n.get("id"),
            "title":             n.get("title") or n.get("id"),
            "epistemic_q":       round(float(n["epistemic_q"]), 2) if n.get("epistemic_q") is not None else None,
            "epistemic_c":       round(float(n["epistemic_c"]), 2) if n.get("epistemic_c") is not None else None,
            "correction_status": n.get("epistemic_correction_status"),
        }
        if lane == "canonical":   canonical_nodes.append(entry)
        if lane == "contained":   contained_nodes.append(entry)
        if lane == "canceled":    canceled_nodes.append(entry)
        if lane == "expired":     expired_nodes.append(entry)

    return {
        "lane_counts":      lane_counts,
        "canonical_nodes":  canonical_nodes[:6],
        "contained_nodes":  contained_nodes[:6],
        "canceled_nodes":   canceled_nodes[:6],
        "expired_nodes":    expired_nodes[:6],
        "total_nodes":      len(nodes),
        "has_epistemic":    any(n.get("epistemic_d") is not None or n.get("epistemic_q") is not None for n in nodes),
    }


# ---------------------------------------------------------------------------
# Legends (Phase 18)
# ---------------------------------------------------------------------------

def _legend_web() -> dict:
    return {
        "node_color": [
            {"label": "Canonical anchor",   "color": "#34d399"},
            {"label": "Supporting context", "color": "#7a8ea5"},
            {"label": "Evidence node",      "color": "#8b5cf6"},
            {"label": "Review gate",        "color": "#f59e0b"},
            {"label": "Conflict pressure",  "color": "#ef4444"},
            {"label": "Archive/quarantine", "color": "#475569"},
        ],
        "node_size": "authority score + load",
        "edge_types": ["lineage", "derives", "supersedes", "conflict", "topic_overlap"],
    }


def _legend_variable() -> dict:
    from app.core.custodian import D_STATE_COLORS
    return {
        "node_color": [
            {"label": "d=+1 (affirmed)",   "color": D_STATE_COLORS[1]},
            {"label": "d=0 (unresolved)",  "color": D_STATE_COLORS[0]},
            {"label": "d=-1 (negated)",    "color": D_STATE_COLORS[-1]},
            {"label": "No epistemic state","color": D_STATE_COLORS[None]},
        ],
        "node_size":      "epistemic_q (evidence quality)",
        "halo_ring":      "m=contain → amber ring; m=cancel → red ring",
        "x_axis":         "epistemic_c (confidence)",
        "y_axis":         "epistemic_q (quality, high=top)",
        "fallback_note":  "Nodes without Daenary metadata appear in lower-left sentinel cluster",
        "data_source":    "epistemic_state frontmatter / Daenary pipeline",
    }


def _legend_constraint() -> dict:
    from app.core.custodian import CORRECTION_STATUS_COLORS
    return {
        "node_color": [{"label": k or "unknown", "color": c}
                       for k, c in CORRECTION_STATUS_COLORS.items() if k is not None],
        "node_size":  "meaning_cost.total (larger = more costly if wrong)",
        "halo":       "escalated / high-cost nodes",
        "axes": {
            "x": "epistemic_c — confidence (right=high)",
            "y": "epistemic_q — quality   (top=high)",
        },
        "zones": {
            "upper_right":  "Viable (high q + high c) → canonical candidates",
            "upper_left":   "Contain zone (high q, low c) → ambiguous but evidence-strong",
            "lower_right":  "Weak zone (low q, high c) → overconfident, weak evidence",
            "lower_left":   "Low zone (low q + low c) → raw / noisy",
        },
        "no_data_cluster": "Nodes without epistemic data: lower-left sentinel cluster",
    }


def _legend_constitutional() -> dict:
    from app.core.custodian import CUSTODIAN_LANES, CUSTODIAN_LANE_COLORS, CUSTODIAN_LANE_X, CUSTODIAN_LANE_BOUNDARIES
    return {
        "node_color":       [{"label": k, "color": CUSTODIAN_LANE_COLORS[k]} for k in CUSTODIAN_LANES],
        "lanes":            CUSTODIAN_LANES,
        "lane_x_centers":   CUSTODIAN_LANE_X,
        "lane_boundary_x":  CUSTODIAN_LANE_BOUNDARIES,
        "includes_all":     True,
        "filter_note":      "All nodes shown — no edge-based filtering. Lane assigned by epistemic state.",
    }


# ---------------------------------------------------------------------------
# Layout descriptor (Phase 18)
# ---------------------------------------------------------------------------

def _layout_descriptor(mode: str) -> dict:
    if mode == "web":
        return {"type": "organic_cluster", "x_semantic": "project cluster angle",
                "y_semantic": "canonical layer + drift", "scale": {"x": 1200, "y": 900}}
    if mode == "variable":
        return {"type": "epistemic_scatter",
                "x_semantic": "epistemic_c (confidence, right=high)",
                "y_semantic": "epistemic_q (quality, top=high)",
                "scale":      {"x": 1200, "y": 900},
                "data_source": "Daenary epistemic_state",
                "fallback":   "Nodes without Daenary metadata → sentinel cluster (lower-left)"}
    if mode == "constraint":
        return {"type": "viability_surface",
                "x_semantic": "epistemic_c (confidence)",
                "y_semantic": "epistemic_q (quality, top=high)",
                "z_semantic": "meaning_cost.total (depth/size)",
                "scale":      {"x": 1200, "y": 900},
                "zones":      ["viable", "contain_zone", "weak_zone", "low_zone"]}
    if mode == "constitutional":
        from app.core.custodian import CUSTODIAN_LANE_X, CUSTODIAN_LANE_BOUNDARIES, CUSTODIAN_LANES
        return {"type": "custodian_topology",
                "x_semantic": "custodian governance lane",
                "y_semantic": "position within lane",
                "scale":      {"x": 1200, "y": 900},
                "lanes":      CUSTODIAN_LANES,
                "lane_x_centers":  CUSTODIAN_LANE_X,
                "lane_boundary_x": CUSTODIAN_LANE_BOUNDARIES,
                "includes_all_nodes": True}
    return {}


# ---------------------------------------------------------------------------
# Diagnostics (Phase 18)
# ---------------------------------------------------------------------------

def _diagnostics(mode: str, nodes: list, edges: list) -> list:
    out: list = []
    if not nodes:
        out.append({"severity": "error", "code": "ZERO_NODES",
                    "message": "Projection returned zero nodes."})
        return out
    if mode == "variable":
        if not any(n.get("dominant_variable") for n in nodes):
            out.append({"severity": "warning", "code": "NO_VARIABLE_DATA",
                        "message": "No variable extraction data available. "
                                   "The ingestion pipeline has not mapped CANON variables."})
        if not any(n.get("epistemic_q") is not None for n in nodes):
            out.append({"severity": "info", "code": "NO_EPISTEMIC_DATA",
                        "message": "No Daenary epistemic_state found. Load the Daenary demo "
                                   "seed to see real d/m/q/c values. Showing sentinel cluster."})
    elif mode == "constraint":
        if not any(n.get("epistemic_q") is not None for n in nodes):
            out.append({"severity": "info", "code": "NO_VIABILITY_DATA",
                        "message": "No epistemic q/c data. Viability surface is empty. "
                                   "Load the Daenary demo seed to see meaningful layout."})
    elif mode == "constitutional":
        if not any(n.get("epistemic_d") is not None or n.get("epistemic_q") is not None for n in nodes):
            out.append({"severity": "info", "code": "NO_CUSTODIAN_DATA",
                        "message": "No Daenary epistemic metadata. All nodes in raw_imported lane. "
                                   "Load the Daenary demo seed to see governance topology."})
    return out


def get_projection_graph(mode: str = "web", max_nodes: int = 300) -> dict[str, Any]:
    import json as _json
    from app.core.custodian import (
        compute_meaning_cost, get_custodian_lane,
        CUSTODIAN_LANE_COLORS, D_STATE_COLORS, CORRECTION_STATUS_COLORS,
    )
    from app.core.projection_manifest import get_manifest_or_error

    mode = (mode or "web").lower()
    if mode in {"geometry", "constraint-geometry"}: mode = "constraint"
    if mode == "structural":                        mode = "web"
    if mode not in MODES:                           mode = "web"

    # ── Phase 19.5: Projection manifest gate ─────────────────────────────────
    # Architectural rule: no projection may render without a valid manifest.
    # Architectural rule: no projection may authorize canonical mutation.
    manifest, manifest_error = get_manifest_or_error(mode)
    if manifest_error:
        return manifest_error

    base      = get_graph_data(max_nodes=max_nodes)
    raw_nodes = [dict(n) for n in base.get("nodes", [])]
    raw_edges = [_edge_style(dict(e)) for e in base.get("edges", [])]

    # Constitutional (Phase 18): ALL nodes included — no edge-based filtering.
    # Custodian lane is assigned per-node from epistemic state.

    # Edge-count accumulators
    edge_counts:      dict = {n["id"]: 0 for n in raw_nodes}
    cross_unapproved: dict = {n["id"]: 0 for n in raw_nodes}
    lineage_out:      set  = set()
    for e in raw_edges:
        for side in ("source", "target"):
            nid = e.get(side)
            if nid in edge_counts:
                edge_counts[nid] += 1
                if e.get("cross_project") and e.get("authority") != "approved":
                    cross_unapproved[nid] += 1
        if e.get("type") in AUTHORITY_EDGE_TYPES:
            lineage_out.add(e.get("source", ""))

    # ── Build enriched nodes ──────────────────────────────────────────────
    nodes: list = []
    for n in raw_nodes:
        variables  = _canon_variables(n)
        metrics    = _metrics(n, edge_counts.get(n["id"], 0), cross_unapproved.get(n["id"], 0))
        var_fields = _variable_node_fields(variables)
        cf         = _constitutional_node_fields(n, n.get("id", "") in lineage_out)
        zone       = _constraint_zone(metrics)
        role       = _role(n, mode, variables)

        # Phase 18: compute meaning_cost
        stored_cost_json = n.get("meaning_cost_json")
        if stored_cost_json:
            try:
                meaning_cost = _json.loads(stored_cost_json)
            except Exception:
                meaning_cost = compute_meaning_cost(n)
        else:
            meaning_cost = compute_meaning_cost(n)

        # Phase 18: mode-specific radius
        if mode == "variable":
            radius = 4 + float(n.get("epistemic_q") or 0.0) * 12
        elif mode == "constraint":
            radius = 4 + float(meaning_cost.get("total", 0.0)) * 16
        else:
            radius = 5 + metrics["load_score"] * 7 + safe_float(n.get("authority") or 0) * 4

        # Phase 18: custodian lane
        cust_lane = get_custodian_lane(n)

        nodes.append({
            **n,
            "display_label":   (f"{n.get('title') or n.get('label') or n['id']} "
                                f"· {n.get('project','Unassigned')}"
                                + (f" · {n.get('canonical_layer')}" if n.get("canonical_layer") else "")),
            "radius":          round(radius, 2),
            "color_role":      role,
            "mapping_source":  "lexical_fallback" if var_fields["dominant_variable"] else "none",

            # Shared metrics
            "risk_score":       safe_float(metrics["drift_risk"]),
            "load_score":       safe_float(metrics["load_score"]),
            "projection_loss":  safe_float(metrics["projection_loss"]),
            "viability_margin": safe_float(metrics["viability_margin"]),
            "constraint_metrics": {k: safe_float(v) for k, v in metrics.items()},

            # Variable Overlay
            "dominant_variable":   var_fields["dominant_variable"],
            "variable_hits":       var_fields["variable_hits"],
            "variable_confidence": var_fields["variable_confidence"],
            "size_metric":         var_fields["size_metric"],

            # Constraint Geometry
            "constraint_zone":    zone,
            "conflict_pressure":  safe_float(metrics["conflict_pressure"]),
            "review_debt":        safe_float(metrics["review_debt"]),
            "drift_risk":         safe_float(metrics["drift_risk"]),

            # Constitutional (legacy fields kept)
            "lane":               cf["lane"],
            "mutation_state":     cf["mutation_state"],
            "approval_state":     cf["approval_state"],
            "rollback_available": cf["rollback_available"],

            # Phase 18: Daenary epistemic
            "epistemic_d":                 n.get("epistemic_d"),
            "epistemic_m":                 n.get("epistemic_m"),
            "epistemic_q":                 round(float(n["epistemic_q"]), 3) if n.get("epistemic_q") is not None else None,
            "epistemic_c":                 round(float(n["epistemic_c"]), 3) if n.get("epistemic_c") is not None else None,
            "epistemic_correction_status": n.get("epistemic_correction_status"),
            "epistemic_valid_until":       n.get("epistemic_valid_until"),
            "custodian_review_state":      n.get("custodian_review_state"),
            "meaning_cost":                meaning_cost,
            "custodian_lane":              cust_lane,
            "ep_color":                    D_STATE_COLORS.get(n.get("epistemic_d"), D_STATE_COLORS[None]),
            "cs_color":                    CORRECTION_STATUS_COLORS.get(n.get("epistemic_correction_status"), "#475569"),
            "cust_color":                  CUSTODIAN_LANE_COLORS.get(cust_lane, "#475569"),

            # Full variable scan (for sidebar)
            "canon_variables": variables,

            # Internal layout helpers (stripped before return)
            "_lane":      cf["lane"],
            "_var_fields": var_fields,
            "_cust_lane":  cust_lane,
        })

    _layout(nodes, mode)

    # ── Sidebar / legend / diagnostics ────────────────────────────────────
    sidebars = {
        "web":           lambda: _sidebar_web(nodes, raw_edges),
        "variable":      lambda: _sidebar_variable(nodes),
        "constraint":    lambda: _sidebar_constraint(nodes),
        "constitutional": lambda: _sidebar_constitutional(nodes, raw_edges),
    }
    legends = {
        "web": _legend_web, "variable": _legend_variable,
        "constraint": _legend_constraint, "constitutional": _legend_constitutional,
    }

    sidebar     = sidebars.get(mode, lambda: {})()
    legend      = legends.get(mode, lambda: {})()
    diagnostics = _diagnostics(mode, nodes, raw_edges)

    # Strip internal fields
    for n in nodes:
        n.pop("_lane", None)
        n.pop("_var_fields", None)
        n.pop("_cust_lane", None)

    losses = [n["projection_loss"] for n in nodes]

    return {
        **{k: v for k, v in base.items() if k not in {"nodes", "edges"}},
        "mode":                mode,
        "projection_id":       PROJECTION_IDS.get(mode, "unknown"),
        "nodes":               nodes,
        "edges":               raw_edges,
        "layout":              _layout_descriptor(mode),
        "legend":              legend,
        "sidebar":             sidebar,
        "diagnostics":         diagnostics,
        "projection_manifest": manifest.to_dict(),   # Phase 19.5: required
        "projection": {
            "method": f"phase18_daenary_{mode}_v1",
            "label":  f"Phase 18 · {mode.replace('_',' ').title()} — Daenary Substrate",
            "dimensions": {
                "web":           ["project_cluster", "layer_rank", "drift_offset"],
                "variable":      ["epistemic_c_x", "epistemic_q_y", "d_state_color"],
                "constraint":    ["epistemic_c_x", "epistemic_q_y", "meaning_cost_z"],
                "constitutional": ["custodian_lane_x", "lane_position_y", "epistemic_q_z"],
            }.get(mode, ["semantic", "authority"]),
            "loss_summary": {
                "mean_projection_loss": round(mean(losses), 3) if losses else 0.0,
                "max_projection_loss":  round(max(losses), 3)  if losses else 0.0,
                "high_loss_nodes":      sum(1 for x in losses if x >= 0.5),
            },
        },
    }
