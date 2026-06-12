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
from typing import Any, Literal, cast

import typer

import vaultspec_rag.cli as _cli

__all__ = [
    "_display_port_unreachable_error",
    "_display_search_results",
    "_display_service_error",
    "_emit_json",
    "_emit_json_error_and_exit",
    "_format_local_index_busy_message",
    "_render_install_report",
    "_render_uninstall_report",
]


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


def _format_local_index_busy_message(action: str) -> str:
    """Return operator-facing text for local index lock failures."""
    return (
        f"Error: Cannot {action} because the local index is busy.\n\n"
        "Another vaultspec-rag command, the background service, or an automatic "
        "index update is using this workspace.\n\n"
        "Next actions:\n"
        "  1. Check current work: vaultspec-rag server status\n"
        "  2. If a service is running, send concurrent work through it with --port.\n"
        "  3. Retry after the current index operation finishes."
    )


def _display_service_error(
    payload: dict[str, object],
    *,
    json_mode: bool = False,
    command: str = "service",
    exit_code: int = 1,
) -> None:
    """Render a structured error returned by the search service fast path.

    When ``json_mode`` is True the helper emits the envelope and
    raises ``typer.Exit(exit_code)`` so callers don't have to thread
    the exit themselves. The Rich path retains its original behaviour
    (no exit; caller decides).
    """
    error = str(payload.get("error", "service_error"))
    message = str(payload.get("message", "Search service returned an error."))
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
    _cli.console.print(
        f"Error: {_human_service_error_message(message)}",
        markup=False,
        highlight=False,
    )
    if error != "http_search_timeout":
        _cli.console.print(f"Code: {error}", markup=False, highlight=False)
    db_path = payload.get("db_path")
    if db_path:
        _cli.console.print(f"DB path: {db_path}", markup=False, highlight=False)
    _display_service_diagnostic_summary(payload.get("diagnostics"))
    remediation = payload.get("remediation")
    if isinstance(remediation, list) and remediation:
        _cli.console.print("Next actions:")
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
    ready_text = (
        "status check passed" if status == "ready" else status.replace("_", " ")
    )
    project_count = health.get("project_count")
    if project_count is None:
        return f"reachable; {ready_text}"
    if isinstance(project_count, int):
        project_word = "project" if project_count == 1 else "projects"
        return f"reachable; {ready_text}; {project_count} {project_word} loaded"
    return f"reachable; {ready_text}; projects loaded: {project_count}"


def _jobs_diagnostic_text(jobs: dict[str, object]) -> str:
    if jobs.get("available") is False:
        return _unavailable_diagnostic_text(jobs, "jobs check")
    running = jobs.get("running_count")
    if isinstance(running, int):
        if running == 0:
            return "no index jobs running"
        word = "job" if running == 1 else "jobs"
        return f"{running} index {word} running"
    return "running job count not reported by service"


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
        line = f"{rank}. {location}"
        if show_scores:
            line += f" (score {_search_result_score(result):.4f})"
        if snippet:
            line += f" - {snippet}"
        _cli.console.print(line, markup=False, highlight=False, soft_wrap=True)


def _single_line_text(value: object) -> str:
    """Collapse multiline display text into one copyable result line."""
    return " ".join(str(value).splitlines())


def _search_result_text(result: dict[str, object], *, root: Path | None) -> str:
    full_text = _non_empty_result_string(result, "rerank_text")
    if full_text is not None:
        return _single_line_text(full_text)
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
                f"The CLI will not silently run {command} locally; "
                f"start the service or re-run with "
                f"--allow-fallback (single-agent use only)."
            ),
            1,
            port=port,
            remediation=[
                "vaultspec-rag server status",
                "vaultspec-rag server start",
                "rerun with --allow-fallback (one user only)",
            ],
        )
        return
    _cli.console.print(
        f"Service on port {port} is unreachable.\n"
        f"The CLI will not silently run {command} locally because that would "
        f"open the local search index directly "
        f"and block other users or agents waiting on the service.\n"
        f"Next actions:\n"
        f"  1. Check status:  vaultspec-rag server status\n"
        f"  2. Start service: vaultspec-rag server start\n"
        f"  3. Or run locally anyway: re-run with "
        f"--allow-fallback (one user only).",
        markup=False,
        highlight=False,
    )


def _action_label(action: object) -> str:
    labels = {
        "applied": "applied",
        "already": "already configured",
        "conflict": "needs review",
        "absent": "not found",
        "removed": "removed",
        "disabled": "disabled",
        "dry_run": "preview only",
        "declined": "declined",
        "skipped": "not changed",
        "skipped-non-tty": "needs confirmation",
        "skipped-eof": "needs confirmation",
        "error": "error",
    }
    text = str(action)
    return labels.get(text, text.replace("_", " ").replace("-", " "))


def _render_sync_summary(added: int, updated: int, removed: int) -> None:
    parts = []
    if added:
        parts.append(f"added {added}")
    if updated:
        parts.append(f"updated {updated}")
    if removed:
        parts.append(f"removed {removed}")
    if parts:
        _cli.console.print(
            f"tool integrations: {', '.join(parts)}",
            markup=False,
            highlight=False,
        )


