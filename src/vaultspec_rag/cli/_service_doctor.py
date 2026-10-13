"""``server doctor`` - readiness across two distinct axes.

A thin adapter over the service-domain operability behaviour. It reports two
axes that earlier conflated into one misleading ``ready`` flag:

- the **installed-dependency** axis (``api.get_readiness`` - torch, models, the
  qdrant binary on disk), safe to call before any runtime is up. Torch is
  judged in the interpreter a started service would run in, from a child
  process, so the doctor itself never imports it; and
- the **live-service** axis, computed from the discovery file and the same
  ``server status`` liveness signals (PID alive, our PID, port listening,
  heartbeat fresh) so a dead daemon is never reported as ready.

The doctor never duplicates the status-path liveness computation: it reuses
``_evaluate_service_signals`` and the service client's lifecycle composer
(the service domain owns operability; adapters only render it). It mutates
nothing - the dependency reporter and the live signals are both read-only.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, cast

import typer
from vaultspec_core.config.workspace import WorkspaceError, resolve_workspace

from .._operator_commands import server_start_command
from .._readiness import ReadinessStatus
from ..api import get_readiness
from ..commands._mode import RAG_DISTRIBUTION_NAME
from ..operator_state._holders import HolderRole, holder_line
from ..operator_state._provisioning import (
    classify_tool_receipt,
    upgrade_commands_for_mode,
)
from ..operator_state._service import ServiceLifecycle
from ..operator_state._topology import (
    RuntimeEnvKind,
    classify_environment,
    environment_root,
)
from ._app import JSON_ENVELOPE_OPTION_HELP, _global_target, server_root_app
from ._process import _resolve_daemon_interpreter
from ._render import (
    BAD,
    COMMAND,
    GOOD,
    HEADING,
    MUTED,
    WARN,
    _emit_json,
    _heading,
    _plain,
    _print_next_action,
    _styled,
    lifecycle_style,
)

if TYPE_CHECKING:
    from ..operator_state._models import ComputeReport
    from ..service_runtime import PlannedService


@server_root_app.command(
    "doctor",
    help=(
        "Report readiness across two axes: installed dependencies (torch, "
        "models, qdrant binary) and the live service (a running daemon's "
        "health). A dead or absent daemon is reported as not ready, with "
        "exactly one command to resolve it. Each pinned model's cached "
        "files are hashed against the digests compiled into this tool, "
        "which reads several gigabytes and takes a few seconds; a model "
        "with no such digests is reported as unpinned."
    ),
)
def service_doctor(
    ctx: typer.Context,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help=f"{JSON_ENVELOPE_OPTION_HELP} It is the readiness snapshot.",
        ),
    ] = False,
) -> None:
    """Render the two-axis readiness snapshot in human or JSON mode.

    The installed-dependency axis comes from the read-only reporter
    (``api.get_readiness``). The live-service axis reads the discovery file
    and, when present, derives the running daemon's state from the same
    signals ``server status`` uses. The top-line ``ready`` is honest: it is
    True only when a live, healthy daemon answers *and* every dependency row
    is ready (or not applicable). No discovery file at all means no service
    is running, which is never read as ready, whatever the dependency rows
    say - a client's own "not needed" rows must never be mistaken for "this
    installation can answer requests". A daemon that is expected (a
    discovery file exists) but is not live and healthy reads ``False`` with
    a ``needs_restart`` status. The installed-dependency axis stays present
    and labelled either way, so what is provisioned is still visible beside
    the live truth. Mutates nothing.
    """
    launching = _resolve_daemon_interpreter()
    planned, compute = _planned_service(launching)
    # The holders that matter are the ones holding the environment the
    # service would run in, which is not necessarily this command's own, and
    # which is nobody's environment at all until a runtime exists.
    # The deep check: this is the one command that proves the model cache
    # without starting the service, so it pays for hashing it.
    report = get_readiness(
        holders_root=(
            None if planned.runtime_required else environment_root(planned.interpreter)
        ),
        compute=compute,
        verify_models=True,
    )
    service = _live_service_axis()
    mode = _mode_floor_axis(_resolve_doctor_target(ctx), planned, launching)
    runtime = _service_runtime_axis(planned)
    overall_ready, status = _overall_readiness(report, service)
    next_action = _doctor_next_action(status)
    if json_output:
        envelope = {
            "ready": overall_ready,
            "status": status,
            "server_mode": bool(report.get("server_mode")),
            "dependencies_ready": bool(report.get("ready")),
            "dependencies": report.get("dependencies"),
            "service": service,
            "mode": mode,
            "interpreter": planned.interpreter,
            "environment_holders": report.get("environment_holders"),
            "service_runtime": runtime,
            "receipt": _receipt_axis(planned),
            "next_action": next_action,
        }
        _emit_json(overall_ready, "server doctor", data=envelope)
    else:
        _render_readiness(report, service, overall_ready, status)
        _render_service_runtime_axis(runtime)
        _render_receipt_axis(planned)
        _render_environment_holders(report)
        _render_mode_floor_axis(mode)
        _print_next_action(next_action)
    raise typer.Exit(code=_doctor_exit_code(overall_ready, service, mode))


def _planned_service(launching: str) -> tuple[PlannedService, ComputeReport]:
    """Judge the environment the daemon would run in, and report its compute.

    One probe for the launching environment, and one more only when a
    runtime would serve - each a child of the interpreter it judges, so this
    command still never imports torch. A runtime that does not exist yet is
    reported as unchecked rather than as the launcher's verdict: what the
    launcher's torch is says nothing about what the runtime will hold, and a
    launcher that cannot serve is no longer a defect to repair.
    """
    from ..operator_state._compute import ProbeDepth
    from ..operator_state._environment_probe import probe_interpreter
    from ..operator_state._installation import ComputeCapability
    from ..operator_state._models import ComputeReport
    from ..operator_state._service_environment import (
        ServiceEnvironment,
        judge_foreign_environment,
    )
    from ..service_runtime import planned_service_environment

    probed: dict[str, ComputeReport] = {}

    def judge(interpreter: str) -> ServiceEnvironment:
        report = probe_interpreter(interpreter, ProbeDepth.VERIFY).compute
        probed[interpreter] = report
        return judge_foreign_environment(interpreter, probed=report)

    planned = planned_service_environment(judge(launching), judge=judge)
    if planned.runtime_required:
        return planned, ComputeReport(
            capability=ComputeCapability.UNKNOWN, detail=_RUNTIME_PENDING
        )
    return planned, probed[planned.interpreter]


def _doctor_exit_code(
    overall_ready: bool,
    service: dict[str, object],
    mode: dict[str, object] | None,
) -> int:
    """Fold every axis into an exit code, error over warn.

    ``overall_ready`` already folds in the live-service axis and every
    dependency row ``compute_readiness`` reports (torch, models, qdrant, and
    any row a future dependency adds), so a start that would fail for any
    reason - a dead or absent daemon, or a dependency that is not ready -
    lifts the exit code without this function naming any one dependency.
    Mirrors core's ``spec doctor`` weighting for the shared per-package axis
    on top: a ``vaultspec-rag`` entry running below its declared floor is an
    error, a declared-vs-observed mode mismatch is a warning. The highest
    severity wins: ``2`` for any error, ``1`` for any warning or not-ready
    verdict, ``0`` only when every axis is ready.
    """
    below_floor = mode is not None and mode.get("version_floor") == "below"
    mismatch = mode is not None and mode.get("mode_mismatch") == "mismatch"
    # A running daemon from another release is actionable in the same way the
    # other warnings are: the operator must replace it. False only when a
    # daemon was actually observed, so an absent daemon is unaffected - it
    # already makes ``overall_ready`` False on its own.
    foreign_release = service.get("version_compatible") is False
    if below_floor:
        return 2
    if not overall_ready or mismatch or foreign_release:
        return 1
    return 0


def _live_service_axis() -> dict[str, object]:
    """Compute the live-service axis from the discovery file, read-only.

    Returns a labelled block describing whether a daemon that is expected to
    be running actually is. When no discovery file exists, the service is not
    started (``present: False``), which keeps the top-line readiness False -
    nothing is running to answer a request. When a discovery file exists, the
    same lifecycle
    signals that back ``server status`` (PID alive, our PID, port listening,
    heartbeat fresh) derive the state, so the doctor and status never disagree.

    Reuses ``_evaluate_service_signals`` from the lifecycle module rather than
    recomputing liveness (the service domain owns operability). That helper
    cleans a confirmed-dead stale ``service.json`` as a side effect, matching
    ``server status`` behaviour exactly.
    """
    from ..serviceclient._compat import classify_service_version
    from ..serviceclient._discovery import read_service_status, resolve_machine_service
    from ..serviceclient._status import compose_discovery_status
    from ._status_render import _evaluate_service_signals, _liveness_from_resolution

    status = read_service_status()
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
        if verdict.state is ServiceLifecycle.STOPPED:
            return {
                "present": False,
                "live": False,
                "state": "not_started",
                "label": "no service has been started (no discovery file)",
            }
        version = classify_service_version(resolution.payload)
        return {
            "present": True,
            "live": verdict.is_live,
            "state": verdict.state.value,
            "label": verdict.label,
            "pid": verdict.signals.pid,
            "port": verdict.port,
            "pid_alive": verdict.signals.pid_alive,
            "pid_matches_service": verdict.signals.pid_matches_service,
            "port_listening": verdict.signals.port_listening,
            "heartbeat_age_seconds": verdict.signals.heartbeat_age_s,
            "heartbeat_stale": verdict.signals.heartbeat_stale,
            "discovery_evidence": resolution.evidence(),
            "version": version.to_dict(),
            "version_compatible": version.is_compatible,
        }

    signals = _evaluate_service_signals(status)
    live = signals.state.is_live
    status_version = classify_service_version(status)
    return {
        "present": True,
        "live": live,
        "state": signals.state.value,
        "label": signals.state_label,
        "pid": signals.pid,
        "port": signals.port,
        "pid_alive": signals.pid_alive,
        "pid_matches_service": signals.pid_is_ours,
        "port_listening": signals.port_listening,
        "heartbeat_age_seconds": signals.heartbeat_age,
        "heartbeat_stale": signals.heartbeat_stale,
        "version": status_version.to_dict(),
        "version_compatible": status_version.is_compatible,
    }


def _overall_readiness(
    report: dict[str, object],
    service: dict[str, object],
) -> tuple[bool, str]:
    """Fold the two axes into an honest top-line ``(ready, status)``.

    - No discovery file at all: no service is running, so ``ready`` is
      always False with status ``not_running`` - a ``server start`` would be
      the first action an operator takes, so the top line never reads ready
      on the strength of installed dependencies alone. A client's own "not
      needed" dependency rows are exactly the case this guards: they must
      never be mistaken for "this installation can answer requests".
    - Discovery file present but the daemon is not live: ``ready`` is False
      and the status is ``needs_restart`` - a dead-but-expected daemon must
      never read ready, regardless of installed dependencies.
    - Discovery file present and the daemon is live and healthy: ``ready``
      when every dependency row is also ready (or not applicable), status
      ``ready`` / ``dependencies_not_ready``. Generic over whatever rows the
      dependency report carries.
    """
    deps_ready = bool(report.get("ready"))
    if not service.get("present"):
        return False, "not_running"
    if not service.get("live"):
        return False, "needs_restart"
    if service.get("state") == ServiceLifecycle.STARTING:
        return False, "starting"
    return deps_ready, ("ready" if deps_ready else "dependencies_not_ready")


def _doctor_next_action(status: str) -> str | None:
    """Return the one command that resolves *status* on its own, or ``None``.

    Only the "nothing is running" status has a single command that resolves
    it by itself; every other not-ready status is already explained by its
    own axis (the live-service block names the daemon's condition, and each
    not-ready dependency row carries its own remedy as its ``detail``), so
    naming a second command here would violate the one-cause-one-command
    messaging constraint rather than serve it.
    """
    if status == "not_running":
        return server_start_command()
    return None


def _resolve_doctor_target(ctx: typer.Context) -> Path:
    """Resolve the workspace root the same way the other commands do.

    Root ``--target`` (or the environment variable it falls back to, already
    stashed on ``ctx.obj`` by the root callback) outranks git/structural
    discovery, which outranks the working directory - the same chain
    ``resolve_workspace`` applies for every non-``server``/``install``/
    ``uninstall`` command. ``server`` short-circuits that resolution at the
    root callback (it does not always need a workspace), so doctor - the one
    ``server`` subcommand that reads workspace-scoped state - resolves it
    here instead of reading ``Path.cwd()`` directly.

    Falls back to the named target (or ``cwd``) rather than raising: the
    doctor mutates nothing and never crashes on a probe, matching every
    other axis's failure contract.
    """
    named_target = _global_target(ctx)
    try:
        return resolve_workspace(target_override=named_target).target_dir
    except WorkspaceError:
        return named_target or Path.cwd()


def _mode_floor_axis(
    target: Path, planned: PlannedService, launching: str
) -> dict[str, object] | None:
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
        planned: Where the daemon would run, which decides whether the
            upgrade sequence has to keep this installation's own accelerator
            build or only take the newer release.
        launching: The interpreter of the installation being upgraded, which
            is this one whether or not the daemon runs from it.

    Returns:
        A labelled block with ``declared_mode``, ``mode_mismatch``,
        ``version_floor``, ``version_floor_running``, and
        ``version_floor_minimum``, or ``None`` when no rag entry is declared.
    """
    try:
        from vaultspec_core.core.diagnosis.collectors import (
            collect_mode_mismatch_state,
            collect_version_floor_state,
        )
        from vaultspec_core.core.workspace_mode import (
            read_package_declaration,
        )

        declaration = read_package_declaration(target, RAG_DISTRIBUTION_NAME)
        if declaration is None:
            return None
        mode_mismatch = collect_mode_mismatch_state(
            target, package=RAG_DISTRIBUTION_NAME
        )
        floor, running, minimum = collect_version_floor_state(
            target, package=RAG_DISTRIBUTION_NAME
        )
    except Exception:
        return None
    declared_mode = declaration.install_mode.value
    return {
        "package": RAG_DISTRIBUTION_NAME,
        "declared_mode": declared_mode,
        "mode_mismatch": mode_mismatch.value,
        "version_floor": floor.value,
        "version_floor_running": running,
        "version_floor_minimum": minimum,
        # Computed here so the envelope and the rendered block read one value.
        "upgrade_commands": list(
            upgrade_commands_for_mode(
                declared_mode, launching, serves=planned.launcher_serves
            )
        ),
    }


