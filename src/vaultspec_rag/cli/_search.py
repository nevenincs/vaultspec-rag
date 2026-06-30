"""``search`` command plus the HuggingFace progress-suppression helper."""

from __future__ import annotations

import contextlib
import json
import os
from typing import TYPE_CHECKING, Annotated, Literal, cast

import typer

import vaultspec_rag.cli as _cli

from ..store import VaultStoreLockedError
from ._app import CLIState, app
from ._gpu_errors import _handle_gpu_error
from ._http_search import _get_search_timeout, _try_http_search
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
    from collections.abc import Callable, Generator
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
        show_scores=show_scores,
        root=target,
    )


def _handle_service_success(
    payload: dict[str, object],
    query: str,
    search_type: str,
    json_mode: bool,
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
        empty_map = cast("dict[str, object]", empty)
        message = str(empty_map.get("message", "No matching indexed items found."))
        _cli.console.print(f"Why: {message}", markup=False)
        remediation = empty_map.get("remediation")
    index_state = payload.get("index_state")
    if isinstance(index_state, dict):
        _render_empty_index_state(cast("dict[str, object]", index_state), search_type)
    if isinstance(remediation, list) and remediation:
        remediation_items = cast("list[object]", remediation)
        _cli.console.print("Next actions:")
        for item in remediation_items:
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
            "Project mismatch: requested project differs from indexed project.",
            markup=False,
            highlight=False,
        )
        _cli.console.print(
            f"Requested project: {requested}",
            markup=False,
            highlight=False,
            soft_wrap=True,
        )
        _cli.console.print(
            f"Indexed project: {indexed_target}",
            markup=False,
            highlight=False,
            soft_wrap=True,
        )
        return
    _cli.console.print(
        f"Project: {requested}",
        markup=False,
        highlight=False,
        soft_wrap=True,
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
    dedup_locales: bool | None,
    prefer: str | None,
    doc_type: str | None,
    feature: str | None,
    date: str | None,
    tag: str | None,
    json_mode: bool,
) -> list[SearchResult]:
    import vaultspec_rag

    from ..registry import get_registry

    # An empty or unbuilt index has nothing to search, so skip the
    # "Searching..." status spinner: the search returns an empty, actionable
    # result either way, and the spinner's control codes otherwise leak into
    # non-interactive (captured / piped) output as a spurious first line.
    has_index = (
        get_registry().code_chunk_count(target) > 0
        if search_type == "code"
        else get_registry().vault_doc_count(target) > 0
    )
    try:
        status_ctx = (
            _cli.console.status(f"Searching {search_type}...")
            if has_index and not json_mode
            else contextlib.nullcontext()
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
    search_type: Literal["vault", "docs", "code"],
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
    dedup_locales: bool | None,
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


def _search_prefer_filter(prefer: str | None, *, json_mode: bool = False) -> str | None:
    if prefer is None:
        return None
    values = {
        "production": "prod",
        "tests": "tests",
        "documentation": "docs",
    }
    normalized = prefer.strip().lower()
    if normalized in values:
        return values[normalized]
    msg = (
        f"--prefer must be one of production, tests, or documentation; got {prefer!r}."
    )
    if json_mode:
        _emit_json_error_and_exit(
            "search",
            "invalid_prefer_value",
            msg,
            2,
            value=prefer,
        )
    _cli.console.print(f"Error: {msg}", markup=False, highlight=False)
    raise typer.Exit(code=2)


def _validate_search_type(
    search_type: str, *, json_mode: bool
) -> Literal["vault", "docs", "code"]:
    normalized = search_type.strip().lower()
    if normalized in {"vault", "docs", "code"}:
        return cast("Literal['vault', 'docs', 'code']", normalized)
    msg = f"--type must be docs, vault, or code; got {search_type!r}."
    if json_mode:
        _emit_json_error_and_exit(
            "search",
            "invalid_search_type",
            msg,
            2,
            value=search_type,
        )
    _cli.console.print(f"Error: {msg}", markup=False, highlight=False)
    raise typer.Exit(code=2)


def _canonical_search_type(
    search_type: Literal["vault", "docs", "code"],
) -> Literal["vault", "code"]:
    return "vault" if search_type == "docs" else search_type


def _render_in_process_results(
    results: list[SearchResult],
    query: str,
    search_type: str,
    json_mode: bool,
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
        _render_empty_in_process_results(query, search_type, target)
        return

    from dataclasses import asdict

    _display_search_results(
        [asdict(r) for r in results],
        search_type,
        via="in-process",
        show_scores=show_scores,
        root=target,
    )


def _render_empty_in_process_results(
    query: str,
    search_type: str,
    target: pathlib.Path,
) -> None:
    result_label = _search_type_result_label(search_type)
    count_label = _search_type_count_label(search_type)
    _cli.console.print(
        f"No {result_label} results found for: {query}",
        markup=False,
        highlight=False,
    )
    _cli.console.print(
        f"Why: No matching {count_label} were found in the local index.",
        markup=False,
        highlight=False,
    )
    _cli.console.print(
        f"Project: {target}",
        markup=False,
        highlight=False,
        soft_wrap=True,
    )
    _cli.console.print("Next actions:", markup=False, highlight=False)
    _cli.console.print(
        f"  - vaultspec-rag index --type {search_type}",
        markup=False,
        highlight=False,
    )
    _cli.console.print(
        "  - vaultspec-rag status",
        markup=False,
        highlight=False,
    )


def _local_only_configured() -> bool:
    """Return True when local-only backend mode is explicitly configured.

    Delegates to the canonical config resolver (``VAULTSPEC_RAG_LOCAL_ONLY``
    env, then the persisted ``install --local-only`` marker, then the default),
    so the truthiness parsing is identical to every other consumer of the knob
    and cannot diverge. This is the configured half of the local-search
    mandate: it stands in for an operator who has already opted the whole
    workspace into local mode, so the router need not require
    ``--allow-fallback`` on every call.
    """
    from ..config import get_config

    return bool(get_config().local_only)


def _local_search_mandated(allow_fallback: bool) -> bool:
    """Return True only when the operator has explicitly authorised local search.

    Search is service-first: the in-process local search loads the GPU model
    stack and opens the local index directly, so it runs only under an explicit
    mandate - the per-call ``--allow-fallback`` flag, or the workspace-level
    local-only configuration. Merely discovering a service port does NOT grant
    a mandate; a discovered-but-dead service with no mandate is an error, not a
    silent local degrade.
    """
    return bool(allow_fallback) or _local_only_configured()


def _display_service_down_error(*, json_mode: bool) -> NoReturn:
    """Report that no service is reachable and local search was not mandated."""
    if json_mode:
        _emit_json_error_and_exit(
            "search",
            "service_down",
            (
                "No running vaultspec-rag service was found and local search "
                "was not authorised. Start the service or rerun with "
                "--allow-fallback (one local user only)."
            ),
            1,
            remediation=[
                "vaultspec-rag server status",
                "vaultspec-rag server start",
                "rerun with --allow-fallback (one local user only)",
            ],
        )
    _cli.console.print(
        "No running vaultspec-rag service was found.\n"
        "The CLI will not silently run the search locally because that would "
        "open the local search index directly and block other users.\n"
        "Next actions:\n"
        "  1. Check status:  vaultspec-rag server status\n"
        "  2. Start service: vaultspec-rag server start\n"
        "  3. Or run locally anyway: re-run with "
        "--allow-fallback (one user only).",
        markup=False,
        highlight=False,
    )
    raise typer.Exit(code=1)


def _abort_on_local_deadline(seconds: float, json_mode: bool) -> NoReturn:
    """Stop a wedged local search at the deadline, releasing the index lock.

    Invoked from a watchdog thread, so it must not depend on the main thread
    making progress: it writes a terse timeout envelope to stderr and then
    force-exits the process. Process exit is what releases the OS file lock the
    local store holds, so a hung model load or store open can never strand the
    lock for the next search.
    """
    import sys

    if json_mode:
        payload = {
            "ok": False,
            "command": "search",
            "error": "local_search_timeout",
            "message": (
                f"Local search exceeded the {seconds:g}s deadline and was "
                "stopped to release the local index lock."
            ),
            "timeout_seconds": seconds,
            "remediation": [
                "vaultspec-rag server start",
                "rerun with a longer --timeout",
            ],
        }
        sys.stderr.write(json.dumps(payload) + "\n")
    else:
        sys.stderr.write(
            f"Local search exceeded the {seconds:g}s deadline and was stopped "
            "to release the local index lock.\n"
            "Next actions:\n"
            "  1. Start the service: vaultspec-rag server start\n"
            "  2. Or rerun with a longer --timeout.\n"
        )
    sys.stderr.flush()
    # Hard stop from a watchdog thread: only process exit reliably frees the
    # OS file lock the local store holds. A normal exit cannot interrupt a
    # wedged model load or store open on the main thread.
    os._exit(124)


@contextlib.contextmanager
def _local_search_deadline(
    seconds: float | None,
    *,
    json_mode: bool,
    on_timeout: Callable[[], object] | None = None,
) -> Generator[None]:
    """Bound a mandated local search by a wall-clock deadline.

    A daemon timer fires ``on_timeout`` (default: write a timeout envelope and
    force-exit) if the body has not finished within ``seconds``. The timer is
    cancelled on normal completion. ``on_timeout`` is an injectable seam so the
    timer mechanism is testable without the default's process exit.
    """
    import threading

    if seconds is None or seconds <= 0:
        yield
        return

    def _default_timeout() -> None:
        _abort_on_local_deadline(float(seconds), json_mode)

    timer = threading.Timer(float(seconds), on_timeout or _default_timeout)
    timer.daemon = True
    timer.start()
    try:
        yield
    finally:
        timer.cancel()


@app.command(
    "search",
    help=(
        "Search project documents or source code. Uses the running service "
        "when available. Local search runs only with an explicit mandate "
        "(--allow-fallback or configured local-only mode)."
    ),
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def handle_search(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="The search query text.")],
    search_type: Annotated[
        str,
        typer.Option(
            "--type",
            metavar="docs|vault|code",
            help=(
                "Search area: 'docs' or 'vault' for documents; 'code' for source files."
            ),
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
        bool | None,
        typer.Option(
            "--dedup-locales/--no-dedup-locales",
            help=(
                "Collapse matching locale files into one representative result. "
                "Defaults to the configured value (on) when not specified."
            ),
        ),
    ] = None,
    prefer: Annotated[
        str | None,
        typer.Option(
            "--prefer",
            help=(
                "Prefer one kind of code result: production, tests, or documentation."
            ),
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
                "for searches handled by the service (default 300 seconds; "
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
    prefer = _search_prefer_filter(prefer, json_mode=json_mode)
    search_type = _validate_search_type(search_type, json_mode=json_mode)

    _validate_and_handle_filters(
        search_type=search_type,
        language=language,
        path=path,
        node_type=structure,
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
    search_type = _canonical_search_type(search_type)

    # Search is service-first: local execution requires an explicit mandate
    # (--allow-fallback or configured local-only mode). Discovering a service
    # port does NOT grant a mandate, so a discovered-but-dead service degrades
    # to a clear error rather than a silent, unbounded local run.
    mandate = _local_search_mandated(allow_fallback)

    if port is None:
        port = _default_service_port()

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
            node_type=structure,
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
                show_scores,
                target,
            )
            return
        if not mandate:
            _display_port_unreachable_error(
                port,
                command="search",
                json_mode=json_mode,
            )
            raise typer.Exit(code=1)
    elif not mandate:
        _display_service_down_error(json_mode=json_mode)

    # A local mandate is present; run the in-process search under a wall-clock
    # deadline so a degraded local store or wedged model load cannot hang while
    # holding the index lock.
    deadline = _get_search_timeout(timeout)
    with _local_search_deadline(deadline, json_mode=json_mode):
        try:
            results = _try_in_process_search(
                target,
                query,
                search_type,
                max_results,
                language,
                path,
                structure,
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
                show_scores,
                target,
            )
        finally:
            from ..registry import get_registry

            get_registry().close_project(target)


def _validate_search_extra_args(ctx: typer.Context) -> None:
    extras = list(ctx.args)
    if not extras:
        return
    unexpected = " ".join(extras)
    _cli.console.print(
        f"Unexpected search options: {unexpected}", markup=False, highlight=False
    )
    raise typer.Exit(code=2)
