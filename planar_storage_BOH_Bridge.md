1. A stable vocabulary map

Before code, define how existing project concepts map to Planar Storage:

Current concept	Planar Storage equivalent
BOH document / uploaded file / source item	Source Registry item
Existing PlaneCards/domains	PlaneCard layer
Evidence state / authority path	Authority metadata + eligibility decision
Proposed changes queue	Certificate / promotion review queue
Candidate Field / nominated output	Subjective PlaneCard or candidate PlaneCard
Trace JSONL / audit trail	Storage events / append-only trace
Graph substrate	Optional retrieval/topology adapter, not the first dependency
Canon / accepted doctrine	Canonical plane

This mapping matters because otherwise Claude Code may duplicate concepts instead of hardening them.

2. Additive database migrations

The minimum DB layer needs these tables or compatible equivalents:

planes
plane_cards
certificates
plane_interfaces
storage_events

If BOH already has an event/trace table, storage_events can be a compatibility wrapper instead of a new table. But the system still needs event types for:

source_registered
plane_card_wrapped
plane_card_updated
retrieval_performed
candidate_created
certificate_requested
certificate_approved
certificate_rejected
promotion_blocked
card_promoted
plane_interface_created
llm_output_recorded

The spec’s required implementation posture is additive, fail-closed, source-preserving, LLM-non-authoritative, certificate-gated, trace-visible, and mode-aware. That should be treated as the patch contract.

3. PlaneCard wrapping service

This is the first real functional layer.

Needed behavior:

existing source/document/chunk
→ wrap as PlaneCard
→ preserve original source
→ attach plane, card_type, topic, source_ref
→ attach d/m/q/c state
→ attach validity
→ attach authority metadata
→ write trace event

Do not replace current document storage.

Do not require vector search.

Do not rewrite source files.

This should start with deterministic defaults:

{
  "plane": "informational",
  "card_type": "source_document",
  "d": 0,
  "m": "contain",
  "quality": 0.5,
  "confidence": 0.5,
  "state": "active"
}

LLM outputs should default differently:

{
  "plane": "subjective",
  "card_type": "llm_synthesis",
  "d": 0,
  "m": "contain",
  "authority": {
    "may_promote": ["human_owner"]
  }
}

The spec explicitly says LLMs may summarize, classify, suggest states, flag conflicts, propose candidates, and draft certificate requests, but may not approve certificates, promote canon, change authority rules, delete sources, or bypass transition rules.

4. Fail-closed authority evaluator

This should be a pure function first.

Minimum function shape:

def can_use(actor, card, operation, mode) -> Decision:
    ...

def can_promote(actor, card, target_plane) -> Decision:
    ...

def can_translate(actor, source_plane, target_plane) -> Decision:
    ...

The output should not be a bare boolean. It should include:

{
  "allowed": false,
  "reason": "certificate_required",
  "required_action": "request_certificate",
  "visible_message": "This card cannot be promoted to canon without an approved certificate."
}

This is what allows the Authority Center to explain blocks instead of just failing.

5. Certificate workflow

This is the heart of making it real.

Needed endpoints:

POST /certificates/request
POST /certificates/{id}/approve
POST /certificates/{id}/reject
POST /certificates/{id}/revoke
GET  /certificates/{id}
GET  /certificates?card_id=&status=

Required rules:

No d=0 → +1/-1 without certificate.
No subjective/informational → canonical without certificate.
No expired certificate.
No revoked certificate.
No wrong-card certificate.
No wrong-transition certificate.
No LLM-approved certificate.

Without this layer, “canonical” is just metadata. With it, canonical status becomes governed state.

6. Plane interface receipts

Any cross-plane move needs a record of translation loss.

Example:

subjective synthesis
→ informational claim

That transition should require:

source card
target plane
reason
semantic loss note
q/c delta
authority snapshot
certificate reference
trace event

This is what prevents plane collapse. A model-generated summary cannot silently become “what the document says.” It has to pass through an interface artifact.

7. Mode-aware retrieval planner

This is where Planar Storage starts behaving differently from RAG.

Current retrieval/search can remain. The planner wraps it:

query
→ existing text/vector/graph search
→ candidate cards
→ eligibility filter
→ mode-specific ranking
→ result object with warnings/exclusions
→ retrieval_performed event

Minimum retrieval modes:

Strict Answer
Exploration
Audit / Provenance
Canon Review
Low-B Worker Context

Strict Answer should exclude subjective, expired, blocked, deprecated, low-confidence, and unauthorized cards unless explicitly allowed. Exploration can include weaker material but must label it as exploratory. Audit mode should prioritize source refs, events, certificates, interfaces, authority snapshots, blocked transitions, and promotion history. The spec gives this exact mode split and the intended behavior.

