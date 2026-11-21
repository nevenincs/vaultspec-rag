"""Run one search inside the CLI process and render its answer.

This is the local half of ``search``: it runs only under an explicit local
mandate, opens the local index directly, and hands the renderer the same
``index_state`` shape the service puts on its own response.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import typer

import vaultspec_rag.cli as _cli

from .._operator_commands import index_command
from .._source_types import PublicSourceType
from .._store_locks import VaultStoreLockedError
from ..api import CodebaseSearchRequest, VaultSearchRequest
from . import _render as search_render
from ._gpu_errors import _handle_gpu_error
from ._render import (
    _display_search_results,
    _emit_json,
    _emit_json_error_and_exit,
    _plain,
)
from ._search_filters import fail_invalid_filter, fail_invalid_prefer
from ._search_results_render import (
    FILTER_ADVISORY,
    ServiceSearchRenderRequest,
    handle_service_results,
    render_partial_domain_failures,
    render_shortfall_warnings,
    search_type_count_label,
    search_type_result_label,
)

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Iterator
    from typing import NoReturn

    from .._index_breadth import CodeBreadthSnapshot
    from .._index_integrity import IndexIntegrity, IndexIntegritySnapshot
    from .._publication_state import IndexTransitionError
    from .._source_types import IndexSource
    from ..search import DocumentSearchResult, SearchResult
    from ..search._outcomes import CombinedSearchOutcome
    from ..server._search_route_availability import SearchAvailabilityRequestFacts


def _attach_result_collapse(
    envelope: dict[str, object] | None, results: object
) -> None:
    """Record on *envelope* that this page resolved to a single file.

    A result carries its path under ``path``; a combined outcome nests its
    per-domain lists. Anything without a readable path contributes nothing
    rather than a placeholder, so a shape this does not understand makes the
    signal stay silent instead of inventing a collapse.

    Takes an optional envelope because the non-JSON path has none to carry the
    block: there the warning is rendered from the service payload instead, and
    silently doing nothing here is the correct behaviour rather than a guard
    worth raising over.
    """
    from .._search_state import result_collapse

    if envelope is None:
        return
    state = envelope.get("index_state")
    if not isinstance(state, dict):
        return
    paths = tuple(
        str(path)
        for item in _iter_result_rows(results)
        if isinstance(path := getattr(item, "path", None), str)
    )
    collapse = result_collapse(paths)
    if collapse is not None:
        cast("dict[str, object]", state)["result_collapse"] = collapse


def _iter_result_rows(results: object) -> Iterator[object]:
    """Yield every result row, flattening a combined outcome's domain lists."""
    if isinstance(results, list):
        yield from cast("list[object]", results)
        return
    for attribute in ("vault_results", "code_results", "document_results"):
        nested = getattr(results, attribute, None)
        if isinstance(nested, list):
            yield from cast("list[object]", nested)


@dataclass(frozen=True, slots=True)
class InProcessSearchRequest:
    target: pathlib.Path
    query: str
    search_type: PublicSourceType
    max_results: int
    language: str | None
    path: str | None
    node_type: str | None
    function_name: str | None
    class_name: str | None
    include_paths: list[str] | None
    exclude_paths: list[str] | None
    dedup_locales: bool | None
    prefer: str | None
    doc_type: str | None
    feature: str | None
    date: str | None
    tag: str | None
    source_path: str | None
    extractor_id: str | None
    extractor_version: str | None
    locator_kind: str | None
    json_mode: bool
    envelope: dict[str, object] | None = None
    include_documents: bool = True
    extractor_prefix: str | None = None
    metadata_filters: dict[str, list[str]] | None = None


def _count_indexed(request: InProcessSearchRequest) -> dict[PublicSourceType, int]:
    """Count what each domain holds, opening only the stores this search reads."""
    from ..registry import get_registry

    registry = get_registry()
    target = request.target
    return {
        PublicSourceType.VAULT: registry.vault_doc_count(target),
        PublicSourceType.CODE: registry.code_chunk_count(target),
        PublicSourceType.DOCUMENT: (
            registry.document_chunk_count(target)
            if request.search_type is not PublicSourceType.COMBINED
            or request.include_documents
            else 0
        ),
    }


