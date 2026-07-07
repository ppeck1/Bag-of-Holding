"""Adapter metadata for inert markup/reference text files."""

from app.core.planar_service_schemas import AdapterMetadata

METADATA = AdapterMetadata(
    adapter_id="markup_direct",
    adapter_version="0.1.0",
    supported_extensions=[".rst", ".mdx", ".tex", ".bib", ".xml", ".log"],
    supported_media_types=[
        "text/x-rst",
        "application/xml",
        "text/xml",
        "text/x-tex",
    ],
    can_preserve=True,
    can_normalize=True,
    can_interpret=True,
    can_make_queryable=True,
    requires_sandbox=False,
    fetches_remote_assets=False,
    executes_content=False,
    output_types=["NormalizedArtifact", "EvidenceUnitCandidate"],
    known_losses=["rendering_semantics"],
    warning_types=["markup_treated_as_text"],
    default_safety_lane="accept",
)
