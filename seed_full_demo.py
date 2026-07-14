"""seed_full_demo.py — Full-capability demo library for Bag of Holding.

Generates ~50 self-contained markdown documents across all 8 planes,
all authority tiers, and a wide freshness spread so every Fold projection
shows rich, meaningful data:

  Web           — varied currentness fill (current / stale / expired / conflict / unknown)
  Risk Map      — node sizes span the full range (low risk → critical drift)
  Authority Path— 4 border-weight tiers visible
  Currentness Map— nodes fill all 4 quadrants (X=authority, Y=freshness)
  Evidence State — all 8 planes represented with correct shapes
  Timeline      — documents span 3 years of validity windows

No external files required — all content is embedded.
No server required — run directly: python seed_full_demo.py

Usage:
    python seed_full_demo.py            # seed (idempotent)
    python seed_full_demo.py --force    # clear and re-seed
    python seed_full_demo.py --dry-run  # print plan only
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.resolve()
os.environ.setdefault("BOH_DB",       str(REPO_ROOT / "boh.db"))
os.environ.setdefault("BOH_LIBRARY",  str(REPO_ROOT / "library"))
os.environ.setdefault("BOH_DATA_ROOT",str(REPO_ROOT))

from app.db.connection import init_db, get_conn, fetchall, fetchone, execute
from app.core import input_surface as inp

LIBRARY_ROOT = Path(os.environ["BOH_LIBRARY"]).resolve()
MARKER = LIBRARY_ROOT / ".full_demo_seeded"
DEMO_DIR = LIBRARY_ROOT / "demo"

NOW = int(time.time())

def _ok(m):  print(f"  [OK]  {m}")
def _info(m):print(f"  ...   {m}")
def _skip(m):print(f"  [--]  {m}")
def _err(m): print(f"  [!!]  {m}", file=sys.stderr)
def _hdr(t): print(f"\n--- {t} ---")

# ---------------------------------------------------------------------------
# Document definitions
# Every document has: id, title, project, plane, authority_state,
# freshness_days_ago (None = unknown/ancient), valid_days_ahead (None = no expiry),
# risk (0-1), body
# ---------------------------------------------------------------------------

DOCS = [
    # ── CANONICAL plane — BOH System ──────────────────────────────────────────
    dict(
        id="boh.arch.core-model",
        title="BOH Core Architecture Model",
        project="BOH System",
        plane="canonical",
        authority="canonical",
        freshness_days=5,
        valid_ahead=730,
        risk=0.05,
        body="""# BOH Core Architecture Model

Bag of Holding is a local-first governed knowledge workbench.

## Doctrine

**LLM proposes. Human governs. System audits.**

Every document carries provenance. Authority transfers require explicit approval.
LLM outputs are proposals, not facts. Canonical truth is earned, not inferred.

## Stack

- Python FastAPI backend
- SQLite persistence (boh.db)
- Vanilla ES module frontend at /v2/
- Optional Ollama integration

## Authority boundaries

- BOH_LIBRARY: server-owned document root
- BOH_OPERATOR_TOKEN: mutation gate
- BOH_RETRIEVAL_TOKEN: read-only connector gate
- Actor identity is separate from operator authorization

## Planes

Eight canonical layers organize the corpus:
canonical, evidence, informational, subjective, internal, review, conflict, archive.
""",
    ),
    dict(
        id="boh.arch.authority-model",
        title="BOH Authority Model v2",
        project="BOH System",
        plane="canonical",
        authority="canonical",
        freshness_days=3,
        valid_ahead=365,
        risk=0.04,
        body="""# BOH Authority Model v2

Authority is a first-class dimension in BOH, not a metadata tag.

## Authority states (ranked)

1. canonical   — formally promoted, certificate held
2. trusted     — approved by designated custodian
3. approved    — reviewed and accepted
4. reviewed    — passed deterministic review
5. under_review— in active review queue
6. custodian_review — flagged for custodian attention
7. draft       — indexed, not yet reviewed
8. non_authoritative — advisory content, LLM-origin or external
9. unknown     — authority not assessed

## Operator token

The operator token is the local authorization boundary.
It does not replace authority — it gates privileged mutation routes.
Actor ID records who performed the action; operator token says they were allowed to.

## Certificate model

Certificates are issued for canonical promotion.
A certificate requires: authority proof, conflict resolution, custodian sign-off.
""",
    ),
    dict(
        id="boh.arch.data-model",
        title="BOH Data Model Specification",
        project="BOH System",
        plane="canonical",
        authority="trusted",
        freshness_days=14,
        valid_ahead=365,
        risk=0.08,
        body="""# BOH Data Model Specification

## Core tables

- docs: primary document record (doc_id, title, status, authority_state, canonical_layer, ...)
- doc_chunks: FTS-indexed content chunks
- doc_chunks_fts: full-text search virtual table
- plane_cards: domain card records per plane
- lattice_edges: governed relationships between documents
- actor_ledger: attribution history
- review_queue: pending review items
- approval_requests: formal approval workflow records
- intake_*: governed ingestion pipeline tables

## Key fields on docs

- authority_state: the authority tier label
- canonical_layer: the plane assignment
- epistemic_valid_until: validity window end (ISO-8601)
- freshness_score: computed scalar pressure (0-1)
- authority_score: computed scalar pressure (0-1)
- conflict_pressure: risk-of-being-wrong pressure (0-1)
- canon_readiness: readiness for canonical promotion (0-1)

## Schema evolution

Later-phase tables are created via CREATE TABLE IF NOT EXISTS in
app/db/connection.py. A proper migration system is planned.
""",
    ),
    dict(
        id="boh.arch.retrieval-contract",
        title="External Retrieval Contract v1",
        project="BOH System",
        plane="canonical",
        authority="approved",
        freshness_days=20,
        valid_ahead=365,
        risk=0.09,
        body="""# External Retrieval Contract v1

Read-only retrieval connectors access BOH via /api/retrieve.

## Authentication

BOH_RETRIEVAL_TOKEN — separate from operator token.
Connectors must never receive the operator token.

## Request shape

POST /api/retrieve
{
  "query": "...",
  "limit": 10,
  "include_lineage": true
}

## Response additions (v1)

- citation_uri: "boh://{doc_id}#{chunk_id}" per pack
- source_spans: list mirroring source_span
- warnings: rolled-up gate warnings

## Governance

/api/retrieve is read-only. No corpus data is mutated.
Advisory LLM enqueue mutates the review queue and requires operator token.
""",
    ),
    dict(
        id="boh.arch.fold-workspace",
        title="Fold Workspace Specification v0.3",
        project="BOH System",
        plane="canonical",
        authority="approved",
        freshness_days=7,
        valid_ahead=180,
        risk=0.10,
        body="""# Fold Workspace Specification v0.3

The Fold Workspace visualizes the corpus as a force-directed graph.

## Projections

1. Web — default; fill = currentness
2. Risk Map — size = risk-if-wrong; coordinates stable
3. Authority Path — border weight = authority tier
4. Currentness Map — X = authority pressure, Y = freshness pressure; layout changes
5. Evidence State — fill = plane palette; shape = evidence kind
6. Timeline — X = epistemic_valid_until; layout changes

## Encoding rules

- Fill is reserved for currentness in every projection except Evidence State
- Workflow/gate/intake markers appear as 8px pips, never as fill
- Selection = solid accent ring; keyboard focus = dashed outer ring
- Hover = glow + 8% scale

## Inspector

Each node shows: why-current factor rows, authority facets, fold snapshot,
unknowns, resolver trace link.
""",
    ),
    dict(
        id="boh.arch.security-policy",
        title="BOH Security Policy",
        project="BOH System",
        plane="canonical",
        authority="canonical",
        freshness_days=2,
        valid_ahead=365,
        risk=0.03,
        body="""# BOH Security Policy

## Operator token

- Set BOH_OPERATOR_TOKEN before launch for production use
- DEV-OPEN mode (token unset) allows protected routes with a warning badge
- Token is never exposed in responses or logs

## Actor identity

- X-BOH-Actor-ID attributes every mutation
- Actor identity is separate from authorization
- Default actor: local_operator

## Filesystem boundary

- All reads/writes resolve under BOH_LIBRARY
- Caller-supplied roots outside BOH_LIBRARY are rejected
- Quarantine, hidden, and system folders are excluded from autoindex