def _publish_index_state(
    request: InProcessSearchRequest,
    counts: dict[PublicSourceType, int],
    breadth_snapshot: CodeBreadthSnapshot | None,
    integrity_snapshot: IndexIntegritySnapshot | IndexIntegrity,
    integrity_source: PublicSourceType,
) -> None:
    """Fill the envelope's ``index_state`` from counts already taken."""
    from .._search_state import BreadthFindings, search_index_state

    envelope = request.envelope
    if envelope is None:
        return
    search_type = request.search_type
    # Breadth is published for the code index alone, so a vault- or
    # document-only search has no claim to fall short of.
    shortfall = (
        breadth_snapshot.finish(counts[PublicSourceType.CODE])
        if breadth_snapshot is not None
        else None
    )
    # A combined search reconciles the code domain, mirroring the combined
    # shortfall above; single-domain searches reconcile their own.
    integrity = integrity_snapshot.finish(counts[integrity_source])
    envelope["index_state"] = search_index_state(
        indexed_count=(
            sum(counts.values())
            if search_type is PublicSourceType.COMBINED
            else counts[search_type]
        ),
        requested_root=request.target,
        search_type=search_type,
        findings=BreadthFindings(shortfall=shortfall, integrity=integrity),
    )


def _search_code(
    request: InProcessSearchRequest,
) -> list[SearchResult]:
    import vaultspec_rag

    return vaultspec_rag.search_codebase(
        CodebaseSearchRequest(
            root_dir=request.target,
            query=request.query,
            top_k=request.max_results,
            language=request.language,
            path=request.path,
            node_type=request.node_type,
            function_name=request.function_name,
            class_name=request.class_name,
            include_paths=request.include_paths,
            exclude_paths=request.exclude_paths,
            dedup_locales=request.dedup_locales,
            prefer=request.prefer,
        )
    )


def _search_vault(
    request: InProcessSearchRequest,
) -> list[SearchResult]:
    import vaultspec_rag

    return vaultspec_rag.search_vault(
        VaultSearchRequest(
            root_dir=request.target,
            query=request.query,
            top_k=request.max_results,
            doc_type=request.doc_type,
            feature=request.feature,
            date=request.date,
            tag=request.tag,
        )
    )


def _search_documents(
    request: InProcessSearchRequest,
) -> list[DocumentSearchResult]:
    import vaultspec_rag

    from .._public_search import DocumentSearchRequest

    return vaultspec_rag.search_documents(
        DocumentSearchRequest(
            root_dir=request.target,
            query=request.query,
            top_k=request.max_results,
            source_path=request.source_path,
            extractor_id=request.extractor_id,
            extractor_version=request.extractor_version,
            locator_kind=request.locator_kind,
            extractor_prefix=request.extractor_prefix,
            metadata_filters=request.metadata_filters,
        )
    )


def _search_combined(
    request: InProcessSearchRequest,
) -> CombinedSearchOutcome:
    import vaultspec_rag

    from .._public_search import (
        CodeCombinedSearchFilters,
        CombinedSearchRequest,
        DocumentCombinedSearchFilters,
        VaultCombinedSearchFilters,
    )

    return vaultspec_rag.search_combined(
        CombinedSearchRequest(
            include_documents=request.include_documents,
            root_dir=request.target,
            query=request.query,
            top_k=request.max_results,
            vault_filters=VaultCombinedSearchFilters(
                doc_type=request.doc_type,
                feature=request.feature,
                date=request.date,
                tag=request.tag,
            ),
            code_filters=CodeCombinedSearchFilters(
                language=request.language,
                path=request.path,
                node_type=request.node_type,
                function_name=request.function_name,
                class_name=request.class_name,
                include_paths=tuple(request.include_paths or ()),
                exclude_paths=tuple(request.exclude_paths or ()),
                dedup_locales=request.dedup_locales,
                prefer=request.prefer,
            ),
            document_filters=DocumentCombinedSearchFilters(
                source_path=request.source_path,
                extractor_id=request.extractor_id,
                extractor_version=request.extractor_version,
                locator_kind=request.locator_kind,
                extractor_prefix=request.extractor_prefix,
                metadata_filters=request.metadata_filters,
            ),
        )
    )


