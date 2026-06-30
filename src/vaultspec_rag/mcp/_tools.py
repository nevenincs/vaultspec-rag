"""Search and index MCP tools.

Each tool is a thin delegation to the running RAG daemon through the shared
import-light :mod:`vaultspec_rag.serviceclient` layer. The MCP defines no
behavior of its own: it resolves the service port, offloads the synchronous
wire call to a worker thread, and maps an unreachable service to one clear
"service not running" error. There is no local fallback - when the daemon is
down the MCP is intentionally dysfunctional.

Importing this module runs the ``@mcp.tool()`` decorators, registering the
search/index tools on the shared :data:`mcp` instance.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from mcp.types import ToolAnnotations

from ..serviceclient import (
    _default_service_port,
    _try_http_code_file,
    _try_http_reindex,
    _try_http_search,
)
from ._mcp import mcp

if TYPE_CHECKING:
    from collections.abc import Callable

_SERVICE_DOWN_MESSAGE = (
    "vaultspec-rag service is not running. Start it with `vaultspec-rag server start`."
)

#: Default result count for the search tools, aligned with the CLI's
#: ``--max-results`` default so the same query returns the same number of hits
#: on both surfaces.
_DEFAULT_TOP_K = 10

# Behavioral hints advertised to clients (MCP 2025-11-25 tool annotations). The
# search and retrieval tools only read and are repeatable; the index-refresh
# tools write the index and, via ``clean``, can drop-and-recreate, so they are
# not read-only and carry the destructive hint. None of these tools reach an
# open world of external entities - they talk to one local daemon.
_READ_ONLY = ToolAnnotations(
    readOnlyHint=True, idempotentHint=True, openWorldHint=False
)
_INDEX_REFRESH = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)


def _as_envelope(result: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
    """Return a stable dict envelope, wrapping a bare hit list under ``results``.

    The daemon normally returns a dict envelope (hits plus index-state and
    empty-result diagnostics); a bare list is the legacy shape. Normalising to
    one dict shape gives clients a single result schema to validate against.
    """
    if isinstance(result, list):
        return {"results": result}
    return result


def _require_port() -> int:
    """Return the running service port or raise the one service-down error.

    The unreachable condition is mapped to a single ``RuntimeError`` here so
    the no-local-fallback contract lives in exactly one place.
    """
    port = _default_service_port()
    if port is None:
        raise RuntimeError(_SERVICE_DOWN_MESSAGE)
    return port


def _unwrap[T](result: T | None) -> T:
    """Return *result*, mapping the unreachable sentinel to the service-down error.

    The ``serviceclient`` helpers return ``None`` when the service refuses the
    connection (down between the port read and the call); that maps to the same
    single ``RuntimeError`` as a missing ``service.json``.
    """
    if result is None:
        raise RuntimeError(_SERVICE_DOWN_MESSAGE)
    return result


async def _delegate[T](call: Callable[[], T | None]) -> T:
    """Offload a blocking ``serviceclient`` call and apply the service-down map.

    The ``serviceclient`` helpers are synchronous (blocking ``urllib``); every
    MCP tool is ``async def`` serving on an event loop, so the blocking call is
    run on a worker thread via ``anyio.to_thread.run_sync``. This is transport
    offload, not business logic.
    """
    import anyio.to_thread

    result = await anyio.to_thread.run_sync(call)
    return _unwrap(result)


@mcp.tool(title="Search vault", annotations=_READ_ONLY)
async def search_vault(
    query: str,
    top_k: int = _DEFAULT_TOP_K,
    doc_type: str | None = None,
    feature: str | None = None,
    date: str | None = None,
    tag: str | None = None,
    intent: str | None = None,
    like_ids: list[str | int] | None = None,
    unlike_ids: list[str | int] | None = None,
    project_root: str | None = None,
) -> dict[str, Any]:
    """Search the documentation vault for relevant ADRs, plans, and research.

    ``intent`` selects the ranking profile: ``orientation`` (default; surfaces
    active ADRs and grounding) or ``debugging`` (surfaces execution records and
    audits). ``doc_type`` accepts a single type or a comma-separated union
    (e.g. ``adr,plan``; ``index`` is not searchable). The inline query tokens
    ``intent:``, ``status:``, and ``type:`` are equivalent and also honored.
    Results carry each document's status and related-document edges.
    """
    port = _require_port()
    result = await _delegate(
        partial(
            _try_http_search,
            query,
            "vault",
            top_k,
            port,
            project_root or "",
            doc_type=doc_type,
            feature=feature,
            date=date,
            tag=tag,
            intent=intent,
            like_ids=like_ids,
            unlike_ids=unlike_ids,
        )
    )
    return _as_envelope(result)


@mcp.tool(title="Search codebase", annotations=_READ_ONLY)
async def search_codebase(
    query: str,
    top_k: int = _DEFAULT_TOP_K,
    language: str | None = None,
    path: str | None = None,
    node_type: str | None = None,
    function_name: str | None = None,
    class_name: str | None = None,
    include_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    dedup_locales: bool = False,
    prefer: str | None = None,
    like_ids: list[str | int] | None = None,
    unlike_ids: list[str | int] | None = None,
    project_root: str | None = None,
) -> dict[str, Any]:
    """Search the source codebase for relevant functions, classes, or logic."""
    port = _require_port()
    result = await _delegate(
        partial(
            _try_http_search,
            query,
            "code",
            top_k,
            port,
            project_root or "",
            language=language,
            path=path,
            node_type=node_type,
            function_name=function_name,
            class_name=class_name,
            include_paths=include_paths,
            exclude_paths=exclude_paths,
            dedup_locales=dedup_locales,
            prefer=prefer,
            like_ids=like_ids,
            unlike_ids=unlike_ids,
        )
    )
    return _as_envelope(result)


@mcp.tool(title="Get code file", annotations=_READ_ONLY)
async def get_code_file(
    path: str,
    project_root: str | None = None,
) -> str:
    """Retrieve the full content of a source file by path."""
    port = _require_port()
    res = await _delegate(partial(_try_http_code_file, path, project_root or "", port))
    if "content" in res:
        return str(res["content"])
    if "error" in res:
        raise ValueError(str(res["error"]))
    return ""


@mcp.tool(title="Reindex vault", annotations=_INDEX_REFRESH)
async def reindex_vault(
    clean: bool = False,
    project_root: str | None = None,
) -> dict[str, Any]:
    """Re-index vault documentation (incremental by default)."""
    port = _require_port()
    return await _delegate(
        partial(_try_http_reindex, "vault", clean, port, project_root or "")
    )


@mcp.tool(title="Reindex codebase", annotations=_INDEX_REFRESH)
async def reindex_codebase(
    clean: bool = False,
    project_root: str | None = None,
) -> dict[str, Any]:
    """Re-index the source codebase (incremental by default)."""
    port = _require_port()
    return await _delegate(
        partial(_try_http_reindex, "codebase", clean, port, project_root or "")
    )
