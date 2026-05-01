# Bag of Holding

## A Constraint-Governed Local Knowledge Workbench for Persistent Human–LLM Reasoning

### Canonical Memory · Explicit Governance · Signed Provenance · Sovereign Knowledge Systems

---

# Executive Summary

Most knowledge systems optimize retrieval.

Very few optimize survivability.

Modern work produces enormous amounts of information — documents, notes, decisions, conversations, policies, and fragmented institutional memory. Most of it becomes operational sediment: searchable, but structurally unstable. Context is lost, reasoning decays, and organizations repeatedly rebuild conclusions they have already paid to reach.

Large language models improved retrieval but worsened this problem in a different way. They generate useful answers while preserving almost none of the reasoning substrate that produced them. Conversations become intelligence without continuity.

Bag of Holding exists to solve that failure.

Bag of Holding is a local-first, constraint-governed knowledge workbench designed for persistent reasoning, canonical document stewardship, and auditable human–LLM collaboration. It is not a note-taking application, a vector database wrapper, or a chatbot with memory. It is an operational substrate for maintaining knowledge integrity across time, users, and changing model layers.

The system combines durable Markdown-based knowledge structures, SQLite-backed state management, graph-based relationship modeling, multi-mode Atlas visualization, constrained LLM integration, an explicit governance approval layer with signed provenance artifacts, and a PCDS (PlaneCard Data Structure) epistemic encoding layer.

Every document carries lineage. Every canonical transition carries a signed approval record. Every authority event is attributable, auditable, and reversible. Every indexed document exists simultaneously as a structured epistemic object — a PlaneCard — with explicit belief, direction, mode, and validity fields.

The objective is simple: preserve reasoning, not just information.

Systems fail where memory becomes folklore.

Bag of Holding exists to prevent that.

---

# 1. The Problem

Organizations do not fail because they lack information.

They fail because they lose structure — and because systems that appear to govern knowledge actually rely on implicit trust.

A decision made in March becomes institutional fog by September. The rationale is gone. The reasoning is lost. The constraint is invisible to the people now governed by it. In most systems, reconstructing that decision requires finding the right people, hoping their memory is accurate, and accepting that the record will be incomplete.

A second failure mode is less obvious but more dangerous: systems that store governance metadata but never enforce it. "Canonical" becomes a label, not a guarantee. Approval becomes a convention, not a mechanism. The system looks governed while authority transfers silently.

A third failure mode has emerged with the proliferation of LLM-assisted work: epistemic state without epistemic accountability. A model proposes. The proposal enters the corpus. The corpus becomes the next model's context. The original uncertainty — the delta between observation and conclusion, the measurement quality, the interpretation confidence — has been silently discarded. The system cannot distinguish what was known from what was inferred.

Bag of Holding addresses all three.

---

# 2. Design Philosophy

## Constraint First, Then Authority Transfer Law

Truth is not what is stored. Truth is what survives constraint.

But constraint without enforcement is insufficient. A system that has canonical state but no canonical promotion mechanism is a filing cabinet with colored tabs.

The authority layer establishes what states exist, what transitions are legal, and what requires approval. The authority transfer mechanism provides the explicit, signed, auditable pathway by which transitions actually occur. Both are required. Neither is sufficient alone.

## Two Intake Lanes

**Scratch capture** — Minimal metadata. Documents enter as non-authoritative. Searchable and readable. Excluded from canonical topology. Not canonical-capable without explicit promotion.

**Governed entry** — Full metadata validation. Eligible for Atlas topology, LLM review, and canonical promotion. Promotion still requires explicit approval.

This separation prevents the most common failure: treating ingestion as implicit endorsement.

## Epistemic State Is Not Lifecycle State

The Rubrix lifecycle (observe → vessel → constraint → integrate → release) governs a document's operational position in the governance pipeline. It is explicit, reversible, and append-only.

The Daenary epistemic state (d-state, quality, confidence, mode, temporal validity) governs a document's epistemic position in the knowledge field. It is encoded in `doc_coordinates`, visualized across four Atlas modes, and preserved through the PCDS PlaneCard layer.

