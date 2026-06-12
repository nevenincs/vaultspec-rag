"""``status`` command: GPU info, storage metrics, backend contract."""

from __future__ import annotations

from typing import Annotated, Any, cast

import typer

import vaultspec_rag.cli as _cli

from ._app import CLIState, app
from ._render import _emit_json, _emit_json_error_and_exit


@app.command(
    "status",
    help=(
        "Show index document counts, storage path, and GPU device info. "
        "See the indexing architecture guide: docs/indexing.md"
    ),
)
def handle_status(
    ctx: typer.Context,
    json_mode: Annotated[
        bool,
        typer.Option(
            "--json",
            help=(
                "Emit one JSON envelope to stdout instead of text. "
                "Mirrors the MCP get_index_status response."
            ),
        ),
    ] = False,
) -> None:
    """Show RAG engine status, storage metrics, and GPU info."""
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
        return

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

    device = (
        f"cuda - {gpu_name} ({vram_mb} MB VRAM)"
        if cuda_available
        else "no CUDA GPU available"
    )
    lines = [
        f"Device: {device}",
        f"Storage: {storage_path}",
        f"Vault documents: {vault_count}",
        f"Codebase chunks: {code_count}",
        f"Target: {target}",
    ]
    for line in lines:
        _cli.console.print(
            line,
            markup=False,
            highlight=False,
            soft_wrap=line.startswith(("Storage:", "Target:")),
        )
