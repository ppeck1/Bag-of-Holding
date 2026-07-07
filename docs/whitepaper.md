# Bag of Holding Whitepaper

Bag of Holding is a local-first knowledge workbench for durable reasoning. Its
central design claim is that a useful knowledge system must preserve provenance,
separate proposal from authority, and make drift visible before it becomes
operational truth.

## Doctrine

LLM proposes. Human governs. System audits.

This means model-generated classifications, summaries, duplicate detections, and
conflict notices are advisory until an operator accepts them through governed
workflow. BOH preserves the proposal trail so later readers can distinguish
source material, derived interpretation, and canonical decisions.

## Architecture Shape

- FastAPI backend with SQLite persistence.
- Server-owned library root enforced by filesystem boundary helpers.
- Governed UI served at `/`, with `/v2/` as a compatibility alias.
- Read-only retrieval context packs separated from operator mutations.
- PlaneCards and Fold views for inspecting documents across authority,
  evidence, freshness, and risk dimensions.
- Append-only audit and lifecycle history where implemented.

## Publication Boundary

The public repository contains source, tests, screenshots, and public
documentation. Runtime corpus data, local databases, quarantine files, secrets,
and operator handoff notes are excluded from publication.
