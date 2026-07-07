"""Adapter metadata for legacy office-document hold.

DOC and ODT files may be preserved but normalization requires a sandboxed
converter that is disabled by default. DOCX is handled by docx_text.
"""

from app.core.planar_service_schemas import AdapterMetadata

METADATA = AdapterMetadata(
    adapter_id="docx_hold",
    adapter_version="0.1.0",
    supported_extensions=[".doc", ".odt"],
    supported_media_types=[
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
        "application/vnd.oasis.opendocument.text",
    ],
    can_preserve=True,
    can_normalize=False,   # sandbox converter required
    can_interpret=False,
    can_make_queryable=False,
    requires_sandbox=True,
    fetches_remote_assets=False,
    executes_content=False,
    output_types=[],
    known_losses=["text_extraction", "formatting"],
    warning_types=["docx_held_sandbox_disabled"],
    default_safety_lane="hold",
)
