"""Adapter metadata for PDF hold.

PDFs may be preserved but are not interpreted unless a sandboxed PDF
extraction adapter is explicitly installed and enabled.
"""

from app.core.planar_service_schemas import AdapterMetadata

METADATA = AdapterMetadata(
    adapter_id="pdf_hold",
    adapter_version="0.1.0",
    supported_extensions=[".pdf"],
    supported_media_types=["application/pdf"],
    can_preserve=True,
    can_normalize=False,   # requires sandboxed extractor
    can_interpret=False,   # not interpretable without adapter
    can_make_queryable=False,
    requires_sandbox=True,
    fetches_remote_assets=False,
    executes_content=False,
    output_types=[],
    known_losses=["text_extraction", "structure_extraction"],
    warning_types=["pdf_held_pending_adapter"],
    default_safety_lane="hold",
)
