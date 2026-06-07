"""Console-script entry point for the MCP server.

Split out of the original ``mcp_server.py`` monolith per the
``2026-06-01-module-split-adr``. ``main`` remains importable from the
package root (``vaultspec_rag.mcp_server:main``) - both the
``vaultspec-search-mcp`` console script and the CLI's ``mcp start``
command depend on that import path. ``_http_mode`` is reassigned on the
package namespace so resources/prompts and ``_resolve_root`` observe
the active transport mode.
"""

from __future__ import annotations

import logging

import vaultspec_rag.mcp_server as _m

from ._lifespan import health_handler, service_lifespan
from vaultspec_rag.mcp import mcp

logger = logging.getLogger("vaultspec_rag.mcp_server")


def main(port: int | None = None) -> None:
    """Start the MCP server on stdio or HTTP transport.

    In HTTP mode, builds a Starlette app that mounts the MCP
    streamable-HTTP transport at ``/mcp`` and a raw ``/health``
    endpoint, with ``service_lifespan`` for eager model loading.

    In stdio mode, delegates to ``mcp.run(transport="stdio")``
    for Claude Desktop compatibility (no lifespan).

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
            description="VaultSpec RAG MCP server",
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
        from starlette.routing import Mount, Route

        from ..config import get_config
        from ..logging_config import (
            configure_logging,
            install_daemon_log_rotation,
        )

        # ADR D1 install ordering (CRITICAL):
        # argparse → configure_logging → install_daemon_log_rotation → uvicorn.run.
        # The spawned daemon inherits the parent's stdout/stderr FD
        # redirection onto service.log via Popen, but its own
        # logging handlers are empty.  Core's configure_logging
        # installs a stderr RichHandler, and install_daemon_log_rotation
        # then layers the rotating file handler on top and re-dup2s
        # fds 1/2 onto the rotating stream.  Rotation is a stdio-mode
        # asymmetry on purpose: stdio is one-shot CLI tooling, not a
        # long-lived daemon, so no rotation is needed there.
        configure_logging()
        cfg = get_config()
        install_daemon_log_rotation(
            _m._resolve_log_path(),
            max_bytes=int(cfg.service_log_max_bytes),
            backup_count=int(cfg.service_log_backup_count),
        )

        # Override the default streamable_http_path so the inner
        # Starlette app serves at "/" instead of "/mcp".  Combined
        # with Mount("/mcp"), the effective client URL is "/mcp".
        mcp.settings.streamable_http_path = "/"
        mcp_http_app = mcp.streamable_http_app()

        # Starlette's ``Mount`` redirects bare "/mcp" to "/mcp/" with
        # a 307 hop. The Starlette version pinned here does not expose
        # a ``redirect_slashes=False`` constructor argument, so we
        # rewrite the request path before routing instead - an ASGI
        # wrapper that promotes "/mcp" to "/mcp/" in-process. Both
        # URLs now land directly on the inner app, with no redirect.
        from ._routes import ROUTES as READ_ONLY_ROUTES

        # ``/health`` stays UNGATED (registered here, not in
        # ``_routes``); the P03 read-only routes (e.g. token-gated
        # ``/logs``) register from ``_routes.ROUTES`` on this same inner
        # app. No ASGI wrappers - Starlette ``Route``s only
        # (server-mcp-route + service-observability ADRs).
        app = Starlette(
            routes=[
                Mount("/mcp", app=mcp_http_app),
                Route("/health", health_handler),
                *READ_ONLY_ROUTES,
            ],
            lifespan=service_lifespan,
        )

        async def _mcp_no_redirect(scope, receive, send):
            if scope["type"] == "http" and scope.get("path") == "/mcp":
                scope = {**scope, "path": "/mcp/", "raw_path": b"/mcp/"}
            await app(scope, receive, send)

        try:
            uvicorn.run(
                _mcp_no_redirect,
                host="127.0.0.1",
                port=port,
                timeout_graceful_shutdown=30,
                log_level="info",
                lifespan="on",
            )
        finally:
            _m._registry.close_all()
    else:
        # Eager model load for stdio - matches HTTP mode's service_lifespan.
        # Without this, the first tool call hits "EmbeddingModel not loaded"
        # because ServiceRegistry.lease()/peek_project() require a loaded model.
        _m._registry.load_model()
        _m._registry._on_close_project = _m._stop_watcher
        try:
            mcp.run(transport="stdio")
        finally:
            _m._stop_all_watchers()
            _m._registry.close_all()
