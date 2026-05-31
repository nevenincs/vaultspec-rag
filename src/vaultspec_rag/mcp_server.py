"""MCP server for VaultSpec RAG search and retrieval.

Exposes tools for searching vault and codebase, resources for
retrieving full contents, and prompts for common RAG tasks.

In HTTP mode the server runs inside a Starlette application with
a ``service_lifespan`` that eagerly loads GPU models before
accepting connections.  A raw ``/health`` endpoint is mounted
alongside the MCP transport at ``/mcp``.
"""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import fnmatch
import json
import logging
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from anyio.to_thread import run_sync as _run_in_thread
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from .capabilities import BackendCapabilities, backend_capabilities_dict
from .progress import NullProgressReporter
from .registry import get_registry
from .service import RegistryFullError
from .store import VaultStoreLockedError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.applications import Starlette
    from starlette.requests import Request

logger = logging.getLogger(__name__)

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


def _resolve_log_path() -> Path:
    """Resolve the daemon's rotating log path.

    Mirrors the parent CLI's ``_log_file()`` resolution so the
    daemon writes to the same file the parent created on spawn.
    """
    from .config import get_config

    cfg = get_config()
    status_dir = Path(cfg.status_dir).expanduser()
    status_dir.mkdir(parents=True, exist_ok=True)
    return status_dir / cfg.log_file


def _registry_full_error_dict(exc: RegistryFullError) -> dict[str, Any]:
    """Build the ADR D4 structured error dict for registry-full errors."""
    return {
        "ok": False,
        "error": "registry_full",
        "message": str(exc),
        "max_projects": _registry.max_projects,
        "busy_projects": [str(p) for p in _registry.busy_roots()],
    }


def _local_store_locked_error_dict(exc: VaultStoreLockedError) -> dict[str, Any]:
    """Build a structured error for local Qdrant file-lock contention."""
    return {
        "ok": False,
        "error": "local_store_locked",
        "message": (
            "The local Qdrant index is already open by another vaultspec-rag "
            "process. Route concurrent searches through one resident "
            "vaultspec-rag service, or retry after the other process exits."
        ),
        "db_path": exc.db_path,
        "backend_capabilities": backend_capabilities_dict(),
    }


def _validate_vault_root(root: Path) -> Path:
    """Ensure *root* contains a ``.vault/`` directory.

    Args:
        root: Resolved project root path.

    Returns:
        The validated path (unchanged).

    Raises:
        ValueError: If *root* has no ``.vault/`` subdirectory.
    """
    if not (root / ".vault").is_dir():
        msg = f"not a vaultspec project (no .vault/ directory): {root}"
        raise ValueError(msg)
    return root


def _default_root() -> Path:
    """Resolve the default project root from env or cwd.

    Only used in stdio mode.  HTTP mode must always provide an
    explicit ``project_root`` — see ``_resolve_root()``.

    Returns:
        Resolved ``Path`` from ``VAULTSPEC_RAG_ROOT`` env var, falling
        back to the current working directory.

    Raises:
        ValueError: If called in HTTP mode (should never happen —
            ``_resolve_root`` guards this).
    """
    if _http_mode:
        msg = (
            "project_root is required in HTTP service mode — "
            "the multi-tenant service has no default project"
        )
        raise ValueError(msg)
    from .config import EnvVar

    root_env = os.environ.get(EnvVar.RAG_ROOT)
    root = Path(root_env).resolve() if root_env else Path.cwd().resolve()
    return _validate_vault_root(root)


# -- lifecycle helpers ------------------------------------------------------


def _status_file_path() -> Path:
    """Resolve the same ``service.json`` path the CLI parent writes.

    The CLI ``cli._status_file()`` builds this path from
    ``cfg.status_dir``; the daemon mirrors that resolution so it can
    own end-of-life cleanup without cross-importing from cli.
    """
    from .config import get_config

    cfg = get_config()
    return Path(cfg.status_dir).expanduser() / "service.json"


def _lifecycle_log(event: str, **kv: object) -> None:
    """Emit a structured lifecycle entry at WARNING level.

    WARNING (not INFO) because ``VAULTSPEC_RAG_LOG_LEVEL`` defaults to
    WARNING, so INFO lines are silent by default. Operators see the
    lifecycle without opt-in.

    Args:
        event: Short identifier (``startup`` / ``shutdown``).
        **kv: Extra key=value fields rendered space-separated for
            greppability.
    """
    parts = [f"event={event}"]
    parts.extend(f"{k}={v}" for k, v in kv.items())
    logger.warning("service.lifecycle %s", " ".join(parts))


