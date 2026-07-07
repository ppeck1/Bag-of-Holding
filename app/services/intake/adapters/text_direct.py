"""Adapter metadata for plain text direct staging."""

from app.core.planar_service_schemas import AdapterMetadata

METADATA = AdapterMetadata(
    adapter_id="text_direct",
    adapter_version="0.1.0",
    supported_extensions=[".txt"],
    supported_media_types=["text/plain"],
    can_preserve=True,
    can_normalize=True,
    can_interpret=True,
    can_make_queryable=True,
    requires_sandbox=False,
    fetches_remote_assets=False,
    executes_content=False,
    output_types=["NormalizedArtifact", "EvidenceUnitCandidate"],
    known_losses=["structure"],
    warning_types=[],
    default_safety_lane="accept",
)
