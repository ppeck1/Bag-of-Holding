"""Adapter metadata for YAML direct staging (unsafe tags treated as text)."""

from app.core.planar_service_schemas import AdapterMetadata

METADATA = AdapterMetadata(
    adapter_id="yaml_direct",
    adapter_version="0.1.0",
    supported_extensions=[".yaml", ".yml"],
    supported_media_types=["application/yaml", "text/yaml"],
    can_preserve=True,
    can_normalize=True,
    can_interpret=True,
    can_make_queryable=True,
    requires_sandbox=False,
    fetches_remote_assets=False,
    executes_content=False,
    output_types=["NormalizedArtifact", "EvidenceUnitCandidate"],
    known_losses=[],
    warning_types=["unsafe_yaml_tag_stripped", "schema_unknown_hold"],
    default_safety_lane="accept",
)
