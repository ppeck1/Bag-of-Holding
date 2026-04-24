# Bag of Holding

## A Constraint-Governed Local Knowledge Workbench for Persistent Human–LLM Reasoning

### Canonical Memory · Atlas Visualization · Auditability · Sovereign Knowledge Systems

---

# Executive Summary

Most knowledge systems optimize retrieval.

Very few optimize survivability.

Modern work produces enormous amounts of information — documents, notes, decisions, conversations, policies, and fragmented institutional memory. Most of it becomes operational sediment: searchable, but structurally unstable. Context is lost, reasoning decays, and organizations repeatedly rebuild conclusions they have already paid to reach.

Large language models improved retrieval but worsened this problem in a different way. They generate useful answers while preserving almost none of the reasoning substrate that produced them. Conversations become intelligence without continuity.

Bag of Holding exists to solve that failure.

Bag of Holding is a local-first, constraint-governed knowledge workbench designed for persistent reasoning, canonical document stewardship, and auditable human–LLM collaboration. It is not a note-taking application, a vector database wrapper, or a chatbot with memory. It is an operational substrate for maintaining knowledge integrity across time, users, and changing model layers.

The system combines durable Markdown-based knowledge structures, SQLite-backed state management, graph-based relationship modeling, Atlas visualization, and constrained LLM integration through governed inlet and outlet filters. Knowledge is not merely stored — it is normalized, classified, versioned, linked, and verified.

Every document carries lineage. Every learning event carries provenance. Every canonical artifact survives model replacement.

The objective is simple: preserve reasoning, not just information.

Bag of Holding is designed for environments where trust, traceability, and knowledge continuity matter more than convenience: healthcare operations, clinical informatics, consulting, research systems, governance-heavy enterprises, and technical architecture work.

Systems fail where memory becomes folklore.

Bag of Holding exists to prevent that.

---

# 1. The Problem

Organizations do not fail because they lack information.

They fail because they lose structure.

Most operational environments already contain enough knowledge to solve their problems. The failure occurs in translation: fragmented documentation, undocumented decisions, inconsistent ownership, disappearing institutional memory, and invisible assumptions carried only by specific people.

The result is familiar:

- Teams rebuild decisions that were already made
- Policy becomes dependent on tribal memory
- Critical workflows degrade when key people leave
- Compliance becomes reconstruction instead of verification
- Strategic reasoning collapses into disconnected artifacts

A concrete example makes this tangible. A clinical team makes a triage escalation decision in March. The rationale is clear to the people in the room. Six months later, that decision needs to be audited — a near-miss event, a regulatory review, a new team member who needs to understand the constraint. In most systems, the rationale is gone. What survives is the conclusion, stripped of the reasoning that produced it. Reconstructing that reasoning requires finding the right people, hoping their memory is accurate, and accepting that the record will be incomplete.

In Bag of Holding, that March decision is a governed document: its reasoning is preserved, its status is traceable, its relationship to downstream policies is explicit, and the audit trail is intact. Nothing requires reconstruction because nothing was allowed to decay.

Traditional tools address storage, but not stewardship.

**Notes applications** like Obsidian preserve files well, but governance is largely manual. Relationships, authority, and canonical status are optional rather than structural.

**Notebook systems** like Jupyter preserve execution, but not organizational reasoning. They are excellent for experiments and poor for durable decision architecture.

**Retrieval-augmented generation** improves retrieval speed but does not solve persistence. Retrieved fragments are useful in the moment but disappear immediately afterward. Most RAG systems retrieve knowledge without improving the underlying structure.

**LLM chat interfaces** produce answers without preserving formal reasoning paths. They optimize response quality, not institutional continuity. This creates a dangerous illusion: intelligence appears present while structural memory continues to decay.

Bag of Holding addresses this by treating knowledge architecture — not retrieval speed — as the primary problem.

---

# 2. Design Philosophy

The system is built around one principle: constraint first, not feature first.

Truth is not what is stored. Truth is what survives constraint. Persistence without governance produces noise, not knowledge. Durable systems require explicit structure for what becomes canonical, what remains provisional, and what must be archived.

This produces four commitments that govern every design decision.

**Canonical status must be earned.** Not every document should become authoritative. Drafts, notes, imported artifacts, and exploratory thinking remain valuable, but they are not equal to validated reference material. The system enforces this distinction structurally, not by convention.

**Knowledge must be traceable.** Every artifact should answer: where did this come from, what replaced it, what depends on it, who changed it, and why? This is more important than confidence scoring alone. Lineage before confidence.

**Archives are active infrastructure.** Most systems treat archives as dead storage. Bag of Holding treats archive state as preserved context, historical reasoning, and explicit supersession. Old knowledge should not disappear — it should become properly positioned.

**Operator intent is explicit.** Every interaction exists inside a declared operational state. The system tracks whether the operator is observing, capturing, constraining, or canonicalizing. This prevents ambiguity between exploration and authority.

---

