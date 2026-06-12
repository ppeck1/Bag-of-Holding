"""Candidate file stabilizer for the BOH intake layer.

A file is considered stable when its size and mtime have not changed
between two observations separated by a short settle interval.  This
prevents processing partially-written files.

No filesystem writes.  Read-only stat calls only.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass


SETTLE_INTERVAL_SECONDS = 0.5
DEFAULT_MAX_WAIT_SECONDS = 5.0


@dataclass
class StabilizationResult:
    path: str
    stable: bool
    reason: str | None = None
    size_bytes: int = 0
    mtime: float = 0.0


def is_stable(
    path: str,
    settle_seconds: float = SETTLE_INTERVAL_SECONDS,
) -> StabilizationResult:
    """Return True if the file size and mtime are unchanged after settle_seconds."""
    try:
        stat1 = os.stat(path)
    except OSError as exc:
        return StabilizationResult(path=path, stable=False, reason=f"stat failed: {exc}")

    time.sleep(settle_seconds)

    try:
        stat2 = os.stat(path)
    except OSError as exc:
        return StabilizationResult(path=path, stable=False, reason=f"stat failed on recheck: {exc}")

    if stat1.st_size != stat2.st_size:
        return StabilizationResult(
            path=path, stable=False,
            reason=f"File size changed during settle ({stat1.st_size} → {stat2.st_size} bytes).",
            size_bytes=stat2.st_size,
            mtime=stat2.st_mtime,
        )
    if stat1.st_mtime != stat2.st_mtime:
        return StabilizationResult(
            path=path, stable=False,
            reason="File mtime changed during settle.",
            size_bytes=stat2.st_size,
            mtime=stat2.st_mtime,
        )

    return StabilizationResult(
        path=path, stable=True,
        size_bytes=stat1.st_size,
        mtime=stat1.st_mtime,
    )
