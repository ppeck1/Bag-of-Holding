# SC3_CONSTITUTIVE_MAPPING.md
# SC3 Substrate Lattice — Constitutive vs. Descriptive Zone Mapping

**Phase 26C — Substrate Lattice Closure Decision**
**Status: Architectural decision. Not subject to revision without legitimacy re-proof.**

---

## The Decision

Phase 26C mandates a single architectural resolution:

> **If substrate registration does not change behavior → it is documentation.**
> **If substrate registration changes constitutive boundaries → it is infrastructure.**
>
> **Choose. No middle ground.**

This document records the choice.

**SC3 is infrastructure at constitutive boundaries.**
**SC3 is orientation at descriptive zones.**

Both can be true simultaneously. Only the zone determines which applies.

---

## The Equation

```
X_{t+1} = Π_K(F(X_t))

Where:
    X  = state vector across 3 planes (Physical, Informational, Subjective)
    K  = constraint set (Π_K projects X into the feasible region)
    F  = update function (transitions the state)
```

This equation governs all constitutive state transitions.
At constitutive boundaries, BOH enforces: the K constraint (plane hierarchy) gates whether F can produce a legitimate X transition.

---

## SC3 Coordinate System

The nine core coordinates (3×3 grid):

| Layer | Physical (P) | Informational (I) | Subjective (S) |
|-------|-------------|-------------------|----------------|
| **Constraint (K)** | K.P | K.I | K.S |
| **State (X)** | X.P | X.I | X.S |
| **Dynamic (F)** | F.P | F.I | F.S |

Additional structures:
- **CPL** — Coupling map: inter-coordinate dependencies
- **PROJ** — Projection operator: what is observable as canonical
- **OBS** — Observation model: what an external observer can access

---

## Epistemic Plane Hierarchy

This hierarchy is **constitutive** — it changes system behavior at canonical boundaries.

| Plane | Rank | Epistemic Authority | Examples |
|-------|------|--------------------|----|
| Physical | 3 (highest) | Empirical, sensor, measurement | Sensor readings, clinical measurements, physical observations |
| Informational | 2 | Structured knowledge, policy | Policy documents, codified procedures, verified facts |
| Subjective | 1 (lowest) | Interpretation, inference, synthesis | LLM synthesis, opinion, inference, draft |

### Mutation Rules (Enforced at Canonical Promotion Gate)

| Source → Target | Permitted | SC3 Response |
|----------------|-----------|-------------|
| Physical → Physical | ✅ Yes | SC3 passes; normal governance applies |
| Physical → Informational | ✅ Yes | SC3 passes; normal governance applies |
| Physical → Subjective | ✅ Yes | SC3 passes (downgrade path); normal governance applies |
| Informational → Informational | ✅ Yes | SC3 passes; normal governance applies |
| Informational → Subjective | ✅ Yes | SC3 passes (downgrade path); normal governance applies |
| Informational → Physical | ❌ No | BLOCKED — custodian review required |
| Subjective → Subjective | ✅ Yes | SC3 passes; normal governance applies |
| Subjective → Informational | ❌ No | BLOCKED — custodian review required |
| Subjective → Physical | ❌ No | BLOCKED — critical severity, Physical Canon Custodian required |

**Downgrade path note:** A physical document can be classified into an informational or subjective canon — but the normal approval governance still applies. SC3 only blocks upward-plane promotion without appropriate authority.

---

## Constitutive Zone Mapping

At these zones, SC3 registration **must change system behavior**.

| Zone | SC3 Coordinates | Enforcement |
|------|----------------|-------------|
| **Canonical promotion** | K.P, K.I, K.S (plane constraint on X transition) | Plane mismatch blocks promotion; violation recorded |
| **Authority resolution** | K.I (informational constraint: who may act) | SC3 plane of node informs scope of authority contract |
| **Custodianship transfer** | F.P, F.I, F.S (dynamic: who performs the transfer) | Transfer authority must match target plane rank |
| **Scope legitimacy** | K.P, K.I, K.S (constraint layer per plane) | Scope boundaries are plane-specific |
| **Temporal enforcement** | X.P, X.I, X.S (state: validity window per plane) | Validity expiry is constitutive, not advisory |
| **Canonical lock** | PROJ (projection: what is visible as canon) | Lock gates the PROJ operator |
| **Governance acceptance** | F.I, CPL (dynamic + coupling) | Acceptance requires informational-plane authority at minimum |
| **Irreversible memory** | PROJ, OBS (projection + observation) | Once projected as canonical, requires custodian to undo |

### What "Must Change Behavior" Means

For each constitutive zone:

- **Canonical promotion:** If `sc3_plane(source) < sc3_plane(target_canon)`, the promotion is **blocked**, not just flagged. The violation is recorded in `sc3_violations` table.
- **Authority resolution:** The authority contract considers the plane of the node being resolved; subjective-plane nodes may require lower authority to modify but higher authority to promote.
- **Canonical lock:** When `PROJ` is locked (canonical lock active), no X state transition is permitted regardless of other authority.

---

