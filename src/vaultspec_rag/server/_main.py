"""Console-script entry point for the RAG daemon.

Split out of the original ``server.py`` monolith. ``main`` remains importable from the
package root (``vaultspec_rag.server:main``); the
``vaultspec-search-mcp`` console script depends on that import path.
``_http_mode`` is reassigned on the package namespace so
resources/prompts and ``_resolve_root`` observe the active transport
mode.

The entry point runs in two disjoint modes that no longer share an MCP
surface:

- HTTP mode (``--port`` given) is the service daemon. It serves native
  REST only (``/health`` plus the read-only ``ROUTES`` table) and
  eager-loads the GPU models via ``service_lifespan``. It does not mount
  any MCP app and does not import ``mcp``.
- stdio mode (no ``--port``) is the agent-facing MCP stdio transport. It
  serves MCP over stdio and loads no model: every tool delegates to the
  running daemon over HTTP through ``serviceclient``, so a model in this
  process would be dead weight. ``mcp`` is imported only on this path.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import TYPE_CHECKING

import vaultspec_rag.server as _m

from ._lifespan import health_handler, service_lifespan
from ._runtime import ServerRouteRuntime, install_route_runtime

if TYPE_CHECKING:
    from starlette.applications import Starlette
    from starlette.types import Lifespan

logger = logging.getLogger("vaultspec_rag.server")


def create_http_app(
    runtime: ServerRouteRuntime,
    lifespan: Lifespan[Starlette] | None,
) -> Starlette:
    """Build the one production HTTP route surface for *runtime*."""
    from starlette.applications import Starlette
    from starlette.routing import Route

    from ._routes import ROUTES

    app = Starlette(
        routes=[Route("/health", health_handler), *ROUTES],
        lifespan=lifespan,
    )
    install_route_runtime(app, runtime)
    return app


def _missing_mcp_extra_message(exc: ImportError) -> str:
    """Explain recovery without violating the selected placement mode."""
    return (
        "The RAG MCP stdio transport requires the optional 'mcp' extra, "
        f"which failed to import ({exc}). In tool mode, launch it with "
        "`uvx --from vaultspec-rag[mcp] python -m vaultspec_rag.server`; this "
        "does not modify the project. In dependency mode, add `[mcp]` to the "
        "existing `vaultspec-rag` requirement in `[project].dependencies`. In "
        "dev mode, add it to the existing requirement in "
        "`[dependency-groups].dev` or `[tool.uv].dev-dependencies`, whichever "
        "declares RAG, then run `uv sync`. "
        "`vaultspec-rag install --mcp --mode <mode>` reconciles the selected "
        "surface. On Windows, an installed-but-broken import is usually "
        "pywin32's post-install step not having run (a known mcp/pywin32 "
        "issue, upstream modelcontextprotocol/python-sdk#2233): run "
        "`python -m pywin32_postinstall -install` in that environment."
    )


def _resolve_daemon_argv() -> tuple[int | None, int | None, bool]:
    """Parse the daemon's launch flags from ``sys.argv``.

    The console-script path (no explicit ``port`` argument). Sets the
    per-process launch token on the package namespace exactly as the inline
    parse did, and returns ``(port, parent_pid, read_only)``.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="vaultspec-search-mcp",
        description="VaultSpec RAG daemon",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="HTTP port (default: stdio transport)",
    )
    parser.add_argument(
        "--parent-pid",
        type=int,
        default=None,
        help=(
            "Explicit client PID for the stdio lifetime watchdog "
            "(watched in addition to the discovered ancestor chain)"
        ),
    )
    parser.add_argument(
        "--launch-token",
        default="",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help=(
            "Serve only the search and read tools. The index-management tools "
            "are absent from the advertised listing, not merely refused, so a "
            "composing agent is never handed a schema it may not call."
        ),
    )
    args = parser.parse_args()
    _m._launch_token = str(args.launch_token)
    return args.port, args.parent_pid, args.read_only