def _unlink_status_file_silently() -> None:
    """Best-effort unlink of service.json; ignores missing/locked.

    Called from atexit, signal handlers, and the lifespan finally
    block. Idempotent because any of those code paths may have
    already removed the file.
    """
    path = _status_file_path()
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning(
            "service.lifecycle event=cleanup_failed path=%s error=%s",
            path,
            exc,
        )


def _heartbeat_tick_sync() -> None:
    """Synchronous heartbeat write — atomic via .tmp + os.replace.

    Reads the current service.json, merges ``last_heartbeat`` (ISO-8601
    UTC, second resolution), writes through a tmp file. Called from
    inside ``asyncio.to_thread`` so file I/O does not block the event
    loop.

    Exits silently when service.json is missing (the CLI parent may
    have unlinked it during ``server service stop`` — the heartbeat
    loop will exit on the next tick).
    """
    path = _status_file_path()
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        # Read failures are best-effort: the CLI parent wrote the
        # file; the daemon's tick is additive. Debug-log so the
        # swallow stays observable (no-swallow rule).
        logger.debug(
            "heartbeat tick: failed to read %s: %s",
            path,
            exc,
            exc_info=True,
        )
        return
    if not isinstance(data, dict):
        logger.debug(
            "heartbeat tick: %s did not deserialise to dict (got %r)",
            path,
            type(data).__name__,
        )
        return
    data["last_heartbeat"] = datetime.now(UTC).isoformat(timespec="seconds")
    # Per-process identity token. Empty during the narrow window
    # between module import and service_lifespan startup; the guard
    # prevents an in-flight zero-value overwrite of a token written
    # by a previous daemon process that crashed without unlinking
    # service.json.
    if _SERVICE_TOKEN:
        data["service_token"] = _SERVICE_TOKEN
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(str(tmp), str(path))


async def _heartbeat_loop() -> None:
    """Periodic heartbeat task; cancelled in the lifespan finally.

    Sleeps ``_HEARTBEAT_INTERVAL_SECONDS`` between ticks. Tolerates
    transient write failures so an I/O blip never crashes the
    service; the next tick retries.
    """
    while True:
        try:
            await asyncio.sleep(_HEARTBEAT_INTERVAL_SECONDS)
            await asyncio.to_thread(_heartbeat_tick_sync)
        except asyncio.CancelledError:
            return
        except Exception:  # heartbeat must never crash the service
            logger.warning(
                "service.lifecycle event=heartbeat_failed",
                exc_info=True,
            )


_shutdown_hooks_installed = False
_shutdown_recorded = False


def _record_shutdown(reason: str, **kv: object) -> None:
    """Log + unlink once; subsequent calls are no-ops.

    atexit, the signal handler, and the lifespan finally block may
    all fire in sequence. The first one wins.
    """
    global _shutdown_recorded
    if _shutdown_recorded:
        return
    _shutdown_recorded = True
    _lifecycle_log("shutdown", reason=reason, **kv)
    _unlink_status_file_silently()


def _install_daemon_shutdown_hooks() -> None:
    """Register atexit cleanup once per process.

    SIGTERM/SIGINT are intentionally NOT overridden — uvicorn already
    installs its own graceful-shutdown handler for those signals that
    triggers the lifespan ``finally`` block (which calls
    ``_record_shutdown("clean")``). Overriding here breaks that
    cooperation: a manual signal handler re-raising via
    ``os.kill(SIG_DFL)`` exits the process before logging buffers
    flush, so the lifecycle log line never lands on disk.

    atexit covers the cases uvicorn doesn't (fatal exception during
    startup, ``sys.exit`` from inside the request path). SIGKILL /
    OOM remain unreachable by design; the heartbeat staleness check
    in ``service status`` is the safety net for those.

    Idempotent: a second call is a no-op.
    """
    global _shutdown_hooks_installed
    if _shutdown_hooks_installed:
        return
    _shutdown_hooks_installed = True

    atexit.register(lambda: _record_shutdown("atexit"))


# -- lifespan ---------------------------------------------------------------


