"""``status`` command: index counts, search data location, and GPU info."""

from __future__ import annotations

from typing import Annotated, Any, cast

import typer

import vaultspec_rag.cli as _cli

from ._app import CLIState, app
from ._http_search import _try_http_admin
from ._render import _emit_json, _emit_json_error_and_exit
from ._service_status import _default_service_port


def _status_counts(status: dict[str, object]) -> tuple[int, int]:
    vault_count = status.get("vault_documents", status.get("vault_count", 0))
    code_count = status.get("codebase_chunks", status.get("code_count", 0))
    return int(cast("Any", vault_count)), int(cast("Any", code_count))


def _render_status_text(
    status: dict[str, object],
    *,
    target: object,
    service_port: int | None = None,
) -> None:
    cuda_available = bool(status["cuda"])
    gpu_name = cast("Any", status["gpu_name"])
    vram_mb = int(cast("Any", status["vram_mb"]))
    storage_path = str(status["storage_path"])
    vault_count, code_count = _status_counts(status)
    device = (
        f"cuda - {gpu_name} ({vram_mb} MB VRAM)"
        if cuda_available
        else "no CUDA GPU available"
    )
    lines = [
        f"GPU: {device}",
        f"Search data: {storage_path}",
        f"Vault documents: {vault_count}",
        f"Codebase chunks: {code_count}",
        f"Project: {target}",
    ]
    if service_port is not None:
        lines.append(f"Source: running service at http://127.0.0.1:{service_port}")
    for line in lines:
        _cli.console.print(
            line,
            markup=False,
            highlight=False,
            soft_wrap=line.startswith(("Search data:", "Project:", "Source:")),
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
        "Show index counts, search data location, and GPU device info. "
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
    """Show index counts, search data location, and GPU info."""
    state: CLIState = ctx.obj
    target = state.target

    import vaultspec_rag

    from ..store import VaultStoreLockedError
    from ._gpu_errors import _handle_gpu_error

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
                (
                    "Cannot query index status because another process holds "
                    f"the local index lock: {exc}"
                ),
                1,
            )
        _cli.console.print(
            "Error: Cannot query index status because another process holds "
            f"the local index lock.\n{exc}\n"
            "Check the running service with `vaultspec-rag server status`, "
            "or retry after the other process exits.",
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