def _run_search(
    request: InProcessSearchRequest,
) -> list[SearchResult] | list[DocumentSearchResult] | CombinedSearchOutcome:
    """Dispatch the request to the entry point for its search type."""
    search_type = request.search_type
    if search_type is PublicSourceType.CODE:
        return _search_code(request)
    if search_type is PublicSourceType.VAULT:
        return _search_vault(request)
    if search_type is PublicSourceType.DOCUMENT:
        return _search_documents(request)
    return _search_combined(request)


def try_in_process_search(
    request: InProcessSearchRequest,
) -> list[SearchResult | DocumentSearchResult] | CombinedSearchOutcome:
    """Run one search in this process.

    ``envelope`` collects the same ``index_state`` block the service puts on its
    response, so the local path and the service path hand the renderer one
    shape. It is filled from the counts this function already takes, never from
    a fresh count, so the local path pays no store round trip the service does
    not.
    """
    from .._index_breadth import acquire_code_breadth_snapshot_if_proven
    from .._index_integrity import (
        IndexIntegritySnapshot,
        acquire_index_integrity_snapshot_if_proven,
    )
    from .._publication_state import IndexTransitionError
    from ..search import InvalidFilterForSearchTypeError

    target = request.target
    search_type = request.search_type
    json_mode = request.json_mode
    # An empty or unbuilt index has nothing to search, so skip the
    # "Searching..." status spinner: the search returns an empty, actionable
    # result either way, and the spinner's control codes otherwise leak into
    # non-interactive (captured / piped) output as a spurious first line.
    # Counting opens the local store, so it can raise the locked-store error
    # just as the search itself can. It sits inside the same guard for that
    # reason: outside it the error escaped uncaught and the command exited
    # non-zero with no output at all, so the routing-mode message this path
    # exists to print never reached an operator whose store was actually busy.
    breadth_snapshot = (
        acquire_code_breadth_snapshot_if_proven(target)
        if search_type in (PublicSourceType.CODE, PublicSourceType.COMBINED)
        else None
    )
    integrity_source = (
        PublicSourceType.CODE
        if search_type is PublicSourceType.COMBINED
        else search_type
    )
    integrity_snapshot = acquire_index_integrity_snapshot_if_proven(
        target, integrity_source
    )
    try:
        counts = _count_indexed(request)
    except VaultStoreLockedError as exc:
        search_render.handle_vaultstore_locked_error(exc, json_mode)
        return []
    has_index = (
        any(counts.values())
        if search_type is PublicSourceType.COMBINED
        else counts[search_type] > 0
    )
    _publish_index_state(
        request, counts, breadth_snapshot, integrity_snapshot, integrity_source
    )
    try:
        status_ctx = (
            _cli.console.status(f"Searching {search_type.value}...")
            if has_index and not json_mode
            else contextlib.nullcontext()
        )
        with status_ctx:
            results = _run_search(request)
        if isinstance(integrity_snapshot, IndexIntegritySnapshot):
            integrity_snapshot.publication.validate()
        # The block above is built before the search runs, because its counts
        # come from the store rather than from the answer. The collapse signal
        # is the one finding that cannot be known until there IS an answer, so
        # it is attached here rather than restated as a second builder - the
        # daemon route reaches the same conclusion through the same function.
        _attach_result_collapse(request.envelope, results)
        return cast(
            "list[SearchResult | DocumentSearchResult] | CombinedSearchOutcome",
            results,
        )
    except VaultStoreLockedError as exc:
        search_render.handle_vaultstore_locked_error(exc, json_mode)
        return []
    except InvalidFilterForSearchTypeError as exc:
        # Refusals that need the root's index, such as an undeclared metadata
        # key, can only be raised by the search itself.
        fail_invalid_filter(exc, json_mode)
    except IndexTransitionError as exc:
        # A rebuild's reset touched the read. That is a retryable condition of
        # the index, not a GPU or runtime fault, so it must not reach the
        # handler below that treats a RuntimeError as one.
        _fail_index_transition(exc, request)
    except (ImportError, RuntimeError) as e:
        _handle_gpu_error(e, command="search", json_mode=json_mode)
        return []


