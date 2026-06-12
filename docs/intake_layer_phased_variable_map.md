# BOH Intake Layer — Phased Variable and Wiring Map

Status: **implementation record** (updated 2026-05-28). All phases 0-8 are COMPLETE. Each phase section describes what was introduced in that phase. Verified test counts and the append-only build record are maintained in the private working repository.

Source buildspecs:
- `docs/specs/boh_background_planar_storage_buildspec_v0_2_1_intake_capability_patched.md`
- `new.branch/boh_governed_ingestion_translation_layer_buildspec_v0_1.md`

Cross-reference with `docs/project_variable_map.md` for the full current wiring baseline.

---

## Phase Legend

| Phase | Name | Status | Tests |
|---|---|---|---|
| Phase 0 | Governance Scaffold | COMPLETE | — |
| Phase 1 | Schemas and Version Provenance | COMPLETE | 49 |
| Phase 2 | Adapter Registry | COMPLETE | 61 |
| Phase 3 | Discovery and Capability Initialization | COMPLETE | 37 |
| Phase 4 | Preservation | COMPLETE | 18 |
| Phase 5 | Translation Routing and Normalization | COMPLETE | 42 |
| Phase 6 | Interpretation and Queryability Handoff | COMPLETE | 26 |
| Phase 7 | API and Database Integration | COMPLETE | 21 |
| Phase 8 | Replay, Backpressure, and Scheduler | COMPLETE | 14 |

---

## Phase 0 — Governance Scaffold (COMPLETE)

No runtime behavior. All items in this phase are documentation or governance files only.

### Governance Documents Added

| File | Role |
|---|---|
| `SOURCE_OF_TRUTH.md` | Source-of-truth hierarchy for BOH. |
| `POLICY_REGISTRY.md` | Registry of active policies governing BOH behavior. |
| `SECURITY_POLICY.md` | Security constraints (no execution, no auto-unpack, no remote fetch, no canon bypass). |
| `RETENTION_POLICY.md` | Retention rules for RAW artifacts, ledgers, provenance, quarantine, capability records, and policy snapshots. |

Additional governed work-order process files (authority order, active work order,
done gate, factual state snapshot, append-only build record) are maintained in
the private working repository.
| `PLANAR_SERVICES_IMPLEMENTATION_MAP.md` | Planning map for the background services build. Not implementation. |
| `docs/specs/boh_background_planar_storage_buildspec_v0_2_1_intake_capability_patched.md` | Stable v0.2.1 buildspec stored as reference. |

### Existing Runtime Variables (Baseline — Carry Forward)

These are fully wired before any intake layer work. They are **not** introduced by the intake layer. See `docs/project_variable_map.md` for full detail.

| Variable | Module | Purpose |
|---|---|---|
| `BOH_LIBRARY` | `app.core.fs_boundary` | Server-owned document library root. |
| `BOH_DB` | `app.db.connection` | SQLite database path. |
| `BOH_OPERATOR_TOKEN` | `app.core.auth` | Privileged local mutation boundary. |
| `BOH_RETRIEVAL_TOKEN` | `app.core.retrieval` | Read-only retrieval connector boundary. |
| `BOH_DEFAULT_ACTOR` | `app.core.actor_ledger` | Default actor identity fallback. |
| `BOH_CORS_ORIGINS` | `app.api.main` | CORS origin override. |
| `BOH_AUTO_INDEX` | `app.core.autoindex` | Background startup auto-index flag. |
| `BOH_AUTO_INDEX_MAX_FILES` | `app.core.autoindex` | Startup scan cap. |
| `BOH_DETERMINISTIC_REVIEW_ON_INDEX` | `app.core.autoindex` | Deterministic analysis on index flag. |
| `BOH_LLM_REVIEW_ON_INDEX` | `app.core.autoindex` | LLM review on index flag. |
| `BOH_ANALYZE_ON_INDEX` | `app.core.autoindex` | Umbrella analysis-on-index flag. |
| `BOH_OLLAMA_ENABLED` | `app.core.ollama` | Ollama invocation gate. |
| `BOH_OLLAMA_URL` | `app.core.ollama` | Ollama base URL. |
| `BOH_OLLAMA_MODEL` | `app.core.ollama` | Default Ollama model. |
| `BOH_OLLAMA_MAX_CONTENT` | `app.core.ollama` | Max chars sent to Ollama. |
| `BOH_EXEC_ALLOWED_COMMANDS` | `app.core.execution` | Execution command allowlist. |

---

## Phase 1 — Schemas and Version Provenance (COMPLETE)

**Scope:** Schema/model definitions and serialization tests only. No DB migrations, no routes, no UI, no background runner, no LLM behavior.

