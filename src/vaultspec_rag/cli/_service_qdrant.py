"""``server qdrant`` commands: install, status, clean.

The provisioning verb mirrors the project's sync vocabulary
(``created`` / ``updated`` / ``unchanged`` / ``skipped`` / ``failed``)
and the dry-run discipline; ``status`` is a bounded operator view;
``clean`` is destructive and gated on ``--yes`` with a dry-run
preview.
"""

import urllib.error
import urllib.request
from pathlib import Path
from typing import Annotated, Any

import typer

import vaultspec_rag.cli as _cli

from ..config import get_config
from ..qdrant_runtime import (
    QDRANT_SERVER_VERSION,
    ProvisionReport,
    QdrantProvisionAction,
    provision,
    provisioned_versions,
    resolve_binary,
)
from ._app import server_qdrant_app
from ._render import _emit_json
from ._service_status import _read_service_status


def _print_line(text: str) -> None:
    _cli.console.print(text, markup=False, highlight=False, soft_wrap=True)


def _readyz_probe(port: int) -> bool:
    """True when a qdrant server answers ready on the loopback port."""
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/readyz", timeout=2.0
        ) as resp:
            return int(resp.status) == 200
    except (urllib.error.URLError, OSError, ValueError) as exc:
        _cli.logger.debug("qdrant readyz probe failed on port %d: %s", port, exc)
        return False


def _render_install_report(report: ProvisionReport) -> None:
    _print_line(f"Action: {report.action}")
    _print_line(f"Version: {report.version}")
    if report.asset:
        _print_line(f"Asset: {report.asset}")
    if report.url:
        _print_line(f"URL: {report.url}")
    if report.binary is not None:
        _print_line(f"Binary: {report.binary}")
    if report.sha256:
        _print_line(f"SHA256: {report.sha256}")
    if report.message:
        _print_line(f"Detail: {report.message}")


@server_qdrant_app.command(
    "install",
    help=(
        "Download and verify the pinned qdrant server binary into the "
        "managed bin dir. Idempotent: a verified install reports "
        "'unchanged' with no network I/O."
    ),
)
def qdrant_install(
    upgrade: Annotated[
        bool,
        typer.Option(
            "--upgrade",
            help="Replace a stale or pin-divergent install.",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Preview the version, asset, URL, destination, and digest "
            "without downloading or writing anything.",
        ),
    ] = False,
    binary: Annotated[
        Path | None,
        typer.Option(
            "--binary",
            help="Register an operator-supplied binary instead of "
            "downloading (air-gapped escape hatch; no checksum pin applies).",
        ),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit one JSON envelope to stdout."),
    ] = False,
) -> None:
    """Provision the pinned qdrant server binary."""
    report = provision(upgrade=upgrade, dry_run=dry_run, binary=binary)
    failed = report.action == QdrantProvisionAction.FAILED

    if json_mode:
        _emit_json(
            not failed,
            "server.qdrant.install",
            data=report.to_dict(),
            **(
                {"error": str(report.action), "message": report.message}
                if failed
                else {}
            ),
        )
    else:
        _render_install_report(report)
    if failed:
        raise typer.Exit(code=1)


def _service_qdrant_block() -> dict[str, Any]:
    """The running service's recorded qdrant child, if any."""
    status = _read_service_status()
    if status is None:
        return {"recorded": False}
    block: dict[str, Any] = {"recorded": "qdrant_pid" in status}
    for key in ("qdrant_pid", "qdrant_alive", "qdrant_port"):
        if key in status:
            block[key] = status[key]
    return block


def _qdrant_status_payload() -> dict[str, Any]:
    cfg = get_config()
    resolved = resolve_binary()
    port = int(cfg.qdrant_port)
    return {
        "pinned_version": QDRANT_SERVER_VERSION,
        "server_mode_default": bool(cfg.qdrant_server),
        "port": port,
        "ready": _readyz_probe(port),
        "active_binary": (
            {
                "path": str(resolved.path),
                "source": resolved.source,
                "version": resolved.version or None,
            }
            if resolved is not None
            else None
        ),
        "provisioned": provisioned_versions(),
        "service": _service_qdrant_block(),
    }