def validate_and_handle_filters(request: InProcessSearchRequest) -> None:
    from ..search import (
        InvalidFilterForSearchTypeError,
        InvalidPreferValueError,
        SearchFilterOptions,
        validate_search_filters,
    )

    try:
        validate_search_filters(
            request.search_type,
            SearchFilterOptions(
                language=request.language,
                path=request.path,
                node_type=request.node_type,
                function_name=request.function_name,
                class_name=request.class_name,
                doc_type=request.doc_type,
                feature=request.feature,
                date=request.date,
                tag=request.tag,
                include_paths=request.include_paths,
                exclude_paths=request.exclude_paths,
                dedup_locales=request.dedup_locales,
                prefer=request.prefer,
                source_path=request.source_path,
                extractor_id=request.extractor_id,
                extractor_version=request.extractor_version,
                locator_kind=request.locator_kind,
                extractor_prefix=request.extractor_prefix,
                metadata_filters=request.metadata_filters,
            ),
            include_documents=request.include_documents,
        )
    except InvalidPreferValueError as exc:
        fail_invalid_prefer(exc, request.json_mode)
    except InvalidFilterForSearchTypeError as exc:
        fail_invalid_filter(exc, request.json_mode)


@dataclass(frozen=True, slots=True)
class InProcessRenderRequest:
    results: list[SearchResult | DocumentSearchResult] | CombinedSearchOutcome
    query: str
    search_type: PublicSourceType
    json_mode: bool
    show_scores: bool
    target: pathlib.Path
    envelope: dict[str, object] | None = None


def _availability_facts(
    target: pathlib.Path, source: IndexSource, request_id: str
) -> SearchAvailabilityRequestFacts:
    """Describe a local search to the service's availability classifier.

    A local search has no job snapshot to offer, so the classifier reads only
    the index state the caller built.
    """
    from ..server._search_route_availability import SearchAvailabilityRequestFacts

    return SearchAvailabilityRequestFacts(
        job_snapshot_before=[],
        root=target,
        source=source,
        request_id=request_id,
        port=None,
    )


def _fail_index_transition(
    exc: IndexTransitionError, request: InProcessSearchRequest
) -> NoReturn:
    """Render the retryable transition refusal and exit with the service's code.

    The refusal is the one the service answers a reset-touched read with, built
    by the same function, so a local search and a served one report one
    condition one way. A local search has no job snapshot to offer.
    """
    from uuid import uuid4

    from ..server._search_route_availability import typed_storage_refusal

    facts = _availability_facts(
        request.target, cast("IndexSource", exc.source.value), uuid4().hex
    )
    refusal, _ = typed_storage_refusal(exc, facts, [])
    handle_service_results(
        refusal,
        ServiceSearchRenderRequest(
            request.query,
            request.search_type.value,
            request.json_mode,
            False,
            request.target,
        ),
    )
    raise typer.Exit(code=1)


def _empty_in_process_failure(
    request: InProcessRenderRequest, index_state: dict[str, object]
) -> dict[str, object] | None:
    """Supply local observations to the shared readiness and failure model."""
    from uuid import uuid4

    from .._search_state import SearchReasonCode
    from ..server._search_availability import classify_search_response

    request_id = uuid4().hex
    if request.search_type is PublicSourceType.COMBINED:
        outcome = cast("CombinedSearchOutcome", request.results)
        unbuilt = next(
            (
                fact
                for fact in outcome.source_facts
                if fact.reason_code is SearchReasonCode.INDEX_NOT_BUILT
            ),
            None,
        )
        if unbuilt is None:
            return None
        return unbuilt.failure_response(
            request_id=request_id,
            index_state=index_state,
            sources=outcome.source_facts,
        ) | {"domains": outcome.domain_status_payload()}
    facts = _availability_facts(request.target, request.search_type.value, request_id)
    classified = classify_search_response(
        {"results": []},
        facts.to_context(after_snapshot=[], index_state=index_state),
    )
    return classified.response if classified.status_code != 200 else None


