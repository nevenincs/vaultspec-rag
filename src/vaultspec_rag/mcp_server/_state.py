"""Shared module-level state for the MCP server package.

Split out of the original ``mcp_server.py`` monolith per the
``2026-06-01-module-split-adr``. This module is the canonical home of
the singleton :data:`mcp` FastMCP instance and the process-wide
globals (registry, watcher bookkeeping, identity token, HTTP-mode
flag). The package ``__init__`` re-imports these names so they live in
the ``vaultspec_rag.mcp_server`` namespace, which is the target tests
rebind (e.g. ``mcp_server._http_mode = True``).

Rebind discipline (mirrors the ``cli`` split's monkeypatch handling):

- ``mcp``, ``_watcher_tasks``, ``_watcher_stops``, ``_watcher_lock``
  are mutated *in place* (decorator registration, dict insert/pop,
  lock acquire) and may be imported by reference.
- ``_registry``, ``_http_mode``, ``_SERVICE_TOKEN``, ``_start_time``
  are *reassigned* at runtime (``main`` sets ``_http_mode``;
  ``service_lifespan`` sets ``_start_time``/``_SERVICE_TOKEN``; tests
  rebind ``_registry``). Consumers must read them at call time through
  ``import vaultspec_rag.mcp_server as _m`` so a rebind on the package
  namespace is observed.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP

from ..registry import get_registry

if TYPE_CHECKING:
    import asyncio
    from pathlib import Path

logger = logging.getLogger("vaultspec_rag.mcp_server")

mcp = FastMCP("VaultSpec Search", stateless_http=True)

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
# response — mismatch reports the responding process is not the
# daemon named in ``service.json`` (gh #124 + #125: closes
# PID-reuse false-positives and unrelated-HTTP-server-on-port).
_SERVICE_TOKEN: str = ""

# Heartbeat contract. The daemon writes ``last_heartbeat`` to
# service.json every _HEARTBEAT_INTERVAL_SECONDS so
# ``vaultspec-rag server service status`` can detect a stale file
# (process killed without running atexit / signal handlers —
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