## LLM governance

- LLM outputs enter the review queue as proposals
- No LLM output is applied without explicit operator admission
- LLM canon promotion is locked off
""",
    ),

    # ── EVIDENCE plane — Knowledge Management ─────────────────────────────────
    dict(
        id="km.evidence.retrieval-benchmark-2026",
        title="Retrieval Quality Benchmark — June 2026",
        project="Knowledge Management",
        plane="evidence",
        authority="reviewed",
        freshness_days=8,
        valid_ahead=90,
        risk=0.22,
        body="""# Retrieval Quality Benchmark — June 2026

## Methodology

100 queries against 500-document corpus. Metrics: MRR@10, NDCG@5, P@1.

## Results

| Condition | MRR@10 | NDCG@5 | P@1 |
|-----------|--------|--------|-----|
| FTS baseline | 0.61 | 0.58 | 0.54 |
| + authority rerank | 0.71 | 0.67 | 0.63 |
| + conflict filter | 0.74 | 0.70 | 0.66 |
| + freshness weight | 0.77 | 0.73 | 0.69 |

## Interpretation

Authority reranking provides the largest single gain (+10 MRR).
Conflict filtering removes misleading results for contested topics.
Freshness weighting helps most in rapidly-changing domains.

## Limitations

Benchmark uses synthetic labels. Production corpus may differ.
""",
    ),
    dict(
        id="km.evidence.conflict-detection-study",
        title="Conflict Detection Study: Canon Collision Patterns",
        project="Knowledge Management",
        plane="evidence",
        authority="reviewed",
        freshness_days=30,
        valid_ahead=180,
        risk=0.31,
        body="""# Conflict Detection Study: Canon Collision Patterns

## Purpose

Understand how canonical truth conflicts arise in long-running corpora.

## Finding 1: Terminology drift

The same concept evolves different names across teams.
Without reconciliation, the corpus accumulates conflicting definitions.

## Finding 2: Authority vacuum

When a document's author leaves, authority state degrades silently.
Score drops but no review is triggered without automation.

## Finding 3: Freshness-authority mismatch

A document can be freshly indexed but carry stale authority.
These appear current on the Y-axis but low on the X-axis of Currentness Map.

## Recommendation

Surface authority vacuums as a dedicated alert class.
Pair freshness scoring with authority provenance checks.
""",
    ),
    dict(
        id="km.evidence.fold-graph-test-run",
        title="Fold Graph Projection Test Run — All 6 Projections",
        project="Knowledge Management",
        plane="evidence",
        authority="under_review",
        freshness_days=12,
        valid_ahead=60,
        risk=0.38,
        body="""# Fold Graph Projection Test Run — All 6 Projections

## Test corpus

47 documents, 3 projects, 5 planes, varied authority/freshness.

## Web projection

17 current (green), 12 stale (amber), 8 expired (brown), 6 conflict (red), 4 unknown (purple).
Topology stable; cluster expansion tested.

## Risk Map

Largest nodes: conflict documents + stale with high drift risk.
No reflow confirmed on projection switch.

## Authority Path

4 distinct border weight tiers visible. Certificate nodes render as diamonds.
Governed/certificate edges emphasized correctly.

## Currentness Map

Scatter fills all 4 quadrants. High-authority/low-freshness cluster visible
(old but trusted documents). Low-authority/high-freshness cluster visible (new drafts).

## Evidence State

All 8 planes present. Shape encoding: source=square, evidence=triangle,
claim=circle, interface=diamond. Currentness corner badges visible.

## Timeline

3-year span. Supersession edges connect older to newer versions.
""",
    ),
    dict(
        id="km.evidence.authority-drift-log-q1",
        title="Authority Drift Log — Q1 2026",
        project="Knowledge Management",
        plane="evidence",
        authority="draft",
        freshness_days=90,
        valid_ahead=None,
        risk=0.54,
        body="""# Authority Drift Log — Q1 2026

## Summary

12 documents moved from reviewed → under_review during Q1.
4 documents expired without renewal.
2 new conflicts detected.

## Notable drift cases

### Case 1: Retrieval contract v0.9

Conflict with v1.0 detected. v0.9 authority reduced to draft.
Resolution pending: v1.0 is the authoritative version.

### Case 2: Deployment checklist

Author no longer active. Authority degraded to custodian_review.
Custodian review scheduled for next sprint.

### Case 3: Terminology guide

Divergent definitions found between two team documents.
Conflict flag raised. Under_review pending resolution.

## Patterns

Q1 drift rate: 2.4 documents/month entering under_review.
Average time in under_review: 18 days.
""",
    ),
    dict(
        id="km.evidence.ontology-coverage-report",
        title="Ontology Coverage Report v2",
        project="Knowledge Management",
        plane="evidence",
        authority="non_authoritative",
        freshness_days=180,
        valid_ahead=None,
        risk=0.67,
        body="""# Ontology Coverage Report v2

## Purpose

Assess which concepts in the corpus have adequate documentation vs. gaps.

## Coverage by plane

| Plane | Docs | Average authority | Coverage |
|-------|------|-------------------|----------|
| canonical | 6 | 0.94 | High |
| evidence | 8 | 0.61 | Medium |
| informational | 8 | 0.52 | Medium |
| subjective | 6 | 0.31 | Low |
| internal | 6 | 0.44 | Low |
| review | 6 | 0.38 | Low |
| conflict | 4 | 0.18 | Very Low |
| archive | 6 | 0.55 | Medium |

## Gaps identified

- No formal evidence for LLM proposal quality
- Subjective plane has no canonical anchors
- Conflict plane lacks resolution documentation

## Recommendation

Prioritize evidence collection for: LLM governance, conflict resolution patterns,
and authority transfer procedures.
""",
    ),
    dict(
        id="km.evidence.stale-authority-specimens",
        title="Stale Authority Specimens — Analysis",
        project="Knowledge Management",
        plane="evidence",
        authority="unknown",
        freshness_days=None,
        valid_ahead=None,
        risk=0.78,
        body="""# Stale Authority Specimens — Analysis

## Note

This document itself demonstrates a stale authority specimen.
Its authority_state is unknown and its freshness is indeterminate.
Observe how it appears in the Fold visualizations:

- Web: unknown (purple)
- Risk Map: large node (high drift risk)
- Authority Path: thin border (low tier)
- Currentness Map: bottom-left quadrant (low X, low Y)

## What makes authority go unknown

1. Author identity not tracked at index time
2. External source without clear provenance
3. LLM-generated without admission decision
4. Imported from unvetted external corpus

## Remediation path

1. Assign to a custodian
2. Schedule authority review
3. Determine: promote, maintain at draft, or archive
""",
    ),
    dict(
        id="km.evidence.llm-proposal-quality-log",
        title="LLM Proposal Quality Log — Sample",
        project="Knowledge Management",
        plane="evidence",
        authority="non_authoritative",
        freshness_days=45,
        valid_ahead=90,
        risk=0.62,
        body="""# LLM Proposal Quality Log — Sample

## Purpose

Track LLM proposal accuracy to calibrate trust levels.

## Sample (20 proposals)

Accepted as accurate: 11 (55%)
Accepted with corrections: 5 (25%)
Rejected as inaccurate: 3 (15%)
Rejected as out of scope: 1 (5%)

## Error categories

- Terminology: 4 cases (used term differently than corpus)
- Factual drift: 3 cases (referenced stale information)
- Scope overshoot: 2 cases (made claims outside domain)
- Hallucination: 1 case (fabricated citation)

## Interpretation

LLM proposals are useful accelerants for draft content.
None should bypass the review queue.
The 15% rejection rate justifies the mandatory human review step.

Note: this log is advisory only. LLM-origin document.
""",
    ),
    dict(
        id="km.evidence.plane-distribution-snapshot",
        title="Corpus Plane Distribution Snapshot",
        project="Knowledge Management",
        plane="evidence",
        authority="draft",
        freshness_days=60,
        valid_ahead=120,
        risk=0.44,
        body="""# Corpus Plane Distribution Snapshot

Captured at demo seeding time.

## Target distribution for visualization richness

