"""Pydantic response models for the RAG daemon.

Split out of the original ``server.py`` monolith per the
``2026-06-01-module-split-adr``. These models serialize tool results
across the MCP transport and are re-exported verbatim from the package
root.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..capabilities import BackendCapabilities


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
        source_path: Original source file for a preprocess-hook result
            (e.g. a PDF). None for ordinary results (#185).
        preprocessor_id: Id of the preprocessor that produced this result.
        anchor: Deep-link into the source's own addressing scheme.
        locator: Human-readable locator (e.g. ``"page 12"``).
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
    source_path: str | None = None
    preprocessor_id: str | None = None
    anchor: str | None = None
    locator: str | None = None


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
        status: Service state - ``"ready"``, ``"degraded"``,
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