def _counted(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else plural or singular + 's'}"


def _warning_text(warning: str) -> str:
    if warning == (
        "dry-run: core sync_provider not invoked (would propagate "
        "seeded files to .mcp.json and provider dirs)"
    ):
        return "dry-run preview: would update tool integration files"
    if warning == (
        "dry-run: core sync_provider not invoked (would propagate "
        "removal to .mcp.json and provider dirs)"
    ):
        return "dry-run preview: would remove tool integration files"
    if warning.startswith("core sync failed:"):
        return warning.replace("core sync", "tool integration sync", 1)
    return warning


def _print_warning_or_note(warning: object) -> None:
    text = _warning_text(str(warning))
    prefix = "note" if text.startswith("dry-run preview:") else "warning"
    _cli.console.print(f"{prefix}: {text}", markup=False, highlight=False)


def _render_install_report(report: Any) -> None:
    """Render an install report as plain CLI lines."""
    title = {
        "install": "vaultspec-rag installed",
        "upgrade": "vaultspec-rag upgraded",
        "dry_run": "vaultspec-rag install (dry-run)",
    }.get(report.action, "vaultspec-rag install")
    dry_run = report.action == "dry_run"
    _cli.console.print(title, markup=False, highlight=False)
    _cli.console.print(f"target: {report.target}", markup=False, highlight=False)
    if report.created_dirs:
        verb = "would create" if dry_run else "created"
        _cli.console.print(
            f"{verb} {_counted(len(report.created_dirs), 'directory', 'directories')}"
        )
    if report.seeded:
        verb = "would seed" if dry_run else "seeded"
        _cli.console.print(f"{verb} {_counted(len(report.seeded), 'bundled file')}:")
        for rel in report.seeded:
            _cli.console.print(f"  + {rel}", markup=False, highlight=False)
    sync_added = sum(getattr(r, "added", 0) for r in report.sync_results)
    sync_updated = sum(getattr(r, "updated", 0) for r in report.sync_results)
    sync_pruned = sum(getattr(r, "pruned", 0) for r in report.sync_results)
    _render_sync_summary(sync_added, sync_updated, sync_pruned)
    tc_action = getattr(report, "torch_config_action", "skipped")
    _cli.console.print(
        f"PyTorch configuration: {_action_label(tc_action)}",
        markup=False,
        highlight=False,
    )
    td_action = getattr(report, "torch_direct_dep_action", "skipped")
    if td_action not in ("skipped",):
        td_location = getattr(report, "torch_direct_dep_location", "")
        suffix = f" ({td_location})" if td_location else ""
        _cli.console.print(
            f"PyTorch dependency: {_action_label(td_action)}{suffix}",
            markup=False,
            highlight=False,
        )
    for conflict in getattr(report, "torch_config_conflicts", []):
        _cli.console.print(f"  conflict: {conflict}", markup=False, highlight=False)
    tsync = getattr(report, "torch_sync_action", "skipped")
    if tsync not in ("skipped",):
        _cli.console.print(
            f"uv sync --reinstall-package torch: {tsync}",
            markup=False,
            highlight=False,
        )
    for warning in report.warnings:
        _print_warning_or_note(warning)


def _render_uninstall_report(report: Any) -> None:
    """Render an uninstall report as plain CLI lines."""
    title = {
        "uninstall": "vaultspec-rag uninstalled",
        "dry_run": "vaultspec-rag uninstall (dry-run; use --force to apply)",
    }.get(report.action, "vaultspec-rag uninstall")
    dry_run = report.action == "dry_run"
    _cli.console.print(title, markup=False, highlight=False)
    _cli.console.print(f"target: {report.target}", markup=False, highlight=False)
    if report.removed:
        verb = "would remove" if dry_run else "removed"
        _cli.console.print(
            f"{verb} {_counted(len(report.removed), 'bundled source file')}:"
        )
        for rel in report.removed:
            _cli.console.print(f"  - {rel}", markup=False, highlight=False)
    if report.data_removed:
        verb = "would remove" if dry_run else "removed"
        _cli.console.print(f"{verb} .vault/data/ index data")
    sync_pruned = sum(getattr(r, "pruned", 0) for r in report.sync_results)
    if sync_pruned:
        _render_sync_summary(0, 0, sync_pruned)
    tc_action = getattr(report, "torch_config_action", "skipped")
    _cli.console.print(
        f"PyTorch configuration: {_action_label(tc_action)}",
        markup=False,
        highlight=False,
    )
    td_action = getattr(report, "torch_direct_dep_action", "skipped")
    if td_action not in ("skipped",):
        td_location = getattr(report, "torch_direct_dep_location", "")
        suffix = f" ({td_location})" if td_location else ""
        _cli.console.print(
            f"PyTorch dependency: {_action_label(td_action)}{suffix}",
            markup=False,
            highlight=False,
        )
    for conflict in getattr(report, "torch_config_conflicts", []):
        _cli.console.print(f"  conflict: {conflict}", markup=False, highlight=False)
    for warning in report.warnings:
        _print_warning_or_note(warning)
