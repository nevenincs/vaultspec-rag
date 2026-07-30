"""Search and index MCP tools.

Each tool is a thin delegation to the running RAG daemon through the shared
import-light :mod:`vaultspec_rag.serviceclient` layer. The MCP defines no
behavior of its own: it resolves the service port, offloads the synchronous
wire call to a worker thread, and maps an unreachable service to one clear
"service not running" error. There is no local fallback - when the daemon is
down the MCP is intentionally dysfunctional.

``project_root`` is optional on every tool because this adapter resolves it -
see :mod:`vaultspec_rag.mcp._roots`. The daemon's routes require an explicit
root and always will; the optionality advertised here is the adapter's promise
to fill it, not a default the service supplies.

Importing this module runs the ``@mcp.tool()`` decorators, registering the
search/index tools on the shared :data:`mcp` instance.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any, cast

from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict

from .._source_types import SourceTypeParseError, parse_source_type
from ..serviceclient._transport import (
    _try_http_admin,
    _try_http_clean,
    _try_http_code_file,
    _try_http_reindex,
    _try_http_search,
    document_search_filters,
)
from ._mcp import mcp
from ._roots import _resolve_project_root

if TYPE_CHECKING:
    from collections.abc import Callable


class SearchResults(BaseModel):
    """Structured envelope returned by the search tools (MCP ``outputSchema``).

    Declares the load-bearing fields so clients get a validated result schema
    and ``structuredContent``; ``extra="allow"`` carries the daemon's evolving
    diagnostic fields (``timing``, ``index_state``, ``empty``, error envelopes)
    without coupling the MCP layer to the daemon's full response shape.
    """

    model_config = ConfigDict(extra="allow")

    results: list[dict[str, object]] = []
    summary: str | None = None


_SERVICE_DOWN_MESSAGE = (
    "vaultspec-rag service is not running. Start it with `vaultspec-rag server start`."
)

#: Default result count for the search tools, aligned with the CLI's
#: ``--max-results`` default so the same query returns the same number of hits
#: on both surfaces.
_DEFAULT_TOP_K = 10

# Behavioral hints advertised to clients (MCP 2026-07-28 tool annotations). The
# search and retrieval tools only read and are repeatable. The index-refresh
# tools reconcile to the current files and expose no clean flag, so this surface
# cannot request a drop-and-recreate rebuild.
#
# The hint describes the request, not the outcome: the incremental path can
# still escalate itself into a destructive rebuild when stored vectors predate
# the current embed-input format or content-shaping config has drifted, which
# empties the collection until repopulation finishes. Closing that gap belongs
# in the indexer, where the escalation lives; widening the hint here would
# describe an effect no caller asked for and would not stop it happening.
#
# None of these tools reach an open world of external entities - they talk to
# one local daemon.
_READ_ONLY = ToolAnnotations(
    read_only_hint=True, idempotent_hint=True, open_world_hint=False
)
_INDEX_REFRESH = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
_CLEAN = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=True,
    open_world_hint=False,
)


def _canonical_tool_source(value: object) -> str:
    """Return one closed-set source value or raise a structured tool error."""
    try:
        return parse_source_type(value, allow_aliases=True).value
    except SourceTypeParseError as exc:
        raise ValueError(f"{exc.error_kind}: {exc}") from None


def _search_envelope_or_raise(
    result: object,
) -> dict[str, Any]:
    """Return a successful search envelope or raise the daemon's failure."""
    if not isinstance(result, dict):
        raise RuntimeError(
            "invalid_service_response: The search service returned an invalid "
            "response; expected a JSON object envelope."
        )
    # isinstance narrows the key/value types no further than dict[Unknown,
    # Unknown]; the JSON object this daemon returns is always str-keyed.
    envelope = cast("dict[str, Any]", result)
    if envelope.get("ok") is not False:
        if not isinstance(envelope.get("results"), list):
            raise RuntimeError(
                "invalid_service_response: The search service returned an invalid "
                "response; expected a success envelope containing a results list."
            )
        return envelope

    error_code = str(envelope.get("error") or "search_failed")
    message = str(envelope.get("message") or "The search request failed.")
    raw_remediation = envelope.get("remediation")
    if isinstance(raw_remediation, list):
        remediation = [
            step.strip()
            for step in cast("list[object]", raw_remediation)
            if isinstance(step, str) and step.strip()
        ]
    elif isinstance(raw_remediation, str) and raw_remediation.strip():
        remediation = [raw_remediation.strip()]
    else:
        remediation = []

    detail = f"{error_code}: {message}"
    if remediation:
        detail = f"{detail} Remediation: {' | '.join(remediation)}"
    raise RuntimeError(detail)


