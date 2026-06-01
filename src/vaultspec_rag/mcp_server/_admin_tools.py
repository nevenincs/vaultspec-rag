"""Admin and watcher-control MCP tools.

Split out of the original ``mcp_server.py`` monolith per the
``2026-06-01-module-split-adr``. Importing this module runs the
``@mcp.tool()`` decorators for the registry/watcher admin tools.
Registry and watcher bookkeeping are read through the package alias so
test rebinds / in-place mutations on ``vaultspec_rag.mcp_server`` are
observed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from anyio.to_thread import run_sync as _run_in_thread

import vaultspec_rag.mcp_server as _m

from ._state import mcp


@mcp.tool()
async def list_projects(
    project_root: str | None = None,
) -> dict[str, Any]:
    """Return a snapshot of every active :class:`ProjectSlot`.

    Args:
        project_root: Accepted for signature parity with other admin
            tools (``get_index_status``, ``reindex_*``).  Ignored —
            the list is registry-wide.

    Returns:
        Dict with keys ``projects`` (list), ``max_projects`` (int),
        and ``idle_ttl_seconds`` (float).  Each project entry has
        ``root``, ``last_access_iso`` (ISO-8601 local timestamp
        derived from the monotonic ``idle_seconds``),
        ``idle_seconds``, and ``ref_count``.
    """
    del project_root  # signature parity only

    def _run() -> dict[str, Any]:
        from datetime import datetime

        snapshot = _m._registry.snapshot()
        wall_now = datetime.now().astimezone()
        projects = []
        for entry in snapshot:
            idle_s = float(entry["idle_seconds"])
            last_access_wall = wall_now.timestamp() - idle_s
            last_access_iso = (
                datetime.fromtimestamp(last_access_wall).astimezone().isoformat()
            )
            projects.append(
                {
                    "root": str(entry["root"]),
                    "last_access_iso": last_access_iso,
                    "idle_seconds": idle_s,
                    "ref_count": int(entry["ref_count"]),
                },
            )
        return {
            "projects": projects,
            "max_projects": _m._registry.max_projects,
            "idle_ttl_seconds": _m._registry.idle_ttl_seconds,
        }

    return await _run_in_thread(_run)


@mcp.tool()
async def evict_project(root: str) -> dict[str, Any]:
    """Force-evict the :class:`ProjectSlot` for *root*.

    Args:
        root: Workspace root directory (resolved internally).

    Returns:
        One of:

        - ``{"evicted": True,  "reason": "forced"}`` — slot removed.
        - ``{"evicted": False, "reason": "busy"}`` — slot had live
          leases; operator should retry.
        - ``{"evicted": False, "reason": "not_found"}`` — unknown
          root.
    """
    target = Path(root).resolve()

    def _run() -> dict[str, Any]:
        evicted, reason = _m._registry.try_evict(target)
        return {"evicted": evicted, "reason": reason}

    return await _run_in_thread(_run)


@mcp.tool()
async def get_watcher_state(project_root: str | None = None) -> dict[str, Any]:
    """Report filesystem-watcher configuration and running state.

    Runs on the event loop (reads watcher bookkeeping directly); does
    not touch the GPU, so it is not dispatched to a worker thread.

    Args:
        project_root: Optional root; when given, a ``running`` boolean
            for that resolved root is included.

    Returns:
        Dict with ``watch_enabled`` (bool), ``debounce_ms`` (int),
        ``cooldown_s`` (float), and ``watching`` (list of resolved
        root paths with a live watcher). When *project_root* is given,
        also ``running`` (bool) for that root.
    """
    from ..config import get_config

    cfg = get_config()
    with _m._watcher_lock:
        watching = [str(r) for r in _m._watcher_tasks]
    state: dict[str, Any] = {
        "watch_enabled": bool(cfg.watch_enabled),
        "debounce_ms": int(cfg.watch_debounce_ms),
        "cooldown_s": float(cfg.watch_cooldown_s),
        "watching": watching,
    }
    if project_root is not None:
        state["running"] = str(Path(project_root).resolve()) in watching
    return state


@mcp.tool()
async def start_watcher(root: str) -> dict[str, Any]:
    """Eagerly start the filesystem watcher for *root*.

    Honours the ``watch_enabled`` opt-out: when watching is disabled
    the service stays pull-only and no watcher is started.

    Args:
        root: Workspace root directory (resolved internally).

    Returns:
        Dict with ``root``, ``started`` (bool — running on return), and
        ``watch_enabled`` (bool).
    """
    from ..config import get_config

    target = Path(root).resolve()
    started = _m._ensure_watcher(target)
    return {
        "root": str(target),
        "started": bool(started),
        "watch_enabled": bool(get_config().watch_enabled),
    }


@mcp.tool()
async def stop_watcher(root: str) -> dict[str, Any]:
    """Stop the filesystem watcher for *root* (pull-only for that root).

    Args:
        root: Workspace root directory (resolved internally).

    Returns:
        Dict with ``root`` and ``stopped`` (bool — whether a watcher was
        running and has now been stopped).
    """
    target = Path(root).resolve()
    with _m._watcher_lock:
        was_running = target in _m._watcher_tasks
    _m._stop_watcher(target)
    return {"root": str(target), "stopped": bool(was_running)}


@mcp.tool()
async def get_service_state(project_root: str | None = None) -> dict[str, Any]:
    """Return a consolidated read-only snapshot of the service's state.

    A Tier-1 observability read (``service-observability`` ADR): one
    structured document that mirrors state the service already holds —
    per-source index counts + GPU/device (reusing ``get_index_status``
    logic), the project slot table (reusing ``list_projects`` data), and
    a watcher rollup (reusing ``get_watcher_state`` data). Read-only; no
    control. Surfaced verbatim by ``server service info``.

    Args:
        project_root: Optional project root for the index/GPU section.
            Defaults to ``VAULTSPEC_RAG_ROOT`` env var or cwd (stdio
            only); required in HTTP service mode. The projects and
            watcher sections are registry-wide and ignore this value.

    Returns:
        Dict with keys:

        - ``index`` — the ``get_index_status`` payload (vault/code
          counts, storage path, target dir, GPU VRAM) or a structured
          error dict when the registry is full.
        - ``projects`` — the ``list_projects`` payload (slot list,
          ``max_projects``, ``idle_ttl_seconds``).
        - ``watcher`` — the ``get_watcher_state`` rollup (enable flag,
          debounce/cooldown, watched roots).
    """
    from ._tools import get_index_status

    index = await get_index_status(project_root=project_root)
    projects = await list_projects(project_root=project_root)
    watcher = await get_watcher_state(project_root=project_root)

    index_data: dict[str, Any] = (
        index if isinstance(index, dict) else index.model_dump()
    )
    return {
        "index": index_data,
        "projects": projects,
        "watcher": watcher,
    }


@mcp.tool()
async def get_logs(lines: int = 200) -> dict[str, Any]:
    """Return the last *lines* of the rotated service log.

    A Tier-2a observability read (``service-observability`` ADR) with
    parity to the read-only ``GET /logs`` HTTP route: both call the
    shared :func:`~vaultspec_rag.logging_config.read_service_log` reader
    that spans the rotated set (``service.log`` + ``.log.1..N``) oldest
    -first, newest last, tolerant of a file vanishing mid-rollover. File
    I/O runs on a worker thread.

    Args:
        lines: Maximum number of trailing lines to return (default
            200). Values ``<= 0`` yield an empty list.

    Returns:
        Dict with key ``lines`` — the list of log lines (without
        trailing newlines), oldest-first.
    """
    from ..logging_config import read_service_log

    def _run() -> dict[str, Any]:
        return {"lines": read_service_log(lines)}

    return await _run_in_thread(_run)


@mcp.tool()
async def reconfigure_watcher(
    root: str,
    debounce_ms: int | None = None,
    cooldown_s: float | None = None,
) -> dict[str, Any]:
    """Restart *root*'s watcher with new tuning values.

    ``awatch`` fixes its debounce at construction, so reconfiguration
    is a stop-then-restart. Values left ``None`` fall back to the
    resolved config defaults. Honours the ``watch_enabled`` opt-out.

    Args:
        root: Workspace root directory (resolved internally).
        debounce_ms: New debounce window (ms); ``None`` uses config.
        cooldown_s: New per-source cooldown (s); ``None`` uses config.

    Returns:
        Dict with ``root``, ``restarted`` (bool), and the effective
        ``debounce_ms`` / ``cooldown_s`` in force after the restart.
    """
    from ..config import get_config

    target = Path(root).resolve()
    _m._stop_watcher(target)
    restarted = _m._ensure_watcher(
        target,
        debounce_ms=debounce_ms,
        cooldown_s=cooldown_s,
    )
    cfg = get_config()
    return {
        "root": str(target),
        "restarted": bool(restarted),
        "debounce_ms": int(debounce_ms)
        if debounce_ms is not None
        else int(cfg.watch_debounce_ms),
        "cooldown_s": float(cooldown_s)
        if cooldown_s is not None
        else float(cfg.watch_cooldown_s),
    }