| Plane | Target docs | Purpose |
|-------|-------------|---------|
| canonical | 6 | Stable high-authority core |
| evidence | 8 | Varied quality/freshness |
| informational | 8 | General reference |
| subjective | 6 | Advisory/LLM content |
| internal | 6 | Process docs |
| review | 6 | Active review |
| conflict | 4 | Disputed content |
| archive | 6 | Historical |

Total: 50 documents across 4 projects.

## Fold View coverage

This distribution ensures:
- All currentness states appear (requires varied validity dates)
- All 4 Currentness Map quadrants populated
- Evidence State shows all 8 planes
- Risk Map has meaningful size variation
""",
    ),

    # ── INFORMATIONAL plane — Knowledge Management ────────────────────────────
    dict(
        id="km.info.getting-started",
        title="Getting Started with Bag of Holding",
        project="Knowledge Management",
        plane="informational",
        authority="approved",
        freshness_days=10,
        valid_ahead=365,
        risk=0.12,
        body="""# Getting Started with Bag of Holding

## Prerequisites

- Python 3.11+
- pip install -r requirements.txt

## Quick start

    python launcher.py

Opens http://127.0.0.1:8000/v2/ — the new governed UI.

## First steps

1. Navigate to Current State to see corpus health
2. Use Capture & Intake to add documents to your library
3. Open Fold Workspace to visualize the corpus graph
4. Set an operator token in Settings → Security & Advanced

## URL map

- /v2/#current    Current State / Overview
- /v2/#fold       Fold Workspace (graph)
- /v2/#library    Library (search, browse)
- /v2/#review     Review Center
- /v2/#authority  Authority & Audit
- /v2/#intake     Capture & Intake
- /v2/#settings   Settings
""",
    ),
    dict(
        id="km.info.deployment-checklist",
        title="BOH Deployment Checklist",
        project="Knowledge Management",
        plane="informational",
        authority="reviewed",
        freshness_days=25,
        valid_ahead=180,
        risk=0.19,
        body="""# BOH Deployment Checklist

## Before launch

- [ ] Set BOH_OPERATOR_TOKEN (required for production use)
- [ ] Set BOH_LIBRARY to the correct library root
- [ ] Set BOH_DB to persistent storage location
- [ ] Set BOH_RETRIEVAL_TOKEN for an external retrieval consumer
- [ ] Configure BOH_OLLAMA_URL if using LLM review
- [ ] Run: python launcher.py --no-browser to verify startup
- [ ] Hit /api/health and confirm status: ok
- [ ] Confirm library root in response matches expected path

## After first launch

- [ ] Run seed script if this is a fresh deployment
- [ ] Verify Fold View shows indexed documents
- [ ] Confirm authority states are distributed as expected
- [ ] Test a search query in Library

## Ongoing

- [ ] Monitor /api/coherence/summary for drift
- [ ] Review /api/conflicts periodically
- [ ] Check /api/integrity/dashboard for authority violations
""",
    ),
    dict(
        id="km.info.faq",
        title="BOH Frequently Asked Questions",
        project="Knowledge Management",
        plane="informational",
        authority="reviewed",
        freshness_days=40,
        valid_ahead=180,
        risk=0.16,
        body="""# BOH Frequently Asked Questions

## Q: What is DEV-OPEN mode?

When BOH_OPERATOR_TOKEN is not set, protected routes are allowed through with a
DEV-OPEN badge in the UI. Set the token for production use.

## Q: Why can't I see my documents in the Fold?

Documents must be indexed first. Use Capture & Intake or run
python seed_demo_library.py.

## Q: What is an authority state?

The authority state records how much trust the corpus has in a document.
canonical > trusted > approved > reviewed > under_review >
custodian_review > draft > non_authoritative > unknown.

## Q: What is a plane?

A plane (canonical_layer) classifies what kind of document it is:
canonical, evidence, informational, subjective, internal, review, conflict, archive.
Planes appear in the Evidence State projection of the Fold Workspace.

## Q: How do LLM proposals work?

Ollama generates proposals that enter the review queue.
No LLM output is applied without explicit operator admission.
""",
    ),
    dict(
        id="km.info.troubleshooting",
        title="BOH Troubleshooting Guide",
        project="Knowledge Management",
        plane="informational",
        authority="under_review",
        freshness_days=55,
        valid_ahead=90,
        risk=0.35,
        body="""# BOH Troubleshooting Guide

## Server won't start

- Port already in use: launcher tries next 10 ports automatically
- Missing packages: pip install -r requirements.txt
- Wrong directory: run from the repository root folder

## /api/coherence/summary returns 500

Was caused by timezone-naive datetime comparison.
Fixed in v2.28.4+: all fromisoformat() calls now return UTC-aware datetimes.

## Documents not appearing in Fold

1. Check /api/fold/library — should return docs array
2. Run seed_full_demo.py to populate demo content
3. Verify BOH_LIBRARY points to correct directory

## Search returns no results

1. Check /api/search?q=test — should return results array
2. Ensure documents are indexed (not just preserved)
3. FTS index is built on indexing, not on preservation

## Authority badges showing unknown

Unknown means authority was not assessed at index time.
Use Authority & Audit → Authority Ledger to review and promote.
""",
    ),
    dict(
        id="km.info.api-reference-summary",
        title="BOH API Reference Summary",
        project="Knowledge Management",
        plane="informational",
        authority="approved",
        freshness_days=18,
        valid_ahead=365,
        risk=0.13,
        body="""# BOH API Reference Summary

Full OpenAPI spec at /docs or /openapi.json.

## Key read-only endpoints

GET /api/health          — server status and version
GET /api/dashboard       — corpus summary (total docs, conflicts, etc.)
GET /api/docs            — paginated document list
GET /api/search          — full-text search
GET /api/coherence/summary — coherence state distribution
GET /api/fold/library    — Fold Workspace scatter data
GET /api/fold/node/{id}  — detailed node packet with why_current
GET /api/graph/projection — graph topology for Fold
GET /api/integrity/dashboard — integrity and drift state
GET /api/audit           — audit event stream

## Key operator-gated endpoints

POST /api/llm/queue/{id}/approve  — admit LLM proposal
POST /api/llm/queue/{id}/reject   — reject LLM proposal
POST /api/governance/approve/{id}/approve — approve governance request
POST /api/intake/run              — run intake pipeline
POST /api/index                   — index documents

## Authentication

X-BOH-Operator-Token required for mutation endpoints.
X-BOH-Retrieval-Token required for /api/retrieve.
""",
    ),
    dict(
        id="km.info.visualization-guide",
        title="BOH Visualization Guide — Understanding Fold Projections",
        project="Knowledge Management",
        plane="informational",
        authority="reviewed",
        freshness_days=6,
        valid_ahead=180,
        risk=0.17,
        body="""# BOH Visualization Guide — Understanding Fold Projections

## How to read the Fold Workspace

The Fold Workspace shows your corpus as a force-directed graph.
Each document is a node. Edges show relationships.

## Color encoding (Web projection)

- Green (✓ current): freshness and authority both good
- Amber (⚠ stale): aging, needs attention
- Brown (⧖ expired): validity window closed
- Red (! conflicted): contradicting content detected
- Purple (? unknown): authority/freshness not assessed

## Projection switcher

Click a projection in the control bar to change what's emphasized:

- Web: navigate the corpus, see conflicts as red nodes
- Risk Map: larger nodes = higher drift risk (bigger = more concern)
- Authority Path: thicker borders = higher authority tier
- Currentness Map: top-right quadrant = high authority + fresh (ideal)
- Evidence State: color = plane type (canonical=gold, evidence=teal, etc.)
- Timeline: left = older, right = newer validity

## Inspector

Click any node to see: Why current? factors, authority tier, cert status,
pressure bars, fold snapshot, unknowns, and resolver trace.
""",
    ),
    dict(
        id="km.info.knowledge-governance-primer",
        title="Knowledge Governance Primer",
        project="Knowledge Management",
        plane="informational",
        authority="custodian_review",
        freshness_days=120,
        valid_ahead=None,
        risk=0.48,
        body="""# Knowledge Governance Primer

## Why governance matters

Without governance, knowledge bases decay silently.
Documents accumulate contradictions.
Authority becomes unclear.
Consumers can't distinguish reliable from speculative content.

## The BOH model

BOH makes governance explicit:

