"""Import-light service-client surface shared by the CLI and the MCP.

This package houses the production-proven HTTP wire client and the service
discovery helpers, factored out so both the CLI fast path and the MCP stdio
shell consume one surface without loading Torch, the models, or the store.
Importing it pulls only stdlib plus the lightweight filter validator; it is
the "CLI -> service is the only proven production path" client layer.
"""

from __future__ import annotations

from ._discovery import (
    DISCOVERY_REASON_POINTER_FOREIGN,
    DISCOVERY_REASON_POINTER_INVALID,
    DISCOVERY_REASON_POINTER_MISSING,
    DISCOVERY_REASON_POINTER_STALE,
    DISCOVERY_REASON_PROBE_FAILED,
    DISCOVERY_SOURCE_MACHINE_POINTER,
    DISCOVERY_SOURCE_NONE,
    DISCOVERY_SOURCE_STATUS_FILE,
    DISCOVERY_STATE_ABSENT,
    DISCOVERY_STATE_DEGRADED,
    DISCOVERY_STATE_READY,
    MachineResolution,
    _default_service_port,
    _delete_service_status,
    _read_service_status,
    _status_dir,
    _status_file,
    resolve_machine_service,
)
from ._transport import (
    DEFAULT_SEARCH_TIMEOUT_SECONDS,
    _do_http_call,
    _is_connection_refused,
    _timeout_diagnostics,
    _try_http_admin,
    _try_http_clean,
    _try_http_code_file,
    _try_http_create_job,
    _try_http_delete_job,
    _try_http_get_job,
    _try_http_reindex,
    _try_http_retry_job,
    _try_http_search,
    _try_http_set_job_desired_state,
    _try_http_vault_document,
)

__all__ = [
    "DEFAULT_SEARCH_TIMEOUT_SECONDS",
    "DISCOVERY_REASON_POINTER_FOREIGN",
    "DISCOVERY_REASON_POINTER_INVALID",
    "DISCOVERY_REASON_POINTER_MISSING",
    "DISCOVERY_REASON_POINTER_STALE",
    "DISCOVERY_REASON_PROBE_FAILED",
    "DISCOVERY_SOURCE_MACHINE_POINTER",
    "DISCOVERY_SOURCE_NONE",
    "DISCOVERY_SOURCE_STATUS_FILE",
    "DISCOVERY_STATE_ABSENT",
    "DISCOVERY_STATE_DEGRADED",
    "DISCOVERY_STATE_READY",
    "MachineResolution",
    "_default_service_port",
    "_delete_service_status",
    "_do_http_call",
    "_is_connection_refused",
    "_read_service_status",
    "_status_dir",
    "_status_file",
    "_timeout_diagnostics",
    "_try_http_admin",
    "_try_http_clean",
    "_try_http_code_file",
    "_try_http_create_job",
    "_try_http_delete_job",
    "_try_http_get_job",
    "_try_http_reindex",
    "_try_http_retry_job",
    "_try_http_search",
    "_try_http_set_job_desired_state",
    "_try_http_vault_document",
    "resolve_machine_service",
]
