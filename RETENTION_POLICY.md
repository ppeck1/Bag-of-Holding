# RETENTION_POLICY.md

This file records retention constraints for BOH-hosted Planar Background Services.

## Phase 0 Rule

Phase 0 is planning and documentation only. No runtime retention behavior is implemented by this file.

## Preservation Policy

Future services should preserve:

- RAW/source artifacts when policy allows
- audit ledgers
- actor ledgers
- correction ledgers
- provenance records
- quarantine records
- capability records
- policy snapshots used to make decisions

## Deletion Policy

Future services must not delete source material, RAW artifacts, audit ledgers, correction ledgers, or provenance records automatically.

Any cleanup behavior must be explicit, bounded, operator-authorized where destructive, and auditable.

## Quarantine Policy

Quarantine is a preservation and safety lane, not a deletion lane. Quarantined files may be preserved without being interpreted, indexed, normalized, or treated as canon candidates.

## IntakeCapability Requirement

Before later phases process discovered material, the system must be able to represent whether a candidate is:

- discovered
- preservable
- normalizable
- interpretable
- queryable
- canon eligible

`canon_eligible` must default to false.