@server_qdrant_app.command(
    "status",
    help=(
        "Show the pinned version, the active binary and its resolution "
        "source, provisioned versions (bounded), and live server state."
    ),
)
def qdrant_status(
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit one JSON envelope to stdout."),
    ] = False,
) -> None:
    """Show qdrant runtime provisioning and liveness state."""
    payload = _qdrant_status_payload()

    if json_mode:
        _emit_json(True, "server.qdrant.status", data=payload)
        return

    _print_line(f"Pinned version: {payload['pinned_version']}")
    active = payload["active_binary"]
    if isinstance(active, dict):
        _print_line(f"Active binary: {active['path']} (source: {active['source']})")
    else:
        _print_line("Active binary: none")
        _print_line("Next action:")
        _print_line("  vaultspec-rag server qdrant install")
    _print_line(f"Server port: {payload['port']}")
    _print_line(f"Server ready: {'yes' if payload['ready'] else 'no'}")
    service = payload["service"]
    if isinstance(service, dict) and service.get("recorded"):
        _print_line(
            f"Service child: pid {service.get('qdrant_pid')} "
            f"(alive: {service.get('qdrant_alive')}, "
            f"port: {service.get('qdrant_port')})"
        )
    else:
        _print_line("Service child: none recorded")
    provisioned = payload["provisioned"]
    if isinstance(provisioned, list) and provisioned:
        _print_line("Provisioned versions:")
        for entry in provisioned:
            marker = " (current pin)" if entry.get("current") else ""
            _print_line(f"  {entry.get('version')} - {entry.get('source')}{marker}")
    else:
        _print_line("Provisioned versions: none")


@server_qdrant_app.command(
    "clean",
    help=(
        "Delete provisioned qdrant binaries from the managed bin dir. "
        "Destructive: requires --yes. --keep-current preserves the "
        "pinned version. Server storage (collections) is never touched."
    ),
)
def qdrant_clean(
    keep_current: Annotated[
        bool,
        typer.Option(
            "--keep-current",
            help="Preserve the install matching the pinned version.",
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Confirm deletion."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview what would be removed."),
    ] = False,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit one JSON envelope to stdout."),
    ] = False,
) -> None:
    """Remove provisioned qdrant binaries (gated on ``--yes``)."""
    targets = [
        str(entry["version"])
        for entry in provisioned_versions()
        if not (keep_current and entry.get("current"))
    ]

    if dry_run or not yes:
        _render_clean_preview(targets, dry_run=dry_run, json_mode=json_mode)
        return

    removed = _perform_clean(keep_current=keep_current, json_mode=json_mode)
    if json_mode:
        _emit_json(True, "server.qdrant.clean", data={"removed": removed})
    elif removed:
        _print_line(f"Removed: {', '.join(removed)}")
    else:
        _print_line("Nothing to remove.")


def _render_clean_preview(
    targets: list[str],
    *,
    dry_run: bool,
    json_mode: bool,
) -> None:
    """Render the gated/dry-run preview; exits 1 when --yes is missing."""
    detail = "Dry run - nothing removed." if dry_run else "Re-run with --yes to delete."
    if json_mode:
        _emit_json(
            True,
            "server.qdrant.clean",
            data={"would_remove": targets, "removed": [], "detail": detail},
        )
    else:
        if targets:
            _print_line(f"Would remove: {', '.join(targets)}")
        else:
            _print_line("Nothing to remove.")
        _print_line(detail)
    if not dry_run and targets:
        raise typer.Exit(code=1)


def _perform_clean(*, keep_current: bool, json_mode: bool) -> list[str]:
    """Run the destructive removal, converting OSError to exit 1."""
    from ..qdrant_runtime import clean_provisioned

    try:
        return clean_provisioned(keep_current=keep_current)
    except OSError as exc:
        message = (
            f"Failed to remove a provisioned install: {exc}. A running "
            "qdrant child may be holding the binary - stop the service "
            "first (vaultspec-rag server stop)."
        )
        if json_mode:
            _emit_json(
                False,
                "server.qdrant.clean",
                error="clean_failed",
                message=message,
            )
        else:
            _print_line(message)
        raise typer.Exit(code=1) from exc
