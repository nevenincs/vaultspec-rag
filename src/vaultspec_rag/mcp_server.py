"""MCP server for VaultSpec RAG search and retrieval.

Exposes tools for searching vault and codebase, resources for
retrieving full contents, and prompts for common RAG tasks.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import anyio
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from .embeddings import EmbeddingModel
from .indexer import CodebaseIndexer, VaultIndexer
from .search import VaultSearcher
from .store import VaultStore

logger = logging.getLogger(__name__)

mcp = FastMCP("VaultSpec Search")


@dataclass
class RagComponents:
    """Lazily-initialized RAG component bundle.

    Attributes:
        store: Qdrant-backed vector store for vault and
            codebase collections.
        model: GPU-accelerated embedding model (Qwen3 dense +
            SPLADE sparse + optional CrossEncoder reranker).
        searcher: Hybrid search engine over vault and codebase
            collections.
        vault_indexer: Incremental indexer for .vault/
            documentation files.
        code_indexer: Incremental indexer for source code files
            using tree-sitter AST chunking.
        root_dir: Workspace root directory containing .vault/
            and source code.
    """

    store: VaultStore
    model: EmbeddingModel
    searcher: VaultSearcher
    vault_indexer: VaultIndexer
    code_indexer: CodebaseIndexer
    root_dir: Path


_comp: RagComponents | None = None
_comp_lock = threading.Lock()
_comp_error: Exception | None = None
_gpu_sem = asyncio.Semaphore(1)
_watcher_stop = asyncio.Event()
_watcher_task: asyncio.Task[None] | None = None


def get_comp() -> RagComponents:
    """Return the initialized RAG components, creating them on first call.

    Thread-safe: uses a threading.Lock with double-check pattern to
    prevent concurrent initialization. Caches initialization failures
    to avoid retrying expensive GPU setup.

    Returns:
        The singleton RagComponents instance.

    Raises:
        RuntimeError: If a previous initialization attempt failed
            (the original exception is chained).
    """
    global _comp, _comp_error
    if _comp is not None:
        return _comp
    with _comp_lock:
        if _comp is not None:
            return _comp
        if _comp_error is not None:
            raise RuntimeError(
                f"RAG initialization previously failed: {_comp_error}",
            ) from _comp_error
        try:
            logger.info("Initializing VaultSpec RAG components...")
            root_env = os.environ.get("VAULTSPEC_ROOT")
            root_dir = Path(root_env) if root_env else Path.cwd()

            store = VaultStore(root_dir)
            model = EmbeddingModel()

            _comp = RagComponents(
                store=store,
                model=model,
                searcher=VaultSearcher(root_dir, model, store),
                vault_indexer=VaultIndexer(root_dir, model, store),
                code_indexer=CodebaseIndexer(root_dir, model, store),
                root_dir=root_dir,
            )
        except Exception as exc:
            _comp_error = exc
            raise
    return _comp


def _ensure_watcher() -> None:
    """Launch the filesystem watcher as a background asyncio task.

    Safe to call repeatedly — only starts once. Must be called from the
    async event loop thread (not from a worker thread).
    """
    global _watcher_task
    if _watcher_task is not None:
        return
    if _comp is None:
        return

    from .watcher import watch_and_reindex

    vault_dir = _comp.root_dir / ".vault"
    _watcher_task = asyncio.ensure_future(
        watch_and_reindex(
            root_dir=_comp.root_dir,
            vault_dir=vault_dir,
            vault_indexer=_comp.vault_indexer,
            code_indexer=_comp.code_indexer,
            gpu_sem=_gpu_sem,
            stop_event=_watcher_stop,
            searcher=_comp.searcher,
        ),
    )
    logger.info("Filesystem watcher started for %s", _comp.root_dir)


# Structured Output Models
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


# Tools
@mcp.tool()
async def search_vault(query: str, top_k: int = 5) -> SearchResponse:
    """Search the documentation vault for relevant ADRs, plans, and research.

    Args:
        query: Natural language search string (supports
            type:adr, feature:name, etc.).
        top_k: Number of results to return.

    Returns:
        SearchResponse with ranked vault results and a
        human-readable summary.

    Raises:
        RuntimeError: If RAG components fail to initialize
            (e.g., no CUDA GPU available).
    """
    top_k = _clamp_top_k(top_k)
    query = _validate_query(query)

    def _run() -> SearchResponse:
        comp = get_comp()
        logger.info("Searching vault for: %s", query)
        results = comp.searcher.search_vault(query, top_k=top_k)
        items = [
            SearchResultItem.model_validate(r, from_attributes=True) for r in results
        ]
        return SearchResponse(
            results=items,
            summary=f"Found {len(results)} relevant documents in the vault.",
        )

    async with _gpu_sem:
        result = await anyio.to_thread.run_sync(_run)
    _ensure_watcher()
    return result


@mcp.tool()
async def search_codebase(
    query: str,
    top_k: int = 5,
    language: str | None = None,
    node_type: str | None = None,
    function_name: str | None = None,
    class_name: str | None = None,
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

    Returns:
        SearchResponse with ranked codebase results and a
        human-readable summary.

    Raises:
        RuntimeError: If RAG components fail to initialize
            (e.g., no CUDA GPU available).
    """
    top_k = _clamp_top_k(top_k)
    query = _validate_query(query)

    def _run() -> SearchResponse:
        comp = get_comp()
        logger.info("Searching codebase for: %s (lang=%s)", query, language)
        results = comp.searcher.search_codebase(
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

    async with _gpu_sem:
        result = await anyio.to_thread.run_sync(_run)
    _ensure_watcher()
    return result


@mcp.tool()
async def search_all(query: str, top_k: int = 5) -> SearchResponse:
    """Search both documentation and codebase for comprehensive context.

    Args:
        query: Natural language search string.
        top_k: Number of results to return from each source.

    Returns:
        SearchResponse with merged vault and codebase results,
        ranked by normalized relevance score.

    Raises:
        RuntimeError: If RAG components fail to initialize
            (e.g., no CUDA GPU available).
    """
    top_k = _clamp_top_k(top_k)
    query = _validate_query(query)

    def _run() -> SearchResponse:
        comp = get_comp()
        logger.info("Unified search for: %s", query)
        results = comp.searcher.search_all(query, top_k=top_k)
        items = [
            SearchResultItem.model_validate(r, from_attributes=True) for r in results
        ]
        return SearchResponse(
            results=items,
            summary=f"Found {len(results)} mixed results from vault and codebase.",
        )

    async with _gpu_sem:
        result = await anyio.to_thread.run_sync(_run)
    _ensure_watcher()
    return result


@mcp.tool()
async def get_index_status() -> IndexStatus:
    """Return the current status of the RAG index and GPU hardware.

    Returns:
        IndexStatus with document counts, storage path, and
        GPU device information.

    Raises:
        RuntimeError: If RAG components fail to initialize
            (e.g., no CUDA GPU available).
    """

    def _run() -> IndexStatus:
        comp = get_comp()
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
            vault_count=comp.store.count(),
            code_count=comp.store.count_code(),
            storage_path=str(comp.store.db_path),
            target_dir=str(comp.root_dir),
            gpu_name=gpu_name,
            vram_gb=round(vram_gb, 2),
        )

    return await anyio.to_thread.run_sync(_run)