def _render_readiness(
    report: dict[str, object],
    service: dict[str, object],
    overall_ready: bool,
    status: str,
) -> None:
    """Render both readiness axes as a bounded plain-text summary."""
    server_mode = bool(report.get("server_mode"))
    _heading("Service readiness")
    _plain(f"Backend: {'server' if server_mode else 'local-only'}")
    _styled(
        "Readiness: ",
        (_overall_label(overall_ready, status), GOOD if overall_ready else BAD),
    )
    _render_live_service_axis(service)
    _render_dependency_axis(report)


#: Why the environment the daemon would run in has nothing to report yet.
_RUNTIME_PENDING = "the service runtime does not exist yet"


def _service_runtime_axis(planned: PlannedService) -> dict[str, object] | None:
    """Say where the daemon would run from, when that is not this environment.

    ``None`` for a launcher that serves the daemon itself: there is no
    runtime in that story, and a row about one would be a warning for a
    state that is not present.

    A runtime that has still to be created is not a defect of anything the
    operator installed, so it is reported as one sentence naming the one
    command that creates it, and it is kept out of the dependency rows the
    top-line verdict folds in: nothing about a live, healthy service becomes
    untrue because a runtime it does not use is absent.
    """
    if planned.launcher_serves:
        return None
    if planned.runtime_required:
        return {
            "source": str(planned.source),
            "ready": False,
            "label": (
                f"not ready - the first `{server_start_command()}` creates the "
                f"environment the service runs in"
            ),
        }
    return {
        "source": str(planned.source),
        "ready": True,
        "label": f"ready - the service runs from {planned.interpreter}",
    }


