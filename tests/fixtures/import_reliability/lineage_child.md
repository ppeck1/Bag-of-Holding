---
boh:
  id: fixture-lineage-child-001
  type: reference
  purpose: "Lineage child fixture — derived document for Phase 26.2 lineage verification"
  status: draft
  version: "1.0.0"
  updated: "2026-04-29T00:00:00Z"
  project: "BOH Import Verification"
  topics:
    - lineage
    - child document
    - derived relationship
  lineage:
    - relationship: derived_from
      source_doc_id: fixture-lineage-source-001
      source_path: lineage_source.md
      relationship_strength: 0.9
      notes: "Extends the source document with additional detail"
  rubrix:
    operator_state: observe
    operator_intent: capture
---

# Lineage Child Document

This is the **child** (derived) document in a lineage relationship test.

## Purpose

Verify that BOH correctly records and displays lineage relationships. This document **derives from** `lineage_source.md`.

## Content

This document extends the source definition:

LINEAGE_CHILD: A document that derives from, references, or supersedes a source document. The relationship is recorded in BOH's lineage table and should be visible in the document detail panel under "Lineage."

## Expected Lineage Display

In the document detail panel:
- **Lineage section** should show: "Derives from: Lineage Source Document"
- The relationship type should be `derived_from`
- A link to the parent document should be visible

## Test Criteria

- lineage_child.md is indexed: ✓
- doc_id: fixture-lineage-child-001
- parent: fixture-lineage-source-001
- relationship: derived_from
