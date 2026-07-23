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

import vaultspec_rag.server as _m

from ._lifespan import health_handler, service_lifespan

logger = logging.getLogger("vaultspec_rag.server")


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


def _resolve_daemon_argv() -> tuple[int | None, int | None]:
    """Parse ``--port``/``--parent-pid``/``--launch-token`` from ``sys.argv``.

    The console-script path (no explicit ``port`` argument). Sets the
    per-process launch token on the package namespace exactly as the inline
    parse did, and returns ``(port, parent_pid)``.
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
    args = parser.parse_args()
    _m._launch_token = str(args.launch_token)
    return args.port, args.parent_pid


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
    if port is None:
        port, parent_pid = _resolve_daemon_argv()
    else:
        parent_pid = None
        _m._launch_token = ""

    _m._http_mode = port is not None
    _m._service_port = port or 0

    if port is not None:
        import uvicorn
        from starlette.applications import Starlette
        from starlette.routing import Route

        from ..config import get_config
        from ..logging_config import (
            configure_logging,
            install_daemon_log_capture,
        )

        # Install ordering (CRITICAL):
        # argparse → configure_logging → install_daemon_log_capture → uvicorn.run.
        # The spawned daemon inherits the parent's stdout/stderr FD
        # redirection onto service.log via Popen. Core's configure_logging
        # installs its normal stderr sink; install_daemon_log_capture replaces
        # it with one canonical stream and redirects fds 1/2 into a pipe whose
        # bounded drain is the only service.log writer. Rotation is a stdio-mode
        # asymmetry on purpose: stdio is one-shot CLI tooling, not a
        # long-lived daemon, so no rotation is needed there.
        configure_logging(level="INFO")
        cfg = get_config()
        log_capture = install_daemon_log_capture(
            _m._resolve_log_path(),
            max_bytes=int(cfg.managed_log_max_bytes),
            backup_count=int(cfg.managed_log_backup_count),
        )

        daemon_exit_code = 0
        try:
            from ..jobs import register_on_job_complete
            from ._routes import ROUTES as READ_ONLY_ROUTES

            def _on_reindex_complete(duration_s: float) -> None:
                _m.incr("reindex_total")
                _m.observe("reindex_last_duration_seconds", duration_s)

            register_on_job_complete(_on_reindex_complete)

            # ``/health`` stays UNGATED (registered here, not in
            # ``_routes``); the read-only routes (e.g. token-gated ``/logs``)
            # register from ``_routes.ROUTES`` on this same app. The daemon
            # serves native REST only: no MCP mount, no ASGI wrappers, just
            # Starlette ``Route``s. The MCP is a separate stdio client that
            # reaches these routes over HTTP.
            app = Starlette(
                routes=[
                    Route("/health", health_handler),
                    *READ_ONLY_ROUTES,
                ],
                lifespan=service_lifespan,
            )

            # Arm the standalone-daemon exit backstop before the event loop
            # starts. ``service_lifespan`` forces a prompt ``os._exit`` after its
            # bounded shutdown so a wedged ``to_thread`` worker cannot hang the
            # interpreter-exit executor join. The stashed capture lets that exit
            # flush ``service.log`` first. Both are read only via the package
            # alias; the in-process embedded-reuse lifespan never sets them.
            _m._daemon_process = True
            _m._daemon_log_capture = log_capture

            uvicorn.run(
                app,
                host="127.0.0.1",
                port=port,
                timeout_graceful_shutdown=30,
                log_level="info",
                lifespan="on",
            )
        except BaseException:
            daemon_exit_code = 1
            raise
        finally:
            try:
                _m._registry.close_all()
            finally:
                capture_closed = log_capture.close()
            # Standalone-daemon exit backstop. ``service_lifespan`` forces its own
            # ``os._exit`` on the clean-serving and guarded-startup-failure paths,
            # so reaching here on the daemon means ``uvicorn.run`` returned or
            # raised WITHOUT that exit firing - a failed port bind, or a startup
            # error uvicorn surfaced before the lifespan ran. Force the exit so the
            # interpreter-exit executor join cannot wedge this daemon alive owning
            # nothing (the orphan-accumulation class). The in-process
            # embedded-reuse host (no ``_daemon_process``) skips it and enforces
            # the log-drain contract instead.
            if _m._daemon_process:
                os._exit(daemon_exit_code if capture_closed else 1)
            if not capture_closed:
                raise RuntimeError(
                    "service log drain did not finish within its shutdown bound"
                )
    else:
        # stdio is the sole MCP transport. ``mcp`` is imported only here:
        # the HTTP daemon no longer mounts any MCP app, so it never needs
        # the package, and ``mcp`` is an optional extra rather than a core
        # dependency. The guarded ImportError keeps the actionable
        # pywin32/missing-extra message on the one path that requires it.
        try:
            from ..mcp import mcp
        except ImportError as exc:  # missing mcp extra, or a broken pywin32 link
            raise RuntimeError(_missing_mcp_extra_message(exc)) from exc

        # The watchdog is stdio-only: this process's lifetime is its client
        # connection, unlike the HTTP daemon above, which outlives its
        # spawner by design. stdin EOF stays the primary exit; the watchdog
        # reaps the shim when the spawning chain breaks without an EOF
        # (abandoned generations, killed uv.exe).
        from ._stdio_lifetime import install_stdio_lifetime_watchdog

        install_stdio_lifetime_watchdog(parent_pid)

        # No model load: the stdio MCP holds no GPU resource. Every tool
        # delegates to the running daemon over HTTP through serviceclient,
        # so a model loaded here would be dead weight (and would violate
        # the thin-client "load no Torch" contract).
        _m._registry._on_close_project = _m._stop_watcher  # pyright: ignore[reportPrivateUsage]
        try:
            mcp.run(transport="stdio")
        finally:
            _m._stop_all_watchers()
            _m._registry.close_all()
