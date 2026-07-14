# Glossary

One-screen definitions for the project's internal vocabulary, in roughly the
order a new reader meets them.

| Term | Meaning |
| --- | --- |
| **Plane** | One of eight canonical knowledge layers that classify every document: `canonical`, `evidence`, `informational`, `subjective`, `internal`, `review`, `conflict`, `archive`. Planes describe *what kind of claim* a document makes, independent of its quality. |
| **Authority state** | Where a document stands in the trust ladder (`canonical` … `unknown`). Authority is earned through explicit, audited transitions — never inferred from retrieval relevance or LLM confidence. |
| **CANON** | The set of documents granted canonical authority, plus the scalar "bridge" variables derived for governance pressure (`drift_rate`, `entropy`, `delta_c_star`, `gamma`, `omega_viability`, `mismatch_gradient`). CANON status is a governed outcome, not a score. |
| **Fold / Current Fold View** | The resolver that answers "what is currently true, and why?" for a document or cluster. Produces a `CurrentFoldPacket`: currentness label, dimensional pressure scores, unknowns, and a trace. The Fold Workspace UI renders six projections of it (Web, Risk Map, Authority Path, Currentness Map, Evidence State, Timeline). |
| **PlaneCard / PCDS** | The PlaneCard Data Structure — the storage primitive that wraps an indexed document with its plane, card type, topic, belief/direction/mode (`b`/`d`/`m`), validity window, and payload. The "Domains" surface is built from PlaneCards. |
| **Planar Gate** | Metadata + correction-ledger layer that records governed corrections to planar classifications instead of silently overwriting them. |
| **Daenary** | The epistemic-state vocabulary attached to documents: direction (`d`: affirmed / unresolved / negated), measurement quality (`q`), interpretation confidence (`c`), mode, and temporal validity. Drives the Evidence State projection and semantic search filters. |
| **Rubrix** | The operator-state block in document frontmatter (`operator_state`, `operator_intent`, `next_operator`) — a declarative record of what the human operator was doing with the document. |
| **External retrieval consumer** | A read-only client of the retrieval contract. `/api/retrieve` returns ranked, cited context packs with citation URIs (`boh://{doc_id}#{chunk_id}`), source spans, and warnings. |
| **Context object** | The richer retrieval unit from `/api/context-object`: scope-addressed (doc / project / plane / query / node), with provenance, grounded blockers, question-type context, and fold-neighborhood traversal — designed so an LLM consumer receives governed state, not just text. |
| **Governed intake** | The ingestion pipeline (discovery → preservation → translation → normalization → queryability → interpretation → handoff) that lands external content in `intake_*` ledgers with full provenance. Intake content reaches retrieval only through the explicit, operator-gated **promotion** bridge, and promoted documents stay mutation-isolated and excluded from retrieval by default (dual gate). |
| **Operator token / retrieval token** | Two deliberately separate credentials: `BOH_OPERATOR_TOKEN` gates mutations; `BOH_RETRIEVAL_TOKEN` gates the read-only connectors. Connectors never receive the operator token. |
| **Actor** | Any entity that can originate or act on knowledge (human, LLM, importer, system). Actor identity is recorded for attribution and is independent of operator authorization. |
| **Corpus class** | A document's lifecycle classification (canon / draft / derived / archive / evidence / promoted-intake …) used by exposure and mutation rules. |
| **Approval** | A governed authority transfer that requires explicit operator review and a signed, immutable provenance artifact. Approvals are requests (supersede, patch, edge promotion) that an operator accepts or rejects; rejection causes no state change. All approvals are audit-logged. |
| **Duplicate decision** | An operator-recorded review decision on a content duplicate pair. Four decisions exist: `canonical` (one doc preferred; both kept), `duplicate` (both flagged as duplicate; neither gains authority), `ignored` (false positive; both kept as-is), `quarantine` (both isolated to quarantine layer pending review). **Bag of Holding never deletes source files**, regardless of decision. |
| **ICS export** | Calendar format export of document lifecycle events (created, updated, approved, expired, etc.). Useful for tracking approval milestones and freshness windows in external calendar applications (Apple Calendar, Google Calendar, Outlook). Accessed via `GET /api/events/export.ics`. |

The architecture documents in `docs/architecture/` and `docs/whitepaper.md`
develop these concepts in depth.
