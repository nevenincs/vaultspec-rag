"""Search and index MCP tools.

Split out of the original ``mcp_server.py`` monolith per the
``2026-06-01-module-split-adr``. Importing this module runs the
``@mcp.tool()`` decorators, registering the search/index tools on the
shared :data:`mcp` instance. The registry is read through the package
alias so a test rebind of ``_registry`` is observed.
"""

from __future__ import annotations

import logging
from typing import Any

from anyio.to_thread import run_sync as _run_in_thread

import vaultspec_rag.mcp_server as _m

from ..progress import NullProgressReporter
from ..service import RegistryFullError
from ..store import VaultStoreLockedError
from ._models import IndexResponse, IndexStatus, SearchResponse, SearchResultItem
from ._state import mcp
from ._utils import (
    _clamp_top_k,
    _is_sensitive_path,
    _resolve_root,
    _validate_query,
)

logger = logging.getLogger("vaultspec_rag.mcp_server")


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
            with _m._registry.lease(root) as slot:
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
            return _m._registry_full_error_dict(exc)
        except VaultStoreLockedError as exc:
            return _m._local_store_locked_error_dict(exc)

    result = await _run_in_thread(_run)
    if isinstance(result, SearchResponse):
        _m._ensure_watcher(root)
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
            with _m._registry.lease(root) as slot:
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
            return _m._registry_full_error_dict(exc)
        except VaultStoreLockedError as exc:
            return _m._local_store_locked_error_dict(exc)

    result = await _run_in_thread(_run)
    if isinstance(result, SearchResponse):
        _m._ensure_watcher(root)
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
            with _m._registry.lease(root) as slot:
                try:
                    import torch

                    vram_gb = (
                        torch.cuda.get_device_properties(0).total_memory / 1e9
                        if torch.cuda.is_available()
                        else 0.0
                    )
                except ImportError as exc:
                    logger.debug(
                        "torch unavailable for index_status VRAM probe: %s", exc
                    )
                    vram_gb = 0.0
                return IndexStatus(
                    vault_count=slot.store.count(),
                    code_count=slot.store.count_code(),
                    storage_path=str(slot.store.db_path),
                    target_dir=str(root),
                    vram_gb=round(vram_gb, 2),
                )
        except RegistryFullError as exc:
            return _m._registry_full_error_dict(exc)

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
            with _m._registry.lease(root) as slot:
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
            return _m._registry_full_error_dict(exc)

    result = await _run_in_thread(_run)
    if isinstance(result, IndexResponse):
        _m._ensure_watcher(root)
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
            with _m._registry.lease(root) as slot:
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
            return _m._registry_full_error_dict(exc)

    result = await _run_in_thread(_run)
    if isinstance(result, IndexResponse):
        _m._ensure_watcher(root)
    return result