**Delivered:** `app/core/planar_service_schemas.py` — 49 tests in `tests/test_planar_service_schemas.py`.

### New Module

| File | Purpose |
|---|---|
| `app/core/planar_service_schemas.py` | Schema-only module for all Phase 1 records. |
| `tests/test_planar_service_schemas.py` | Serialization and invariant tests for Phase 1 schemas. |

### New Schema Types

All types live in `app/core/planar_service_schemas.py`. None wire into routes, DB, or UI yet.

#### IntakeCapability

The central guardrail that prevents collapsing discovery into ingestion.

| Field | Type | Default | Invariant |
|---|---|---|---|
| `intake_capability_id` | `str` | `ic_<stable_hash>` | Stable; deterministic from source identity + policy snapshot hash. |
| `raw_artifact_id` | `str \| None` | `None` | Null until preservation succeeds. |
| `source_ref` | `str` | required | Path or source identifier. |
| `batch_id` | `str` | required | Parent batch. |
| `discovered` | `bool` | `True` on creation | Always true after scanner sees file. |
| `preservable` | `bool` | `False` | False until policy and safety checks allow. |
| `normalizable` | `bool` | `False` | False until adapter routing confirms support. |
| `interpretable` | `bool` | `False` | False until extraction/interpretation succeeds. |
| `queryable` | `bool` | `False` | False until indexing and governance allow it. |
| `canon_eligible` | `bool` | `False` | **Always false by default. Never set by intake layer.** |
| `required_adapter` | `str \| None` | `None` | Adapter ID needed; null only when no adapter required. |
| `safety_lane` | `str` | `"hold"` | `accept \| hold \| quarantine \| ignore`. Default hold. |
| `failure_reason` | `str \| None` | `None` | Non-null when any capability is blocked or missing. |
| `lifecycle_state` | `str` | `"discovered"` | `discovered \| preserved \| held \| normalized \| interpreted \| queryable_advisory \| quarantined \| ignored \| failed` |
| `trust_state` | `str` | `"unknown"` | `unknown \| unreviewed_download \| trusted_local \| reviewed_source \| blocked` |
| `authority_default` | `str` | `"none"` | `none \| advisory \| review_required \| blocked` |
| `trace_event_refs` | `list[str]` | `[]` | References to TraceEvent IDs. |
| `version_provenance` | `VersionProvenance` | required | Schema, service, adapter registry, policy snapshot hash, created_at. |

#### RawArtifact

Preserved immutable copy of a discovered file.

| Field | Type | Notes |
|---|---|---|
| `raw_artifact_id` | `str` | Stable hash of source_ref + sha256 + preservation_policy_version. |
| `intake_capability_id` | `str` | Parent capability record. |
| `source_ref` | `str` | Original path or source identifier. |
| `source_hash_sha256` | `str` | SHA-256 of original before copy. |
| `preserved_hash_sha256` | `str` | SHA-256 verified after copy. |
| `byte_size` | `int` | Byte count. |
| `media_type` | `str \| None` | Detected MIME type. |
| `preservation_path` | `str` | RAW storage path relative to BOH_DATA root. |
| `batch_id` | `str` | Parent batch. |
| `version_provenance` | `VersionProvenance` | Policy snapshot hash and timestamps. |

#### NormalizedArtifact

Output of a successful adapter normalization run.

| Field | Type | Notes |
|---|---|---|
| `normalized_artifact_id` | `str` | Hash of raw_artifact_id + adapter_run_id + output_hash. |
| `raw_artifact_id` | `str` | Source artifact. |
| `adapter_run_id` | `str` | Which adapter run produced this. |
| `output_path` | `str` | Normalized output path relative to BOH_DATA root. |
| `output_hash_sha256` | `str` | Hash of normalized output. |
| `output_type` | `str` | e.g. `markdown`, `text`, `json`, `extracted_units`. |
| `known_losses` | `list[str]` | Capabilities lost during normalization. |
| `warnings` | `list[str]` | Non-fatal conversion events. |
| `version_provenance` | `VersionProvenance` | Adapter version, policy snapshot hash, timestamps. |

#### EvidenceUnit

A span of normalized content that can be referenced for retrieval.

| Field | Type | Notes |
|---|---|---|
| `evidence_unit_id` | `str` | Stable ID. |
| `normalized_artifact_id` | `str` | Source artifact. |
| `span_start` | `int` | Byte offset start. |
| `span_end` | `int` | Byte offset end. |
| `unit_type` | `str` | `heading \| body \| table \| frontmatter \| claim`. |
| `text_hash` | `str` | Hash of extracted text. |
| `authority_default` | `str` | From parent IntakeCapability. |
| `canon_eligible` | `bool` | `False` by default. |
| `version_provenance` | `VersionProvenance` | |