def _with_domain_tokens(
    query: str,
    *,
    exclude_domains: list[str] | None,
    only_domains: list[str] | None,
    include_domains: list[str] | None,
) -> str:
    """Append exclude:/only:/include: domain tokens to a query string.

    The daemon parses these inline tokens, so encoding the MCP tool's typed
    domain params this way keeps the HTTP wire shape identical to the CLI's
    without widening the transport signature.
    """
    tokens: list[str] = []
    for prefix, values in (
        ("exclude", exclude_domains),
        ("only", only_domains),
        ("include", include_domains),
    ):
        cleaned = [v.strip() for v in values or [] if v.strip()]
        if cleaned:
            tokens.append(f"{prefix}:{','.join(cleaned)}")
    if not tokens:
        return query
    return f"{query} {' '.join(tokens)}".strip()


def _require_port() -> int:
    """Return the port of a reachable, release-compatible service.

    Two preconditions for every tool call, both mapped to a single
    ``RuntimeError`` here so neither contract is restated per tool: the daemon
    must be reachable (a tool never falls back to a local backend), and it must
    be the same release as this client. The version travels in the discovery
    pointer this call already reads, so confirming it costs no extra round trip.

    Driving a foreign release is exactly the silent-degradation this refuses: an
    unrecognised request field is dropped rather than rejected, so a newer
    client's filters would be ignored and the answer computed against a
    different candidate set, with a 200 and no indication anything was lost.
    """
    from ..serviceclient._compat import resolve_data_plane_service

    service = resolve_data_plane_service()
    if service.port is None:
        raise RuntimeError(_SERVICE_DOWN_MESSAGE)
    if not service.version.is_compatible:
        raise RuntimeError(
            f"{service.version.error_code()}: {service.version.reason()}. "
            f"{' '.join(service.version.remediation())}"
        )
    return service.port


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
async def search_vault(  # noqa: PLR0913 - MCP exposes the stable flat tool input schema.
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
) -> SearchResults:
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
            _canonical_tool_source("vault"),
            top_k,
            port,
            _resolve_project_root(project_root),
            doc_type=doc_type,
            feature=feature,
            date=date,
            tag=tag,
            intent=intent,
            like_ids=like_ids,
            unlike_ids=unlike_ids,
        )
    )
    return SearchResults.model_validate(_search_envelope_or_raise(result))


