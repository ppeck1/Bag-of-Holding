"""SHA-256 hashing helpers for the BOH intake layer."""

from __future__ import annotations

import hashlib
from pathlib import Path

BLOCK_SIZE = 65536


def sha256_file(path: str) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(BLOCK_SIZE):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