These systems do not overlap. A document can be in `stable` lifecycle state while having low epistemic confidence. A document can be in `review` state while having high measurement quality. Conflating governance state with epistemic state produces exactly the kind of silent authority transfer that BOH is built to prevent.

## Governance Without Explicit Approval Is Still Implicit Governance

A document becoming canonical is not a formatting event. It is an authority event.

Without explicit approval workflow, the system still relies on hidden authority transfer — silent re-imports, implied trust in review artifacts, semantic similarity becoming structural truth, unrecorded supersession.

This recreates the exact failure mode Bag of Holding was built to prevent: intelligence appearing present while provenance silently decays.

---

# 3. System Architecture

Bag of Holding is built as a local knowledge operating system, not a single application.

**Ingestion** → controlled intake of Markdown, HTML, JSON, plain text, YAML, and CSV with frontmatter validation

**Normalization** → duplicate detection, metadata extraction, hash-based change detection

**Lifecycle engine** → `observe → vessel → constraint → integrate → release` with reversible transitions and append-only history

**Canon & conflict layer** → deterministic scoring resolves authority; conflicts surface and stay until explicitly resolved

**Certification layer** → hash-based, id-projection, and automated issuers; no authority transition without a valid certificate

**Graph layer** → explicit edges for lineage, derivation, conflict, and supersession with five visual strand types

**Atlas** → force-directed visualization with four projection modes: Web (relational), Evidence State (confidence × quality), Risk Map (constraint geometry viability), and Authority Path (constitutional topology)

**LLM interface** → Ollama integration with inlet/outlet filters and mandatory review queue; `non_authoritative: true` enforced at data layer; toggle persisted without restart

**Approval workflow** → four explicit approval surfaces with signed provenance artifacts; no authority transfer without a signed record

**PCDS layer** → Phase 19 PlaneCard Data Structure: every indexed document wrapped as a PlaneCard with plane, card_type, topic, b/d/m, constraints, validity, context_ref, and payload

**CA Explorer** → companion substrate lattice application providing cellular automata-based confidence and belief-state analysis with direct CANON integration

---

# 4. The Four Visualization Modes

The Atlas is not decorative graph visualization. It is the operational visibility layer — the instrument panel for the epistemic state of the corpus.

## Web (Relational)

The foundational topology view. Nodes represent documents; edges represent typed relationships (lineage, supersession, derivation, conflict, topic overlap). Node color encodes corpus class; node size reflects canon score. This mode answers: what depends on what, what conflicts with what, and what is trusted.

## Evidence State

Documents are positioned on a 2D plane where X = interpretation confidence and Y = measurement quality. Node color encodes d-state (green = +1 affirmed, amber = 0 unresolved, red = −1 negated). Documents without epistemic state cluster in the lower-left sentinel zone. This mode identifies knowledge gaps, contradictions, and documents requiring epistemic intervention. It answers: where is the corpus epistemically weak, and where are assertions being made without adequate evidential grounding?

## Risk Map

A constraint geometry projection. Documents are positioned by their q/c viability surface — epistemic confidence × quality × meaning cost. Four viability quadrants define actionable zones: Viable (high q, high c, upper-right), Contain Zone, Weak Zone, and Low Zone requiring intervention (lower-left). Each Projection Manifest defines the active signal, conserved metric, quality gate thresholds, discarded dimensions, and allowed governance actions for the current view.

## Authority Path

The constitutional topology projection. Documents are positioned by custodian lane × governance state ordering. Lane distribution counters surface how many documents are in each governance state: raw imported, expired, cancelled, contained, under review, approved, canonical, archived. Contradiction-blocked and held-for-resolution nodes are highlighted explicitly. This mode identifies governance bottlenecks, unresolved authority transitions, and documents approaching expiration.

---

# 5. Explicit Approval Surfaces

Every authority transfer requires a visible, deliberate, signed approval. Four surfaces:

**1. Canonical promotion** (`draft → canonical_candidate → canonical`)

Operator creates a promotion request. The document state does not change. A reviewer inspects the request, provides a mandatory review note, and approves. At approval, the system creates a signed provenance artifact (HMAC-SHA256) and then executes the state change.

**2. Cross-project edge promotion** (`suggested → governed`)

