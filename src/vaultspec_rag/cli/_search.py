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
        f"No {search_type} results found for: {query}",
        markup=False,
        highlight=False,
    )
    empty = payload.get("empty")
    if isinstance(empty, dict):
        message = str(empty.get("message", "No matching indexed items found."))
        reason = str(empty.get("reason", "no_match"))
        _cli.console.print(f"Reason: {message} ({reason})", markup=False)
        remediation = empty.get("remediation")
        if isinstance(remediation, list) and remediation:
            _cli.console.print("Next actions:")
            for item in remediation:
                _cli.console.print(f"  - {item}")
    index_state = payload.get("index_state")
    if isinstance(index_state, dict):
        indexed = index_state.get("indexed_count", "?")
        requested = index_state.get("requested_target_root", "?")
        indexed_target = index_state.get("indexed_target_root", "?")
        _cli.console.print(
            f"indexed_count={indexed}; requested_target={requested}; "
            f"indexed_target={indexed_target}",
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
                f"The vault index at {exc.db_path} is currently in "
                "use by another process. Current routing mode: "
                "direct local-store search. Stop the resident "
                "service / RAG service, or route through one running "
                "vaultspec-rag service for concurrent access "
                "(e.g., using --port 8766)."
            ),
            1,
            db_path=str(exc.db_path),
            routing_mode="local",
            remediation=[
                "Wait for the other process to finish.",
                "vaultspec-rag search ... --port 8766",
                "vaultspec-rag server stop",
                "vaultspec-rag server mcp stop",
            ],
        )
    _cli.console.print(
        f"Error: The vault index at {exc.db_path} is currently in use by "
        "another process (routing mode: direct local-store search).\n\n"
        "  Another vaultspec-rag command, RAG service, or file watcher is "
        "likely running against this workspace.\n\n"
        "  Local-file-backed RAG storage cannot be opened by multiple "
        "processes at once. For concurrent agent searches, route every "
        "request through one running vaultspec-rag service.\n\n"
        "  To resolve, do one of the following:\n"
        "    1. Wait for the other process to finish.\n"
        "    2. Route your search request through a running "
        "service on a port, e.g.:\n"
        "         vaultspec-rag search ... --port 8766\n"
        "    3. Stop the running server:\n"
        "         vaultspec-rag server mcp stop\n"
        "         vaultspec-rag server stop\n"
        "    4. If no vaultspec-rag process is alive, look for an "
        "orphaned Python process holding the lock and stop it manually.",
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
        "Search vault documents or source code using hybrid dense+sparse embeddings. "
        "Delegates to a running service when one is detected; falls back to "
        "in-process GPU search otherwise."
    ),
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def handle_search(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="The search query text.")],
    search_type: Annotated[
        Literal["vault", "code"],
        typer.Option(
            "--type",
            help="Search source: 'vault' (docs) or 'code' (source).",
            show_default=True,
        ),
    ] = "vault",
    max_results: Annotated[
        int,
        typer.Option(
            "--max-results",
            help=(
                "Maximum number of results to return. Default 10 "
                "to mitigate top-k crowding by near-duplicate chunks."
            ),
        ),
    ] = 10,
    language: Annotated[
        str | None,
        typer.Option(
            "--language",
            help="Code-search filter: programming language (e.g. 'python').",
        ),
    ] = None,
    path: Annotated[
        str | None,
        typer.Option(
            "--path",
            help=(
                "Code-search filter: exact project-relative file path (KEYWORD match)."
            ),
        ),
    ] = None,
    include_paths: Annotated[
        list[str] | None,
        typer.Option(
            "--include-path",
            help=(
                "Code-search filter: repeatable fnmatch glob; "
                "keep results whose project-relative path matches "
                "at least one pattern. Use with --type code."
            ),
        ),
    ] = None,
    exclude_paths: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-path",
            help=(
                "Code-search filter: repeatable fnmatch glob; "
                "drop results whose project-relative path matches "
                "any pattern. Use with --type code."
            ),
        ),
    ] = None,
    dedup_locales: Annotated[
        bool,
        typer.Option(
            "--dedup-locales",
            help=(
                "Code-search post-process: collapse near-tie locale "
                "variants (e.g. locales/{en,es}.yml) into one canonical "
                "result. Use with --type code."
            ),
        ),
    ] = False,
    prefer: Annotated[
        str | None,
        typer.Option(
            "--prefer",
            help=(
                "Code-search post-process: nudge results matching the "
                "given category up (and others down) after rerank. One "
                "of 'prod', 'tests', 'docs'. Use with --type code."
            ),
        ),
    ] = None,
    node_type: Annotated[
        str | None,
        typer.Option(
            "--node-type",
            help="Code-search filter: AST node type.",
        ),
    ] = None,
    function_name: Annotated[
        str | None,
        typer.Option(
            "--function-name",
            help="Code-search filter: function/method name.",
        ),
    ] = None,
    class_name: Annotated[
        str | None,
        typer.Option(
            "--class-name",
            help="Code-search filter: class/struct name.",
        ),
    ] = None,
    doc_type: Annotated[
        str | None,
        typer.Option(
            "--doc-type",
            help="Vault-search filter: vault doc type (e.g. 'adr', 'plan').",
        ),
    ] = None,
    feature: Annotated[
        str | None,
        typer.Option(
            "--feature",
            help="Vault-search filter: feature tag (kebab-case).",
        ),
    ] = None,
    date: Annotated[
        str | None,
        typer.Option(
            "--date",
            help="Vault-search filter: exact ISO date (yyyy-mm-dd).",
        ),
    ] = None,
    tag: Annotated[
        str | None,
        typer.Option(
            "--tag",
            help="Vault-search filter: free-form tag (without #).",
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
        typer.Option("--port", help="Port of running RAG service (fast path)."),
    ] = None,
    allow_fallback: Annotated[
        bool,
        typer.Option(
            "--allow-fallback",
            help=(
                "When --port is given but the service is unreachable, "
                "silently fall back to in-process search. Defaults off: "
                "the CLI hard-fails with remediation instead, to avoid "
                "re-entering the Qdrant lock that the resident service "
                "is meant to own."
            ),
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help=(
                "Re-enable HuggingFace tqdm progress bars during "
                "in-process model load and encode. Off by default to "
                "keep search output script-friendly."
            ),
        ),
    ] = False,
    json_mode: Annotated[
        bool,
        typer.Option(
            "--json",
            help=(
                "Emit one JSON envelope to stdout instead of text. "
                "Wraps results in "
                '{"ok": true, "command": "search", "data": '
                '{"results": [...]}}; errors use the matching '
                '{"ok": false, "error", "message"} shape. Use this '
                "for agent / CI consumption."
            ),
        ),
    ] = False,
    timeout: Annotated[
        float | None,
        typer.Option(
            "--timeout",
            help=(
                "Connection and read timeout budget in seconds "
                "for service-delegated searches (default 300; "
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
        f"Unexpected search option(s): {unexpected}", markup=False, highlight=False
    )
    raise typer.Exit(code=2)
