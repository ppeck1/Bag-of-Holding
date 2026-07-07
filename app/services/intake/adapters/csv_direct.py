"""Adapter metadata for CSV direct staging with large-file profiling fallback."""

from app.core.planar_service_schemas import AdapterMetadata

METADATA = AdapterMetadata(
    adapter_id="csv_direct",
    adapter_version="0.1.0",
    supported_extensions=[".csv", ".tsv"],
    supported_media_types=["text/csv", "text/tab-separated-values"],
    can_preserve=True,
    can_normalize=True,
    can_interpret=True,
    can_make_queryable=True,
    requires_sandbox=False,
    fetches_remote_assets=False,
    executes_content=False,
    output_types=["NormalizedArtifact", "EvidenceUnitCandidate"],
    known_losses=["large_file_profile_only"],
    warning_types=["large_file_profile_fallback"],
    default_safety_lane="accept",
)