@asynccontextmanager
async def service_lifespan(_app: Starlette) -> AsyncIterator[None]:
    """Eagerly load GPU models before accepting connections.

    Startup loads the shared ``EmbeddingModel`` with per-stage
    timing logs, registers daemon-owned shutdown hooks, and starts
    the heartbeat task.  Shutdown cancels the heartbeat, closes
    all project stores, releases GPU memory, and unlinks
    ``service.json``.

    Args:
        _app: The Starlette application instance (unused but
            required by the lifespan protocol).

    Yields:
        Control to the running application.
    """
    global _start_time, _shutdown_recorded, _SERVICE_TOKEN
    _start_time = time.monotonic()
    _shutdown_recorded = False
    # Generate the per-process identity token before the first
    # heartbeat tick fires (which would otherwise persist an empty
    # token into service.json). The token round-trips through
    # /health for CLI-side identity verification (gh #124/#125).
    _SERVICE_TOKEN = uuid.uuid4().hex

    t_total = time.perf_counter()

    # HF cache status
    from .config import EnvVar

    hf_home = os.environ.get(EnvVar.HF_HOME, "~/.cache/huggingface")
    logger.info("HF cache: %s", hf_home)

    # Wire watcher lifecycle into registry so close_project() stops watchers
    _registry._on_close_project = _stop_watcher

    # Load models (raises RuntimeError if no CUDA via _check_rag_deps)
    t0 = time.perf_counter()
    await _run_in_thread(_registry.load_model)
    logger.info("All models loaded in %.2fs", time.perf_counter() - t0)

    logger.info("Service startup complete in %.2fs", time.perf_counter() - t_total)

    # Daemon now owns end-of-life cleanup. The CLI parent created
    # service.json; the daemon's hooks remove it on exit so a stale
    # file never misleads ``service status`` (issue #113).
    _install_daemon_shutdown_hooks()
    _lifecycle_log("startup", pid=os.getpid())

    heartbeat_task = asyncio.create_task(_heartbeat_loop())
    # First heartbeat right away so a freshly started service is
    # immediately distinguishable from a stale CLI-only write.
    try:
        await asyncio.to_thread(_heartbeat_tick_sync)
    except Exception:
        logger.warning(
            "service.lifecycle event=heartbeat_initial_failed",
            exc_info=True,
        )

    # Start the MCP session manager.  Starlette's Mount does NOT
    # propagate lifespan to sub-apps, so the streamable_http_app's
    # own lifespan never fires.  Running it here ensures the session
    # manager's task group is active before the first /mcp request.
    async with mcp.session_manager.run():
        try:
            yield
        finally:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await heartbeat_task
            # Cancel watchers BEFORE closing stores to prevent
            # incremental_index() running against a closed store.
            _stop_all_watchers()
            _registry.close_all()
            logger.info("Service shutdown complete")
            _record_shutdown("clean")


# -- health endpoint --------------------------------------------------------


async def health_handler(_request: Request) -> object:
    """Return service health as JSON.

    Args:
        _request: The incoming Starlette request.

    Returns:
        A ``JSONResponse`` with status, CUDA availability,
        model state, connected projects, and uptime.
    """
    from starlette.responses import JSONResponse

    try:
        import torch

        cuda = torch.cuda.is_available()
    except ImportError:
        cuda = False

    reg_health = _registry.health()
    uptime = time.monotonic() - _start_time if _start_time > 0 else 0.0

    if reg_health["model_loaded"]:
        status = "ready"
    elif _start_time > 0:
        status = "degraded"
    else:
        status = "error"

    return JSONResponse(
        {
            "status": status,
            "cuda": cuda,
            "models_loaded": reg_health["model_loaded"],
            "project_count": reg_health["project_count"],
            "uptime_s": round(uptime, 2),
            "backend_capabilities": backend_capabilities_dict(),
            # Per-process identity token. Mirrors the value written
            # to service.json. The CLI compares the two to detect
            # PID-reuse and unrelated-HTTP-server-on-port collisions
            # (gh #124, #125).
            "service_token": _SERVICE_TOKEN,
        },
    )


# -- watcher -----------------------------------------------------------------


def _ensure_watcher(root: Path) -> None:
    """Launch a filesystem watcher for *root* as a background asyncio task.

    Safe to call repeatedly — starts at most one watcher per root.
    Uses a double-check lock pattern to prevent duplicate watcher
    creation when multiple tool handlers finish near-simultaneously.

    Must be called from the async event loop thread (not from a
    worker thread).

    Args:
        root: Project root directory to watch.
    """
    root = root.resolve()
    if root in _watcher_tasks:
        return
    # Resolve the project slot OUTSIDE the lock — peek_project() has
    # its own per-root locking and can take 50-200ms on cold start.
    # Holding _watcher_lock during that would block the event loop.
    slot = _registry.peek_project(root)
    with _watcher_lock:
        if root in _watcher_tasks:
            return
        if _registry._shutting_down:
            return

        from .watcher import watch_and_reindex

        stop_event = asyncio.Event()
        vault_dir = root / ".vault"
        task = asyncio.create_task(
            watch_and_reindex(
                root_dir=root,
                vault_dir=vault_dir,
                vault_indexer=slot.vault_indexer,
                code_indexer=slot.code_indexer,
                stop_event=stop_event,
                graph_cache=slot.graph_cache,
            ),
        )
        _watcher_tasks[root] = task
        _watcher_stops[root] = stop_event
        logger.info("Filesystem watcher started for %s", root)


