# Planar Gate And Correction Ledger

The Planar Gate evaluates whether a context pack contains the expected evidence
planes for an operation. It returns deterministic posture information such as
allowed, warning, or blocked, with reasons.

The correction ledger records advisory correction proposals and review outcomes.
It does not silently rewrite gate rules or canonical facts.

## Design Rules

- Gate decisions are explainable and fail closed where required evidence is
  missing.
- LLM-generated corrections remain proposals.
- Operator review is required before governance state changes.
- Ledger records preserve provenance for later audit.