def _render_service_runtime_axis(axis: dict[str, object] | None) -> None:
    """Report where the daemon would run from, when a runtime is involved."""
    if axis is None:
        return
    ready = bool(axis.get("ready"))
    _styled(
        ("Service runtime:", HEADING),
        (f" {axis.get('label', '?')}", GOOD if ready else WARN),
        soft_wrap=True,
    )


def _receipt_axis(planned: PlannedService) -> dict[str, object] | None:
    """What an upgrade of this installation would resolve, or ``None``.

    Only a uv tool installation has a receipt to judge. Everything else
    resolves from a project or from nothing, and reporting a verdict about a
    file that does not exist would be an invented fact.

    An installation the daemon does not run from has no receipt worth a row
    either: what its next upgrade resolves for torch decides nothing about a
    service that runs from its own environment, and the fix would be a repair
    of something that is not broken.
    """
    if not planned.launcher_serves:
        return None
    interpreter = planned.interpreter
    kind = classify_environment(environment_root(interpreter))
    if kind is not RuntimeEnvKind.UV_TOOL:
        return None
    verdict = classify_tool_receipt(interpreter)
    return {
        "verdict": verdict.value,
        "label": verdict.label,
        "durable": verdict.durable,
        "fix": list(verdict.fix(interpreter)),
    }


