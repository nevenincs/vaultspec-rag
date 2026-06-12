"""Vault store opener with friendly lock-error translation."""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

import vaultspec_rag.cli as _cli

from ..store import VaultStore, VaultStoreLockedError
from ._render import _emit_json_error_and_exit

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["_open_vault_store"]


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
        typer.Exit: With code 1 if the local search index is already held by
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
                    f"The local search index at {exc.db_path} is busy. "
                    "Another vaultspec-rag command, the background service, "
                    "or an automatic index update is using this workspace. "
                    "Use one running vaultspec-rag service for concurrent "
                    "searches."
                ),
                1,
                db_path=str(exc.db_path),
                remediation=[
                    "Wait for the other process to finish.",
                    "vaultspec-rag server status",
                    "vaultspec-rag server stop",
                    (
                        "Stop any orphaned Python process that is still using "
                        "this workspace."
                    ),
                ],
            )
        _cli.console.print(
            f"Error: The local search index at {exc.db_path} is busy.\n\n"
            "  Another vaultspec-rag command, the background service, or an "
            "automatic index update is using this workspace.\n\n"
            "  Only one local command can use this index directly at a time. "
            "For concurrent searches, send requests through one running "
            "vaultspec-rag service.\n\n"
            "  Next actions:\n"
            "    1. Wait for the other command or update to finish.\n"
            "    2. Check the service:\n"
            "         vaultspec-rag server status\n"
            "    3. Stop the running service:\n"
            "         vaultspec-rag server stop\n"
            "    4. If no vaultspec-rag process is alive, look for an "
            "orphaned Python process using the index and stop it manually.",
            markup=False,
            highlight=False,
        )
        raise typer.Exit(code=1) from exc