#### AdapterMetadata

Declares what an adapter can and cannot do.

| Field | Type | Notes |
|---|---|---|
| `adapter_id` | `str` | Stable adapter identifier. |
| `adapter_version` | `str` | Semantic version. |
| `supported_extensions` | `list[str]` | e.g. `[".html", ".htm"]`. |
| `supported_media_types` | `list[str]` | MIME types. |
| `can_preserve` | `bool` | |
| `can_normalize` | `bool` | |
| `can_interpret` | `bool` | |
| `can_make_queryable` | `bool` | |
| `requires_sandbox` | `bool` | |
| `fetches_remote_assets` | `bool` | Must be false for current adapters. |
| `executes_content` | `bool` | Must be false for all adapters. |
| `output_types` | `list[str]` | e.g. `["NormalizedArtifact", "EvidenceUnitCandidate"]`. |
| `known_losses` | `list[str]` | |
| `warning_types` | `list[str]` | Possible warning codes this adapter emits. |
| `default_safety_lane` | `str` | `accept \| hold \| quarantine \| ignore`. |

#### AdapterRun

Record of a single adapter execution against a RawArtifact.

| Field | Type | Notes |
|---|---|---|
| `adapter_run_id` | `str` | Hash of raw_artifact_id + adapter_id + adapter_version + policy_snapshot_hash. |
| `adapter_id` | `str` | |
| `adapter_version` | `str` | |
| `raw_artifact_id` | `str` | |
| `intake_capability_id` | `str` | |
| `success` | `bool` | |
| `failure_reason` | `str \| None` | |
| `warnings` | `list[str]` | |
| `output_artifact_ids` | `list[str]` | NormalizedArtifact IDs produced. |
| `version_provenance` | `VersionProvenance` | |

#### SafetyLaneTransition

Records a lane change for an IntakeCapability.

| Field | Type | Notes |
|---|---|---|
| `transition_id` | `str` | Hash of capability_id + from_lane + to_lane + reason + actor_or_job + timestamp_bucket. |
| `intake_capability_id` | `str` | |
| `from_lane` | `str` | Previous lane. |
| `to_lane` | `str` | New lane. |
| `reason` | `str` | Why transition occurred. |
| `actor_or_job` | `str` | Who or what caused the transition. |
| `version_provenance` | `VersionProvenance` | |

#### IngestionJob

A scheduled or manual ingestion run.

| Field | Type | Notes |
|---|---|---|
| `job_id` | `str` | Stable ID. |
| `job_mode` | `str` | `scheduled_scan \| manual_scan \| single_file_replay \| batch_replay \| adapter_dry_run \| capability_rebuild \| normalization_rebuild \| queryability_recheck` |
| `batch_id` | `str \| None` | Assigned batch. |
| `status` | `str` | `pending \| running \| complete \| failed \| paused` |
| `started_at` | `str \| None` | ISO-8601. |
| `completed_at` | `str \| None` | ISO-8601. |
| `version_provenance` | `VersionProvenance` | |

#### IngestionJobEvent

An event within a job run.

| Field | Type | Notes |
|---|---|---|
| `event_id` | `str` | |
| `job_id` | `str` | |
| `event_type` | `str` | e.g. `discovered`, `preserved`, `normalized`, `quarantined`, `failed`. |
| `intake_capability_id` | `str \| None` | Related file if applicable. |
| `message` | `str` | Human-readable event description. |
| `version_provenance` | `VersionProvenance` | |

#### HandoffPacket

State passed from the intake layer to Planar Governance.

| Field | Type | Notes |
|---|---|---|
| `handoff_id` | `str` | |
| `intake_capability_id` | `str` | |
| `raw_artifact_id` | `str \| None` | |
| `normalized_artifact_id` | `str \| None` | |
| `evidence_candidate_refs` | `list[str]` | |
| `capability_state` | `dict` | Snapshot of IntakeCapability boolean fields. |
| `safety_lane` | `str` | |
| `required_adapter` | `str \| None` | |
| `failure_reason` | `str \| None` | |
| `warnings` | `list[str]` | |
| `trace_event_refs` | `list[str]` | |
| `version_provenance` | `VersionProvenance` | |

#### TraceEvent

An individual audit event emitted during intake processing.

| Field | Type | Notes |
|---|---|---|
| `trace_event_id` | `str` | |
| `event_type` | `str` | |
| `intake_capability_id` | `str \| None` | |
| `job_id` | `str \| None` | |
| `detail` | `dict` | Free-form detail specific to event_type. |
| `version_provenance` | `VersionProvenance` | |

