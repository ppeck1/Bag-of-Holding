# Retention Policy

Bag of Holding is local-first. The repository stores source, tests, public docs,
and demo assets. Runtime retention is controlled by the operator running the
local instance.

## Retained In Source

- Application source and tests
- Public architecture and run documentation
- Demo scripts and public screenshots
- Placeholder environment configuration

## Not Retained In Public Source

- SQLite runtime databases
- Indexed corpus files under `library/`
- Quarantine data
- Local exports
- Operator handoffs and private review queues
- Secrets, tokens, private keys, and credential-bearing URLs

## Runtime Data

Runtime data may be durable on the local machine until the operator deletes it.
BOH favors auditability and append-only records for governance history, so
cleanup decisions should be explicit rather than automatic.

## Public Export

Public publication uses the sanitized export workflow. The exporter copies only
tracked allowlisted files, and the audit step fails if private markers, runtime
data, local paths, or secret-shaped values are present.
