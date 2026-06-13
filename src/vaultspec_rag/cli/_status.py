"""``status`` command: project index counts, storage, and compute device."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, cast

import typer

import vaultspec_rag.cli as _cli

from ._app import CLIState, app
from ._http_search import _try_http_admin
from ._render import (
    _emit_json,
    _emit_json_error_and_exit,
    _format_local_index_busy_message,
)
from ._service_status import _default_service_port


def _status_counts(status: dict[str, object]) -> tuple[int, int]:
    vault_count = status.get("vault_documents", status.get("vault_count", 0))
    code_count = status.get("codebase_chunks", status.get("code_count", 0))
    return int(cast("Any", vault_count)), int(cast("Any", code_count))


def _human_index_data_location(storage_path: object) -> str:
    raw = str(storage_path)
    if "://" in raw:
        return "remote storage"
    path = Path(raw)
    if path.name.lower() == "qdrant":
        return str(path.parent)
    return raw


def _render_status_text(
    status: dict[str, object],
    *,
    target: object,
    service_port: int | None = None,
) -> None:
    cuda_available = bool(status["cuda"])
    gpu_name = cast("Any", status["gpu_name"])
    vram_mb = int(cast("Any", status["vram_mb"]))
    index_data_path = _human_index_data_location(status["storage_path"])
    vault_count, code_count = _status_counts(status)
    device = (
        f"GPU - {gpu_name} ({vram_mb} MB VRAM)"
        if cuda_available
        else "CPU only (no supported GPU detected)"
    )
    lines = [
        f"Compute: {device}",
        f"Index data: {index_data_path}",
        f"Vault documents: {vault_count}",
        f"Source code sections: {code_count}",
        f"Project: {target}",
    ]
    if service_port is not None:
        lines.append(f"Address: http://127.0.0.1:{service_port}")
    for line in lines:
        _cli.console.print(
            line,
            markup=False,
            highlight=False,
            soft_wrap=line.startswith(("Index data:", "Project:", "Address:")),
        )


def _emit_status_json(
    status: dict[str, object],
    *,
    target: object,
    service_port: int | None = None,
) -> None:
    vault_count, code_count = _status_counts(status)
    data: dict[str, object] = {
        "cuda": bool(status["cuda"]),
        "gpu_name": status["gpu_name"],
        "vram_mb": int(cast("Any", status["vram_mb"])),
        "storage_path": str(status["storage_path"]),
        "vault_documents": vault_count,
        "codebase_chunks": code_count,
        "target_dir": str(target),
        "backend_capabilities": status.get("backend_capabilities", {}),
    }
    if service_port is not None:
        data["service_port"] = service_port
    _emit_json(True, "status", data=data)


def _service_index_status(target: object) -> tuple[dict[str, object], int] | None:
    port = _default_service_port()
    if port is None:
        return None
    result = _try_http_admin(
        "get_service_state",
        {"project_root": str(target)},
        port,
    )
    if not isinstance(result, dict) or result.get("ok") is False:
        return None
    raw_index = result.get("index")
    if not isinstance(raw_index, dict) or raw_index.get("error"):
        return None
    return cast("dict[str, object]", raw_index), port


@app.command(
    "status",
    help=(
        "Show project index counts, index data location, and compute device. "
        "See the indexing architecture guide: docs/indexing.md"
    ),
)
def handle_status(
    ctx: typer.Context,
    json_mode: Annotated[
        bool,
        typer.Option(
            "--json",
            help=("Emit JSON for scripts instead of human text."),
        ),
    ] = False,
) -> None:
    """Show project index counts, index data location, and compute device."""
    state: CLIState = ctx.obj
    target = state.target

    import vaultspec_rag

    from ..store import VaultStoreLockedError
    from ._gpu_errors import _handle_gpu_error

    service_status = _service_index_status(target)
    if service_status is not None:
        status, service_port = service_status
        if json_mode:
            _emit_status_json(status, target=target, service_port=service_port)
            return
        _render_status_text(status, target=target, service_port=service_port)
        return

    try:
        status = vaultspec_rag.get_status(target)
    except VaultStoreLockedError as exc:
        service_status = _service_index_status(target)
        if service_status is not None:
            status, service_port = service_status
            if json_mode:
                _emit_status_json(status, target=target, service_port=service_port)
                return
            _render_status_text(status, target=target, service_port=service_port)
            return
        if json_mode:
            _emit_json_error_and_exit(
                "status",
                "status_locked",
                "Cannot read index status because the local index is busy.",
                1,
                db_path=str(exc.db_path),
                remediation=[
                    "vaultspec-rag server status",
                    "Retry after the current index operation finishes.",
                ],
            )
        _cli.console.print(
            _format_local_index_busy_message("read index status"),
            markup=False,
            highlight=False,
        )
        raise typer.Exit(code=1) from None
    except (ImportError, RuntimeError) as e:
        _handle_gpu_error(e)
        return

    if json_mode:
        _emit_status_json(status, target=target)
        return

    _render_status_text(status, target=target)
