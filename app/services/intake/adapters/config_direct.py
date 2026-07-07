"""Adapter metadata for inert configuration/text-structured files."""

from app.core.planar_service_schemas import AdapterMetadata

METADATA = AdapterMetadata(
    adapter_id="config_direct",
    adapter_version="0.1.0",
    supported_extensions=[
        ".toml", ".ini", ".cfg", ".conf", ".properties", ".env.example",
    ],
    supported_media_types=[],
    can_preserve=True,
    can_normalize=True,
    can_interpret=True,
    can_make_queryable=True,
    requires_sandbox=False,
    fetches_remote_assets=False,
    executes_content=False,
    output_types=["NormalizedArtifact", "EvidenceUnitCandidate"],
    known_losses=["runtime_semantics"],
    warning_types=["configuration_not_executed"],
    default_safety_lane="accept",
)
