"""Discovery service for the BOH Governed Ingestion & Translation Layer.

Scans configured watch paths, excludes partial/temp files and ignored
patterns, and yields candidate file paths for further pipeline stages.

Contract:
- Returns paths only; does not create IntakeCapability records itself.
- Never writes to disk.
- Never reads from BOH_LIBRARY; operates on separately configured watch paths.
- Temp/partial files are excluded by default patterns.
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path


# Default exclusion patterns for partial/temp files
DEFAULT_IGNORE_PATTERNS: list[str] = [
    "*.crdownload",   # Chrome partial download
    "*.part",         # Firefox/wget partial download
    "*.tmp",          # Generic temp file
    "*.~lock.*",      # LibreOffice lock files
    ".~lock.*",       # LibreOffice lock files (dot prefix)
    "~$*",            # MS Office temp files
    "*.swp",          # Vim swap files
    "*.swo",          # Vim swap files
    ".DS_Store",      # macOS metadata
    "Thumbs.db",      # Windows thumbnail cache
    "__pycache__",    # Python cache (directory)
    "*.pyc",          # Python bytecode
    ".git",           # Git directory
]


@dataclass
class DiscoveryResult:
    watch_path: str
    candidates: list[str] = field(default_factory=list)
    excluded: list[tuple[str, str]] = field(default_factory=list)  # (path, reason)
    error: str | None = None


def _is_excluded(name: str, path: str, ignore_patterns: list[str]) -> tuple[bool, str]:
    """Return (excluded, reason) for a file or directory name."""
    for pattern in ignore_patterns:
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(path, pattern):
            return True, f"Matches ignore pattern '{pattern}'."
    return False, ""


def scan(
    watch_path: str,
    ignore_patterns: list[str] | None = None,
    recursive: bool = True,
) -> DiscoveryResult:
    """Scan a directory and return candidate file paths.

    Directories matching ignore patterns are skipped entirely (not descended).
    Files matching ignore patterns are recorded in result.excluded.
    """
    patterns = (ignore_patterns or []) + DEFAULT_IGNORE_PATTERNS
    result = DiscoveryResult(watch_path=watch_path)

    root = Path(watch_path)
    if not root.exists():
        result.error = f"Watch path does not exist: {watch_path}"
        return result
    if not root.is_dir():
        result.error = f"Watch path is not a directory: {watch_path}"
        return result

    def _walk(directory: Path) -> None:
        try:
            entries = sorted(directory.iterdir())
        except PermissionError as exc:
            result.excluded.append((str(directory), f"Permission denied: {exc}"))
            return

        for entry in entries:
            name = entry.name
            excluded, reason = _is_excluded(name, str(entry), patterns)
            if excluded:
                result.excluded.append((str(entry), reason))
                continue
            if entry.is_dir():
                if recursive:
                    _walk(entry)
                continue
            if entry.is_file():
                result.candidates.append(str(entry))

    _walk(root)
    return result


def scan_paths(
    watch_paths: list[str],
    ignore_patterns: list[str] | None = None,
    recursive: bool = True,
) -> list[DiscoveryResult]:
    """Scan multiple watch paths and return one DiscoveryResult per path."""
    return [scan(wp, ignore_patterns=ignore_patterns, recursive=recursive) for wp in watch_paths]
