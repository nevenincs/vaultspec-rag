"""``status`` command: the service, this installation, active features, and index."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, NoReturn, cast

import typer

from .._job_values import count
from .._operator_commands import index_command, server_status_command
from .._source_types import PublicSourceType
from ..operator_state._installation import ComputeCapability
from ..operator_state._models import (
    HealthReport,
    InstallationReport,
    ServiceStateReport,
)
from ..serviceclient._discovery import _default_service_port
from ..serviceclient._transport import _try_http_admin
from ..serviceclient._typed_state import parse_report
from ._app import CLIState, JsonMode, app
from ._cli_format import _counted_unit, _format_mib
from ._render import (
    _emit_json,
    _emit_json_error_and_exit,
    _format_local_index_busy_message,
    _plain,
    _print_next_action,
    exit_with_error,
)
from ._status_labels import render_degradation

if TYPE_CHECKING:
    from ..operator_state._features import PreprocessHookState


def _status_counts(status: dict[str, object]) -> tuple[int, int, int | None]:
    # A version-skewed daemon can publish these as something other than an
    # int; count() reads a malformed field as "not measured" rather than
    # raising out of the status command.
    vault_count = status.get("vault_count", 0)
    code_count = status.get("code_count", 0)
    document_count = status.get("document_count")
    return (
        count(vault_count) or 0,
        count(code_count) or 0,
        count(document_count),
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
        return index_command(missing[0])
    return index_command(PublicSourceType.COMBINED)


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
        # Byte caps go through the shared vocabulary like every other size in
        # this command: printed raw, `source_bytes=137438953472` asks the
        # operator to do the arithmetic that "128.0 GiB" already did.
        lines.append(
            f"{source.capitalize()} support: "
            f"{_counted_unit(_domain_count(domain, 'source_files'), 'file')}, "
            f"{_profile_bytes(domain, 'source_bytes')} of source, "
            f"{_counted_unit(_domain_count(domain, 'generated_chunks'), 'section')} "
            f"generated, {_profile_bytes(domain, 'weighted_bytes')} weighted"
        )
    return lines


def _domain_count(domain: dict[str, object], key: str) -> int:
    """Read one integer cap from a support domain, defaulting to zero."""
    raw = domain.get(key, 0)
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return 0
    return int(raw)


def _generation_lines(generations: object) -> list[str]:
    """Render the per-domain index generation records.

    The payload carries one structured record per domain - generation number,
    the job that produced it, its state and any error kind. Interpolated whole
    it printed a nested Python repr several lines long, which is unreadable and
    tells an operator nothing they can act on. Each domain gets one line here,
    and a record whose shape is not recognised is still named rather than
    dropped, so an unexpected payload degrades to less detail instead of to
    silence.
    """
    if not isinstance(generations, dict):
        return []
    records = cast("dict[str, object]", generations)
    lines: list[str] = []
    for domain in sorted(records):
        raw = records[domain]
        if raw is None:
            # A domain the service knows about but has never indexed. Saying so
            # beats rendering the literal "None", which reads as a fault.
            lines.append(f"  {domain}: not indexed yet")
            continue
        if not isinstance(raw, dict):
            lines.append(f"  {domain}: {raw}")
            continue
        record = cast("dict[str, object]", raw)
        parts = [f"generation {record.get('generation', 'not reported')}"]
        state = record.get("state")
        if state:
            parts.append(str(state))
        error_kind = record.get("error_kind")
        if error_kind:
            parts.append(f"error: {error_kind}")
        job_id = record.get("job_id")
        if job_id:
            parts.append(f"job {str(job_id)[:8]}")
        lines.append(f"  {domain}: {', '.join(parts)}")
    return lines


def _compute_line(installation: InstallationReport) -> str:
    """State whether the environment can run inference, and on what.

    The hardware and the environment are named separately, because a machine
    with a capable GPU can still hold a torch build that cannot use it.
    """
    compute = installation.compute
    hardware = installation.hardware
    capability = compute.capability
    if capability is ComputeCapability.NOT_APPLICABLE:
        return capability.label
    name = compute.device_name or hardware.name or hardware.presence.label
    memory_mib = compute.memory_mib or hardware.memory_mib
    unified = " unified memory" if compute.backend == "mps" else ""
    device = f"{name} ({_format_mib(memory_mib)}{unified})" if memory_mib else name
    if capability is ComputeCapability.READY:
        return f"ready on {device}"
    return f"{device}; {capability.label}"


@dataclass(frozen=True, slots=True)
class _ServiceView:
    """What a running service reported about itself and this root."""

    port: int
    state: ServiceStateReport
    health: HealthReport | None


@dataclass(frozen=True, slots=True)
class _StatusView:
    """Everything the status command reports, from whichever source had it."""

    target: object
    index: dict[str, object]
    installation: InstallationReport
    hooks: PreprocessHookState
    hook_rules: int
    service: _ServiceView | None = None


def _hooks_line(view: _StatusView) -> str:
    rules = f", {_counted_unit(view.hook_rules, 'rule')}" if view.hook_rules else ""
    return f"{view.hooks.label}{rules}"


def _watcher_label(service: _ServiceView) -> str:
    features = service.health.features if service.health is not None else None
    if features is not None and not features.watcher_enabled:
        return "off (disabled when the service started)"
    if service.state.root_features.watcher_running:
        return "following this project"
    return "not following this project"


def _service_lines(view: _StatusView) -> list[str]:
    service = view.service
    if service is None:
        return [
            "Service: not running",
            f"This installation: {view.installation.role.label}",
        ]
    lines = [
        f"Service: running at http://127.0.0.1:{service.port}",
        f"Service installation: {view.installation.role.label}",
    ]
    local = _resolve_local_interpreter()
    if not _same_path(view.installation.executable, local):
        lines.append(
            f"Note: the running service uses {view.installation.executable}; "
            f"a service started from here would use {local}."
        )
    return lines


def _feature_lines(view: _StatusView) -> list[str]:
    lines = [f"Preprocessing hooks: {_hooks_line(view)}"]
    service = view.service
    if service is None:
        return lines
    features = service.health.features if service.health is not None else None
    if features is not None:
        lines.append(f"Typesafe classification: {features.typesafe.state.label}")
        lines.append(
            "Reranking: "
            + (
                "off (disabled in configuration)"
                if not features.reranker_enabled
                else "ready"
                if features.reranker_loaded
                else "not loaded yet"
            )
        )
    lines.append(f"File watcher: {_watcher_label(service)}")
    return lines


def _render_status_text(view: _StatusView, *, verbose: bool = False) -> None:
    """Render the plain-language status overview.

    Each line answers one question an operator asks - is the service up, what
    is this installation, can it run inference, which optional features are
    active, what is indexed - and a fix appears only for a real defect, never
    for a client that simply has no GPU work to do.
    """
    service_port = view.service.port if view.service is not None else None
    vault_count, code_count, document_count = _status_counts(view.index)
    documents = (
        _counted_unit(document_count, "document section")
        if document_count is not None
        else "document sections not reported"
    )
    capability = view.installation.compute.capability
    lines = [
        f"Project: {view.target}",
        *_service_lines(view),
        f"Compute: {_compute_line(view.installation)}",
    ]
    if capability.is_defect and capability.remediation:
        lines.append(f"  Fix: {capability.remediation}")
    lines.extend(_feature_lines(view))
    lines.extend(
        (
            f"Index: {_counted_unit(vault_count, 'vault document')}, "
            f"{_counted_unit(code_count, 'code section')}, {documents}",
            "Index data: "
            + _human_index_data_location(
                view.index.get("storage_path", "not reported"),
                service_port=service_port,
            ),
        )
    )
    lines.extend(render_degradation(view.index, header="Degraded because:"))
    if verbose:
        lines.append(f"Interpreter: {view.installation.executable}")
        lines.extend(_support_profile_lines(view.index))
        generation_lines = _generation_lines(view.index.get("generations"))
        if generation_lines:
            lines.append("Index generations:")
            lines.extend(generation_lines)
    # Soft-wrapped so a long path or verdict stays one line a reader (or a
    # script reading "Label: value") can take whole; the terminal still wraps
    # it visually.
    for line in lines:
        _plain(line, soft_wrap=True)
    if service_port is not None:
        _plain(f"Service details: {server_status_command(service_port)}")
    _print_next_action(_status_next_action(vault_count, code_count, document_count))


def _emit_status_json(view: _StatusView) -> None:
    vault_count, code_count, document_count = _status_counts(view.index)
    service = view.service
    data: dict[str, object] = {
        "service": {
            "running": service is not None,
            "port": service.port if service is not None else None,
        },
        "installation": view.installation.model_dump(mode="json"),
        "features": {
            "preprocess_hooks": view.hooks.value,
            "preprocess_rule_count": view.hook_rules,
            "service": (
                service.health.features.model_dump(mode="json")
                if service is not None and service.health is not None
                else None
            ),
            "watcher_running": (
                service.state.root_features.watcher_running
                if service is not None
                else None
            ),
        },
        "storage_path": str(view.index.get("storage_path", "")),
        "vault_count": vault_count,
        "code_count": code_count,
        "document_count": document_count,
        "target_dir": str(view.target),
        "backend_capabilities": view.index.get("backend_capabilities", {}),
    }
    for key in ("generations", "degraded_reasons", "support_profile"):
        if key in view.index:
            data[key] = view.index[key]
    _emit_json(True, "status", data=data)


def _answered(result: object) -> bool:
    """Whether the service answered with a body, rather than failing to."""
    return isinstance(result, dict) and result.get("ok") is not False


def _refuse_incompatible_service(port: int, *, json_mode: bool) -> NoReturn:
    """Report a service whose state this client cannot read, and stop.

    Falling back to the local store would be wrong twice over: the running
    service holds that store, so the read fails as "busy", and the operator is
    sent looking for a lock instead of at the release mismatch.
    """
    from ..serviceclient._compat import classify_service_version
    from ..serviceclient._transport import _try_http_health

    verdict = classify_service_version(_try_http_health(port))
    reason = (
        verdict.reason()
        if not verdict.is_compatible
        else "the running service's state could not be read by this client"
    )
    remedy = " ".join(verdict.remediation()) or server_status_command(port)
    exit_with_error(
        "status",
        verdict.error_code() or "service_state_unreadable",
        f"Cannot show index status: {reason}. {remedy}",
        1,
        json_mode=json_mode,
    )


def _service_view(target: object, *, json_mode: bool) -> _StatusView | None:
    """Read a running service's state for this root, and its health.

    ``None`` means no service answered, and the caller reports from this
    machine instead.
    """
    from ..serviceclient._transport import _try_http_health

    port = _default_service_port()
    if port is None:
        return None
    result = _try_http_admin(
        "get_service_state",
        {"project_root": str(target)},
        port,
    )
    state = parse_report(ServiceStateReport, result)
    if state is None and _answered(result):
        _refuse_incompatible_service(port, json_mode=json_mode)
    if state is None or state.index.get("error"):
        return None
    return _StatusView(
        target=target,
        index=state.index,
        installation=state.installation,
        hooks=state.root_features.preprocess_hooks,
        hook_rules=state.root_features.preprocess_rule_count,
        service=_ServiceView(
            port=port,
            state=state,
            health=parse_report(HealthReport, _try_http_health(port)),
        ),
    )


def _resolve_local_interpreter() -> str:
    from ._process import _resolve_daemon_interpreter

    return _resolve_daemon_interpreter()


def _same_path(left: str, right: str) -> bool:
    import os

    def canonical(path: str) -> str:
        return os.path.normcase(os.path.realpath(path))

    return canonical(left) == canonical(right)


def _local_view(target: object, index: dict[str, object]) -> _StatusView:
    """Describe this machine, for when no service answers.

    The installation is read from package metadata in a child of the daemon
    interpreter, so this command never imports torch and never claims a device
    it did not verify; the hooks are this root's own configuration.
    """
    from ..config._settings import get_config
    from ..indexer._preprocess_config import root_hook_state
    from ..operator_state._compute import ProbeDepth
    from ..operator_state._environment_probe import probe_interpreter
    from ..operator_state._hardware import read_hardware

    facts = probe_interpreter(_resolve_local_interpreter(), ProbeDepth.METADATA)
    hooks, rules = root_hook_state(Path(str(target)), get_config().preprocess_mode)
    return _StatusView(
        target=target,
        index=index,
        installation=InstallationReport(
            role=facts.role,
            mcp_adapter=facts.mcp_adapter,
            executable=facts.executable,
            prefix=facts.prefix,
            hardware=read_hardware(),
            compute=facts.compute,
            local=True,
        ),
        hooks=hooks,
        hook_rules=rules,
    )


def _report(view: _StatusView, *, json_mode: bool, verbose: bool) -> None:
    if json_mode:
        _emit_status_json(view)
        return
    _render_status_text(view, verbose=verbose)


@app.command(
    "status",
    help=(
        "Show the service, this installation's compute, the project's active "
        "features, and its index."
    ),
)
def handle_status(
    ctx: typer.Context,
    json_mode: JsonMode = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help=(
                "Also show the interpreter, the support profile limits, and the "
                "per-domain index generations."
            ),
        ),
    ] = False,
) -> None:
    """Show the service, this installation's compute, features, and index."""
    state: CLIState = ctx.obj
    target = state.target

    import vaultspec_rag

    from .._store_locks import VaultStoreLockedError

    view = _service_view(target, json_mode=json_mode)
    if view is not None:
        _report(view, json_mode=json_mode, verbose=verbose)
        return

    try:
        index = vaultspec_rag.get_status(target)
    except VaultStoreLockedError as exc:
        view = _service_view(target, json_mode=json_mode)
        if view is not None:
            _report(view, json_mode=json_mode, verbose=verbose)
            return
        if json_mode:
            _emit_json_error_and_exit(
                "status",
                "status_locked",
                "Cannot read index status because the local index is busy.",
                1,
                db_path=str(exc.db_path),
                remediation=[
                    server_status_command(),
                    "Retry after the current index operation finishes.",
                ],
            )
        _plain(_format_local_index_busy_message("read index status"))
        raise typer.Exit(code=1) from None

    _report(_local_view(target, index), json_mode=json_mode, verbose=verbose)