@mcp.tool()
async def get_code_file(path: str) -> str:
    """Retrieve the full content of a source file by path.

    Args:
        path: Path to the file relative to codebase root.

    Returns:
        The UTF-8 text content of the file.

    Raises:
        ValueError: If the path escapes the workspace root or
            the file exceeds 10 MB.
        FileNotFoundError: If the file does not exist.
        RuntimeError: If RAG components fail to initialize.
    """

    max_read_size = 10 * 1024 * 1024  # 10 MB

    def _run() -> str:
        comp = get_comp()
        root_resolved = comp.root_dir.resolve()
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

    return await anyio.to_thread.run_sync(_run)


@mcp.tool()
async def reindex_vault(clean: bool = False) -> IndexResponse:
    """Re-index vault documentation (incremental by default).

    Invalidates the VaultGraph cache after indexing so the next
    search picks up updated document relationships.

    Args:
        clean: If True, drop and recreate the vault collection
            before a full re-index.

    Returns:
        IndexResponse with counts of added, updated, and
        removed documents plus timing.

    Raises:
        RuntimeError: If RAG components fail to initialize
            (e.g., no CUDA GPU available).
    """

    def _run() -> IndexResponse:
        comp = get_comp()
        mode = "full" if clean else "incremental"
        logger.info("Starting %s vault re-index...", mode)
        if clean:
            result = comp.vault_indexer.full_index(clean=True)
        else:
            result = comp.vault_indexer.incremental_index()
        # Invalidate the graph cache so the next search_vault call rebuilds
        # from the fresh index rather than serving stale graph-boost scores.
        comp.searcher._graph_built_at = 0.0
        return IndexResponse(
            total=result.total,
            added=result.added,
            updated=result.updated,
            removed=result.removed,
            duration_ms=result.duration_ms,
            files=result.files,
        )

    async with _gpu_sem:
        result = await anyio.to_thread.run_sync(_run)
    _ensure_watcher()
    return result


@mcp.tool()
async def reindex_codebase(clean: bool = False) -> IndexResponse:
    """Re-index the source codebase (incremental by default).

    Args:
        clean: If True, drop and recreate the codebase
            collection before a full re-index.

    Returns:
        IndexResponse with counts of added, updated, and
        removed chunks plus timing.

    Raises:
        RuntimeError: If RAG components fail to initialize
            (e.g., no CUDA GPU available).
    """

    def _run() -> IndexResponse:
        comp = get_comp()
        mode = "full" if clean else "incremental"
        logger.info("Starting %s codebase re-index...", mode)
        if clean:
            result = comp.code_indexer.full_index(clean=True)
        else:
            result = comp.code_indexer.incremental_index()
        return IndexResponse(
            total=result.total,
            added=result.added,
            updated=result.updated,
            removed=result.removed,
            duration_ms=result.duration_ms,
            files=result.files,
        )

    async with _gpu_sem:
        result = await anyio.to_thread.run_sync(_run)
    _ensure_watcher()
    return result


# Resources
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

    def _run() -> str:
        comp = get_comp()
        doc = comp.store.get_by_id(doc_id)
        if not doc:
            raise FileNotFoundError(f"Document '{doc_id}' not found")
        return doc.get("content", "")

    return await anyio.to_thread.run_sync(_run)


# Prompts
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


def main(port: int | None = None) -> None:
    """Start the MCP server on stdio or HTTP transport.

    Args:
        port: If provided, run on streamable-http at
            127.0.0.1:<port>. Otherwise use stdio transport.
    """
    if port is not None:
        mcp.run(transport="streamable-http", host="127.0.0.1", port=port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
