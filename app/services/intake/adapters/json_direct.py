"""Adapter metadata for JSON/JSONL direct staging."""

from app.core.planar_service_schemas import AdapterMetadata

METADATA = AdapterMetadata(
    adapter_id="json_direct",
    adapter_version="0.1.0",
    supported_extensions=[".json", ".jsonl"],
    supported_media_types=["application/json", "application/x-ndjson"],
    can_preserve=True,
    can_normalize=True,
    can_interpret=True,
    can_make_queryable=True,
    requires_sandbox=False,
    fetches_remote_assets=False,
    executes_content=False,
    output_types=["NormalizedArtifact", "EvidenceUnitCandidate"],
    known_losses=[],
    warning_types=["invalid_json_hold", "schema_unknown_hold"],
    default_safety_lane="accept",
)
