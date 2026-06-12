"""Managed intake scheduler component for WO-1 (Gate B / B4).

One lifecycle-managed scheduler that fixes the original race and unboundedness:

- Capacity is a BoundedSemaphore reserved BEFORE executor submission, so queued-plus-running
  work is capped (the executor alone is not the backpressure boundary). cap=0 accepts nothing.
- Each candidate is canonicalized, hashed, and registered as a source revision; only a
  'discovered' revision is eligible. The atomic conditional claim decides the single winner of
  concurrent scans; capacity is released immediately if the claim is lost or submission fails,
  and in `finally` after execution.
- The loop uses `stop_event.wait(interval)` so shutdown is prompt. `start_if_enabled` is a
  lock-protected singleton; `stop` drains in-flight work and the executor; start→stop→start
  yields one clean replacement loop. Expired leases are reconciled on start (fail-closed).
- No silent swallowing: worker and scan-loop failures are logged and recorded.

The pipeline function and executor are injectable for deterministic tests.
"""

from __future__ import annotations

import logging
import math
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from app.db import connection as _dbconn
from app.services.intake import source_revision_service as revsvc
from app.services.intake.adapter_registry import adapter_registry_fingerprint
from app.services.intake.clock import utc_now_iso
from app.services.intake.discovery import scan
from app.services.intake.hashing import sha256_file
from app.services.intake.orchestrator import run_pipeline_for_claimed_revision
from app.services.intake.stabilizer import is_stable

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return os.environ.get("BOH_INTAKE_SCHEDULER_ENABLED", "false").lower() == "true"


def _policy_bind() -> str | None:
    return os.environ.get("BOH_INTAKE_POLICY_SNAPSHOT_BIND") or None


def _ignore_patterns() -> list[str] | None:
    """Custom discovery ignore patterns from BOH_INTAKE_IGNORE_PATTERNS (comma-separated).

    Returns None when unset/empty, so discovery applies ONLY its built-in defaults — the
    scheduler's behavior is unchanged unless an operator explicitly configures exclusions.
    """
    raw = os.environ.get("BOH_INTAKE_IGNORE_PATTERNS", "")
    pats = [p.strip() for p in raw.split(",") if p.strip()]
    return pats or None


def _norm(path: str) -> str:
    """Canonical, case-folded, symlink-resolved absolute path (Windows-safe comparison key)."""
    return os.path.normcase(os.path.abspath(os.path.realpath(path)))


def _contains_or_equal(parent: str, child: str) -> bool:
    p, c = _norm(parent), _norm(child)
    return p == c or c.startswith(p + os.sep)


def _overlaps(a: str, b: str) -> bool:
    return _contains_or_equal(a, b) or _contains_or_equal(b, a)


def _validate_layout(watch: str, data_root: str) -> str | None:
    """WO-1.1 P0: return a structured reason if the root layout is unsafe, else None.

    Uses canonical, case-folded, resolved paths and rejects ancestor-or-descendant overlap between
    the watched tree and the data root / library / DB — so the scheduler can never discover its own
    staging output, the managed library, or the live database. Also rejects a non-directory watch
    path and an uncreatable data root.
    """
    if not os.path.isdir(watch):
        return f"watch_not_a_directory:{watch}"
    try:
        os.makedirs(data_root, exist_ok=True)
    except OSError as exc:
        return f"data_root_uncreatable:{exc}"
    # Writability probe with a UNIQUE, exclusively-created name (never a fixed name a user file could
    # share); remove only the probe this call created, in a finally.
    probe = None
    try:
        fd, probe = tempfile.mkstemp(dir=data_root, prefix=".boh_intake_write_probe.")
        os.write(fd, b"x")
        os.close(fd)
    except OSError as exc:
        return f"data_root_unwritable:{exc}"
    finally:
        if probe and os.path.exists(probe):
            try:
                os.remove(probe)
            except OSError:
                pass
    library = os.environ.get("BOH_LIBRARY") or os.path.join(os.getcwd(), "library")
    # The EFFECTIVE DB path used by app.db.connection (default 'boh.db' relative to cwd when BOH_DB
    # is unset). _contains_or_equal resolves relative paths against the process working directory.
    db_path = _dbconn.DB_PATH
    if _overlaps(watch, data_root):
        return f"watch_data_overlap:{watch}|{data_root}"
    if _overlaps(watch, library):
        return f"watch_library_overlap:{watch}|{library}"
    if _overlaps(data_root, library):
        return f"data_library_overlap:{data_root}|{library}"
    if db_path and _contains_or_equal(watch, db_path):
        return f"db_inside_watch:{db_path}"
    if db_path and _contains_or_equal(data_root, db_path):
        return f"db_inside_data_root:{db_path}"
    if db_path and _contains_or_equal(library, db_path):
        return f"db_inside_library:{db_path}"
    return None


