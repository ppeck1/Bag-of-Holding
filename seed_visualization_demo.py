"""Seed the BOH visualization demo database with fabricated docs and edges.

Run from the project root:
    python seed_visualization_demo.py
"""
import os, json, time, hashlib
from pathlib import Path

os.environ.setdefault("BOH_DB", str(Path("boh.db").resolve()))

from app.db.connection import init_db, get_conn
from app.services.indexer import index_file

ROOT = Path(__file__).resolve().parent
LIB = ROOT / "library"

DOC_UPDATES = {
    "demo.core.viability-canonical": (1,None,.94,.91,"accurate","2026-06-01T00:00:00Z",.18,"canonical","canonical","canonical","canonical","approved"),
    "demo.core.projection-loss": (1,None,.82,.74,"accurate","2026-05-15T00:00:00Z",.26,"approved","approved_patch","supporting","approved","approved"),
    "demo.core.load-pressure": (0,"contain",.76,.48,"incomplete","2026-05-05T00:00:00Z",.62,"under_review","review_required","review","review_required","pending"),
    "demo.core.conflict-triage-rule": (0,"cancel",.69,.31,"conflicting","2026-04-20T00:00:00Z",.88,"contained","conflict","conflict","review_required","pending"),
    "demo.evidence.shift-log-alpha": (1,None,.71,.64,"mostly_accurate","2026-05-10T00:00:00Z",.41,"evidence","draft","evidence","draft","none"),
    "demo.evidence.noisy-sensor": (1,None,.28,.72,"uncertain","2026-05-03T00:00:00Z",.77,"weak_quality","draft","evidence","draft","none"),
    "demo.evidence.raw-import": (None,None,None,None,None,None,None,"raw_imported","draft","supporting","draft","none"),
    "demo.policy.authority-map": (1,None,.91,.86,"accurate","2026-06-15T00:00:00Z",.22,"canonical","canonical","canonical","canonical","approved"),
    "demo.policy.wrong-team-attempt": (-1,None,.87,.58,"likely_incorrect","2026-05-02T00:00:00Z",.81,"rejected","review_required","review","review_required","pending"),
    "demo.policy.role-boundary": (1,None,.84,.81,"accurate","2026-06-01T00:00:00Z",.19,"approved","approved_patch","supporting","approved","approved"),
    "demo.temporal.warning": (0,"contain",.66,.52,"incomplete","2026-05-01T00:00:00Z",.55,"warning","review_required","review","review_required","pending"),
    "demo.temporal.containment": (0,"contain",.58,.27,"conflicting","2026-04-18T00:00:00Z",.91,"contained","conflict","conflict","review_required","pending"),
    "demo.temporal.forced-escalation": (-1,None,.49,.22,"likely_incorrect","2026-04-10T00:00:00Z",.95,"forced_escalation","review_required","review","review_required","pending"),
    "demo.archive.superseded-rule": (1,None,.73,.69,"historical","2026-03-01T00:00:00Z",.33,"expired","superseded","archive","superseded","unassigned"),
    "demo.cross.research-proposal": (0,"contain",.62,.44,"incomplete","2026-05-20T00:00:00Z",.58,"under_review","draft","supporting","draft","none"),
    "demo.cross.external-reference": (0,"cancel",.39,.35,"uncertain","2026-05-25T00:00:00Z",.69,"canceled","draft","supporting","draft","none"),
}

