"""Adapter metadata for image hold.

Images may be preserved but require an explicit image interpretation
adapter (OCR, vision) before they can be normalized or queried.
"""

from app.core.planar_service_schemas import AdapterMetadata

METADATA = AdapterMetadata(
    adapter_id="image_hold",
    adapter_version="0.1.0",
    supported_extensions=[".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".tiff", ".tif"],
    supported_media_types=[
        "image/png", "image/jpeg", "image/gif",
        "image/webp", "image/svg+xml", "image/bmp", "image/tiff",
    ],
    can_preserve=True,
    can_normalize=False,   # image interpretation adapter required
    can_interpret=False,
    can_make_queryable=False,
    requires_sandbox=False,
    fetches_remote_assets=False,
    executes_content=False,
    output_types=[],
    known_losses=["visual_content", "text_in_image"],
    warning_types=["image_held_pending_interpreter"],
    default_safety_lane="hold",
)
