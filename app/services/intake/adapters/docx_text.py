"""Adapter metadata for DOCX text extraction using stdlib ZIP/XML parsing."""

from app.core.planar_service_schemas import AdapterMetadata

METADATA = AdapterMetadata(
    adapter_id="docx_text",
    adapter_version="0.1.0",
    supported_extensions=[".docx"],
    supported_media_types=[
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ],
    can_preserve=True,
    can_normalize=True,
    can_interpret=True,
    can_make_queryable=True,
    requires_sandbox=False,
    fetches_remote_assets=False,
    executes_content=False,
    output_types=["NormalizedArtifact", "EvidenceUnitCandidate"],
    known_losses=["layout_precision", "formatting", "embedded_media", "macros"],
    warning_types=["docx_macros_not_executed", "docx_embedded_media_ignored"],
    default_safety_lane="accept",
)