EDGES = [
    ("demo.core.viability-canonical","demo.core.projection-loss","derives",1,.88,1,"approved lineage: viability spec derives projection-loss mapping"),
    ("demo.core.viability-canonical","demo.core.load-pressure","canon_relates_to",1,.76,1,"approved relationship: load pressure affects viability"),
    ("demo.core.load-pressure","demo.core.conflict-triage-rule","conflicts",-1,.32,0,"unresolved conflict: triage rule increases load pressure"),
    ("demo.evidence.shift-log-alpha","demo.core.load-pressure","derives",1,.70,1,"evidence supports load pressure model"),
    ("demo.evidence.noisy-sensor","demo.core.load-pressure","canon_relates_to",0,.44,0,"suggested weak evidence connection"),
    ("demo.policy.authority-map","demo.policy.role-boundary","derives",1,.90,1,"approved authority lineage"),
    ("demo.policy.wrong-team-attempt","demo.policy.authority-map","conflicts",-1,.25,0,"authority mismatch example"),
    ("demo.temporal.warning","demo.temporal.containment","supersedes",0,.72,1,"escalation ladder step"),
    ("demo.temporal.containment","demo.temporal.forced-escalation","supersedes",-1,.84,1,"persistent high drift escalates"),
    ("demo.archive.superseded-rule","demo.policy.role-boundary","supersedes",1,.80,1,"new role boundary supersedes legacy rule"),
    ("demo.cross.research-proposal","demo.core.viability-canonical","canon_relates_to",0,.22,0,"cross-project suggested relation"),
    ("demo.cross.external-reference","demo.cross.research-proposal","conflicts",-1,.35,0,"external reference conflicts with research proposal"),
]

init_db()

# Index all ordinary files first. Canonical docs may be blocked by authority rules,
# so they are upserted below as synthetic seed fixtures.
for path in LIB.glob("*.md"):
    try:
        index_file(path, LIB)
    except Exception as exc:
        print("index warning:", path.name, exc)

conn = get_conn()

# Ensure blocked canonical fixtures exist.
for doc_id in ("demo.core.viability-canonical", "demo.policy.authority-map"):
    path = next(LIB.glob(doc_id.replace("demo.","").replace(".","-") + ".md"))
    text = path.read_text(encoding="utf-8")
    title = doc_id.replace("demo.","").replace("."," ").title()
    conn.execute("""INSERT OR IGNORE INTO docs
      (doc_id,path,type,status,version,updated_ts,operator_state,operator_intent,
       plane_scope_json,field_scope_json,node_scope_json,text_hash,source_type,topics_tokens,
       title,summary,corpus_class,project,document_class,canonical_layer,authority_state,
       review_state,provenance_json,source_hash,document_id,app_state)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (doc_id, path.name, "architecture", "canonical", "0.0.1", int(time.time()),
       "release", "canonize", "[]", "[]", json.dumps([doc_id]),
       hashlib.sha256(text.encode()).hexdigest(), "library", "canonical authority",
       title, "Synthetic canonical anchor.", "CORPUS_CLASS:CANON",
       "Governance Sandbox" if "policy" in doc_id else "Aster Hospital Simulation",
       "architecture", "canonical", "canonical", "approved",
       json.dumps({"fabricated": True}), "fabricated-seed", doc_id, "library"))

for doc_id, vals in DOC_UPDATES.items():
    d,m,q,c,corr,until,cost,cust_state,status,layer,auth,review = vals
    conn.execute("""UPDATE docs SET
      status=?, canonical_layer=?, authority_state=?, review_state=?,
      epistemic_d=?, epistemic_m=?, epistemic_q=?, epistemic_c=?,
      epistemic_correction_status=?, epistemic_valid_until=?,
      epistemic_context_ref=?, epistemic_source_ref=?, epistemic_last_evaluated=?,
      meaning_cost_json=?, custodian_review_state=?
      WHERE doc_id=?""",
      (status,layer,auth,review,d,m,q,c,corr,until,doc_id,"fabricated-demo",
       "2026-04-28T00:00:00Z", json.dumps({"total": cost}) if cost is not None else None,
       cust_state, doc_id))

now = int(time.time())
for s,t,typ,state,perm,approved,detail in EDGES:
    conn.execute("""INSERT OR REPLACE INTO doc_edges
      (source_doc_id,target_doc_id,edge_type,state,permeability,load_score,detected_ts,detail,authority,approved)
      VALUES (?,?,?,?,?,?,?,?,?,?)""",
      (s,t,typ,state,perm,round(1-perm,2),now,detail,"approved" if approved else "suggested",approved))

conn.commit()
print("Seeded BOH visualization demo:", conn.execute("SELECT count(*) FROM docs WHERE doc_id LIKE 'demo.%'").fetchone()[0], "docs")
# conn remains open for Phase 25.3 stress fixtures

# Phase 25.3–25.8 governance stress fixtures: believable failure, not happy-path sterility.
from datetime import datetime, timezone
stress_now = datetime.now(timezone.utc).isoformat()

def _insert_json(table_sql, params):
    conn.execute(table_sql, params)

# Authority mismatch attempts: wrong resolver, wrong team, wrong role, wrong scope.
stress_attempts = [
    ("AL_STRESS_RESOLVER", "demo.policy.authority-map", "document", "actor_wrong_resolver", "resolver", "Governance", "governance", 0, "authority_mismatch: resolver", {"failure_type": ["resolver"], "attempted_by": "actor_wrong_resolver"}),
    ("AL_STRESS_TEAM", "demo.policy.wrong-team-attempt", "document", "actor_security_adjacent", "resolver", "Security", "clinical", 0, "authority_mismatch: team,scope", {"failure_type": ["team", "scope"], "attempted_by": "actor_security_adjacent"}),
    ("AL_STRESS_ROLE", "demo.policy.role-boundary", "document", "actor_reviewer_only", "reviewer", "Governance", "governance", 0, "authority_mismatch: role", {"failure_type": ["role"], "attempted_by": "actor_reviewer_only"}),
]
for row in stress_attempts:
    aid, target, typ, actor, role, team, required, result, reason, meta = row
    conn.execute("""INSERT OR REPLACE INTO authority_resolution_log
      (id,target_id,target_type,actor_id,actor_role,actor_team,required_authority,authorization_result,failure_reason,timestamp,metadata_json)
      VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
      (aid,target,typ,actor,role,team,required,result,reason,stress_now,json.dumps(meta)))

