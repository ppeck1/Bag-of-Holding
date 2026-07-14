# Security

Bag of Holding is designed for local development and local evaluation. It is not
a hosted service and should not be exposed directly to the public internet.

## Boundary Model

- `BOH_LIBRARY` is the server-owned document boundary.
- Protected mutations require `BOH_OPERATOR_TOKEN`.
- Read-only retrieval uses `BOH_RETRIEVAL_TOKEN`, separate from the operator
  token.
- When `BOH_OPERATOR_TOKEN` is unset, the app runs in local dev-open mode and
  shows that state in the UI.
- LLM outputs are advisory proposals. They do not become canonical facts without
  explicit operator review.

## Public Repository Policy

The public repository contains source code, tests, design docs, and screenshots.
It must not contain local runtime data, SQLite databases, secrets, private
operator handoffs, generated review artifacts, or machine-specific paths.

Public releases are maintainer-produced from an explicit allowlist and pass an
independent fail-closed privacy audit before publication. Runtime and private
governance files are not part of the exported repository.

## Reporting

For security concerns in a public fork or portfolio copy, open a private report
with the repository owner instead of posting credentials or corpus content in an
issue.