def _render_receipt_axis(planned: PlannedService) -> None:
    """Report what the next upgrade of this installation would resolve."""
    axis = _receipt_axis(planned)
    if axis is None:
        return
    raw = axis["fix"]
    commands = cast("list[object]", raw) if isinstance(raw, list) else []
    _styled(
        ("Installation receipt:", HEADING),
        (f" {axis['label']}", WARN if commands else GOOD),
    )
    if not commands:
        return
    _plain("  make upgrades keep the GPU build, in order:")
    for command in commands:
        # Soft-wrapped: a folded command is not one an operator can paste.
        _styled("    ", (str(command), COMMAND), soft_wrap=True)


def _render_environment_holders(report: dict[str, object]) -> None:
    """Report who is running out of the service environment, and what they are.

    The scan ran for the daemon's environment, so the list is about the
    environment a repair would change rather than the one this command
    happens to run in. Nothing here blocks that repair: it is applied in
    place, and these are the processes that keep the build they imported at
    startup until they are restarted.
    """
    raw = report.get("environment_holders")
    if not isinstance(raw, dict):
        return
    snapshot = cast("dict[str, object]", raw)
    if not snapshot.get("scanned"):
        return
    holders = snapshot.get("holders")
    entries = cast("list[object]", holders) if isinstance(holders, list) else []
    if not entries and snapshot.get("certain") and not snapshot.get("self_held"):
        _plain("Service environment: nothing is running out of it")
        return
    _heading("Running out of the service environment:")
    if snapshot.get("self_held"):
        _plain("  this command is running inside that environment")
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        holder = cast("dict[str, object]", entry)
        pid = holder.get("pid")
        port = holder.get("port")
        launcher = holder.get("launcher_pid")
        _plain(
            "  "
            + holder_line(
                int(pid) if isinstance(pid, int) else 0,
                _holder_role(holder.get("role")),
                launcher_pid=launcher if isinstance(launcher, int) else None,
                port=port if isinstance(port, int) else None,
                remedy=False,
            )
        )
    total = snapshot.get("total")
    if isinstance(total, int) and total > len(entries):
        _plain(f"  ... and {total - len(entries)} more")
    if not snapshot.get("certain"):
        _plain("  the scan was incomplete, so this list may be short")