def _stop_watcher(root: Path) -> None:
    """Stop and remove the watcher for *root*.

    Args:
        root: Project root directory (must be resolved).
    """
    root = root.resolve()
    with _watcher_lock:
        stop_event = _watcher_stops.pop(root, None)
        task = _watcher_tasks.pop(root, None)
    if stop_event is not None:
        stop_event.set()
    if task is not None and not task.done():
        task.cancel()
    if task is not None:
        logger.info("Filesystem watcher stopped for %s", root)


def _stop_all_watchers() -> None:
    """Stop all running watchers."""
    with _watcher_lock:
        roots = list(_watcher_tasks.keys())
    for root in roots:
        _stop_watcher(root)


# -- Pydantic models --------------------------------------------------------


class SearchResultItem(BaseModel):
    """Pydantic mirror of SearchResult for MCP serialization.

    Attributes:
        id: Unique document or chunk identifier (relative path
            without extension for vault, blake2b hash for code).
        path: File path relative to the workspace root.
        title: Human-readable document or chunk title.
        score: Relevance score (0.0-1.0 after normalization).
        snippet: Text excerpt from the matched document or
            code chunk.
        source: Origin collection, either ``"vault"`` or
            ``"codebase"``.
        doc_type: Vault document type (e.g., ``"adr"``,
            ``"plan"``). Empty for codebase results.
        feature: Feature tag from vault metadata. Empty for
            codebase results.
        date: ISO date string from vault metadata. Empty for
            codebase results.
        language: Programming language (e.g., ``"python"``).
            Empty for vault results.
        line_start: Starting line number in the source file.
            None for vault results.
        line_end: Ending line number in the source file.
            None for vault results.
        node_type: AST node type (e.g.,
            ``"function_definition"``). None for vault results.
        function_name: Function or method name extracted by
            tree-sitter. None if not applicable.
        class_name: Class or struct name extracted by
            tree-sitter. None if not applicable.
    """

    model_config = {"from_attributes": True}

    id: str
    path: str
    title: str
    score: float
    snippet: str
    source: str
    doc_type: str = ""
    feature: str = ""
    date: str = ""
    language: str = ""
    line_start: int | None = None
    line_end: int | None = None
    node_type: str | None = None
    function_name: str | None = None
    class_name: str | None = None


class SearchResponse(BaseModel):
    """Response envelope for search tool results.

    Attributes:
        results: Ranked list of search result items, ordered
            by descending relevance score.
        summary: Human-readable summary of the search outcome.
        backend_capabilities: Concurrency capabilities for the
            active local vector backend.
    """

    results: list[SearchResultItem] = Field(
        description="List of ranked search results",
    )
    summary: str = Field(
        description="Human-readable summary of findings",
    )
    backend_capabilities: BackendCapabilities = Field(
        default_factory=BackendCapabilities,
        description="Backend concurrency capabilities for agent orchestration",
    )


class IndexStatus(BaseModel):
    """Current state of the RAG index and GPU hardware.

    Attributes:
        vault_count: Number of indexed vault documents.
        code_count: Number of indexed codebase chunks.
        storage_path: Absolute path to the Qdrant local
            database directory.
        target_dir: Workspace root directory being indexed.
        vram_gb: Total GPU VRAM in gigabytes.
        backend_capabilities: Concurrency capabilities for the
            active local vector backend.
    """

    vault_count: int = Field(
        description="Number of indexed vault documents",
    )
    code_count: int = Field(
        description="Number of indexed codebase chunks",
    )
    storage_path: str = Field(
        description="Path to the vector database",
    )
    target_dir: str = Field(
        description="Workspace root directory",
    )
    vram_gb: float = Field(
        default=0.0,
        description="Total GPU VRAM in GB",
    )
    backend_capabilities: BackendCapabilities = Field(
        default_factory=BackendCapabilities,
        description="Backend concurrency capabilities for agent orchestration",
    )


class IndexResponse(BaseModel):
    """Result summary from a reindex operation.

    Attributes:
        total: Total items in the index after the operation.
        added: Number of newly indexed items.
        updated: Number of re-indexed (modified) items.
        removed: Number of items removed from the index.
        duration_ms: Wall-clock time of the operation in
            milliseconds.
        files: Number of source files processed.
    """

    total: int = Field(
        description="Total items in index after operation",
    )
    added: int = Field(description="Newly indexed items")
    updated: int = Field(
        description="Re-indexed (modified) items",
    )
    removed: int = Field(description="Removed items")
    duration_ms: int = Field(
        description="Wall-clock time in milliseconds",
    )
    files: int = Field(
        default=0,
        description="Files processed",
    )