1. Authority is tracked per document (9 states)
2. Conflicts are detected and flagged (not silently ignored)
3. Changes require actor attribution
4. LLM contributions enter a review queue, not the corpus directly
5. Canon promotion requires certificate + custodian sign-off

## The cost of skipping governance

- Silent drift: documents diverge without detection
- Authority collapse: everything becomes equally trusted or equally suspect
- Retrieval pollution: bad documents score as well as good ones
- Audit gaps: no record of who changed what or why

## Getting started with governance

1. Set an operator token
2. Review conflicts periodically
3. Keep high-authority documents fresh
4. Use the Authority Ledger to track authority changes
""",
    ),
    dict(
        id="km.info.plane-classification-guide",
        title="Plane Classification Guide",
        project="Knowledge Management",
        plane="informational",
        authority="reviewed",
        freshness_days=35,
        valid_ahead=365,
        risk=0.14,
        body="""# Plane Classification Guide

## Eight planes

### canonical
The most authoritative knowledge. Promoted through formal review.
Example: architecture specifications, security policy, formal contracts.

### evidence
Verified observations, experiments, benchmarks, audit logs.
Example: benchmark results, test evidence, drift logs.

### informational
General reference and documentation.
Example: FAQs, guides, API references, tutorials.

### subjective
Advisory, opinion, or LLM-generated content.
Example: design notes, speculation, proposals, LLM drafts.

### internal
Process documents, team notes, governance scaffold.
Example: meeting notes, sprint plans, onboarding guides.

### review
Documents actively being reviewed or proposed for change.
Example: RFCs, proposed changes, under-discussion items.

### conflict
Disputed or contradicting content awaiting resolution.
Example: contradicting definitions, unresolved disagreements.

### archive
Superseded or historical content preserved for provenance.
Example: old specs, deprecated APIs, historical decisions.
""",
    ),

    # ── SUBJECTIVE plane — Knowledge Management ───────────────────────────────
    dict(
        id="km.subj.design-philosophy",
        title="BOH Design Philosophy Notes",
        project="Knowledge Management",
        plane="subjective",
        authority="non_authoritative",
        freshness_days=50,
        valid_ahead=None,
        risk=0.55,
        body="""# BOH Design Philosophy Notes

Advisory notes. These are opinions, not policy.

## On explainability

Every score should be decomposable.
"Why is this document stale?" should have a specific answer.
Opaque numeric scores are a governance hazard.

## On trust

Trust is earned incrementally.
A document starts at unknown and works its way up through review.
There is no shortcut. Trust shortcuts create vulnerabilities.

## On LLM roles

LLMs are powerful but unreliable authors.
The review queue exists to catch what they get wrong.
LLM proposal volume shouldn't outpace human review capacity.

## On simplicity

The fewer concepts a user needs to understand to operate safely, the better.
Current vs. stale vs. expired vs. conflict covers most cases.
Complexity in the engine; simplicity in the interface.
""",
    ),
    dict(
        id="km.subj.ux-design-notes",
        title="UX Design Notes — Governed Interface Principles",
        project="Knowledge Management",
        plane="subjective",
        authority="non_authoritative",
        freshness_days=15,
        valid_ahead=90,
        risk=0.42,
        body="""# UX Design Notes — Governed Interface Principles

Advisory. Based on observation, not formal study.

## Principle 1: Semantic consistency

The same color always means the same thing.
Green = current. Amber = stale. Red = conflict. Purple = unknown.
Never repurpose semantic colors for decoration.

## Principle 2: Governance visibility

Security and authority state should be surfaced, not hidden.
DEV-OPEN badge, authority tier in inspector, cert status in facets.
Users should never be surprised by what permissions they have.

## Principle 3: Reversible first

Dangerous actions (purge, reset) are always clearly marked as irreversible.
Reversible actions (quarantine, hold) use Containment styling, not Danger.
The UI styling should communicate consequence.

## Principle 4: Honest data

Show what's unknown as unknown. Don't interpolate missing authority.
Show inferred values as inferred (banner annotation).
Trust is built by being honest about limitations.
""",
    ),
    dict(
        id="km.subj.future-architecture-speculation",
        title="Future Architecture Speculation — LLM Advisory",
        project="Knowledge Management",
        plane="subjective",
        authority="non_authoritative",
        freshness_days=30,
        valid_ahead=60,
        risk=0.71,
        body="""# Future Architecture Speculation — LLM Advisory

This document is LLM-generated and advisory only.
Do not treat as canonical. Enter review queue before using.

## Possible future directions

### Federated governance

Multiple BOH instances sharing authority evidence.
Authority certificates could travel between instances.
Conflicts detected cross-corpus.

### Real-time coherence streaming

WebSocket endpoint streaming coherence events.
Dashboard updates without polling.
Fold graph animates authority changes live.

### Embedding-based similarity

Vector embeddings for semantic deduplication.
Identify similar documents before they conflict.
Cluster by meaning, not just by project tag.

### Audit chain

Blockchain-style append-only audit.
Authority changes provably immutable.
Third-party audit of governance decisions.

ADVISORY: These are speculative. No commitment implied.
""",
    ),
    dict(
        id="km.subj.technology-comparison",
        title="Knowledge Tool Technology Comparison Notes",
        project="Knowledge Management",
        plane="subjective",
        authority="draft",
        freshness_days=75,
        valid_ahead=None,
        risk=0.58,
        body="""# Knowledge Tool Technology Comparison Notes

Opinion piece. Not a formal evaluation.

## Dimension: Authority tracking

Most tools: none
BOH: first-class, 9 states

## Dimension: Conflict detection

Most tools: manual
BOH: automated at index time + periodic coherence evaluation

## Dimension: LLM integration

Most tools: direct insertion
BOH: review queue, operator admission required

## Dimension: Provenance

Most tools: basic metadata
BOH: actor ledger, authority transfer chain, certificate model

## Dimension: Visualization

Most tools: list/table views
BOH: force-directed graph with 6 projections

## Observation

Most knowledge tools optimize for ingestion speed.
BOH optimizes for epistemic integrity.
These goals are in tension. BOH consciously accepts the tradeoff.
""",
    ),
    dict(
        id="km.subj.ai-governance-proposal",
        title="Proposed: AI Governance Layer Enhancement",
        project="Knowledge Management",
        plane="subjective",
        authority="draft",
        freshness_days=22,
        valid_ahead=45,
        risk=0.63,
        body="""# Proposed: AI Governance Layer Enhancement

PROPOSAL ONLY. Not approved. Under discussion.

## Problem

The current review queue is binary: admit or reject.
Complex proposals may need staged admission:
draft → under_review → approved → canonical.

## Proposed: Staged admission

Each LLM proposal could move through stages with different reviewer tiers.
Stage 1: any reviewer can promote draft → under_review
Stage 2: approved reviewer required for → approved
Stage 3: custodian required for → canonical

## Rationale

Reduces bottleneck on canonical promotion.
Distributes review work across reviewer tiers.
Creates audit trail at each stage.

## Concerns

- Complexity increase
- Stage boundaries may be unclear
- Could create false sense of authority before canonical

Review this before implementing.
""",
    ),
    dict(
        id="km.subj.performance-tuning-notes",
        title="Performance Tuning Notes — Informal",
        project="Knowledge Management",
        plane="subjective",
        authority="non_authoritative",
        freshness_days=200,
        valid_ahead=None,
        risk=0.66,
        body="""# Performance Tuning Notes — Informal

Informal notes. Not verified. Use with caution.

## Observed: coherence evaluation is O(n)

evaluate_all_coherence iterates every document.
With 500+ documents, this can take several seconds.
Consider: sampling, caching, or incremental evaluation.

## Observed: Fold library fetch grows with corpus

/api/fold/library fetches all docs and computes scalars per request.
With large corpora, consider: paginated fold, cached snapshots.

## Observed: FTS index needs rebuilding after bulk import

After bulk import, OPTIMIZE the FTS table for best performance.

## Not verified

These are informal observations, not benchmarked measurements.
Run your own benchmarks before making architectural decisions based on this.
""",
    ),

    # ── INTERNAL plane — Governance Layer ─────────────────────────────────────
    dict(
        id="gov.internal.change-control",
        title="Change Control Overview",
        project="Governance Layer",
        plane="internal",
        authority="approved",
        freshness_days=8,
        valid_ahead=365,
        risk=0.11,
        body="""# Change Control Overview