def _holder_role(value: object) -> HolderRole:
    """Read a reported role, without failing on one this build does not know.

    The snapshot can come from a service of another release, and a role it
    names that this one does not is still a process an operator has to deal
    with. Refusing to render the whole block over the word is a worse answer
    than calling it what it is: something running out of the environment.
    """
    try:
        return HolderRole(str(value))
    except ValueError:
        return HolderRole.UNRECOGNISED


def _render_mode_floor_axis(mode: dict[str, object] | None) -> None:
    """Render rag's provisioning mode-and-floor axis, clearly labelled.

    Silent when no rag entry is declared (``mode is None``), matching the JSON
    envelope's omission, so a pre-install run shows no provisioning block.
    """
    if mode is None:
        return
    _heading("Provisioning (vaultspec-rag):")
    _plain(f"  declared mode: {mode.get('declared_mode', '?')}")
    if mode.get("mode_mismatch") == "mismatch":
        verdict, style = "mismatch", WARN
        detail = " - .mcp.json launch shape disagrees with the declared mode"
    elif mode.get("mode_mismatch") == "unknown":
        verdict, style, detail = "unknown", WARN, " - no mode declared"
    else:
        verdict, style = "ok", GOOD
        detail = " - artifacts match the declared mode"
    _styled("  install mode: ", (verdict, style), detail)
    if mode.get("version_floor") == "below":
        _styled(
            "  version floor: ",
            ("error", BAD),
            f" - running {mode.get('version_floor_running')} "
            f"is below the declared floor {mode.get('version_floor_minimum')}",
        )
        _plain("    upgrade with, in order:")
        raw = mode.get("upgrade_commands")
        commands = cast("list[object]", raw) if isinstance(raw, list) else []
        for command in commands:
            # Soft-wrapped: a folded command is not one an operator can paste.
            _styled("      ", (str(command), COMMAND), soft_wrap=True)
    else:
        _styled("  version floor: ", ("ok", GOOD))


