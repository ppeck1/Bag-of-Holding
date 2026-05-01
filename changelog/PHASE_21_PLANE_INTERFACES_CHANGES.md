# BOH v2 — Phase 21 Plane Interfaces Implementation

## Implemented

Phase 21 begins the Constraint-Native Lattice Engine sequence by making cross-plane movement explicit.

### New core module

Created:

- `app/core/plane_interface.py`

Capabilities:

- Creates immutable plane interface artifacts.
- Validates source and target planes.
- Blocks same-plane interface artifacts.
- Requires non-empty translation reason.
- Requires certificate references for cross-plane mutation.
- Verifies referenced certificates exist and are approved.
- Verifies certificate node alignment when `node_id` is provided.
- Records semantic loss notes.
- Records `q_delta` and `c_delta`.
- Records explicit `authority_plane`.
- Supports retrieval and listing.

### New database table

Added migration-safe schema in `app/db/connection.py`:

- `plane_interfaces`

Indexed by:

- `node_id`
- `source_plane, target_plane`
- `authority_plane`
- `created_at`

### Canonical promotion path patched

Updated:

- `app/core/certificate.py`

Canonical promotion now follows:

```text
approved certificate
→ plane interface artifact
→ canonical mutation
```

`apply_canonical_promotion()` now returns `interface_id` and logs it into the lattice event detail.

### New API routes

Created:

- `app/api/routes/plane_interface_routes.py`

Registered in:

- `app/api/main.py`

Endpoints:

- `POST /api/plane-interfaces`
- `GET /api/plane-interfaces`
- `GET /api/plane-interfaces/{interface_id}`

### Regression tests added

Created:

- `tests/test_phase21_plane_interface.py`

Coverage:

- Interface creation requires certificate references.
- Approved certificates permit interface creation.
- Canonical promotion creates a plane interface before mutation.
- API route can create, list, and read interfaces.

## Validation performed

Passed:

```text
/usr/bin/python3 -m py_compile app/core/plane_interface.py app/core/certificate.py app/api/routes/plane_interface_routes.py app/api/main.py
```

Passed core smoke test using isolated DB:

```text
request certificate → approve certificate → apply canonical promotion → verify generated interface artifact
```

Observed result:

```text
promotion returned ok=True with interface_id
interface source_plane=internal
target_plane=canonical
certificate_refs contained the approved certificate
```

## Test caveat

Full pytest was not completed in this container because importing the FastAPI app through the venv Python process timed out. Core module import, DB initialization, schema migration, syntax compilation, and isolated certificate-to-interface-to-canonical smoke validation succeeded.

## Phase 21 review

### Usability impact

Promotion now exposes an additional artifact. This makes the promotion path less invisible and gives users a concrete translation record.

### Friction increase

Moderate. Users will see another object in the lawful mutation chain. This is intentional. Cross-plane movement is now inspectable instead of implied.

### False authority risk

Reduced. Canonical status can no longer appear as a direct plane jump. The interface artifact records why the target plane accepted the translation and which certificate authorized it.

### Operator comprehension

Improved for advanced users, initially worse for new users. UI copy should eventually explain it as: “This is the translation receipt between planes.”

### Failure recovery path

Better. If promotion fails before mutation, the error can now identify whether the certificate failed, the interface failed, or the canonical write failed.

### Audit survivability

Improved. The certificate proves permission; the interface proves translation; the lattice event proves mutation occurred. These are distinct and should remain distinct.

## Next phase not implemented yet

Phase 22 is intentionally not included here. Per the patch instructions, Phase 21 should be reviewed before moving into the Constraint-Native Graph + Flow Traversal engine.