BOH separates proposed changes from governed acceptance.

## Review principles

- Capture the requested outcome and affected boundary.
- Keep proposed changes narrow and attributable.
- Require relevant tests before acceptance.
- Preserve authorization, validation, filesystem, and audit controls.
- Stop when a change cannot be verified safely.

## Evidence

Accepted changes should record what changed, why it changed, who approved it,
and which verification demonstrated the intended result.
""",
    ),
    dict(
        id="gov.internal.phase-planning-notes",
        title="Phase Planning Notes — BOH Development",
        project="Governance Layer",
        plane="internal",
        authority="under_review",
        freshness_days=45,
        valid_ahead=60,
        risk=0.40,
        body="""# Phase Planning Notes — BOH Development

## Completed phases

Phase 1-8: Governed ingestion and translation layer
Phase 7a-7b: Fold aggregation engine and cluster routes
Phase A-C: New governed UI at /v2/

## Current focus

- /v2/ root cutover (flip / to serve /v2/)
- CANON variable backend (omega_viability, stability_signal, etc.)
- Operator token threading through UI action buttons
- Real why_current factor rows from backend

## Next phases

Phase D: Operator token UI wiring
Phase E: CANON variable computation
Phase F: /v2/ root cutover
Phase G: Fold Phase 7c (cluster UI)

## Governance note

Future phases require explicit review and acceptance before implementation.
Planning notes are not evidence that a feature is shipped.
""",
    ),
    dict(
        id="gov.internal.operator-procedures",
        title="Local Operator Procedures",
        project="Governance Layer",
        plane="internal",
        authority="reviewed",
        freshness_days=20,
        valid_ahead=180,
        risk=0.24,
        body="""# Local Operator Procedures

## Setting the operator token

PowerShell:
    $env:BOH_OPERATOR_TOKEN = "your-token-here"
    python launcher.py

Bash:
    BOH_OPERATOR_TOKEN=your-token python launcher.py

## Using the token in browser requests

The token is stored in sessionStorage as boh_operator_token.
Enter it in Settings → Security & Advanced.

## Actor identity

Set actor ID in Settings → Security & Advanced.
Default: local_operator.
Attribution records appear in Authority & Audit → Authority Ledger.

## Clean workspace workflow

1. Set operator token
2. Start BOH
3. Navigate to Status → Maintenance
4. Click Rebuild index (destroys derived data, recoverable)
5. Or Reset workspace (irreversible — removes all index data)

## Safe restart

Ctrl+C to stop. Launcher auto-selects next free port if 8000 is in use.
""",
    ),
    dict(
        id="gov.internal.release-notes-2026-06",
        title="Release Notes — June 2026",
        project="Governance Layer",
        plane="internal",
        authority="approved",
        freshness_days=1,
        valid_ahead=90,
        risk=0.07,
        body="""# Release Notes — June 2026

## New features

- New governed UI at /v2/ (vanilla ES modules, no build step)
- Fold Workspace: all 6 projections, full interaction depth
- Phase C screens: Library, Review, Authority, Capture, Settings, Activity Log
- Global search deep-link from top bar
- Alert drawer wired to /api/audit
- LLM queue admit/reject with operator token guard
- why_current factor rows in fold node inspector
- Launcher: auto port retry (up to +10 ports)

## Bug fixes

- coherence_decay.py: fromisoformat() timezone bug fixed (was causing 500)
- temporal_governor.py and 9 other core files: same timezone fix
- settings-full.js: rebuild() self-replace bug fixed (tabs now switch)
- All Phase C screens: rebuild() bug fixed

## Launcher

- Opens /v2/ by default
- Unicode crash fixed on Windows
- Dead duplicate code block removed
""",
    ),
    dict(
        id="gov.internal.test-baseline-notes",
        title="Test Baseline Notes",
        project="Governance Layer",
        plane="internal",
        authority="reviewed",
        freshness_days=12,
        valid_ahead=90,
        risk=0.21,
        body="""# Test Baseline Notes

## UI pinning tests (fast, no server required)

tests/test_fold_view_ui.py — 17 tests
tests/test_phase27_browser_workflow_static.py — 18 tests
Total: 35 tests, run in ~0.2s

Run after any HTML/JS change:
    python -m pytest tests/test_fold_view_ui.py tests/test_phase27_browser_workflow_static.py -q

## Fold packet tests (requires DB init)

tests/test_current_fold_packet.py — 55 tests
Run in ~6s with DB.

## Full suite

python -m pytest tests -q
Requires running server for some tests.
Pre-server tests: ~90 reliable standalone tests.

## Known flaky test

test_bulk_import_activity_idempotency.py::test_repeated_unchanged_upload_is_skipped
Timestamp-sensitive. Passes in isolation. Known issue.
""",
    ),
    dict(
        id="gov.internal.security-audit-notes",
        title="Security Audit Notes — Local Dev",
        project="Governance Layer",
        plane="internal",
        authority="custodian_review",
        freshness_days=60,
        valid_ahead=90,
        risk=0.46,
        body="""# Security Audit Notes — Local Dev

These notes are for local development only.
A proper security audit is needed for any production deployment.

## Reviewed

- Filesystem boundary: BOH_LIBRARY enforced, traversal rejected
- Operator token: protected routes fail closed when token set
- Actor attribution: all mutations recorded
- LLM governance: proposals cannot bypass review queue

## Concerns for production

- CORS is permissive by default (localhost allowlist)
- dev-open mode could be accidentally deployed without token
- No rate limiting on API endpoints
- SQLite has no access control beyond filesystem permissions

## Not reviewed

- Network-level security
- TLS termination
- Multi-user access control
- Database encryption

## Recommendation

This is a local-first tool. Production deployment requires
additional security hardening outside scope of current implementation.
""",
    ),

    # ── REVIEW plane — Governance Layer ───────────────────────────────────────
    dict(
        id="gov.review.schema-change-proposal",
        title="RFC: Schema Change — Add currentness_score Column",
        project="Governance Layer",
        plane="review",
        authority="draft",
        freshness_days=18,
        valid_ahead=30,
        risk=0.58,
        body="""# RFC: Schema Change — Add currentness_score Column

STATUS: UNDER REVIEW. Do not implement without approval.

## Motivation

The current fold node packet synthesizes currentness from freshness_score
and authority_score. A native currentness_score field would make the
Overview tiles accurate without inference.

## Proposed change

Add to docs table:
    currentness_score REAL DEFAULT NULL,
    currentness_label TEXT DEFAULT NULL

Populate via coherence evaluation on index.

## Impact

- Schema migration required
- All coherence evaluation paths need update
- Overview tiles would show native values (not inferred)
- Fold Workspace projections more accurate

## Concerns

- Schema changes need careful migration planning
- Backfill required for existing documents
- Could be expensive to compute for large corpora

## Status

Under review. Requires custodian approval before implementation.
""",
    ),
    dict(
        id="gov.review.api-extension-proposal",
        title="RFC: API Extension — /api/fold/why-current Endpoint",
        project="Governance Layer",
        plane="review",
        authority="draft",
        freshness_days=14,
        valid_ahead=45,
        risk=0.52,
        body="""# RFC: API Extension — /api/fold/why-current Endpoint

STATUS: UNDER REVIEW.

## Motivation

The fold node inspector shows why_current factor rows, but these are
currently synthesized in app/core/current_fold.py from scalar fields.
A dedicated endpoint could return richer, more accurate factor rows.

## Proposed endpoint

GET /api/fold/why-current/{doc_id}

Returns:
{
  "doc_id": "...",
  "why_current": [
    {"dir": "pos", "factor": "Source freshness", "evi": "valid until 2026-09-01"},
    {"dir": "pos", "factor": "Authority", "evi": "cert C_8821 confirmed"},
    {"dir": "weak", "factor": "Open conflicts", "evi": "1 unresolved"},
    ...
  ],
  "trace_link": "/api/trace/log?doc_id=..."
}

## Alternative

