"""``status`` command: GPU info, storage metrics, backend contract."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

import vaultspec_rag.cli as _cli

from ..capabilities import backend_capabilities_dict
from ._app import CLIState, app
from ._gpu_errors import _handle_gpu_error
from ._render import _add_backend_contract_rows, _emit_json
from ._store import _open_vault_store


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

    try:
        import torch
    except ImportError as e:
        _handle_gpu_error(e)

    cuda_available = torch.cuda.is_available()
    if cuda_available:
        gpu_name = torch.cuda.get_device_name(0)
        props = torch.cuda.get_device_properties(0)
        vram_mb = props.total_memory // (1024 * 1024)
    else:
        gpu_name = None
        vram_mb = 0

    # Store metrics
    store = _open_vault_store(target, json_mode=json_mode, command="status")
    try:
        vault_count = store.count()
        code_count = store.count_code()
        storage_path = str(store.db_path)
    finally:
        store.close()

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
                "backend_capabilities": backend_capabilities_dict(),
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