#### QuarantineRecord

Record of a file that was quarantined.

| Field | Type | Notes |
|---|---|---|
| `quarantine_record_id` | `str` | |
| `intake_capability_id` | `str` | |
| `raw_artifact_id` | `str \| None` | |
| `quarantine_reason` | `str` | |
| `quarantine_category` | `str` | `archive_pending_review \| executable_blocked \| unsupported \| suspicious \| failed_hash \| source_trust_unknown` |
| `review_required` | `bool` | |
| `released_at` | `str \| None` | ISO-8601; null until released. |
| `version_provenance` | `VersionProvenance` | |

#### VersionProvenance

Shared provenance record carried by all schema types.

| Field | Type | Notes |
|---|---|---|
| `schema_version` | `str` | Schema model version. |
| `service_version` | `str` | Intake layer service version. |
| `adapter_registry_version` | `str \| None` | Registry version snapshot. |
| `policy_snapshot_hash` | `str \| None` | SHA-256 of active policy snapshot. |
| `created_at` | `str` | ISO-8601 creation time. |

#### Alignment Types (wrap existing BOH concepts)

These types exist as compatibility wrappers to prevent naming collisions with existing modules.

| Type | Wraps | Notes |
|---|---|---|
| `GateResultRef` | `app.core.planar_gate.GateResult` | Reference handle; does not replace existing GateResult. |
| `ContextPackRef` | `app.core.context_pack.ContextPack` | Reference handle; does not replace existing ContextPack. |
| `PlaneCardRef` | `app.core.plane_card` | Reference handle into existing PlaneCard model. |
| `AuthorityStateRef` | `app.core.authority_state` | Reference handle into existing authority state. |
| `ConflictSetRef` | `app.core.conflicts` | Reference handle. |
| `ReviewProposalRef` | Aligns with existing approval/LLM queue | Intake layer proposal reference only. |
| `MistakeEventRef` | `app.core.planar_fixtures.MistakeEvent` | Reference into existing fixture emit. |
| `PatchProposalRef` | Existing planar fixture type | Reference handle. |
| `CanonChangeRecordRef` | Existing planar canon change type | Reference handle; does not grant promotion authority. |
| `InformationResidenceMapRef` | Existing residence map type | Reference handle. |
| `PolicySnapshot` | New; parallel to policy registry | Deterministic hash/version snapshot of active policy rules at a point in time. |
| `PolicyRule` | New | Named rule entry with version and effect. |
| `BackpressureState` | New | Pause/resume state for ingestion flow control. |
| `RetentionDecision` | New | Retention action and reason for a RawArtifact or NormalizedArtifact. |
| `SoloOverrideRecord` | New | Operator-acknowledged override of a blocked/held state. |

### Phase 1 Test Assertions Required

| Test | Assertion |
|---|---|
| `test_intake_capability_canon_eligible_defaults_false` | `IntakeCapability().canon_eligible == False` |
| `test_discovery_does_not_imply_preservation` | Discovered-only record has `preservable=False` |
| `test_discovery_does_not_imply_interpretation` | Discovered-only record has `interpretable=False` |
| `test_discovery_does_not_imply_queryability` | Discovered-only record has `queryable=False` |
| `test_failure_reason_required_on_blocked_path` | Failed preservation/normalization has non-null `failure_reason` |
| `test_raw_artifact_carries_source_hash` | `RawArtifact.source_hash_sha256` is required and non-empty |
| `test_normalized_artifact_carries_adapter_ref` | `NormalizedArtifact.adapter_run_id` is required |
| `test_evidence_unit_references_normalized_source` | `EvidenceUnit.normalized_artifact_id` is required |
| `test_gate_result_ref_is_advisory_only` | `GateResultRef` cannot represent a canon promotion state |
| `test_policy_snapshot_has_deterministic_hash` | Same inputs produce same `PolicySnapshot.policy_snapshot_hash` |
| `test_version_provenance_required_on_all_types` | Every schema type carries `version_provenance.schema_version` and `created_at` |
| `test_serialization_roundtrip_intake_capability` | JSON serialize → deserialize preserves all required fields |
| `test_serialization_roundtrip_raw_artifact` | Roundtrip |
| `test_serialization_roundtrip_normalized_artifact` | Roundtrip |
| `test_serialization_roundtrip_ingestion_job` | Roundtrip |
| `test_serialization_roundtrip_handoff_packet` | Roundtrip |

---

## Phase 2 — Adapter Registry (COMPLETE)

**Scope:** Adapter metadata loader, extension/media-type matching, coverage report. No DB writes, no scanning, no routes yet.

