"""CLI application for vaultspec-rag.

VaultSpec RAG is a GPU-accelerated Retrieval-Augmented Generation (RAG) engine
that provides unified hybrid search over project documentation and source code.
It uses dense embeddings (Qwen3), sparse embeddings (SPLADE), and learned
reranking (CrossEncoder) to find the most relevant context for code generation,
code review, and documentation discovery.

Import order is load-bearing, but it is enforced by dependency rather than by
the order of the statements below: every command submodule imports the app or
sub-app it decorates from ``_app``, so ``_app`` has finished creating and
nesting them before any ``@*.command()`` decorator fires.

The command submodules are imported for that decorator side effect ALONE. They
contribute no names to this package - a command handler is reached by running
the CLI, never by importing its function - so importing them by name here would
be a re-export with no caller. They are named in ``__all__`` because the import
exists for its effect rather than for a symbol, and that is the difference
between a deliberate side-effect import and one a later reader deletes as unused.

What this package does export is the small set of names its own consumers reach
through the package namespace rather than from the module that defines them:
``console`` and the process helpers (``_is_pid_alive``, ``_is_our_service``,
``_terminate_pid``) are read at call time through
``import vaultspec_rag.cli as _cli``. Reading them at call time keeps the
command modules from importing ``_core`` and the process module at their own
import time, which is what would put them in the decorator-registration cycle
described above. Everything else is imported from the module that owns it.
"""

from __future__ import annotations

from ..serviceclient._transport import _try_http_reindex, _try_http_search

# Command submodules, imported purely so their decorators register against the
# apps ``_app`` nests. Nothing here is re-exported.
from . import (
    _index,
    _install,
    _preprocess,
    _service_doctor,
    _service_jobs,
    _service_lifecycle,
    _service_logs,
    _service_projects,
    _service_qdrant,
    _service_quiesce,
    _service_reconcile,
    _service_storage,
    _service_watcher,
    _status,
    _store,
    _test,
)
from ._app import app, run_cli
from ._core import console
from ._gpu_errors import _cpu_only_message, _no_gpu_message, _no_torch_message
from ._process import (
    TerminationResult,
    _heartbeat_age_seconds,
    _is_our_service,
    _is_pid_alive,
    _port_is_listening,
    _service_child_env,
    _spawn_service,
    _terminate_pid,
)
from ._render import (
    _display_search_results,
    _display_service_error,
    _render_install_report,
    _render_uninstall_report,
)
from ._search import (
    _suppress_hf_progress,  # pyright: ignore[reportPrivateUsage]  # _search lacks __all__; read through the package by its consumers
)
from ._service_status import (
    _append_lifecycle_shutdown_log,
    _log_file,
    _read_service_status,
    _status_file,
    _write_service_status,
)

__all__ = [
    "TerminationResult",
    "_append_lifecycle_shutdown_log",
    "_cpu_only_message",
    "_display_search_results",
    "_display_service_error",
    "_heartbeat_age_seconds",
    "_index",
    "_install",
    "_is_our_service",
    "_is_pid_alive",
    "_log_file",
    "_no_gpu_message",
    "_no_torch_message",
    "_port_is_listening",
    "_preprocess",
    "_read_service_status",
    "_render_install_report",
    "_render_uninstall_report",
    "_service_child_env",
    "_service_doctor",
    "_service_jobs",
    "_service_lifecycle",
    "_service_logs",
    "_service_projects",
    "_service_qdrant",
    "_service_quiesce",
    "_service_reconcile",
    "_service_storage",
    "_service_watcher",
    "_spawn_service",
    "_status",
    "_status_file",
    "_store",
    "_suppress_hf_progress",
    "_terminate_pid",
    "_test",
    "_try_http_reindex",
    "_try_http_search",
    "_write_service_status",
    "app",
    "console",
    "run_cli",
]
