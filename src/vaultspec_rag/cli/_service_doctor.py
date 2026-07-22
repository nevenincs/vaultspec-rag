"""``server doctor`` - readiness across two distinct axes.

A thin adapter over the service-domain operability behaviour. It reports two
axes that earlier conflated into one misleading ``ready`` flag:

- the **installed-dependency** axis (``api.get_readiness`` - torch, models, the
  qdrant binary on disk), safe to call before any runtime is up; and
- the **live-service** axis, computed from the discovery file and the same
  ``server status`` liveness signals (PID alive, our PID, port listening,
  heartbeat fresh) so a dead daemon is never reported as ready.

The doctor never duplicates the status-path liveness computation: it reuses
``_evaluate_service_signals`` / ``_compute_state`` from the lifecycle module
(the service domain owns operability; adapters only render it). It mutates
nothing - the dependency reporter and the live signals are both read-only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, cast

import typer

import vaultspec_rag.cli as _cli

from ..api import get_readiness
from ._app import server_app
from ._render import _emit_json

#: The distribution name rag's own doctor rows read from the shared per-package
#: ``.vaultspec/workspace.json`` map, so a mixed workspace's ``vaultspec-core``
#: sibling entry is never mistaken for rag's own.
_RAG_PACKAGE = "vaultspec-rag"


@server_app.command(
    "doctor",
    help=(
        "Report readiness across two axes: installed dependencies (torch, "
        "models, qdrant binary) and the live service (a running daemon's "
        "health). A dead daemon is reported as not ready."
    ),
)
def service_doctor(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the readiness snapshot as a JSON envelope."),
    ] = False,
) -> None:
    """Render the two-axis readiness snapshot in human or JSON mode.

    The installed-dependency axis comes from the read-only reporter
    (``api.get_readiness``). The live-service axis reads the discovery file
    and, when present, derives the running daemon's state from the same
    signals ``server status`` uses. The top-line ``ready`` is honest: when a
    daemon is expected (a discovery file exists) but is not live and healthy,
    ``ready`` is False with a ``degraded``/``needs-restart`` status; when no
    daemon is expected (no discovery file), ``ready`` reflects installed
    dependencies so a pre-install ``doctor`` still works. Mutates nothing.
    """
    report = get_readiness()
    service = _live_service_axis()
    mode = _mode_floor_axis(Path.cwd())
    overall_ready, status = _overall_readiness(report, service)
    if json_output:
        envelope = {
            "ready": overall_ready,
            "status": status,
            "server_mode": bool(report.get("server_mode")),
            "dependencies_ready": bool(report.get("ready")),
            "dependencies": report.get("dependencies"),
            "service": service,
            "mode": mode,
        }
        _emit_json(overall_ready, "server doctor", data=envelope)
    else:
        _render_readiness(report, service, overall_ready, status)
        _render_mode_floor_axis(mode)
    raise typer.Exit(code=_doctor_exit_code(service, mode))


def _doctor_exit_code(
    service: dict[str, object],
    mode: dict[str, object] | None,
) -> int:
    """Fold the daemon and provisioning axes into an exit code, error over warn.

    Mirrors core's ``spec doctor`` weighting for the shared per-package axis: a
    ``vaultspec-rag`` entry running below its declared floor is an error, a
    declared-vs-observed mode mismatch is a warning. Combined with the existing
    dead-daemon signal (a daemon expected but not live is a warning), the highest
    severity wins: ``2`` for any error, ``1`` for any warning, ``0`` otherwise.

    A pre-install / no-daemon run with no committed rag declaration keeps exit 0
    even when dependencies are not yet ready, preserving the informational
    pre-install contract callers relied on; only an actionable divergence
    (below-floor error, mode mismatch, or dead daemon) lifts the exit code.
    """
    dead_daemon = bool(service.get("present")) and not service.get("live")
    below_floor = mode is not None and mode.get("version_floor") == "below"
    mismatch = mode is not None and mode.get("mode_mismatch") == "mismatch"
    if below_floor:
        return 2
    if dead_daemon or mismatch:
        return 1
    return 0


def _live_service_axis() -> dict[str, object]:
    """Compute the live-service axis from the discovery file, read-only.

    Returns a labelled block describing whether a daemon that is expected to
    be running actually is. When no discovery file exists, the service is not
    started (``present: False``) and the live axis does not constrain the
    top-line readiness. When a discovery file exists, the same lifecycle
    signals that back ``server status`` (PID alive, our PID, port listening,
    heartbeat fresh) derive the state, so the doctor and status never disagree.

    Reuses ``_evaluate_service_signals`` from the lifecycle module rather than
    recomputing liveness (the service domain owns operability). That helper
    cleans a confirmed-dead stale ``service.json`` as a side effect, matching
    ``server status`` behaviour exactly.
    """
    from ..serviceclient._discovery import resolve_machine_service
    from ..serviceclient._status import STATUS_STOPPED, compose_discovery_status
    from ._service_lifecycle import _evaluate_service_signals
    from ._service_status import _read_service_status
    from ._status_render import _liveness_from_resolution

    status = _read_service_status()
    if status is None:
        # The singleton is machine-global, so an absent record in this status
        # directory is not evidence that nothing is running. Deriving the axis
        # from the same canonical composition the status verb uses is what
        # keeps doctor and status from disagreeing about a live holder.
        resolution = resolve_machine_service()
        verdict = compose_discovery_status(
            resolution,
            _liveness_from_resolution(resolution),
        )
        if verdict.state == STATUS_STOPPED:
            return {
                "present": False,
                "live": False,
                "state": "not_started",
                "label": "no service has been started (no discovery file)",
            }
        return {
            "present": True,
            "live": verdict.exit_code == 0,
            "state": verdict.state,
            "label": verdict.label,
            "pid": verdict.signals.pid,
            "port": verdict.port,
            "pid_alive": verdict.signals.pid_alive,
            "pid_matches_service": verdict.signals.pid_matches_service,
            "port_listening": verdict.signals.port_listening,
            "heartbeat_age_seconds": verdict.signals.heartbeat_age_s,
            "heartbeat_stale": verdict.signals.heartbeat_stale,
            "discovery_evidence": resolution.evidence(),
        }

    (
        pid,
        port,
        _started_at,
        pid_alive,
        pid_is_ours,
        port_listening,
        heartbeat_age,
        heartbeat_stale,
        _token_match,
        state,
        state_label,
        exit_code,
    ) = _evaluate_service_signals(status)

    live = exit_code == 0
    return {
        "present": True,
        "live": live,
        "state": state,
        "label": state_label,
        "pid": pid,
        "port": port,
        "pid_alive": pid_alive,
        "pid_matches_service": pid_is_ours,
        "port_listening": port_listening,
        "heartbeat_age_seconds": heartbeat_age,
        "heartbeat_stale": heartbeat_stale,
    }


def _overall_readiness(
    report: dict[str, object],
    service: dict[str, object],
) -> tuple[bool, str]:
    """Fold the two axes into an honest top-line ``(ready, status)``.

    - No discovery file: the live axis is not asserted, so ``ready`` reflects
      installed dependencies (a pre-install ``doctor`` still works), with
      status ``ready`` / ``dependencies_not_ready``.
    - Discovery file present and the daemon is live and healthy: ``ready`` when
      dependencies are also ready, status ``ready`` / ``dependencies_not_ready``.
    - Discovery file present but the daemon is not live: ``ready`` is False and
      the status is ``needs_restart`` - a dead-but-expected daemon must never
      read ready, regardless of installed dependencies.
    """
    deps_ready = bool(report.get("ready"))
    if not service.get("present"):
        return deps_ready, ("ready" if deps_ready else "dependencies_not_ready")
    if not service.get("live"):
        return False, "needs_restart"
    return deps_ready, ("ready" if deps_ready else "dependencies_not_ready")


def _mode_floor_axis(target: Path) -> dict[str, object] | None:
    """Compute rag's provisioning mode-and-floor axis, read-only.

    Reports the ``vaultspec-rag`` entry in the shared per-package
    ``.vaultspec/workspace.json`` map through the same core collectors core's own
    ``spec doctor`` uses, keyed to ``vaultspec-rag`` so a sibling
    ``vaultspec-core`` entry is never read as rag's own: the declared mode, the
    mode-mismatch signal (whether rag's ``.mcp.json`` launch shape matches its
    declaration), and the version-floor signal (whether the running
    vaultspec-core is at or above rag's declared minimum).

    Returns ``None`` when no rag entry is declared - a pre-install workspace, or a
    directory that is not a vaultspec workspace at all - so the axis stays silent
    rather than inventing a row, preserving the informational pre-install
    contract. Any collector failure is swallowed to ``None``: the doctor mutates
    nothing and never crashes on a probe, matching the live-service axis.

    Args:
        target: Workspace root directory whose ``.vaultspec/workspace.json`` is
            read.

    Returns:
        A labelled block with ``declared_mode``, ``mode_mismatch``,
        ``version_floor``, ``version_floor_running``, and
        ``version_floor_minimum``, or ``None`` when no rag entry is declared.
    """
    try:
        from vaultspec_core.core.diagnosis.collectors import (  # pyright: ignore[reportMissingTypeStubs]
            collect_mode_mismatch_state,
            collect_version_floor_state,
        )
        from vaultspec_core.core.workspace_mode import (  # pyright: ignore[reportMissingTypeStubs]
            read_package_declaration,
        )

        declaration = read_package_declaration(target, _RAG_PACKAGE)
        if declaration is None:
            return None
        mode_mismatch = collect_mode_mismatch_state(target, package=_RAG_PACKAGE)
        floor, running, minimum = collect_version_floor_state(
            target, package=_RAG_PACKAGE
        )
    except Exception:
        return None
    return {
        "package": _RAG_PACKAGE,
        "declared_mode": declaration.install_mode.value,
        "mode_mismatch": mode_mismatch.value,
        "version_floor": floor.value,
        "version_floor_running": running,
        "version_floor_minimum": minimum,
    }


def _render_readiness(
    report: dict[str, object],
    service: dict[str, object],
    overall_ready: bool,
    status: str,
) -> None:
    """Render both readiness axes as a bounded plain-text summary."""
    server_mode = bool(report.get("server_mode"))
    _cli.console.print("Service readiness", markup=False, highlight=False)
    _cli.console.print(
        f"Backend: {'server' if server_mode else 'local-only'}",
        markup=False,
        highlight=False,
    )
    _cli.console.print(
        f"Readiness: {_overall_label(overall_ready, status)}",
        markup=False,
        highlight=False,
    )
    _render_live_service_axis(service)
    _render_dependency_axis(report)


def _render_mode_floor_axis(mode: dict[str, object] | None) -> None:
    """Render rag's provisioning mode-and-floor axis, clearly labelled.

    Silent when no rag entry is declared (``mode is None``), matching the JSON
    envelope's omission, so a pre-install run shows no provisioning block.
    """
    if mode is None:
        return
    _cli.console.print("Provisioning (vaultspec-rag):", markup=False, highlight=False)
    _cli.console.print(
        f"  declared mode: {mode.get('declared_mode', '?')}",
        markup=False,
        highlight=False,
    )
    if mode.get("mode_mismatch") == "mismatch":
        detail = "mismatch - .mcp.json launch shape disagrees with the declared mode"
    elif mode.get("mode_mismatch") == "unknown":
        detail = "unknown - no mode declared"
    else:
        detail = "ok - artifacts match the declared mode"
    _cli.console.print(f"  install mode: {detail}", markup=False, highlight=False)
    if mode.get("version_floor") == "below":
        _cli.console.print(
            f"  version floor: error - running {mode.get('version_floor_running')} "
            f"is below the declared floor {mode.get('version_floor_minimum')}; "
            f"upgrade with uv tool upgrade vaultspec-rag",
            markup=False,
            highlight=False,
        )
    else:
        _cli.console.print("  version floor: ok", markup=False, highlight=False)


def _overall_label(overall_ready: bool, status: str) -> str:
    if overall_ready:
        return "ready for requests"
    if status == "needs_restart":
        return "not ready - service needs restart"
    return "not ready"


def _render_live_service_axis(service: dict[str, object]) -> None:
    """Render the live-service axis block, clearly labelled and separate."""
    _cli.console.print("Live service:", markup=False, highlight=False)
    if not service.get("present"):
        _cli.console.print(
            f"  {service.get('label', 'no service has been started')}",
            markup=False,
            highlight=False,
        )
        return
    state_word = "running" if service.get("live") else "not running"
    _cli.console.print(
        f"  status: {state_word} ({service.get('label', service.get('state', '?'))})",
        markup=False,
        highlight=False,
    )
    _cli.console.print(
        f"  process: pid {service.get('pid')} "
        f"({'alive' if service.get('pid_alive') else 'not alive'})",
        markup=False,
        highlight=False,
    )
    _cli.console.print(
        f"  network: port {service.get('port')} "
        f"({'listening' if service.get('port_listening') else 'not listening'})",
        markup=False,
        highlight=False,
    )
    heartbeat_age = service.get("heartbeat_age_seconds")
    if isinstance(heartbeat_age, int | float) and not isinstance(heartbeat_age, bool):
        suffix = " (stale)" if service.get("heartbeat_stale") else ""
        _cli.console.print(
            f"  heartbeat: {heartbeat_age:.0f}s ago{suffix}",
            markup=False,
            highlight=False,
        )
    else:
        _cli.console.print("  heartbeat: absent", markup=False, highlight=False)


def _render_dependency_axis(report: dict[str, object]) -> None:
    """Render the installed-dependency axis block, clearly labelled and separate."""
    deps_ready = bool(report.get("ready"))
    _cli.console.print(
        f"Installed dependencies: {'ready' if deps_ready else 'not ready'}",
        markup=False,
        highlight=False,
    )
    deps = report.get("dependencies")
    dep_list = cast("list[object]", deps) if isinstance(deps, list) else []
    for dep in dep_list:
        if not isinstance(dep, dict):
            continue
        dep_map = cast("dict[str, object]", dep)
        name = str(dep_map.get("name", "?"))
        dep_status = str(dep_map.get("status", "unknown"))
        detail = str(dep_map.get("detail", ""))
        line = f"  {name}: {dep_status}" + (f" - {detail}" if detail else "")
        _cli.console.print(line, markup=False, highlight=False)
