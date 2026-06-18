"""HTTP REST client helpers for the CLI fast path.

The wire client itself was factored into the import-light
``vaultspec_rag.serviceclient`` package so the CLI and the MCP consume one
surface. This module re-exports that surface unchanged so the CLI's existing
imports (and the tests that import these names from
``vaultspec_rag.cli._http_search``) keep working without behavior change.

Each ``_try_http_*`` helper talks to a running RAG service over HTTP and
discriminates "service unreachable" (connection refused -> ``None``) from
"live but broken" (structured error dict). ``_is_connection_refused`` walks
the exception chain to make that call.
"""

from __future__ import annotations

from ..serviceclient._transport import (
    DEFAULT_SEARCH_TIMEOUT_SECONDS,
    _do_http_call,
    _get_search_timeout,
    _is_connection_refused,
    _logs_route_path,
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
    "_do_http_call",
    "_get_search_timeout",
    "_is_connection_refused",
    "_logs_route_path",
    "_timeout_diagnostics",
    "_try_http_admin",
    "_try_http_benchmark",
    "_try_http_code_file",
    "_try_http_quality",
    "_try_http_reindex",
    "_try_http_search",
]
