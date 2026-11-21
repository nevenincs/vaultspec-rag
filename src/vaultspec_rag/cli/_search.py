"""``search`` command plus the HuggingFace progress-suppression helper."""

from __future__ import annotations

import contextlib
import json
import math
import os
from dataclasses import replace
from typing import TYPE_CHECKING, Annotated

import typer

from .._operator_commands import (
    server_start_command,
    server_status_command,
)
from ..config._types import EnvVar
from ..serviceclient._compat import resolve_data_plane_service
from ..serviceclient._search_transport import (
    get_search_timeout,
    try_http_search,
)
from ..serviceclient._transport import DocumentSearchFilters
from ._app import (
    CLIState,
    JsonMode,
    PortOption,
    app,
)
from ._gpu_errors import (
    refuse_beside_a_service_of_another_release,
    refuse_if_gpu_owned,
)
from ._render import (
    _display_port_unreachable_error,
    _display_service_version_error,
    _emit_json_error_and_exit,
    _plain,
    exit_with_error,
)
from ._search_filters import (
    metadata_filters_option,
    search_prefer_filter,
    validate_search_type,
)
from ._search_in_process import (
    InProcessRenderRequest,
    InProcessSearchRequest,
    render_in_process_results,
    try_in_process_search,
    validate_and_handle_filters,
)
from ._search_results_render import (
    FILTER_ADVISORY,
    ServiceSearchRenderRequest,
    handle_service_results,
    muted_line,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from typing import NoReturn

__all__ = ["_suppress_hf_progress", "handle_search"]


def _suppress_hf_progress() -> None:
    """Silence HuggingFace and sentence-transformers tqdm bars.

    The CLI's in-process path loads SentenceTransformer + SparseEncoder
    + CrossEncoder; their default tqdm output pollutes stdout. Set
    before model construction so the env reaches every downstream
    import.
    """
    os.environ.setdefault(EnvVar.HF_HUB_DISABLE_PROGRESS_BARS.value, "1")
    os.environ.setdefault(EnvVar.TRANSFORMERS_NO_ADVISORY_WARNINGS.value, "1")
    os.environ.setdefault(EnvVar.TRANSFORMERS_VERBOSITY.value, "error")


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
    from ..config._settings import get_config

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


def _validate_freshness_options(
    policy: str,
    wait_seconds: float | None,
    *,
    json_mode: bool,
) -> tuple[str, float | None]:
    """Validate the CLI spelling of the service-owned freshness policy."""
    if policy not in {"immediate", "bounded"}:
        code = "invalid_freshness_policy"
        message = "freshness_policy must be 'immediate' or 'bounded'"
    elif policy == "immediate" and wait_seconds is not None:
        code = "invalid_freshness_wait_seconds"
        message = "freshness_wait_seconds requires freshness_policy 'bounded'"
    elif policy == "immediate":
        return policy, None
    else:
        from ..config._settings import get_config

        maximum = float(get_config().search_freshness_wait_max_seconds)
        if (
            wait_seconds is None
            or not math.isfinite(wait_seconds)
            or wait_seconds < 0
            or wait_seconds > maximum
        ):
            code = "invalid_freshness_wait_seconds"
            message = (
                "freshness_wait_seconds must be a finite number between 0 and "
                f"{maximum:g}"
            )
        else:
            return policy, wait_seconds
    if json_mode:
        _emit_json_error_and_exit("search", code, message, 2)
    _plain(f"Error: {message}")
    raise typer.Exit(code=2)


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
                server_status_command(),
                server_start_command(),
                "rerun with --allow-fallback (one local user only)",
            ],
        )
    _plain(
        "No running vaultspec-rag service was found.\n"
        "The CLI will not silently run the search locally because that would "
        "open the local search index directly and block other users.\n"
        "Next actions:\n"
        f"  1. Check status:  {server_status_command()}\n"
        f"  2. Start service: {server_start_command()}\n"
        "  3. Or run locally anyway: re-run with "
        "--allow-fallback (one user only)."
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
                server_start_command(),
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
) -> Generator[None]:
    """Bound a mandated local search by a wall-clock deadline.

    A daemon timer writes a timeout envelope and force-exits the process if the
    body has not finished within ``seconds``. The timer is cancelled on normal
    completion.
    """
    import threading

    if seconds is None or seconds <= 0:
        yield
        return

    def _on_timeout() -> None:
        _abort_on_local_deadline(float(seconds), json_mode)

    timer = threading.Timer(float(seconds), _on_timeout)
    timer.daemon = True
    timer.start()
    try:
        yield
    finally:
        timer.cancel()


