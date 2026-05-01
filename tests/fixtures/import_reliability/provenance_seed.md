---
boh:
  id: fixture-provenance-seed-001
  type: reference
  purpose: "Provenance seed fixture — custody history test for Phase 26.2 verification"
  status: draft
  version: "1.2.0"
  updated: "2026-04-29T00:00:00Z"
  project: "BOH Import Verification"
  topics:
    - provenance
    - custody history
    - change tracking
  provenance:
    created_by: "test-author-alice"
    created_at: "2026-01-15T09:00:00Z"
    last_edited_by: "test-author-bob"
    last_edited_at: "2026-04-29T10:30:00Z"
    change_log:
      - version: "1.0.0"
        edited_by: "test-author-alice"
        edited_at: "2026-01-15T09:00:00Z"
        summary: "Initial creation"
      - version: "1.1.0"
        edited_by: "test-author-alice"
        edited_at: "2026-02-10T14:00:00Z"
        summary: "Added content section"
      - version: "1.2.0"
        edited_by: "test-author-bob"
        edited_at: "2026-04-29T10:30:00Z"
        summary: "Updated for Phase 26.2 verification"
    approval_certificates: []
    source_hash: "sha256-placeholder-for-testing"
  rubrix:
    operator_state: vessel
    operator_intent: define
---

# Provenance Seed Document

This document tests **provenance** (custody and change history) visibility in BOH.

## What Provenance Means

**Provenance** is distinct from Lineage:

- **Provenance** = custody history of *this* document: who created it, who edited it, when changes occurred, what authority approved it, what certificates exist.
- **Lineage** = relationships to *other* documents: derives from, supersedes, duplicates, conflicts with.

## Content

This document has a rich provenance record embedded in its frontmatter:

- Created by: `test-author-alice` on 2026-01-15
- Edited by: `test-author-alice` on 2026-02-10 (added content)
- Edited by: `test-author-bob` on 2026-04-29 (verification update)
- Version: 1.2.0

## Expected Provenance Display

In the document detail panel under "Provenance Chain":
- Creator: test-author-alice
- Last editor: test-author-bob
- Version history: 3 entries (v1.0.0 → v1.1.0 → v1.2.0)
- No approval certificates yet (this is a draft)

## Test Criteria

- provenance_seed.md is indexed with version 1.2.0: ✓
- Provenance accordion shows custody metadata: requires UI rendering verification
- Version history is visible: requires lifecycle-history endpoint
