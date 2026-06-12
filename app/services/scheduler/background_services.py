"""Compatibility adapter for the BOH intake scheduler.

SUPERSEDED by `app/services/intake/scheduler_manager.py` (WO-1 Gate B). This module no longer
contains a scan loop, worker-count state, or a pipeline execution path — it only delegates to the
managed `SchedulerManager` so existing import sites keep working. New code should import
`app.services.intake.scheduler_manager` directly.
"""

from __future__ import annotations

import os

from app.services.intake import scheduler_manager as _mgr


def start_if_enabled() -> bool:
    """Start the managed intake scheduler if enabled. Delegates to SchedulerManager."""
    return _mgr.start_if_enabled()


def stop(drain_timeout: float | None = None) -> dict:
    # None -> the manager uses its validated BOH_INTAKE_DRAIN_TIMEOUT; a numeric override still wins.
    return _mgr.stop(drain_timeout=drain_timeout)


def status() -> dict:
    return _mgr.status()


def get_in_flight_count() -> int:
    """Currently-executing intake workers (from the managed scheduler's status)."""
    return _mgr.status().get("active_workers", 0)


def _backpressure_max() -> int:
    """Configured queued-plus-running cap (kept for demo/reporting callers)."""
    try:
        return int(os.environ.get("BOH_INTAKE_BACKPRESSURE_MAX", "10"))
    except ValueError:
        return 10
