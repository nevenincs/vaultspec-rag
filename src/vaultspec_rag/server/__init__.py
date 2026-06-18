"""RAG daemon HTTP service for VaultSpec RAG search and retrieval.

Exposes REST endpoints for searching vault and codebase, reindexing,
and observing daemon state. The daemon runs inside a Starlette
application with a ``service_lifespan`` that eagerly loads GPU models
before accepting connections, and serves a raw ``/health`` endpoint
alongside the native REST routes.

The MCP protocol surface no longer lives here. After the thin-client
rework, the ``mcp`` FastMCP instance is defined only in
``vaultspec_rag.mcp._mcp`` and is served by the standalone stdio
forwarder; the daemon exposes native REST only and no longer mounts an
MCP app.

This module was split into a package (``server/``) per the
``2026-06-01-module-split-adr``. The verbatim public surface - the
response models, the shared globals, and the ``_``-prefixed helpers
tests import or monkeypatch directly - is re-exported here unchanged
through an explicit ``__all__``.

Import order is load-bearing and mirrors the ``cli`` split:

1. ``_state`` first - owns the process-wide globals (``_registry``,
   ``_watcher_*``, ``_SERVICE_TOKEN``, ``_http_mode``, ``_start_time``).
   These names live in *this* package namespace because that is what
   tests rebind (e.g. ``server._http_mode = True``).
2. Leaf helper submodules (``_models``, ``_utils``, ``_lifecycle``,
   ``_lifespan``, ``_watcher``) - pure logic.
3. ``_main`` - the console-script ``main`` entry point.

Reassigned globals (``_http_mode``, ``_SERVICE_TOKEN``, ``_start_time``,
``_registry``) are read by submodules at call time through
``import vaultspec_rag.server as _m`` so a rebind on this package
namespace is observed - the same discipline the ``cli`` split uses for
monkeypatched names.
"""

from __future__ import annotations

# Re-export ``BackendCapabilities`` from its home module so the
# pre-split ``from . import BackendCapabilities``
# import keeps resolving.
from ..capabilities import BackendCapabilities

# 2a. Leaf helper imported as a submodule (not by-name): the in-flight
#     jobs registry. The reindex tools and watcher write through
#     ``_jobs.record_*`` and tests reach it via ``server._jobs``.
from . import _jobs

# 2. Leaf helpers (no decorators).
from ._lifecycle import (
    _heartbeat_loop,
    _heartbeat_tick_sync,
    _install_daemon_shutdown_hooks,
    _lifecycle_log,
    _record_shutdown,
    _resolve_log_path,
    _status_file_path,
    _unlink_status_file_silently,
)
from ._lifespan import health_handler, service_lifespan

# 4. Entry point.
from ._main import main
from ._models import (
    HealthResponse,
    IndexResponse,
    IndexStatus,
    SearchResponse,
    SearchResultItem,
)

# 1. State globals
from ._state import (
    _HEARTBEAT_INTERVAL_SECONDS,
    _HEARTBEAT_STALENESS_SECONDS,
    _MAX_QUERY_LEN,
    _SENSITIVE_DIRS,
    _SENSITIVE_PATTERNS,
    _SERVICE_TOKEN,
    _http_mode,
    _registry,
    _shutdown_hooks_installed,
    _shutdown_recorded,
    _start_time,
    _watcher_lock,
    _watcher_stops,
    _watcher_tasks,
    incr,
    observe,
    render_prometheus,
    reset_metrics,
)
from ._utils import (
    ProjectRootRequiredError,
    _clamp_top_k,
    _default_root,
    _is_sensitive_path,
    _local_store_locked_error_dict,
    _registry_full_error_dict,
    _resolve_root,
    _validate_query,
    _validate_vault_root,
)
from ._watcher import (
    _ensure_watcher,
    _ensure_watcher_soon,
    _stop_all_watchers,
    _stop_watcher,
)

__all__ = [
    "_HEARTBEAT_INTERVAL_SECONDS",
    "_HEARTBEAT_STALENESS_SECONDS",
    "_MAX_QUERY_LEN",
    "_SENSITIVE_DIRS",
    "_SENSITIVE_PATTERNS",
    "_SERVICE_TOKEN",
    "BackendCapabilities",
    "HealthResponse",
    "IndexResponse",
    "IndexStatus",
    "ProjectRootRequiredError",
    "SearchResponse",
    "SearchResultItem",
    "_clamp_top_k",
    "_default_root",
    "_ensure_watcher",
    "_ensure_watcher_soon",
    "_heartbeat_loop",
    "_heartbeat_tick_sync",
    "_http_mode",
    "_install_daemon_shutdown_hooks",
    "_is_sensitive_path",
    "_jobs",
    "_lifecycle_log",
    "_local_store_locked_error_dict",
    "_record_shutdown",
    "_registry",
    "_registry_full_error_dict",
    "_resolve_log_path",
    "_resolve_root",
    "_shutdown_hooks_installed",
    "_shutdown_recorded",
    "_start_time",
    "_status_file_path",
    "_stop_all_watchers",
    "_stop_watcher",
    "_unlink_status_file_silently",
    "_validate_query",
    "_validate_vault_root",
    "_watcher_lock",
    "_watcher_stops",
    "_watcher_tasks",
    "health_handler",
    "incr",
    "main",
    "observe",
    "render_prometheus",
    "reset_metrics",
    "service_lifespan",
]


if __name__ == "__main__":
    main()
