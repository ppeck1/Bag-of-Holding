"""Adapter metadata for source code direct staging (read-only, never executed)."""

from app.core.planar_service_schemas import AdapterMetadata

METADATA = AdapterMetadata(
    adapter_id="code_direct",
    adapter_version="0.1.0",
    supported_extensions=[
        ".py", ".js", ".ts", ".tsx", ".jsx",
        ".go", ".rs", ".java", ".c", ".cpp", ".h", ".hpp",
        ".rb", ".php", ".swift", ".kt", ".scala",
        ".sh", ".bash", ".zsh", ".fish",
        ".sql", ".r", ".lua", ".dart",
    ],
    supported_media_types=["text/x-python", "text/javascript", "text/x-go", "application/x-sh"],
    can_preserve=True,
    can_normalize=True,
    can_interpret=True,
    can_make_queryable=True,
    requires_sandbox=False,
    fetches_remote_assets=False,
    executes_content=False,  # INVARIANT: source code is never executed by the adapter
    output_types=["NormalizedArtifact", "EvidenceUnitCandidate"],
    known_losses=["execution_semantics"],
    warning_types=["shell_script_not_executed"],
    default_safety_lane="accept",
)
