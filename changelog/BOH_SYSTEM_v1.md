# BOH_SYSTEM_v1.md
# Bag of Holding — Canonical Operating Doctrine

**Version: 1.0**
**Authority: Phase 26B**
**Status: Authoritative**

This is not a patch note. This is not a historical fragment. This is not implementation memory.

This is what BOH is.

---

## What is BOH?

**Bag of Holding is canonical governance infrastructure.**

It is not a PKM (personal knowledge management) tool.
It is not a document database.
It is not a search engine with governance features.

It is a system that makes canonical truth:

- **structurally enforceable** — wrong actors cannot mutate it
- **explicitly auditable** — every governance event is permanent
- **legibly explainable** — every block produces a human-readable explanation
- **epistemically grounded** — truth is typed by its plane of origin (SC3)

The product is not governance alone. The product is not freedom alone.

The product is the balance:

> **Exploration is cheap. Truth is expensive. That is the product.**

---

## Core Distinction: Constitutive vs. Descriptive

### Constitutive Zones

These are **trust boundaries**.

They define what becomes trusted.

They are **machine-enforced, not advisory**.

BOH applies constitutive enforcement to:

| Action | Why Constitutive |
|--------|-----------------|
| Canonical promotion | Truth state change — must be authorized |
| Authority resolution | Who may mutate — must be verified |
| Custodianship transfer | Custody handoff — requires signed lineage |
| Scope legitimacy | Boundary enforcement — prevents cross-scope mutation |
| Temporal validity enforcement | Stale authority = blocked mutation |
| Forced escalation | Authority transfer — permanent governance event |
| Canonical lock state | Mutation suspension — lasts until resolved |
| Governance acceptance | Irreversible institutional memory |

**No administrative bypass. No override path. No advisory mode.**

### Descriptive Zones

These are **working surfaces**.

They support thinking, exploration, drafting, and ambiguity.

They are **fast** — no bureaucratic overhead.

BOH applies descriptive treatment to:

| Zone | Why Descriptive |
|------|----------------|
| Drafts | Not yet claimed as truth |
| Notes | Exploration, not assertion |
| LLM synthesis | Subjective plane — orientation only |
| Speculative mapping | Temporary inference |
| Exploration branches | Working surface |
| Research scaffolding | Pre-canonical |

**Exploration must remain fast. No governance friction here.**

---

## What May Mutate Truth?

### The Authority Chain

Canonical truth may only be mutated by actors who satisfy ALL of:

1. **Identity** — declared resolver ID matches (if resolver-specific contract exists)
2. **Team** — actor belongs to the required authority domain
3. **Role** — actor holds the required governance role
4. **Scope** — actor's authority covers this node's scope boundary
5. **Temporal validity** — authority window has not expired
6. **SC3 plane** — source document has sufficient epistemic rank for target canon

All dimensions must pass simultaneously.
Failing one dimension blocks the action.
Every failure is a permanent governance event.

### What Cannot Mutate Truth

- Actors with wrong identity, team, role, or scope
- Autonomous actors (LLM, system, auto) — cannot approve promotions
- Self-promotion (identity cannot expand its own authority)
- Synthetic resolver claims (forged actor_id alone is insufficient)
- Subjective-plane evidence overwriting physical or informational canon (SC3 rule)
- Actors during forced escalation (authority has been transferred)
- Actions against canonical-locked nodes (lock must be resolved first)

---

## How Escalation Works

### Escalation Ladder

```
LOW → MODERATE → HIGH → PERSISTENT_HIGH
         ↓
     Forced Escalation
         ↓
   Authority Transfer to Supervisor
```

| Level | Trigger | Effect |
|-------|---------|--------|
| WARNING | First drift signal | Governance notification |
| CONTAIN | Active boundary breach | Canonical lock imposed |
| FORCED ESCALATION | Persistent unresolved HIGH | Authority transferred to supervisor |

### Authority Transfer Model

When forced escalation fires:
- The original resolver loses standing for this node
- Authority is transferred to the registered supervisor
- The transfer is signed and recorded (irreversible governance event)
- The node remains locked until the supervisor resolves or explicitly releases

**The original resolver cannot bypass forced escalation by re-attempting.**

---

## How Daenary Relates to Rubrix

**Daenary** is the custodian state machine.
**Rubrix** is the governance workflow engine.

Their relationship:

```
Rubrix (governance workflow)
    → generates open items and resolution decisions
    → routes authority through the escalation ladder
    → approves promotions through the approval chain

Daenary (custodian state)
    → gates canonical mutations based on current state
    → enforces canonical locks (prevents bypass during escalation)
    → binds SC3 plane validity to mutation permission
    → is consulted at every authority-gated resolve
```

**Daenary state → legitimacy → mutation permission.**

An actor may have valid authority (Rubrix says yes) but still be blocked by Daenary state.
Both gates must pass for a canonical mutation to succeed.

This is intentional. Authority is necessary but not sufficient.

---

## How Atlas Relates

**Atlas** is the visibility surface, not the authority surface.

Atlas provides:
- Visual representation of the canonical state of all nodes
- Plane-aware graph visualization (physical / informational / subjective)
- Coherence and drift indicators
- Governance event overlay

Atlas does NOT:
- Grant or deny authority
- Create canonical locks
- Change node state
- Resolve governance events

