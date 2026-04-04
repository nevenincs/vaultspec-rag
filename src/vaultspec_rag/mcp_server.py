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
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from anyio.to_thread import run_sync as _run_in_thread
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from .service import ServiceRegistry

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.applications import Starlette
    from starlette.requests import Request

logger = logging.getLogger(__name__)

mcp = FastMCP("VaultSpec Search", stateless_http=True)

_registry = ServiceRegistry()
_watcher_tasks: dict[Path, asyncio.Task[None]] = {}
_watcher_stops: dict[Path, asyncio.Event] = {}
_watcher_lock = threading.Lock()
_start_time: float = 0.0


def _default_root() -> Path:
    """Resolve the default project root from env or cwd.

    Returns:
        Resolved ``Path`` from ``VAULTSPEC_ROOT`` env var, falling
        back to the current working directory.
    """
    root_env = os.environ.get("VAULTSPEC_ROOT")
    return Path(root_env).resolve() if root_env else Path.cwd().resolve()


# -- lifespan ---------------------------------------------------------------


@asynccontextmanager
async def service_lifespan(_app: Starlette) -> AsyncIterator[None]:
    """Eagerly load GPU models before accepting connections.

    Startup loads the shared ``EmbeddingModel`` with per-stage
    timing logs.  Shutdown closes all project stores and releases
    GPU memory.

    Args:
        _app: The Starlette application instance (unused but
            required by the lifespan protocol).

    Yields:
        Control to the running application.
    """
    global _start_time
    _start_time = time.monotonic()

    t_total = time.perf_counter()

    # HF cache status
    hf_home = os.environ.get("HF_HOME", "~/.cache/huggingface")
    logger.info("HF cache: %s", hf_home)

    # Load models (raises RuntimeError if no CUDA via _check_rag_deps)
    t0 = time.perf_counter()
    await _run_in_thread(_registry.load_model)
    logger.info("All models loaded in %.2fs", time.perf_counter() - t0)

    logger.info("Service startup complete in %.2fs", time.perf_counter() - t_total)

    try:
        yield
    finally:
        # Cancel watchers BEFORE closing stores to prevent
        # incremental_index() running against a closed store.
        _stop_all_watchers()
        _registry.close_all()
        logger.info("Service shutdown complete")


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
            "projects": reg_health["projects"],
            "uptime_s": round(uptime, 2),
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
    with _watcher_lock:
        if root in _watcher_tasks:
            return

        slot = _registry.get_project(root)

        from .watcher import watch_and_reindex

        stop_event = asyncio.Event()
        vault_dir = root / ".vault"
        task = asyncio.ensure_future(
            watch_and_reindex(
                root_dir=root,
                vault_dir=vault_dir,
                vault_indexer=slot.vault_indexer,
                code_indexer=slot.code_indexer,
                stop_event=stop_event,
                graph_cache=slot.graph_cache,
                gpu_lock=_registry.gpu_lock,
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
    """

    results: list[SearchResultItem] = Field(
        description="List of ranked search results",
    )
    summary: str = Field(
        description="Human-readable summary of findings",
    )


class IndexStatus(BaseModel):
    """Current state of the RAG index and GPU hardware.

    Attributes:
        vault_count: Number of indexed vault documents.
        code_count: Number of indexed codebase chunks.
        storage_path: Absolute path to the Qdrant local
            database directory.
        target_dir: Workspace root directory being indexed.
        gpu_name: CUDA GPU device name (e.g.,
            ``"NVIDIA GeForce RTX 4080"``).
        vram_gb: Total GPU VRAM in gigabytes.
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
    gpu_name: str = Field(
        default="unknown",
        description="GPU device name",
    )
    vram_gb: float = Field(
        default=0.0,
        description="Total GPU VRAM in GB",
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
        status: Service state — ``"ready"``, ``"loading"``,
            or ``"error"``.
        cuda: Whether a CUDA GPU is available.
        models_loaded: Whether GPU models have been loaded.
        projects: List of connected project root paths.
        uptime_s: Seconds since service startup.
    """

    status: str = Field(description="Service state")
    cuda: bool = Field(description="CUDA GPU available")
    models_loaded: bool = Field(description="GPU models loaded")
    projects: list[str] = Field(
        default_factory=list,
        description="Connected project roots",
    )
    uptime_s: float = Field(
        default=0.0,
        description="Seconds since startup",
    )


_MAX_QUERY_LEN = 10_000  # characters; prevents accidental OOM on huge queries


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

    Args:
        project_root: Explicit project root path, or ``None``
            to use the default.

    Returns:
        Resolved ``Path`` for the project root.
    """
    if project_root:
        return Path(project_root).resolve()
    return _default_root()


# -- Tools -------------------------------------------------------------------


@mcp.tool()
async def search_vault(
    query: str,
    top_k: int = 5,
    project_root: str | None = None,
) -> SearchResponse:
    """Search the documentation vault for relevant ADRs, plans, and research.

    Args:
        query: Natural language search string (supports
            type:adr, feature:name, etc.).
        top_k: Number of results to return.
        project_root: Optional project root path. Defaults to
            ``VAULTSPEC_ROOT`` env var or cwd.

    Returns:
        SearchResponse with ranked vault results and a
        human-readable summary.

    Raises:
        RuntimeError: If RAG components fail to initialize
            (e.g., no CUDA GPU available).
    """
    top_k = _clamp_top_k(top_k)
    query = _validate_query(query)
    root = _resolve_root(project_root)

    def _run() -> SearchResponse:
        slot = _registry.get_project(root)
        logger.info("Searching vault for: %s", query)
        results = slot.searcher.search_vault(query, top_k=top_k)
        items = [
            SearchResultItem.model_validate(r, from_attributes=True) for r in results
        ]
        return SearchResponse(
            results=items,
            summary=f"Found {len(results)} relevant documents in the vault.",
        )

    result = await _run_in_thread(_run)
    _ensure_watcher(root)
    return result


@mcp.tool()
async def search_codebase(
    query: str,
    top_k: int = 5,
    language: str | None = None,
    node_type: str | None = None,
    function_name: str | None = None,
    class_name: str | None = None,
    project_root: str | None = None,
) -> SearchResponse:
    """Search the source codebase for relevant functions, classes, or logic.

    Args:
        query: Natural language search string or code snippet.
        top_k: Number of chunks to return.
        language: Optional language filter (e.g.,
            ``"python"``, ``"rust"``).
        node_type: Optional AST node type filter (e.g.,
            ``"function_definition"``).
        function_name: Optional function/method name filter.
        class_name: Optional class/struct name filter.
        project_root: Optional project root path. Defaults to
            ``VAULTSPEC_ROOT`` env var or cwd.

    Returns:
        SearchResponse with ranked codebase results and a
        human-readable summary.

    Raises:
        RuntimeError: If RAG components fail to initialize
            (e.g., no CUDA GPU available).
    """
    top_k = _clamp_top_k(top_k)
    query = _validate_query(query)
    root = _resolve_root(project_root)

    def _run() -> SearchResponse:
        slot = _registry.get_project(root)
        logger.info("Searching codebase for: %s (lang=%s)", query, language)
        results = slot.searcher.search_codebase(
            query,
            top_k=top_k,
            language=language,
            node_type=node_type,
            function_name=function_name,
            class_name=class_name,
        )
        items = [
            SearchResultItem.model_validate(r, from_attributes=True) for r in results
        ]
        return SearchResponse(
            results=items,
            summary=f"Found {len(results)} relevant code blocks.",
        )

    result = await _run_in_thread(_run)
    _ensure_watcher(root)
    return result


@mcp.tool()
async def search_all(
    query: str,
    top_k: int = 5,
    project_root: str | None = None,
) -> SearchResponse:
    """Search both documentation and codebase for comprehensive context.

    Args:
        query: Natural language search string.
        top_k: Number of results to return from each source.
        project_root: Optional project root path. Defaults to
            ``VAULTSPEC_ROOT`` env var or cwd.

    Returns:
        SearchResponse with merged vault and codebase results,
        ranked by normalized relevance score.

    Raises:
        RuntimeError: If RAG components fail to initialize
            (e.g., no CUDA GPU available).
    """
    top_k = _clamp_top_k(top_k)
    query = _validate_query(query)
    root = _resolve_root(project_root)

    def _run() -> SearchResponse:
        slot = _registry.get_project(root)
        logger.info("Unified search for: %s", query)
        results = slot.searcher.search_all(query, top_k=top_k)
        items = [
            SearchResultItem.model_validate(r, from_attributes=True) for r in results
        ]
        return SearchResponse(
            results=items,
            summary=f"Found {len(results)} mixed results from vault and codebase.",
        )

    result = await _run_in_thread(_run)
    _ensure_watcher(root)
    return result


@mcp.tool()
async def get_index_status(
    project_root: str | None = None,
) -> IndexStatus:
    """Return the current status of the RAG index and GPU hardware.

    Args:
        project_root: Optional project root path. Defaults to
            ``VAULTSPEC_ROOT`` env var or cwd.

    Returns:
        IndexStatus with document counts, storage path, and
        GPU device information.

    Raises:
        RuntimeError: If RAG components fail to initialize
            (e.g., no CUDA GPU available).
    """
    root = _resolve_root(project_root)

    def _run() -> IndexStatus:
        slot = _registry.get_project(root)
        try:
            import torch

            gpu_name = (
                torch.cuda.get_device_name(0) if torch.cuda.is_available() else "no GPU"
            )
            vram_gb = (
                torch.cuda.get_device_properties(0).total_memory / 1e9
                if torch.cuda.is_available()
                else 0.0
            )
        except ImportError:
            gpu_name = "unknown"
            vram_gb = 0.0
        return IndexStatus(
            vault_count=slot.store.count(),
            code_count=slot.store.count_code(),
            storage_path=str(slot.store.db_path),
            target_dir=str(root),
            gpu_name=gpu_name,
            vram_gb=round(vram_gb, 2),
        )

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
            ``VAULTSPEC_ROOT`` env var or cwd.

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
) -> IndexResponse:
    """Re-index vault documentation (incremental by default).

    Invalidates the VaultGraph cache after indexing so the next
    search picks up updated document relationships.

    Args:
        clean: If True, drop and recreate the vault collection
            before a full re-index.
        project_root: Optional project root path. Defaults to
            ``VAULTSPEC_ROOT`` env var or cwd.

    Returns:
        IndexResponse with counts of added, updated, and
        removed documents plus timing.

    Raises:
        RuntimeError: If RAG components fail to initialize
            (e.g., no CUDA GPU available).
    """
    root = _resolve_root(project_root)

    def _run() -> IndexResponse:
        slot = _registry.get_project(root)
        mode = "full" if clean else "incremental"
        logger.info("Starting %s vault re-index...", mode)
        with _registry.gpu_lock:
            if clean:
                result = slot.vault_indexer.full_index(clean=True)
            else:
                result = slot.vault_indexer.incremental_index()
        slot.graph_cache.invalidate()
        return IndexResponse(
            total=result.total,
            added=result.added,
            updated=result.updated,
            removed=result.removed,
            duration_ms=result.duration_ms,
            files=result.files,
        )

    result = await _run_in_thread(_run)
    _ensure_watcher(root)
    return result


@mcp.tool()
async def reindex_codebase(
    clean: bool = False,
    project_root: str | None = None,
) -> IndexResponse:
    """Re-index the source codebase (incremental by default).

    Args:
        clean: If True, drop and recreate the codebase
            collection before a full re-index.
        project_root: Optional project root path. Defaults to
            ``VAULTSPEC_ROOT`` env var or cwd.

    Returns:
        IndexResponse with counts of added, updated, and
        removed chunks plus timing.

    Raises:
        RuntimeError: If RAG components fail to initialize
            (e.g., no CUDA GPU available).
    """
    root = _resolve_root(project_root)

    def _run() -> IndexResponse:
        slot = _registry.get_project(root)
        mode = "full" if clean else "incremental"
        logger.info("Starting %s codebase re-index...", mode)
        with _registry.gpu_lock:
            if clean:
                result = slot.code_indexer.full_index(clean=True)
            else:
                result = slot.code_indexer.incremental_index()
        return IndexResponse(
            total=result.total,
            added=result.added,
            updated=result.updated,
            removed=result.removed,
            duration_ms=result.duration_ms,
            files=result.files,
        )

    result = await _run_in_thread(_run)
    _ensure_watcher(root)
    return result


# -- Resources ---------------------------------------------------------------


@mcp.resource("vault://{doc_id}")
async def get_vault_document(doc_id: str) -> str:
    """Retrieve the full content of a vault document by its stem ID.

    Args:
        doc_id: Relative path without extension (e.g.,
            ``"adr/overview"``).

    Returns:
        The full text content of the vault document.

    Raises:
        FileNotFoundError: If no document matches the given ID.
        RuntimeError: If RAG components fail to initialize.
    """
    root = _default_root()

    def _run() -> str:
        slot = _registry.get_project(root)
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
    return (
        f"Please analyze the implementation and documentation "
        f"for the '{feature_name}' feature.\n\n"
        f"1. Use `search_vault` with 'feature:{feature_name}' "
        f"to find related ADRs and plans.\n"
        f"2. Use `search_codebase` to find the actual "
        f"implementation logic.\n"
        f"3. Summarize how the implementation aligns with "
        f"the original design specs."
    )


# -- entry point -------------------------------------------------------------


def main(port: int | None = None) -> None:
    """Start the MCP server on stdio or HTTP transport.

    In HTTP mode, builds a Starlette app that mounts the MCP
    streamable-HTTP transport at ``/mcp`` and a raw ``/health``
    endpoint, with ``service_lifespan`` for eager model loading.

    In stdio mode, delegates to ``mcp.run(transport="stdio")``
    for Claude Desktop compatibility (no lifespan).

    Args:
        port: If provided, run on streamable-http at
            127.0.0.1:<port>. Otherwise use stdio transport.
    """
    if port is not None:
        import uvicorn
        from starlette.applications import Starlette
        from starlette.routing import Mount, Route

        app = Starlette(
            routes=[
                Mount("/mcp", app=mcp.streamable_http_app()),
                Route("/health", health_handler),
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
            )
        finally:
            _registry.close_all()
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    import argparse

    _parser = argparse.ArgumentParser(description="VaultSpec RAG MCP server")
    _parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="HTTP port (default: stdio transport)",
    )
    _args = _parser.parse_args()
    main(port=_args.port)
