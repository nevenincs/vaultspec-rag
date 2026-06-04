"""``index`` and ``clean`` commands: build or drop index collections."""

from __future__ import annotations

from typing import Annotated, Literal

import typer
from rich.table import Table

import vaultspec_rag.cli as _cli

from ..embeddings import EmbeddingModel
from ..indexer import CodebaseIndexer, VaultIndexer
from ..store import VaultStoreLockedError
from ._app import CLIState, app
from ._core import logger
from ._gpu_errors import _handle_gpu_error
from ._mcp_search import _try_mcp_reindex
from ._render import (
    _display_mcp_error,
    _display_port_unreachable_error,
    _emit_json,
    _emit_json_error_and_exit,
)
from ._service_status import _default_service_port
from ._store import _open_vault_store


@app.command("index")
def handle_index(
    ctx: typer.Context,
    index_type: Annotated[
        Literal["vault", "code", "all"],
        typer.Option(
            "--type",
            help="What to index: 'vault' (docs), 'code' (source), or 'all'.",
            show_default=True,
        ),
    ] = "all",
    model: Annotated[
        str | None,
        typer.Option("--model", help="Override the embedding model name."),
    ] = None,
    rebuild: Annotated[
        bool,
        typer.Option(
            "--rebuild",
            help="Drop the selected index collections before re-indexing.",
        ),
    ] = False,
    port: Annotated[
        int | None,
        typer.Option(
            "--port",
            help="Port of running MCP server (fast path).",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="List files that would be indexed without indexing.",
        ),
    ] = False,
    exclude: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude",
            help="Ad-hoc exclusion pattern (repeatable, gitignore syntax).",
        ),
    ] = None,
    allow_fallback: Annotated[
        bool,
        typer.Option(
            "--allow-fallback",
            help=(
                "When --port is given but the service is unreachable, "
                "silently fall back to in-process indexing. Defaults "
                "off; the CLI hard-fails with remediation instead, to "
                "avoid re-entering the Qdrant lock that the resident "
                "service is meant to own."
            ),
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help="Re-enable HuggingFace tqdm progress bars.",
        ),
    ] = False,
    json_mode: Annotated[
        bool,
        typer.Option(
            "--json",
            help=(
                "Emit one JSON envelope to stdout instead of a Rich "
                "table. Wraps per-source summaries in "
                '{"ok": true, "command": "index", "data": '
                '{"sources": [...]}}. Use this for agent / CI '
                "consumption."
            ),
        ),
    ] = False,
) -> None:
    """Index vault documents and/or codebase chunks.

    When ``--port`` is given, delegates to a running MCP server
    via ``_try_mcp_reindex``. On dead/unreachable port, hard-fails
    with remediation unless ``--allow-fallback`` is set.

    Args:
        ctx: Typer context carrying ``CLIState``.
        index_type: What to index: ``vault``, ``code``, or
            ``all``.
        model: Override the default embedding model name.
        rebuild: Drop the selected index collections before re-indexing.
        port: Port of a running MCP server for fast-path
            delegation.
        dry_run: List files that would be indexed without
            actually indexing.  Codebase only.
        exclude: Ad-hoc exclusion patterns (gitignore syntax,
            repeatable).  Combined with ``.vaultragignore``.
        allow_fallback: Opt in to silent in-process fallback when
            ``--port`` is unreachable.
        verbose: Re-enable HuggingFace tqdm progress bars.

    Raises:
        typer.Exit: On GPU errors, locked index files, or
            unreachable ``--port`` without ``--allow-fallback``.

    """
    if not verbose:
        _cli._suppress_hf_progress()
    state: CLIState = ctx.obj
    target = state.target

    # --dry-run: list codebase files without loading GPU or Qdrant.
    # Must come before --port MCP delegation (D9).
    if dry_run:
        if index_type not in ("code", "all"):
            if json_mode:
                _emit_json_error_and_exit(
                    "index",
                    "dry_run_requires_code",
                    "--dry-run only applies to codebase indexing.",
                    2,
                )
            _cli.console.print(
                "[yellow]--dry-run only applies to codebase indexing.[/]"
            )
            return
        # Bypass __init__ to avoid loading GPU model and Qdrant store;
        # scan_files() only needs root_dir and _extra_excludes.
        c_indexer = CodebaseIndexer.__new__(CodebaseIndexer)
        c_indexer.root_dir = target
        c_indexer._extra_excludes = exclude or []
        files = c_indexer.scan_files()
        if json_mode:
            _emit_json(
                True,
                "index",
                data={
                    "dry_run": True,
                    "count": len(files),
                    "files": [str(f.relative_to(target)) for f in sorted(files)],
                },
            )
            return
        _cli.console.print(f"[bold]{len(files)}[/] files would be indexed:")
        for f in sorted(files):
            _cli.console.print(f"  {f.relative_to(target)}")
        return

    # `--rebuild` is destructive; the `--type all` default would
    # silently destroy both collections. Require an explicit
    # `--type` whenever `--rebuild` is set, but keep bare
    # `vaultspec-rag index` (incremental, idempotent) frictionless.
    if rebuild:
        try:
            param_source = ctx.get_parameter_source("index_type")
            # click 8.3+ / typer 0.26+ may vendor ParameterSource
            # such that neither ``is`` nor ``==`` works across
            # imports; compare by enum ``.name`` which is stable.
            type_is_explicit = getattr(param_source, "name", "") != "DEFAULT"
        except (AttributeError, LookupError) as exc:
            # Defensive fallback — if the click API is unavailable
            # on an exotic typer version, treat default as explicit
            # so we never spuriously block a previously-working flow.
            logger.debug("click ParameterSource probe failed: %s", exc, exc_info=True)
            type_is_explicit = True
        if not type_is_explicit:
            remediation = [
                "vaultspec-rag index --rebuild --type vault",
                "vaultspec-rag index --rebuild --type code",
                "vaultspec-rag index --rebuild --type all",
            ]
            msg = (
                "--rebuild is destructive; pass an explicit --type "
                "(vault|code|all) so the scope is unambiguous. The "
                "previous behaviour silently inherited --type all "
                "from the default and dropped both collections."
            )
            if json_mode:
                _emit_json_error_and_exit(
                    "index",
                    "rebuild_requires_explicit_type",
                    msg,
                    2,
                    remediation=remediation,
                )
            _cli.console.print(f"[red]{msg}[/]")
            for line in remediation:
                _cli.console.print(f"  [cyan]{line}[/]")
            raise typer.Exit(code=2)

    if port is None:
        port = _default_service_port()
        if port is not None:
            # We detected a running service, so enable fallback automatically.
            allow_fallback = True

    if port is not None:
        if exclude and not json_mode:
            _cli.console.print(
                "[yellow]--exclude is ignored when delegating to MCP server.[/]",
            )
        do_vault = index_type in ("vault", "all")
        do_code = index_type in ("code", "all")
        v_data = None
        c_data = None

        if do_vault:
            v_data = _try_mcp_reindex(
                "reindex_vault",
                rebuild,
                port,
                str(target),
            )
        if do_code:
            c_data = _try_mcp_reindex(
                "reindex_codebase",
                rebuild,
                port,
                str(target),
            )

        # Surface structured errors (live service, broken tool) instead
        # of silently relaning. _try_mcp_reindex now returns:
        #   None  -> connection refused (service down)
        #   dict  -> either a successful summary or {"ok": False, ...}
        for label, data in (("vault", v_data), ("codebase", c_data)):
            if isinstance(data, dict) and data.get("ok") is False:
                if not json_mode:
                    _cli.console.print(
                        f"[red]MCP reindex_{label} reported an error; "
                        f"refusing to silently fall back.[/]",
                    )
                _display_mcp_error(data, json_mode=json_mode, command="index")
                raise typer.Exit(code=1)

        if v_data is not None or c_data is not None:
            is_async = False
            for data in (v_data, c_data):
                if isinstance(data, dict) and "job_id" in data:
                    is_async = True

            if is_async:
                if json_mode:
                    _emit_json(
                        True,
                        "index",
                        data={
                            "via": "mcp",
                            "async": True,
                            "vault_job_id": (v_data.get("job_id") if v_data else None),
                            "codebase_job_id": (
                                c_data.get("job_id") if c_data else None
                            ),
                        },
                    )
                    return
                if v_data:
                    _cli.console.print(
                        "Vault re-index job queued on service: "
                        f"[cyan]{v_data.get('job_id')}[/]"
                    )
                if c_data:
                    _cli.console.print(
                        "Codebase re-index job queued on service: "
                        f"[cyan]{c_data.get('job_id')}[/]"
                    )
                _cli.console.print(
                    "Check progress with: [bold]vaultspec-rag server service jobs[/]"
                )
                return

            def _row(label: str, data: dict[str, object]) -> dict[str, object]:
                def _i(key: str) -> int:
                    raw = data.get(key, 0)
                    return int(raw) if isinstance(raw, int | float | str) else 0

                return {
                    "source": label,
                    "added": _i("added"),
                    "updated": _i("updated"),
                    "removed": _i("removed"),
                    "total": _i("total"),
                    "duration_ms": _i("duration_ms"),
                }

            sources: list[dict[str, object]] = []
            if v_data:
                sources.append(_row("vault", v_data))
            if c_data:
                sources.append(_row("codebase", c_data))
            if json_mode:
                _emit_json(
                    True,
                    "index",
                    data={"via": "mcp", "sources": sources},
                )
                return

            table = Table(title="Indexing Summary (via MCP)", show_header=True)
            table.add_column("Source", style="bold")
            table.add_column("Added", style="green", justify="right")
            table.add_column("Updated", style="yellow", justify="right")
            table.add_column("Removed", style="red", justify="right")
            table.add_column("Total", style="cyan", justify="right")
            table.add_column("Time", justify="right")
            for row in sources:
                src_value = row["source"]
                label = src_value.capitalize() if isinstance(src_value, str) else ""
                table.add_row(
                    label,
                    str(row["added"]),
                    str(row["updated"]),
                    str(row["removed"]),
                    str(row["total"]),
                    f"{row['duration_ms']}ms",
                )
            _cli.console.print(table)
            return

        if not allow_fallback:
            _display_port_unreachable_error(
                port,
                command="indexing",
                json_mode=json_mode,
            )
            raise typer.Exit(code=1)
        if not json_mode:
            _cli.console.print(
                "[yellow]MCP server unavailable, falling back to in-process "
                "indexing (--allow-fallback set)...[/]",
            )

    from ..progress import RichProgressReporter

    do_vault = index_type in ("vault", "all")
    do_code = index_type in ("code", "all")
    v_res = None
    c_res = None

    with RichProgressReporter(_cli.console) as reporter:
        reporter.phase_start("resolve workspace", 1)
        reporter.advance(1)
        reporter.phase_end()

        reporter.phase_start("open store", 1)
        store = _open_vault_store(target, json_mode=json_mode, command="index")
        if rebuild:
            # Scope the rebuild to the selected collection. A
            # whole-directory rmtree would destroy both collections
            # even on `--rebuild --type vault`; use the
            # collection-scoped store API instead.
            do_vault = index_type in ("vault", "all")
            do_code = index_type in ("code", "all")
            try:
                if do_vault:
                    store.drop_table()
                    store.ensure_table()
                if do_code:
                    store.drop_code_table()
                    store.ensure_code_table()
            except VaultStoreLockedError as exc:
                if json_mode:
                    _emit_json_error_and_exit(
                        "index",
                        "rebuild_locked",
                        (
                            f"Cannot drop the {index_type} collection — "
                            f"another process holds the lock: {exc}"
                        ),
                        1,
                    )
                _cli.console.print(
                    f"[bold red]Error:[/] Cannot drop the {index_type} "
                    f"collection — another process holds the lock.\n{exc}\n"
                    "Close any other processes using the index and retry.",
                )
                raise typer.Exit(code=1) from None
        reporter.advance(1)
        reporter.phase_end()

        try:
            reporter.phase_start("load embedding model", 1)
            try:
                emb_model = EmbeddingModel(model_name=model)
            except (ImportError, RuntimeError) as e:
                _handle_gpu_error(e)
            reporter.advance(1)
            reporter.phase_end()

            v_indexer = VaultIndexer(target, emb_model, store) if do_vault else None
            c_indexer = (
                CodebaseIndexer(target, emb_model, store, extra_excludes=exclude or [])
                if do_code
                else None
            )

            if do_vault:
                assert v_indexer is not None
                v_res = (
                    v_indexer.full_index(clean=True, reporter=reporter)
                    if rebuild
                    else v_indexer.incremental_index(reporter=reporter)
                )

            if do_code:
                assert c_indexer is not None
                c_res = (
                    c_indexer.full_index(clean=True, reporter=reporter)
                    if rebuild
                    else c_indexer.incremental_index(reporter=reporter)
                )
        finally:
            store.close()

    in_process_sources: list[dict[str, object]] = []
    if v_res is not None:
        in_process_sources.append(
            {
                "source": "vault",
                "added": v_res.added,
                "updated": v_res.updated,
                "removed": v_res.removed,
                "total": v_res.total,
                "duration_ms": v_res.duration_ms,
            }
        )
    if c_res is not None:
        in_process_sources.append(
            {
                "source": "codebase",
                "added": c_res.added,
                "updated": c_res.updated,
                "removed": c_res.removed,
                "total": c_res.total,
                "duration_ms": c_res.duration_ms,
            }
        )

    if json_mode:
        _emit_json(
            True,
            "index",
            data={"via": "in-process", "sources": in_process_sources},
        )
        return

    # Summary table
    table = Table(title="Indexing Summary (via in-process)", show_header=True)
    table.add_column("Source", style="bold")
    table.add_column("Added", style="green", justify="right")
    table.add_column("Updated", style="yellow", justify="right")
    table.add_column("Removed", style="red", justify="right")
    table.add_column("Total", style="cyan", justify="right")
    table.add_column("Time", justify="right")
    for row in in_process_sources:
        src_value = row["source"]
        label = src_value.capitalize() if isinstance(src_value, str) else ""
        table.add_row(
            label,
            str(row["added"]),
            str(row["updated"]),
            str(row["removed"]),
            str(row["total"]),
            f"{row['duration_ms']}ms",
        )
    _cli.console.print(table)


