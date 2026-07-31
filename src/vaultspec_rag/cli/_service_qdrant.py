"""``server qdrant`` commands: install, status, clean.

The provisioning verb mirrors the project's sync vocabulary
(``created`` / ``updated`` / ``unchanged`` / ``skipped`` / ``failed``)
and the dry-run discipline; ``status`` is a bounded operator view;
``clean`` is destructive and gated on ``--yes`` with a dry-run
preview.
"""

from pathlib import Path
from typing import Annotated, Any, NoReturn, cast

import typer

from .._operator_commands import server_start_command
from .._sync_vocabulary import ProvisionAction
from ..config._settings import get_config
from ..qdrant_runtime._constants import (
    QDRANT_SERVER_VERSION,
    ProvisionReport,
)
from ..qdrant_runtime._provision import provision, provisioned_versions
from ..qdrant_runtime._resolve import probe_qdrant_endpoint, resolve_binary
from ..serviceclient._discovery import read_service_status
from ._app import JsonMode, server_qdrant_app
from ._progress import StartupStatusReporter
from ._render import _emit_json, _plain_line, _print_next_action, address_line


def _action_label(action: object) -> str:
    return str(action).replace("_", " ")


def _render_install_report(report: ProvisionReport) -> None:
    _plain_line(f"Action: {_action_label(report.action)}")
    _plain_line(f"Version: {report.version}")
    if report.asset:
        _plain_line(f"Release package: {report.asset}")
    if report.url:
        _plain_line(f"Download: {report.url}")
    if report.binary is not None:
        _plain_line(f"Install: {report.binary}")
    if report.sha256:
        _plain_line(f"SHA256: {report.sha256}")
    if report.message:
        _plain_line(f"Detail: {report.message}")


@server_qdrant_app.command(
    "install",
    help=(
        "Download and verify the managed Qdrant server. If the requested "
        "version is already installed, nothing is downloaded."
    ),
)
def qdrant_install(
    upgrade: Annotated[
        bool,
        typer.Option(
            "--upgrade",
            help="Replace an installed Qdrant server when the managed version changed.",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help=(
                "Preview the version, release package, download, install path, "
                "and digest without downloading or writing anything."
            ),
        ),
    ] = False,
    binary: Annotated[
        Path | None,
        typer.Option(
            "--binary",
            help=(
                "Register an operator-supplied Qdrant executable instead of "
                "downloading the managed release."
            ),
        ),
    ] = None,
    json_mode: JsonMode = False,
) -> None:
    """Install the managed Qdrant server."""
    # A first install downloads a native archive, hashes it, and unpacks it,
    # none of which said anything before this. The report is rendered after the
    # block so the terminal outcome never has to share a line with a live
    # region, and ``--json`` keeps the reporter silent so exactly one envelope
    # reaches stdout.
    with StartupStatusReporter(json_mode=json_mode) as progress:
        progress.announce("Installing the managed Qdrant server...")
        report = provision(
            upgrade=upgrade,
            dry_run=dry_run,
            binary=binary,
            on_progress=progress.stage,
        )
    failed = report.action == ProvisionAction.FAILED

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
    """The running service's recorded Qdrant process, if any."""
    status = read_service_status()
    if status is None:
        return {"recorded": False}
    block: dict[str, object] = {"recorded": "qdrant_pid" in status}
    for key in ("qdrant_pid", "qdrant_alive", "qdrant_port"):
        if key in status:
            block[key] = status[key]
    return block


def _qdrant_status_payload(port: int | None = None) -> dict[str, Any]:
    cfg = get_config()
    resolved = resolve_binary()
    service = _service_qdrant_block()
    service_port: object = service.get("qdrant_port")
    qdrant_port = int(
        port
        if port is not None
        else service_port
        if isinstance(service_port, int | float | str)
        else cfg.qdrant_port
    )
    return {
        "pinned_version": QDRANT_SERVER_VERSION,
        "server_mode_default": bool(cfg.qdrant_server),
        "port": qdrant_port,
        "ready": probe_qdrant_endpoint(qdrant_port).ready,
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
        "service": service,
    }


