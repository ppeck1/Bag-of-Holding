# BOH and Agicore: Constraint Boundaries at Different Layers

BOH and Agicore share a core invariant:

LLMs may propose, but deterministic systems must govern execution, promotion, and audit.

BOH currently enforces this at the application/workbench layer:
- local-first document corpus
- append-only lifecycle history
- review-safe LLM proposals
- canon resolution
- authority transitions
- provenance and lineage

Agicore explores a related idea at the DSL/compiler layer:
- AI at build time
- deterministic runtime
- typed declarations
- generated tests
- governance primitives
- audit-oriented system generation

The useful distinction:

BOH governs knowledge state after ingestion.
Agicore governs generated system structure before runtime.

Possible future bridge:

Rubrix lifecycle could be expressed as a declarative lifecycle primitive:

observe -> vessel -> constraint -> integrate -> release

Important:
Do not claim BOH is Agicore-compatible.
Do not add Agicore as a dependency.
Do not pivot BOH toward Agicore.
This is related-work positioning only.
