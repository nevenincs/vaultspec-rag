"""``search`` command plus the HuggingFace progress-suppression helper."""

from __future__ import annotations

import contextlib
import os
from typing import TYPE_CHECKING, Annotated, Literal, cast

import typer

import vaultspec_rag.cli as _cli

from ..store import VaultStoreLockedError
from ._app import CLIState, app
from ._gpu_errors import _handle_gpu_error
from ._http_search import _try_http_search
from ._render import (
    _display_port_unreachable_error,
    _display_search_results,
    _display_service_error,
    _emit_json,
    _emit_json_error_and_exit,
)
from ._service_status import _default_service_port

if TYPE_CHECKING:
    import pathlib
    from typing import NoReturn

    from ..search import SearchResult

__all__ = ["_suppress_hf_progress", "handle_search"]


def _suppress_hf_progress() -> None:
    """Silence HuggingFace and sentence-transformers tqdm bars.

    The CLI's in-process path loads SentenceTransformer + SparseEncoder
    + CrossEncoder; their default tqdm output pollutes stdout. Set
    before model construction so the env reaches every downstream
    import.
    """
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")


def _handle_service_results(
    service_results: list[dict[str, object]] | dict[str, object] | None,
    query: str,
    search_type: str,
    json_mode: bool,
    no_truncate: bool,
    show_scores: bool,
    target: pathlib.Path | None = None,
) -> None:
    if isinstance(service_results, dict):
        if "results" in service_results:
            _handle_service_success(
                service_results,
                query,
                search_type,
                json_mode,
                no_truncate,
                show_scores,
                target,
            )
            return
        _display_service_error(
            service_results,
            json_mode=json_mode,
            command="search",
        )
        raise typer.Exit(code=1)
    if json_mode:
        _emit_json(
            True,
            "search",
            data={
                "query": query,
                "search_type": search_type,
                "via": "service",
                "results": list(service_results or []),
            },
        )
        return
    if not service_results:
        _cli.console.print(
            f"No {search_type} results found for: {query}",
            markup=False,
            highlight=False,
        )
        return
    _display_search_results(
        service_results,
        search_type,
        via="service",
        no_truncate=no_truncate,
        show_scores=show_scores,
        root=target,
    )


def _handle_service_success(
    payload: dict[str, object],
    query: str,
    search_type: str,
    json_mode: bool,
    no_truncate: bool,
    show_scores: bool,
    target: pathlib.Path | None = None,
) -> None:
    raw_results = payload.get("results")
    results = (
        list(cast("list[dict[str, object]]", raw_results))
        if isinstance(raw_results, list)
        else []
    )
    if json_mode:
        data = dict(payload)
        data["query"] = query
        data["search_type"] = search_type
        data["via"] = "service"
        _emit_json(True, "search", data=data)
        return
    if not results:
        _render_empty_service_results(payload, query, search_type)
        return
    _display_search_results(
        results,
        search_type,
        via="service",
        no_truncate=no_truncate,
        show_scores=show_scores,
        root=target,
    )


def _render_empty_service_results(
    payload: dict[str, object],
    query: str,
    search_type: str,
) -> None:
    _cli.console.print(
        f"No {_search_type_result_label(search_type)} results found for: {query}",
        markup=False,
        highlight=False,
    )
    remediation: object = None
    empty = payload.get("empty")
    if isinstance(empty, dict):
        message = str(empty.get("message", "No matching indexed items found."))
        _cli.console.print(f"Why: {message}", markup=False)
        remediation = empty.get("remediation")
    index_state = payload.get("index_state")
    if isinstance(index_state, dict):
        _render_empty_index_state(cast("dict[str, object]", index_state), search_type)
    if isinstance(remediation, list) and remediation:
        _cli.console.print("Next actions:")
        for item in remediation:
            _cli.console.print(f"  - {item}")


def _search_type_result_label(search_type: str) -> str:
    if search_type in ("code", "codebase"):
        return "source code"
    if search_type == "vault":
        return "vault document"
    return search_type.replace("_", " ")


def _search_type_count_label(search_type: str) -> str:
    if search_type in ("code", "codebase"):
        return "source code sections"
    if search_type == "vault":
        return "vault documents"
    return f"{search_type.replace('_', ' ')} items"


