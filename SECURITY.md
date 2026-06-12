# Security Policy

## Project status

Bag of Holding is a **local-first knowledge workbench under active development**
(public alpha source release). It is designed to run on `127.0.0.1` for a single
local operator. It is not a hosted service and has no server-side tenant model.

## Supported versions

| Version | Supported |
| --- | --- |
| `main` (latest source) | Yes — fixes land here |
| Anything older | No — update to `main` |

## Reporting a vulnerability

Please report vulnerabilities **privately** via GitHub Security Advisories:
**Security tab → "Report a vulnerability"** on this repository. Do not open a
public issue for an exploitable problem.

Include reproduction steps, the affected route/module, and impact. You can
expect an acknowledgement within a few days; this is a solo-maintained project,
so fixes are best-effort but security reports get first priority.

## Deployment model and boundaries

- The server binds to loopback (`127.0.0.1`) by default. **Exposing it beyond
  loopback (LAN, reverse proxy, internet) is outside the supported deployment
  model** unless you separately add transport security, authentication hardening,
  and isolation appropriate to your environment.
- Mutation routes are gated by `BOH_OPERATOR_TOKEN`; read-only retrieval
  connectors use the separate `BOH_RETRIEVAL_TOKEN` and must never receive the
  operator token. When `BOH_OPERATOR_TOKEN` is unset the server runs in
  **dev-open mode** (clearly badged in the UI) — never expose a dev-open
  instance beyond your own machine.
- The server-owned library root (`BOH_LIBRARY`) is a filesystem boundary:
  caller-supplied roots are rejected, and writes resolve inside the boundary.

## What must never be committed

Runtime corpora, SQLite databases (`*.db`, snapshots, WAL/SHM files), tokens,
`.env` files, quarantine contents, and generated reports are local runtime data
and must not be committed or shared. The repository's `.gitignore` enforces
this; treat any tracked file of those types as a defect and report it.

## Architectural security documents

`SECURITY_POLICY.md` in this repository is an architectural planning document
(design constraints for the governed-intake substrate), not the vulnerability
reporting policy — this file is.
