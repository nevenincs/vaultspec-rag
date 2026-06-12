"""Output rendering: JSON envelopes, backend-contract rows, and human output.

Holds the shared ``--json`` envelope helpers plus the renderers for
search results and install/uninstall reports. Renderers read
``console`` from the package namespace at call time so tests that
swap ``vaultspec_rag.cli.console`` observe the substitution.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

import typer

import vaultspec_rag.cli as _cli

from ..capabilities import backend_capabilities_dict

if TYPE_CHECKING:
    from rich.table import Table

__all__ = [
    "_add_backend_contract_rows",
    "_display_port_unreachable_error",
    "_display_search_results",
    "_display_service_error",
    "_emit_json",
    "_emit_json_error_and_exit",
    "_render_install_report",
    "_render_uninstall_report",
]


def _capability_value(caps: dict[str, object], key: str) -> str:
    """Return a capability value as display text."""
    value = caps.get(key, "unknown")
    return str(value)


def _add_backend_contract_rows(
    table: Table,
    caps: dict[str, object] | None = None,
) -> None:
    """Add backend concurrency contract rows to a Rich table."""
    data = caps if caps is not None else backend_capabilities_dict()
    table.add_row(
        "Search Concurrency",
        (
            "supported; same-project local backend access "
            f"{_capability_value(data, 'same_project_search_strategy')}"
        ),
    )
    table.add_row(
        "Cross-project Search",
        _capability_value(data, "cross_project_search_strategy"),
    )
    table.add_row(
        "Storage Process Model",
        (
            f"{_capability_value(data, 'local_storage_process_model')} "
            "local Qdrant process"
        ),
    )


def _emit_json(
    ok: bool,
    command: str,
    *,
    data: object | None = None,
    error: str | None = None,
    message: str | None = None,
    **extra: object,
) -> None:
    """Write one envelope-wrapped JSON document to stdout.

    The envelope is `{"ok": bool, "command": str, "data" | "error" +
    "message", **extra}`. Every ``--json`` invocation emits exactly
    one document. We bypass the Rich ``console`` entirely so no
    formatting bytes leak - ``json.dumps`` plus one trailing
    newline, written directly to ``sys.stdout``.
    """
    envelope: dict[str, object] = {"ok": ok, "command": command}
    if data is not None:
        envelope["data"] = data
    if error is not None:
        envelope["error"] = error
    if message is not None:
        envelope["message"] = message
    envelope.update(extra)
    sys.stdout.write(json.dumps(envelope, default=str) + "\n")
    sys.stdout.flush()


def _emit_json_error_and_exit(
    command: str,
    error: str,
    message: str,
    code: int,
    **extra: object,
) -> None:
    """Emit an `{"ok": false, ...}` envelope, then raise `typer.Exit`.

    Centralises the JSON error path so every command's failure
    branches converge on one shape. Used by the new `--json` wiring
    on every CLI command and by the JSON-mode branches of
    ``_display_service_error`` / ``_display_port_unreachable_error``.
    """
    _emit_json(
        False,
        command,
        error=error,
        message=message,
        **extra,
    )
    raise typer.Exit(code=code)


def _display_service_error(
    payload: dict[str, object],
    *,
    json_mode: bool = False,
    command: str = "service",
    exit_code: int = 1,
) -> None:
    """Render a structured error returned by the RAG service fast path.

    When ``json_mode`` is True the helper emits the envelope and
    raises ``typer.Exit(exit_code)`` so callers don't have to thread
    the exit themselves. The Rich path retains its original behaviour
    (no exit; caller decides).
    """
    error = str(payload.get("error", "service_error"))
    message = str(payload.get("message", "RAG service returned an error."))
    if json_mode:
        extra: dict[str, object] = {}
        for key in (
            "db_path",
            "backend_capabilities",
            "diagnostics",
            "port",
            "timeout_seconds",
            "remediation",
        ):
            value = payload.get(key)
            if value is not None:
                extra[key] = value
        _emit_json_error_and_exit(
            command,
            error,
            message,
            exit_code,
            **extra,
        )
        return
    _cli.console.print(f"[bold red]Error:[/] {_human_service_error_message(message)}")
    if error != "http_search_timeout":
        _cli.console.print(f"[dim]code={error}[/]")
    db_path = payload.get("db_path")
    if db_path:
        _cli.console.print(f"[dim]db_path={db_path}[/]")
    _display_service_diagnostic_summary(payload.get("diagnostics"))
    remediation = payload.get("remediation")
    if isinstance(remediation, list) and remediation:
        _cli.console.print("[bold]Next actions:[/]")
        for item in remediation:
            _cli.console.print(f"  - {item}")


def _human_service_error_message(message: str) -> str:
    """Remove raw backend diagnostics from default human error prose."""
    return re.sub(
        r"\s+Service status=.*?same_project_search_strategy=[^.\s]+\.?",
        "",
        message,
    ).strip()


def _display_service_diagnostic_summary(diagnostics: object) -> None:
    """Render timeout/error diagnostics without backend contract internals."""
    if not isinstance(diagnostics, dict):
        return
    health = diagnostics.get("health")
    jobs = diagnostics.get("jobs")
    if isinstance(health, dict):
        _cli.console.print(
            f"Service: {_health_diagnostic_text(cast('dict[str, object]', health))}"
        )
    if isinstance(jobs, dict):
        _cli.console.print(
            f"Work: {_jobs_diagnostic_text(cast('dict[str, object]', jobs))}"
        )


def _health_diagnostic_text(health: dict[str, object]) -> str:
    if health.get("available") is False:
        return _unavailable_diagnostic_text(health, "status check")
    status = str(health.get("status", "unknown"))
    project_count = health.get("project_count")
    if project_count is None:
        return f"reachable; health status {status}"
    return f"reachable; health status {status}; {project_count} project(s) loaded"


def _jobs_diagnostic_text(jobs: dict[str, object]) -> str:
    if jobs.get("available") is False:
        return _unavailable_diagnostic_text(jobs, "jobs check")
    running = jobs.get("running_count")
    if isinstance(running, int):
        if running == 0:
            return "no running jobs reported"
        return f"{running} running job(s) reported"
    return "running work status unknown"


def _unavailable_diagnostic_text(data: dict[str, object], label: str) -> str:
    error = str(data.get("error", "")).strip()
    message = str(data.get("message", "")).strip()
    if error == "TimeoutError" or "timed out" in message.lower():
        return f"{label} timed out"
    if message:
        return f"{label} unavailable ({message})"
    return f"{label} unavailable"


def _display_search_results(
    results: list[dict[str, object]],
    search_type: str,
    via: Literal["service", "in-process"] = "service",
    *,
    no_truncate: bool = False,
    show_scores: bool = False,
    root: Path | None = None,
) -> None:
    """Display search results as stable line-oriented records.

    Args:
        results: List of result dicts with ``score``, ``path``,
            ``snippet``, and optional ``line_start`` keys.
        search_type: Search source label retained for API compatibility
            (e.g. ``vault``, ``code``).
        via: Transport path indicator retained for API compatibility
            (e.g. ``service``, ``in-process``).
        no_truncate: Backwards-compatible no-op. Default human output
            no longer truncates snippets.
        show_scores: Include numeric relevance scores after the rank.
        root: Workspace root used to read full source lines when a
            result includes a local relative path and line range.

    """
    _ = search_type, via, no_truncate
    for rank, result in enumerate(results, start=1):
        location = _search_result_location(result)
        snippet = _search_result_text(result, root=root)
        details = f"rank={rank}"
        if show_scores:
            details += f" score={_search_result_score(result):.4f}"
        line = f"{location}: {details}"
        if snippet:
            line += f" {snippet}"
        _cli.console.print(line, markup=False, highlight=False, soft_wrap=True)


def _single_line_text(value: object) -> str:
    """Collapse multiline display text into one copyable result line."""
    return " ".join(str(value).splitlines())


def _search_result_text(result: dict[str, object], *, root: Path | None) -> str:
    source_text = _source_line_text(result, root=root)
    if source_text:
        return source_text
    return _single_line_text(result.get("snippet", ""))


def _source_line_text(result: dict[str, object], *, root: Path | None) -> str:
    path_text = _non_empty_result_string(result, "source_path") or (
        _non_empty_result_string(result, "path")
    )
    line_start = result.get("line_start")
    if path_text is None or not isinstance(line_start, int):
        return ""
    line_end = result.get("line_end")
    end = (
        line_end if isinstance(line_end, int) and line_end >= line_start else line_start
    )
    path = Path(path_text)
    if not path.is_absolute():
        path = (root or Path.cwd()) / path
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    selected = lines[line_start - 1 : end]
    return _single_line_text("\n".join(selected))


def _search_result_score(result: dict[str, object]) -> float:
    raw_score = result.get("score", 0.0)
    if isinstance(raw_score, (int, float, str)):
        try:
            return float(raw_score)
        except ValueError:
            return 0.0
    return 0.0


def _search_result_location(result: dict[str, object]) -> str:
    """Return the best stable locator already present on a result."""
    anchor = _non_empty_result_string(result, "anchor")
    if anchor is not None:
        return anchor

    path = (
        _non_empty_result_string(result, "path")
        or _non_empty_result_string(result, "source_path")
        or _non_empty_result_string(result, "doc_id")
        or _non_empty_result_string(result, "id")
        or "<unknown>"
    )
    line_start = _result_int(result, "line_start")
    if line_start is not None:
        column = (
            _result_int(result, "column_start")
            or _result_int(result, "col_start")
            or _result_int(result, "column")
        )
        suffix = f":{line_start}"
        if column is not None:
            suffix += f":{column}"
        return f"{path}{suffix}"

    locator = _non_empty_result_string(result, "locator")
    if locator is not None:
        return f"{path} ({locator})"
    return path


def _non_empty_result_string(
    result: dict[str, object],
    key: str,
) -> str | None:
    value = result.get(key)
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _result_int(result: dict[str, object], key: str) -> int | None:
    value = result.get(key)
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def _display_port_unreachable_error(
    port: int,
    *,
    command: str,
    json_mode: bool = False,
) -> None:
    """Render the standard remediation when ``--port`` is dead.

    Mirrors the lock-error UX so users see consistent guidance whether
    the resident service refused the connection or refused parallel
    access. The CLI used to silently fall back to in-process here; that
    behaviour is now opt-in via ``--allow-fallback``.

    When ``json_mode`` is True the helper emits a ``port_unreachable``
    envelope and exits with code 1; the prose path is unchanged.
    """
    if json_mode:
        _emit_json_error_and_exit(
            command,
            "port_unreachable",
            (
                f"Service on port {port} is unreachable. "
                f"The CLI will not silently fall back to in-process "
                f"{command}; start the service or re-run with "
                f"--allow-fallback (single-agent use only)."
            ),
            1,
            port=port,
            remediation=[
                "vaultspec-rag server status",
                "vaultspec-rag server start",
                "rerun with --allow-fallback (single-agent only)",
            ],
        )
        return
    _cli.console.print(
        f"[bold red]Service on port {port} is unreachable.[/]\n"
        f"[white]The CLI will not silently fall back to in-process "
        f"{command} because that would acquire the Qdrant lock and "
        f"strand any other agent waiting on the resident service.[/]\n"
        f"[bold]Remediation:[/]\n"
        f"  1. Check status:  vaultspec-rag server status\n"
        f"  2. Start service: vaultspec-rag server start\n"
        f"  3. Or opt in to in-process fallback: re-run with "
        f"--allow-fallback (single-agent use only).",
    )


def _render_install_report(report: Any) -> None:
    """Render an install report to the Rich console."""
    title = {
        "install": "[bold green]vaultspec-rag installed[/]",
        "upgrade": "[bold green]vaultspec-rag upgraded[/]",
        "dry_run": "[bold yellow]vaultspec-rag install (dry-run)[/]",
    }.get(report.action, "[bold]vaultspec-rag install[/]")
    _cli.console.print(title)
    _cli.console.print(f"target: [cyan]{report.target}[/]")
    if report.created_dirs:
        _cli.console.print(f"created [bold]{len(report.created_dirs)}[/] directories")
    if report.seeded:
        _cli.console.print(f"seeded [bold]{len(report.seeded)}[/] bundled files:")
        for rel in report.seeded:
            _cli.console.print(f"  [green]+[/] {rel}")
    sync_added = sum(getattr(r, "added", 0) for r in report.sync_results)
    sync_updated = sum(getattr(r, "updated", 0) for r in report.sync_results)
    sync_pruned = sum(getattr(r, "pruned", 0) for r in report.sync_results)
    if sync_added or sync_updated or sync_pruned:
        _cli.console.print(
            f"core sync: [green]+{sync_added}[/] "
            f"[yellow]~{sync_updated}[/] [red]-{sync_pruned}[/]"
        )
    tc_action = getattr(report, "torch_config_action", "skipped")
    tc_colour = {
        "applied": "green",
        "already": "cyan",
        "dry_run": "yellow",
        "disabled": "dim",
        "declined": "yellow",
        "conflict": "red",
        "absent": "yellow",
        "error": "red",
        "skipped-non-tty": "yellow",
        "skipped-eof": "yellow",
    }.get(tc_action, "white")
    _cli.console.print(f"torch-config: [{tc_colour}]{tc_action}[/]")
    td_action = getattr(report, "torch_direct_dep_action", "skipped")
    if td_action not in ("skipped",):
        td_colour = {
            "applied": "green",
            "already": "cyan",
            "dry_run": "yellow",
            "conflict": "red",
            "absent": "yellow",
        }.get(td_action, "white")
        td_location = getattr(report, "torch_direct_dep_location", "")
        suffix = f" ({td_location})" if td_location else ""
        _cli.console.print(
            f"torch direct dependency: [{td_colour}]{td_action}[/]{suffix}"
        )
    for conflict in getattr(report, "torch_config_conflicts", []):
        # Assemble the prefix and body as a single ``Text`` so Rich's
        # word-wrapper can honour the leading two-space indent across
        # wrapped continuation lines. Also keeps literal ``[…]``
        # tokens in ``conflict`` verbatim - ``Text.assemble`` does not
        # parse markup. CLI-05.
        from rich.text import Text

        _cli.console.print(Text.assemble("  ", ("conflict: ", "red"), conflict))
    tsync = getattr(report, "torch_sync_action", "skipped")
    if tsync not in ("skipped",):
        t_colour = {"succeeded": "green", "failed": "red"}.get(tsync, "yellow")
        _cli.console.print(f"uv sync --reinstall-package torch: [{t_colour}]{tsync}[/]")
    for warning in report.warnings:
        # Warnings carry user-pyproject-derived strings (literal TOML
        # keys like ``[tool.uv.sources]``, raw exception messages,
        # tails of uv stderr) - Rich would parse those as markup tags
        # and silently drop the bracketed tokens. Render the prefix
        # with markup, then the body verbatim.
        _cli.console.print("[yellow]warning:[/] ", end="")
        _cli.console.print(warning, markup=False, highlight=False)


def _render_uninstall_report(report: Any) -> None:
    """Render an uninstall report to the Rich console."""
    title = {
        "uninstall": "[bold green]vaultspec-rag uninstalled[/]",
        "dry_run": "[bold yellow]vaultspec-rag uninstall (dry-run; "
        "use --force to apply)[/]",
    }.get(report.action, "[bold]vaultspec-rag uninstall[/]")
    _cli.console.print(title)
    _cli.console.print(f"target: [cyan]{report.target}[/]")
    if report.removed:
        _cli.console.print(
            f"removed [bold]{len(report.removed)}[/] bundled source files:"
        )
        for rel in report.removed:
            _cli.console.print(f"  [red]-[/] {rel}")
    if report.data_removed:
        _cli.console.print("[red]-[/] .vault/data/ (rag index purged)")
    sync_pruned = sum(getattr(r, "pruned", 0) for r in report.sync_results)
    if sync_pruned:
        _cli.console.print(f"core sync pruned: [red]-{sync_pruned}[/]")
    tc_action = getattr(report, "torch_config_action", "skipped")
    tc_colour = {
        "removed": "green",
        "absent": "dim",
        "dry_run": "yellow",
        "skipped": "yellow",
        "error": "red",
    }.get(tc_action, "white")
    _cli.console.print(f"torch-config: [{tc_colour}]{tc_action}[/]")
    td_action = getattr(report, "torch_direct_dep_action", "skipped")
    if td_action not in ("skipped",):
        td_colour = {
            "removed": "green",
            "dry_run": "yellow",
            "conflict": "red",
            "absent": "dim",
        }.get(td_action, "white")
        td_location = getattr(report, "torch_direct_dep_location", "")
        suffix = f" ({td_location})" if td_location else ""
        _cli.console.print(
            f"torch direct dependency: [{td_colour}]{td_action}[/]{suffix}"
        )
    for conflict in getattr(report, "torch_config_conflicts", []):
        # Same Text.assemble treatment as the install side - see
        # CLI-05 in _render_install_report for the rationale.
        from rich.text import Text

        _cli.console.print(Text.assemble("  ", ("conflict: ", "yellow"), conflict))
    for warning in report.warnings:
        # Same markup-leak guard as _render_install_report; see comment
        # there for the rationale.
        _cli.console.print("[yellow]warning:[/] ", end="")
        _cli.console.print(warning, markup=False, highlight=False)
