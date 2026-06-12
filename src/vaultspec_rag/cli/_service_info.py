"""``server info``: consolidated read-only service state.

Tier-1 observability subcommand (``service-observability`` ADR, plan
P02). Calls the service-state admin endpoint through the shared HTTP
admin client and renders a plain summary (or the JSON envelope).
Service-not-running yields exit code 3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, NoReturn, cast

import typer

import vaultspec_rag.cli as _cli

from ._app import server_app
from ._http_search import _try_http_admin
from ._render import _emit_json, _emit_json_error_and_exit
from ._service_status import _default_service_port


@server_app.command("info")
def service_info(
    ctx: typer.Context,
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    project_root: Annotated[
        Path | None,
        typer.Option(
            "--project-root",
            "--root",
            help=(
                "Project root for the consolidated service state. "
                "Defaults to global --target when provided."
            ),
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit one JSON envelope instead of a summary."),
    ] = False,
) -> None:
    """Show a consolidated snapshot of the running service's state."""
    resolved_port = port if port is not None else _default_service_port()
    if resolved_port is None:
        _exit_service_info_not_running(json_mode)

    effective_root = project_root or _global_target_from_context(ctx)
    if effective_root is None:
        _exit_project_root_required(json_mode)

    result = _try_http_admin(
        "get_service_state",
        {"project_root": str(effective_root)},
        resolved_port,
    )
    if result is None:
        _exit_service_info_not_running(json_mode)

    if result.get("ok") is False:
        _exit_service_info_error(result, json_mode)

    if json_mode:
        _emit_json(True, "service.info", data=result)
        return

    _render_service_info(result)


def _global_target_from_context(ctx: typer.Context) -> Path | None:
    root_ctx = cast("Any", ctx.find_root())
    obj = getattr(root_ctx, "obj", None)
    if isinstance(obj, dict):
        value = cast("dict[str, object]", obj).get("target")
        if isinstance(value, Path):
            return value
    return None


def _exit_service_info_not_running(json_mode: bool) -> NoReturn:
    message = "Service is not running. Start it with `vaultspec-rag server start`."
    if json_mode:
        _emit_json_error_and_exit("service.info", "service_not_running", message, 3)
    _cli.console.print(
        "[red]Service is not running.[/] "
        "Start it with [bold]vaultspec-rag server start[/].",
    )
    raise typer.Exit(3)


def _exit_project_root_required(json_mode: bool) -> NoReturn:
    message = (
        "Project root is required. Pass global --target or "
        "`vaultspec-rag server info --project-root <path>`."
    )
    if json_mode:
        _emit_json_error_and_exit(
            "service.info",
            "project_root_required",
            message,
            2,
        )
    _cli.console.print(f"[bold red]Error:[/] {message}")
    raise typer.Exit(2)


def _exit_service_info_error(
    result: dict[str, Any],
    json_mode: bool,
) -> NoReturn:
    error = str(result.get("error", "service_error"))
    message = str(result.get("message", "RAG service returned an error."))
    if json_mode:
        _emit_json_error_and_exit(
            "service.info",
            error,
            message,
            1,
            data=result,
        )
    _cli.console.print(f"[bold red]Error:[/] {message}")
    _cli.console.print(f"[dim]code={error}[/]")
    raise typer.Exit(1)


def _render_service_info(result: dict[str, Any]) -> None:
    raw_index = result.get("index")
    index = cast("dict[str, object]", raw_index) if isinstance(raw_index, dict) else {}
    raw_projects = result.get("projects")
    projects_data = (
        cast("dict[str, object]", raw_projects)
        if isinstance(raw_projects, dict)
        else {}
    )
    raw_watcher = result.get("watcher")
    watcher = (
        cast("dict[str, object]", raw_watcher) if isinstance(raw_watcher, dict) else {}
    )

    _cli.console.print("Service state")
    _cli.console.print(
        f"Index: vault_docs={index.get('vault_count', '?')} "
        f"code_chunks={index.get('code_count', '?')}",
        markup=False,
        highlight=False,
    )
    _cli.console.print(
        f"Target: {index.get('target_dir', '')}",
        markup=False,
        highlight=False,
        soft_wrap=True,
    )
    _cli.console.print(f"GPU: vram_gb={index.get('vram_gb', '?')}")

    raw_slots = projects_data.get("projects")
    slots: list[object] = (
        cast("list[object]", raw_slots) if isinstance(raw_slots, list) else []
    )
    _cli.console.print(
        f"Project slots: {len(slots)}/{projects_data.get('max_projects', '?')}",
        markup=False,
        highlight=False,
    )

    enabled = bool(watcher.get("watch_enabled", False))
    raw_watching = watcher.get("watching")
    watching: list[object] = (
        cast("list[object]", raw_watching) if isinstance(raw_watching, list) else []
    )
    mode = "enabled" if enabled else "disabled (pull-only)"
    _cli.console.print(
        f"Index updates: {mode}; watched_roots={len(watching)}",
        markup=False,
        highlight=False,
    )
