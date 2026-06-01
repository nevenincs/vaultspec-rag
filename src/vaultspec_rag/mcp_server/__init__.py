"""MCP server for VaultSpec RAG search and retrieval.

Exposes tools for searching vault and codebase, resources for
retrieving full contents, and prompts for common RAG tasks.

In HTTP mode the server runs inside a Starlette application with
a ``service_lifespan`` that eagerly loads GPU models before
accepting connections.  A raw ``/health`` endpoint is mounted
alongside the MCP transport at ``/mcp``.

This module was split into a package (``mcp_server/``) per the
``2026-06-01-module-split-adr``. The verbatim public surface — the
``mcp`` FastMCP instance, every tool/resource/prompt, the response
models, the shared globals, and the ``_``-prefixed helpers tests
import or monkeypatch directly — is re-exported here unchanged through
an explicit ``__all__``.

Import order is load-bearing and mirrors the ``cli`` split:

1. ``_state`` first — owns the singleton ``mcp`` instance and the
   process-wide globals (``_registry``, ``_watcher_*``,
   ``_SERVICE_TOKEN``, ``_http_mode``, ``_start_time``). These names
   live in *this* package namespace because that is what tests rebind
   (e.g. ``mcp_server._http_mode = True``).
2. Leaf helper submodules (``_models``, ``_utils``, ``_lifecycle``,
   ``_lifespan``, ``_watcher``) — pure logic with no decorators.
3. Tool / resource / prompt submodules (``_tools``, ``_admin_tools``,
   ``_resources``) — importing them runs the ``@mcp.tool()`` /
   ``@mcp.resource()`` / ``@mcp.prompt()`` decorators against the one
   ``mcp`` instance defined in step 1.
4. ``_main`` — the console-script ``main`` entry point.

Reassigned globals (``_http_mode``, ``_SERVICE_TOKEN``, ``_start_time``,
``_registry``) are read by submodules at call time through
``import vaultspec_rag.mcp_server as _m`` so a rebind on this package
namespace is observed — the same discipline the ``cli`` split uses for
monkeypatched names.
"""

from __future__ import annotations

# Re-export ``BackendCapabilities`` from its home module so the
# pre-split ``from vaultspec_rag.mcp_server import BackendCapabilities``
# import keeps resolving.
from ..capabilities import BackendCapabilities

# 2a. Leaf helper imported as a submodule (not by-name): the in-flight
#     jobs registry. The reindex tools and watcher write through
#     ``_jobs.record_*`` and tests reach it via ``mcp_server._jobs``.
from . import _jobs

# 3. Tool / resource / prompt submodules — their import side effect is
#    the decorator registration against ``mcp``.
from ._admin_tools import (
    evict_project,
    get_logs,
    get_service_state,
    get_watcher_state,
    list_projects,
    reconfigure_watcher,
    start_watcher,
    stop_watcher,
)

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
from ._resources import analyze_feature, get_vault_document

# 1. Shared state: the mcp instance + process-wide globals. Defined
#    before any tool submodule imports so the decorators register
#    against this one instance and so the rebindable globals resolve
#    on the package namespace.
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
    mcp,
)
from ._tools import (
    get_code_file,
    get_index_status,
    reindex_codebase,
    reindex_vault,
    search_codebase,
    search_vault,
)
from ._utils import (
    _clamp_top_k,
    _default_root,
    _is_sensitive_path,
    _local_store_locked_error_dict,
    _registry_full_error_dict,
    _resolve_root,
    _validate_query,
    _validate_vault_root,
)
from ._watcher import _ensure_watcher, _stop_all_watchers, _stop_watcher

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
    "SearchResponse",
    "SearchResultItem",
    "_clamp_top_k",
    "_default_root",
    "_ensure_watcher",
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
    "analyze_feature",
    "evict_project",
    "get_code_file",
    "get_index_status",
    "get_logs",
    "get_service_state",
    "get_vault_document",
    "get_watcher_state",
    "health_handler",
    "list_projects",
    "main",
    "mcp",
    "reconfigure_watcher",
    "reindex_codebase",
    "reindex_vault",
    "search_codebase",
    "search_vault",
    "service_lifespan",
    "start_watcher",
    "stop_watcher",
]


if __name__ == "__main__":
    main()
