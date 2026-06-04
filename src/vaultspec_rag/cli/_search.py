"""``search`` command plus the HuggingFace progress-suppression helper."""

from __future__ import annotations

import contextlib
import os
from typing import Annotated, Literal

import typer
from rich.table import Table

import vaultspec_rag.cli as _cli

from ..embeddings import EmbeddingModel
from ..search import VaultSearcher
from ..store import VaultStoreLockedError
from ._app import CLIState, app
from ._gpu_errors import _handle_gpu_error
from ._mcp_search import _try_mcp_search
from ._render import (
    _display_mcp_error,
    _display_port_unreachable_error,
    _display_search_results,
    _emit_json,
    _emit_json_error_and_exit,
)
from ._service_status import _default_service_port
from ._store import _open_vault_store


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


@app.command("search")
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
                "result. Use with --type code (#121)."
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
                "of 'prod', 'tests', 'docs'. Use with --type code (#122)."
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
            help=("Vault-search filter: vault doc type (e.g. 'adr', 'plan')."),
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
    no_truncate: Annotated[
        bool,
        typer.Option(
            "--no-truncate",
            help=(
                "Disable the 120-character snippet truncation in the "
                "results table so sibling files with long paths stay "
                "distinguishable."
            ),
        ),
    ] = False,
    port: Annotated[
        int | None,
        typer.Option("--port", help="Port of running MCP server (fast path)."),
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
                "Emit one JSON envelope to stdout instead of a Rich "
                "table. Wraps results in "
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
                "for service-delegated searches."
            ),
        ),
    ] = None,
) -> None:
    """Search for relevant context in documentation or code.

    When ``--port`` is given, delegates to a running MCP server.
    On dead/unreachable port, hard-fails with remediation unless
    ``--allow-fallback`` is set.

    Args:
        ctx: Typer context carrying ``CLIState``.
        query: The search query text.
        search_type: Search source: ``vault`` or ``code``.
        max_results: Maximum number of results to return.
        language: Code-search filter for programming language.
        path: Code-search filter for exact project-relative file path.
        include_paths: Repeatable fnmatch globs; results whose
            project-relative path matches at least one pattern are
            kept (post-query filter, code search only).
        exclude_paths: Repeatable fnmatch globs; results whose
            project-relative path matches any pattern are dropped
            (post-query filter, code search only).
        node_type: Code-search filter for AST node type.
        function_name: Code-search filter for function/method name.
        class_name: Code-search filter for class/struct name.
        doc_type: Vault-search filter for vault doc type.
        feature: Vault-search filter for feature tag.
        date: Vault-search filter for exact ISO date.
        tag: Vault-search filter for free-form tag.
        port: Port of a running MCP server for fast-path
            delegation.
        allow_fallback: Opt in to silent in-process fallback when
            ``--port`` is unreachable.
        verbose: Re-enable HuggingFace tqdm progress bars.

    Raises:
        typer.Exit: On GPU initialization errors, filter/search-type
            mismatch, or unreachable ``--port`` without
            ``--allow-fallback``.

    """
    if not verbose:
        _cli._suppress_hf_progress()
    state: CLIState = ctx.obj
    target = state.target

    code_filter_fields = (
        ("language", language),
        ("path", path),
        ("node_type", node_type),
        ("function_name", function_name),
        ("class_name", class_name),
    )
    vault_filter_fields = (
        ("doc_type", doc_type),
        ("feature", feature),
        ("date", date),
        ("tag", tag),
    )
    code_filters_supplied = any(v is not None for _, v in code_filter_fields)
    vault_filters_supplied = any(v is not None for _, v in vault_filter_fields)
    glob_filters_supplied = bool(include_paths) or bool(exclude_paths)
    postproc_supplied = bool(dedup_locales) or prefer is not None

    if prefer is not None and prefer not in {"prod", "tests", "docs"}:
        msg = f"--prefer must be one of 'prod', 'tests', 'docs'; got {prefer!r}."
        if json_mode:
            _emit_json_error_and_exit(
                "search",
                "invalid_prefer_value",
                msg,
                2,
                value=prefer,
            )
        _cli.console.print(f"[red]{msg}[/]")
        raise typer.Exit(code=2)

    def _emit_filter_mismatch(filter_kind: str, offending: list[str]) -> None:
        flag_list = ", ".join(offending)
        msg = (
            f"{filter_kind}-search filters ({flag_list}) require "
            f"--type {filter_kind}; got --type {search_type}."
        )
        if json_mode:
            _emit_json_error_and_exit(
                "search",
                "invalid_filter_for_search_type",
                msg,
                2,
                filter_kind=filter_kind,
                offending=offending,
            )
        _cli.console.print(f"[red]{msg}[/]")
        raise typer.Exit(code=2)

    if code_filters_supplied and search_type != "code":
        _emit_filter_mismatch(
            "code",
            sorted(name for name, value in code_filter_fields if value is not None),
        )
    if vault_filters_supplied and search_type != "vault":
        _emit_filter_mismatch(
            "vault",
            sorted(name for name, value in vault_filter_fields if value is not None),
        )
    if glob_filters_supplied and search_type != "code":
        offending = []
        if include_paths:
            offending.append("--include-path")
        if exclude_paths:
            offending.append("--exclude-path")
        _emit_filter_mismatch("code", offending)
    if postproc_supplied and search_type != "code":
        offending = []
        if dedup_locales:
            offending.append("--dedup-locales")
        if prefer is not None:
            offending.append("--prefer")
        _emit_filter_mismatch("code", offending)

    if port is None:
        port = _default_service_port()
        if port is not None:
            allow_fallback = True

    if port is not None:
        mcp_results = _try_mcp_search(
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
        if mcp_results is not None:
            if isinstance(mcp_results, dict):
                _display_mcp_error(
                    mcp_results,
                    json_mode=json_mode,
                    command="search",
                )
                # Rich path falls through to its own exit; JSON path
                # exited inside _display_mcp_error.
                raise typer.Exit(code=1)
            if json_mode:
                _emit_json(
                    True,
                    "search",
                    data={
                        "query": query,
                        "search_type": search_type,
                        "via": "mcp",
                        "results": list(mcp_results),
                    },
                )
                return
            if not mcp_results:
                _cli.console.print(
                    f"[yellow]No {search_type} results found for:[/] "
                    f"[italic]{query}[/]",
                )
                return
            _display_search_results(
                mcp_results,
                search_type,
                via="mcp",
                no_truncate=no_truncate,
            )
            return
        if not allow_fallback:
            _display_port_unreachable_error(
                port,
                command="search",
                json_mode=json_mode,
            )
            raise typer.Exit(code=1)
        if not json_mode:
            _cli.console.print(
                "[yellow]MCP server unavailable, falling back to in-process "
                "search (--allow-fallback set)...[/]",
            )

    try:
        store = _open_vault_store(
            target,
            json_mode=json_mode,
            command="search",
            raise_on_locked=True,
        )
    except VaultStoreLockedError as exc:
        if json_mode:
            _emit_json_error_and_exit(
                "search",
                "local_store_locked",
                (
                    f"The vault index at {exc.db_path} is currently in "
                    "use by another process. Current routing mode: "
                    "direct local-store search. Stop the resident "
                    "service / MCP server, or route through one running "
                    "vaultspec-rag service for concurrent access "
                    "(e.g., using --port 8766)."
                ),
                1,
                db_path=str(exc.db_path),
                routing_mode="local",
                remediation=[
                    "Wait for the other process to finish.",
                    "vaultspec-rag search ... --port 8766",
                    "vaultspec-rag server service stop",
                    "vaultspec-rag server mcp stop",
                ],
            )
        _cli.console.print(
            f"[bold red]Error:[/] The vault index at [cyan]{exc.db_path}[/] "
            "is currently in use by another process "
            "(routing mode: direct local-store search).\n\n"
            "  Another [cyan]vaultspec-rag[/] command, MCP server, HTTP service, "
            "or file watcher is likely running against this workspace.\n\n"
            "  Local-file-backed RAG storage cannot be opened by multiple "
            "processes at once. For concurrent agent searches, route every "
            "request through one running [cyan]vaultspec-rag[/] service.\n\n"
            "  To resolve, do one of the following:\n"
            "    1. Wait for the other process to finish.\n"
            "    2. Route your search request through a running "
            "service on a port, e.g.:\n"
            "         [cyan]vaultspec-rag search ... --port 8766[/]\n"
            "    3. Stop the running server:\n"
            "         [cyan]vaultspec-rag server mcp stop[/]\n"
            "         [cyan]vaultspec-rag server service stop[/]\n"
            "    4. If no vaultspec-rag process is alive, look for an "
            "orphaned Python process holding the lock and stop it manually."
        )
        raise typer.Exit(code=1) from exc

    try:
        status_ctx = (
            contextlib.nullcontext()
            if json_mode
            else _cli.console.status(f"[bold green]Searching {search_type}...")
        )
        with status_ctx:
            try:
                model = EmbeddingModel()
            except (ImportError, RuntimeError) as e:
                _handle_gpu_error(e)
            searcher = VaultSearcher(target, model, store)

            if search_type == "code":
                results = searcher.search_codebase(
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
                results = searcher.search_vault(
                    query,
                    top_k=max_results,
                    doc_type=doc_type,
                    feature=feature,
                    date=date,
                    tag=tag,
                )
    finally:
        store.close()

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
            f"[yellow]No {search_type} results found for:[/] [italic]{query}[/]",
        )
        return

    table = Table(
        title=f"Search Results: {search_type} (via in-process)",
        box=None,
    )
    table.add_column("Score", justify="right", style="cyan", no_wrap=True)
    table.add_column("Location", style="green")
    table.add_column("Snippet", style="white")

    for r in results:
        snippet_raw = r.snippet.replace("\n", " ")
        snippet = snippet_raw if no_truncate else snippet_raw[:120]
        location = r.path
        if r.line_start:
            location += f":{r.line_start}"
        table.add_row(f"{r.score:.2f}", location, snippet)

    _cli.console.print(table)
