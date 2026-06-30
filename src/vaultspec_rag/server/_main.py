"""Console-script entry point for the RAG daemon.

Split out of the original ``server.py`` monolith per the
``2026-06-01-module-split-adr``. ``main`` remains importable from the
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

import vaultspec_rag.server as _m

from ._lifespan import health_handler, service_lifespan

logger = logging.getLogger("vaultspec_rag.server")


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
    if port is None:
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
        args = parser.parse_args()
        port = args.port

    _m._http_mode = port is not None

    if port is not None:
        import uvicorn
        from starlette.applications import Starlette
        from starlette.routing import Route

        from ..config import get_config
        from ..logging_config import (
            configure_logging,
            install_daemon_log_rotation,
        )

        # Install ordering (CRITICAL):
        # argparse → configure_logging → install_daemon_log_rotation → uvicorn.run.
        # The spawned daemon inherits the parent's stdout/stderr FD
        # redirection onto service.log via Popen, but its own
        # logging handlers are empty.  Core's configure_logging
        # installs a stderr RichHandler, and install_daemon_log_rotation
        # then layers the rotating file handler on top and re-dup2s
        # fds 1/2 onto the rotating stream.  Rotation is a stdio-mode
        # asymmetry on purpose: stdio is one-shot CLI tooling, not a
        # long-lived daemon, so no rotation is needed there.
        configure_logging(level="INFO")
        cfg = get_config()
        install_daemon_log_rotation(
            _m._resolve_log_path(),
            max_bytes=int(cfg.service_log_max_bytes),
            backup_count=int(cfg.service_log_backup_count),
        )

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

        try:
            uvicorn.run(
                app,
                host="127.0.0.1",
                port=port,
                timeout_graceful_shutdown=30,
                log_level="info",
                lifespan="on",
            )
        finally:
            _m._registry.close_all()
    else:
        # stdio is the sole MCP transport. ``mcp`` is imported only here:
        # the HTTP daemon no longer mounts any MCP app, so it never needs
        # the package, and ``mcp`` is an optional extra rather than a core
        # dependency. The guarded ImportError keeps the actionable
        # pywin32/missing-extra message on the one path that requires it.
        try:
            from ..mcp import mcp
        except ImportError as exc:  # missing mcp extra, or a broken pywin32 link
            raise RuntimeError(
                "The RAG MCP stdio transport requires the optional 'mcp' extra, "
                f"which failed to import ({exc}). Install it with "
                "`uv add vaultspec-rag[mcp]` (or re-run `vaultspec-rag install`, "
                "which adds it by default). On Windows, an installed-but-broken "
                "import is usually pywin32's post-install step not having run (a "
                "known mcp/pywin32 issue, upstream "
                "modelcontextprotocol/python-sdk#2233): run "
                "`python -m pywin32_postinstall -install` in this environment."
            ) from exc

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
