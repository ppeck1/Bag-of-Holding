---
boh:
  id: fixture-llm-known-good-001
  type: reference
  purpose: "LLM analysis known-good fixture for Phase 26.2 verification"
  status: draft
  version: "1.0.0"
  updated: "2026-04-29T00:00:00Z"
  project: "BOH Import Verification"
  topics:
    - ai analysis
    - review artifact
    - deterministic extraction
  rubrix:
    operator_state: observe
    operator_intent: capture
---

# LLM Analysis Test Document

This document is the reference fixture for Phase 26.2 AI Analysis (formerly "LLM Review Artifact") verification.

## Important Clarification

The BOH "AI Analysis" feature does **not** require Ollama to be running. It is a **deterministic extraction** pipeline:

1. Extracts headings as topics
2. Extracts `TERM: definition` patterns as definitions
3. Detects suspected conflicts with existing definitions in the database
4. Suggests metadata patches for missing fields (e.g., version, topics)
5. Computes a normalization hash

No LLM inference is called. The analysis works offline.

## Definitions

**Ai Analysis**: The BOH deterministic document extraction pipeline. Extracts topics, definitions, variables, and conflict candidates from a document without LLM inference.

**Review Artifact**: The output of the AI Analysis pipeline. A non-authoritative JSON record containing extracted metadata, conflict candidates, and suggested patches.

**Deterministic Extraction**: Analysis that produces the same output for the same input, regardless of when or how many times it runs. No probabilistic inference involved.

## Expected Analysis Output

When this document is analyzed, the AI Analysis pipeline should return:

- `extracted_topics`: headings from this document
- `extracted_definitions`: AI_ANALYSIS, REVIEW_ARTIFACT, DETERMINISTIC_EXTRACTION
- `suspected_conflicts`: empty (no conflicts in fresh database)
- `recommended_metadata_patch`: empty (frontmatter is complete)
- `non_authoritative`: true
- `requires_explicit_confirmation`: true

## Test Success Criteria

- `/api/review/{path}` returns 200 with content
- `extracted_topics` is non-empty
- `extracted_definitions` contains at least one entry
- `non_authoritative` is `true`
- No Ollama or network connection required