Semantic similarity suggests relationships. It does not establish authority. Suggested edges render as dashed low-opacity strands in Atlas. Promoting to governed requires explicit approval acknowledging the cross-project authority dependency.

**3. Review artifact patch approval**

LLM review output must never silently rewrite source truth. Applying a patch requires a diff_hash of proposed changes and explicit line-by-line approval before any content merge. No auto-merge. No silent overwrite.

**4. Supersede operation**

Superseding a canonical document requires an impact preview (downstream reference count), explicit acknowledgment, and approval. Old canonicals are never deleted — they remain queryable with `status=superseded`. Lineage records preserve the full chain.

**Provenance artifact:**

```json
{
  "artifact_id": "prv-abc123",
  "action_type": "canonical_promotion",
  "document_id": "...",
  "from_state": "draft",
  "to_state": "canonical",
  "approved_by": "operator",
  "approved_at": 1714000000,
  "reason": "Reconciled formal variable definitions",
  "signature": "hmac-sha256:..."
}
```

Every approval creates this record before the state change executes. The record is immutable and append-only.

---

# 6. The Certification Layer

Phase 15 introduced signed provenance artifacts. The certification layer extends this into a full validation infrastructure.

Authority transitions — canonical promotion, supersession, governed edge creation — require a certificate. Only three issuer types are accepted: hash-based, id-projection, and automated (with explicit automation scope). Certificate requests carry a justification and conflict hash. Certificates are validated before any governance state change is executed.

The Certification Validation Center in the Resolution Center provides a full certificate inspection surface. Every certificate is queryable, inspectable, and linked to its originating governance event. The audit log preserves the full issuance and validation chain.

This means the system can answer: *not just who approved this, but what certificate validated that approval, and what was the conflict state at the time of issuance.*

---

# 7. PlaneCards — Phase 19 PCDS Layer

Phase 19 introduced the PlaneCard Data Structure. Every indexed document is wrapped as a PlaneCard — a structured epistemic object that carries:

| Field | Description |
|-------|-------------|
| `plane` | Named knowledge plane |
| `card_type` | Semantic classification |
| `topic` | Normalized topic string |
| `b/d/m` | Belief / Direction / Mode values |
| `constraints` | Active validity constraints |
| `validity` | Temporal validity window |
| `context_ref` | Cross-reference handle |
| `payload` | Document content reference |

The PlaneCard layer is the bridge between the document governance system and the substrate epistemic analysis layer. It provides a normalized, structured representation of each document's epistemic position that can be consumed by external analysis tools — including the CA Explorer.

PlaneCards are backfillable from existing index data and visible through the Domains panel.

---

# 8. CA Explorer Integration

The CA Explorer (v11.2.0, Substrate Lattice + CANON) is a companion research application that provides cellular automata-based substrate analysis with direct integration into BOH's CANON layer.

The CA Explorer models the epistemic substrate as a cellular automaton with configurable parameters: rule set, threshold, coupling, inertia, and pulse rate. The substrate generates waveform outputs across E, H, B, D channels. X_S belief bounds, radial analysis, and VECT field diagnostics are available in real time.

The CANON panel within CA Explorer reads from BOH's canonical state, allowing the substrate dynamics to be tuned against the actual epistemic topology of the corpus. This provides a research surface for understanding how belief propagates, stabilizes, and decays across a knowledge field over time.

The CA Explorer does not write back to BOH's primary governance layer. Its outputs are non-authoritative research data, consistent with BOH's constraint that epistemic analysis tools cannot promote their own conclusions to canonical status.

---

# 9. What the System Can Defend

**Why is this document canonical?**  
→ The provenance chain shows who approved it, when, for what reason, from what prior state, and what certificate validated the transition.

**Who approved this?**  
→ `reviewed_by` is required for every approval execution. The governance event log is append-only.

**What did it replace?**  
→ Supersession records preserve the full lineage chain. Old canonicals remain queryable.

**Why does this cross-project edge exist?**  
→ Either explicitly approved (governed, full opacity in Atlas) or it remains suggested (dashed, low-opacity).

**What is the epistemic quality of this document?**  
→ Daenary coordinates (d-state, quality, confidence) are preserved at index time and visible in Evidence State mode.

