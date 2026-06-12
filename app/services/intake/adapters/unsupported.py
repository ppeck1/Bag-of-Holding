"""Adapter metadata for unsupported/unknown file types.

Fails closed: records required_adapter and failure_reason, routes to
hold or quarantine, never normalizes or interprets.
"""

from app.core.planar_service_schemas import AdapterMetadata

METADATA = AdapterMetadata(
    adapter_id="unsupported",
    adapter_version="0.1.0",
    supported_extensions=[],   # catch-all; matched only when no other adapter claims the extension
    supported_media_types=[],
    can_preserve=False,
    can_normalize=False,
    can_interpret=False,
    can_make_queryable=False,
    requires_sandbox=False,
    fetches_remote_assets=False,
    executes_content=False,
    output_types=[],
    known_losses=[],
    warning_types=["unsupported_type_hold"],
    default_safety_lane="hold",
)