# WO-1.1 Phase B item 4 — config validation ranges (fail closed before worker startup).
_SCAN_INTERVAL_RANGE = (1, 86400)
_CAPACITY_RANGE = (1, 4096)
_DRAIN_TIMEOUT_RANGE = (0.001, 3600.0)


def _validated_int(key: str, default: int, lo: int, hi: int) -> tuple[int | None, str | None]:
    raw = os.environ.get(key)
    if raw is None or raw.strip() == "":
        return default, None
    try:
        v = int(raw.strip())
    except ValueError:
        return None, f"config_invalid:{key}:not_an_integer:{raw!r}"
    if v < lo or v > hi:
        return None, f"config_invalid:{key}:out_of_range[{lo},{hi}]:{v}"
    return v, None


def _validated_float(key: str, default: float, lo: float, hi: float) -> tuple[float | None, str | None]:
    raw = os.environ.get(key)
    if raw is None or raw.strip() == "":
        return default, None
    try:
        v = float(raw.strip())
    except ValueError:
        return None, f"config_invalid:{key}:not_a_number:{raw!r}"
    if not math.isfinite(v):  # reject nan / inf / -inf (range comparisons silently accept nan)
        return None, f"config_invalid:{key}:not_finite:{raw!r}"
    if v < lo or v > hi:
        return None, f"config_invalid:{key}:out_of_range[{lo},{hi}]:{v}"
    return v, None


