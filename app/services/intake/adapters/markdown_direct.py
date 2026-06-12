"""Adapter metadata for Markdown direct staging."""

from app.core.planar_service_schemas import AdapterMetadata

METADATA = AdapterMetadata(
    adapter_id="markdown_direct",
    adapter_version="0.1.0",
    supported_extensions=[".md", ".markdown"],
    supported_media_types=["text/markdown", "text/x-markdown"],
    can_preserve=True,
    can_normalize=True,
    can_interpret=True,
    can_make_queryable=True,
    requires_sandbox=False,
    fetches_remote_assets=False,
    executes_content=False,
    output_types=["NormalizedArtifact", "EvidenceUnitCandidate"],
    known_losses=[],
    warning_types=["frontmatter_parse_warning"],
    default_safety_lane="accept",
)