**Delivered:** `app/services/intake/adapter_registry.py` + 13 adapter stubs — 61 tests in `tests/test_intake_adapter_registry.py`.

### New Modules

| File | Purpose |
|---|---|
| `app/services/intake/adapter_registry.py` | Load, register, match, and report adapters. |
| `app/services/intake/adapters/__init__.py` | Adapter package. |
| `app/services/intake/adapters/markdown_direct.py` | Direct `.md`/`.markdown` staging. |
| `app/services/intake/adapters/text_direct.py` | Direct `.txt` staging. |
| `app/services/intake/adapters/code_direct.py` | Direct code file staging (read-only, no execution). |
| `app/services/intake/adapters/json_direct.py` | Direct `.json`/`.jsonl` staging with invalid-JSON hold. |
| `app/services/intake/adapters/yaml_direct.py` | Direct `.yaml`/`.yml` staging with unsafe-tag text fallback. |
| `app/services/intake/adapters/csv_direct.py` | Direct `.csv` staging with large-file profile fallback. |
| `app/services/intake/adapters/html_adapter.py` | Script-neutralizing HTML-to-MD normalization with warnings. |
| `app/services/intake/adapters/pdf_hold.py` | Preserve-but-hold; marks interpretable=False. |
| `app/services/intake/adapters/docx_hold.py` | Preserve-but-hold; sandbox converter required. |
| `app/services/intake/adapters/image_hold.py` | Preserve-but-hold; image interpreter required. |
| `app/services/intake/adapters/archive_hold.py` | Metadata-only; quarantine; no auto-unpack. |
| `app/services/intake/adapters/executable_block.py` | Block before preservation; quarantine. |
| `app/services/intake/adapters/unsupported.py` | Fail closed with `required_adapter`/`failure_reason`. |
| `tests/test_intake_adapter_registry.py` | Adapter metadata, matching, coverage, cannot-promote-canon. |

### Invariants for Adapters

- Every adapter must declare `can_preserve`, `can_normalize`, `can_interpret`, `can_make_queryable`.
- `executes_content` must always be `False`.
- `fetches_remote_assets` must always be `False` for current adapters.
- An adapter cannot set `canon_eligible=True`.
- Missing/unsupported type must record `required_adapter` and `failure_reason`.

---

## Phase 3 — Discovery and Capability Initialization (COMPLETE)

**Scope:** Watch-path scanning, ignore patterns, partial-file exclusion, candidate stabilization, IntakeCapability creation, trace emission. No preservation yet.

**Delivered:** `discovery.py`, `stabilizer.py`, `capability.py`, `trace.py` — 37 tests in `tests/test_intake_discovery.py`.

### New Modules

| File | Purpose |
|---|---|
| `app/services/intake/discovery.py` | Watch-path scan, ignore patterns, partial-file exclusion. |
| `app/services/intake/stabilizer.py` | Candidate file stabilization (size/mtime settle check). |
| `app/services/intake/capability.py` | IntakeCapability initialization from discovered candidate. |
| `app/services/intake/trace.py` | Trace event emission. |
| `tests/test_intake_discovery.py` | Every discovered file gets a capability record; partial downloads ignored. |

### New Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `BOH_INTAKE_WATCH_PATHS` | unset | Comma-separated paths the intake scanner monitors. |
| `BOH_INTAKE_IGNORE_PATTERNS` | unset | Comma-separated glob patterns to skip (e.g. `*.crdownload,*.tmp`). |
| `BOH_INTAKE_ENABLED` | `false` | Gate for intake scanning. Must be explicitly enabled. |
| `BOH_INTAKE_BATCH_MAX` | `50` | Max files per ingestion batch. |

### Invariants

- A discovered file gets `IntakeCapability(discovered=True)` and all other capability booleans `False`.
- Partial downloads (`.crdownload`, `.part`, `.tmp`) are excluded.
- Discovery alone does not write to RAW, DB, or normalized output.
- Every discovery event writes a `TraceEvent`.

---

## Phase 4 — Preservation (COMPLETE)

**Scope:** Hash original, copy to RAW, verify hash, write source registry and batch manifest. Quarantine on failed hash.

**Delivered:** `hashing.py`, `preservation.py` — 18 tests in `tests/test_intake_preservation.py`. Env var `BOH_DATA_ROOT` introduced (required; no default).

### New Modules

| File | Purpose |
|---|---|
| `app/services/intake/preservation.py` | Copy-and-verify pipeline. |
| `app/services/intake/hashing.py` | SHA-256 computation helpers. |
| `app/services/intake/manifests.py` | `source_registry.jsonl` and `batch_manifest.json` writers. |
| `tests/test_intake_preservation.py` | Preservation roundtrip, hash-verify, original not mutated, failed-hash quarantine. |

