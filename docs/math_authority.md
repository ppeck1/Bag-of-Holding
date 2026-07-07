# Authority And Scoring Notes

This document summarizes the deterministic scoring surfaces referenced by the
code. Code remains the executable source of truth.

## Canon Score

Canon scoring combines document metadata, lifecycle state, authority state,
topic evidence, and conflict pressure into a deterministic ranking. The same
database state should produce the same score without model involvement.

## Search Score

Search combines:

- FTS or lexical relevance
- document authority and lifecycle signals
- conflict penalties
- metadata filters
- bounded context size

The ranking is advisory. It does not promote documents or change canonical
state.

## Fold Metrics

Fold metrics project persisted document state into visual dimensions such as:

- authority score
- freshness score
- conflict pressure
- canon readiness
- currentness label

Unknown or missing values should remain explicit rather than being silently
normalized into confidence.

## Planar Metrics

PlaneCard and Planar Gate logic use deterministic variables to expose evidence,
subjective interpretation, internal state, review state, canonical state,
conflict state, and archive state. These variables are inspection signals, not
automatic governance actions.