class HealthResponse(BaseModel):
    """Health check response for the service.

    Attributes:
        status: Service state — ``"ready"``, ``"degraded"``,
            or ``"error"``.
        cuda: Whether a CUDA GPU is available.
        models_loaded: Whether GPU models have been loaded.
        project_count: Number of connected projects.
        uptime_s: Seconds since service startup.
        backend_capabilities: Search concurrency and local storage
            process-model contract.
        service_token: Per-process identity token mirroring the
            value written into ``service.json``. The CLI compares
            the two to detect PID-reuse and
            unrelated-HTTP-server-on-port collisions.
    """

    status: str = Field(description="Service state")
    cuda: bool = Field(description="CUDA GPU available")
    models_loaded: bool = Field(description="GPU models loaded")
    project_count: int = Field(
        default=0,
        description="Number of connected projects",
    )
    uptime_s: float = Field(
        default=0.0,
        description="Seconds since startup",
    )
    backend_capabilities: BackendCapabilities = Field(
        default_factory=BackendCapabilities,
        description="Backend concurrency capabilities for agent orchestration",
    )
    service_token: str = Field(
        default="",
        description=(
            "Per-process identity token. Empty for pre-upgrade "
            "daemons; non-empty for daemons running this version. "
            "CLI matches against the value in service.json to "
            "detect PID-reuse / unrelated-server collisions."
        ),
    )


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


def _is_sensitive_path(rel_path: str) -> bool:
    """Check whether *rel_path* matches a sensitive file pattern.

    Uses forward-slash normalized paths for cross-platform consistency.
    Checks each path component against ``_SENSITIVE_DIRS`` and the
    filename against ``_SENSITIVE_PATTERNS``.

    Args:
        rel_path: File path relative to the workspace root.

    Returns:
        True if the path matches any sensitive pattern.
    """
    normalised = rel_path.replace("\\", "/")
    parts = normalised.split("/")
    for part in parts[:-1]:
        if part in _SENSITIVE_DIRS:
            return True
    filename = parts[-1]
    return any(fnmatch.fnmatch(filename, pat) for pat in _SENSITIVE_PATTERNS)


def _clamp_top_k(top_k: int) -> int:
    """Clamp top_k to the range [1, 100].

    Args:
        top_k: Requested number of results.

    Returns:
        The clamped value, at least 1 and at most 100.
    """
    return max(1, min(top_k, 100))


def _validate_query(query: str) -> str:
    """Truncate query to _MAX_QUERY_LEN characters.

    Args:
        query: Raw user query string.

    Returns:
        The original query, or a truncated copy if it
        exceeded the maximum length.
    """
    if len(query) > _MAX_QUERY_LEN:
        logger.warning(
            "Query truncated from %d to %d characters",
            len(query),
            _MAX_QUERY_LEN,
        )
        return query[:_MAX_QUERY_LEN]
    return query


def _resolve_root(project_root: str | None) -> Path:
    """Resolve a project root path from an optional string.

    In HTTP service mode, ``project_root`` is required — the
    multi-tenant daemon has no default project.  In stdio mode,
    falls back to ``VAULTSPEC_RAG_ROOT`` env var or cwd.

    Args:
        project_root: Explicit project root path, or ``None``
            to use the default (stdio only).

    Returns:
        Resolved ``Path`` for the project root.

    Raises:
        ValueError: If the resolved path has no ``.vault/``
            subdirectory, or if ``project_root`` is omitted
            in HTTP mode.
    """
    if project_root is not None:
        if not project_root.strip():
            msg = "project_root must not be empty"
            raise ValueError(msg)
        return _validate_vault_root(Path(project_root).resolve())
    return _default_root()


# -- Tools -------------------------------------------------------------------


@mcp.tool()
async def search_vault(
    query: str,
    top_k: int = 5,
    doc_type: str | None = None,
    feature: str | None = None,
    date: str | None = None,
    tag: str | None = None,
    project_root: str | None = None,
) -> SearchResponse | dict[str, Any]:
    """Search the documentation vault for relevant ADRs, plans, and research.

    Args:
        query: Natural language search string (supports
            type:adr, feature:name, etc. as inline tokens).
        top_k: Number of results to return.
        doc_type: Optional vault doc-type filter (e.g. ``'adr'``,
            ``'plan'``). Equivalent to the ``type:`` query token.
        feature: Optional feature-tag filter (kebab-case).
        date: Optional exact ISO-date filter.
        tag: Optional free-form tag filter (matches against the
            ``tags`` payload array).
        project_root: Optional project root path. Defaults to
            ``VAULTSPEC_RAG_ROOT`` env var or cwd (stdio only).
            Required in HTTP service mode.

    Returns:
        SearchResponse with ranked vault results and a
        human-readable summary. Same-project searches are serialized
        inside the service because the local Qdrant backend is not
        safe for parallel access through the same project slot.

    Raises:
        RuntimeError: If RAG components fail to initialize
            (e.g., no CUDA GPU available).
    """
    top_k = _clamp_top_k(top_k)
    query = _validate_query(query)
    root = _resolve_root(project_root)

    def _run() -> SearchResponse | dict[str, Any]:
        try:
            with _registry.lease(root) as slot:
                logger.info("Searching vault for: %s", query)
                results = slot.searcher.search_vault(
                    query,
                    top_k=top_k,
                    doc_type=doc_type,
                    feature=feature,
                    date=date,
                    tag=tag,
                )
                items = [
                    SearchResultItem.model_validate(r, from_attributes=True)
                    for r in results
                ]
                return SearchResponse(
                    results=items,
                    summary=f"Found {len(results)} relevant documents in the vault.",
                )
        except RegistryFullError as exc:
            return _registry_full_error_dict(exc)
        except VaultStoreLockedError as exc:
            return _local_store_locked_error_dict(exc)

    result = await _run_in_thread(_run)
    if isinstance(result, SearchResponse):
        _ensure_watcher(root)
    return result


