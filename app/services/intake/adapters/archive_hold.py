"""Adapter metadata for archive quarantine.

Archives are registered with metadata only.  Auto-unpack is never
performed.  All archives go to quarantine pending explicit review.
"""

from app.core.planar_service_schemas import AdapterMetadata

METADATA = AdapterMetadata(
    adapter_id="archive_hold",
    adapter_version="0.1.0",
    supported_extensions=[".zip", ".tar", ".gz", ".bz2", ".xz", ".rar", ".7z", ".tar.gz", ".tgz"],
    supported_media_types=[
        "application/zip",
        "application/x-tar",
        "application/gzip",
        "application/x-bzip2",
        "application/x-rar-compressed",
        "application/x-7z-compressed",
    ],
    can_preserve=False,    # metadata only; no content copy by default
    can_normalize=False,   # auto-unpack is prohibited
    can_interpret=False,
    can_make_queryable=False,
    requires_sandbox=True,
    fetches_remote_assets=False,
    executes_content=False,
    output_types=[],
    known_losses=["archive_contents"],
    warning_types=["archive_quarantined_no_unpack"],
    default_safety_lane="quarantine",
)
