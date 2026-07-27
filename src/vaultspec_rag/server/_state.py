"""Shared module-level state for the RAG daemon (server) package.

Split out of the original ``server.py`` monolith. This module is the canonical home of
the daemon's process-wide globals (registry, watcher bookkeeping,
identity token, HTTP-mode flag). The package ``__init__`` re-imports
these names so they live in the ``vaultspec_rag.server`` namespace,
which is where every consumer reads them. The MCP ``FastMCP`` instance
is not owned here - after the thin-client rework it lives only in
``vaultspec_rag.mcp._mcp`` and is served by the standalone stdio
forwarder.

Rebind discipline (mirrors the ``cli`` split):

- ``_watcher_tasks``, ``_watcher_stops``, ``_watcher_lock`` are mutated
  *in place* (dict insert/pop, lock acquire) and may be imported by
  reference.
- ``_http_mode``, ``_SERVICE_TOKEN``, ``_start_time``,
  ``_start_wall_time`` are *reassigned* at runtime (``main`` sets
  ``_http_mode``; ``service_lifespan`` sets the start stamps and
  ``_SERVICE_TOKEN``). Consumers must read them at call time through
  ``import vaultspec_rag.server as _m``, or they bind the value the
  daemon held before startup finished rather than the one it runs on.
- ``_registry`` is bound once here at import and never reassigned. It is
  read through the same alias so the watcher's ownership check compares
  every caller against one object.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..config._paths import SERVICE_STATUS_FILENAME

__all__ = [
    "_HEARTBEAT_INTERVAL_SECONDS",
    "_MAX_QUERY_LEN",
    "_SENSITIVE_DIRS",
    "_SENSITIVE_PATTERNS",
    "_SERVICE_TOKEN",
    "SurveySnapshot",
    "_daemon_log_capture",
    "_daemon_process",
    "_http_mode",
    "_launch_token",
    "_registry",
    "_service_port",
    "_shutdown_hooks_installed",
    "_shutdown_recorded",
    "_start_time",
    "_start_wall_time",
    "_watcher_lock",
    "_watcher_stops",
    "_watcher_tasks",
    "incr",
    "observe",
    "publish_survey_snapshot",
    "render_prometheus",
    "reset_metrics",
    "survey_snapshot",
]

from ..registry import get_registry

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Sequence
    from pathlib import Path

    from ..logging_config import DaemonLogCapture
    from ..storage_survey import NamespaceSurvey

logger = logging.getLogger("vaultspec_rag.server")

# This import-time alias caches the registry singleton, and the watcher reads
# it (as ``server._registry``) while the job dispatcher reads the live
# ``get_registry()``. That is safe ONLY because nothing in a live process ever
# rebuilds the singleton - the two always resolve to one object. Any future
# production reset or hot-swap path MUST read ``get_registry()`` live here (or
# refresh this alias at the swap), or the watcher and the dispatcher will drive
# different registries and double-open the same non-parallel-safe local store.
_registry = get_registry()
_watcher_tasks: dict[Path, asyncio.Task[None]] = {}
_watcher_stops: dict[Path, asyncio.Event] = {}
_watcher_lock = threading.Lock()
_start_time: float = 0.0
# Wall-clock twin of ``_start_time``, stamped in the same statement pair at
# lifespan startup. ``_start_time`` is monotonic (correct for durations, not
# comparable to anything epoch-stamped), while job records carry epoch
# ``finished_at`` values, so placing a job relative to this process needs an
# epoch witness. Both are kept: the monotonic one still yields uptime, and the
# pair lets a reader derive the generation start two independent ways and take
# the earlier, so a mid-run system-clock adjustment can only widen the window a
# job is judged against, never narrow it.
_start_wall_time: float = 0.0
_http_mode: bool = False  # set once in main() before event loop starts
_service_port: int = 0  # set by main() before the HTTP lifespan starts
_launch_token: str = ""  # unique CLI launch-attempt witness, HTTP mode only

# Standalone-daemon exit backstop. ``_daemon_process`` is set True exactly once
# in ``main()`` right before ``uvicorn.run`` on the HTTP daemon path, and never
# by a test or the in-process embedded-reuse lifespan. It gates the
# post-shutdown ``os._exit``: only the real spawned daemon forces a prompt
# process exit after a bounded teardown (a wedged ``to_thread`` worker would
# otherwise hang the interpreter-exit executor join); the embedded-reuse
# contract, which retries the lifespan in-process, must never be terminated.
# ``_daemon_log_capture`` is that daemon's log-pipe drain, stashed so the
# backstop can flush ``service.log`` before ``os._exit`` skips the drain thread.
_daemon_process: bool = False
_daemon_log_capture: DaemonLogCapture | None = None

# Per-process identity token. Generated once in ``service_lifespan``
# startup, written into ``service.json`` via the first heartbeat
# tick, and returned from ``/health``. The CLI's ``_is_our_service``
# compares the file's recorded value against the live ``/health``
# response - mismatch reports the responding process is not the
# daemon named in ``service.json`` (gh #124 + #125: closes
# PID-reuse false-positives and unrelated-HTTP-server-on-port).
_SERVICE_TOKEN: str = ""

# Heartbeat contract. The daemon writes ``last_heartbeat`` to
# service.json every _HEARTBEAT_INTERVAL_SECONDS so
# ``vaultspec-rag server status`` can detect a stale file
# (process killed without running atexit / signal handlers -
# SIGKILL, OOM, kernel panic). The CLI flags the file stale when
# the age exceeds HEARTBEAT_STALENESS_SECONDS. Four beats per
# minute tolerates up to three missed beats before the verdict
# flips to "crashed".
_HEARTBEAT_INTERVAL_SECONDS = 15

_MAX_QUERY_LEN = 10_000  # characters; prevents accidental OOM on huge queries

_SENSITIVE_PATTERNS: tuple[str, ...] = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*credentials*",
    "*secrets*",
    SERVICE_STATUS_FILENAME,
)

_SENSITIVE_DIRS: tuple[str, ...] = (
    ".git",
    ".vaultspec-rag",
)

# Shutdown bookkeeping; reassigned by _record_shutdown / lifespan.
_shutdown_hooks_installed: bool = False
_shutdown_recorded: bool = False


# --------------------------------------------------------------------------- #
# Storage-survey snapshot cache.                                              #
# --------------------------------------------------------------------------- #
#
# The full storage survey walks every collection's on-disk footprint, so it
# is O(namespaces) and was measured at ~15s on a store with ~100 namespaces.
# The scheduled maintenance cycle already pays that cost every interval; it
# publishes its classified result here so ``/storage/survey`` can answer from
# the snapshot in O(1). Writers hand over a fully built, immutable snapshot
# in a single reference assignment (atomic in CPython), so readers never see
# a partially built value; staleness is surfaced to consumers through
# ``computed_at`` and remedied by the route's ``?fresh=true`` recompute.


@dataclass(frozen=True)
class SurveySnapshot:
    """One immutable, fully classified storage survey with its wall-clock stamp.

    Attributes:
        surveys: The classified namespace records, in survey order.
        computed_at: ISO-8601 UTC timestamp of when the survey ran.
    """

    surveys: tuple[NamespaceSurvey, ...]
    computed_at: str


_survey_snapshot: SurveySnapshot | None = None


def publish_survey_snapshot(
    surveys: Sequence[NamespaceSurvey], computed_at: str
) -> None:
    """Publish a freshly computed survey as the current snapshot.

    Called by the maintenance tick, the startup warmer, and the route's
    fresh path. The tuple copy plus single assignment is the atomic swap;
    no lock is required for readers.

    Args:
        surveys: The classified namespace records just gathered.
        computed_at: ISO-8601 UTC timestamp of the gather.
    """
    global _survey_snapshot
    _survey_snapshot = SurveySnapshot(tuple(surveys), computed_at)


def survey_snapshot() -> SurveySnapshot | None:
    """Return the current survey snapshot, or ``None`` before the first publish."""
    return _survey_snapshot


# --------------------------------------------------------------------------- #
# Inline metrics holder (#142).                                     #
# --------------------------------------------------------------------------- #
#
# A tiny, dependency-free metrics surface for the ``/metrics`` Prometheus
# route. Counters and last-duration gauges are mutated *inline* by the
# search/reindex tool paths under ``_metrics_lock`` - there is **no**
# background collector thread: the standing rejection of background
# sweepers means metrics are mutated inline, never sampled. GPU memory is read
# on-demand inside :func:`render_prometheus` so it reflects the value at
# scrape time, never a sampled snapshot.

_metrics_lock = threading.Lock()

# Monotonic counters: total search/reindex tool invocations since process
# start. Mutated in place via ``incr`` so they may be imported by reference;
# read under the lock by ``render_prometheus``.
_counters: dict[str, int] = {
    "search_total": 0,
    "reindex_total": 0,
    "maintenance_cycles_total": 0,
    "maintenance_reclaims_total": 0,
    "maintenance_reconciled_total": 0,
    "maintenance_reconciled_bytes_total": 0,
}

# Last-observed operation durations (seconds), as point-in-time gauges.
# The ``maintenance_*`` gauges are the scheduled storage-maintenance
# rollup: refreshed once per cycle by the tick, never by a collector.
_gauges: dict[str, float] = {
    "search_last_duration_seconds": 0.0,
    "reindex_last_duration_seconds": 0.0,
    "maintenance_disk_free_bytes": 0.0,
    "maintenance_dangling_bytes": 0.0,
    "maintenance_pending_grace": 0.0,
    "maintenance_orphaned_namespaces": 0.0,
    "maintenance_last_reclaimed_bytes": 0.0,
    "store_drifted_collections": 0.0,
}


def incr(name: str, amount: int = 1) -> None:
    """Increment the named counter by *amount* (inline, lock-guarded).

    Unknown names are ignored so a typo in a hot path can never crash a
    tool call. Called inline by the search/reindex tool paths; never by a
    background thread.

    Args:
        name: Counter key (``"search_total"`` or ``"reindex_total"``).
        amount: Positive increment (default 1).
    """
    with _metrics_lock:
        if name in _counters:
            _counters[name] += amount


def observe(name: str, value: float) -> None:
    """Set the named last-duration gauge to *value* (inline, lock-guarded).

    Unknown names are ignored. Called inline by the search/reindex tool
    paths after an operation completes; never by a background thread.

    Args:
        name: Gauge key (e.g. ``"search_last_duration_seconds"``).
        value: The most recent observed duration in seconds.
    """
    with _metrics_lock:
        if name in _gauges:
            _gauges[name] = value


def reset_metrics() -> None:
    """Zero all counters and gauges (test-only)."""
    with _metrics_lock:
        for key in _counters:
            _counters[key] = 0
        for key in _gauges:
            _gauges[key] = 0.0


def _gpu_memory_bytes() -> tuple[float, float] | None:
    """Return ``(allocated, reserved)`` CUDA bytes, or ``None`` if unavailable.

    Read on-demand at scrape time. Guards both a missing ``torch`` import
    and an absent/uninitialised CUDA device so ``/metrics`` never crashes
    on a CPU-only host.
    """
    try:
        import torch
    except ImportError:
        return None
    if not torch.cuda.is_available():
        return None
    try:
        allocated = float(torch.cuda.memory_allocated(0))
        reserved = float(torch.cuda.memory_reserved(0))
    except (RuntimeError, AssertionError):
        return None
    return allocated, reserved


def render_prometheus() -> str:
    """Render the current metrics as Prometheus text exposition format.

    Emits the ``0.0.4`` text format directly - no ``prometheus_client``
    dependency, no collector thread. Counters carry a ``# TYPE ... counter``
    line, gauges ``# TYPE ... gauge``; GPU memory is read on-demand and
    omitted entirely when CUDA is unavailable. The metric names are
    prefixed ``vaultspec_rag_``.

    Returns:
        The Prometheus exposition text (trailing newline included).
    """
    with _metrics_lock:
        counters = dict(_counters)
        gauges = dict(_gauges)

    lines: list[str] = []
    for name, value in counters.items():
        metric = f"vaultspec_rag_{name}"
        lines.append(f"# TYPE {metric} counter")
        lines.append(f"{metric} {value}")
    for name, value in gauges.items():
        metric = f"vaultspec_rag_{name}"
        lines.append(f"# TYPE {metric} gauge")
        lines.append(f"{metric} {value}")

    gpu = _gpu_memory_bytes()
    if gpu is not None:
        allocated, reserved = gpu
        lines.append("# TYPE vaultspec_rag_gpu_memory_allocated_bytes gauge")
        lines.append(f"vaultspec_rag_gpu_memory_allocated_bytes {allocated}")
        lines.append("# TYPE vaultspec_rag_gpu_memory_reserved_bytes gauge")
        lines.append(f"vaultspec_rag_gpu_memory_reserved_bytes {reserved}")

    # Worker-pool partition depth: borrowed tokens and queued waiters
    # per limiter, so saturation is observable before it times out.
    from ..concurrency import limiter_stats

    for pool, stats in limiter_stats().items():
        if stats.get("total_tokens") is None:
            continue
        for stat_name, value in stats.items():
            metric = f"vaultspec_rag_{pool}_pool_{stat_name}"
            lines.append(f"# TYPE {metric} gauge")
            lines.append(f"{metric} {value}")

    return "\n".join(lines) + "\n"
