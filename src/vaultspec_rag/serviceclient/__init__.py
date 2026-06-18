"""Import-light service-client surface shared by the CLI and the MCP.

This package houses the production-proven HTTP wire client and the service
discovery helpers, factored out so both the CLI fast path and the MCP stdio
shell consume one surface without loading Torch, the models, or the store.
Importing it pulls only stdlib plus the lightweight filter validator; it is
the "CLI -> service is the only proven production path" client layer.
"""

from __future__ import annotations

from ._discovery import (
    _default_service_port,
    _read_service_status,
    _status_dir,
    _status_file,
)
from ._transport import (
    DEFAULT_SEARCH_TIMEOUT_SECONDS,
    _do_http_call,
    _is_connection_refused,
    _timeout_diagnostics,
    _try_http_admin,
    _try_http_benchmark,
    _try_http_code_file,
    _try_http_quality,
    _try_http_reindex,
    _try_http_search,
)

__all__ = [
    "DEFAULT_SEARCH_TIMEOUT_SECONDS",
    "_default_service_port",
    "_do_http_call",
    "_is_connection_refused",
    "_read_service_status",
    "_status_dir",
    "_status_file",
    "_timeout_diagnostics",
    "_try_http_admin",
    "_try_http_benchmark",
    "_try_http_code_file",
    "_try_http_quality",
    "_try_http_reindex",
    "_try_http_search",
]
