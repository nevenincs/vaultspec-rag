"""``server stop``: terminate the resident service and attribute the shutdown.

Owns the stop path: the ``--port`` identity-resolved stop, the status-file
stop, and the machine-singleton reclaim that recovers a holder with no
discoverable ``service.json``. A stop that leaves the service running is a
failure (``_fail_stop``, exit 1) in both output modes; every satisfied outcome
(``stopped`` / ``already_stopped`` / ``cleaned`` / ``reclaimed`` / ``reaped``)
is a success so a broker treats the idempotent case as done.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Annotated, cast

import typer

import vaultspec_rag.cli as _cli

from ._app import server_app
from ._core import logger
from ._http_search import _try_http_health
from ._process import (
    _DEFAULT_GRACEFUL_DRAIN_SECONDS,
    _port_is_listening,
)
from ._service_lifecycle import (
    _fail_lifecycle,
    _lifecycle_success,
    _process_line,
    _should_unlink_discovery_file,
)
from ._service_status import _delete_service_status, _read_service_status

__all__ = [
    "_fail_stop",
    "_initiator_fields",
    "_reclaim_machine_singleton",
    "_service_pid_on_port",
    "_stop_service_on_port",
    "_stop_success",
    "_terminate_and_confirm",
    "service_stop",
]

_STOP_COMMAND = "service.stop"

# An operator stop waits for the daemon's own lifespan shutdown so both
# discovery views are removed by the only lease holder authorized to remove
# them. The drain covers job drain, store close, GPU release, and managed
# Qdrant teardown; the surrounding budget leaves room for the forced-kill
# escalation and owned-child reap once the drain window expires.
_STOP_GRACEFUL_DRAIN_SECONDS = 20.0
_STOP_TERMINATION_BUDGET_SECONDS = 45.0


def _reclaim_machine_singleton() -> int | None:
    """Reclaim a resident machine-lock holder that has no discoverable status file.

    The machine singleton lock is vaultspec-rag-exclusive and machine-scoped, so
    a live holder is THE resident service even when it never registered (or lost)
    a ``service.json`` in this status directory. Such a holder otherwise
    deadlocks the machine: ``server start`` refuses it (lock held), ``server
    stop`` reports "not running" (no discovery), and ``server status`` reports
    stopped - leaving a manual OS kill as the only escape. Terminating the
    confirmed holder
    makes ``server stop`` the real recovery the start refusal points to.

    Returns the reclaimed holder pid, or ``None`` when no reclaimable
    vaultspec-rag holder is found. The ``_is_our_service`` executable check
    guards against terminating an unrelated process after pid reuse.
    """
    from .._machine_lock import machine_lock_live_holder

    holder = machine_lock_live_holder()
    if (
        holder
        and holder != os.getpid()
        and _cli._is_pid_alive(holder)
        and _cli._is_our_service(holder)
    ):
        _terminate_and_confirm(holder)
        return holder
    return None


def _initiator_fields() -> dict[str, str]:
    """Return the identity of the process performing the stop, for attribution.

    Carries the terminating process' own pid, command line, and cwd so "who
    stopped the machine service" is answerable from one shutdown record rather
    than only naming the terminated pid. The command line is bounded so a long
    argv cannot bloat the audit line or the envelope. The argv is logged
    verbatim, which constrains future stop flags: none may ever carry a
    secret without revisiting this field.
    """
    cmd = " ".join(sys.argv)
    if len(cmd) > 300:
        cmd = f"{cmd[:297]}..."
    return {
        "initiator_pid": str(os.getpid()),
        "initiator_cmd": cmd,
        "initiator_cwd": os.getcwd(),
    }


def _refuse_terminate_from_unisolated_test() -> None:
    """Refuse to touch the machine-global service from an unisolated test run.

    A pytest run in a development worktree once resolved the operator's
    real managed service (no isolated status/storage dirs in its
    environment) and terminated it mid-index, killing two in-flight
    production jobs. Tests must run against isolated dirs; when the
    terminate path detects a pytest context whose environment still
    resolves the machine-global singleton, failing the test loudly is
    strictly better than stopping the operator's daemon.

    Raises:
        RuntimeError: When called under pytest without either machine-dir
            env override in place.
    """
    if "PYTEST_CURRENT_TEST" not in os.environ:
        return
    from ..config import EnvVar

    if os.environ.get(EnvVar.STATUS_DIR.value) or os.environ.get(
        EnvVar.QDRANT_STORAGE_DIR.value
    ):
        return
    raise RuntimeError(
        "refusing to terminate the machine-global vaultspec-rag service from "
        "a test run: neither VAULTSPEC_RAG_STATUS_DIR nor "
        "VAULTSPEC_RAG_QDRANT_STORAGE_DIR is isolated. Point both at a temp "
        "dir (the test-suite conftest does this automatically) so the test "
        "exercises its own sandboxed service instead of the operator's."
    )


def _stop_graceful_drain_seconds() -> float:
    """Return the drain window worth funding on this platform.

    A daemon that can act on the termination signal cleans up after itself,
    which is always the better outcome: it is the lease holder, so it is the
    only process that can delete its own discovery pointer while still owning
    the singleton. POSIX delivers ``SIGTERM`` to it, so the wait buys a real
    clean shutdown. Windows cannot: the daemon is spawned console-detached, and
    a console control event only reaches processes sharing the sender's
    console, so the signal is never delivered and waiting on it would buy
    nothing but latency before the forced kill.
    """
    if sys.platform == "win32":
        return _DEFAULT_GRACEFUL_DRAIN_SECONDS
    return _STOP_GRACEFUL_DRAIN_SECONDS


def _clean_orphaned_machine_pointer() -> bool:
    """Delete a discovery pointer whose publishing daemon is confirmed gone.

    Pointer deletion is owner-authenticated, so this does not bypass that
    contract - it satisfies it. The previous holder's death released the OS
    lock, so acquiring it here makes this process the singleton owner for the
    duration of the delete. A failure to acquire means someone else already
    owns the singleton, and a live owner's pointer is theirs to publish and
    clean; refusing to touch it is what keeps a stop from erasing a successor's
    discovery.

    Returns whether the pointer is gone.
    """
    from .._machine_lock import (
        acquire_machine_lock_lease,
        delete_machine_discovery,
        machine_discovery_path,
        release_machine_lock_lease,
    )

    try:
        if not machine_discovery_path().exists():
            return True
        lease, _holder = acquire_machine_lock_lease()
        if lease is None:
            return False
        try:
            delete_machine_discovery(lease)
        finally:
            release_machine_lock_lease(lease)
    except (OSError, PermissionError, RuntimeError) as exc:
        # Never fail a satisfied stop over cleanup of a record the staleness
        # contract already neutralises; debug-log so the swallow is observable.
        logger.debug("orphaned machine pointer cleanup failed: %s", exc, exc_info=True)
        return False
    return True


def _terminate_and_confirm(pid: int, *, console_group_signal: bool = True) -> None:
    """Terminate *pid*, confirm its exit, then clear its discovery records.

    ``console_group_signal`` MUST be False for a DISCOVERED pid the caller did
    not spawn (the orphan reap): a Windows ``CTRL_BREAK_EVENT`` addressed to an
    arbitrary pid that is not a known group leader is undefined and can be
    delivered to the CALLER's own console group, so a discovered target is
    force-killed by pid via ``TerminateProcess`` instead.
    """
    _refuse_terminate_from_unisolated_test()
    _cli._terminate_pid(
        pid,
        timeout=_STOP_TERMINATION_BUDGET_SECONDS,
        graceful_drain=_stop_graceful_drain_seconds(),
        console_group_signal=console_group_signal,
    )

    # Wait briefly for process to exit
    for _ in range(50):
        if not _cli._is_pid_alive(pid):
            break
        time.sleep(0.1)

    # A forced kill leaves the daemon's own pointer behind. Now that its holder
    # is gone the singleton is free, so reclaim it and remove the record rather
    # than leaving a pointer that advertises a dead process.
    if not _cli._is_pid_alive(pid):
        _clean_orphaned_machine_pointer()

    # On Windows this is always a force-kill: the daemon is spawned detached
    # from any shell, so this separate stop process shares no console with it
    # and a console-scoped CTRL_BREAK cannot reach it - the graceful signal
    # fails and the escalation TerminateProcess is what actually stops it,
    # bypassing the daemon's atexit handler and lifespan ``finally``. The CLI
    # parent emits this mirror line so Windows operators keep the audit trail
    # the daemon never got to write. POSIX flows through SIGTERM → uvicorn's
    # signal handler → lifespan finally → ``_record_shutdown("clean")`` and the
    # daemon logs its own clean shutdown, but the CLI-side initiator attribution
    # is valuable on every platform, so the line is emitted unconditionally.
    _cli._append_lifecycle_shutdown_log(
        "cli_terminate",
        pid=pid,
        platform=sys.platform,
        **_initiator_fields(),
    )


def _service_pid_on_port(port: int) -> tuple[int, str | None] | None:
    """Resolve the live serving pid (and token) on *port* via ``/health``.

    The service domain owns identity: ``/health`` reports the serving pid and
    the per-process token, so a service on a non-default port is resolvable
    without the status file (which is keyed per status dir and may diverge from
    the running instance). Returns ``None`` when nothing healthy
    is serving the port.
    """
    if not _port_is_listening(port):
        return None
    health = _try_http_health(port)
    if health is None:
        return None
    serving_pid = health.get("pid")
    if not isinstance(serving_pid, int) or serving_pid <= 0:
        return None
    raw_token = health.get("service_token")
    token = raw_token if isinstance(raw_token, str) and raw_token else None
    return serving_pid, token


def _stop_success(
    json_mode: bool,
    *,
    status: str,
    human_title: str,
    human_lines: tuple[str, ...] = (),
    **data: object,
) -> None:
    """Emit a successful stop outcome (``stopped`` / ``already_stopped`` / ...).

    Binds the stop command name to the one shared lifecycle success renderer.
    An already-stopped service is a success so a supervising broker treats the
    idempotent case as satisfied rather than as a fault; that rule lives in the
    shared renderer alongside the envelope-versus-human decision.
    """
    _lifecycle_success(
        json_mode,
        command=_STOP_COMMAND,
        status=status,
        human_title=human_title,
        human_lines=human_lines,
        **data,
    )


def _fail_stop(
    json_mode: bool,
    *,
    error: str,
    message: str,
    human_lines: tuple[str, ...],
    next_actions: tuple[str, ...] = (),
    **data: object,
) -> typer.Exit:
    """Render a failed stop outcome and RETURN the ``typer.Exit`` to raise.

    A stop that leaves the service running did not do its job, so it exits 1 in
    BOTH human and ``--json`` modes - a broker or script must never read a
    skipped stop as success. That rule lives in the shared renderer this binds
    the stop command name to.
    """
    return _fail_lifecycle(
        json_mode,
        command=_STOP_COMMAND,
        error=error,
        message=message,
        human_lines=human_lines,
        next_actions=next_actions,
        **data,
    )


def _stop_service_on_port(port: int, json_mode: bool = False) -> None:
    """Stop the service answering on *port*, status-file independent.

    Targets the running instance the operator named with ``--port`` even when
    the status file is missing or records a divergent port. The
    discovery file is only removed when it actually points at this port, so
    stopping one config's service never erases another's discovery file.
    """
    resolved = _service_pid_on_port(port)
    if resolved is None:
        _stop_success(
            json_mode,
            status="already_stopped",
            human_title="Service is not running.",
            human_lines=(f"No service is answering on http://127.0.0.1:{port}.",),
            port=port,
        )
        return
    pid, token = resolved
    if not _cli._is_our_service(pid, port=port, expected_token=token):
        raise _fail_stop(
            json_mode,
            error="identity_unconfirmed",
            message="Service stop skipped",
            human_lines=(
                f"A process is answering on port {port} but its identity could "
                "not be confirmed as a vaultspec-rag service; it was left "
                "running.",
            ),
            next_actions=(f"vaultspec-rag server status --port {port} --verbose",),
            pid=pid,
            port=port,
        )

    _terminate_and_confirm(pid)

    # Remove the discovery file only when it points at the port we just stopped,
    # so stopping a non-default-port service never erases a different config's
    # status file.
    status = _read_service_status()
    if status is not None and int(status.get("port", 0)) == port:
        _delete_service_status()
    _stop_success(
        json_mode,
        status="stopped",
        human_title="Service stopped",
        human_lines=(_process_line(pid),),
        pid=pid,
        port=port,
        **_initiator_fields(),
    )


def _expected_singleton_port(explicit_port: int | None) -> int | None:
    """Resolve the machine singleton's service port for an orphan reap.

    An explicit ``--port`` wins; otherwise the discovery pointer's port (the
    running singleton), else the configured default. The port is the reap's
    safety scope - a daemon launched for a DIFFERENT port (an isolated-config or
    foreign-worktree instance) is never a reap target.
    """
    if explicit_port is not None:
        return explicit_port
    status = _read_service_status()
    if status is not None:
        raw = status.get("port")
        if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
            return raw
    from ..serviceclient._discovery import _default_service_port

    return _default_service_port()


def _orphan_daemon_pids(port: int) -> dict[int, int]:
    """Return ``{pid: ppid}`` of ``vaultspec_rag.server`` daemons for *port*.

    Matches the resident-daemon launch witness by port (any launch token), so
    every race-loser that tried to serve this machine singleton's port is found,
    while a daemon launched for a different port never matches - the reap scope
    that spares isolated-config and foreign-worktree daemons.

    A venv ``python.exe`` shim spawns the real interpreter, so one logical daemon
    appears as a launcher+worker PAIR both carrying the witness in a parent-child
    relation. The ppid map lets the reap protect, or clear, a whole pair rather
    than half of it.

    Raises:
        OSError: The process table could not be enumerated. Deliberately
            propagated rather than swallowed: a scan that fails silently returns
            no matches, which is indistinguishable from a machine with no
            orphans, and the reap would then report a satisfied no-op. A broker
            reading that success concludes the machine is clear and starts a
            daemon that loses the singleton race to the orphan the scan never
            saw. An unachieved reap must be a fault, never a quiet zero.
    """
    import psutil

    marker = ["-m", "vaultspec_rag.server", "--port", str(port)]
    found: dict[int, int] = {}
    try:
        processes = list(psutil.process_iter(["pid", "ppid", "cmdline"]))
    except Exception as exc:
        logger.warning("orphan scan could not enumerate processes: %s", exc)
        raise OSError(f"could not enumerate processes: {exc}") from exc
    for process in processes:
        try:
            info = cast("dict[str, object]", process.info)
            raw = info.get("cmdline")
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            # Normal while walking a live process table: a process can exit
            # mid-scan, and another user's process is not inspectable. Skipping
            # one such process is correct; skipping the whole scan is not, which
            # is why only these two are caught and only around this read.
            logger.debug("orphan scan skipped a process: %s", exc)
            continue
        if not isinstance(raw, list):
            continue
        argv = [str(item) for item in cast("list[object]", raw)]
        if not any(
            argv[index : index + len(marker)] == marker
            for index in range(len(argv) - len(marker) + 1)
        ):
            continue
        pid = info.get("pid")
        ppid = info.get("ppid")
        if isinstance(pid, int) and not isinstance(pid, bool):
            found[pid] = (
                ppid if isinstance(ppid, int) and not isinstance(ppid, bool) else 0
            )
    return found


def _pid_terminated(pid: int) -> bool:
    """True if *pid* is gone or a POSIX zombie (dead, awaiting parent reap).

    A force-killed orphan whose parent has not yet ``waitpid``'d it lingers as a
    zombie: ``os.kill(pid, 0)`` still succeeds so ``_is_pid_alive`` reports it
    live, yet the process is terminated and holds no GPU, port, or machine lock.
    The reap must count such a defunct process as reaped, not as a survivor -
    otherwise a killed orphan whose supervisor is still running (which reparents
    to init only once that supervisor exits) reads as ``orphan_reap_incomplete``
    despite being dead. Windows has no zombie state (``TerminateProcess`` removes
    the process), so this only refines the POSIX case.
    """
    if not _cli._is_pid_alive(pid):
        return True
    if sys.platform == "win32":
        return False
    import psutil

    try:
        return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True
    except psutil.Error:
        return False


def _guard_unconfirmed_port_holder(
    port: int,
    serving: tuple[int, str | None] | None,
    json_mode: bool,
) -> None:
    """Refuse the reap when the port is held by something that will not identify.

    The identity anchor protects a listener that ANSWERS the health probe. One
    that accepts the connection and stays silent leaves every anchor at zero, so
    the sweep would terminate a live port holder and report a satisfied reap.

    A genuine orphan holds no port - that is what makes it an orphan - so
    refusing here loses nothing this verb exists to clear, and the sibling
    single-port stop already refuses exactly this situation rather than killing
    what it cannot confirm.

    Raises:
        typer.Exit: When something is listening but unidentifiable.
    """
    if serving is not None or not _port_is_listening(port):
        return
    raise _fail_stop(
        json_mode,
        error="port_holder_unconfirmed",
        message="Orphan reap refused: the port is held by an unconfirmed process",
        human_lines=(
            f"Something is listening on port {port} but did not answer the "
            "identity probe, so it cannot be told apart from a live service.",
            "No daemon was reaped. An orphan holds no port, so nothing this "
            "command clears is affected by stopping here.",
        ),
        next_actions=(f"vaultspec-rag server status --port {port} --verbose",),
        port=port,
    )


def _reap_orphan_daemons(port: int, json_mode: bool) -> None:
    """Reap race-loser daemons for the machine singleton on *port*.

    Confirm-then-reap, scoped by the launch witness (same port). The machine-lock
    holder, the discovery-pointer pid, and this process are the must-never-kill
    anchors - the real singleton - and because a venv shim makes each live daemon
    a launcher+worker PAIR, the anchor's matched shim parent and matched children
    are protected too, so a live singleton's launcher is never reaped as an
    orphan. The port scope spares isolated-config and foreign-worktree daemons.
    An orphan that will not die is a non-zero fault, never a silent success.
    """
    from .._machine_lock import machine_lock_live_holder

    try:
        matched = _orphan_daemon_pids(port)
    except OSError as exc:
        # The scan is the whole basis for "there is nothing to reap". If it
        # could not run, the honest outcome is that the request was not
        # satisfied - reporting a reap of zero would tell a broker the machine
        # is clear on the strength of a scan that never happened.
        raise _fail_stop(
            json_mode,
            error="orphan_scan_failed",
            message="Orphan reap could not inspect the process table",
            human_lines=(
                f"Could not enumerate processes to find orphan daemons on "
                f"port {port}: {exc}",
                "No daemon was reaped, and no claim is made about whether any "
                "orphan exists.",
            ),
            next_actions=(f"vaultspec-rag server status --port {port} --verbose",),
            port=port,
            detail=str(exc),
        ) from exc
    lock_holder = machine_lock_live_holder()
    status = _read_service_status()
    pointer_pid = 0
    if status is not None:
        raw = status.get("pid")
        if isinstance(raw, int) and not isinstance(raw, bool):
            pointer_pid = raw

    # The pid actually bound to and answering /health on the port is the
    # authoritative "this daemon owns the port" signal: an isolated-config daemon
    # shares this machine but not this config's lock path or pointer, so neither
    # lock_holder nor pointer_pid captures it. Anchor on it too so a live
    # port-bound daemon is spared regardless of which config's state we can see.
    serving = _service_pid_on_port(port)
    serving_pid = serving[0] if serving is not None else 0

    _guard_unconfirmed_port_holder(port, serving, json_mode)

    anchors = {os.getpid(), lock_holder, pointer_pid, serving_pid}
    protected = set(anchors)
    for pid, ppid in matched.items():
        if pid in anchors and ppid in matched:
            protected.add(ppid)
        if ppid in anchors:
            protected.add(pid)

    reaped: list[int] = []
    survivors: list[int] = []
    for pid in matched:
        if pid in protected or not _cli._is_our_service(pid):
            continue
        # Discovered pid, not one we spawned: force-kill by pid, never a
        # console-group CTRL_BREAK that could reach the operator's own console.
        _terminate_and_confirm(pid, console_group_signal=False)
        (reaped if _pid_terminated(pid) else survivors).append(pid)

    if survivors:
        raise _fail_stop(
            json_mode,
            error="orphan_reap_incomplete",
            message="Orphan reap left daemons running",
            human_lines=(
                f"Reaped {len(reaped)} orphan daemon(s) on port {port}; "
                f"{len(survivors)} would not terminate: {survivors}.",
            ),
            next_actions=(f"vaultspec-rag server status --port {port} --verbose",),
            reaped=len(reaped),
            survivors=survivors,
            port=port,
        )
    _stop_success(
        json_mode,
        status="reaped",
        human_title="Orphan daemons reaped",
        human_lines=(
            f"Reaped {len(reaped)} orphan daemon(s) on port {port}."
            if reaped
            else f"No orphan daemons found on port {port}.",
        ),
        reaped=len(reaped),
        reaped_pids=reaped,
        port=port,
        **_initiator_fields(),
    )


@server_app.command("stop", help="Stop the background search service.")
def service_stop(
    port: Annotated[
        int | None,
        typer.Option(
            "--port",
            help=(
                "Stop the service answering on this port, resolving its identity "
                "from /health rather than the status file. Use when the service "
                "runs on a non-default port or the status file diverges from the "
                "running instance."
            ),
        ),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option(
            "--json",
            help=(
                "Emit one machine-readable outcome envelope instead of human "
                "text. An already-stopped service is the success "
                "`already_stopped` (exit 0); a stop that leaves the service "
                "running (unconfirmed identity) is `identity_unconfirmed` "
                "(exit 1) in both output modes."
            ),
        ),
    ] = False,
    orphans: Annotated[
        bool,
        typer.Option(
            "--orphans",
            help=(
                "Reap surplus vaultspec-rag daemons that lost the machine-"
                "singleton race and linger holding no port, lock, or discovery "
                "pointer, invisible to a normal stop. Confirm-then-reap, scoped "
                "to this singleton's port; the live singleton, isolated-config, "
                "and foreign-worktree daemons are always spared."
            ),
        ),
    ] = False,
) -> None:
    """Stop the background search service.

    Reads the status file from ``~/.vaultspec-rag/service.json``, verifies
    the PID is still alive and belongs to a vaultspec-rag process, requests
    termination, waits briefly, then removes the status file.

    Graceful shutdown reaches the daemon only on Unix, where ``SIGTERM`` is
    delivered cross-process and drives the daemon's own lifespan teardown
    (escalating to ``SIGKILL`` if the drain window expires). On Windows the
    daemon is spawned detached from any shell (its own or no console), so a
    separate stop process cannot deliver a console-scoped ``CTRL_BREAK_EVENT``
    to it - the attempt fails and the stop degrades to a ``TerminateProcess``
    force-kill. That force-kill is abrupt - the daemon runs none of its own
    teardown - but it is tolerated: the vector store recovers from an abrupt
    stop, and this stop process itself reaps the daemon's owned Qdrant child
    and clears its discovery pointer. It is not a graceful in-daemon shutdown,
    and the audit trail is the CLI-side mirror line rather than the daemon's
    own shutdown record.

    With ``--port`` the running instance on that port is targeted directly via
    its ``/health`` identity, so a non-default-port service whose status file is
    missing or divergent is still stoppable.

    Exit codes: 0 for every satisfied outcome (``stopped``, ``already_stopped``,
    ``cleaned``, ``reclaimed``, ``reaped``); 1 when the stop is skipped because a
    live
    recorded process could not be confirmed as ours - the one outcome that
    leaves a service running.
    """
    if orphans:
        target_port = _expected_singleton_port(port)
        if target_port is None:
            raise _fail_stop(
                json_mode,
                error="port_unresolved",
                message="Orphan reap needs a resolvable service port",
                human_lines=(
                    "Could not resolve the machine singleton's port; pass --port.",
                ),
            )
        _reap_orphan_daemons(target_port, json_mode)
        return

    if port is not None:
        _stop_service_on_port(port, json_mode)
        return

    status = _read_service_status()
    if status is None:
        # No service.json for this config. Before reporting "not running", fall
        # back to the machine-global singleton lock: a live holder is the
        # resident service even when it left no discovery file here, and
        # reclaiming it is the documented recovery for a wedged/undiscoverable
        # singleton that would otherwise deadlock `server start`.
        reclaimed = _reclaim_machine_singleton()
        if reclaimed is not None:
            _stop_success(
                json_mode,
                status="reclaimed",
                human_title="Service stopped",
                human_lines=(
                    f"Reclaimed the resident machine service (pid {reclaimed}); "
                    "it held the singleton lock without a discoverable status "
                    "file.",
                ),
                pid=reclaimed,
                **_initiator_fields(),
            )
            return
        # No reclaimable holder. We do NOT probe the port: on the shared default
        # port another project's healthy service would otherwise be misreported
        # as this config's orphan.
        _stop_success(
            json_mode,
            status="already_stopped",
            human_title="Service is not running.",
        )
        return

    pid = int(status["pid"])
    port = int(status["port"])
    raw_token = status.get("service_token")
    expected_token = raw_token if isinstance(raw_token, str) else None
    if not _cli._is_our_service(pid, port=port, expected_token=expected_token):
        # Identity not confirmed. Remove the discovery file only when the PID
        # is confirmed dead; an alive-but-unconfirmed PID (a transient
        # /health/identity miss) must not have its file erased, which would
        # both mis-report a live daemon as gone and break discovery (#204).
        if _should_unlink_discovery_file(_cli._is_pid_alive(pid)):
            _delete_service_status()
            _stop_success(
                json_mode,
                status="cleaned",
                human_title="Service status cleaned",
                human_lines=(f"Recorded process {pid} is no longer running.",),
                pid=pid,
            )
            return
        raise _fail_stop(
            json_mode,
            error="identity_unconfirmed",
            message="Service stop skipped",
            human_lines=(
                f"Recorded process {pid} is alive but its identity could not "
                "be confirmed; the discovery file was left in place.",
            ),
            next_actions=("vaultspec-rag server status --verbose",),
            pid=pid,
            port=port,
        )

    _terminate_and_confirm(pid)
    _delete_service_status()
    _stop_success(
        json_mode,
        status="stopped",
        human_title="Service stopped",
        human_lines=(_process_line(pid),),
        pid=pid,
        port=port,
        **_initiator_fields(),
    )