def _print_qdrant_install_and_state(payload: dict[str, object]) -> None:
    active = payload["active_binary"]
    if isinstance(active, dict):
        active_binary = cast("dict[str, object]", active)
        _plain_line(f"Executable: {active_binary['path']}")
    else:
        _plain_line("Executable: not installed")
        _print_next_action("vaultspec-rag server qdrant install")
    _plain_line(address_line(payload["port"]))
    if payload["ready"]:
        _plain_line("Connection: accepting requests")
        return
    _plain_line("Connection: not accepting requests")
    if isinstance(active, dict):
        _print_next_action(server_start_command(qdrant=True))


def _print_qdrant_process(service: object) -> None:
    if not isinstance(service, dict):
        _plain_line("Process: not started by vaultspec-rag")
        return
    service_block = cast("dict[str, object]", service)
    if not service_block.get("recorded"):
        _plain_line("Process: not started by vaultspec-rag")
        return
    alive_flag = service_block.get("qdrant_alive")
    alive = (
        "running, started by vaultspec-rag"
        if alive_flag is True
        else "not running"
        if alive_flag is False
        else "state not reported"
    )
    _plain_line(f"Process: {alive}")
    _plain_line(f"Process ID: {service_block.get('qdrant_pid', 'not reported')}")
    _plain_line(f"Process port: {service_block.get('qdrant_port', 'not reported')}")


def _print_qdrant_versions(provisioned: object) -> None:
    if not (isinstance(provisioned, list) and provisioned):
        _plain_line("Available installs: none")
        return
    _plain_line("Available installs:")
    for raw_entry in cast("list[object]", provisioned):
        if not isinstance(raw_entry, dict):
            continue
        entry = cast("dict[str, object]", raw_entry)
        marker = " (current)" if entry.get("current") else ""
        source = (
            "downloaded release"
            if entry.get("source") == "download"
            else entry.get("source")
        )
        _plain_line(f"  {entry.get('version')} - {source}{marker}")


@server_qdrant_app.command(
    "status",
    help=("Show the managed Qdrant executable, address, connection, and process."),
)
def qdrant_status(
    port: Annotated[
        int | None,
        typer.Option(
            "--port",
            min=1,
            max=65535,
            help="Qdrant HTTP port to check.",
        ),
    ] = None,
    json_mode: JsonMode = False,
) -> None:
    """Show Qdrant runtime install and liveness state."""
    payload = _qdrant_status_payload(port)

    if json_mode:
        _emit_json(True, "server.qdrant.status", data=payload)
        return

    _plain_line("Qdrant storage service")
    _plain_line(f"Managed version: {payload['pinned_version']}")
    _print_qdrant_install_and_state(payload)
    _print_qdrant_process(payload["service"])
    _print_qdrant_versions(payload["provisioned"])


@server_qdrant_app.command(
    "clean",
    help=(
        "Delete managed Qdrant server installs. Destructive: requires --yes. "
        "--keep-current preserves the current managed version. "
        "Index data is never touched."
    ),
)
def qdrant_clean(
    keep_current: Annotated[
        bool,
        typer.Option(
            "--keep-current",
            help="Preserve the current managed Qdrant version.",
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Confirm deletion of managed Qdrant installs."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview what would be removed."),
    ] = False,
    json_mode: JsonMode = False,
) -> None:
    """Remove managed Qdrant installs (gated on ``--yes``)."""
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
        _plain_line(f"Removed: {', '.join(removed)}")
    else:
        _plain_line("Nothing to remove.")


def _render_clean_preview(
    targets: list[str],
    *,
    dry_run: bool,
    json_mode: bool,
) -> None:
    """Render the gated/dry-run preview; exits 1 when --yes is missing."""
    detail = (
        "Dry run - no managed Qdrant installs were removed."
        if dry_run
        else "Re-run with --yes to delete these managed Qdrant installs."
    )
    if json_mode:
        _emit_json(
            True,
            "server.qdrant.clean",
            data={"would_remove": targets, "removed": [], "detail": detail},
        )
    else:
        if targets:
            _plain_line(f"Would remove installed Qdrant versions: {', '.join(targets)}")
        else:
            _plain_line("No managed Qdrant installs would be removed.")
        _plain_line(detail)
    if not dry_run and targets:
        raise typer.Exit(code=1)


