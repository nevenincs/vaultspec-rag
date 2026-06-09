"""Vault store opener with friendly lock-error translation."""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

import vaultspec_rag.cli as _cli

from ..store import VaultStore, VaultStoreLockedError
from ._render import _emit_json_error_and_exit

if TYPE_CHECKING:
    from pathlib import Path


def _open_vault_store(
    target: Path,
    *,
    json_mode: bool = False,
    command: str = "cli",
    raise_on_locked: bool = False,
) -> VaultStore:
    """Open a VaultStore, translating lock errors into a friendly CLI exit.

    Args:
        target: Workspace root directory.
        json_mode: When True, emit a ``local_store_locked`` envelope
            and ``typer.Exit(1)`` instead of the Rich prose path -
            every command's ``--json`` flag threads through here so
            the lock-error UX never corrupts the JSON stream.
        command: Envelope ``command`` field; defaults to ``"cli"`` for
            call sites that have not been wired to a specific command
            name yet.
        raise_on_locked: If True, propagate VaultStoreLockedError rather than exiting.

    Returns:
        An open VaultStore instance.

    Raises:
        VaultStoreLockedError: If raise_on_locked is True and the store is locked.
        typer.Exit: With code 1 if the Qdrant storage is already held by
            another process. The message names the exact path and lists
            the three options available to the user.
    """
    try:
        return VaultStore(target)
    except VaultStoreLockedError as exc:
        if raise_on_locked:
            raise
        if json_mode:
            _emit_json_error_and_exit(
                command,
                "local_store_locked",
                (
                    f"The vault index at {exc.db_path} is currently in "
                    "use by another process. Stop the resident "
                    "RAG service, or route through one running "
                    "vaultspec-rag service for concurrent access."
                ),
                1,
                db_path=str(exc.db_path),
                remediation=[
                    "Wait for the other process to finish.",
                    "vaultspec-rag server stop",
                    "vaultspec-rag server mcp stop",
                ],
            )
        _cli.console.print(
            f"[bold red]Error:[/] The vault index at [cyan]{exc.db_path}[/] "
            "is currently in use by another process.\n\n"
            "  Another [cyan]vaultspec-rag[/] command, RAG service, "
            "or file watcher is likely running against this workspace.\n\n"
            "  Local-file-backed RAG storage cannot be opened by multiple "
            "processes at once. For concurrent agent searches, route every "
            "request through one running [cyan]vaultspec-rag[/] service.\n\n"
            "  To resolve, do one of the following:\n"
            "    1. Wait for the other process to finish.\n"
            "    2. Stop the running server:\n"
            "         [cyan]vaultspec-rag server mcp stop[/]\n"
            "         [cyan]vaultspec-rag server stop[/]\n"
            "    3. If no vaultspec-rag process is alive, look for an "
            "orphaned Python process holding the lock and stop it manually.",
        )
        raise typer.Exit(code=1) from exc