Enrich the existing /api/fold/node/{id} response with why_current
(which is now done as of the June 2026 release).
This RFC may be closed as implemented.
""",
    ),
    dict(
        id="gov.review.ui-cutover-proposal",
        title="RFC: /v2/ Root Cutover Plan",
        project="Governance Layer",
        plane="review",
        authority="under_review",
        freshness_days=5,
        valid_ahead=30,
        risk=0.44,
        body="""# RFC: /v2/ Root Cutover Plan

STATUS: UNDER REVIEW.

## Goal

Make /v2/ the primary UI served at /.
Move classic UI to /classic/.

## Steps

1. Verify all daily-use screens functional in /v2/ ✓
2. Update app/api/main.py StaticFiles mount order
3. Update test_phase27_browser_workflow_static.py
   (currently pins classic UI HTML structure)
4. Update RUN_INSTRUCTIONS.md
5. Keep /classic/ available for transition period

## Risk

test_phase27_browser_workflow_static.py pins aria-labels and nav structure
from app/ui/index.html. These tests must be updated or retired.

## Rollback

Revert the mount order in main.py.
Classic UI files are preserved in app/ui/.

## Approval required

This changes what users see at /. Requires explicit approval.
""",
    ),
    dict(
        id="gov.review.conflict-resolution-procedure",
        title="Draft: Conflict Resolution Procedure",
        project="Governance Layer",
        plane="review",
        authority="draft",
        freshness_days=28,
        valid_ahead=60,
        risk=0.50,
        body="""# Draft: Conflict Resolution Procedure

DRAFT. Not yet approved.

## When a conflict is detected

1. System raises a conflict flag on both documents
2. Documents appear in Review Center → Conflicts
3. Operator assigns a resolver

## Resolution options

A. Accept document A, reject document B
   - B authority reduces to draft or below
   - A remains at current authority state
   - Conflict acknowledged

B. Merge content
   - New document created incorporating both
   - Both originals archived
   - New doc enters review queue

C. Accept both with scope clarification
   - Documents remain but scope boundaries clarified
   - Conflict acknowledged with note

D. Escalate
   - Requires custodian involvement
   - Conflict flagged as blocked pending custodian

## Audit requirement

All resolutions must be attributed to an actor.
Resolution reason must be recorded.
""",
    ),
    dict(
        id="gov.review.canon-promotion-criteria",
        title="Draft: Canon Promotion Criteria",
        project="Governance Layer",
        plane="review",
        authority="under_review",
        freshness_days=35,
        valid_ahead=90,
        risk=0.47,
        body="""# Draft: Canon Promotion Criteria

DRAFT. Under custodian review.

## Requirements for canonical promotion

1. Authority state >= approved (not draft or non_authoritative)
2. No open conflicts
3. Freshness score >= 0.5 (not expired or critically stale)
4. Custodian sign-off
5. Certificate issued

## Canon readiness score

The canon_readiness field (0-1) on each node approximates these criteria.
High canon_readiness = large node in Currentness Map (size encodes readiness).

## Certificate model

Certificate required for canonical promotion.
Certificate attests: authority proof, conflict check, custodian approval.

## Automatic demotion

If a canonical document's validity expires and is not renewed,
it is automatically demoted to expired.
Authority state remains canonical but currentness becomes expired.
""",
    ),
    dict(
        id="gov.review.ollama-integration-review",
        title="Review: Ollama Integration Governance",
        project="Governance Layer",
        plane="review",
        authority="custodian_review",
        freshness_days=40,
        valid_ahead=30,
        risk=0.56,
        body="""# Review: Ollama Integration Governance

STATUS: CUSTODIAN REVIEW — expires soon, renewal needed.

## Current governance locks (hard-coded)

- LLM proposal queue only: LOCKED ON
- LLM canon promotion: LOCKED OFF
- Trace LLM output: LOCKED ON

These cannot be changed via Settings. Intentional.

## Gating conditions

BOH_OLLAMA_ENABLED must be set to enable LLM features.
BOH_OPERATOR_TOKEN required to enqueue proposals.

## Review items

1. Is the review queue capacity adequate for proposal volume?
2. Should rejection reasons be required (not just optional)?
3. Should LLM-origin documents auto-expire after N days?
4. Is the advisory-only marker visible enough in the UI?

## Renewal

This document expires in 30 days. Custodian must review
and either renew or update governance policy.
""",
    ),

    # ── CONFLICT plane — Governance Layer ─────────────────────────────────────
    dict(
        id="gov.conflict.authority-scope-dispute-a",
        title="Authority Scope: Interpretation A — Operator Owns Corpus",
        project="Governance Layer",
        plane="conflict",
        authority="under_review",
        freshness_days=25,
        valid_ahead=60,
        risk=0.88,
        body="""# Authority Scope: Interpretation A — Operator Owns Corpus

CONFLICT DOCUMENT. In dispute with Interpretation B.

## Position

The operator token holder has ultimate authority over the corpus.
Any document can be promoted or demoted by operator decision.
Authority states are advisory; the operator can override.

## Rationale

Local-first means the local operator is sovereign.
Governance constraints are helpful defaults, not laws.
The operator set the token; they chose to run BOH.

## Evidence cited

- BOH_OPERATOR_TOKEN is set by the local administrator
- Protected routes all pass through operator auth
- No external authority can override local decisions

## Status

DISPUTED by Interpretation B.
Cannot be promoted until conflict resolved.
""",
    ),
    dict(
        id="gov.conflict.authority-scope-dispute-b",
        title="Authority Scope: Interpretation B — Authority is Document Property",
        project="Governance Layer",
        plane="conflict",
        authority="under_review",
        freshness_days=23,
        valid_ahead=60,
        risk=0.91,
        body="""# Authority Scope: Interpretation B — Authority is Document Property

CONFLICT DOCUMENT. In dispute with Interpretation A.

## Position

Authority state belongs to the document, not the operator.
The operator facilitates the governance process but cannot unilaterally
override earned authority.
Canonical promotion requires the certificate model to be satisfied.

## Rationale

If operators can override authority arbitrarily, the governance model
loses its guarantees.
Authority must be earned through the defined process to have meaning.
A document becomes canonical because it satisfies canon criteria,
not because someone says so.

## Evidence cited

- Certificate model requires proof of authority
- Conflict resolution requires actor attribution
- Authority ledger records transfers for audit purposes

## Status

DISPUTED by Interpretation A.
Requires custodian resolution.
""",
    ),
    dict(
        id="gov.conflict.data-model-version-conflict",
        title="Data Model: v2 vs v2.1 — Conflicting Schema Definitions",
        project="Governance Layer",
        plane="conflict",
        authority="draft",
        freshness_days=50,
        valid_ahead=None,
        risk=0.84,
        body="""# Data Model: v2 vs v2.1 — Conflicting Schema Definitions

CONFLICT. Two documents define the schema differently.

## What v2 says

canonical_layer is a free-form text field.
Values are not constrained at the schema level.
Validation happens in application code.

## What v2.1 says

canonical_layer should be an enum type.
Values: canonical, evidence, informational, subjective, internal, review, conflict, archive.
Validation at the schema level prevents invalid values.

## Impact

Current implementation uses free-form text (v2 interpretation).
The Evidence State projection normalizes values via layerToPlane() mapping.
Moving to enum would require schema migration.

## Status

Conflict unresolved. Both documents indexed but neither promoted to canonical.
""",
    ),
    dict(
        id="gov.conflict.llm-role-dispute",
        title="LLM Role: Disagreement on Advisory vs. Collaborative",
        project="Governance Layer",
        plane="conflict",
        authority="draft",
        freshness_days=80,
        valid_ahead=None,
        risk=0.79,
        body="""# LLM Role: Disagreement on Advisory vs. Collaborative

CONFLICT DOCUMENT.

## Position Alpha: LLM is purely advisory

LLM proposals should never reach canonical.
They are useful for drafting but require full human review at every stage.
The distinction between LLM-origin and human-origin content must always be visible.

## Position Beta: LLM can collaborate as a peer

After sufficient track record, LLM proposals with high accuracy scores
could be fast-tracked through review.
Treating LLM as purely advisory creates unnecessary bottlenecks.

## Current governance position

BOH currently implements Position Alpha.
LLM canon promotion is LOCKED OFF.
All LLM proposals enter the review queue.

## Why this is a conflict