@app.command(
    "search",
    help=(
        "Search ADRs and source code by meaning by default.\n"
        "\n"
        "Uses the running service when available. Local search runs only "
        "with an explicit mandate (--allow-fallback or configured "
        "local-only mode).\n"
        "\n"
        "\b\n"
        "Query markers - write them anywhere in the query text:\n"
        "  documents  type:adr feature:rag date:2026-07 tag:research\n"
        "  code       lang:python path:src/ func:encode class:Searcher\n"
        "             nodetype:function_definition\n"
        "  noise      only:prod exclude:tests,docs include:locale\n"
        "  ranking    status:active intent:debugging\n"
        "\n"
        "\b\n"
        "  domains    prod tests docs locale generated vendored worktree\n"
        "  status     all | active | accepted,proposed,superseded,...\n"
        "  intent     orientation (default) | debugging\n"
        "\n"
        "only:/exclude:/include:, status:, and intent: are marker-only - "
        "they have no --flag equivalent. Comma-separated sets accumulate "
        "when repeated.\n"
        "\n"
        "path: is the in-query spelling of --include-path: it takes a path "
        "pattern, where a plain one matches that path and everything under "
        "it. --path is the different, exact-path filter.\n"
        "\n"
        "\b\n"
        "Examples:\n"
        '  vaultspec-rag search "auth token validation only:prod" --type code\n'
        '  vaultspec-rag search "fixture helpers exclude:tests" --type code\n'
        '  vaultspec-rag search "encode batch lang:python func:encode" --type code\n'
        '  vaultspec-rag search "gpu lock decision type:adr status:active"\n'
    ),
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def handle_search(  # noqa: PLR0913 - Typer exposes each supported filter explicitly.
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="The search query text.")],
    search_type: Annotated[
        str,
        typer.Option(
            "--type",
            metavar="vault|code|document|combined",
            help=(
                "Search area: vault documentation, source code, extracted documents, "
                "or all three with explicit combined. Without --type: ADRs and code. "
                "Aliases: docs, codebase, all."
            ),
            show_default=True,
        ),
    ] = "combined",
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
            help=(
                "Only show code results from this one exact "
                "project-relative path. Use --include-path to select a "
                "subtree or a glob."
            ),
        ),
    ] = None,
    include_paths: Annotated[
        list[str] | None,
        typer.Option(
            "--include-path",
            help=(
                "Only show code results whose project-relative path matches "
                "this pattern. A plain pattern matches that path and "
                "everything under it; globs are accepted. Repeatable."
            ),
        ),
    ] = None,
    exclude_paths: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-path",
            help=(
                "Hide code results whose project-relative path matches this "
                "pattern. A plain pattern matches that path and everything "
                "under it; globs are accepted. Repeatable."
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
    source_path: Annotated[
        str | None,
        typer.Option(
            "--source-path",
            help="Only show extracted-document results from this source path.",
        ),
    ] = None,
    extractor_id: Annotated[
        str | None,
        typer.Option(
            "--extractor-id",
            help=(
                "Only show document results emitted by this extractor. A "
                "comma-separated list matches any of them."
            ),
        ),
    ] = None,
    extractor_prefix: Annotated[
        str | None,
        typer.Option(
            "--extractor-prefix",
            help=(
                "Only show document results from extractors in this dotted "
                "family: a.b matches a.b and a.b.c, not a.bc. A "
                "comma-separated list matches any of them."
            ),
        ),
    ] = None,
    meta: Annotated[
        list[str] | None,
        typer.Option(
            "--meta",
            metavar="KEY=VALUE[,VALUE]",
            help=(
                "Only show document results whose declared metadata key holds "
                "any of these values. Repeatable; different keys must all "
                "match."
            ),
        ),
    ] = None,
    extractor_version: Annotated[
        str | None,
        typer.Option(
            "--extractor-version",
            help="Only show document results from this extractor version.",
        ),
    ] = None,
    locator_kind: Annotated[
        str | None,
        typer.Option(
            "--locator-kind",
            help=(
                "Only show document results with this locator kind. A "
                "comma-separated list matches any of them."
            ),
        ),
    ] = None,
    show_scores: Annotated[
        bool,
        typer.Option(
            "--scores",
            help="Show numeric relevance scores in human search output.",
        ),
    ] = False,
    port: PortOption = None,
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
    json_mode: JsonMode = False,
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
    freshness_policy: Annotated[
        str,
        typer.Option(
            "--freshness-policy",
            metavar="immediate|bounded",
            help="Return immediately or wait within a bounded publication window.",
            show_default=True,
        ),
    ] = "immediate",
    freshness_wait_seconds: Annotated[
        float | None,
        typer.Option(
            "--freshness-wait-seconds",
            help=(
                "Publication wait bound in seconds; requires "
                "--freshness-policy bounded."
            ),
        ),
    ] = None,
) -> None:
    """Search vault documents or source code."""
    _validate_search_extra_args(ctx)
    if not verbose:
        _suppress_hf_progress()
    state: CLIState = ctx.obj
    target = state.target
    freshness_policy, freshness_wait_seconds = _validate_freshness_options(
        freshness_policy,
        freshness_wait_seconds,
        json_mode=json_mode,
    )
    prefer = search_prefer_filter(prefer, json_mode=json_mode)
    parameter_source = ctx.get_parameter_source("search_type")
    include_documents = parameter_source is None or parameter_source.name != "DEFAULT"
    search_type = validate_search_type(search_type, json_mode=json_mode)
    metadata_filters = metadata_filters_option(meta, json_mode=json_mode)
    local_request = InProcessSearchRequest(
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
        source_path,
        extractor_id,
        extractor_version,
        locator_kind,
        json_mode,
        include_documents=include_documents,
        extractor_prefix=extractor_prefix,
        metadata_filters=metadata_filters,
    )
    validate_and_handle_filters(local_request)
    if not json_mode:
        muted_line(FILTER_ADVISORY)

    # Search is service-first: local execution requires an explicit mandate
    # (--allow-fallback or configured local-only mode). Discovering a service
    # port does NOT grant a mandate, so a discovered-but-dead service degrades
    # to a clear error rather than a silent, unbounded local run.
    mandate = _local_search_mandated(allow_fallback)

    if port is None:
        service = resolve_data_plane_service()
        if service.reachable and not service.version.is_compatible:
            # A discovered daemon of another release cannot answer this search
            # faithfully - it drops filter fields it does not know rather than
            # rejecting them - so without a mandate the release is the refusal.
            # With one, the release is no longer what blocks: that daemon holds
            # this machine whatever it speaks, and running in-process beside it
            # would load a second model stack.
            if mandate:
                refuse_beside_a_service_of_another_release(
                    command="search", json_mode=json_mode
                )
            _display_service_version_error(
                service.version,
                command="search",
                json_mode=json_mode,
            )
            raise typer.Exit(code=1)
        port = service.port

    if port is not None:
        service_results = try_http_search(
            query,
            search_type.value,
            max_results,
            port,
            str(target),
            timeout=timeout,
            include_documents=include_documents,
            freshness_policy=freshness_policy,
            freshness_wait_seconds=freshness_wait_seconds,
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
            document_filters=DocumentSearchFilters(
                source_path=source_path,
                extractor_id=extractor_id,
                extractor_version=extractor_version,
                locator_kind=locator_kind,
                extractor_prefix=extractor_prefix,
                metadata_filters=metadata_filters,
            ),
        )
        if service_results is not None:
            handle_service_results(
                service_results,
                ServiceSearchRenderRequest(
                    query,
                    search_type.value,
                    json_mode,
                    show_scores,
                    target,
                ),
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

    if freshness_policy == "bounded":
        # The wait policy is service-owned; local execution cannot honour it.
        exit_with_error(
            "search",
            "bounded_freshness_requires_service",
            "Bounded freshness requires a running service; local search has no "
            "publication-wait authority.",
            2,
            json_mode=json_mode,
        )

    refuse_if_gpu_owned(command="search", json_mode=json_mode)

    # A local mandate is present; run the in-process search under a wall-clock
    # deadline so a degraded local store or wedged model load cannot hang while
    # holding the index lock.
    deadline = get_search_timeout(timeout)
    with _local_search_deadline(deadline, json_mode=json_mode):
        envelope: dict[str, object] = {}
        try:
            results = try_in_process_search(replace(local_request, envelope=envelope))

            render_in_process_results(
                InProcessRenderRequest(
                    results,
                    query,
                    search_type,
                    json_mode,
                    show_scores,
                    target,
                    envelope,
                )
            )
        finally:
            from ..registry import get_registry

            get_registry().close_project(target)


def _validate_search_extra_args(ctx: typer.Context) -> None:
    extras = list(ctx.args)
    if not extras:
        return
    unexpected = " ".join(extras)
    _plain(f"Unexpected search options: {unexpected}")
    raise typer.Exit(code=2)
