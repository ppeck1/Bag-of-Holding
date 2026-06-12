"""Schema-only module for BOH Governed Ingestion & Translation Layer.

Phase 1 — records, provenance types, and reference wrappers only.
No database access, no runtime behavior, no route or service wiring.

Core doctrine encoded here:
- discovery != ingestion
- preservation != interpretation
- normalization != authority
- queryability != canon eligibility
- canon_eligible is always False by default and must never be set by the intake layer
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any


SCHEMA_VERSION = "0.1.0"
SERVICE_VERSION = "0.1.0"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str)
    return prefix + hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:24]


# ---------------------------------------------------------------------------
# Shared provenance record
# ---------------------------------------------------------------------------

@dataclass
class VersionProvenance:
    schema_version: str = SCHEMA_VERSION
    service_version: str = SERVICE_VERSION
    adapter_registry_version: str | None = None
    policy_snapshot_hash: str | None = None
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Core intake records
# ---------------------------------------------------------------------------

@dataclass
class IntakeCapability:
    """Central guardrail that prevents collapsing discovery into ingestion.

    All capability booleans start False and must be proven True by each
    pipeline stage.  canon_eligible is re-forced to False in __post_init__
    and must never be set True by the intake layer.
    """

    source_ref: str
    batch_id: str
    intake_capability_id: str = field(default="")
    raw_artifact_id: str | None = None

    # Capability progression — all False until each stage proves otherwise
    discovered: bool = True
    preservable: bool = False
    normalizable: bool = False
    interpretable: bool = False
    queryable: bool = False
    canon_eligible: bool = False  # INVARIANT: always False

    required_adapter: str | None = None
    safety_lane: str = "hold"   # accept | hold | quarantine | ignore
    failure_reason: str | None = None

    lifecycle_state: str = "discovered"  # see LifecycleState values in buildspec
    trust_state: str = "unknown"         # unknown | unreviewed_download | trusted_local | reviewed_source | blocked
    authority_default: str = "none"      # none | advisory | review_required | blocked

    trace_event_refs: list[str] = field(default_factory=list)
    version_provenance: VersionProvenance = field(default_factory=VersionProvenance)

    def __post_init__(self) -> None:
        # Force invariant: the intake layer never grants canon eligibility
        self.canon_eligible = False
        if not self.intake_capability_id:
            self.intake_capability_id = _stable_id(
                "ic_",
                self.source_ref,
                self.batch_id,
                self.version_provenance.policy_snapshot_hash or "no_policy",
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RawArtifact:
    """Immutable preserved copy of a discovered file.

    source_hash_sha256 is computed before copy; preserved_hash_sha256 is
    verified after.  A mismatch quarantines the artifact.
    """

    intake_capability_id: str
    source_ref: str
    batch_id: str
    source_hash_sha256: str
    preserved_hash_sha256: str
    byte_size: int
    preservation_path: str
    raw_artifact_id: str = field(default="")
    media_type: str | None = None
    version_provenance: VersionProvenance = field(default_factory=VersionProvenance)

    def __post_init__(self) -> None:
        if not self.raw_artifact_id:
            self.raw_artifact_id = _stable_id(
                "raw_",
                self.source_ref,
                self.source_hash_sha256,
                self.version_provenance.policy_snapshot_hash or "no_policy",
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NormalizedArtifact:
    """Output produced by a successful adapter normalization run."""

    raw_artifact_id: str
    adapter_run_id: str
    output_path: str
    output_hash_sha256: str
    output_type: str   # markdown | text | json | extracted_units | ...
    normalized_artifact_id: str = field(default="")
    known_losses: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    version_provenance: VersionProvenance = field(default_factory=VersionProvenance)

    def __post_init__(self) -> None:
        if not self.normalized_artifact_id:
            self.normalized_artifact_id = _stable_id(
                "norm_",
                self.raw_artifact_id,
                self.adapter_run_id,
                self.output_hash_sha256,
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceUnit:
    """A span of normalized content eligible for retrieval.

    canon_eligible is re-forced to False in __post_init__.
    """

    normalized_artifact_id: str
    span_start: int
    span_end: int
    unit_type: str  # heading | body | table | frontmatter | claim
    text_hash: str
    evidence_unit_id: str = field(default="")
    authority_default: str = "none"
    canon_eligible: bool = False  # INVARIANT: always False
    version_provenance: VersionProvenance = field(default_factory=VersionProvenance)

    def __post_init__(self) -> None:
        self.canon_eligible = False
        if not self.evidence_unit_id:
            self.evidence_unit_id = _stable_id(
                "eu_",
                self.normalized_artifact_id,
                self.span_start,
                self.span_end,
                self.text_hash,
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Evidence graph records (Phase 4)
# ---------------------------------------------------------------------------

@dataclass
class EvidenceGraphNode:
    """A node in the evidence graph, derived from one EvidenceUnit.

    Carries the originating unit's provenance (span + text_hash) so every
    node traces back to its source. canon_eligible is re-forced to False.
    """

    evidence_unit_id: str
    normalized_artifact_id: str
    node_type: str  # "evidence" | "claim"
    span_start: int
    span_end: int
    text_hash: str
    authority_default: str = "none"
    node_id: str = field(default="")
    canon_eligible: bool = False  # INVARIANT: always False

    def __post_init__(self) -> None:
        self.canon_eligible = False
        if not self.node_id:
            self.node_id = _stable_id(
                "egn_",
                self.evidence_unit_id,
                self.node_type,
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceGraphEdge:
    """A typed, directional relationship between two evidence nodes.

    Only relationships derivable from existing unit fields are emitted as
    edges. Relationships requiring semantic judgement become review items.
    """

    source_node_id: str
    target_node_id: str
    relation: str  # "same_source" | "derives_from"
    reason: str = ""
    edge_id: str = field(default="")

    def __post_init__(self) -> None:
        if not self.edge_id:
            self.edge_id = _stable_id(
                "ege_",
                self.source_node_id,
                self.target_node_id,
                self.relation,
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceReviewItem:
    """A relationship the service refuses to guess.

    Emitted instead of an edge when more than one relation is plausible
    (e.g. supports vs contradicts between two claims). A human resolves it.
    """

    node_ids: list[str]
    candidate_relations: list[str]
    reason: str = ""
    review_item_id: str = field(default="")

    def __post_init__(self) -> None:
        # Normalize ordering so the id is stable regardless of input order.
        self.node_ids = sorted(self.node_ids)
        self.candidate_relations = sorted(self.candidate_relations)
        if not self.review_item_id:
            self.review_item_id = _stable_id(
                "eri_",
                self.node_ids,
                self.candidate_relations,
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceGraphSnapshot:
    """A reproducible snapshot of the evidence graph.

    Deterministic by construction: nodes/edges/review_items are sorted by
    stable id and the snapshot carries no wall-clock timestamp, so building
    twice from the same input yields byte-identical output. canon_eligible
    is re-forced to False.
    """

    nodes: list[EvidenceGraphNode] = field(default_factory=list)
    edges: list[EvidenceGraphEdge] = field(default_factory=list)
    review_items: list[EvidenceReviewItem] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION
    service_version: str = SERVICE_VERSION
    policy_snapshot_hash: str | None = None
    snapshot_id: str = field(default="")
    canon_eligible: bool = False  # INVARIANT: always False

    def __post_init__(self) -> None:
        self.canon_eligible = False
        self.nodes.sort(key=lambda n: n.node_id)
        self.edges.sort(key=lambda e: e.edge_id)
        self.review_items.sort(key=lambda r: r.review_item_id)
        if not self.snapshot_id:
            self.snapshot_id = _stable_id(
                "egs_",
                [n.node_id for n in self.nodes],
                [e.edge_id for e in self.edges],
                [r.review_item_id for r in self.review_items],
                self.policy_snapshot_hash or "no_policy",
            )

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    @property
    def review_item_count(self) -> int:
        return len(self.review_items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "schema_version": self.schema_version,
            "service_version": self.service_version,
            "policy_snapshot_hash": self.policy_snapshot_hash,
            "canon_eligible": self.canon_eligible,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "review_item_count": self.review_item_count,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "review_items": [r.to_dict() for r in self.review_items],
        }


# ---------------------------------------------------------------------------
# Adapter records
# ---------------------------------------------------------------------------

@dataclass
class AdapterMetadata:
    """Declares what an adapter can and cannot do.

    fetches_remote_assets and executes_content must always be False for
    current adapters.
    """

    adapter_id: str
    adapter_version: str
    supported_extensions: list[str]
    supported_media_types: list[str]
    can_preserve: bool
    can_normalize: bool
    can_interpret: bool
    can_make_queryable: bool
    requires_sandbox: bool = False
    fetches_remote_assets: bool = False   # INVARIANT: must stay False
    executes_content: bool = False         # INVARIANT: must stay False
    output_types: list[str] = field(default_factory=list)
    known_losses: list[str] = field(default_factory=list)
    warning_types: list[str] = field(default_factory=list)
    default_safety_lane: str = "hold"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AdapterRun:
    """Record of a single adapter execution against a RawArtifact."""

    adapter_id: str
    adapter_version: str
    raw_artifact_id: str
    intake_capability_id: str
    success: bool
    adapter_run_id: str = field(default="")
    failure_reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    output_artifact_ids: list[str] = field(default_factory=list)
    version_provenance: VersionProvenance = field(default_factory=VersionProvenance)

    def __post_init__(self) -> None:
        if not self.adapter_run_id:
            self.adapter_run_id = _stable_id(
                "ar_",
                self.raw_artifact_id,
                self.adapter_id,
                self.adapter_version,
                self.version_provenance.policy_snapshot_hash or "no_policy",
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SafetyLaneTransition:
    """Records a lane change event for an IntakeCapability."""

    intake_capability_id: str
    from_lane: str
    to_lane: str
    reason: str
    actor_or_job: str
    transition_id: str = field(default="")
    version_provenance: VersionProvenance = field(default_factory=VersionProvenance)

    def __post_init__(self) -> None:
        if not self.transition_id:
            ts_bucket = self.version_provenance.created_at[:16]
            self.transition_id = _stable_id(
                "slt_",
                self.intake_capability_id,
                self.from_lane,
                self.to_lane,
                self.reason,
                self.actor_or_job,
                ts_bucket,
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Job records
# ---------------------------------------------------------------------------

@dataclass
class IngestionJob:
    """A scheduled or manual ingestion run owned by BOH."""

    job_mode: str   # scheduled_scan | manual_scan | single_file_replay | batch_replay | ...
    job_id: str = field(default="")
    batch_id: str | None = None
    status: str = "pending"   # pending | running | complete | failed | paused
    started_at: str | None = None
    completed_at: str | None = None
    version_provenance: VersionProvenance = field(default_factory=VersionProvenance)

    def __post_init__(self) -> None:
        if not self.job_id:
            self.job_id = _stable_id(
                "job_",
                self.job_mode,
                self.version_provenance.created_at,
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IngestionJobEvent:
    """An event within a job run."""

    job_id: str
    event_type: str
    message: str
    event_id: str = field(default="")
    intake_capability_id: str | None = None
    version_provenance: VersionProvenance = field(default_factory=VersionProvenance)

    def __post_init__(self) -> None:
        if not self.event_id:
            self.event_id = _stable_id(
                "je_",
                self.job_id,
                self.event_type,
                self.version_provenance.created_at,
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Governance handoff
# ---------------------------------------------------------------------------

@dataclass
class HandoffPacket:
    """State handed from the intake layer to Planar Governance.

    Raises ValueError if capability_state claims canon_eligible=True, since
    the intake layer has no authority to grant that.
    """

    intake_capability_id: str
    capability_state: dict[str, Any]
    safety_lane: str
    handoff_id: str = field(default="")
    raw_artifact_id: str | None = None
    normalized_artifact_id: str | None = None
    evidence_candidate_refs: list[str] = field(default_factory=list)
    required_adapter: str | None = None
    failure_reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    trace_event_refs: list[str] = field(default_factory=list)
    version_provenance: VersionProvenance = field(default_factory=VersionProvenance)

    def __post_init__(self) -> None:
        if self.capability_state.get("canon_eligible"):
            raise ValueError(
                "HandoffPacket.capability_state.canon_eligible must be False; "
                "the intake layer cannot grant canon eligibility"
            )
        if not self.handoff_id:
            self.handoff_id = _stable_id(
                "hoff_",
                self.intake_capability_id,
                self.raw_artifact_id or "no_raw",
                self.version_provenance.created_at,
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Audit and trace
# ---------------------------------------------------------------------------

@dataclass
class TraceEvent:
    """An individual audit event emitted during intake processing."""

    event_type: str
    trace_event_id: str = field(default="")
    intake_capability_id: str | None = None
    job_id: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    version_provenance: VersionProvenance = field(default_factory=VersionProvenance)

    def __post_init__(self) -> None:
        if not self.trace_event_id:
            self.trace_event_id = _stable_id(
                "te_",
                self.event_type,
                self.intake_capability_id or "no_cap",
                self.job_id or "no_job",
                self.version_provenance.created_at,
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QuarantineRecord:
    """Record of a file that was quarantined."""

    intake_capability_id: str
    quarantine_reason: str
    quarantine_category: str  # archive_pending_review | executable_blocked | unsupported | suspicious | failed_hash | source_trust_unknown
    review_required: bool = True
    quarantine_record_id: str = field(default="")
    raw_artifact_id: str | None = None
    released_at: str | None = None
    version_provenance: VersionProvenance = field(default_factory=VersionProvenance)

    def __post_init__(self) -> None:
        if not self.quarantine_record_id:
            self.quarantine_record_id = _stable_id(
                "qr_",
                self.intake_capability_id,
                self.quarantine_category,
                self.version_provenance.created_at,
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Policy and governance types
# ---------------------------------------------------------------------------

@dataclass
class PolicyRule:
    """A named rule entry within a PolicySnapshot."""

    rule_id: str
    rule_name: str
    effect: str   # allow | deny | hold | quarantine | ignore
    target: str
    version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PolicySnapshot:
    """Deterministic hash of active policy rules at a point in time.

    Same rule set always produces the same policy_snapshot_hash.
    """

    rules: list[PolicyRule]
    snapshot_id: str = field(default="")
    policy_snapshot_hash: str = field(default="")
    version_provenance: VersionProvenance = field(default_factory=VersionProvenance)

    def __post_init__(self) -> None:
        rules_blob = json.dumps(
            [r.to_dict() for r in self.rules], sort_keys=True
        )
        self.policy_snapshot_hash = hashlib.sha256(
            rules_blob.encode("utf-8")
        ).hexdigest()
        if not self.snapshot_id:
            self.snapshot_id = _stable_id("ps_", self.policy_snapshot_hash)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RetentionDecision:
    """Retention action and reason for a raw or normalized artifact."""

    artifact_id: str
    artifact_type: str   # raw | normalized
    action: str          # retain | purge | archive | defer
    reason: str
    retention_decision_id: str = field(default="")
    version_provenance: VersionProvenance = field(default_factory=VersionProvenance)

    def __post_init__(self) -> None:
        if not self.retention_decision_id:
            self.retention_decision_id = _stable_id(
                "rd_",
                self.artifact_id,
                self.action,
                self.version_provenance.created_at,
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BackpressureState:
    """Pause/resume state for ingestion flow control."""

    active: bool
    reason: str | None = None
    unreviewed_count: int = 0
    max_unreviewed: int = 100
    paused_at: str | None = None
    version_provenance: VersionProvenance = field(default_factory=VersionProvenance)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SoloOverrideRecord:
    """Operator-acknowledged override of a blocked or held state."""

    intake_capability_id: str
    override_reason: str
    operator_id: str
    overridden_state: str
    solo_override_id: str = field(default="")
    version_provenance: VersionProvenance = field(default_factory=VersionProvenance)

    def __post_init__(self) -> None:
        if not self.solo_override_id:
            self.solo_override_id = _stable_id(
                "so_",
                self.intake_capability_id,
                self.operator_id,
                self.version_provenance.created_at,
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Reference wrappers — handles into existing BOH concepts.
# These avoid duplicating models or creating divergent semantics.
# ---------------------------------------------------------------------------

@dataclass
class GateResultRef:
    """Reference into an existing GateResult (app.core.planar_gate.GateResult).

    advisory_only is re-forced to True; this ref cannot represent a canon
    promotion state.
    """

    gate_result_id: str
    posture: str              # answerable | bounded | review_required | blocked
    advisory_only: bool = True  # INVARIANT: always True

    def __post_init__(self) -> None:
        self.advisory_only = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContextPackRef:
    """Reference into an existing ContextPack (app.core.context_pack)."""

    context_pack_id: str
    do_not_treat_as_canonical: bool = True
    advisory_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlaneCardRef:
    """Reference into an existing PlaneCard."""

    card_id: str
    plane: str
    card_type: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuthorityStateRef:
    """Reference into an existing document authority state."""

    doc_id: str
    authority_state: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConflictSetRef:
    """Reference into an existing conflict set."""

    conflict_id: str
    conflict_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReviewProposalRef:
    """Reference to an intake-layer review proposal.

    Does not grant promotion authority.  canon_eligible is re-forced to False.
    """

    proposal_id: str
    proposal_type: str
    canon_eligible: bool = False  # INVARIANT: always False

    def __post_init__(self) -> None:
        self.canon_eligible = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MistakeEventRef:
    """Reference into an existing MistakeEvent."""

    mistake_id: str
    mistake_class: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PatchProposalRef:
    """Reference into an existing PatchProposal."""

    proposal_id: str
    proposal_type: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CanonChangeRecordRef:
    """Reference into an existing CanonChangeRecord.

    The intake layer cannot issue canon changes; this is a read-only handle.
    """

    record_id: str
    change_type: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InformationResidenceMapRef:
    """Reference into an existing InformationResidenceMap entry."""

    map_id: str
    location: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