# 3. System Architecture

Bag of Holding is built as a local knowledge operating system rather than a single application. Its architecture prioritizes durability, auditability, and model independence.

## Ingestion Layer

Responsible for controlled intake of external material: PDFs, Markdown, HTML, research notes, project documents, policy artifacts, and imported legacy systems. The goal is not immediate indexing, but governed entry.

## Normalization Layer

Raw input is transformed into durable, machine-readable structure through frontmatter standardization, formatting normalization, duplicate identification, metadata extraction, and schema alignment. This prevents ingestion entropy.

## Canonicalization Layer

Documents are classified by operational role: reference, note, draft, canonical, or archive. Canonical outputs become governed system artifacts. Achieving canonical status requires explicit review and designation — it cannot be automated.

## State Engine

SQLite functions as the local governed state engine. It stores registry metadata, document coordinates, graph relationships, lifecycle states, lineage references, verification queues, and audit trails. Durability matters more than novelty. The current version is designed for single-operator local-first use; multi-user stewardship is on the roadmap.

## Graph Relationship Layer

Knowledge is not flat. Documents, concepts, decisions, and operational nodes require relational structure. Graph edges capture dependency, inheritance, contradiction, supersession, domain adjacency, and authority relationships. This supports reasoning rather than search alone.

## Atlas Visualization Layer

Atlas provides visible topology. Users can inspect system structure, conflict zones, dependency chains, orphaned knowledge, canonical pathways, and cross-domain relationships. Knowledge must be inspectable, not hidden. Atlas is observability infrastructure, not decoration.

## LLM Interface Layer

Large language models operate inside the system — not above it. They function as constrained operators rather than autonomous authorities. The architecture is intentionally model-agnostic, supporting Ollama, local GGUF models, OpenAI, Anthropic, Gemini, and future model layers. Knowledge survives model replacement. This is mandatory.

## Verification Layer

Human review remains mandatory for all authority transitions. The system does not outsource truth.

---

# 4. Knowledge Model

Bag of Holding uses intentionally simple durable substrates. Complexity belongs in structure, not storage dependencies.

## Markdown as Primary Substrate

Markdown is portable, inspectable, versionable, human-readable, and tool-independent. Knowledge should survive software changes. The system must outlive the interface.

## Frontmatter as Governance Layer

Each file carries structured frontmatter encoding identity, purpose, operational status, version, scope, topics, operator state, and lifecycle metadata. This creates durable machine readability without sacrificing direct human ownership.

```yaml
boh:
  id: unique-id-001
  type: canonical
  purpose: What this document governs
  status: canonical
  version: "1.2.0"
  updated: "2026-04-24T00:00:00Z"
  topics: [triage escalation, clinical workflow]
  rubrix:
    operator_state: release
    operator_intent: canonize
```

## Rubrix Lifecycle

Documents move through a governed operational progression:

```
observe → vessel → constraint → integrate → release
```

Each state carries explicit meaning. `observe` is intake. `vessel` is captured but not yet evaluated. `constraint` is under active review. `integrate` is ready for canonical promotion. `release` is canonical or archived. Every transition is recorded with timestamp, actor, direction, and reason.

Critically: lifecycle movement is reversible. A document can move backward through states. Undo is available. The history is append-only and never deleted. This means mistakes in governance are recoverable, not catastrophic.

## SQLite as State Authority

SQLite manages governed system state locally without infrastructure overhead. It handles canonical registry, duplicate resolution, lineage chains, verification status, and operational indexing. The database is the record of authority — not the files alone.

---

# 5. LLM Integration

Bag of Holding does not position the LLM as the system.

The LLM is an operator inside the system.

This distinction is critical and non-negotiable.

## Inlet Filter

Before a prompt reaches the model, the inlet filter retrieves relevant governed context from the knowledge graph: prior decisions, canonical references, active project state, linked constraints, operational definitions, and prior contradictions. The model receives structured context, not isolated prompts.

## Outlet Filter

After model response, the outlet filter evaluates output for learnable content: candidate facts, structural updates, new relationships, contradictions, unresolved ambiguities, and review requirements. High-confidence outputs do not automatically become truth. They become review candidates.

## Verification Queue

Authority requires confirmation. Ollama proposals and model outputs enter a review queue where the operator inspects each item and explicitly approves or rejects it. Approval applies only safe, non-canonical metadata fields. Canonical status cannot be granted from the queue. This is enforced at the data layer, not by convention.

This prevents hallucination becoming infrastructure.

## What the Model Cannot Do

These constraints are architectural, not advisory:

- The model cannot overwrite canonical documents
- The model cannot auto-promote documents to canonical status
- The model cannot bypass the verification queue
- No model output applies to the corpus without explicit operator action

The goal is a system where the LLM makes the operator faster, not one where the LLM makes decisions the operator later discovers.

---

# 6. Atlas Interface

Most knowledge systems fail because the structure is invisible.

Atlas solves that.

