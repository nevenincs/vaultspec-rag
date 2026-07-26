"""Output rendering: JSON envelopes, backend-contract rows, and human output.

Holds the shared ``--json`` envelope helpers plus the renderers for
search results and install/uninstall reports. Renderers read
``console`` from the package namespace at call time, which keeps this
module out of the import cycle an import-time binding of ``_core``
would create.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

import typer

import vaultspec_rag.cli as _cli

from ._cli_format import _counted_unit

if TYPE_CHECKING:
    from ..commands._provision import ProvisionOutcome
    from ..serviceclient._compat import ServiceVersionVerdict

__all__ = [
    "_display_port_unreachable_error",
    "_display_search_results",
    "_display_service_error",
    "_display_service_not_running",
    "_display_service_version_error",
    "_emit_json",
    "_emit_json_error_and_exit",
    "_format_local_index_busy_message",
    "_plain",
    "_plain_line",
    "_render_install_report",
    "_render_uninstall_report",
]


def _plain(text: str, *, soft_wrap: bool | None = None) -> None:
    """Print one literal operator line: no Rich markup, no auto-highlighting.

    Operator output is data - paths, ids, commands, service messages - so Rich
    must not read a bracketed substring as markup or restyle numbers and paths
    inside it. That made ``markup=False, highlight=False`` the standing idiom on
    nearly two hundred call sites; naming it once keeps a new line from
    acquiring styling by simply forgetting them.

    ``soft_wrap`` defaults to ``None`` rather than ``False`` so an unspecified
    call defers to the console's own setting, exactly as omitting it does.
    The console is read at call time, so a test that swaps
    ``vaultspec_rag.cli.console`` still observes the substitution.
    """
    _cli.console.print(text, markup=False, highlight=False, soft_wrap=soft_wrap)


def _plain_line(text: str) -> None:
    """Print one operator line that a live progress region may be open around.

    Lines emitted from inside a reporting block cannot use ``typer.echo``:
    Rich erases its own frame before a line only when the line arrives through
    its console, and a raw stream write is invisible to that bookkeeping, so
    the frame erases it instead. Soft wrapping is what keeps a long path or
    command from being folded mid-token on a narrow terminal.

    Result tables rendered after the block closes have no such constraint;
    this is for the lines that do.
    """
    _plain(text, soft_wrap=True)


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


def _address_line(port: object) -> str:
    """Return the operator's "Address:" line for a loopback service port.

    One template with sixteen callers. Eight of them used to build the string
    inline, so the label, the host rendering, and the scheme were a rename
    away from disagreeing across the CLI's own output.
    """
    return f"Address: http://127.0.0.1:{port}"


def _display_service_not_running(port: int | None = None) -> None:
    if port is not None:
        _plain(_address_line(port))
    _plain("Service is not running. Start it with `vaultspec-rag server start`.")


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
    _plain(f"Error: {_human_service_error_message(message)}")
    if error != "http_search_timeout":
        _plain(f"Code: {error}")
    db_path = payload.get("db_path")
    if db_path:
        _plain(f"Index data: {db_path}")
    _display_service_diagnostic_summary(payload.get("diagnostics"))
    remediation = payload.get("remediation")
    if isinstance(remediation, list) and remediation:
        _cli.console.print("Next actions:")
        for item in cast("list[object]", remediation):
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
    diagnostics_map = cast("dict[str, object]", diagnostics)
    health = diagnostics_map.get("health")
    jobs = diagnostics_map.get("jobs")
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
        return _unavailable_diagnostic_text(health, "request check")
    raw_status = health.get("status")
    if not isinstance(raw_status, str) or not raw_status or raw_status == "unknown":
        ready_text = "request status not reported by service"
    else:
        ready_text = (
            "requests ready" if raw_status == "ready" else raw_status.replace("_", " ")
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
            return "no active index jobs"
        word = "job" if running == 1 else "jobs"
        return f"{running} active index {word}"
    return "active job count not reported by service"


def _unavailable_diagnostic_text(data: dict[str, object], label: str) -> str:
    error = str(data.get("error", "")).strip()
    message = str(data.get("message", "")).strip()
    if error == "TimeoutError" or "timed out" in message.lower():
        return f"{label} timed out"
    if message:
        return f"{label} not reported by service ({message})"
    return f"{label} not reported by service"


def _display_search_results(
    results: list[dict[str, object]],
    search_type: str,
    via: Literal["service", "in-process"] = "service",
    *,
    show_scores: bool = False,
    root: Path | None = None,
) -> None:
    """Display search results as stable, readable records.

    Args:
        results: List of result dicts with ``score``, ``path``,
            ``snippet``, and optional ``line_start`` keys.
        search_type: Search source label retained for API compatibility
            (e.g. ``vault``, ``code``).
        via: Transport path indicator retained for API compatibility
            (e.g. ``service``, ``in-process``).
        show_scores: Include numeric relevance scores after the rank.
        root: Workspace root used to read full source lines when a
            result includes a local relative path and line range.

    """
    _ = search_type, via
    for rank, result in enumerate(results, start=1):
        location = _search_result_location(result)
        line = f"{rank}. {location}"
        if show_scores:
            line += f" (score {_search_result_score(result):.4f})"
        _plain(line, soft_wrap=True)
        meta_line = _search_result_meta_line(result)
        if meta_line is not None:
            _plain(f"   {meta_line}", soft_wrap=True)
        for text_line in _search_result_text_lines(result, root=root):
            _plain(f"   {text_line}", soft_wrap=True)


def _search_result_meta_line(result: dict[str, object]) -> str | None:
    """Render the vault frontmatter line: type, feature, status, date, related.

    Returns ``None`` for results without a ``doc_type`` (codebase hits), so only
    vault documents gain the metadata line. Surfaces the pipeline context that
    turns a hit into an orientation entry point - especially ``status`` (so a
    superseded ADR is visible as such) and the ``related`` lineage edges.
    """
    doc_type = _non_empty_result_string(result, "doc_type")
    if doc_type is None:
        return None
    parts: list[str] = [doc_type]
    feature = _non_empty_result_string(result, "feature")
    if feature is not None:
        parts.append(f"feature: {feature}")
    status = _non_empty_result_string(result, "status")
    if status is not None:
        parts.append(f"status: {status}")
    date = _non_empty_result_string(result, "date")
    if date is not None:
        parts.append(date)
    related = result.get("related")
    if isinstance(related, list) and related:
        related_items = cast("list[object]", related)
        shown = ", ".join(str(x) for x in related_items[:5])
        suffix = ", ..." if len(related_items) > 5 else ""
        parts.append(f"related: {shown}{suffix}")
    return " | ".join(parts)


def _display_text_lines(value: object) -> list[str]:
    return [line.rstrip() for line in str(value).splitlines()]


def _search_result_text_lines(
    result: dict[str, object], *, root: Path | None
) -> list[str]:
    full_text = _non_empty_result_string(result, "rerank_text")
    if full_text is not None:
        return _display_text_lines(full_text)
    source_lines = _source_line_text_lines(result, root=root)
    if source_lines:
        return source_lines
    return _display_text_lines(result.get("snippet", ""))


def _source_line_text_lines(
    result: dict[str, object], *, root: Path | None
) -> list[str]:
    path_text = _non_empty_result_string(result, "source_path") or (
        _non_empty_result_string(result, "path")
    )
    line_start = result.get("line_start")
    if path_text is None or not isinstance(line_start, int):
        return []
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
        return []
    return lines[line_start - 1 : end]


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
        or "location-not-reported"
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
                f"--allow-fallback (one local user only)."
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
    _plain(
        f"Service on port {port} is unreachable.\n"
        f"The CLI will not silently run {command} locally because that would "
        f"open the local search index directly "
        f"and block other users waiting on the service.\n"
        f"Next actions:\n"
        f"  1. Check status:  vaultspec-rag server status\n"
        f"  2. Start service: vaultspec-rag server start\n"
        f"  3. Or run locally anyway: re-run with "
        f"--allow-fallback (one user only)."
    )


def _display_service_version_error(
    verdict: ServiceVersionVerdict,
    *,
    command: str,
    json_mode: bool,
) -> None:
    """Refuse to send *command* to a daemon of a different release.

    The CLI half of the release gate the MCP applies in its port precondition.
    Both read the same verdict, so the error code, the diagnosis and the
    remediation are the verdict's - only the presentation differs, which is what
    keeps one condition from acquiring two contracts.

    Refusing rather than proceeding is the point: an unrecognised request field
    is dropped by the daemon rather than rejected, so continuing would answer
    over a different candidate set with no sign anything was lost.
    """
    remediation = [
        *verdict.remediation(),
        "vaultspec-rag server status",
    ]
    if json_mode:
        _emit_json_error_and_exit(
            command,
            verdict.error_code() or "service_version_mismatch",
            f"Refusing to {command} against the running service: {verdict.reason()}.",
            1,
            version=verdict.to_dict(),
            remediation=remediation,
        )
        return
    _plain(
        f"Refusing to {command} against the running service.\n"
        f"{verdict.reason().capitalize()}.\n"
        f"A daemon from another release drops request fields it does not know "
        f"rather than rejecting them, so the answer would be computed over a "
        f"different candidate set with nothing to show it.\n"
        f"Next actions:\n"
        f"  1. Restart the service: vaultspec-rag server stop, then "
        f"vaultspec-rag server start\n"
        f"  2. Confirm the release:  vaultspec-rag server status"
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
    parts: list[str] = []
    if added:
        parts.append(f"added {added}")
    if updated:
        parts.append(f"updated {updated}")
    if removed:
        parts.append(f"removed {removed}")
    if parts:
        _plain(f"tool integrations: {', '.join(parts)}")


def _render_provider_outcome(provider: str, outcome: dict[str, object]) -> None:
    parts = [
        f"{label} {outcome[label]}"
        for label in (
            "added",
            "updated",
            "unchanged",
            "skipped",
            "pruned",
            "errored",
        )
        if isinstance(outcome.get(label), int) and outcome[label]
    ]
    summary = ", ".join(parts) if parts else "no changes"
    _plain(f"{provider.capitalize()} MCP: {summary}")
    for label in ("warnings", "errors"):
        messages = outcome.get(label)
        if isinstance(messages, list):
            for message in cast("list[object]", messages):
                _plain(f"  {label[:-1]}: {message}")


def _render_provider_sync(report: Any) -> None:
    """Render the same per-provider MCP outcomes exposed by report JSON."""
    data = report.to_dict()
    providers = data.get("sync_providers")
    if isinstance(providers, dict):
        for provider, raw_outcome in cast("dict[object, object]", providers).items():
            if isinstance(provider, str) and isinstance(raw_outcome, dict):
                _render_provider_outcome(
                    provider, cast("dict[str, object]", raw_outcome)
                )
    top_level_errors = data.get("mcp_errors")
    if isinstance(top_level_errors, list):
        for error in cast("list[object]", top_level_errors):
            _plain(f"MCP lifecycle error: {error}")


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
    prefix = "Note" if text.startswith("dry-run preview:") else "Warning"
    _plain(f"{prefix}: {text}")


def _render_mcp_extra(report: Any) -> None:
    """Render the structured MCP optional-dependency lifecycle result."""
    action = getattr(report, "mcp_extra_action", "skipped")
    if action == "skipped":
        return
    location = getattr(report, "mcp_extra_location", "")
    suffix = f" ({location})" if location else ""
    _plain(f"MCP optional dependency: {_action_label(action)}{suffix}")


def _render_install_report(report: Any) -> None:
    """Render an install report as plain CLI lines."""
    title = {
        "install": "vaultspec-rag installed",
        "upgrade": "vaultspec-rag upgraded",
        "dry_run": "vaultspec-rag install (dry-run)",
    }.get(report.action, "vaultspec-rag install")
    dry_run = report.action == "dry_run"
    _plain(title)
    _plain(f"Target: {report.target}")
    if report.created_dirs:
        verb = "would create" if dry_run else "created"
        _cli.console.print(
            f"{verb} "
            f"{_counted_unit(len(report.created_dirs), 'directory', 'directories')}"
        )
    if report.seeded:
        verb = "would seed" if dry_run else "seeded"
        _cli.console.print(
            f"{verb} {_counted_unit(len(report.seeded), 'bundled file')}:"
        )
        for rel, action in report.seeded:
            _plain(f"  {action} {rel}")
    sync_added = sum(getattr(r, "added", 0) for r in report.sync_results)
    sync_updated = sum(getattr(r, "updated", 0) for r in report.sync_results)
    sync_pruned = sum(getattr(r, "pruned", 0) for r in report.sync_results)
    _render_sync_summary(sync_added, sync_updated, sync_pruned)
    _render_provider_sync(report)
    _render_mcp_extra(report)
    tc_action = getattr(report, "torch_config_action", "skipped")
    _plain(f"PyTorch configuration: {_action_label(tc_action)}")
    td_action = getattr(report, "torch_direct_dep_action", "skipped")
    if td_action not in ("skipped",):
        td_location = getattr(report, "torch_direct_dep_location", "")
        suffix = f" ({td_location})" if td_location else ""
        _plain(f"PyTorch dependency: {_action_label(td_action)}{suffix}")
    for conflict in getattr(report, "torch_config_conflicts", []):
        _plain(f"  conflict: {conflict}")
    tsync = getattr(report, "torch_sync_action", "skipped")
    if tsync not in ("skipped",):
        _plain(f"uv sync --reinstall-package torch: {tsync}")
    _render_provisioning_outcome(getattr(report, "provision_outcome", None))
    for warning in report.warnings:
        _print_warning_or_note(warning)


# Human labels for the heterogeneous provisioning steps. The torch step
# is the only two-phase one: a ``created``/``updated`` torch result with
# ``sync_pending`` reads as "configured, sync pending", distinct from a
# fetched binary that is terminally "downloaded"/"unchanged". Driven by a
# flat table so the renderer stays a single bounded loop.
_PROVISION_STEP_LABELS = {
    "torch": "PyTorch",
    "models": "Models",
    "qdrant": "Qdrant binary",
}
_PROVISION_ACTION_LABELS = {
    "created": "downloaded",
    "updated": "updated",
    "unchanged": "already present",
    "skipped": "skipped",
    "failed": "failed",
    "dry_run": "preview only",
}


def _provision_step_label(step: object) -> str:
    text = str(step)
    return _PROVISION_STEP_LABELS.get(text, text)


def _provision_action_phrase(step: dict[str, object]) -> str:
    """Phrase one provisioning step honestly, surfacing torch's two phases.

    A ``created``/``updated`` torch step carries ``sync_pending=True`` and
    must read as "configured, sync pending" - the half-done state the front
    door must communicate - rather than a binary's terminal "downloaded".
    """
    action = str(step.get("action", ""))
    if step.get("sync_pending") and action in ("created", "updated"):
        return "configured, sync pending"
    return _PROVISION_ACTION_LABELS.get(action, action.replace("_", " "))


def _render_provisioning_outcome(outcome: ProvisionOutcome | None) -> None:
    """Render the heterogeneous per-dependency provisioning outcome.

    Bounded and honest: one line per considered dependency through the
    shared sync vocabulary, the torch two-phase "configured, sync
    pending" wording kept distinct from a binary's "downloaded", and the
    detail appended so a ``skipped`` step always carries its reason.
    Reads the JSON-serialisable ``to_dict`` view so the human and JSON
    reports describe exactly the same outcome.
    """
    if outcome is None:
        return
    data = outcome.to_dict()
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        return
    _plain(f"Provisioning: {data.get('status', 'unchanged')}")
    for step in cast("list[object]", steps):
        if not isinstance(step, dict):
            continue
        step_map = cast("dict[str, object]", step)
        label = _provision_step_label(step_map.get("step", ""))
        phrase = _provision_action_phrase(step_map)
        detail = str(step_map.get("detail", "")).strip()
        suffix = f" ({detail})" if detail else ""
        _plain(f"  {label}: {phrase}{suffix}")


def _render_uninstall_report(report: Any) -> None:
    """Render an uninstall report as plain CLI lines."""
    title = {
        "uninstall": "vaultspec-rag uninstalled",
        "dry_run": "vaultspec-rag uninstall (dry-run; use --force to apply)",
    }.get(report.action, "vaultspec-rag uninstall")
    dry_run = report.action == "dry_run"
    _plain(title)
    _plain(f"Target: {report.target}")
    if report.removed:
        verb = "would remove" if dry_run else "removed"
        _cli.console.print(
            f"{verb} {_counted_unit(len(report.removed), 'bundled source file')}:"
        )
        for rel in report.removed:
            _plain(f"  - {rel}")
    if report.data_removed:
        verb = "would remove" if dry_run else "removed"
        _cli.console.print(f"{verb} .vault/data/ index data")
    sync_pruned = sum(getattr(r, "pruned", 0) for r in report.sync_results)
    if sync_pruned:
        _render_sync_summary(0, 0, sync_pruned)
    _render_provider_sync(report)
    _render_mcp_extra(report)
    tc_action = getattr(report, "torch_config_action", "skipped")
    _plain(f"PyTorch configuration: {_action_label(tc_action)}")
    td_action = getattr(report, "torch_direct_dep_action", "skipped")
    if td_action not in ("skipped",):
        td_location = getattr(report, "torch_direct_dep_location", "")
        suffix = f" ({td_location})" if td_location else ""
        _plain(f"PyTorch dependency: {_action_label(td_action)}{suffix}")
    for conflict in getattr(report, "torch_config_conflicts", []):
        _plain(f"  conflict: {conflict}")
    for warning in report.warnings:
        _print_warning_or_note(warning)
