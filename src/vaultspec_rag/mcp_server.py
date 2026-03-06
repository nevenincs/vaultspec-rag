"""MCP server for VaultSpec RAG search and retrieval.

Exposes tools for searching vault and codebase, resources for
retrieving full contents, and prompts for common RAG tasks.
"""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

from .embeddings import EmbeddingModel
from .indexer import CodebaseIndexer, VaultIndexer
from .search import VaultSearcher
from .store import VaultStore

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP("VaultSpec Search")


# Global components (lazy-loaded)
class RagComponents:
    store: VaultStore
    model: EmbeddingModel
    searcher: VaultSearcher
    vault_indexer: VaultIndexer
    code_indexer: CodebaseIndexer
    root_dir: Path


_comp: RagComponents | None = None


def get_comp() -> RagComponents:
    """Return the initialized RAG components, creating them if necessary."""
    global _comp
    if _comp is None:
        logger.info("Initializing VaultSpec RAG components...")
        root_env = os.environ.get("VAULTSPEC_ROOT")
        root_dir = Path(root_env) if root_env else Path.cwd()

        # VaultStore connection will respect environment variables for storage dir
        store = VaultStore(root_dir)
        model = EmbeddingModel()

        _comp = RagComponents()
        _comp.store = store
        _comp.model = model
        _comp.searcher = VaultSearcher(root_dir, model, store)
        _comp.vault_indexer = VaultIndexer(root_dir, model, store)
        _comp.code_indexer = CodebaseIndexer(root_dir, model, store)
        _comp.root_dir = root_dir
    return _comp


# Structured Output Models
class SearchResultItem(BaseModel):
    """Pydantic mirror of SearchResult for MCP serialization."""

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


class SearchResponse(BaseModel):
    results: list[SearchResultItem] = Field(description="List of ranked search results")
    summary: str = Field(description="Human-readable summary of findings")


class IndexStatus(BaseModel):
    vault_count: int = Field(description="Number of indexed vault documents")
    code_count: int = Field(description="Number of indexed codebase chunks")
    storage_path: str = Field(description="Path to the vector database")


# Tools
@mcp.tool()
async def search_vault(
    query: str, top_k: int = 5, ctx: Context | None = None
) -> SearchResponse:
    """Search the documentation vault for relevant ADRs, plans, and research.

    Args:
        query: Natural language search string (supports type:adr, feature:name, etc.).
        top_k: Number of results to return.
        ctx: Optional request context for logging.
    """
    comp = get_comp()
    if ctx and hasattr(ctx, "info"):
        with contextlib.suppress(Exception):
            await ctx.info(f"Searching vault for: {query}")

    results = comp.searcher.search_vault(query, top_k=top_k)
    items = [SearchResultItem.model_validate(r, from_attributes=True) for r in results]
    summary = f"Found {len(results)} relevant documents in the vault."
    return SearchResponse(results=items, summary=summary)


@mcp.tool()
async def search_codebase(
    query: str, top_k: int = 5, language: str | None = None, ctx: Context | None = None
) -> SearchResponse:
    """Search the source codebase for relevant functions, classes, or logic.

    Args:
        query: Natural language search string or code snippet.
        top_k: Number of chunks to return.
        language: Optional language filter (e.g., 'python', 'rust').
        ctx: Optional request context for logging.
    """
    comp = get_comp()
    if ctx and hasattr(ctx, "info"):
        with contextlib.suppress(Exception):
            await ctx.info(f"Searching codebase for: {query} (lang={language})")

    if language:
        query = f"lang:{language} {query}"

    results = comp.searcher.search_codebase(query, top_k=top_k)
    items = [SearchResultItem.model_validate(r, from_attributes=True) for r in results]
    summary = f"Found {len(results)} relevant code blocks."
    return SearchResponse(results=items, summary=summary)


@mcp.tool()
async def search_all(
    query: str, top_k: int = 5, ctx: Context | None = None
) -> SearchResponse:
    """Search both documentation and codebase for comprehensive context."""
    comp = get_comp()
    if ctx and hasattr(ctx, "info"):
        with contextlib.suppress(Exception):
            await ctx.info(f"Unified search for: {query}")

    results = comp.searcher.search_all(query, top_k=top_k)
    items = [SearchResultItem.model_validate(r, from_attributes=True) for r in results]
    summary = f"Found {len(results)} mixed results from vault and codebase."
    return SearchResponse(results=items, summary=summary)


@mcp.tool()
def get_index_status() -> IndexStatus:
    """Return the current status of the RAG index (doc counts, etc.)."""
    comp = get_comp()

    # Avoid calling methods directly to prevent ToolError if they are missing
    v_count = 0
    if hasattr(comp.store, "count"):
        with contextlib.suppress(Exception):
            v_count = comp.store.count()

    c_count = 0
    if hasattr(comp.store, "count_code"):
        with contextlib.suppress(Exception):
            c_count = comp.store.count_code()

    path = "unknown"
    if hasattr(comp.store, "db_path"):
        path = str(comp.store.db_path)

    return IndexStatus(
        vault_count=v_count,
        code_count=c_count,
        storage_path=path,
    )


@mcp.tool()
def get_code_file(path: str) -> str:
    """Retrieve the full content of a source file by path.

    Args:
        path: Path to the file relative to codebase root.
    """
    comp = get_comp()
    full_path = (comp.root_dir / path).resolve()
    if not full_path.is_relative_to(comp.root_dir.resolve()):
        return f"Error: path '{path}' is outside the workspace."
    if not full_path.exists():
        return f"Error: File '{path}' not found."
    try:
        return full_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file '{path}': {e}"


# Resources
@mcp.resource("vault://{doc_id}")
def get_vault_document(doc_id: str) -> str:
    """Retrieve the full content of a vault document by its stem ID.

    Args:
        doc_id: Stem of the document filename.
    """
    comp = get_comp()
    doc = comp.store.get_by_id(doc_id)
    if not doc:
        return f"Document '{doc_id}' not found."
    return doc.get("content", "")


# Prompts
@mcp.prompt()
def analyze_feature(feature_name: str) -> str:
    """Create a prompt to analyze a specific feature across docs and code."""
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


def main():
    """Main entry point for the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
