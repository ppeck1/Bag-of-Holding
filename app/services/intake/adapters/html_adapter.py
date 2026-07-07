"""Adapter metadata for HTML neutralizing adapter.

Scripts, forms, and iframes are stripped and recorded as warnings.
HTML is treated as hostile text until neutralized.
"""

from app.core.planar_service_schemas import AdapterMetadata

METADATA = AdapterMetadata(
    adapter_id="html_adapter",
    adapter_version="0.1.0",
    supported_extensions=[".html", ".htm"],
    supported_media_types=["text/html"],
    can_preserve=True,
    can_normalize=True,
    can_interpret=True,
    can_make_queryable=True,
    requires_sandbox=False,
    fetches_remote_assets=False,  # remote assets are never fetched
    executes_content=False,        # scripts are stripped, never executed
    output_types=["NormalizedArtifact", "EvidenceUnitCandidate"],
    known_losses=["interactive_behavior", "layout_precision", "script_behavior"],
    warning_types=["script_stripped", "form_stripped", "iframe_removed", "remote_asset_not_fetched"],
    default_safety_lane="hold",
)