def _render_empty_index_state(
    index_state: dict[str, object],
    search_type: str,
) -> None:
    source = str(index_state.get("source") or search_type)
    indexed = index_state.get("indexed_count", "?")
    _cli.console.print(
        f"Indexed {_search_type_count_label(source)}: {indexed}.",
        markup=False,
        highlight=False,
    )
    requested = str(index_state.get("requested_target_root", "")).strip()
    indexed_target = str(index_state.get("indexed_target_root", "")).strip()
    if not requested or not indexed_target:
        return
    if index_state.get("target_matches") is False and requested != indexed_target:
        _cli.console.print(
            f"Project mismatch: requested {requested}; index is for {indexed_target}.",
            markup=False,
            highlight=False,
        )
        return
    _cli.console.print(
        f"Project: {requested}.",
        markup=False,
        highlight=False,
    )


def _handle_vaultstore_locked_error(
    exc: VaultStoreLockedError, json_mode: bool
) -> NoReturn:
    if json_mode:
        _emit_json_error_and_exit(
            "search",
            "local_store_locked",
            (
                f"The local search index at {exc.db_path} is busy. "
                "This command tried to search the index directly, but another "
                "vaultspec-rag command, the background service, or an automatic "
                "index update is using this workspace. Send the search through "
                "the running service instead, for example with --port 8766."
            ),
            1,
            db_path=str(exc.db_path),
            routing_mode="direct_local_search",
            remediation=[
                "Wait for the other command or update to finish.",
                "vaultspec-rag search ... --port 8766",
                "vaultspec-rag server status",
                "vaultspec-rag server stop",
                "Stop any orphaned Python process that is still using this workspace.",
            ],
        )
    _cli.console.print(
        f"Error: The local search index at {exc.db_path} is busy.\n\n"
        "  This command tried to search the index directly, but another "
        "vaultspec-rag command, the background service, or an automatic index "
        "update is using this workspace.\n\n"
        "  Only one local command can use this index directly at a time. "
        "For concurrent searches, send requests through one running "
        "vaultspec-rag service.\n\n"
        "  Next actions:\n"
        "    1. Wait for the other command or update to finish.\n"
        "    2. Send this search through a running "
        "service on a port, e.g.:\n"
        "         vaultspec-rag search ... --port 8766\n"
        "    3. Check the service:\n"
        "         vaultspec-rag server status\n"
        "    4. Stop the running service:\n"
        "         vaultspec-rag server stop\n"
        "    5. If no vaultspec-rag process is alive, look for an "
        "orphaned Python process using the index and stop it manually.",
        markup=False,
        highlight=False,
    )
    raise typer.Exit(code=1) from exc