The key implementation detail:

retrieval score ≠ eligibility

A chunk can be semantically perfect and still be blocked.

8. UI surfaces

Minimum UI does not need to be ornate. It needs to expose decisions.

Required panels:

PlaneCard Inspector
Authority Center
Retrieval Mode Selector
Conflict/Staleness Panel
Promotion Review Queue
Translation Receipt Viewer

The Authority Center should answer:

Can this be used as answer context?
Can this be used as evidence?
Can this be promoted?
Why blocked?
What certificate is required?
Who can approve?
What expires soon?

The spec names these UI requirements directly.

9. Tests before expansion

The tests are not optional. This system’s value is enforcement.

Minimum acceptance tests:

invalid plane rejected
invalid d rejected
invalid m rejected
invalid q/c rejected
source wraps without mutation
backfill is idempotent
strict mode excludes subjective cards
explore mode includes subjective cards
audit mode returns trace/provenance objects
wrong actor blocked
wrong role blocked
promotion without cert blocked
wrong cert blocked
valid cert allows matching transition
cross-plane movement without interface blocked
LLM output stored as subjective
LLM cannot approve cert
LLM cannot promote canon
all material operations write trace events

The spec’s acceptance matrix already captures this: schema, wrapping, retrieval, authority, certificates, promotion, plane interface, LLM safety, UI, and trace all need tests.

Recommended implementation sequence here
Patch 1: Passive PlaneCards

Goal: make the storage substrate visible without changing behavior.

Deliver:

planes constants / seed data
plane_cards table
PlaneCard schema
wrap source endpoint
get/list/filter endpoints
backfill existing sources
plane_card_wrapped trace event
tests for validation + idempotency

No promotion yet. No complex UI yet. No vector work.

This makes BOH able to say:

“This source exists as an epistemic object with plane, source ref, state, quality, confidence, validity, and authority metadata.”
Patch 2: Retrieval modes

Goal: make retrieval governed.

Deliver:

retrieval policy definitions
strict/explore/audit/canon-review/worker-context endpoints
eligibility evaluator
excluded_summary
retrieval_performed trace event
minimal UI mode selector
result badges: eligible / blocked / stale / subjective / expired
tests for mode differences

This is the first point where Planar Storage becomes operationally different from RAG.

Patch 3: Certificates and promotion blocking

Goal: make canon protected.

Deliver:

certificates table
certificate request/approve/reject/revoke endpoints
promotion endpoint
fail-closed authority checks
promotion_blocked and card_promoted events
tests for no-cert/wrong-cert/expired/revoked/success paths

This creates the first real canon gate.

Patch 4: Plane interfaces

Goal: stop cross-plane collapse.

Deliver:

plane_interfaces table
create/list interface endpoints
cross-plane promotion requires interface
semantic loss / q-c delta fields
translation receipt viewer
tests for subjective→informational and informational→physical blocks
Patch 5: UI integration

Goal: make governance legible.

Deliver:

PlaneCard Inspector
Authority Center integration
Promotion Review Queue
Conflict/Staleness Panel
Translation Receipt Viewer

The UI should never show LLM output as canon unless promoted. The spec states this as an acceptance requirement.

What should not be done yet

Do not start with:

Kubernetes
Neo4j
distributed federation
cloud provider dependency
autonomous agents
tool bus
vector DB requirement
LLM semantic extraction
source rewriting
full graph dependency

The existing graph substrate idea is adjacent, but it should remain advisory. Prior graph-substrate guidance defines the graph boundary as: graph extracts/indexes relationships, BOH governs truth, the harness consumes graph context, and humans approve promotion.

So Planar Storage should govern graph output too, not depend on graph output to exist.

The minimum functional definition

This is functionally implemented when BOH / the harness can do this complete loop:

source imported
→ source preserved
→ source wrapped as PlaneCard
→ retrieval mode selected
→ eligibility evaluated
→ result shown with plane/state/authority/warnings
→ LLM output stored as subjective
→ promotion attempted
→ promotion blocked without certificate
→ certificate requested
→ human approves
→ cross-plane interface recorded if needed
→ card promoted
→ trace proves the path

That is the actual MVP.

Not the full theory. Not every plane. Not every visualization. Not vector search. Not graph search.

The core build target is:

governed retrieval + non-authoritative LLM output + certificate-gated promotion + visible trace

Once that exists, Planar Storage is no longer a concept. It becomes the project’s truth-state substrate.