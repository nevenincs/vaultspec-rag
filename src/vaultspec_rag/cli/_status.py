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
from ._status_labels import render_degradation


def _status_counts(status: dict[str, object]) -> tuple[int, int, int | None]:
    vault_count = status.get("vault_documents", status.get("vault_count", 0))
    code_count = status.get("codebase_chunks", status.get("code_count", 0))
    document_count = status.get("document_chunks", status.get("document_count"))
    return (
        int(cast("Any", vault_count)),
        int(cast("Any", code_count)),
        int(cast("Any", document_count)) if document_count is not None else None,
    )


def _human_index_data_location(
    storage_path: object,
    *,
    service_port: int | None = None,
) -> str:
    raw = str(storage_path)
    if "://" in raw:
        if service_port is not None:
            return "running service storage"
        return "remote storage"
    path = Path(raw)
    if path.name.lower() == "qdrant":
        return str(path.parent)
    return raw


def _status_next_action(
    vault_count: int,
    code_count: int,
    document_count: int | None,
) -> str | None:
    missing = [
        source
        for source, count in (
            ("vault", vault_count),
            ("code", code_count),
            ("document", document_count),
        )
        if count is not None and count <= 0
    ]
    if not missing:
        return None
    if len(missing) == 1:
        return f"vaultspec-rag index --type {missing[0]}"
    return "vaultspec-rag index --type all"


def _profile_bytes(profile: dict[str, object], key: str) -> str:
    """Render one profile byte threshold in operator units."""
    from .._units import human_bytes

    raw = profile.get(key, 0)
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return "not reported"
    return human_bytes(raw)


def _support_profile_lines(status: dict[str, object]) -> list[str]:
    raw_profile = status.get("support_profile")
    if not isinstance(raw_profile, dict):
        return []
    profile = cast("dict[str, object]", raw_profile)
    lines = [f"Support profile: {profile.get('name', 'not reported')}"]
    backends = profile.get("accepted_backends")
    if isinstance(backends, list):
        typed_backends = cast("list[object]", backends)
        lines.append(f"Accepted backends: {', '.join(map(str, typed_backends))}")
    lines.extend(
        (
            f"Minimum RAM: {_profile_bytes(profile, 'minimum_ram_bytes')}",
            f"Minimum free disk: {_profile_bytes(profile, 'minimum_free_disk_bytes')}",
        )
    )
    raw_domains = profile.get("domains")
    if not isinstance(raw_domains, dict):
        return lines
    domains = cast("dict[str, object]", raw_domains)
    for source in ("code", "document"):
        raw_domain = domains.get(source)
        if not isinstance(raw_domain, dict):
            continue
        domain = cast("dict[str, object]", raw_domain)
        lines.append(
            f"{source.capitalize()} support: "
            f"source_files={domain.get('source_files', 0)}, "
            f"source_bytes={domain.get('source_bytes', 0)}, "
            f"generated_chunks={domain.get('generated_chunks', 0)}, "
            f"weighted_bytes={domain.get('weighted_bytes', 0)}"
        )
    return lines


def _status_diagnostics(status: dict[str, object]) -> list[str]:
    """Render optional policy, generation, and degraded-state diagnostics.

    Degradation goes through the shared renderer rather than being formatted
    here: this payload reports one structured record per index domain, and
    interpolating that list printed a container repr at the operator instead of
    a cause and a command.
    """
    lines: list[str] = []
    lines.extend(_support_profile_lines(status))
    policy = status.get("policy", status.get("policy_fingerprint"))
    generations = status.get("generations", status.get("generation"))
    if policy not in (None, "", {}):
        lines.append(f"Policy: {policy}")
    if generations not in (None, "", {}):
        lines.append(f"Generations: {generations}")
    lines.extend(render_degradation(status, header="Degraded because:"))
    return lines


def _render_status_text(
    status: dict[str, object],
    *,
    target: object,
    service_port: int | None = None,
) -> None:
    cuda_available = bool(status["cuda"])
    gpu_name = cast("Any", status["gpu_name"])
    vram_mb = int(cast("Any", status["vram_mb"]))
    index_data_path = _human_index_data_location(
        status["storage_path"],
        service_port=service_port,
    )
    vault_count, code_count, document_count = _status_counts(status)
    device = (
        f"GPU - {gpu_name} ({vram_mb} MB VRAM)"
        if cuda_available
        else "CPU only (no supported GPU detected)"
    )
    lines = [
        "Project index",
        f"Project: {target}",
        f"Index data: {index_data_path}",
        f"Vault documents: {vault_count}",
        f"Source code sections: {code_count}",
        "Document sections: "
        f"{document_count if document_count is not None else 'not reported'}",
        f"Compute: {device}",
        *_status_diagnostics(status),
    ]
    if service_port is not None:
        lines.append("Server: running")
        lines.append(f"Address: http://127.0.0.1:{service_port}")
        lines.append("Server details:")
    next_action = _status_next_action(vault_count, code_count, document_count)
    for line in lines:
        _cli.console.print(
            line,
            markup=False,
            highlight=False,
            soft_wrap=line.startswith(("Index data:", "Project:", "Address:")),
        )
    if service_port is not None:
        _cli.console.print(
            f"  vaultspec-rag server status --port {service_port}",
            markup=False,
            highlight=False,
        )
    if next_action:
        _cli.console.print("Next action:", markup=False, highlight=False)
        _cli.console.print(f"  {next_action}", markup=False, highlight=False)


def _emit_status_json(
    status: dict[str, object],
    *,
    target: object,
    service_port: int | None = None,
) -> None:
    vault_count, code_count, document_count = _status_counts(status)
    data: dict[str, object] = {
        "cuda": bool(status["cuda"]),
        "gpu_name": status["gpu_name"],
        "vram_mb": int(cast("Any", status["vram_mb"])),
        "storage_path": str(status["storage_path"]),
        "vault_documents": vault_count,
        "codebase_chunks": code_count,
        "document_chunks": document_count,
        "target_dir": str(target),
        "backend_capabilities": status.get("backend_capabilities", {}),
    }
    for key in (
        "policy",
        "policy_fingerprint",
        "generations",
        "generation",
        "degraded_reasons",
        "degraded",
        "support_profile",
    ):
        if key in status:
            data[key] = status[key]
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
    if not isinstance(raw_index, dict):
        return None
    index_dict = cast("dict[str, object]", raw_index)
    if index_dict.get("error"):
        return None
    return index_dict, port


@app.command(
    "status",
    help="Show project index counts, index data location, and compute device.",
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
