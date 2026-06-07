"""CLI application for vaultspec-rag.

VaultSpec RAG is a GPU-accelerated Retrieval-Augmented Generation (RAG) engine
that provides unified hybrid search over project documentation and source code.
It uses dense embeddings (Qwen3), sparse embeddings (SPLADE), and learned
reranking (CrossEncoder) to find the most relevant context for code generation,
code review, and documentation discovery.

This module was split into a package (``cli/``) per the
``2026-06-01-module-split-adr``. The verbatim public surface - the Typer
``app`` plus the ``_``-prefixed helpers that tests import or monkeypatch
directly (``_spawn_service``, ``_health_probe``, ``_try_http_search``,
``console`` …) - is re-exported here unchanged through an explicit
``__all__``.

Import order matters and is load-bearing:

1. ``_core`` first - owns ``console`` / ``logger`` / ``sys`` so every
   submodule shares one console and one ``vaultspec_rag.cli``-named logger.
2. ``_app`` next - creates ``app`` and the sub-apps and nests them; this MUST
   run before any command submodule's ``@*.command()`` decorator fires.
3. The leaf helper submodules, then the command submodules (their decorators
   register against the already-nested apps).

Several submodules reference test-monkeypatchable names (``console``,
``_is_pid_alive``, ``_health_probe``, ``_log_file``, ``_terminate_pid``,
``_is_our_service``) through ``import vaultspec_rag.cli as _cli`` at call
time, so ``monkeypatch.setattr(cli, name, …)`` is observed by the consumers
exactly as it was in the pre-split monolith.
"""

from __future__ import annotations

import sys

# 2. Typer app + sub-apps, created and nested before any command decorator.
from ._app import (
    CLIState,
    _global_target,
    app,
    main,
    mcp_app,
    server_app,
    service_app,
    service_projects_app,
    service_watcher_app,
    version_callback,
)
from ._benchmark import handle_benchmark

# 1. Shared runtime state (console, logger). ``sys`` is re-exported so
#    tests that do ``monkeypatch.setattr(cli.sys, "platform", …)`` keep
#    working against the package namespace.
from ._core import console, logger

# 3a. Leaf helper submodules (no command decorators).
from ._gpu_errors import (
    _cpu_only_message,
    _handle_gpu_error,
    _no_gpu_message,
    _no_torch_message,
)

# 3b. Command submodules - importing them runs the ``@app.command()`` /
#     ``@*_app.command()`` decorators against the apps nested in step 2.
from ._index import handle_clean, handle_index
from ._install import handle_install, handle_uninstall
from ._mcp_admin import mcp_start, mcp_status, mcp_stop
from ._http_search import (
    _is_connection_refused,
    _try_http_admin,
    _try_http_reindex,
    _try_http_search,
)
from ._process import (
    _health_probe,
    _heartbeat_age_seconds,
    _is_our_service,
    _is_pid_alive,
    _port_is_available,
    _port_is_listening,
    _service_child_env,
    _spawn_service,
    _terminate_pid,
)
from ._quality import handle_quality
from ._render import (
    _add_backend_contract_rows,
    _display_mcp_error,
    _display_port_unreachable_error,
    _display_search_results,
    _emit_json,
    _emit_json_error_and_exit,
    _render_install_report,
    _render_uninstall_report,
)
from ._search import _suppress_hf_progress, handle_search
from ._service_info import service_info
from ._service_jobs import service_jobs
from ._service_lifecycle import (
    service_start,
    service_status,
    service_stop,
    service_warmup,
)
from ._service_logs import service_logs
from ._service_projects import (
    service_projects_evict,
    service_projects_list,
)
from ._service_status import (
    _append_lifecycle_shutdown_log,
    _default_service_port,
    _log_file,
    _read_service_status,
    _status_dir,
    _status_file,
    _write_service_status,
)
from ._service_watcher import (
    service_watcher_reconfigure,
    service_watcher_start,
    service_watcher_status,
    service_watcher_stop,
)
from ._status import handle_status
from ._store import _open_vault_store
from ._test import handle_test

__all__ = [
    "CLIState",
    "_add_backend_contract_rows",
    "_append_lifecycle_shutdown_log",
    "_cpu_only_message",
    "_default_service_port",
    "_display_mcp_error",
    "_display_port_unreachable_error",
    "_display_search_results",
    "_emit_json",
    "_emit_json_error_and_exit",
    "_global_target",
    "_handle_gpu_error",
    "_health_probe",
    "_heartbeat_age_seconds",
    "_is_connection_refused",
    "_is_our_service",
    "_is_pid_alive",
    "_log_file",
    "_no_gpu_message",
    "_no_torch_message",
    "_open_vault_store",
    "_port_is_available",
    "_port_is_listening",
    "_read_service_status",
    "_render_install_report",
    "_render_uninstall_report",
    "_service_child_env",
    "_spawn_service",
    "_status_dir",
    "_status_file",
    "_suppress_hf_progress",
    "_terminate_pid",
    "_try_http_admin",
    "_try_http_reindex",
    "_try_http_search",
    "_write_service_status",
    "app",
    "console",
    "handle_benchmark",
    "handle_clean",
    "handle_index",
    "handle_install",
    "handle_quality",
    "handle_search",
    "handle_status",
    "handle_test",
    "handle_uninstall",
    "logger",
    "main",
    "mcp_app",
    "mcp_start",
    "mcp_status",
    "mcp_stop",
    "server_app",
    "service_app",
    "service_info",
    "service_jobs",
    "service_logs",
    "service_projects_app",
    "service_projects_evict",
    "service_projects_list",
    "service_start",
    "service_status",
    "service_stop",
    "service_warmup",
    "service_watcher_app",
    "service_watcher_reconfigure",
    "service_watcher_start",
    "service_watcher_status",
    "service_watcher_stop",
    "sys",
    "version_callback",
]


if __name__ == "__main__":
    app()