@mcp.tool()
async def search_codebase(
    query: str,
    top_k: int = 5,
    language: str | None = None,
    path: str | None = None,
    node_type: str | None = None,
    function_name: str | None = None,
    class_name: str | None = None,
    include_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    dedup_locales: bool = False,
    prefer: str | None = None,
    project_root: str | None = None,
) -> SearchResponse | dict[str, Any]:
    """Search the source codebase for relevant functions, classes, or logic.

    Args:
        query: Natural language search string or code snippet.
        top_k: Number of chunks to return.
        language: Optional language filter (e.g.,
            ``"python"``, ``"rust"``).
        path: Optional exact-match path filter against the
            project-relative file path payload.
        node_type: Optional AST node type filter (e.g.,
            ``"function_definition"``).
        function_name: Optional function/method name filter.
        class_name: Optional class/struct name filter.
        include_paths: Optional fnmatch glob patterns kept by a
            post-query Python filter (e.g.
            ``["src/foo/**"]``). Operates against the
            POSIX-normalised project-relative path. Useful for
            restricting results to a subtree.
        exclude_paths: Optional fnmatch glob patterns dropped by a
            post-query Python filter (e.g.
            ``["locales/*.yml", "tests/**"]``). Useful for
            pruning crowding paths.
        dedup_locales: When True, collapse near-tie locale variants
            (e.g. ``locales/{en,es}.yml``) into a single canonical
            result after rerank. Opt-in; defaults to False.
        prefer: Optional ``"prod" | "tests" | "docs"``. Applies a
            small +/- score nudge to the matching category after
            rerank. Opt-in; defaults to None (no nudge).
        project_root: Optional project root path. Defaults to
            ``VAULTSPEC_RAG_ROOT`` env var or cwd (stdio only).
            Required in HTTP service mode.

    Returns:
        SearchResponse with ranked codebase results and a
        human-readable summary. Same-project searches are serialized
        inside the service because the local Qdrant backend is not
        safe for parallel access through the same project slot.

    Raises:
        RuntimeError: If RAG components fail to initialize
            (e.g., no CUDA GPU available).
    """
    top_k = _clamp_top_k(top_k)
    query = _validate_query(query)
    root = _resolve_root(project_root)

    def _run() -> SearchResponse | dict[str, Any]:
        try:
            with _registry.lease(root) as slot:
                logger.info(
                    "Searching codebase for: %s (lang=%s)",
                    query,
                    language,
                )
                results = slot.searcher.search_codebase(
                    query,
                    top_k=top_k,
                    language=language,
                    path=path,
                    node_type=node_type,
                    function_name=function_name,
                    class_name=class_name,
                    include_paths=include_paths,
                    exclude_paths=exclude_paths,
                    dedup_locales=dedup_locales,
                    prefer=prefer,
                )
                items = [
                    SearchResultItem.model_validate(r, from_attributes=True)
                    for r in results
                ]
                return SearchResponse(
                    results=items,
                    summary=f"Found {len(results)} relevant code blocks.",
                )
        except RegistryFullError as exc:
            return _registry_full_error_dict(exc)
        except VaultStoreLockedError as exc:
            return _local_store_locked_error_dict(exc)

    result = await _run_in_thread(_run)
    if isinstance(result, SearchResponse):
        _ensure_watcher(root)
    return result


