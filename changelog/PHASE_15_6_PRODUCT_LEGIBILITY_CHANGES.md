# Bag of Holding v2 — Phase 15.6 Product Legibility Patch

## Source Patch
Applied the user-provided "Product Legibility + Progressive Disclosure" patch.

## Summary
This patch preserves the formal BOH/CANON engine while making the default product surface easier to understand. Governance, provenance, canonical controls, review artifacts, hashes, signatures, and CANON diagnostics remain intact. The UI now defaults toward plain-language workflow terms, with deeper machinery exposed through Advanced mode.

## Major Changes

### 1. User-Facing Copy Layer
- Added `app/ui/copy_map.js`.
- Introduced centralized user-facing labels for navigation, governance, and CANON diagnostics.
- Kept internal API names and backend schema terms unchanged.

### 2. Simple / Advanced Display Mode
- Added a global `Simple | Advanced` toggle in the header.
- Persisted mode using `localStorage`.
- Default mode is `simple`.
- Advanced mode exposes lower-level details such as IDs, hashes, review levels, cross-project exposure, and raw governance internals.

### 3. Product Navigation Reframing
- Reframed displayed labels toward user workflow language:
  - New / Import → Inbox
  - Atlas → Connections
  - Governance → Review Center
  - LLM Queue → Suggested Changes
  - Constitutional Ledger → Decision History
  - Review Patch → Suggested Change
- Preserved backend routes and data names.

### 4. Inbox / Draft Flow
- Added first-class product-level `app_state` support in database migration.
- New browser-created content now carries an Inbox-facing state in frontmatter.
- Indexed draft/working content is assigned `app_state = inbox`; reviewed/stable content maps toward library state.
- Governance state remains separate from product-facing state.

### 5. Human Explanation Panels for Review Cards
- Added `explainApprovalImpact(item)`.
- Review cards now display a plain-language "What this means" block generated from blast-radius fields.
- Existing severity, impact, rollback, governance tier, and cross-project data remain available.

### 6. CANON Diagnostics as Optional Detail
- Added `stabilityLabel(deltaC)` helper for simplified stability display.
- Advanced-mode classing now supports hiding lower-level diagnostic machinery by default.
- CANON math remains available; it is not removed or renamed internally.

### 7. First-Launch Onboarding
- Added a first-launch intro card explaining BOH as reasoning preservation.
- Added "Don’t show again" persistence via `localStorage`.

### 8. Demo Project Seed
- Added `POST /api/input/demo-seed`.
- Added `Load Demo Project` button in Inbox.
- Demo creates sample research notes through normal safe intake, not canonical authority mutation.

### 9. README Repositioning
- Updated README opening to position BOH as a local-first reasoning-preservation workspace.
- Added sections for:
  - What problem does this solve?
  - Simple mode vs Advanced mode
- Preserved deeper governance and architecture documentation below the new opening.

## Files Changed
- `app/ui/copy_map.js`
- `app/ui/index.html`
- `app/ui/app.js`
- `app/ui/style.css`
- `app/api/routes/input_routes.py`
- `app/core/input_surface.py`
- `app/db/connection.py`
- `app/db/schema.sql`
- `app/services/indexer.py`
- `README.md`

## Validation
- Test suite passed: `654 passed, 2 skipped`.

## Guardrails Preserved
- No governance protections weakened.
- No internal schema or route renames required for existing code paths.
- No LLM auto-merge introduced.
- No canonical auto-promotion introduced.
- Review boundaries remain explicit.
- Provenance, signatures, hashes, and rollback details remain available in Advanced mode.