## Descriptive Zone Mapping

At these zones, SC3 registration provides **orientation only**. No enforcement.

| Zone | SC3 Role | Effect |
|------|----------|--------|
| **Drafts** | X.S (subjective state) | Orientation: where in the knowledge space this draft lives |
| **Notes / exploration** | X.S, X.I | Mapping: consistency checking, no governance block |
| **LLM synthesis** | X.S (subjective — always) | LLM output is permanently subjective plane; orientation only |
| **Speculative mapping** | X.S, CPL | Consistency guidance; no enforcement |
| **Temporary inference** | X.S | Labeled as subjective; no canonical weight |
| **Research scaffolding** | X.I (if structured), X.S (if exploratory) | Classification; no governance gate |

**Key property:** No failure at a descriptive zone blocks the action.
SC3 at descriptive zones is used for:
- Orienting new content in the knowledge space
- Consistency checking between related nodes
- Reasoning support for LLM synthesis
- Audit trail of subjective-plane activity

**Descriptive zones must remain fast.** No governance friction.

---

## Projection Enforcement

The PROJ operator governs what is visible as canonical.

```
PROJ: X_full → X_observable
```

At canonical boundaries:
- A canonical lock = PROJ is suspended for that node. No state change is visible as canonical until the lock is released.
- A plane mismatch = PROJ cannot incorporate the source into the target canon plane.

This means: **even if a document exists in the system, it is not projected as canonical unless it has passed the SC3 plane gate and the full authority chain.**

---

## Plane Inference Rules

BOH infers the SC3 plane of a node from its metadata, in priority order:

1. **Explicit `sc3_plane` field** in metadata (highest priority)
2. **`plane_scope` or `plane_path` field** — if contains "physical", "informational", or "subjective"
3. **`source_type` mapping:**

| source_type | Plane |
|-------------|-------|
| sensor, measurement, observation, physical_record | physical |
| canon_folder, policy, rule, structured_knowledge | informational |
| llm_synthesis, inference, interpretation, opinion, draft | subjective |

4. **`corpus_class` / `document_class` heuristic:**

| corpus_class pattern | Plane |
|---------------------|-------|
| "physical", "sensor" | physical |
| "llm", "synthetic", "draft" | subjective |
| "canon", "policy" | informational |

5. **Default:** informational

---

## Legitimacy Boundaries

SC3 becomes the architectural legitimacy boundary when:

1. A promotion attempt carries a plane mismatch
2. A lock state prevents PROJ from incorporating the source
3. A scope authority is plane-specific (physical scope authority ≠ subjective scope authority)
4. A temporal validity is tied to the epistemic plane of the claiming actor

At these points: **SC3 registration is not documentation. It is the gate.**

---

## Ontology Drift Prevention

SC3 uses **no new ontological tokens**.

The validation test (Phase 25, Fix H) demonstrated that:
- Musical sections, cell lifecycles, and Roman Empire periodization
- Can all be mapped using the existing 9 coordinates + CPL + PROJ + OBS
- Without requiring new tokens, new coordinate systems, or new ontologies

**If SC3 requires a new token to describe a new domain, SC3 has failed.**

The substrate is general. New domains add registrations, not new coordinates.

---

## BOH → SC3 Coordinate Map

| BOH Concept | SC3 Coordinate | Role |
|------------|---------------|------|
| Governance rules, scope limits | `SC3.K.*` | Constraint layer — what is permitted |
| Daenary custodian state | `SC3.X.*` | State layer — current truth state |
| Escalation / custodian actions | `SC3.F.*` | Dynamic layer — how state transitions occur |
| Integrity panel, Atlas visualization | `SC3.OBS` | Observation model — what is visible |
| Canonical lock (projection gate) | `SC3.PROJ` | Projection operator — what is canonical |
| Cross-plane dependencies | `SC3.CPL` | Coupling map — inter-coordinate relationships |

---

## API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /api/authority/sc3/check` | Check if action is constitutive or descriptive |
| `POST /api/authority/sc3/promotion-gate` | Apply SC3 plane enforcement to canonical promotion |
| `POST /api/authority/sc3/infer-plane` | Infer epistemic plane from node metadata |
| `GET /api/authority/sc3/violations` | Audit trail of SC3 constitutive violations |
| `GET /api/authority/sc3/mapping` | Full machine-readable constitutive/descriptive map |

---

## Summary: The Closure

**SC3³ is the substrate, not a parallel ontology.**

The closure decision:
- SC3 registration **changes behavior** at constitutive boundaries (canonical promotion, authority resolution, lock state, scope legitimacy)
- SC3 registration provides **orientation** at descriptive zones (drafts, notes, LLM synthesis, exploration)
- Both are true simultaneously
- The zone (constitutive vs. descriptive) determines which applies

**This resolves the ambiguity. Architecture fracture is prevented.**

---

*SC3_CONSTITUTIVE_MAPPING.md — Phase 26C*
*Implementation: `app/core/sc3_constitutive.py`*
*Tests: `tests/test_phase26a_authority_proof.py` (26A-8, 26A-12)*
