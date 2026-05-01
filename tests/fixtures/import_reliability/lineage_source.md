---
boh:
  id: fixture-lineage-source-001
  type: reference
  purpose: "Lineage source fixture — parent document for Phase 26.2 lineage verification"
  status: draft
  version: "1.0.0"
  updated: "2026-04-29T00:00:00Z"
  project: "BOH Import Verification"
  topics:
    - lineage
    - parent document
    - source relationship
  rubrix:
    operator_state: observe
    operator_intent: capture
---

# Lineage Source Document

This is the **source** (parent) document in a lineage relationship test.

## Purpose

Verify that BOH correctly records and displays lineage relationships between documents. This document should appear as a **parent** (or "source of") `lineage_child.md`.

## Content

This document establishes the canonical definition of the following concept:

LINEAGE_SOURCE: The originating document in a document-to-document relationship. Related child documents derive from, reference, or supersede this source.

## Expected Lineage

After import and lineage seeding:
- This document (`lineage_source.md`) should appear as the source
- `lineage_child.md` should appear as a derivative
- The relationship type should be `derived_from`
- Both documents should show the relationship in their detail panels

## Test Criteria

- lineage_source.md is indexed: ✓ (if you can read this, it was)
- doc_id: fixture-lineage-source-001
- relationship to child: derives_from (child derives from this source)