### New Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `BOH_DATA_ROOT` | unset | Root for `01_RAW/`, `02_NORMALIZED/`, `07_LEDGER/`, `99_QUARANTINE/`. Must be declared; not auto-created. |

### New Directory Structure (under `BOH_DATA_ROOT`)

| Path | Contents |
|---|---|
| `00_INBOX/watch_paths.json` | Configured watch paths. |
| `00_INBOX/ignore_patterns.json` | Ignore patterns. |
| `00_INBOX/ingestion_policy.json` | Active policy snapshot for inbox. |
| `01_RAW/<date>/<batch_id>/files/` | Preserved immutable copies. |
| `01_RAW/<date>/<batch_id>/source_registry.jsonl` | Source preservation truth per batch. |
| `01_RAW/<date>/<batch_id>/batch_manifest.json` | Batch summary. |
| `99_QUARANTINE/archives_pending_review/` | Archive quarantine. |
| `99_QUARANTINE/executables_blocked/` | Executable quarantine. |
| `99_QUARANTINE/unsupported/` | Unsupported type quarantine. |
| `99_QUARANTINE/suspicious/` | Suspicious file quarantine. |
| `99_QUARANTINE/failed_hash/` | Hash verification failure quarantine. |
| `99_QUARANTINE/source_trust_unknown/` | Unknown trust-state quarantine. |

### Source-of-Truth Rule

```
01_RAW + source_registry = preservation truth
07_LEDGER/intake_capabilities.jsonl = capability/audit truth
SQLite = query/index convenience only
UI = display only
```

---

## Phase 5 — Translation Routing and Normalization (COMPLETE)

**Scope:** Translation router, run direct-staging and HTML adapters, route hold/quarantine adapters, write normalization manifest. Warnings must surface; losses must not be hidden.

**Delivered:** `translation_router.py`, `normalization.py` — 42 tests in `tests/test_intake_translation.py`. HTML neutralizer uses stdlib `html.parser` only; strips script/style/form/iframe/object/embed/on* handlers.

### New Modules

| File | Purpose |
|---|---|
| `app/services/intake/translation_router.py` | Route RawArtifact to the correct adapter path. |
| `app/services/intake/normalization.py` | Orchestrate normalization runs, record NormalizedArtifact. |
| `tests/test_intake_translation.py` | Supported files normalize; held files explain why; quarantined do not normalize; warnings surface. |

### New Directory Structure

| Path | Contents |
|---|---|
| `02_NORMALIZED/<batch_id>/` | Normalized artifact outputs. |

### File Handling Matrix

| File type | Preservation | Normalization | Interpreter | Safety lane | Adapter |
|---|---|---|---|---|---|
| `.md` / `.markdown` | yes | direct | yes | accept | `markdown_direct` |
| `.txt` | yes | direct | yes | accept | `text_direct` |
| `.html` / `.htm` | yes | neutralize | yes (with warnings) | hold → accept | `html_adapter` |
| `.json` / `.jsonl` | yes | direct | schema-dependent | accept / hold | `json_direct` |
| `.yaml` / `.yml` | yes | direct | schema-dependent | accept / hold | `yaml_direct` |
| `.csv` | yes | direct / profile | limited | accept / hold | `csv_direct` |
| code files | yes | direct | structural only | accept / hold | `code_direct` |
| `.pdf` | if allowed | hold | false unless adapter | hold | `pdf_hold` |
| `.docx` | if allowed | hold | false unless adapter | hold | `docx_hold` |
| images | if allowed | hold | false unless adapter | hold | `image_hold` |
| archives | metadata only | no auto-unpack | false | quarantine | `archive_hold` |
| executables | usually no | never | false | quarantine | `executable_block` |
| unknown binary | policy | no | false | hold / quarantine | `unsupported` |
| temp/partial | ignore | no | false | ignore | — |

---

## Phase 6 — Interpretation and Queryability Handoff (COMPLETE)

**Scope:** Evidence candidate handoff, queryability classifier, Planar Governance handoff packet, advisory-queryable state. Only interpreted/gated material can become queryable. Queryable material remains advisory unless a separate canon workflow acts.

**Delivered:** `queryability.py`, `interpretation.py`, `governance_handoff.py` — 26 tests in `tests/test_intake_queryability.py`. MIN_QUERYABLE_WORDS=5. Single whole-document EvidenceUnit produced per normalized artifact. HandoffPacket enforces canon_eligible=False in __post_init__.

### New Modules

