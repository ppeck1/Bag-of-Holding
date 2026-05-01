---
boh:
  id: fixture-bad-encoding-warning
  type: reference
  purpose: "Bad encoding fixture — tests graceful handling of non-UTF-8 bytes"
  status: draft
  version: "1.0.0"
  updated: "2026-04-29T00:00:00Z"
  project: "BOH Import Verification"
  rubrix:
    operator_state: observe
    operator_intent: capture
---

# Bad Encoding Test Document

This document contains valid UTF-8 content in the frontmatter.
The test verifies that files with encoding issues are handled gracefully.

## Purpose

When BOH encounters a file with non-UTF-8 bytes, it should:
1. NOT crash the indexer or return HTTP 500
2. Replace undecodable bytes with the Unicode replacement character (U+FFFD)
3. Still index the valid portions of the document
4. Record a lint warning (not a hard failure)

## Expected Behavior

- File is indexed (indexed: true)
- Title extracted from frontmatter
- Any undecodable bytes replaced with replacement character
- Lint warning recorded but does not block indexing

## Content

FIXTURE_ID: bad_encoding_warning_001
EXPECTED_STATUS: draft (indexed with replacement chars)