def _try_in_process_search(
    target: pathlib.Path,
    query: str,
    search_type: str,
    max_results: int,
    language: str | None,
    path: str | None,
    node_type: str | None,
    function_name: str | None,
    class_name: str | None,
    include_paths: list[str] | None,
    exclude_paths: list[str] | None,
    dedup_locales: bool,
    prefer: str | None,
    doc_type: str | None,
    feature: str | None,
    date: str | None,
    tag: str | None,
    json_mode: bool,
) -> list[SearchResult]:
    import vaultspec_rag

    try:
        status_ctx = (
            contextlib.nullcontext()
            if json_mode
            else _cli.console.status(f"Searching {search_type}...")
        )
        with status_ctx:
            if search_type == "code":
                results = vaultspec_rag.search_codebase(
                    target,
                    query,
                    top_k=max_results,
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
            else:
                results = vaultspec_rag.search_vault(
                    target,
                    query,
                    top_k=max_results,
                    doc_type=doc_type,
                    feature=feature,
                    date=date,
                    tag=tag,
                )
        return results
    except VaultStoreLockedError as exc:
        _handle_vaultstore_locked_error(exc, json_mode)
        return []
    except (ImportError, RuntimeError) as e:
        _handle_gpu_error(e)
        return []


def _validate_and_handle_filters(
    search_type: Literal["vault", "code"],
    language: str | None,
    path: str | None,
    node_type: str | None,
    function_name: str | None,
    class_name: str | None,
    doc_type: str | None,
    feature: str | None,
    date: str | None,
    tag: str | None,
    include_paths: list[str] | None,
    exclude_paths: list[str] | None,
    dedup_locales: bool,
    prefer: str | None,
    json_mode: bool,
) -> None:
    from ..search import (
        InvalidFilterForSearchTypeError,
        InvalidPreferValueError,
        validate_search_filters,
    )

    try:
        validate_search_filters(
            search_type,
            language=language,
            path=path,
            node_type=node_type,
            function_name=function_name,
            class_name=class_name,
            doc_type=doc_type,
            feature=feature,
            date=date,
            tag=tag,
            include_paths=include_paths,
            exclude_paths=exclude_paths,
            dedup_locales=dedup_locales,
            prefer=prefer,
        )
    except InvalidPreferValueError as exc:
        msg = str(exc)
        if json_mode:
            _emit_json_error_and_exit(
                "search",
                "invalid_prefer_value",
                msg,
                2,
                value=exc.prefer_value,
            )
        _cli.console.print(f"Error: {msg}", markup=False, highlight=False)
        raise typer.Exit(code=2) from None
    except InvalidFilterForSearchTypeError as exc:
        msg = str(exc)
        if json_mode:
            _emit_json_error_and_exit(
                "search",
                "invalid_filter_for_search_type",
                msg,
                2,
                filter_kind=exc.filter_kind,
                offending=exc.offending_filters,
            )
        _cli.console.print(f"Error: {msg}", markup=False, highlight=False)
        raise typer.Exit(code=2) from None


def _search_structure_filter(
    structure: str | None,
    node_type: str | None,
    json_mode: bool,
) -> str | None:
    if (
        structure is not None
        and node_type is not None
        and structure.strip() != node_type.strip()
    ):
        message = (
            "--structure and --node-type received different values; use --structure."
        )
        if json_mode:
            _emit_json_error_and_exit("search", "invalid_filter", message, 2)
        _cli.console.print(f"Error: {message}", markup=False, highlight=False)
        raise typer.Exit(code=2)
    return structure if structure is not None else node_type


def _render_in_process_results(
    results: list[SearchResult],
    query: str,
    search_type: str,
    json_mode: bool,
    no_truncate: bool,
    show_scores: bool,
    target: pathlib.Path,
) -> None:
    if json_mode:
        from dataclasses import asdict

        _emit_json(
            True,
            "search",
            data={
                "query": query,
                "search_type": search_type,
                "via": "in-process",
                "results": [asdict(r) for r in results],
            },
        )
        return

    if not results:
        _cli.console.print(
            f"No {search_type} results found for: {query}",
            markup=False,
            highlight=False,
        )
        return

    from dataclasses import asdict

    _display_search_results(
        [asdict(r) for r in results],
        search_type,
        via="in-process",
        no_truncate=no_truncate,
        show_scores=show_scores,
        root=target,
    )


@app.command(
    "search",
    help=(
        "Search project documents or source code. Uses the running service "
        "when available; otherwise runs the search locally."
    ),
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def handle_search(  # noqa: PLR0913 - Typer command signature mirrors CLI options.
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="The search query text.")],
    search_type: Annotated[
        Literal["vault", "code"],
        typer.Option(
            "--type",
            help="Search area: 'vault' for documents or 'code' for source files.",
            show_default=True,
        ),
    ] = "vault",
    max_results: Annotated[
        int,
        typer.Option(
            "--max-results",
            "--limit",
            help=(
                "Maximum number of results to show. Default 10 keeps the "
                "output focused."
            ),
        ),
    ] = 10,
    language: Annotated[
        str | None,
        typer.Option(
            "--language",
            help="Only show code results in this programming language.",
        ),
    ] = None,
    path: Annotated[
        str | None,
        typer.Option(
            "--path",
            help="Only show code results from this exact project-relative path.",
        ),
    ] = None,
    include_paths: Annotated[
        list[str] | None,
        typer.Option(
            "--include-path",
            help=(
                "Only show code results whose project-relative path matches "
                "this glob. Repeat for multiple globs."
            ),
        ),
    ] = None,
    exclude_paths: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-path",
            help=(
                "Hide code results whose project-relative path matches this "
                "glob. Repeat for multiple globs."
            ),
        ),
    ] = None,
    dedup_locales: Annotated[
        bool,
        typer.Option(
            "--dedup-locales",
            help=("Collapse matching locale files into one representative result."),
        ),
    ] = False,
    prefer: Annotated[
        str | None,
        typer.Option(
            "--prefer",
            help=("Prefer one kind of code result: 'prod', 'tests', or 'docs'."),
        ),
    ] = None,
    node_type: Annotated[
        str | None,
        typer.Option(
            "--node-type",
            help="Legacy name for --structure.",
            hidden=True,
        ),
    ] = None,
    structure: Annotated[
        str | None,
        typer.Option(
            "--structure",
            help="Only show code results for this source-code structure.",
        ),
    ] = None,
    function_name: Annotated[
        str | None,
        typer.Option(
            "--function-name",
            help="Only show code results from this function or method.",
        ),
    ] = None,
    class_name: Annotated[
        str | None,
        typer.Option(
            "--class-name",
            help="Only show code results from this class or struct.",
        ),
    ] = None,
    doc_type: Annotated[
        str | None,
        typer.Option(
            "--doc-type",
            help="Only show document results with this type, such as 'adr' or 'plan'.",
        ),
    ] = None,
    feature: Annotated[
        str | None,
        typer.Option(
            "--feature",
            help="Only show document results for this feature tag.",
        ),
    ] = None,
    date: Annotated[
        str | None,
        typer.Option(
            "--date",
            help="Only show document results from this date (yyyy-mm-dd).",
        ),
    ] = None,
    tag: Annotated[
        str | None,
        typer.Option(
            "--tag",
            help="Only show document results with this tag, without '#'.",
        ),
    ] = None,
    show_scores: Annotated[
        bool,
        typer.Option(
            "--scores",
            help="Show numeric relevance scores in human search output.",
        ),
    ] = False,
    port: Annotated[
        int | None,
        typer.Option("--port", help="Use the service running on this port."),
    ] = None,
    allow_fallback: Annotated[
        bool,
        typer.Option(
            "--allow-fallback",
            help=(
                "If the selected service is not reachable, run the search "
                "locally instead of stopping with an error."
            ),
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help=("Show model loading and progress messages during local search."),
        ),
    ] = False,
    json_mode: Annotated[
        bool,
        typer.Option(
            "--json",
            help=("Emit JSON for scripts and automation instead of human text."),
        ),
    ] = False,
    timeout: Annotated[
        float | None,
        typer.Option(
            "--timeout",
            help=(
                "Connection and read timeout budget in seconds "
                "for searches handled by the service (default 300; "
                "override with VAULTSPEC_RAG_SEARCH_TIMEOUT)."
            ),
        ),
    ] = None,
) -> None:
    """Search vault documents or source code."""
    _validate_search_extra_args(ctx)
    if not verbose:
        _cli._suppress_hf_progress()
    state: CLIState = ctx.obj
    target = state.target
    node_type = _search_structure_filter(structure, node_type, json_mode)

    _validate_and_handle_filters(
        search_type=search_type,
        language=language,
        path=path,
        node_type=node_type,
        function_name=function_name,
        class_name=class_name,
        doc_type=doc_type,
        feature=feature,
        date=date,
        tag=tag,
        include_paths=include_paths,
        exclude_paths=exclude_paths,
        dedup_locales=dedup_locales,
        prefer=prefer,
        json_mode=json_mode,
    )

    if port is None:
        port = _default_service_port()
        if port is not None:
            allow_fallback = True

    if port is not None:
        service_results = _try_http_search(
            query,
            search_type,
            max_results,
            port,
            str(target),
            timeout=timeout,
            language=language,
            path=path,
            node_type=node_type,
            function_name=function_name,
            class_name=class_name,
            doc_type=doc_type,
            feature=feature,
            date=date,
            tag=tag,
            include_paths=include_paths,
            exclude_paths=exclude_paths,
            dedup_locales=dedup_locales,
            prefer=prefer,
        )
        if service_results is not None:
            _handle_service_results(
                service_results,
                query,
                search_type,
                json_mode,
                False,
                show_scores,
                target,
            )
            return
        if not allow_fallback:
            _display_port_unreachable_error(
                port,
                command="search",
                json_mode=json_mode,
            )
            raise typer.Exit(code=1)

    results = _try_in_process_search(
        target,
        query,
        search_type,
        max_results,
        language,
        path,
        node_type,
        function_name,
        class_name,
        include_paths,
        exclude_paths,
        dedup_locales,
        prefer,
        doc_type,
        feature,
        date,
        tag,
        json_mode,
    )

    _render_in_process_results(
        results,
        query,
        search_type,
        json_mode,
        False,
        show_scores,
        target,
    )


def _validate_search_extra_args(ctx: typer.Context) -> None:
    """Accept legacy no-op render flags while preserving strict option errors."""
    extras = list(ctx.args)
    if not extras or all(item == "--no-truncate" for item in extras):
        return
    unexpected = " ".join(extras)
    _cli.console.print(
        f"Unexpected search options: {unexpected}", markup=False, highlight=False
    )
    raise typer.Exit(code=2)
