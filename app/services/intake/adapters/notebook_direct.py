"""Adapter metadata for Jupyter notebooks extracted as inert text."""

from app.core.planar_service_schemas import AdapterMetadata

METADATA = AdapterMetadata(
    adapter_id="notebook_direct",
    adapter_version="0.1.0",
    supported_extensions=[".ipynb"],
    supported_media_types=["application/x-ipynb+json"],
    can_preserve=True,
    can_normalize=True,
    can_interpret=True,
    can_make_queryable=True,
    requires_sandbox=False,
    fetches_remote_assets=False,
    executes_content=False,
    output_types=["NormalizedArtifact", "EvidenceUnitCandidate"],
    known_losses=["cell_outputs", "execution_state", "widget_state"],
    warning_types=["notebook_code_not_executed", "notebook_outputs_dropped"],
    default_safety_lane="accept",
)
