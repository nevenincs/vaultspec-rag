"""``index`` and ``clean`` commands: build or delete index data."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Annotated, Any, NamedTuple, cast

if TYPE_CHECKING:
    import pathlib
    from contextlib import AbstractContextManager

    from .._public_index import DocumentScanResult
    from ..api import AllIndexOutcomes
    from ..indexer import IndexResult
    from ..indexer._content_discovery import (
        AdmissionCount,
        AdmissionSample,
        ContentScanResult,
    )
    from ..progress import ProgressReporter

import typer

import vaultspec_rag.cli as _cli

from .._operator_commands import (
    IndexCommandOptions,
    index_command,
    index_source_option,
    server_status_command,
)
from .._source_types import (
    INDEX_SOURCES,
    PublicSourceType,
    SourceTypeParseError,
    parse_source_type,
)
from .._store_locks import VaultStoreLockedError
from .._store_writes import InsufficientDiskSpaceError
from ..config import EnvVar
from ..serviceclient._compat import resolve_data_plane_service
from ..serviceclient._transport import _try_http_reindex
from ._app import (
    JSON_OPTION_HELP,
    CLIState,
    JsonMode,
    PortOption,
    app,
)
from ._cli_format import _counted_unit
from ._core import logger
from ._gpu_errors import _handle_gpu_error
from ._render import (
    _display_port_unreachable_error,
    _display_service_error,
    _display_service_version_error,
    _emit_json,
    _emit_json_error_and_exit,
    _format_local_index_busy_message,
    _plain,
)
from ._search import _suppress_hf_progress


def _warn_preprocess_flag_ignored_when_delegating(json_mode: bool) -> None:
    """Warn loudly that --no-preprocess does not apply to a delegated run.

    The flag only shapes an in-process run: when the CLI delegates to a
    running service, that service preprocesses under the mode it was started
    with and cannot be overridden per request. The run still proceeds, so this
    warns loudly rather than silently accepting a flag it cannot honour.
    Emitted through the logger (so it survives ``--json`` on stderr) and,
    in human mode, printed as a visible ``Warning:`` line.
    """
    message = (
        "--no-preprocess does not apply to a delegated index run: the running "
        "service preprocesses under the mode it was started with, and this run "
        "uses that mode. Start the service with --no-preprocess to change it."
    )
    logger.warning("%s", message)
    if not json_mode:
        _plain(f"Warning: {message}")


def _apply_preprocess_off_env() -> None:
    """Set the preprocess kill-switch env for the in-process run about to begin.

    The ``preprocess_mode`` config property reads the env var live, so setting
    it here (before indexing) takes effect without a config rebuild.
    """
    os.environ[EnvVar.PREPROCESS.value] = "off"


def _index_route_label(via: str) -> str:
    if via == "service":
        return "running service"
    if via == "in-process":
        return "this command"
    return via.replace("-", " ")


def _index_source_label(source: str) -> str:
    if source in {"code", "codebase"}:
        return "Source code"
    if source == "vault":
        return "Vault"
    if source == "document":
        return "Documents"
    if source == "not_reported":
        return "Index source not reported"
    return source.replace("_", " ").capitalize()


def _parse_index_source(
    value: object,
    *,
    command: str,
    json_mode: bool,
) -> PublicSourceType:
    """Parse a CLI source selection while retaining explicit legacy aliases."""
    try:
        return parse_source_type(value, allow_aliases=True)
    except SourceTypeParseError as exc:
        if json_mode:
            _emit_json_error_and_exit(
                command,
                exc.error_kind,
                str(exc),
                2,
                **exc.as_payload(),
            )
        _plain(f"Error: {exc}")
        raise typer.Exit(code=2) from None


def _format_index_duration(raw: object) -> str:
    if isinstance(raw, int | float):
        raw_milliseconds = float(raw)
    elif isinstance(raw, str):
        try:
            raw_milliseconds = float(raw)
        except ValueError:
            return "not reported"
    else:
        return "not reported"
    try:
        milliseconds = max(0, int(raw_milliseconds))
    except (OverflowError, ValueError):
        return "not reported"
    if milliseconds < 1000:
        return _counted_unit(milliseconds, "millisecond")
    seconds = milliseconds / 1000.0
    if seconds < 10:
        if seconds.is_integer():
            return _counted_unit(int(seconds), "second")
        return f"{seconds:.1f} seconds"
    return _counted_unit(round(seconds), "second")


def _print_index_summary(sources: list[dict[str, object]], *, via: str) -> None:
    _plain(f"Indexing summary: ran in {_index_route_label(via)}.")
    if not sources:
        _cli.console.print("No sources indexed.")
        return
    for row in sources:
        source = str(row.get("source") or "not_reported")
        label = _index_source_label(source)
        duration = _format_index_duration(row.get("duration_ms"))
        duration_text = (
            f"finished in {duration}"
            if duration != "not reported"
            else "duration not reported"
        )
        _plain(
            f"{label}: added {row.get('added', 0)}; "
            f"updated {row.get('updated', 0)}; "
            f"removed {row.get('removed', 0)}; "
            f"total {row.get('total', 0)}; "
            f"{duration_text}",
            soft_wrap=True,
        )


class _DryRunScan(NamedTuple):
    """Disjoint code and document discovery projected for CLI rendering."""

    code_scan: ContentScanResult | None
    document_scan: DocumentScanResult | None
    code_files: list[str]
    document_files: list[str]

    @property
    def files(self) -> list[str]:
        return [*self.code_files, *self.document_files]

    @property
    def total(self) -> int:
        document_total = self.document_scan.total_files if self.document_scan else 0
        return len(self.code_files) + document_total


def _validate_dry_run_request(
    index_type: PublicSourceType,
    json_mode: bool,
    dry_run_limit: int,
) -> None:
    """Reject unsupported source selections and invalid sample bounds."""
    if index_type is PublicSourceType.VAULT:
        message = "Dry run is available for code and document indexing."
        remediation = [
            index_command(source, IndexCommandOptions(dry_run=True))
            for source in (PublicSourceType.CODE, PublicSourceType.DOCUMENT)
        ]
        if json_mode:
            _emit_json_error_and_exit(
                "index",
                "dry_run_requires_supported_type",
                message,
                2,
                remediation=remediation,
            )
        _plain(message)
        _plain("Run:")
        _plain(f"  {remediation[0]}")
        raise typer.Exit(code=2)
    if dry_run_limit >= 0:
        return
    message = "Dry-run file limit must be zero or greater."
    if json_mode:
        _emit_json_error_and_exit(
            "index",
            "invalid_dry_run_limit",
            message,
            2,
            remediation=["Use --dry-run-limit 0 or a positive number."],
        )
    _plain(message)
    _plain("Run:")
    command = index_command(
        PublicSourceType.CODE,
        IndexCommandOptions(dry_run=True, dry_run_limit=50),
    )
    _plain(f"  {command}")
    raise typer.Exit(code=2)


def _scan_dry_run_sources(
    index_type: PublicSourceType,
    target: pathlib.Path,
    exclude: list[str] | None,
    dry_run_limit: int,
) -> _DryRunScan:
    """Discover the requested sources without opening index storage."""
    from ..api import scan_codebase

    code_scan = (
        scan_codebase(target, extra_excludes=exclude)
        if index_type in (PublicSourceType.CODE, PublicSourceType.COMBINED)
        else None
    )
    import vaultspec_rag

    document_scan = (
        vaultspec_rag.scan_documents(
            target,
            sample_limit=dry_run_limit,
            extra_excludes=exclude,
        )
        if index_type in (PublicSourceType.DOCUMENT, PublicSourceType.COMBINED)
        else None
    )
    code_files = [
        path.relative_to(target).as_posix()
        for path in sorted(code_scan.files if code_scan is not None else [])
    ]
    document_files = list(document_scan.sampled_paths) if document_scan else []
    return _DryRunScan(code_scan, document_scan, code_files, document_files)


def _dry_run_admission(scan: ContentScanResult | None) -> dict[str, object]:
    """Project code admission evidence into the stable JSON shape."""
    counts: tuple[AdmissionCount, ...] = scan.counts if scan is not None else ()
    samples: tuple[AdmissionSample, ...] = scan.samples if scan is not None else ()
    return {
        "policy_fingerprint": scan.policy_fingerprint if scan is not None else None,
        "counts": [count.as_payload() for count in counts],
        "samples": [sample.as_payload() for sample in samples],
    }


def _dry_run_document_source(scan: _DryRunScan) -> dict[str, object]:
    """Project bounded document discovery into the stable JSON shape."""
    document_scan = scan.document_scan
    return {
        "count": document_scan.total_files if document_scan else 0,
        "files": scan.document_files,
        "truncated": bool(document_scan and document_scan.truncated),
        "membership_fingerprint": (
            document_scan.membership_fingerprint if document_scan else None
        ),
        "content_fingerprint": (
            document_scan.content_fingerprint if document_scan else None
        ),
        "policy_snapshot": document_scan.policy_snapshot if document_scan else None,
        "preprocess_rule_count": (
            document_scan.preprocess_rule_count if document_scan else 0
        ),
        "execution_mode": document_scan.execution_mode if document_scan else None,
    }


def _emit_dry_run_json(scan: _DryRunScan) -> None:
    """Emit one structured dry-run outcome."""
    _emit_json(
        True,
        "index",
        data={
            "dry_run": True,
            "count": scan.total,
            "files": scan.files,
            "truncated": bool(scan.document_scan and scan.document_scan.truncated),
            "sources": {
                "code": {"count": len(scan.code_files), "files": scan.code_files},
                "document": _dry_run_document_source(scan),
            },
            "admission": _dry_run_admission(scan.code_scan),
        },
    )


def _render_dry_run(
    scan: _DryRunScan, index_type: PublicSourceType, limit: int
) -> None:
    """Render a bounded human-readable dry-run summary."""
    shown_files = scan.files[:limit]
    noun = "file" if scan.total == 1 else "files"
    source_description = (
        "source-code" if index_type is PublicSourceType.CODE else index_type.value
    )
    _plain(f"Dry run: {scan.total} {source_description} {noun} would be indexed.")
    if scan.code_scan is not None and scan.code_scan.counts:
        _plain("Admission summary:")
        for count in scan.code_scan.counts:
            kind = count.kind.value if count.kind is not None else "unowned"
            disposition = "admitted" if count.admitted else "rejected"
            _plain(f"  - {kind}/{disposition}/{count.reason.value}: {count.count}")
    if shown_files:
        _plain("Files shown:")
        for path in shown_files:
            _cli.console.print(f"  - {path}")
    elif scan.total:
        _plain("Files shown: none.")
    _render_hidden_dry_run_files(scan.total - len(shown_files), scan.total, index_type)


def _render_hidden_dry_run_files(
    hidden: int,
    total: int,
    index_type: PublicSourceType,
) -> None:
    """Explain a bounded human sample when additional files were discovered."""
    if hidden <= 0:
        return
    hidden_noun = "file" if hidden == 1 else "files"
    suffix = (
        "or --json for the full list."
        if index_type is PublicSourceType.CODE
        else "to request a larger bounded sample."
    )
    _plain(
        f"{hidden} more {hidden_noun} not shown. Use --dry-run-limit {total} {suffix}",
        soft_wrap=True,
    )


def _handle_dry_run(
    index_type: PublicSourceType,
    json_mode: bool,
    target: pathlib.Path,
    exclude: list[str] | None,
    dry_run_limit: int,
    no_preprocess: bool,
) -> None:
    _validate_dry_run_request(index_type, json_mode, dry_run_limit)
    if no_preprocess:
        _apply_preprocess_off_env()
    scan = _scan_dry_run_sources(index_type, target, exclude, dry_run_limit)
    if json_mode:
        _emit_dry_run_json(scan)
        return
    _render_dry_run(scan, index_type, dry_run_limit)


def _validate_rebuild(ctx: typer.Context, json_mode: bool) -> None:
    try:
        param_source = ctx.get_parameter_source("index_type")
        type_is_explicit = getattr(param_source, "name", "") != "DEFAULT"
    except (AttributeError, LookupError) as exc:
        logger.debug("click ParameterSource probe failed: %s", exc, exc_info=True)
        type_is_explicit = True
    if not type_is_explicit:
        # Every source the flag accepts, so a new one reaches the operator
        # here instead of being accepted but never offered.
        remediation = [
            index_command(source, IndexCommandOptions(rebuild=True))
            for source in PublicSourceType
        ]
        msg = (
            "--rebuild is destructive; pass an explicit --type "
            "(vault|code|document|combined) so the scope is unambiguous. The "
            "previous behaviour silently inherited --type all "
            "from the default and dropped every collection."
        )
        if json_mode:
            _emit_json_error_and_exit(
                "index",
                "rebuild_requires_explicit_type",
                msg,
                2,
                remediation=remediation,
            )
        _plain(f"Error: {msg}")
        for line in remediation:
            _plain(f"  {line}")
        raise typer.Exit(code=2)


def _try_service_delegation(
    port: int,
    exclude: list[str] | None,
    json_mode: bool,
    index_type: PublicSourceType,
    rebuild: bool,
    target: pathlib.Path,
    allow_fallback: bool,
) -> bool:
    if exclude and not json_mode:
        _cli.console.print(
            "--exclude is ignored when using the running service.",
        )
    data = _try_http_reindex(
        index_type,
        rebuild,
        port,
        str(target),
        initiator_kind="cli",
    )
    if (
        isinstance(data, dict)
        and data.get("ok") is False
        and data.get("partial") is not True
    ):
        if not json_mode:
            _plain(
                f"Reindex {index_type.value} reported an error; "
                "refusing to silently fall back."
            )
        _display_service_error(data, json_mode=json_mode, command="index")
        raise typer.Exit(code=1)

    if data is not None:
        if json_mode:
            _emit_json(
                True,
                "index",
                data={"via": "service", "source": index_type.value, "outcome": data},
            )
        elif "job_id" in data:
            _plain(
                f"{_index_source_label(index_type.value)} re-index job queued on "
                f"service: {data.get('job_id')}"
            )
            _cli.console.print("Check progress with: vaultspec-rag server jobs")
        elif _print_service_domain_outcomes(data.get("domains")):
            pass
        else:
            rows = data.get("sources")
            if isinstance(rows, list):
                _print_index_summary(
                    cast("list[dict[str, object]]", rows), via="service"
                )
            else:
                _print_index_summary(
                    [
                        {
                            "source": index_type.value,
                            **data,
                        }
                    ],
                    via="service",
                )
        return True

    if not allow_fallback:
        _display_port_unreachable_error(
            port,
            command="indexing",
            json_mode=json_mode,
        )
        raise typer.Exit(code=1)

    return False


def _print_service_domain_outcomes(raw_domains: object) -> bool:
    """Render canonical per-domain queued or failed reindex outcomes."""
    if not isinstance(raw_domains, dict):
        return False
    domains = cast("dict[str, object]", raw_domains)
    rendered = False
    for source in INDEX_SOURCES:
        raw = domains.get(source)
        if not isinstance(raw, dict):
            continue
        domain = cast("dict[str, object]", raw)
        rendered = True
        label = _index_source_label(source)
        if domain.get("ok") is True:
            _plain(f"{label} re-index job queued on service: {domain.get('job_id')}")
        else:
            _plain(
                f"{label}: failed: {domain.get('error_kind')}: {domain.get('detail')}"
            )
    if rendered:
        _cli.console.print("Check progress with: vaultspec-rag server jobs")
    return rendered


@app.command(
    "index",
    help=(
        "Build or update the vault, code, and extracted-document search indexes. "
        "Uses the running service when available; otherwise runs locally."
    ),
)
def handle_index(
    ctx: typer.Context,
    index_type: Annotated[
        str,
        typer.Option(
            "--type",
            help=(
                "What to index: vault, code, document, or combined. "
                "Aliases: docs, codebase, all."
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
    port: PortOption = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help=(
                "Show the resolved code/document admission summary without indexing. "
                "Use with --type code, document, combined, or the default all alias."
            ),
        ),
    ] = False,
    dry_run_limit: Annotated[
        int,
        typer.Option(
            "--dry-run-limit",
            help=(
                "Maximum source-code file paths to show in human dry-run output. "
                "JSON output still includes every path."
            ),
            show_default=True,
        ),
    ] = 50,
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
                "If the selected service is not reachable, build the index "
                "locally instead of stopping with an error."
            ),
        ),
    ] = False,
    no_preprocess: Annotated[
        bool,
        typer.Option(
            "--no-preprocess",
            help=(
                "Load no document-preprocessing rules for this in-process index "
                "run (VAULTSPEC_RAG_PREPROCESS=off). Applies to in-process "
                "indexing only; a running service uses the preprocess mode it "
                "was started with."
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
    json_mode: JsonMode = False,
) -> None:
    """Index vault documents and/or codebase chunks."""
    if not verbose:
        _suppress_hf_progress()
    state: CLIState = ctx.obj
    target = state.target
    source = _parse_index_source(index_type, command="index", json_mode=json_mode)

    if dry_run:
        _handle_dry_run(
            source,
            json_mode,
            target,
            exclude,
            dry_run_limit,
            no_preprocess,
        )
        return

    if rebuild:
        _validate_rebuild(ctx, json_mode)

    if port is None:
        service = resolve_data_plane_service()
        if service.reachable and not service.version.is_compatible:
            # Refuse instead of falling through to the in-process path. A daemon
            # of another release still owns the store and the writer lock, so
            # indexing around it would contend with a process this build cannot
            # speak to - a worse outcome than stopping.
            _display_service_version_error(
                service.version,
                command="index",
                json_mode=json_mode,
            )
            raise typer.Exit(code=1)
        port = service.port
        if port is not None:
            # We detected a running service, so enable fallback automatically.
            allow_fallback = True

    # A preprocess flag only shapes an in-process run. When a service will
    # handle this index (an explicit or auto-detected port), the daemon
    # preprocesses under its own start-time mode, so warn loudly that the flag
    # does not apply rather than silently accepting it - the run still proceeds.
    if no_preprocess and port is not None:
        _warn_preprocess_flag_ignored_when_delegating(json_mode)

    if port is not None and _try_service_delegation(
        port, exclude, json_mode, source, rebuild, target, allow_fallback
    ):
        return

    # In-process path: apply the forwarded preprocess mode to the env before
    # indexing begins (the config property reads it live).
    if no_preprocess:
        _apply_preprocess_off_env()

    _try_in_process_indexing(source, rebuild, model, exclude, target, json_mode)


def _try_in_process_indexing(
    index_type: PublicSourceType,
    rebuild: bool,
    model: str | None,
    exclude: list[str] | None,
    target: pathlib.Path,
    json_mode: bool,
) -> None:
    import contextlib

    import vaultspec_rag

    from ..progress import NullProgressReporter, RichProgressReporter

    # Progress is human output and stdout is the result channel, so a --json
    # run reports none of it. Emitting it there put prose ahead of the envelope
    # on the one path that promises exactly one structured document, and a
    # broker parsing stdout got a syntax error instead of an outcome.
    reporter_ctx: AbstractContextManager[ProgressReporter] = (
        contextlib.nullcontext(NullProgressReporter())
        if json_mode
        else RichProgressReporter(_cli.console)
    )
    with reporter_ctx as reporter:
        reporter.phase_start("resolve workspace", 1)
        reporter.advance(1)
        reporter.phase_end()

        try:
            v_res, c_res, d_res, all_outcomes = _execute_source_indexing(
                vaultspec_rag,
                index_type=index_type,
                target=target,
                rebuild=rebuild,
                reporter=reporter,
                model=model,
                exclude=exclude,
            )
        except VaultStoreLockedError as exc:
            if json_mode:
                _emit_json_error_and_exit(
                    "index",
                    "rebuild_locked" if rebuild else "index_locked",
                    "Cannot update the index because the local index is busy.",
                    1,
                    db_path=str(exc.db_path),
                    index_type=index_type.value,
                    remediation=[
                        server_status_command(),
                        "Use --port with a running service for concurrent work.",
                        "Retry after the current index operation finishes.",
                    ],
                )
            _plain(_format_local_index_busy_message("update the index"))
            raise typer.Exit(code=1) from None
        except InsufficientDiskSpaceError as exc:
            # A RuntimeError subclass: without this branch the disk
            # preflight refusal would fall into the GPU-error handler
            # and be misdiagnosed as a torch problem.
            if json_mode:
                _emit_json_error_and_exit(
                    "index",
                    "disk_preflight_failed",
                    str(exc),
                    1,
                    index_type=index_type.value,
                    remediation=[
                        "vaultspec-rag server storage survey",
                        "vaultspec-rag server storage prune --dry-run",
                        "Free disk space on the store volume and retry.",
                    ],
                )
            _plain(f"Error: {exc}")
            raise typer.Exit(code=1) from None
        except (ImportError, RuntimeError) as e:
            _handle_gpu_error(e)

    in_process_sources = _collect_index_rows(v_res, c_res, d_res, all_outcomes)

    if json_mode:
        _emit_json(
            True,
            "index",
            data={
                "via": "in-process",
                "sources": in_process_sources,
                "partial": any(row.get("ok") is False for row in in_process_sources),
            },
        )
        return

    _print_index_summary(
        [row for row in in_process_sources if row.get("ok") is not False],
        via="in-process",
    )
    _render_failed_index_rows(in_process_sources)


def _collect_index_rows(
    vault_result: IndexResult | None,
    code_result: IndexResult | None,
    document_result: IndexResult | None,
    all_outcomes: AllIndexOutcomes | None,
) -> list[dict[str, object]]:
    """Build non-collapsing per-domain rows for CLI output."""
    rows: list[dict[str, object]] = []
    for source, result in (
        ("vault", vault_result),
        ("code", code_result),
        ("document", document_result),
    ):
        if result is None:
            continue
        row = _index_result_row(source, result)
        if source == "code":
            row.update(
                preprocess_ok=result.preprocess_ok,
                preprocess_skipped=result.preprocess_skipped,
                preprocess_failures=result.preprocess_failures,
            )
        if result.reuse is not None:
            row["reuse"] = result.reuse
        rows.append(row)
    if all_outcomes is None:
        return rows
    for source, outcome in (
        ("vault", all_outcomes.vault),
        ("code", all_outcomes.code),
        ("document", all_outcomes.document),
    ):
        rows.append(
            _index_result_row(source, outcome.result)
            if outcome.result is not None
            else {"source": source, "ok": False, "error": outcome.error}
        )
    return rows


def _render_failed_index_rows(rows: list[dict[str, object]]) -> None:
    for row in rows:
        if row.get("ok") is not False:
            continue
        _plain(f"{_index_source_label(str(row['source']))}: failed: {row['error']}")


def _execute_source_indexing(
    api: Any,
    *,
    index_type: PublicSourceType,
    target: pathlib.Path,
    rebuild: bool,
    reporter: Any,
    model: str | None,
    exclude: list[str] | None,
) -> tuple[
    IndexResult | None,
    IndexResult | None,
    IndexResult | None,
    AllIndexOutcomes | None,
]:
    """Execute exactly one canonical source selection without fallback."""
    if index_type is PublicSourceType.COMBINED:
        return (
            None,
            None,
            None,
            api.index_all(
                target,
                clean=rebuild,
                reporter=reporter,
                model_name=model,
                extra_excludes=exclude,
            ),
        )
    if index_type is PublicSourceType.VAULT:
        return (
            api.index(
                target,
                clean=rebuild,
                reporter=reporter,
                model_name=model,
            ),
            None,
            None,
            None,
        )
    if index_type is PublicSourceType.CODE:
        return (
            None,
            api.index_codebase(
                target,
                clean=rebuild,
                reporter=reporter,
                model_name=model,
                extra_excludes=exclude,
            ),
            None,
            None,
        )
    return (
        None,
        None,
        api.index_documents(
            target,
            clean=rebuild,
            reporter=reporter,
            model_name=model,
            extra_excludes=exclude,
        ),
        None,
    )


def _index_result_row(source: str, result: IndexResult) -> dict[str, object]:
    """Project one real IndexResult into the stable CLI row shape."""
    return {
        "source": source,
        "ok": True,
        "added": result.added,
        "updated": result.updated,
        "removed": result.removed,
        "total": result.total,
        "duration_ms": result.duration_ms,
    }


@app.command(
    "clean",
    help=(
        "Delete selected index data without rebuilding it. "
        "Does not load models or use the GPU."
    ),
)
def handle_clean(
    ctx: typer.Context,
    clean_type: Annotated[
        str,
        typer.Argument(
            help=(
                "What to delete: vault, code, document, or combined/all. "
                "Required so nothing is deleted by accident."
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
                f"{JSON_OPTION_HELP} Requires --yes "
                "so no prompt interrupts the JSON output."
            ),
        ),
    ] = False,
) -> None:
    """Delete selected index data without rebuilding it."""
    state: CLIState = ctx.obj
    target = state.target
    source = _parse_index_source(clean_type, command="clean", json_mode=json_mode)
    canonical_clean_type = index_source_option(source)
    if json_mode and not yes:
        _emit_json_error_and_exit(
            "clean",
            "json_requires_yes",
            "--json requires --yes so the command can write one JSON result "
            "without an interactive confirmation prompt.",
            2,
        )
    if not yes:
        try:
            confirmed = typer.confirm(
                f"Delete {clean_type} search index data for {target}?",
                default=False,
            )
        except typer.Abort:
            _cli.console.print("Clean cancelled.")
            raise typer.Exit(code=1) from None
        if not confirmed:
            _cli.console.print("Clean cancelled.")
            raise typer.Exit(code=1)

    import vaultspec_rag

    try:
        cleared_raw = vaultspec_rag.clean(target, clean_type=canonical_clean_type)
    except VaultStoreLockedError as exc:
        if json_mode:
            _emit_json_error_and_exit(
                "clean",
                "clean_locked",
                "Cannot clean the index because the local index is busy.",
                1,
                db_path=str(exc.db_path),
                clean_type=source.value,
                remediation=[
                    server_status_command(),
                    "Stop the service if you need exclusive cleanup.",
                    "Retry after the current index operation finishes.",
                ],
            )
        _plain(_format_local_index_busy_message("clean the index"))
        raise typer.Exit(code=1) from None

    cleared = [s.lower() for s in cleared_raw]

    if json_mode:
        _emit_json(
            True,
            "clean",
            data={
                "clean_type": clean_type,
                "source": source.value,
                "cleared": cleared,
            },
        )
        return

    _cli.console.print("Clean summary")
    for source in cleared:
        label = _index_source_label("codebase" if source == "code" else source)
        _plain(f"{label} index: empty.")
