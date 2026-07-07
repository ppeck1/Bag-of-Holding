# Security Policy

## Supported Use

This alpha source release is supported for local evaluation only. Do not deploy
it as an internet-facing service without an independent security review.

## Secrets

Never commit real values for:

- `BOH_OPERATOR_TOKEN`
- `BOH_RETRIEVAL_TOKEN`
- API keys, passwords, private keys, or credential-bearing URLs

Use `.env.example` for variable names and placeholder values only.

## Data Handling

Corpus content, generated review artifacts, SQLite databases, and operator
handoffs are local runtime data. They are excluded from the public export and
should remain private unless reviewed deliberately.

## Vulnerability Reports

Send a concise private report with:

- affected version or commit
- reproduction steps
- expected impact
- whether any local corpus data or credentials were involved

Do not include live secrets or private corpus documents in the report.