Lists and folders are insufficient for reasoning-heavy environments. Users need to see dependency chains, contradiction zones, hidden centrality, weakly governed clusters, and system fragmentation. Atlas provides graph-native visibility into all of it.

Nodes are colored by corpus class and sized by canon score. Red halos indicate conflicts. Amber halos indicate stale coordinates. Edges show lineage, derivation, and topic relationships. Hovering an edge reveals shared topics, edge type, and confidence. Hovering a node reveals title, status, and diagnostic indicators.

The interface supports zoom, pan, node drag, neighborhood expansion, fit-to-screen, and focus-on-selected. Performance presets allow the graph to run smoothly on ordinary hardware across corpora of hundreds of documents.

Atlas answers operational questions:

- What depends on this document?
- What conflicts with it?
- What is stale and may need re-evaluation?
- Where is authority weakly established?
- What would break if this were archived?

These are not questions that search engines answer. They require visible structure.

---

# 7. Comparison to Existing Systems

| System | Strength | Limitation relative to BOH |
|--------|----------|----------------------------|
| **Obsidian** | Local note ownership, linking | No canonical governance, no lineage enforcement, no operational authority |
| **Jupyter** | Computation and execution workflows | No durable institutional reasoning, no decision architecture |
| **LangChain / LlamaIndex** | Pipeline orchestration | Optimizes pipelines, not institutional memory |
| **Mem0 / Persistent AI Memory** | LLM continuity | Prioritizes personalization over formal knowledge governance |
| **Neo4j** | Graph construction | Focused on ingestion, not full lifecycle management |
| **Notovision** | Bidirectional filter architecture, persistent assistant memory | BOH extends further into canonical document stewardship, operational topology, and formal knowledge lifecycle governance |

The common thread: existing tools solve retrieval, continuity, or execution well. Few explicitly govern the full knowledge lifecycle from intake through canonical status through archive with an intact audit trail.

---

# 8. Use Cases

BOH is strongest in environments where decisions carry consequence and ambiguity has cost.

**Clinical informatics.** Healthcare systems depend on decisions surviving turnover. Triage protocols, workflow rationale, and policy constraints require auditability when something goes wrong. BOH preserves the reasoning behind governance decisions, not just the decisions themselves.

**Consulting and architecture review.** Complex advisory work regularly disappears into slide decks and call recordings. BOH preserves decision lineage and design rationale so that follow-on engagements begin from a documented position, not oral reconstruction.

**Policy and compliance.** Compliance increasingly requires tracing a decision back to its source authority, not reconstructing it from memory. BOH maintains source authority rather than reconstructed memory.

**Research systems.** Literature reviews, theory development, and formal research benefit from canonical persistence across a working corpus rather than scattered note accumulation with no explicit authority structure.

**Enterprise knowledge retention.** Institutional knowledge should not leave when individuals do. This is a structural problem, not a documentation problem. BOH provides the structural answer.

---

# 9. Current State and Roadmap

Bag of Holding is transitioning from prototype into operator-grade tooling.

The current implementation is a single-operator, local-first workbench. It handles corpora of hundreds of documents with full lifecycle governance, Atlas visualization, Ollama integration with review queue, and audit-safe mutation history. It runs without cloud dependency, infrastructure overhead, or external services.

**What is implemented:**

- Governed lifecycle transitions with reversible backward movement and append-only history
- Deterministic canon resolution and conflict detection
- Atlas force-directed graph with zoom, pan, drag, edge hover, and performance controls
- Ollama LLM integration with inlet/outlet filter and mandatory review queue
- Startup auto-indexing with hash-based change detection
- Full-text search with semantic state filters
- `/api/status` diagnostics and system health monitoring
- Audit log for every mutation

**Phase roadmap:**

| Phase | Focus |
|-------|-------|
| 1–12 | Core workbench: ingestion, lifecycle, canon, conflicts, Atlas, LLM governance *(complete)* |
| 13 | Multi-document reasoning chains, cross-document conflict resolution |
| 14 | Multi-user stewardship, role boundaries, shared canonical layers |
| 15 | MCP integrations, containerized deployment, enterprise partitioning |
| 16 | Operator-grade production hardening, long-term institutional deployment |

The current priority is not more features. It is proof through strong operational use cases.

---

# 10. Conclusion

Most systems optimize convenience.

Few optimize continuity.

Bag of Holding is built for continuity.

It preserves not only files, but authority. Not only retrieval, but reasoning. Not only memory, but survivable structure.

Large language models are powerful accelerators. Without governance, they become another layer of institutional forgetting — faster answers that leave the underlying structure weaker than before.

The future of trustworthy AI is not better prompts.

It is better architecture.

Organizations do not lose knowledge because people fail to document. They lose knowledge because systems fail to preserve authority.

Systems fail where memory becomes folklore.

Bag of Holding exists to prevent that.

---

*Local-first · SQLite + Markdown · No cloud dependency*  
*Source: github.com/ppeck1/Bag-of-Holding*