Position Beta represents a possible future direction.
The two positions are incompatible at the policy level.
This document exists to surface the disagreement explicitly.
""",
    ),

    # ── ARCHIVE plane — Research Archive ──────────────────────────────────────
    dict(
        id="arch.archive.legacy-route-docs",
        title="ARCHIVED: Legacy Route Documentation — Pre-Phase-27",
        project="Research Archive",
        plane="archive",
        authority="trusted",
        freshness_days=None,
        valid_ahead=None,
        risk=0.33,
        body="""# ARCHIVED: Legacy Route Documentation — Pre-Phase-27

HISTORICAL. Superseded by current route surface.

## Pre-Phase-27 routes (no longer accurate)

These routes existed before the operator token model was hardened.
Some routes had weaker authorization requirements.
Do not use this document as a current API reference.

## What changed in Phase 27

- All mutation routes now require operator token (when configured)
- Actor attribution added to all mutation paths
- Retrieval token separated from operator token
- Bulk import routes now use managed library boundary

## Where to find current routes

OpenAPI: http://localhost:8000/docs
Current route matrix: docs/archive/ROUTE_AUTHORITY_MATRIX_v2_28_4.md

## Preservation reason

Kept for provenance and to understand auth boundary evolution.
Do not re-activate these patterns.
""",
    ),
    dict(
        id="arch.archive.old-data-model-v1",
        title="ARCHIVED: Data Model v1 — Pre-PlaneCard",
        project="Research Archive",
        plane="archive",
        authority="approved",
        freshness_days=None,
        valid_ahead=None,
        risk=0.28,
        body="""# ARCHIVED: Data Model v1 — Pre-PlaneCard

HISTORICAL. PlaneCard model supersedes this.

## v1 structure (no longer current)

In v1, all content was stored in a single docs table.
There was no plane concept.
Authority states were fewer (5 instead of 9).

## Evolution to v2

Phase 18 introduced PlaneCards as a separate entity.
Phase 19 added plane-specific routes and filters.
Phase 24 added temporal governor and epistemic validity.
Phase 28 hardened the authority boundary.

## Key differences

v1: no planes, flat authority, no temporal validity
v2: 8 planes, 9 authority states, temporal validity windows

## Preservation reason

Kept for understanding data model evolution.
Migration notes for v1 → v2 are in docs/archive/.
""",
    ),
    dict(
        id="arch.archive.phase-15-design-notes",
        title="ARCHIVED: Phase 15 Design Notes — Coherence Decay",
        project="Research Archive",
        plane="archive",
        authority="reviewed",
        freshness_days=None,
        valid_ahead=None,
        risk=0.37,
        body="""# ARCHIVED: Phase 15 Design Notes — Coherence Decay

HISTORICAL.

## Phase 15 introduced

- Coherence decay formula: C(t) = C0 * e^(-kÏ„) + R(t)
- Temporal ambiguity state (missing timestamps = ambiguity, not decay)
- Per-plane decay policy (canonical decays slower than evidence)
- Refresh credit from explicit refresh events

## Phase 24 corrections

Phase 24 corrected the epoch-0 fallback bug.
Phase 24.1 removed the epoch-0 fallback permanently.
Phase 24.2 introduced the temporal governor with drift detection.

## Current implementation

app/core/coherence_decay.py — the coherence formula
app/core/temporal_governor.py — drift detection and escalation
app/core/temporal_escalation.py — escalation policy

## Known issue (fixed June 2026)

fromisoformat() was returning naive datetimes for date-only strings.
Comparison with datetime.now(timezone.utc) raised TypeError.
Fixed by attaching UTC timezone when tzinfo is None.
""",
    ),
    dict(
        id="arch.archive.original-fold-design",
        title="ARCHIVED: Original Fold View Design — Phases 0-5",
        project="Research Archive",
        plane="archive",
        authority="reviewed",
        freshness_days=None,
        valid_ahead=None,
        risk=0.30,
        body="""# ARCHIVED: Original Fold View Design — Phases 0-5

HISTORICAL. Superseded by Phase B Fold Workspace.

## Original design (Phases 0-5)

The original Fold View was a scatter canvas (HTML5 Canvas 2D).
A single projection: authority_score vs freshness_score.
No force-directed layout.
No edge rendering.
No cluster support.

## Phase B (2026-06-01)

Phase B replaced the scatter canvas with a full SVG force-directed graph.
Six projections added.
Full interaction depth: keyboard nav, camera memory, cluster expand/collapse.
Real typed edge rendering.
Node inspector with why_current factor rows.

## What was preserved

The /api/fold/library endpoint that served scatter data.
The CurrentFoldPacket model (enhanced with why_current in June 2026).
The scalar pressure computation logic.

## Preservation reason

Historical record of the original approach.
Helps understand design decisions that led to Phase B.
""",
    ),
    dict(
        id="arch.archive.rejected-ontology-proposals",
        title="ARCHIVED: Rejected Ontology Proposals",
        project="Research Archive",
        plane="archive",
        authority="non_authoritative",
        freshness_days=None,
        valid_ahead=None,
        risk=0.42,
        body="""# ARCHIVED: Rejected Ontology Proposals

HISTORICAL. Proposals rejected during design review.

## Proposal: Binary trust model

Rejected. Too coarse. Current/not-current is insufficient for governance.
Authority has nuance that binary cannot capture.

## Proposal: Numeric authority score only

Rejected. Numeric scores without interpretation are opaque.
Users need to understand what "0.74" means to act on it.
Named states (canonical, trusted, approved, ...) are more actionable.

## Proposal: Graph-as-primary (no flat docs table)

Rejected. Graph-first makes simple queries complex.
The docs table as primary with lattice_edges as secondary is more ergonomic.

## Proposal: Conflict as a state, not a flag

Rejected. Conflict is a relationship between documents, not a property of one.
The current model (conflict pairs in lattice_edges) correctly captures this.
The `conflict` plane is for documents that ARE disputes, not that HAVE conflicts.

## Why keep rejected proposals

They document the reasoning behind current design choices.
Future designers should understand why alternatives were considered and rejected.
""",
    ),
    dict(
        id="arch.archive.glossary-v1",
        title="ARCHIVED: Glossary v1 — Superseded by Plane Guide",
        project="Research Archive",
        plane="archive",
        authority="approved",
        freshness_days=None,
        valid_ahead=None,
        risk=0.25,
        body="""# ARCHIVED: Glossary v1 — Superseded by Plane Guide

HISTORICAL. See Plane Classification Guide (km.info.plane-classification-guide).

## Terms (historical definitions)

**Corpus**: the full set of documents managed by BOH.

**Node**: a document in the Fold graph representation.

**Authority state**: the trust level of a document (was: trust level).
Was 5 states in v1, now 9 states in v2.

**Plane**: the classification of document type.
Was: "layer". Renamed to "plane" in Phase 18.

**Coherence**: the degree to which a document is current and uncontested.
Computed from freshness decay, conflict penalty, and refresh credit.

**Fold**: the governed visualization of corpus structure.
Name reflects "dimensional folding" — projecting high-dimensional state
onto viewable 2D representations.