@mcp.tool()
async def get_index_status(
    project_root: str | None = None,
) -> IndexStatus | dict[str, Any]:
    """Return the current status of the RAG index and GPU hardware.

    Args:
        project_root: Optional project root path. Defaults to
            ``VAULTSPEC_RAG_ROOT`` env var or cwd (stdio only).
            Required in HTTP service mode.

    Returns:
        IndexStatus with document counts, storage path, and
        GPU device information.

    Raises:
        RuntimeError: If RAG components fail to initialize
            (e.g., no CUDA GPU available).
    """
    root = _resolve_root(project_root)

    def _run() -> IndexStatus | dict[str, Any]:
        try:
            with _registry.lease(root) as slot:
                try:
                    import torch

                    vram_gb = (
                        torch.cuda.get_device_properties(0).total_memory / 1e9
                        if torch.cuda.is_available()
                        else 0.0
                    )
                except ImportError:
                    vram_gb = 0.0
                return IndexStatus(
                    vault_count=slot.store.count(),
                    code_count=slot.store.count_code(),
                    storage_path=str(slot.store.db_path),
                    target_dir=str(root),
                    vram_gb=round(vram_gb, 2),
                )
        except RegistryFullError as exc:
            return _registry_full_error_dict(exc)

    return await _run_in_thread(_run)


@mcp.tool()
async def get_code_file(
    path: str,
    project_root: str | None = None,
) -> str:
    """Retrieve the full content of a source file by path.

    Args:
        path: Path to the file relative to codebase root.
        project_root: Optional project root path. Defaults to
            ``VAULTSPEC_RAG_ROOT`` env var or cwd (stdio only).
            Required in HTTP service mode.

    Returns:
        The UTF-8 text content of the file.

    Raises:
        ValueError: If the path escapes the workspace root or
            the file exceeds 10 MB.
        FileNotFoundError: If the file does not exist.
        RuntimeError: If RAG components fail to initialize.
    """
    root = _resolve_root(project_root)
    max_read_size = 10 * 1024 * 1024  # 10 MB

    def _run() -> str:
        root_resolved = root.resolve()
        full_path = (root_resolved / path).resolve()
        if not full_path.is_relative_to(root_resolved):
            raise ValueError(f"path '{path}' is outside the workspace")
        if _is_sensitive_path(path):
            raise ValueError("access denied")
        if not full_path.exists():
            raise FileNotFoundError(f"File '{path}' not found")
        if full_path.stat().st_size > max_read_size:
            raise ValueError(
                f"File '{path}' exceeds maximum read size of 10 MB",
            )
        return full_path.read_text(encoding="utf-8")

    return await _run_in_thread(_run)


@mcp.tool()
async def reindex_vault(
    clean: bool = False,
    project_root: str | None = None,
) -> IndexResponse | dict[str, Any]:
    """Re-index vault documentation (incremental by default).

    Invalidates the VaultGraph cache after indexing so the next
    search picks up updated document relationships.

    Args:
        clean: If True, run a full re-index that re-encodes every
            vault document and purges any rows whose IDs are absent
            from the new corpus. The rebuild is failure-safe — the
            old collection is preserved until the new slices have
            been streamed in place — so an interrupted clean run
            never leaves the store empty (#68 Track B).
        project_root: Optional project root path. Defaults to
            ``VAULTSPEC_RAG_ROOT`` env var or cwd (stdio only).
            Required in HTTP service mode.

    Returns:
        IndexResponse with counts of added, updated, and
        removed documents plus timing. ``removed`` reflects the
        number of stale rows purged after the streaming rebuild
        when ``clean=True``.

    Raises:
        RuntimeError: If RAG components fail to initialize
            (e.g., no CUDA GPU available).
    """
    root = _resolve_root(project_root)

    def _run() -> IndexResponse | dict[str, Any]:
        try:
            with _registry.lease(root) as slot:
                mode = "full" if clean else "incremental"
                logger.info("Starting %s vault re-index...", mode)
                if clean:
                    result = slot.vault_indexer.full_index(
                        clean=True, reporter=NullProgressReporter()
                    )
                else:
                    result = slot.vault_indexer.incremental_index(
                        reporter=NullProgressReporter()
                    )
                slot.graph_cache.invalidate()
                return IndexResponse(
                    total=result.total,
                    added=result.added,
                    updated=result.updated,
                    removed=result.removed,
                    duration_ms=result.duration_ms,
                    files=result.files,
                )
        except RegistryFullError as exc:
            return _registry_full_error_dict(exc)

    result = await _run_in_thread(_run)
    if isinstance(result, IndexResponse):
        _ensure_watcher(root)
    return result


