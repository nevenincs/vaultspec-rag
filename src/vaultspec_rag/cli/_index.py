"""``index`` and ``clean`` commands: build or drop index collections."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

if TYPE_CHECKING:
    import pathlib

import typer
from rich.table import Table

import vaultspec_rag.cli as _cli

from ..store import VaultStoreLockedError
from ._app import CLIState, app
from ._core import logger
from ._gpu_errors import _handle_gpu_error
from ._http_search import _try_http_reindex
from ._render import (
    _display_port_unreachable_error,
    _display_service_error,
    _emit_json,
    _emit_json_error_and_exit,
)
from ._service_status import _default_service_port


def _handle_dry_run(
    index_type: str, json_mode: bool, target: pathlib.Path, exclude: list[str] | None
) -> None:
    if index_type not in ("code", "all"):
        if json_mode:
            _emit_json_error_and_exit(
                "index",
                "dry_run_requires_code",
                "--dry-run only applies to codebase indexing.",
                2,
            )
        _cli.console.print("[yellow]--dry-run only applies to codebase indexing.[/]")
        raise typer.Exit(code=2)
    import vaultspec_rag

    files = vaultspec_rag.scan_codebase_files(target, extra_excludes=exclude)
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


def _validate_rebuild(ctx: typer.Context, json_mode: bool) -> None:
    try:
        param_source = ctx.get_parameter_source("index_type")
        type_is_explicit = getattr(param_source, "name", "") != "DEFAULT"
    except (AttributeError, LookupError) as exc:
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


def _try_service_delegation(
    port: int,
    exclude: list[str] | None,
    json_mode: bool,
    index_type: str,
    rebuild: bool,
    target: pathlib.Path,
    allow_fallback: bool,
) -> bool:
    if exclude and not json_mode:
        _cli.console.print(
            "[yellow]--exclude is ignored when delegating to the RAG service.[/]",
        )
    do_vault = index_type in ("vault", "all")
    do_code = index_type in ("code", "all")
    v_data = None
    c_data = None

    if do_vault:
        v_data = _try_http_reindex(
            "reindex_vault",
            rebuild,
            port,
            str(target),
        )
    if do_code:
        c_data = _try_http_reindex(
            "reindex_codebase",
            rebuild,
            port,
            str(target),
        )

    for label, data in (("vault", v_data), ("codebase", c_data)):
        if isinstance(data, dict) and data.get("ok") is False:
            if not json_mode:
                _cli.console.print(
                    f"[red]Reindex {label} reported an error; "
                    f"refusing to silently fall back.[/]",
                )
            _display_service_error(data, json_mode=json_mode, command="index")
            raise typer.Exit(code=1)

    if v_data is not None or c_data is not None:
        return _print_service_results(v_data, c_data, json_mode)

    if not allow_fallback:
        _display_port_unreachable_error(
            port,
            command="indexing",
            json_mode=json_mode,
        )
        raise typer.Exit(code=1)

    return False


def _print_service_async_results(
    v_data: dict | None, c_data: dict | None, json_mode: bool
) -> bool:
    if json_mode:
        _emit_json(
            True,
            "index",
            data={
                "via": "service",
                "async": True,
                "vault_job_id": (v_data.get("job_id") if v_data else None),
                "codebase_job_id": (c_data.get("job_id") if c_data else None),
            },
        )
        return True
    if v_data:
        _cli.console.print(
            f"Vault re-index job queued on service: [cyan]{v_data.get('job_id')}[/]"
        )
    if c_data:
        _cli.console.print(
            f"Codebase re-index job queued on service: [cyan]{c_data.get('job_id')}[/]"
        )
    _cli.console.print("Check progress with: [bold]vaultspec-rag server jobs[/]")
    return True


def _print_service_results(
    v_data: dict | None, c_data: dict | None, json_mode: bool
) -> bool:
    is_async = False
    for data in (v_data, c_data):
        if isinstance(data, dict) and "job_id" in data:
            is_async = True

    if is_async:
        return _print_service_async_results(v_data, c_data, json_mode)

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
            data={"via": "service", "sources": sources},
        )
        return True

    table = Table(title="Indexing Summary", show_header=True)
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
    return True


@app.command(
    "index",
    help=(
        "Build or update the vault and/or codebase search index. "
        "Delegates to a running service when one is detected; falls back to "
        "in-process GPU indexing otherwise. "
        "See the indexing architecture guide: docs/indexing.md"
    ),
)
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
            help="Port of running RAG service (fast path).",
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
    """Index vault documents and/or codebase chunks."""
    if not verbose:
        _cli._suppress_hf_progress()
    state: CLIState = ctx.obj
    target = state.target

    if dry_run:
        _handle_dry_run(index_type, json_mode, target, exclude)
        return

    if rebuild:
        _validate_rebuild(ctx, json_mode)

    if port is None:
        port = _default_service_port()
        if port is not None:
            # We detected a running service, so enable fallback automatically.
            allow_fallback = True

    if port is not None and _try_service_delegation(
        port, exclude, json_mode, index_type, rebuild, target, allow_fallback
    ):
        return

    _try_in_process_indexing(index_type, rebuild, model, exclude, target, json_mode)


def _try_in_process_indexing(
    index_type: str,
    rebuild: bool,
    model: str | None,
    exclude: list[str] | None,
    target: pathlib.Path,
    json_mode: bool,
) -> None:
    import vaultspec_rag

    from ..progress import RichProgressReporter

    do_vault = index_type in ("vault", "all")
    do_code = index_type in ("code", "all")
    v_res = None
    c_res = None

    with RichProgressReporter(_cli.console) as reporter:
        reporter.phase_start("resolve workspace", 1)
        reporter.advance(1)
        reporter.phase_end()

        try:
            if do_vault:
                v_res = vaultspec_rag.index(
                    target,
                    clean=rebuild,
                    reporter=reporter,
                    model_name=model,
                )

            if do_code:
                c_res = vaultspec_rag.index_codebase(
                    target,
                    clean=rebuild,
                    reporter=reporter,
                    model_name=model,
                    extra_excludes=exclude,
                )
        except VaultStoreLockedError as exc:
            if json_mode:
                _emit_json_error_and_exit(
                    "index",
                    "rebuild_locked" if rebuild else "index_locked",
                    (
                        f"Cannot access the {index_type} collection - "
                        f"another process holds the lock: {exc}"
                    ),
                    1,
                )
            _cli.console.print(
                f"[bold red]Error:[/] Cannot access the {index_type} "
                f"collection - another process holds the lock.\n{exc}\n"
                "Close any other processes using the index and retry.",
            )
            raise typer.Exit(code=1) from None
        except (ImportError, RuntimeError) as e:
            _handle_gpu_error(e)

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
    table = Table(title="Indexing Summary", show_header=True)
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


@app.command(
    "clean",
    help=(
        "Drop selected index collections without re-indexing. "
        "Does not load models or touch the GPU — only clears Qdrant collections "
        "and metadata sidecars. "
        "See the indexing architecture guide: docs/indexing.md"
    ),
)
def handle_clean(
    ctx: typer.Context,
    clean_type: Annotated[
        Literal["vault", "code", "all"],
        typer.Argument(
            help=(
                "What to wipe (REQUIRED): 'vault' (docs), 'code' "
                "(source), or 'all'. No default - a destructive "
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
    """Drop selected index collections without re-indexing."""
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

    import vaultspec_rag

    try:
        cleared_raw = vaultspec_rag.clean(target, clean_type=clean_type)
    except VaultStoreLockedError as exc:
        if json_mode:
            _emit_json_error_and_exit(
                "clean",
                "clean_locked",
                f"Cannot clean the index - another process holds the lock: {exc}",
                1,
            )
        _cli.console.print(
            "[bold red]Error:[/] Cannot clean the index - "
            "another process holds the lock.\n"
            f"{exc}\nClose any other processes using the index and retry."
        )
        raise typer.Exit(code=1) from None

    cleared = [s.capitalize() for s in cleared_raw]

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