def _perform_clean(*, keep_current: bool, json_mode: bool) -> list[str]:
    """Run the destructive removal, converting OSError to exit 1."""
    from ..qdrant_runtime._provision import clean_provisioned

    try:
        return clean_provisioned(keep_current=keep_current)
    except OSError as exc:
        message = (
            f"Failed to remove a managed Qdrant install: {exc}. A running "
            "Qdrant process may still be using it - stop the service first "
            "(vaultspec-rag server stop)."
        )
        if json_mode:
            _emit_json(
                False,
                "server.qdrant.clean",
                error="clean_failed",
                message=message,
            )
        else:
            _plain_line(message)
        raise typer.Exit(code=1) from exc


def _fail_quarantine(error: str, message: str, *, json_mode: bool) -> NoReturn:
    """Emit a quarantine failure (JSON or text) and exit non-zero."""
    if json_mode:
        _emit_json(False, "server.qdrant.quarantine", error=error, message=message)
    else:
        _plain_line(message)
    raise typer.Exit(code=1)


def _emit_quarantine_listing(collections: list[str], *, json_mode: bool) -> None:
    """Print (or emit as JSON) the shared store's collection names."""
    if json_mode:
        _emit_json(
            True,
            "server.qdrant.quarantine",
            data={"collections": collections},
        )
        return
    _plain_line("Qdrant collections in the shared store")
    if not collections:
        _plain_line("  (none)")
    for name in collections:
        _plain_line(f"  {name}")


@server_qdrant_app.command(
    "quarantine",
    help=(
        "Move a corrupt collection out of the shared store so the server can "
        "start again. Run with no name to list collections; name one to "
        "quarantine it (requires --yes). The quarantined collection re-indexes "
        "on its next use; nothing is deleted."
    ),
)
def qdrant_quarantine(
    collection: Annotated[
        str | None,
        typer.Argument(help="Collection to quarantine; omit to list the store."),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Confirm moving the named collection aside."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview the move without touching the store."),
    ] = False,
    json_mode: JsonMode = False,
) -> None:
    """List the shared store's collections, or quarantine a named one.

    The operator escape hatch: when the supervised start cannot identify a
    corrupt collection automatically, an
    operator lists the store and quarantines the culprit by name. The move is
    reversible (the files are preserved under ``quarantine/``).
    """
    from ..qdrant_runtime._supervise import (
        _list_on_disk_collections,  # pyright: ignore[reportPrivateUsage]  # intra-package sibling module: shared delegation seam
        _quarantine_collection,  # pyright: ignore[reportPrivateUsage]  # intra-package sibling module: shared delegation seam
    )

    storage = Path(str(get_config().qdrant_storage_dir)).expanduser()
    collections = sorted(_list_on_disk_collections(storage))

    if collection is None:
        _emit_quarantine_listing(collections, json_mode=json_mode)
        return

    if collection not in collections:
        _fail_quarantine(
            "unknown_collection",
            f"Collection {collection!r} is not in the store. "
            "Run `vaultspec-rag server qdrant quarantine` to list collections.",
            json_mode=json_mode,
        )

    if dry_run:
        message = f"Would quarantine collection {collection!r} from {storage}."
        if json_mode:
            _emit_json(
                True,
                "server.qdrant.quarantine",
                data={"collection": collection, "dry_run": True},
            )
        else:
            _plain_line(message)
        return

    if not yes:
        _fail_quarantine(
            "confirmation_required",
            f"Refusing to quarantine {collection!r} without --yes. "
            "Re-run with --yes (or --dry-run to preview).",
            json_mode=json_mode,
        )

    try:
        dest = _quarantine_collection(storage, collection)
    except OSError as exc:
        _fail_quarantine(
            "quarantine_failed",
            f"Could not quarantine {collection!r}: {exc}. The managed server may "
            "be running and holding the files - stop it first "
            "(`vaultspec-rag server stop`), then retry.",
            json_mode=json_mode,
        )

    if json_mode:
        _emit_json(
            True,
            "server.qdrant.quarantine",
            data={"collection": collection, "quarantined_to": str(dest)},
        )
        return
    _plain_line(f"Quarantined collection {collection!r} to {dest}.")
    _plain_line("Restart the server; that root re-indexes on its next use.")
