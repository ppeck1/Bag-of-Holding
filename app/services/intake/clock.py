"""Shared UTC timestamp formatter for intake orchestration (WO-1).

DRAFT — supports the `0001_intake_orchestration_integrity` schema-review gate.

One normalized UTC ISO-8601 (`...Z`) formatter, shared rather than recreated per caller, so the
ledgers (`intake_source_revisions`, `intake_runs`) carry consistent timestamps across manual
intake, replay, and scheduler execution. The existing `db_writer._now()` is consolidated onto
this during the orchestrator/writer work (Gate B).
"""

from __future__ import annotations

import time

_FMT = "%Y-%m-%dT%H:%M:%SZ"


def utc_now_iso() -> str:
    """Current UTC time as ISO-8601 with a trailing 'Z' (second resolution)."""
    return time.strftime(_FMT, time.gmtime())


def utc_iso_in(seconds: float) -> str:
    """UTC ISO-8601 (Z) `seconds` from now — used for claim-lease expiry. Same formatter so
    timestamps compare lexicographically with `utc_now_iso()`."""
    return time.strftime(_FMT, time.gmtime(time.time() + seconds))