# Canonical locks created by failed legitimacy proof and containment.
locks = [
    ("LOCK_STRESS_AUTHORITY", "demo.policy.wrong-team-attempt", "authority_mismatch", None, 1, {"source": "seed_stress", "failure_type": ["team", "scope"]}),
    ("LOCK_STRESS_CONTAINMENT", "demo.temporal.containment", "high_drift_containment", "ESC_STRESS_CONTAIN", 1, {"source": "seed_stress", "d": 0, "m": "contain"}),
    ("LOCK_STRESS_FORCED", "demo.temporal.forced-escalation", "persistent_high_drift_forced_escalation", "ESC_STRESS_FORCED", 1, {"source": "seed_stress", "authority_transfer": {"to": "supervisor_governance"}}),
]
for lock_id,node,reason,eid,active,meta in locks:
    conn.execute("""INSERT OR REPLACE INTO canonical_locks
      (lock_id,node_id,reason,escalation_id,active,created_at,released_at,metadata_json)
      VALUES (?,?,?,?,?,?,?,?)""",
      (lock_id,node,reason,eid,active,stress_now,None,json.dumps(meta)))

# Binding escalation records.
escs = [
    ("ESC_STRESS_WARN", "demo.temporal.warning", "moderate", "warning", "status=warning; owner=temporal_owner; refresh_due=required", 1, "temporal_owner", "temporal_supervisor", None, None, "moderate drift warning", "temporal", 0, None, 1),
    ("ESC_STRESS_CONTAIN", "demo.temporal.containment", "high", "containment", "status=containment; forced d=0, m=contain; canonical_lock=LOCK_STRESS_CONTAINMENT", 1, "temporal_owner", "temporal_supervisor", None, None, "high drift containment", "temporal", 1, "ANCHOR_STRESS_CONTAIN", 1),
    ("ESC_STRESS_FORCED", "demo.temporal.forced-escalation", "high", "escalation", "status=escalation; authority_transferred_to=supervisor_governance; canonical_lock=LOCK_STRESS_FORCED", 1, "temporal_owner", "supervisor_governance", None, "supervisor_governance", "persistent high drift", "governance", 1, "ANCHOR_STRESS_FORCED", 1),
]
for e in escs:
    conn.execute("""INSERT OR REPLACE INTO escalation_events
      (escalation_id,node_id,drift_risk,escalation_level,action_taken,notification_sent,owner,supervisor,refresh_due,escalated_to,why,supervisory_plane,forced_scope_reduction,anchor_id,route_found,created_at,metadata_json)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (*e, stress_now, json.dumps({"source": "seed_stress"})))

conn.commit()
print("Added governance stress fixtures: authority mismatches, locks, containments, escalations")
conn.close()