**Atlas = visibility. Authority guard = mutation control. These are separate concerns.**

---

## How SC3 Maps

SC3³ (Scalar-3³ Substrate Lattice) is the domain-general persistence coordinate system.

The BOH → SC3 mapping:

| BOH Concept | SC3 Coordinate |
|------------|---------------|
| Governance rules, scope limits | `SC3.K.*` (Constraint layer) |
| Daenary state, canonical lock | `SC3.X.*` (State layer) |
| Escalation / custodian actions | `SC3.F.*` (Dynamic layer) |
| Integrity panel, Atlas | `SC3.OBS` (Observation model) |
| Canonical lock (what is visible as canon) | `SC3.PROJ` (Projection operator) |

### SC3 is Not an Ontology Split

SC3 does not create a parallel ontology.
SC3 maps existing BOH concepts to a domain-general coordinate system.

This enables:
- Comparison across domains without new tokens
- Mathematical formalization of state transitions: `X_{t+1} = Π_K(F(X_t))`
- Epistemic plane enforcement at constitutive boundaries

### SC3 Plane Authority (Phase 26C)

SC3 planes carry epistemic authority:

| Plane | Rank | Examples |
|-------|------|---------|
| Physical | 3 (highest) | Sensor data, measurement, empirical observation |
| Informational | 2 | Structured knowledge, policy, codified facts |
| Subjective | 1 (lowest) | Interpretation, inference, LLM synthesis, opinion |

**Constitutive rule:** Lower-rank planes cannot directly overwrite higher-rank canon.

This is enforced at the canonical promotion gate — not advisory.

---

## What is the Actual Product?

**BOH is canonical governance infrastructure.**

Specifically, BOH is the infrastructure layer that answers:

> *Given that multiple actors produce conflicting knowledge about the same domain — which version is canonical, who may change that determination, and what happens when the wrong actor tries?*

BOH makes that answer:
- **Deterministic** — not probabilistic
- **Auditable** — every decision is permanently recorded
- **Explainable** — every block produces a human-readable explanation
- **Bypassable? No.** — wrong actors are structurally blocked

### Use Cases

| Use Case | How BOH Governs It |
|----------|-------------------|
| Clinical knowledge management | Clinical authority chain, scope-limited custodians |
| Infrastructure policy | Infrastructure team authority domain |
| Research corpus management | SC3 plane enforcement (physical evidence > LLM synthesis) |
| Multi-team knowledge bases | Cross-scope legitimacy enforcement |
| Regulatory documentation | Canonical lock + provenance chain |
| Enterprise knowledge governance | Forced escalation + authority audit |

### Not Use Cases

| Not This | Why |
|----------|-----|
| Personal note-taking (Notion, Obsidian competitor) | BOH is for multi-actor governance, not personal memory |
| Search engine | Canon resolution is governance, not retrieval |
| LLM wrapper | LLM synthesis is subjective plane — cannot directly become canon |
| Database ORM | BOH is above the database layer |

---

## The Trust Promise

A user who encounters a node marked **canonical** in BOH can trust:

1. It was promoted through an explicit approval chain (not auto-promoted)
2. The promoting actor had verified authority (identity, team, role, scope)
3. The source document had sufficient epistemic plane authority for the target canon
4. No unauthorized actor mutated it (all attempts are blocked and recorded)
5. If anything tried to bypass this, it failed and is permanently logged

**This is the promise. It is architectural. Not policy. Not advisory.**

---

## Governance Legibility

Every blocked action must answer:

| Question | Answer |
|----------|--------|
| Why was this blocked? | Specific failure dimension (resolver / team / role / scope / SC3 plane) |
| Who must resolve it? | Named resolver or authority domain |
| What is the escalation state? | warning / contain / forced escalation / locked |
| What happens next? | Concrete path forward |
| Why can I not override it? | Machine truth explanation, not policy language |

This is not UX nicety. This is commercialization.

**Trust must be explainable or it is not trusted.**

---

## System Boundaries

### What BOH Controls

- Canonical state of documents and facts
- Authority chain for canonical mutations
- Audit log of every governance event
- SC3 plane enforcement at constitutive boundaries
- Escalation ladder and authority transfer

### What BOH Does Not Control

- File storage (local filesystem)
- Network access (local-first by design)
- LLM inference (Ollama integration is advisory, not constitutive)
- User authentication (assumed to be handled externally)

---

## Architectural Invariants

These cannot change without re-establishing the legitimacy proof:

1. **No silent bypass.** Every failed authority attempt is recorded.
2. **No administrative override path.** If governance blocks it, the block holds.
3. **Autonomous actors cannot promote.** `approved_by='llm'` is always rejected.
4. **Self-promotion is illegal.** An actor cannot expand its own authority.
5. **SC3 plane hierarchy is enforced at canonical promotion.** Not advisory.
6. **Canonical locks persist.** They are not cleared by time or pressure.
7. **Audit is append-only.** Governance events are permanent.
8. **Every rejection produces a legible explanation.** Not "access denied."

---

*This document is the canonical operating doctrine for Bag of Holding v1.*
*It supersedes all patch notes, implementation fragments, and historical descriptions.*
*When there is conflict between this document and any other, this document is authoritative.*

**BOH_SYSTEM_v1.md — Phase 26B**