@mcp.tool(title="Search codebase", annotations=_READ_ONLY)
async def search_codebase(  # noqa: PLR0913 - MCP exposes the stable flat tool input schema.
    query: str,
    top_k: int = _DEFAULT_TOP_K,
    language: str | None = None,
    path: str | None = None,
    node_type: str | None = None,
    function_name: str | None = None,
    class_name: str | None = None,
    include_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    dedup_locales: bool | None = None,
    prefer: str | None = None,
    exclude_domains: list[str] | None = None,
    only_domains: list[str] | None = None,
    include_domains: list[str] | None = None,
    like_ids: list[str | int] | None = None,
    unlike_ids: list[str | int] | None = None,
    project_root: str | None = None,
) -> SearchResults:
    """Search the source codebase for relevant functions, classes, or logic.

    Noise domains (tests, docs, locale, generated, vendored, worktree clones)
    are hidden or demoted by the project noise profile; pass ``exclude_domains``
    / ``only_domains`` to narrow further, or ``include_domains`` to re-admit a
    domain the profile filters by default.
    """
    port = _require_port()
    # Domain filters travel as inline query tokens (exclude:/only:/include:),
    # the same wire shape the CLI uses, so the transport needs no extra params.
    full_query = _with_domain_tokens(
        query,
        exclude_domains=exclude_domains,
        only_domains=only_domains,
        include_domains=include_domains,
    )
    result = await _delegate(
        partial(
            _try_http_search,
            full_query,
            _canonical_tool_source("codebase"),
            top_k,
            port,
            _resolve_project_root(project_root),
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
    return SearchResults.model_validate(_search_envelope_or_raise(result))


@mcp.tool(title="Search documents", annotations=_READ_ONLY)
async def search_documents(  # noqa: PLR0913 - MCP exposes the stable flat tool input schema.
    query: str,
    top_k: int = _DEFAULT_TOP_K,
    source_path: str | None = None,
    extractor_id: str | None = None,
    extractor_version: str | None = None,
    locator_kind: str | None = None,
    project_root: str | None = None,
) -> SearchResults:
    """Search independently indexed extracted-document content."""
    port = _require_port()
    result = await _delegate(
        partial(
            _try_http_search,
            query,
            _canonical_tool_source("document"),
            top_k,
            port,
            _resolve_project_root(project_root),
            document_filters=document_search_filters(
                source_path=source_path,
                extractor_id=extractor_id,
                extractor_version=extractor_version,
                locator_kind=locator_kind,
            ),
        )
    )
    return SearchResults.model_validate(_search_envelope_or_raise(result))


@mcp.tool(title="Search all index domains", annotations=_READ_ONLY)
async def search_combined(  # noqa: PLR0913 - MCP exposes each owned filter explicitly.
    query: str,
    top_k: int = _DEFAULT_TOP_K,
    language: str | None = None,
    path: str | None = None,
    node_type: str | None = None,
    function_name: str | None = None,
    class_name: str | None = None,
    include_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    dedup_locales: bool | None = None,
    prefer: str | None = None,
    exclude_domains: list[str] | None = None,
    only_domains: list[str] | None = None,
    include_domains: list[str] | None = None,
    doc_type: str | None = None,
    feature: str | None = None,
    date: str | None = None,
    tag: str | None = None,
    intent: str | None = None,
    source_path: str | None = None,
    extractor_id: str | None = None,
    extractor_version: str | None = None,
    locator_kind: str | None = None,
    project_root: str | None = None,
) -> SearchResults:
    """Search vault, code, and document domains with partial outcomes intact."""
    port = _require_port()
    result = await _delegate(
        partial(
            _try_http_search,
            _with_domain_tokens(
                query,
                exclude_domains=exclude_domains,
                only_domains=only_domains,
                include_domains=include_domains,
            ),
            _canonical_tool_source("combined"),
            top_k,
            port,
            _resolve_project_root(project_root),
            language=language,
            path=path,
            node_type=node_type,
            function_name=function_name,
            class_name=class_name,
            include_paths=include_paths,
            exclude_paths=exclude_paths,
            dedup_locales=dedup_locales,
            prefer=prefer,
            doc_type=doc_type,
            feature=feature,
            date=date,
            tag=tag,
            intent=intent,
            document_filters=document_search_filters(
                source_path=source_path,
                extractor_id=extractor_id,
                extractor_version=extractor_version,
                locator_kind=locator_kind,
            ),
        )
    )
    return SearchResults.model_validate(_search_envelope_or_raise(result))


@mcp.tool(title="Get code file", annotations=_READ_ONLY)
async def get_code_file(
    path: str,
    project_root: str | None = None,
) -> str:
    """Retrieve the full content of a source file by path."""
    port = _require_port()
    res = await _delegate(
        partial(
            _try_http_code_file,
            path,
            _resolve_project_root(project_root),
            port,
        )
    )
    if "content" in res:
        return str(res["content"])
    if "error" in res:
        raise ValueError(str(res["error"]))
    return ""


@mcp.tool(title="Reindex vault", annotations=_INDEX_REFRESH)
async def reindex_vault(
    project_root: str | None = None,
) -> dict[str, Any]:
    """Re-index vault documentation incrementally."""
    return await _reindex_source("vault", project_root)


@mcp.tool(title="Reindex codebase", annotations=_INDEX_REFRESH)
async def reindex_codebase(
    project_root: str | None = None,
) -> dict[str, Any]:
    """Re-index the source codebase incrementally."""
    return await _reindex_source("codebase", project_root)


async def _reindex_source(
    source: object,
    project_root: str | None,
) -> dict[str, Any]:
    """Delegate one canonical incremental reindex without local fallback."""
    port = _require_port()
    result = await _delegate(
        partial(
            _try_http_reindex,
            _canonical_tool_source(source),
            False,
            port,
            _resolve_project_root(project_root),
            initiator_kind="mcp",
        )
    )
    if result.get("ok") is False and result.get("partial") is not True:
        error = str(result.get("error") or "reindex_failed")
        message = str(result.get("message") or "The reindex request failed.")
        raise RuntimeError(f"{error}: {message}")
    return result


@mcp.tool(title="Reindex documents", annotations=_INDEX_REFRESH)
async def reindex_documents(
    project_root: str | None = None,
) -> dict[str, Any]:
    """Incrementally re-index extracted documents."""
    return await _reindex_source("document", project_root)


@mcp.tool(title="Reindex all index domains", annotations=_INDEX_REFRESH)
async def reindex_all(
    project_root: str | None = None,
) -> dict[str, Any]:
    """Incrementally re-index vault, code, and document domains."""
    return await _reindex_source("combined", project_root)


def _service_state_or_raise(result: dict[str, object]) -> dict[str, object]:
    """Return the bare service-state response without lifecycle interpretation.

    Service state is an observation document, not a quiesce transition
    acknowledgement. Its controller-owned ``quiesce`` block therefore travels
    unchanged to MCP callers; only a transport-owned failure envelope fails the
    tool call.
    """
    if result.get("ok") is False:
        error = str(result.get("error") or "status_failed")
        message = str(result.get("message") or "The status request failed.")
        raise RuntimeError(f"{error}: {message}")
    return result


@mcp.tool(title="Get index status", annotations=_READ_ONLY)
async def get_index_status(
    project_root: str | None = None,
) -> dict[str, Any]:
    """Return count, policy, generation, and degraded-state service details."""
    port = _require_port()
    args: dict[str, object] = {"project_root": _resolve_project_root(project_root)}
    result = await _delegate(
        partial(
            _try_http_admin,
            "get_service_state",
            args,
            port,
        )
    )
    return _service_state_or_raise(result)


async def _clean_source(
    source: object,
    project_root: str | None,
) -> dict[str, Any]:
    """Delegate one targeted clean and retain every domain outcome."""
    port = _require_port()
    result = await _delegate(
        partial(
            _try_http_clean,
            _canonical_tool_source(source),
            port,
            _resolve_project_root(project_root),
        )
    )
    if result.get("ok") is False and result.get("partial") is not True:
        error = str(result.get("error") or "clean_failed")
        message = str(result.get("message") or "The clean request failed.")
        raise RuntimeError(f"{error}: {message}")
    return result


@mcp.tool(title="Clean document index", annotations=_CLEAN)
async def clean_documents(
    project_root: str | None = None,
) -> dict[str, Any]:
    """Delete only independently indexed extracted-document content."""
    return await _clean_source("document", project_root)


@mcp.tool(title="Clean all index domains", annotations=_CLEAN)
async def clean_all(
    project_root: str | None = None,
) -> dict[str, Any]:
    """Delete vault, code, and document content with per-domain outcomes."""
    return await _clean_source("combined", project_root)
