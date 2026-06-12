# SECURITY_POLICY.md

> **Architectural planning document.** This file records design-time security
> constraints for BOH-hosted Planar Background Services (written at Phase 0;
> the constraints below have since been implemented by the governed-intake
> layer). For the vulnerability reporting policy and the supported deployment
> model, see `SECURITY.md`.

This file records security constraints for BOH-hosted Planar Background Services.

## Phase 0 Rule

Phase 0 is planning and documentation only. No runtime security behavior is implemented by this file.

## Service Safety Constraints

Future Planar Background Services must:

- use the existing BOH filesystem boundary
- stay under the server-owned library root or approved staging roots
- fail closed on unsafe paths
- avoid caller-supplied roots unless explicitly allowed by a tested boundary
- preserve operator-token and actor-ledger boundaries
- keep read-only connector roles separate from operator authority

## Explicit Blocks

Future background intake and normalization work must not:

- execute discovered files
- auto-unpack archives
- fetch remote assets during parsing or normalization
- run embedded scripts
- trust unsafe HTML
- render unsafe HTML as privileged application content
- promote discovered content into canon automatically
- use LLM output as authority
- give another program the operator token

## HTML Handling

HTML may only be treated as source text or safely extracted content until a later accepted implementation proves stronger behavior. Unsafe HTML behavior includes executing scripts, loading remote assets, trusting inline event handlers, or treating rendered output as verified content.

## Archive Handling

Archives may be registered or preserved only when a later implementation explicitly supports that path. They must not be auto-unpacked or recursively scanned by default.