**Where are the governance bottlenecks?**  
→ Authority Path mode shows lane distribution and held-for-resolution counts across the corpus.

**Which documents are at epistemic risk?**  
→ Risk Map mode surfaces documents in the contain, weak, and low viability zones.

**Can this be rolled back?**  
→ Lifecycle backward movement is available at every stage. Superseded documents remain queryable. The provenance sequence makes any rollback attributable and verifiable.

These answers come from the system itself — not from Slack, not from tribal memory, not from institutional folklore.

That is the distinction between a governed system and a well-organized filing cabinet.

---

# 10. LLM Integration

The LLM is an operator inside the system. It does not govern it.

The following are enforced at the data layer:

- Canonical status cannot be granted from the LLM review queue
- Trusted Source status cannot be granted from the LLM review queue
- All model outputs carry `non_authoritative: true`
- Every invocation is recorded in `llm_invocations` for audit
- Ollama failures never block server startup or document indexing
- The Ollama enable/disable toggle is persisted without server restart

When Ollama is disabled, the system returns structured non-authoritative responses with invocation records. The AI Analysis pipeline operates deterministically — baseline analysis (topic extraction, normalization, conflict detection) requires no Ollama. Indexing, lifecycle management, and the approval workflow function independently of model availability.

---

# 11. Current State

Bag of Holding is an operational system through Phase 19, handling structured document corpora with full lifecycle governance, deterministic canon resolution, multi-mode Atlas visualization, Ollama integration, explicit approval workflow with signed provenance artifacts, a certification validation layer, and a PCDS PlaneCard substrate.

It runs without cloud dependency, infrastructure overhead, or external services.

| Phase Range | Focus |
|------------|-------|
| 1–11 | Core workbench: ingestion, lifecycle, canon, conflicts, FTS5, Atlas, Daenary, LLM |
| 12 | Lifecycle undo/backward, auto-index, LLM review queue, Ollama hardening, status API |
| 13 | Multi-format ingestion, folder picker, Atlas physics, edge visual strands |
| 14 | Authority state machine, metadata contract, two intake lanes |
| 15 | Explicit approval workflow, signed provenance artifacts, governance UI |
| 16–18 | Multi-mode visualization (Evidence State, Risk Map, Authority Path), Projection Manifests, certification layer, Resolution Center consolidation |
| **19** | **PlaneCard / PCDS layer, Domains panel, CA Explorer integration, full epistemic stack** |

---

# 12. Why This Matters

This project reflects a specific approach to systems design: governance first, authority explicit, and failure modes made visible before they become operational incidents.

Most knowledge tooling is built for convenience. Bag of Holding is built for environments where convenience is the wrong optimization — where a decision canonized prematurely, or an LLM output applied without review, can produce real downstream harm.

The architecture is intentional. It is not the fastest path to a working demo. It is the right path to a trustworthy system.

The multi-mode visualization is not cosmetic variety. Each mode surfaces a different class of epistemic risk: relational topology (Web), measurement and confidence gaps (Evidence State), viability and intervention priority (Risk Map), and governance pipeline blockage (Authority Path). A system that can only show you what is connected cannot tell you whether what is connected is trustworthy.

The PCDS layer is not metadata enrichment. It is the structural commitment that every document's epistemic position — not just its existence — is a first-class object in the system. Documents are not records that happen to have coordinates. They are epistemic objects that happen to have content.

---

# 13. Conclusion

Most systems optimize convenience.

Few optimize continuity.

Bag of Holding is built for continuity.

The authority layer established what states exist and what transitions are legal. The authority transfer mechanism provided the signed, auditable pathway. The certification layer extended this into full transition validation. The PCDS layer extended this further into epistemic object representation.

Each phase added not features, but defenses — additional surfaces where the system can be asked to account for itself and can answer.

That is the distinction between a system that stores knowledge and a system that can defend truth.

Organizations do not lose knowledge because people fail to document. They lose knowledge because systems fail to preserve authority.

The future of trustworthy AI is not better prompts. It is better architecture.

Systems fail where memory becomes folklore.

Bag of Holding exists to prevent that.

---

*Local-first · SQLite + Markdown · No cloud dependency*  
*Source: github.com/ppeck1/Bag-of-Holding*

