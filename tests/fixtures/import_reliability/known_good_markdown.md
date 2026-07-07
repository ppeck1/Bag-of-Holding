---
boh:
  id: fixture-known-good-md-001
  type: reference
  purpose: "Known-good Markdown import fixture for Phase 26.2 verification"
  status: draft
  version: "1.0.0"
  updated: "2026-04-29T00:00:00Z"
  project: "BOH Import Verification"
  topics:
    - import reliability
    - markdown parsing
    - frontmatter validation
  rubrix:
    operator_state: observe
    operator_intent: capture
---

# Known-Good Markdown Test Document

This document is the reference fixture for Phase 26.2 import reliability verification.

## Purpose

Verify that BOH correctly:

1. Parses YAML frontmatter from `.md` files
2. Extracts title from the first `# Heading`
3. Extracts topics from the `topics:` frontmatter list
4. Assigns correct status (`draft`) on first import
5. Indexes content for search

## Content Section

This section contains body text that should be indexed for search.

Key facts:
- FIXTURE_ID = known_good_markdown_001
- EXPECTED_STATUS = draft
- EXPECTED_TITLE = Known-Good Markdown Test Document

## Definition Block

KNOWN_GOOD_MD: A markdown document with valid BOH frontmatter that serves as the reference import test case.

## Conclusion

If this document indexes correctly, the markdown import pipeline is functioning.
