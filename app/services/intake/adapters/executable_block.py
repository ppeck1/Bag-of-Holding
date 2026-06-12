"""Adapter metadata for executable block.

Executables are blocked before preservation.  They receive an
IntakeCapability record with safety_lane=quarantine and are never
copied to RAW, normalized, or made queryable.
"""

from app.core.planar_service_schemas import AdapterMetadata

METADATA = AdapterMetadata(
    adapter_id="executable_block",
    adapter_version="0.1.0",
    supported_extensions=[
        ".exe", ".bat", ".cmd", ".com", ".msi",
        ".dmg", ".app", ".deb", ".rpm",
        ".ps1", ".psm1", ".psd1",
    ],
    supported_media_types=[
        "application/x-executable",
        "application/x-msdownload",
        "application/x-dosexec",
        "application/x-msdos-program",
    ],
    can_preserve=False,
    can_normalize=False,
    can_interpret=False,
    can_make_queryable=False,
    requires_sandbox=False,
    fetches_remote_assets=False,
    executes_content=False,  # blocked entirely; never executed
    output_types=[],
    known_losses=[],
    warning_types=["executable_blocked"],
    default_safety_lane="quarantine",
)
