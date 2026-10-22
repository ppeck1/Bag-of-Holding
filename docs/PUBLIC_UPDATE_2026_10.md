# BOH source update — October 2026

This update publishes the application improvements developed since the earlier
portfolio snapshot and a standalone local HTTP consumer. It does not bundle
the private evaluation corpus or any other project's source material.

## Available now

- Plain UTF-8 Markdown can be indexed without a BOH header. Original bytes are
  preserved; default posture is draft, supporting and non-authoritative.
  Explicit malformed BOH metadata is rejected rather than silently downgraded.
  Indented horizontal rules and code blocks remain ordinary body text.
- Managed source observations track changed, missing and invalid sources while
  preserving prior revisions. Incomplete scans report uncertainty. Proven
  renames can preserve identity; content equality alone does not prove a rename.
- Governed retrieval applies scope, authority and identifier/phrase constraints
  consistently. Exact lookup searches the indexed snapshot beyond the old
  bounded candidate window and reports complete, partial or unknown coverage
  under its budgets. Complete coverage does not promise every match in a small
  result limit, or exhaustive coverage of unindexed files.
- The evidence-diversity evaluator can credit complementary reviewed facts in
  one document and avoid counting repeated facts twice. It is a separate
  measurement tool, not a new ranking algorithm or proof of general relevance.
- UI status distinguishes unavailable measurements from zero and keeps action
  availability and errors visible.
- `tools/platform/consumer.py` provides a standard-library-only HTTP client for
  trusted local consumers. It preserves retrieval policy/coverage metadata and
  follows only returned citation identities to the source reader.

## Use the local consumer

Configure a running BOH instance with a retrieval credential, and set
`BOH_CONSUMER_TOKEN` in the consumer process environment. Use its logical library
identifier, then run:

```powershell
python tools/platform/consumer.py --base-url http://127.0.0.1:8000 --library-id YOUR_LIBRARY_ID --query "When should I use this method?"
```

The CLI emits JSON. It accepts literal loopback HTTP with an explicit port,
refuses redirects and environment proxies, and sends only the retrieval
credential. `Client.retrieve()` preserves the wire response; `Client.lookup()`
adds explicit reader follow-up. A reader body is current file content: the
client labels its equality to the indexed source hash as unknown. Logical
libraries are browsing filters, not separate authorization tenants.

## Verification boundary

The public suite includes the existing sanitized tests and portable subsets of
the new Markdown, lifecycle, exact-lookup, diversity and HTTP-consumer tests.
Assertions in those subsets retain their original behavior. Private corpus
measurements, operational MCP adapter checks, checkpoint/restore harnesses and
other-project integration checks remain outside this source export. See
[test inventory](PUBLIC_TEST_INVENTORY.json) for exact omitted functions.
Existing explicitly marked operational-MCP skips remain visible.

The complete private source previously passed 1976 tests; that count is not the
public test result. The GitHub Actions check reports this export's own result.
Public CI uses Python 3.11 and `python -m pytest tests -q`.

This remains a local development platform. Clean-machine packaging, remote
tenant isolation, large-corpus performance, general passage relevance and
unattended operations have not been qualified. PDF/image OCR is unavailable.
The operational MCP deployment remains excluded as documented in the README.
The README screenshots are retained captures from the earlier isolated demo;
they are not newly captured acceptance evidence for this update.