| File | Purpose |
|---|---|
| `app/services/intake/interpretation.py` | Evidence extraction handoff. |
| `app/services/intake/queryability.py` | Queryability classifier; advisory-queryable state management. |
| `app/services/intake/governance_handoff.py` | Build and emit HandoffPacket to Planar Governance. |
| `tests/test_intake_queryability.py` | Advisory-queryable gate, canon_eligible stays false. |

### New Directory Structure

| Path | Contents |
|---|---|
| `03_GRAPH/<batch_id>/` | Graph extraction outputs. |
| `04_PLANAR/<batch_id>/` | Planar governance handoff packets. |
| `07_LEDGER/intake_capabilities.jsonl` | Capability audit ledger. |
| `07_LEDGER/event_log.jsonl` | Trace event log. |
| `07_LEDGER/adapter_runs.jsonl` | Adapter run log. |
| `07_LEDGER/safety_lane_transitions.jsonl` | Safety lane transition log. |

---

## Phase 7 — API and Database Integration (COMPLETE)

**Scope:** API endpoints for capabilities, adapters, lanes, quarantine, and pipeline run. New DB tables for durable query state. UI panels are deferred to future work.

**Delivered:** `db_writer.py`, `intake_routes.py` — 21 tests in `tests/test_intake_routes.py`. 6 new SQLite tables. Schema version v2.7.0-phase-intake. Actual routes delivered differ from planned routes (see below).

### Actual API Routes Delivered

| Route | Method | Purpose | Auth |
|---|---|---|---|
| `/api/intake/capabilities` | `GET` | List capabilities (filter: lifecycle_state, safety_lane, batch_id). | Read-only. |
| `/api/intake/capabilities/{id}` | `GET` | Single capability by ID. | Read-only. |
| `/api/intake/adapters` | `GET` | Adapter coverage report + capability summary. | Read-only. |
| `/api/intake/safety-lanes` | `GET` | Lane counts grouped by safety_lane. | Read-only. |
| `/api/intake/quarantine` | `GET` | Paginated quarantine records. | Read-only. |
| `/api/intake/run` | `POST` | Full single-file pipeline: capability -> preserve -> route -> normalize -> assess -> interpret -> handoff + DB persist. | Operator token. |

### New Router File

| File | Prefix | Purpose |
|---|---|---|
| `app/api/routes/intake_routes.py` | `/api/intake` | All intake layer read routes and operator-gated pipeline run. |

### New DB Tables (SQLite, added via additive executescript)

| Table | Purpose |
|---|---|
| `intake_capabilities` | Durable IntakeCapability records (canon_eligible always 0). |
| `intake_raw_artifacts` | RawArtifact records (preservation truth index). |
| `intake_normalized_artifacts` | NormalizedArtifact records. |
| `intake_adapter_runs` | Per-run adapter execution records. |
| `intake_quarantine_records` | QuarantineRecord entries. |
| `intake_trace_events` | Trace event log. |

### UI Panels (Deferred — Future Work)

Ingestion Dashboard, Capability Matrix, Adapter Coverage Map, and Translation Queue are planned but not yet built. The API endpoints listed above expose the data needed by these panels.

### Status Language for Future UI

Use: `Discovered`, `Preserved`, `Held`, `Normalized`, `Interpreted`, `Advisory-queryable`, `Quarantined`, `Ignored`.

Never use: `Ingested`, `Imported successfully`, `Added to library`, `Understood`, `Trusted`, `Ready for canon` -- unless the exact capability state supports the claim.

---

## Phase 8 — Replay, Backpressure, and Scheduler (COMPLETE)

**Scope:** Single-file replay, background scan scheduler, backpressure via in-flight counter. Runs must be idempotent.

**Delivered:** `replay.py`, `app/services/scheduler/background_services.py` — 14 tests in `tests/test_intake_scheduler.py`. Scheduler disabled by default; enabled via `BOH_INTAKE_SCHEDULER_ENABLED=true`.

### New Modules

| File | Purpose |
|---|---|
| `app/services/intake/replay.py` | `reprocess()` re-runs held/failed capability through full pipeline + DB update; `list_replayable()` returns non-quarantined held capabilities. |
| `app/services/scheduler/__init__.py` | Package stub. |
| `app/services/scheduler/background_services.py` | `start_if_enabled()` daemon scan loop; backpressure via `_in_flight_count`; disabled by default. |
| `tests/test_intake_scheduler.py` | Scheduler enable/disable, backpressure, scan dispatch, in-flight counting. |