@app.command("clean")
def handle_clean(
    ctx: typer.Context,
    clean_type: Annotated[
        Literal["vault", "code", "all"],
        typer.Argument(
            help=(
                "What to wipe (REQUIRED): 'vault' (docs), 'code' "
                "(source), or 'all'. No default — a destructive "
                "'all' default would be a footgun."
            ),
        ),
    ],
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Confirm the destructive wipe without prompting.",
        ),
    ] = False,
    json_mode: Annotated[
        bool,
        typer.Option(
            "--json",
            help=(
                "Emit one JSON envelope to stdout instead of a Rich "
                "table. Requires --yes (no interactive confirm) so "
                "the JSON stream stays uncorrupted."
            ),
        ),
    ] = False,
) -> None:
    """Drop selected index collections without re-indexing.

    This command does not load embedding models, walk the vault, scan
    the codebase, or touch GPUs. It drops and re-creates the selected
    Qdrant collections and clears the matching metadata sidecar files.
    """
    state: CLIState = ctx.obj
    target = state.target
    if json_mode and not yes:
        _emit_json_error_and_exit(
            "clean",
            "json_requires_yes",
            "--json requires --yes; the interactive confirm would "
            "corrupt the JSON stream on stdin.",
            2,
        )
    if not yes:
        confirmed = typer.confirm(
            f"Delete {clean_type} RAG index data for {target}?",
            default=False,
        )
        if not confirmed:
            _cli.console.print("[yellow]Clean cancelled.[/]")
            raise typer.Exit(code=1)

    from ..config import get_config

    cfg = get_config()
    store = _open_vault_store(target, json_mode=json_mode, command="clean")
    try:
        do_vault = clean_type in ("vault", "all")
        do_code = clean_type in ("code", "all")
        if do_vault:
            store.drop_table()
            store.ensure_table()
        if do_code:
            store.drop_code_table()
            store.ensure_code_table()
    finally:
        store.close()

    data_dir = target / cfg.data_dir
    cleared: list[str] = []
    if clean_type in ("vault", "all"):
        meta = data_dir / cfg.index_metadata_file
        meta.unlink(missing_ok=True)
        cleared.append("Vault")
    if clean_type in ("code", "all"):
        meta = data_dir / cfg.code_index_metadata_file
        meta.unlink(missing_ok=True)
        cleared.append("Codebase")

    if json_mode:
        _emit_json(
            True,
            "clean",
            data={
                "clean_type": clean_type,
                "cleared": [s.lower() for s in cleared],
            },
        )
        return

    table = Table(title="Clean Summary", show_header=True)
    table.add_column("Source", style="bold")
    table.add_column("Status", style="green")
    for source in cleared:
        table.add_row(source, "empty")
    _cli.console.print(table)