def _run_http_daemon(port: int) -> None:
    """Run the standalone HTTP daemon and enforce its shutdown contract."""
    import uvicorn

    from ..config._settings import get_config
    from ..logging_config import configure_logging, install_daemon_log_capture
    from ..registry import get_registry

    # Install ordering (CRITICAL): argparse → configure_logging → capture → uvicorn.
    configure_logging(level="INFO")
    cfg = get_config()
    log_capture = install_daemon_log_capture(
        _m._resolve_log_path(),
        max_bytes=int(cfg.managed_log_max_bytes),
        backup_count=int(cfg.managed_log_backup_count),
    )
    runtime = ServerRouteRuntime(
        token=uuid.uuid4().hex,
        registry=get_registry(),
        port=port,
    )
    daemon_exit_code = 0
    try:
        from ..jobs import register_on_job_complete

        def _on_reindex_complete(duration_s: float) -> None:
            _m.incr("reindex_total")
            _m.observe("reindex_last_duration_seconds", duration_s)

        register_on_job_complete(_on_reindex_complete)
        app = create_http_app(runtime, service_lifespan)
        _m._daemon_process = True
        _m._daemon_log_capture = log_capture
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=runtime.port,
            timeout_graceful_shutdown=30,
            # Uvicorn's default log config is a second logging configuration:
            # it installs its own formatters and handlers and clears
            # propagation, so its records reach the managed log untimestamped
            # and unformatted, having never passed the root handler. Declining
            # it leaves uvicorn's loggers propagating to the one configured
            # root handler like every other producer.
            log_config=None,
            log_level="info",
            lifespan="on",
        )
    except BaseException:
        daemon_exit_code = 1
        raise
    finally:
        try:
            runtime.registry.close_all()
        finally:
            capture_closed = log_capture.close()
        if _m._daemon_process:
            os._exit(daemon_exit_code if capture_closed else 1)
        if not capture_closed:
            raise RuntimeError(
                "service log drain did not finish within its shutdown bound"
            )


def _run_stdio_mcp(parent_pid: int | None, *, read_only: bool = False) -> None:
    """Run the thin stdio MCP client without loading the indexing model.

    Under *read_only* the mutating tools are withdrawn before the first
    listing is served, so they are absent from the surface rather than
    present and refusing.
    """
    try:
        from ..mcp import mcp
    except ImportError as exc:
        raise RuntimeError(_missing_mcp_extra_message(exc)) from exc

    if read_only:
        from ..mcp._tools import restrict_to_read_only_tools

        restrict_to_read_only_tools()

    from ._stdio_lifetime import install_stdio_lifetime_watchdog

    install_stdio_lifetime_watchdog(parent_pid)
    _m._registry._on_close_project = _m._stop_watcher  # pyright: ignore[reportPrivateUsage]
    try:
        mcp.run(transport="stdio")
    finally:
        _m._stop_all_watchers()
        _m._registry.close_all()


def main(port: int | None = None) -> None:
    """Start the RAG daemon on stdio or HTTP transport.

    In HTTP mode, builds a Starlette app that serves the raw
    ``/health`` endpoint and the read-only ``ROUTES`` table, with
    ``service_lifespan`` for eager model loading. The daemon serves
    native REST only - no MCP surface is mounted.

    In stdio mode, delegates to ``mcp.run(transport="stdio")``. The
    stdio process loads no model: every tool reaches the running daemon
    over HTTP via ``serviceclient``, so stdio is a thin forwarder, not a
    duplicate service.

    When invoked as the ``vaultspec-search-mcp`` console script with no
    explicit ``port`` argument, parses ``sys.argv`` for ``--port`` and
    ``--help``. ``--help`` must be free (no GPU, no model load) so that
    packaging smoke tests and install probes succeed in environments
    without CUDA.

    Args:
        port: If provided, run on streamable-http at
            127.0.0.1:<port>. Otherwise parse argv (or use stdio).
    """
    parent_pid: int | None = None
    read_only = False
    if port is None:
        port, parent_pid, read_only = _resolve_daemon_argv()
    else:
        parent_pid = None
        _m._launch_token = ""

    _m._http_mode = port is not None

    if port is not None:
        _run_http_daemon(port)
        return
    _run_stdio_mcp(parent_pid, read_only=read_only)