def render_in_process_results(request: InProcessRenderRequest) -> None:
    from ..search._outcomes import (
        COMBINED_SEARCH_FAILED,
        COMBINED_SEARCH_FAILED_MESSAGE,
    )

    results = request.results
    query = request.query
    search_type = request.search_type
    json_mode = request.json_mode
    show_scores = request.show_scores
    target = request.target
    breadth = request.envelope or {}

    if search_type is PublicSourceType.COMBINED:
        # _run_in_process_search only returns a CombinedSearchOutcome when it
        # dispatched on PublicSourceType.COMBINED, the same discriminant
        # checked above, so `results` is that type here.
        outcome = cast("CombinedSearchOutcome", results)
        result_items = outcome.results
        domains = outcome.domain_status_payload()
        if not outcome.ok:
            failure_payload: dict[str, object] = {
                "ok": False,
                "error": COMBINED_SEARCH_FAILED,
                "message": COMBINED_SEARCH_FAILED_MESSAGE,
                "partial": False,
                "domains": domains,
            }
            if json_mode:
                _emit_json_error_and_exit(
                    "search",
                    COMBINED_SEARCH_FAILED,
                    COMBINED_SEARCH_FAILED_MESSAGE,
                    1,
                    domains=domains,
                )
            render_partial_domain_failures(failure_payload)
            raise typer.Exit(code=1)
    else:
        result_items = cast("list[SearchResult | DocumentSearchResult]", results)
        domains = None
    # The service's own wire form, so an in-process search shows the same
    # fields - and withholds the same ones - as a search the service answers.
    from ..server._models import SearchResultItem

    items = [SearchResultItem.serialize(r) for r in result_items]
    if not items and isinstance(raw_state := breadth.get("index_state"), dict):
        failure = _empty_in_process_failure(
            request, cast("dict[str, object]", raw_state)
        )
        if failure is not None:
            handle_service_results(
                failure,
                ServiceSearchRenderRequest(
                    query, search_type.value, json_mode, show_scores, target
                ),
            )
    if json_mode:
        data: dict[str, object] = {
            "query": query,
            "search_type": search_type.value,
            "via": "in-process",
            "advisory": FILTER_ADVISORY,
            "results": items,
        }
        if domains is not None:
            data["partial"] = cast("CombinedSearchOutcome", results).partial
            data["domains"] = domains
        data.update(breadth)
        _emit_json(
            True,
            "search",
            data=data,
        )
        return

    if not result_items:
        _render_empty_in_process_results(query, search_type.value, target)
        render_shortfall_warnings(breadth)
        if domains is not None:
            render_partial_domain_failures(
                {
                    "partial": cast("CombinedSearchOutcome", results).partial,
                    "domains": domains,
                }
            )
        return

    _display_search_results(
        items,
        search_type.value,
        via="in-process",
        show_scores=show_scores,
        root=target,
    )
    render_shortfall_warnings(breadth)
    if domains is not None:
        render_partial_domain_failures(
            {
                "partial": cast("CombinedSearchOutcome", results).partial,
                "domains": domains,
            }
        )


def _render_empty_in_process_results(
    query: str,
    search_type: str,
    target: pathlib.Path,
) -> None:
    result_label = search_type_result_label(search_type)
    count_label = search_type_count_label(search_type)
    _plain(f"No {result_label} results found for: {query}")
    _plain(f"Why: No matching {count_label} were found in the local index.")
    _plain(f"Project: {target}", soft_wrap=True)
    _plain("Next actions:")
    _plain(f"  - {index_command(search_type)}")
    _plain("  - vaultspec-rag status")