### New Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `BOH_INTAKE_SCHEDULER_ENABLED` | `false` | Enable background scheduled scan. Must be explicit. |
| `BOH_WATCH_PATH` | unset | Directory to watch when scheduler is enabled. |
| `BOH_INTAKE_BACKPRESSURE_MAX` | `10` | Max concurrent in-flight pipeline runs. |
| `BOH_INTAKE_SCAN_INTERVAL` | `30` | Seconds between watch-path scans. |
| `BOH_INTAKE_IGNORE_PATTERNS` | unset | Comma-separated discovery ignore patterns (fnmatch) added to the built-in defaults; no-op when unset/blank. Used at the full corpus-activation gate (C4) to exclude a generated SQLite index file from the watched corpus (e.g. under `<watch-root>`). |
| `BOH_INTAKE_DRAIN_TIMEOUT` | `30` | Bounded drain timeout for scheduler `stop()` (seconds). Validated `0.001–3600` at start. |

### Job Modes

| Mode | Trigger | Notes |
|---|---|---|
| `scheduled_scan` | BOH scheduler | Periodic watch-path scan. |
| `manual_scan` | API / CLI | Operator-initiated immediate scan. |
| `single_file_replay` | API | Re-run full pipeline for one file. |
| `batch_replay` | API | Re-run pipeline for all files in a batch. |
| `adapter_dry_run` | API | Test adapter on a file without writing RAW. |
| `capability_rebuild` | API | Recompute capability record from existing RAW artifacts. |
| `normalization_rebuild` | API | Re-run normalization on existing RAW artifacts. |
| `queryability_recheck` | API | Re-evaluate queryability classifier for a batch. |

### Stable ID Rules

| Record | ID derivation |
|---|---|
| `IntakeCapability` | `hash(source_ref + source_size + source_mtime + initial_sha256_or_seen_token + policy_snapshot_hash)` |
| `RawArtifact` | `hash(source_ref + sha256 + preservation_policy_version)` |
| `AdapterRun` | `hash(raw_artifact_id + adapter_id + adapter_version + policy_snapshot_hash)` |
| `NormalizedArtifact` | `hash(raw_artifact_id + adapter_run_id + output_hash)` |
| `SafetyLaneTransition` | `hash(intake_capability_id + from_lane + to_lane + reason + actor_or_job + timestamp_bucket)` |

### Replay Invariants

- Same file + same hash + same policy: must not create duplicate RAW content.
- Same RAW + same adapter: must not create duplicate normalized output.
- Same unsupported file: must keep same `required_adapter`/`failure_reason` unless policy changed.
- Same quarantine decision: must remain stable unless review changes it.
- Replay must never promote canon.
- Every replay run must produce: job record, job events, IntakeCapability changes, trace events, summary report, UI-visible status.

---

## Cross-Phase Invariants (All Phases)

These rules apply at every phase and must never be violated:

```
BOH is the host application and authority surface.
The intake layer may not have independent canon rules, trust decisions, or source-of-truth hierarchy.
Discovery does not imply preservation.
Preservation does not imply interpretation.
Normalization does not imply authority.
Queryability does not imply canon eligibility.
canon_eligible defaults to False and is never set by the intake layer.
Every file must receive an IntakeCapability record.
Every unsupported, held, or quarantined file must carry a failure_reason.
Every background run must produce job events, trace events, and UI-visible status.
The intake layer may not promote canon, approve trust, resolve conflicts silently, or bypass planar governance.
External schedulers may trigger BOH but must not create independent job records.
UI is display only; it may not overwrite ledger or capability state.
LLM behavior is optional, downstream, and advisory. Never authoritative.
```

---

## Known Naming Conflict Watchpoints

| Name | Existing | Risk |
|---|---|---|
| `ContextPack` | `app.core.context_pack` | Buildspec also names ContextPack. Do not add a second model with divergent semantics. Use `ContextPackRef` in Phase 1. |
| `PlaneCard` | `app.core.plane_card` | Extend or wrap, do not fork. |
| `CorrectionLedger` / `MistakeEvent` / `PatchProposal` | `app.core.correction_ledger`, `app.core.planar_fixtures` | Align buildspec types with existing ledger; do not create parallel tables. |
| `GateResult` | `app.core.planar_gate` | Phase 1 uses `GateResultRef` only; full alignment deferred to Phase 6. |
| `QuarantineRecord` | Folder-level behavior only today | Phase 7 adds typed DB persistence; must not conflict with existing workspace quarantine folder logic. |
| `ReviewProposal` | Overlaps approval requests + LLM queue | Map deliberately before adding a DB table. |
| `BOH_DATA` | Not yet declared | Do not introduce a parallel runtime root alongside `BOH_LIBRARY` without a recorded boundary decision. |
| `app/services/retrieval/` | Current retrieval lives in `app/core/retrieval.py` | Do not create this folder during intake work; it would risk split-brain retrieval behavior. |
