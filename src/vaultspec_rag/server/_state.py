"""Shared module-level state for the RAG daemon (server) package.

Split out of the original ``server.py`` monolith per the
``2026-06-01-module-split-adr``. This module is the canonical home of
the singleton :data:`mcp` FastMCP instance and the process-wide
globals (registry, watcher bookkeeping, identity token, HTTP-mode
flag). The package ``__init__`` re-imports these names so they live in
the ``vaultspec_rag.server`` namespace, which is the target tests
rebind (e.g. ``server._http_mode = True``).

Rebind discipline (mirrors the ``cli`` split's monkeypatch handling):

- ``mcp``, ``_watcher_tasks``, ``_watcher_stops``, ``_watcher_lock``
  are mutated *in place* (decorator registration, dict insert/pop,
  lock acquire) and may be imported by reference.
- ``_registry``, ``_http_mode``, ``_SERVICE_TOKEN``, ``_start_time``
  are *reassigned* at runtime (``main`` sets ``_http_mode``;
  ``service_lifespan`` sets ``_start_time``/``_SERVICE_TOKEN``; tests
  rebind ``_registry``). Consumers must read them at call time through
  ``import vaultspec_rag.server as _m`` so a rebind on the package
  namespace is observed.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

__all__ = [
    "_HEARTBEAT_INTERVAL_SECONDS",
    "_HEARTBEAT_STALENESS_SECONDS",
    "_MAX_QUERY_LEN",
    "_SENSITIVE_DIRS",
    "_SENSITIVE_PATTERNS",
    "_SERVICE_TOKEN",
    "_http_mode",
    "_registry",
    "_shutdown_hooks_installed",
    "_shutdown_recorded",
    "_start_time",
    "_watcher_lock",
    "_watcher_stops",
    "_watcher_tasks",
    "incr",
    "observe",
    "render_prometheus",
    "reset_metrics",
]

from ..registry import get_registry

if TYPE_CHECKING:
    import asyncio
    from pathlib import Path

logger = logging.getLogger("vaultspec_rag.server")

_registry = get_registry()
_watcher_tasks: dict[Path, asyncio.Task[None]] = {}
_watcher_stops: dict[Path, asyncio.Event] = {}
_watcher_lock = threading.Lock()
_start_time: float = 0.0
_http_mode: bool = False  # set once in main() before event loop starts

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
# the age exceeds _HEARTBEAT_STALENESS_SECONDS. Four beats per
# minute tolerates up to three missed beats before the verdict
# flips to "crashed".
_HEARTBEAT_INTERVAL_SECONDS = 15
_HEARTBEAT_STALENESS_SECONDS = 60

_MAX_QUERY_LEN = 10_000  # characters; prevents accidental OOM on huge queries

_SENSITIVE_PATTERNS: tuple[str, ...] = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*credentials*",
    "*secrets*",
    "service.json",
)

_SENSITIVE_DIRS: tuple[str, ...] = (
    ".git",
    ".vaultspec-rag",
)

# Shutdown bookkeeping; reassigned by _record_shutdown / lifespan.
_shutdown_hooks_installed: bool = False
_shutdown_recorded: bool = False


# --------------------------------------------------------------------------- #
# Inline metrics holder (#142, plan P05).                                     #
# --------------------------------------------------------------------------- #
#
# A tiny, dependency-free metrics surface for the ``/metrics`` Prometheus
# route. Counters and last-duration gauges are mutated *inline* by the
# search/reindex tool paths under ``_metrics_lock`` - there is **no**
# background collector thread (honours the standing rejection of background
# sweepers per the ``service-observability`` ADR). GPU memory is read
# on-demand inside :func:`render_prometheus` so it reflects the value at
# scrape time, never a sampled snapshot.

_metrics_lock = threading.Lock()

# Monotonic counters: total search/reindex tool invocations since process
# start. Mutated in place via ``incr`` so they may be imported by reference;
# read under the lock by ``render_prometheus``.
_counters: dict[str, int] = {
    "search_total": 0,
    "reindex_total": 0,
}

# Last-observed operation durations (seconds), as point-in-time gauges.
_gauges: dict[str, float] = {
    "search_last_duration_seconds": 0.0,
    "reindex_last_duration_seconds": 0.0,
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

    return "\n".join(lines) + "\n"