**Certificate**: the formal attestation required for canonical promotion.
""",
    ),
]

# ---------------------------------------------------------------------------
# Conflict pairs: (doc_id_a, doc_id_b, edge_type)
# ---------------------------------------------------------------------------
CONFLICT_PAIRS = [
    ("gov.conflict.authority-scope-dispute-a", "gov.conflict.authority-scope-dispute-b", "contradicts"),
    ("gov.conflict.data-model-version-conflict", "boh.arch.data-model", "contradicts"),
    ("gov.conflict.llm-role-dispute", "boh.arch.security-policy", "contradicts"),
    ("km.subj.ai-governance-proposal", "gov.review.canon-promotion-criteria", "contradicts"),
    ("km.evidence.llm-proposal-quality-log", "km.subj.future-architecture-speculation", "contradicts"),
    ("gov.review.schema-change-proposal", "boh.arch.data-model", "contradicts"),
]

# Supersedes relationships
SUPERSEDES_PAIRS = [
    ("boh.arch.authority-model", "arch.archive.legacy-route-docs"),
    ("boh.arch.data-model", "arch.archive.old-data-model-v1"),
    ("boh.arch.fold-workspace", "arch.archive.original-fold-design"),
    ("km.info.plane-classification-guide", "arch.archive.glossary-v1"),
]

# ---------------------------------------------------------------------------
# Freshness / validity helpers
# ---------------------------------------------------------------------------
NOW_TS = int(time.time())

def _iso_ahead(days: Optional[int]) -> Optional[str]:
    if days is None:
        return None
    dt = datetime.datetime.utcfromtimestamp(NOW_TS + days * 86400)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def _iso_ago(days: Optional[int]) -> Optional[str]:
    """Return an ISO timestamp for `days` ago (None → very old, use 3yr ago)."""
    if days is None:
        days = 3 * 365
    dt = datetime.datetime.utcfromtimestamp(max(0, NOW_TS - days * 86400))
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

# Authority → approximate score
AUTHORITY_SCORE = {
    "canonical":       0.95,
    "trusted":         0.83,
    "approved":        0.74,
    "reviewed":        0.64,
    "under_review":    0.52,
    "custodian_review":0.43,
    "draft":           0.33,
    "non_authoritative":0.21,
    "unknown":         0.10,
}

# ---------------------------------------------------------------------------
# Seeding logic
# ---------------------------------------------------------------------------

def _write_doc(doc: dict) -> Path:
    """Write document content (with BOH frontmatter) to library/demo/<plane>/<id>.md"""
    plane = doc["plane"]
    dest = DEMO_DIR / plane / f"{doc['id']}.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    fm = inp.build_boh_frontmatter(
        doc["title"], [],
        doc_id=doc["id"],
        doc_type="reference",
        project=doc["project"],
        document_class="reference",
        provenance={"mode": "demo_seed", "source": "seed_full_demo"},
    )
    dest.write_text(fm + doc["body"], encoding="utf-8")
    return dest

def _index_doc(path: Path, doc: dict) -> Optional[str]:
    """Index a written document file in place. Returns doc_id or None."""
    try:
        from app.services.indexer import index_file
        result = index_file(path, LIBRARY_ROOT)
        if not isinstance(result, dict) or not result.get("indexed"):
            errs = result.get("lint_errors") if isinstance(result, dict) else result
            _err(f"  index error {doc['id']}: {errs}")
            return None
        return result.get("doc_id")
    except Exception as e:
        _err(f"  index error {doc['id']}: {e}")
        return None

def _enrich_doc(doc_id: str, doc: dict) -> None:
    """Update DB fields for authority, plane, freshness, validity.

    Fold scalars (freshness_score, authority_score, ...) are DERIVED by
    app.core.fold_metrics at projection time — they are not stored columns.
    Freshness derives from epistemic_last_evaluated (priority) or updated_ts,
    so 'ancient/unknown' is encoded as a very old evaluation timestamp.
    """
    freshness_days = doc.get("freshness_days")
    valid_ahead = doc.get("valid_ahead")
    risk = doc.get("risk", 0.5)

    last_evaluated = _iso_ago(freshness_days if freshness_days is not None else 1500)

    # Validity window
    valid_until = _iso_ahead(valid_ahead) if valid_ahead else (
        _iso_ahead(-30) if freshness_days and freshness_days > 60 else None
    )

    try:
        execute("""
            UPDATE docs SET
                authority_state = ?,
                canonical_layer = ?,
                epistemic_last_evaluated = ?,
                epistemic_valid_until = ?,
                epistemic_c = ?
            WHERE doc_id = ?
        """, (
            doc["authority"],
            doc["plane"],
            last_evaluated,
            valid_until,
            round(1.0 - risk, 3),
            doc_id,
        ))
    except Exception as e:
        _err(f"  enrich error {doc_id}: {e}")

def _add_edge(from_id: str, to_id: str, edge_type: str) -> None:
    """Record a stored lineage relationship between two documents.

    Retrieval (context-object node scope) traverses STORED edges from the
    lineage table; 'conflicts' and 'supersedes' are in the verified vocabulary.
    """
    try:
        from_row = fetchone("SELECT doc_id FROM docs WHERE doc_id = ?", (from_id,))
        to_row   = fetchone("SELECT doc_id FROM docs WHERE doc_id = ?", (to_id,))
        if not from_row or not to_row:
            _skip(f"  edge skipped (doc not found): {from_id} -> {to_id}")
            return
        relationship = "conflicts" if edge_type == "contradicts" else edge_type
        execute("""
            INSERT INTO lineage (doc_id, related_doc_id, relationship, detected_ts, detail)
            VALUES (?, ?, ?, ?, ?)
        """, (from_id, to_id, relationship, NOW_TS, "demo seed edge"))
        _ok(f"  edge: {from_id} --[{relationship}]--> {to_id}")
    except Exception as e:
        _err(f"  edge error: {e}")

def clear_demo() -> None:
    _hdr("Clearing previous demo data")
    try:
        execute("DELETE FROM docs WHERE project IN (?, ?, ?, ?)",
                ("BOH System", "Knowledge Management", "Governance Layer", "Research Archive"))
        _ok("Cleared docs for demo projects")
    except Exception as e:
        _err(f"Clear failed: {e}")
    import shutil
    if DEMO_DIR.exists():
        shutil.rmtree(DEMO_DIR)
        _ok(f"Removed {DEMO_DIR}")
    if MARKER.exists():
        MARKER.unlink()
        _ok("Removed seed marker")

def seed() -> None:
    init_db()
    DEMO_DIR.mkdir(parents=True, exist_ok=True)

    _hdr(f"Writing {len(DOCS)} documents to {DEMO_DIR}")
    doc_id_map = {}  # logical_id → db doc_id

    for doc in DOCS:
        path = _write_doc(doc)
        _info(f"Wrote: {path.relative_to(LIBRARY_ROOT)}")
        db_id = _index_doc(path, doc)
        if db_id:
            doc_id_map[doc["id"]] = db_id
            _enrich_doc(db_id, doc)
            _ok(f"Indexed + enriched: {doc['title'][:55]}")
        else:
            _skip(f"Index failed: {doc['id']}")

    _hdr("Adding conflict and supersedes edges")
    for a, b, etype in CONFLICT_PAIRS:
        a_db = doc_id_map.get(a)
        b_db = doc_id_map.get(b)
        if a_db and b_db:
            _add_edge(a_db, b_db, etype)
        else:
            _skip(f"  edge skipped: {a} -> {b} (missing: {not a_db and a}, {not b_db and b})")

    for a, b in SUPERSEDES_PAIRS:
        a_db = doc_id_map.get(a)
        b_db = doc_id_map.get(b)
        if a_db and b_db:
            _add_edge(a_db, b_db, "supersedes")
        else:
            _skip(f"  supersedes skipped: {a} -> {b}")

    MARKER.write_text(f"seeded {NOW_TS}\n{len(DOCS)} docs\n{len(doc_id_map)} indexed\n")

    print()
    _ok(f"Demo seeded: {len(doc_id_map)}/{len(DOCS)} documents indexed")
    print(f"\n  Planes: canonical, evidence, informational, subjective, internal, review, conflict, archive")
    print(f"  Projects: BOH System, Knowledge Management, Governance Layer, Research Archive")
    print("  Authority: full spread (canonical to unknown)")
    print("  Freshness: full spread (1 day ago to unknown/ancient)")
    print(f"  Conflicts: {len(CONFLICT_PAIRS)} conflict pairs")
    print(f"  Supersedes: {len(SUPERSEDES_PAIRS)} supersession edges")
    print()
    print("  Open the Fold Workspace at /v2/#fold to see all 6 projections.")
    print()

def main() -> None:
    ap = argparse.ArgumentParser(description="Seed full BOH demo library.")
    ap.add_argument("--force",   action="store_true", help="Clear and re-seed even if marker exists")
    ap.add_argument("--dry-run", action="store_true", help="Print plan without writing")
    args = ap.parse_args()

    if args.dry_run:
        print(f"DRY RUN — would seed {len(DOCS)} documents across 4 projects, 8 planes")
        for doc in DOCS:
            print(f"  [{doc['plane'][:8]:8s}] [{doc['authority'][:16]:16s}] {doc['title'][:60]}")
        return

    if MARKER.exists() and not args.force:
        print(f"Demo already seeded (marker: {MARKER})")
        print("Run with --force to re-seed.")
        return

    if args.force and MARKER.exists():
        clear_demo()

    seed()


if __name__ == "__main__":
    main()