def _overall_label(overall_ready: bool, status: str) -> str:
    if overall_ready:
        return "ready for requests"
    if status == "not_running":
        return "not ready - no service is running"
    if status == "needs_restart":
        return "not ready - service needs restart"
    if status == "starting":
        return f"not ready yet - {ServiceLifecycle.STARTING.label}"
    return "not ready"


def _render_live_service_axis(service: dict[str, object]) -> None:
    """Render the live-service axis block, clearly labelled and separate."""
    _heading("Live service:")
    if not service.get("present"):
        label = str(service.get("label", "no service has been started"))
        _styled("  ", (label, WARN))
        return
    label = str(service.get("label", service.get("state", "?")))
    _styled("  status: ", (label, lifecycle_style(service.get("state"))))
    alive = bool(service.get("pid_alive"))
    _styled(
        f"  process: pid {service.get('pid')} (",
        ("alive" if alive else "not alive", GOOD if alive else BAD),
        ")",
    )
    listening = bool(service.get("port_listening"))
    _styled(
        f"  network: port {service.get('port')} (",
        ("listening" if listening else "not listening", GOOD if listening else BAD),
        ")",
    )
    heartbeat_age = service.get("heartbeat_age_seconds")
    if isinstance(heartbeat_age, int | float) and not isinstance(heartbeat_age, bool):
        stale = " (stale)" if service.get("heartbeat_stale") else ""
        _styled(f"  heartbeat: {heartbeat_age:.0f}s ago", (stale, WARN))
    else:
        _styled("  heartbeat: ", ("absent", WARN))
    version = service.get("version")
    if isinstance(version, dict):
        version_map = cast("dict[str, object]", version)
        reported = version_map.get("service_version") or "not reported"
        compatible = bool(version_map.get("compatible"))
        state = "matches this client" if compatible else "INCOMPATIBLE"
        _styled(f"  release: {reported} (", (state, GOOD if compatible else BAD), ")")


def _render_dependency_axis(report: dict[str, object]) -> None:
    """Render the installed-dependency axis block, clearly labelled and separate."""
    deps_ready = bool(report.get("ready"))
    _styled(
        ("Installed dependencies:", HEADING),
        " ",
        ("ready" if deps_ready else "not ready", GOOD if deps_ready else BAD),
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
        _styled(
            f"  {name}: ",
            (dep_status, _DEPENDENCY_STYLE.get(dep_status, WARN)),
            f" - {detail}" if detail else "",
        )


_DEPENDENCY_STYLE = {
    ReadinessStatus.READY.value: GOOD,
    ReadinessStatus.NOT_READY.value: BAD,
    # Muted, not green: "not applicable" is not a signal that this
    # installation can itself run the service.
    ReadinessStatus.NOT_APPLICABLE.value: MUTED,
}
