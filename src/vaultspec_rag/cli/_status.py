"""``status`` command: GPU info, storage metrics, backend contract."""

from __future__ import annotations

from typing import Annotated, Any, cast

import typer
from rich.table import Table

import vaultspec_rag.cli as _cli

from ._app import CLIState, app
from ._render import _add_backend_contract_rows, _emit_json, _emit_json_error_and_exit


@app.command("status")
def handle_status(
    ctx: typer.Context,
    json_mode: Annotated[
        bool,
        typer.Option(
            "--json",
            help=(
                "Emit one JSON envelope to stdout instead of a Rich "
                "table. Mirrors the MCP get_index_status response."
            ),
        ),
    ] = False,
) -> None:
    """Show RAG engine status, storage metrics, and GPU info.

    Args:
        ctx: Typer context carrying ``CLIState``.
        json_mode: Emit a JSON envelope to stdout for agent/CI use.

    Raises:
        typer.Exit: On missing GPU dependencies.

    """
    state: CLIState = ctx.obj
    target = state.target

    import vaultspec_rag

    from ..store import VaultStoreLockedError
    from ._gpu_errors import _handle_gpu_error

    try:
        status = vaultspec_rag.get_status(target)
    except VaultStoreLockedError as exc:
        if json_mode:
            _emit_json_error_and_exit(
                "status",
                "status_locked",
                f"Cannot query index status - another process holds the lock: {exc}",
                1,
            )
        _cli.console.print(
            "[bold red]Error:[/] Cannot query index status - "
            f"another process holds the lock.\n{exc}\n"
            "Close any other processes using the index and retry."
        )
        raise typer.Exit(code=1) from None
    except (ImportError, RuntimeError) as e:
        _handle_gpu_error(e)

    cuda_available = bool(status["cuda"])
    gpu_name = cast("Any", status["gpu_name"])
    vram_mb = int(cast("Any", status["vram_mb"]))
    storage_path = str(status["storage_path"])
    vault_count = int(cast("Any", status["vault_documents"]))
    code_count = int(cast("Any", status["codebase_chunks"]))
    backend_capabilities = cast("Any", status["backend_capabilities"])

    if json_mode:
        _emit_json(
            True,
            "status",
            data={
                "cuda": cuda_available,
                "gpu_name": gpu_name,
                "vram_mb": vram_mb,
                "storage_path": storage_path,
                "vault_documents": vault_count,
                "codebase_chunks": code_count,
                "target_dir": str(target),
                "backend_capabilities": backend_capabilities,
            },
        )
        return

    gpu_status = (
        f"[green]cuda[/] - {gpu_name} ({vram_mb} MB VRAM)"
        if cuda_available
        else "[red]No CUDA GPU available[/]"
    )
    table = Table(title="RAG Engine Status", show_header=False, padding=(0, 2))
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("Device", gpu_status)
    table.add_row("Storage Path", f"[cyan]{storage_path}[/]")
    table.add_row("Vault Documents", f"[green]{vault_count}[/]")
    table.add_row("Codebase Chunks", f"[green]{code_count}[/]")
    table.add_row("Target Directory", f"[cyan]{target}[/]")
    _add_backend_contract_rows(table)
    _cli.console.print(table)
