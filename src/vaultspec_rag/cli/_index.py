"""``index`` and ``clean`` commands: build or delete index data."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

if TYPE_CHECKING:
    import pathlib

import typer

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


def _index_route_label(via: str) -> str:
    if via == "service":
        return "running service"
    if via == "in-process":
        return "this command"
    return via.replace("-", " ")


def _index_source_label(source: str) -> str:
    if source == "codebase":
        return "Source code"
    if source == "vault":
        return "Vault"
    return source.replace("_", " ").capitalize()


def _format_index_duration(raw: object) -> str:
    if not isinstance(raw, int | float):
        return "unknown"
    milliseconds = max(0, int(raw))
    if milliseconds < 1000:
        return f"{milliseconds}ms"
    seconds = milliseconds / 1000.0
    if seconds < 10:
        return f"{seconds:.1f}s"
    return f"{seconds:.0f}s"


def _print_index_summary(sources: list[dict[str, object]], *, via: str) -> None:
    _cli.console.print(
        f"Indexing summary: ran in {_index_route_label(via)}.",
        markup=False,
        highlight=False,
    )
    if not sources:
        _cli.console.print("No sources indexed.")
        return
    for row in sources:
        source = str(row.get("source", "unknown"))
        label = _index_source_label(source)
        _cli.console.print(
            f"{label}: added {row.get('added', 0)}; "
            f"updated {row.get('updated', 0)}; "
            f"removed {row.get('removed', 0)}; "
            f"total {row.get('total', 0)}; "
            f"finished in {_format_index_duration(row.get('duration_ms', 0))}",
            markup=False,
            highlight=False,
        )


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
        _cli.console.print("--dry-run only applies to codebase indexing.")
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
    _cli.console.print(f"{len(files)} files would be indexed:")
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
        _cli.console.print(f"Error: {msg}", markup=False, highlight=False)
        for line in remediation:
            _cli.console.print(f"  {line}", markup=False, highlight=False)
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
            "--exclude is ignored when using the running service.",
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
                    f"Reindex {label} reported an error; "
                    "refusing to silently fall back.",
                    markup=False,
                    highlight=False,
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
    v_data: dict[str, object] | None, c_data: dict[str, object] | None, json_mode: bool
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
            f"Vault re-index job queued on service: {v_data.get('job_id')}",
            markup=False,
            highlight=False,
        )
    if c_data:
        _cli.console.print(
            f"Codebase re-index job queued on service: {c_data.get('job_id')}",
            markup=False,
            highlight=False,
        )
    _cli.console.print("Check progress with: vaultspec-rag server jobs")
    return True


def _print_service_results(
    v_data: dict[str, object] | None, c_data: dict[str, object] | None, json_mode: bool
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

    _print_index_summary(sources, via="service")
    return True


@app.command(
    "index",
    help=(
        "Build or update the project documentation and source-code search index. "
        "Uses the running service when available; otherwise runs locally. "
        "See the indexing architecture guide: docs/indexing.md"
    ),
)
def handle_index(
    ctx: typer.Context,
    index_type: Annotated[
        Literal["vault", "code", "all"],
        typer.Option(
            "--type",
            help=(
                "What to index: 'vault' for documents, 'code' for source files, "
                "or 'all'."
            ),
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
            help="Delete the selected index data before rebuilding it.",
        ),
    ] = False,
    port: Annotated[
        int | None,
        typer.Option(
            "--port",
            help="Use the service running on this port.",
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
                "If the selected service is unavailable, build the index "
                "locally instead of stopping with an error."
            ),
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help="Show model loading and indexing progress messages.",
        ),
    ] = False,
    json_mode: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit JSON for scripts instead of human text.",
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
                f"Error: Cannot access the {index_type} collection - "
                f"another process holds the lock.\n{exc}\n"
                "Close any other processes using the index and retry.",
                markup=False,
                highlight=False,
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
                # Preprocess-hook coverage (#185, D11): never let a skipped
                # file be silently absent from the index report.
                "preprocess_skipped": c_res.preprocess_skipped,
                "preprocess_failures": c_res.preprocess_failures,
            }
        )

    if json_mode:
        _emit_json(
            True,
            "index",
            data={"via": "in-process", "sources": in_process_sources},
        )
        return

    _print_index_summary(in_process_sources, via="in-process")


@app.command(
    "clean",
    help=(
        "Delete selected index data without rebuilding it. "
        "Does not load models or use the GPU. "
        "See the indexing architecture guide: docs/indexing.md"
    ),
)
def handle_clean(
    ctx: typer.Context,
    clean_type: Annotated[
        Literal["vault", "code", "all"],
        typer.Argument(
            help=(
                "What to delete: 'vault' for documents, 'code' for source files, "
                "or 'all'. Required so nothing is deleted by accident."
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
                "Emit JSON for scripts instead of human text. Requires --yes "
                "so no prompt interrupts the JSON output."
            ),
        ),
    ] = False,
) -> None:
    """Delete selected index data without rebuilding it."""
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
            _cli.console.print("Clean cancelled.")
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
            "Error: Cannot clean the index - "
            "another process holds the lock.\n"
            f"{exc}\nClose any other processes using the index and retry.",
            markup=False,
            highlight=False,
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

    _cli.console.print("Clean summary")
    for source in cleared:
        _cli.console.print(f"{source}: empty", markup=False, highlight=False)