@mcp.tool()
async def reindex_codebase(
    clean: bool = False,
    project_root: str | None = None,
) -> IndexResponse | dict[str, Any]:
    """Re-index the source codebase (incremental by default).

    Args:
        clean: If True, run a full re-index that re-encodes every
            source chunk and purges any chunk IDs absent from the
            new scan. The rebuild is failure-safe — the old chunks
            stay live until the new slices have streamed in place —
            so an interrupted clean run never leaves the codebase
            collection empty (#68 Track B).
        project_root: Optional project root path. Defaults to
            ``VAULTSPEC_RAG_ROOT`` env var or cwd (stdio only).
            Required in HTTP service mode.

    Returns:
        IndexResponse with counts of added, updated, and
        removed chunks plus timing. ``removed`` reflects the
        post-stream stale-purge count when ``clean=True``.

    Raises:
        RuntimeError: If RAG components fail to initialize
            (e.g., no CUDA GPU available).
    """
    root = _resolve_root(project_root)

    def _run() -> IndexResponse | dict[str, Any]:
        try:
            with _registry.lease(root) as slot:
                mode = "full" if clean else "incremental"
                logger.info("Starting %s codebase re-index...", mode)
                if clean:
                    result = slot.code_indexer.full_index(
                        clean=True, reporter=NullProgressReporter()
                    )
                else:
                    result = slot.code_indexer.incremental_index(
                        reporter=NullProgressReporter()
                    )
                return IndexResponse(
                    total=result.total,
                    added=result.added,
                    updated=result.updated,
                    removed=result.removed,
                    duration_ms=result.duration_ms,
                    files=result.files,
                )
        except RegistryFullError as exc:
            return _registry_full_error_dict(exc)

    result = await _run_in_thread(_run)
    if isinstance(result, IndexResponse):
        _ensure_watcher(root)
    return result


# -- Admin tools -------------------------------------------------------------


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

        snapshot = _registry.snapshot()
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
            "max_projects": _registry.max_projects,
            "idle_ttl_seconds": _registry.idle_ttl_seconds,
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
        evicted, reason = _registry.try_evict(target)
        return {"evicted": evicted, "reason": reason}

    return await _run_in_thread(_run)


# -- Resources ---------------------------------------------------------------


@mcp.resource("vault://{doc_id}")
async def get_vault_document(doc_id: str) -> str:
    """Retrieve the full content of a vault document by its stem ID.

    Only available in stdio mode (single-project).  In HTTP mode,
    use the ``search_vault`` tool with an explicit ``project_root``.

    Args:
        doc_id: Relative path without extension (e.g.,
            ``"adr/overview"``).

    Returns:
        The full text content of the vault document.

    Raises:
        FileNotFoundError: If no document matches the given ID.
        ValueError: If called in HTTP service mode.
        RuntimeError: If RAG components fail to initialize.
    """
    if _http_mode:
        msg = "Resource vault:// is only available in stdio mode (single-project)."
        raise ValueError(msg)
    root = _default_root()

    def _run() -> str:
        with _registry.lease(root) as slot:
            doc = slot.store.get_by_id(doc_id)
            if not doc:
                raise FileNotFoundError(f"Document '{doc_id}' not found")
            return doc.get("content", "")

    return await _run_in_thread(_run)


# -- Prompts -----------------------------------------------------------------


@mcp.prompt()
def analyze_feature(feature_name: str) -> str:
    """Create a prompt to analyze a feature across docs and code.

    Args:
        feature_name: The feature tag to search for (e.g.,
            ``"pipeline"``, ``"scheduler"``).

    Returns:
        A multi-step instruction string guiding the LLM to
        search vault ADRs, find codebase implementation, and
        summarize alignment.
    """
    root_note = (
        "\n\nNote: In HTTP service mode, you must include "
        "`project_root` in every tool call."
        if _http_mode
        else ""
    )
    return (
        f"Please analyze the implementation and documentation "
        f"for the '{feature_name}' feature.\n\n"
        f"1. Use `search_vault` with 'feature:{feature_name}' "
        f"to find related ADRs and plans.\n"
        f"2. Use `search_codebase` to find the actual "
        f"implementation logic.\n"
        f"3. Summarize how the implementation aligns with "
        f"the original design specs."
        f"{root_note}"
    )


# -- entry point -------------------------------------------------------------


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

    global _http_mode
    _http_mode = port is not None

    if port is not None:
        import uvicorn
        from starlette.applications import Starlette
        from starlette.routing import Mount, Route

        from .config import get_config
        from .logging_config import (
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
            _resolve_log_path(),
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
        # rewrite the request path before routing instead — an ASGI
        # wrapper that promotes "/mcp" to "/mcp/" in-process. Both
        # URLs now land directly on the inner app, with no redirect.
        app = Starlette(
            routes=[
                Mount("/mcp", app=mcp_http_app),
                Route("/health", health_handler),
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
            _registry.close_all()
    else:
        # Eager model load for stdio — matches HTTP mode's service_lifespan.
        # Without this, the first tool call hits "EmbeddingModel not loaded"
        # because ServiceRegistry.lease()/peek_project() require a loaded model.
        _registry.load_model()
        _registry._on_close_project = _stop_watcher
        try:
            mcp.run(transport="stdio")
        finally:
            _stop_all_watchers()
            _registry.close_all()


if __name__ == "__main__":
    main()
