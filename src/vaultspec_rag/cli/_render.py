"""Output rendering: JSON envelopes, backend-contract rows, result tables.

Holds the shared ``--json`` envelope helpers plus the Rich renderers
for search results and install/uninstall reports. Renderers read
``console`` from the package namespace at call time so tests that
swap ``vaultspec_rag.cli.console`` observe the substitution.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Literal, cast

import typer
from rich.table import Table

import vaultspec_rag.cli as _cli

from ..capabilities import backend_capabilities_dict

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
    _cli.console.print(f"[bold red]Error:[/] {message}")
    _cli.console.print(f"[dim]code={error}[/]")
    db_path = payload.get("db_path")
    if db_path:
        _cli.console.print(f"[dim]db_path={db_path}[/]")
    remediation = payload.get("remediation")
    if isinstance(remediation, list) and remediation:
        _cli.console.print("[bold]Next actions:[/]")
        for item in remediation:
            _cli.console.print(f"  - {item}")
    diagnostics = payload.get("diagnostics")
    if isinstance(diagnostics, dict):
        health = diagnostics.get("health")
        jobs = diagnostics.get("jobs")
        if isinstance(health, dict):
            _cli.console.print(
                "[dim]"
                f"service_status={health.get('status', 'unknown')}; "
                f"project_count={health.get('project_count', '?')}"
                "[/]"
            )
        if isinstance(jobs, dict):
            _cli.console.print(f"[dim]running_jobs={jobs.get('running_count', '?')}[/]")
    caps = payload.get("backend_capabilities")
    if isinstance(caps, dict):
        table = Table(title="Backend Contract", show_header=False, padding=(0, 2))
        table.add_column("Key", style="bold")
        table.add_column("Value")
        _add_backend_contract_rows(table, cast("dict[str, object]", caps))
        _cli.console.print(table)


def _display_search_results(
    results: list[dict[str, object]],
    search_type: str,
    via: Literal["service", "in-process"] = "service",
    *,
    no_truncate: bool = False,
) -> None:
    """Display search results as a Rich table.

    Args:
        results: List of result dicts with ``score``, ``path``,
            ``snippet``, and optional ``line_start`` keys.
        search_type: Label for the table title (e.g.
            ``vault``, ``code``, ``all``).
        via: Transport path indicator (e.g. ``service``, ``in-process``).
        no_truncate: Bypass the 120-character snippet truncation
            so sibling files with long paths stay distinguishable.

    """
    table = Table(title=f"Search Results: {search_type} (via {via})", box=None)
    table.add_column("Score", justify="right", style="cyan", no_wrap=True)
    table.add_column("Location", style="green")
    table.add_column("Snippet", style="white")

    for r in results:
        snippet_raw = str(r.get("snippet", "")).replace("\n", " ")
        snippet = snippet_raw if no_truncate else snippet_raw[:120]
        location = str(r.get("path", ""))
        # Preprocess-hook results carry a deep-link anchor / locator (#185);
        # prefer them over the line number so hits point into the source.
        anchor = r.get("anchor")
        locator = r.get("locator")
        line_start = r.get("line_start")
        if anchor:
            location = str(anchor)
        elif locator:
            location += f" ({locator})"
        elif line_start:
            location += f":{line_start}"
        raw_score = r.get("score", 0.0)
        score = float(raw_score) if isinstance(raw_score, (int, float, str)) else 0.0
        table.add_row(f"{score:.2f}", location, snippet)

    _cli.console.print(table)


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
