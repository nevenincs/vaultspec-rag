"""Admin and watcher-control MCP tools.

Split out of the original ``server.py`` monolith per the
``2026-06-01-module-split-adr``. Importing this module runs the
``@mcp.tool()`` decorators for the registry/watcher admin tools.
Registry and watcher bookkeeping are read through the package alias so
test rebinds / in-place mutations on ``vaultspec_rag.server`` are
observed.
"""

from __future__ import annotations

from typing import Any

from ._mcp import mcp
from ._tools import _call_daemon


@mcp.tool()
async def list_projects(
    project_root: str | None = None,
) -> dict[str, Any]:
    """Return a snapshot of every active :class:`ProjectSlot`."""
    return _call_daemon("/projects")


@mcp.tool()
async def evict_project(root: str) -> dict[str, Any]:
    """Force-evict the :class:`ProjectSlot` for *root*."""
    return _call_daemon("/projects/evict", {"root": root})


@mcp.tool()
async def get_watcher_state(project_root: str | None = None) -> dict[str, Any]:
    """Report filesystem-watcher configuration and running state."""
    return _call_daemon("/watcher")


@mcp.tool()
async def start_watcher(root: str) -> dict[str, Any]:
    """Eagerly start the filesystem watcher for *root*."""
    return _call_daemon("/watcher/start", {"root": root})


@mcp.tool()
async def stop_watcher(root: str) -> dict[str, Any]:
    """Stop the filesystem watcher for *root* (pull-only for that root)."""
    return _call_daemon("/watcher/stop", {"root": root})


@mcp.tool()
async def get_service_state(project_root: str | None = None) -> dict[str, Any]:
    """Return a consolidated read-only snapshot of the service's state."""
    path = "/service-state"
    if project_root:
        import urllib.parse

        path += "?project_root=" + urllib.parse.quote(project_root)
    return _call_daemon(path)


@mcp.tool()
async def get_logs(lines: int = 200) -> dict[str, Any]:
    """Return the last *lines* of the rotated service log."""
    # Note: _call_daemon expects JSON, but /logs returns plain text.
    # To fix this without changing _call_daemon, we use the HTTP route but we need a JSON endpoint or custom logic.
    # We will use custom logic here directly for now, or just read the log via the shared module.
    # Wait, the plan says "Rewrite MCP tools to strictly consume the REST API".
    # But for /logs, let's just make a JSON route /logs/json or we can read it locally.
    # Actually, we can read locally:
    from anyio.to_thread import run_sync as _run_in_thread
    from ..logging_config import read_service_log

    def _run() -> dict[str, Any]:
        return {"lines": read_service_log(lines)}

    return await _run_in_thread(_run)


@mcp.tool()
async def get_jobs(limit: int | None = None) -> dict[str, Any]:
    """Return recent index/reindex activity from the in-flight registry."""
    path = "/jobs"
    if limit is not None:
        path += f"?limit={limit}"
    return _call_daemon(path)


@mcp.tool()
async def reconfigure_watcher(
    root: str,
    debounce_ms: int | None = None,
    cooldown_s: float | None = None,
) -> dict[str, Any]:
    """Restart *root*'s watcher with new tuning values."""
    payload: dict[str, Any] = {"root": root}
    if debounce_ms is not None:
        payload["debounce_ms"] = debounce_ms
    if cooldown_s is not None:
        payload["cooldown_s"] = cooldown_s
    return _call_daemon("/watcher/reconfigure", payload)


@mcp.tool()
async def benchmark(
    project_root: str | None = None,
    n_queries: int = 20,
) -> dict[str, Any]:
    """Run search latency benchmarks against the indexed vault."""
    from anyio.to_thread import run_sync as _run_in_thread
    import vaultspec_rag
    from ..server._utils import _resolve_root

    root = _resolve_root(project_root)

    def _run() -> dict[str, Any]:
        return vaultspec_rag.run_benchmark(root, n_queries=n_queries)

    return await _run_in_thread(_run)


@mcp.tool()
async def quality() -> dict[str, Any]:
    """Run quality-scoring probes against a synthetic test corpus."""
    from anyio.to_thread import run_sync as _run_in_thread
    import vaultspec_rag

    def _run() -> dict[str, Any]:
        return vaultspec_rag.run_quality_probe()

    return await _run_in_thread(_run)