class SchedulerManager:
    def __init__(self, pipeline_fn: Callable | None = None):
        self._pipeline_fn = pipeline_fn or run_pipeline_for_claimed_revision
        self._lock = threading.Lock()
        self._counts = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._executor: ThreadPoolExecutor | None = None
        self._sem: threading.BoundedSemaphore | None = None
        self._max = 0
        self._accepted = 0   # queued-or-running (reserved capacity) for the CURRENT generation
        self._generation = 0          # bumped on each successful start; tags worker accounting
        self._active_by_gen: dict[int, int] = {}  # generation -> currently executing workers
        self._state = "disabled"      # disabled|running|draining|undrained|stopped|error
        self._watch_path: str | None = None
        self._data_root: str | None = None
        self._policy: str | None = None
        self._adapter_fp: str | None = None
        self._ignore: list[str] | None = None
        self._interval = 30
        self._drain_timeout = 30.0
        self._last_scan_ts: str | None = None
        self._last_error: str | None = None
        self._restart_refusal_reason: str | None = None

    # ── capacity accounting (generation-tagged; counters never go negative) ─────────
    def _reserve(self) -> bool:
        if self._sem is None:
            return True
        if self._sem.acquire(blocking=False):
            with self._counts:
                self._accepted += 1
            return True
        return False

    def _dec_accepted(self) -> None:
        """Decrement the reserved-work counter, clamped at 0. An attempted underflow is recorded as
        a structured error diagnostic (not silently hidden by the clamp)."""
        with self._counts:
            if self._accepted <= 0:
                self._last_error = "accounting_underflow:accepted"
                logger.error("intake scheduler accounting underflow on 'accepted' (generation=%s)",
                             self._generation)
            self._accepted = max(0, self._accepted - 1)

    def _release(self) -> None:
        """Return a reserved-but-never-dispatched slot (submission failure; same thread/generation)."""
        if self._sem is None:
            return
        self._sem.release()
        self._dec_accepted()

    def _inc_active(self, generation: int) -> None:
        with self._counts:
            self._active_by_gen[generation] = self._active_by_gen.get(generation, 0) + 1

    def _dec_active(self, generation: int) -> None:
        """Decrement a generation's active-worker count, clamped at 0; an attempted underflow is
        recorded as a structured error diagnostic."""
        with self._counts:
            cur = self._active_by_gen.get(generation, 0)
            if cur <= 0:
                self._last_error = "accounting_underflow:active"
                logger.error("intake scheduler accounting underflow on 'active' (generation=%s)",
                             generation)
            nxt = max(0, cur - 1)
            if nxt == 0:
                self._active_by_gen.pop(generation, None)
            else:
                self._active_by_gen[generation] = nxt

    def _active_total(self) -> int:
        return sum(self._active_by_gen.values())

    def _validate_config(self) -> str | None:
        """WO-1.1 Phase B item 4: validate scan interval, capacity, drain timeout, ignore patterns,
        a deterministic adapter fingerprint, and consistent policy binding. Returns a structured
        reason string on failure (fail closed before worker startup), else None. On success the
        validated interval/capacity/drain timeout are bound to this generation."""
        interval, err = _validated_int("BOH_INTAKE_SCAN_INTERVAL", 30, *_SCAN_INTERVAL_RANGE)
        if err:
            return err
        cap, err = _validated_int("BOH_INTAKE_BACKPRESSURE_MAX", 10, *_CAPACITY_RANGE)
        if err:
            return err
        drain, err = _validated_float("BOH_INTAKE_DRAIN_TIMEOUT", 30.0, *_DRAIN_TIMEOUT_RANGE)
        if err:
            return err
        ignore = _ignore_patterns()
        if os.environ.get("BOH_INTAKE_IGNORE_PATTERNS", "").strip() and not ignore:
            return "config_invalid:BOH_INTAKE_IGNORE_PATTERNS:no_valid_patterns"
        fp = adapter_registry_fingerprint()
        if not fp or not fp.startswith("adapterfp-v1:"):
            return "config_adapter_fingerprint_unavailable"
        if fp != adapter_registry_fingerprint():
            return "config_adapter_fingerprint_nondeterministic"
        policy = _policy_bind()
        if policy != _policy_bind():
            return "config_policy_binding_inconsistent"
        # Bind the EXACT validated contract snapshot to this generation — no re-reads of the
        # fingerprint/policy/patterns after validation (a changed third read must not bind an
        # unvalidated value).
        self._interval, self._max, self._drain_timeout = interval, cap, drain
        self._ignore, self._adapter_fp, self._policy = ignore, fp, policy
        return None

    # ── lifecycle ─────────────────────────────────────────────────────────────────
    def start_if_enabled(self) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return True  # singleton: a second start while running is a no-op
            # WO-1.1 P0: refuse a restart while a PRIOR generation is still undrained (its workers
            # are still in flight). Once that generation has fully settled, a new start is allowed.
            if self._state == "undrained":
                if self._active_total() > 0:
                    self._last_error = "restart_refused_prior_generation_undrained"
                    self._restart_refusal_reason = "restart_refused_prior_generation_undrained"
                    logger.warning("intake scheduler start refused: prior generation still draining "
                                   "(%d active)", self._active_total())
                    return False
                self._state = "stopped"  # the old generation settled; safe to replace it
            if not _enabled():
                return False  # disabled-by-default: stay inert, no error
            watch = os.environ.get("BOH_WATCH_PATH", "")
            data_root = os.environ.get("BOH_DATA_ROOT", "")
            # WO-1.1 closure: enabled-but-misconfigured roots fail closed with a structured error.
            if not watch:
                self._last_error = "config_missing:BOH_WATCH_PATH"
                self._state = "error"
                logger.error("intake scheduler not started: config_missing:BOH_WATCH_PATH")
                return False
            if not data_root:
                self._last_error = "config_missing:BOH_DATA_ROOT"
                self._state = "error"
                logger.error("intake scheduler not started: config_missing:BOH_DATA_ROOT")
                return False

            # WO-1.1 P0: reject unsafe watch/data/library/DB root overlap (fail closed before start).
            reason = _validate_layout(watch, data_root)
            if reason:
                self._last_error = f"unsafe_layout:{reason}"
                self._state = "error"
                logger.error("intake scheduler not started: unsafe root layout (%s)", reason)
                return False
            # WO-1.1 Phase B item 4: validate interval / capacity / drain-timeout / ignore-patterns /
            # adapter-fingerprint / policy-binding (fail closed with a structured status error).
            cfg_err = self._validate_config()
            if cfg_err:
                self._last_error = cfg_err
                self._state = "error"
                logger.error("intake scheduler not started: %s", cfg_err)
                return False

            self._watch_path = watch
            self._data_root = data_root
            # _validate_config() already bound this generation's exact validated contract snapshot
            # (interval / max / drain / ignore / adapter_fp / policy) — do NOT re-read them here.
            # Fail closed: do NOT start dispatching if stale leases could not be reconciled.
            try:
                revsvc.reconcile_expired_claims()
            except Exception as exc:  # noqa: BLE001
                self._last_error = f"reconcile_failed: {type(exc).__name__}: {exc}"
                self._state = "error"
                logger.exception("intake scheduler not started: expired-claim reconciliation failed")
                return False
            self._generation += 1
            self._sem = threading.BoundedSemaphore(self._max) if self._max > 0 else _ZeroSemaphore()
            self._executor = ThreadPoolExecutor(max_workers=max(1, self._max),
                                                thread_name_prefix="boh-intake")
            self._stop = threading.Event()
            self._accepted = 0
            self._active_by_gen.setdefault(self._generation, 0)
            self._last_error = None
            self._restart_refusal_reason = None
            self._state = "running"
            self._thread = threading.Thread(target=self._loop, daemon=True,
                                            name="boh-intake-scheduler")
            self._thread.start()
            return True

    def stop(self, drain_timeout: float | None = None) -> dict:
        dt = drain_timeout if drain_timeout is not None else (self._drain_timeout or 30.0)
        with self._lock:
            thread = self._thread
            executor = self._executor
            if thread is None:
                return {"stopped": False, "reason": "not running", "state": self._state}
            self._stop.set()  # loop exits promptly via stop_event.wait
            self._state = "draining"
        thread.join(timeout=dt)  # loop exits promptly via stop_event.wait
        if executor is not None:
            # Bounded drain: cancel queued tasks, then wait for in-flight workers up to the
            # timeout. Workers are daemon threads, so we never block shutdown indefinitely.
            executor.shutdown(wait=False, cancel_futures=True)
            deadline = time.time() + dt
            while self._active_total() > 0 and time.time() < deadline:
                time.sleep(0.05)
        with self._counts:
            active = self._active_total()
            accepted = max(0, self._accepted)
        drained = active == 0 and accepted == 0
        with self._lock:
            self._thread = None
            self._executor = None
            # WO-1.1 P0: an undrained stop is reported truthfully and blocks restart until the old
            # generation's workers settle (they keep their own generation's semaphore/counters).
            self._state = "stopped" if drained else "undrained"
        return {"stopped": True, "drained": drained, "state": self._state,
                "active_workers": active, "queued_or_running": accepted}

    def status(self) -> dict:
        with self._counts:
            accepted = max(0, self._accepted)
            active = self._active_total()
        running = self._thread is not None and self._thread.is_alive()
        return {
            "running": running,
            "enabled": _enabled(),
            "state": self._state,
            "generation": self._generation,
            "max": self._max,
            "queued_or_running": accepted,
            "active_workers": active,
            "drained": active == 0 and accepted == 0,
            "last_scan_ts": self._last_scan_ts,
            "last_error": self._last_error,
            "restart_refusal_reason": self._restart_refusal_reason,
            "watch_path": self._watch_path,
            "data_root_configured": bool(self._data_root),
        }

    # ── scanning ──────────────────────────────────────────────────────────────────
    def _loop(self) -> None:
        interval = self._interval  # validated at start_if_enabled (Phase B item 4)
        while not self._stop.is_set():
            try:
                self._scan_once(self._watch_path, self._data_root)
            except Exception as exc:  # noqa: BLE001 — record, never swallow silently
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("intake scan loop iteration failed")
            self._stop.wait(interval)

    def _scan_once(self, watch_path: str, data_root: str) -> int:
        """Reserve→claim→submit. Returns the number of revisions dispatched this scan."""
        self._last_scan_ts = utc_now_iso()
        dispatched = 0
        for path in scan(watch_path, ignore_patterns=self._ignore).candidates:
            if self._stop.is_set():
                break
            if not is_stable(path).stable:
                continue
            try:
                source_hash = sha256_file(path)
                size = os.path.getsize(path)
            except OSError:
                continue

            row, _created = revsvc.register_or_observe_revision(
                source_ref=path, source_hash_sha256=source_hash, byte_size=size,
                policy_snapshot_hash=self._policy, adapter_registry_version=self._adapter_fp,
            )
            if row["lifecycle_state"] != "discovered":
                continue  # terminal/claimed/in-flight → no new work (last_seen_at bumped)

            if not self._reserve():
                break  # capacity exhausted: stop dispatching this scan (backpressure)

            token = revsvc.try_claim_revision(row["source_revision_id"], claimed_by="scheduler")
            if not token:
                self._release()  # lost the claim race
                continue

            batch_id = f"sched_{int(time.time())}"
            srid = row["source_revision_id"]
            gen, sem = self._generation, self._sem  # bind worker accounting to THIS generation
            try:
                self._executor.submit(self._run_one, path, batch_id, srid, token, source_hash, gen, sem)
                dispatched += 1
            except Exception:
                self._release()  # submission failed: give the capacity slot back
                logger.exception("intake executor submission failed for %s", path)
                # The revision was claimed but no run will execute — fail it (clearing the lease)
                # so it is not stranded until lease expiry; explicit replay can retry it.
                try:
                    revsvc.set_terminal_state(srid, "failed")
                except Exception:
                    logger.exception("failed to release stranded claim for %s", srid)
        return dispatched

    def _run_one(self, path: str, batch_id: str, source_revision_id: str, claim_token: str,
                 expected_source_hash: str, generation: int, sem) -> None:
        self._inc_active(generation)
        try:
            self._pipeline_fn(
                source_ref=path, batch_id=batch_id, source_revision_id=source_revision_id,
                trigger_kind="scheduler", claim_token=claim_token,
                policy_snapshot_hash=self._policy, data_root=self._data_root,
                expected_source_hash=expected_source_hash,
            )
        except Exception:  # noqa: BLE001
            logger.exception("intake worker failed for %s", path)
        finally:
            # Release THIS worker's generation semaphore (old generations keep their own object) and
            # decrement counters generation-safely; underflow is diagnosed, never silently clamped.
            try:
                sem.release()
            except (ValueError, AttributeError):
                pass
            self._dec_active(generation)
            if generation == self._generation:
                self._dec_accepted()


class _ZeroSemaphore:
    """Stand-in for a zero-capacity bound: accepts nothing, releases are no-ops."""
    def acquire(self, blocking: bool = True) -> bool:  # noqa: D401
        return False

    def release(self) -> None:
        pass


# Module-level singleton + thin public API (the lifespan delegates here at Gate C).
_MANAGER = SchedulerManager()


def start_if_enabled() -> bool:
    return _MANAGER.start_if_enabled()


def stop(drain_timeout: float | None = None) -> dict:
    # None -> the manager uses its validated BOH_INTAKE_DRAIN_TIMEOUT; a numeric override still wins.
    return _MANAGER.stop(drain_timeout=drain_timeout)


def status() -> dict:
    return _MANAGER.status()
