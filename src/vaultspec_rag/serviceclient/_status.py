"""Canonical operator status composed from typed discovery and health signals.

The service domain owns operability, so the verdict an operator sees is derived
here once and rendered by the adapters (``server status``, ``server doctor``)
rather than recomputed per surface. Keeping the composition pure - the caller
supplies already-probed liveness signals - lets this module stay import-light
and free of any ``vaultspec_rag.cli`` dependency while still expressing the
whole contract.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ._discovery import (
    DISCOVERY_SOURCE_MACHINE_POINTER,
    DISCOVERY_STATE_ABSENT,
    DISCOVERY_STATE_DEGRADED,
    SERVICE_PHASE_WARMING,
    MachineResolution,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any, TypeGuard

#: Canonical operator states. ``running`` and ``warming`` are healthy live
#: states; ``stopped`` means nothing is running; ``crashed`` means a recorded
#: service is not serving; ``degraded`` means the machine singleton is held but
#: its owner has not published a trustworthy address. ``degraded`` is distinct
#: from both ``stopped`` and ``crashed``: something owns the singleton, so a
#: start would lose the race, and the daemon may well be serving fine.
STATUS_RUNNING = "running"
STATUS_WARMING = "warming"
STATUS_STOPPED = "stopped"
STATUS_CRASHED = "crashed"
STATUS_DEGRADED = "degraded_discovery"

#: Exit codes. These mirror the established broker-facing contract - 0 running,
#: 3 stopped, 4 a service that should be serving but is not, 5 warming - so a
#: degraded discovery verdict rides the existing 4 rather than introducing a
#: new code that every supervising broker would have to learn.
EXIT_RUNNING = 0
EXIT_STOPPED = 3
EXIT_FAULT = 4
EXIT_WARMING = 5

#: The sentences an operator reads for the conditions both the service verdict
#: and the CLI's own signal ladder can reach. The CLI derives a finer state
#: token than this module does - it distinguishes a dead pid from a reused one,
#: where the service reports ``crashed`` for both - but where the two describe
#: the same condition they must not describe it differently. Each of these was
#: spelled in both places, so the same daemon could be explained in two
#: wordings depending on which path an operator arrived through.
LABEL_WARMING = "warming (loading models, not yet serving)"
LABEL_CRASHED_PORT_SILENT = "crashed (port silent)"
LABEL_CRASHED_HEARTBEAT_STALE = "crashed (heartbeat stale)"

__all__ = [
    "EXIT_FAULT",
    "EXIT_RUNNING",
    "EXIT_STOPPED",
    "EXIT_WARMING",
    "LABEL_CRASHED_HEARTBEAT_STALE",
    "LABEL_CRASHED_PORT_SILENT",
    "LABEL_WARMING",
    "RECONCILE_ALREADY",
    "RECONCILE_CONVERGED",
    "RECONCILE_INTERVAL_SECONDS",
    "RECONCILE_TIMEOUT_SECONDS",
    "RECONCILE_UNRESOLVED",
    "STATUS_CRASHED",
    "STATUS_DEGRADED",
    "STATUS_RUNNING",
    "STATUS_STOPPED",
    "STATUS_WARMING",
    "DiscoveryStatus",
    "LivenessSignals",
    "ReconcileOutcome",
    "ReconcileRequest",
    "compose_discovery_status",
    "reconcile_discovery",
]


@dataclass(frozen=True, slots=True)
class LivenessSignals:
    """Already-probed liveness facts about a resolved service address.

    Supplied by the adapter because probing a PID and a port is platform work
    that belongs to the process layer; composing a verdict from those facts is
    service-domain work and belongs here.
    """

    pid: int = 0
    pid_alive: bool = False
    pid_matches_service: bool = False
    port_listening: bool = False
    heartbeat_age_s: float | None = None
    heartbeat_stale: bool = False
    service_token_match: bool | None = None
    phase: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryStatus:
    """One canonical operator verdict plus the evidence that produced it."""

    state: str
    label: str
    exit_code: int
    resolution: MachineResolution
    signals: LivenessSignals = field(default_factory=LivenessSignals)
    health: dict[str, object] | None = None

    @property
    def is_live(self) -> bool:
        """Whether a daemon is running, whether or not it is serving yet."""
        return self.state in {STATUS_RUNNING, STATUS_WARMING}

    @property
    def port(self) -> int | None:
        """The resolved address, when discovery produced one."""
        return self.resolution.port

    def as_dict(self) -> dict[str, Any]:
        """Render the JSON body shared by every operator adapter."""
        payload: dict[str, object] = {
            "state": self.state,
            "label": self.label,
            "discovery": {
                "state": self.resolution.state,
                "source": self.resolution.source,
                "holder_pid": self.resolution.holder_pid,
                "pointer_pid": self.resolution.pointer_pid,
                "port": self.resolution.port,
                "heartbeat_age_seconds": self.resolution.heartbeat_age_s,
                "stale_after_seconds": self.resolution.stale_after_s,
                "reason": self.resolution.reason,
                "evidence": self.resolution.evidence(),
            },
            "pid": self.signals.pid,
            "pid_alive": self.signals.pid_alive,
            "pid_matches_service": self.signals.pid_matches_service,
            "port_listening": self.signals.port_listening,
            "heartbeat_age_seconds": self.signals.heartbeat_age_s,
            "heartbeat_stale": self.signals.heartbeat_stale,
            "service_token_match": self.signals.service_token_match,
        }
        if self.health is not None:
            payload["health"] = self.health
        return payload


def _degraded_label(resolution: MachineResolution) -> str:
    """Explain a degraded verdict in operator language, not reason codes."""
    holder = resolution.holder_pid
    reasons = {
        "pointer_missing": (
            f"a service (PID {holder}) holds the machine singleton but has not "
            "published its address"
        ),
        "pointer_invalid": (
            f"a service (PID {holder}) holds the machine singleton but its "
            "published address is unreadable"
        ),
        "pointer_stale": (
            f"a service (PID {holder}) holds the machine singleton but its "
            "published address has stopped being refreshed"
        ),
        "pointer_foreign": (
            f"a service (PID {holder}) holds the machine singleton while the "
            f"published address still names PID {resolution.pointer_pid}"
        ),
        "probe_failed": "the machine singleton could not be inspected",
    }
    return reasons.get(
        resolution.reason or "",
        f"a service (PID {holder}) holds the machine singleton but its "
        "published address cannot be trusted",
    )


def compose_discovery_status(
    resolution: MachineResolution,
    signals: LivenessSignals | None = None,
    *,
    health: dict[str, object] | None = None,
) -> DiscoveryStatus:
    """Compose the canonical operator verdict for *resolution*.

    Degraded discovery is reported before any liveness reasoning: when the
    singleton owner has not published a trustworthy address there is no address
    worth probing, and rendering such a machine as stopped would invite an
    operator to start a daemon that can only lose the singleton race.
    """
    facts = signals or LivenessSignals()

    state, label, exit_code = _discovery_status_fields(resolution, facts)
    return DiscoveryStatus(
        state=state,
        label=label,
        exit_code=exit_code,
        resolution=resolution,
        signals=facts,
        health=health,
    )


def _discovery_status_fields(
    resolution: MachineResolution, facts: LivenessSignals
) -> tuple[str, str, int]:
    """Classify fixed resolution and liveness facts into one operator verdict."""
    if resolution.state == DISCOVERY_STATE_DEGRADED:
        return STATUS_DEGRADED, _degraded_label(resolution), EXIT_FAULT
    if resolution.state == DISCOVERY_STATE_ABSENT:
        return STATUS_STOPPED, "stopped (no service is running)", EXIT_STOPPED

    # Ready: an address resolved, so the liveness facts decide whether the
    # daemon behind it is actually serving.
    # A daemon that stamped ``warming`` holds the singleton and is loading
    # models: its silent port and unstarted heartbeat are expected, so this is
    # checked before either is treated as a fault.
    for failed, state, label, exit_code in (
        (
            not facts.pid_alive,
            STATUS_CRASHED,
            "crashed (recorded process is not running)",
            EXIT_FAULT,
        ),
        (
            not facts.pid_matches_service,
            STATUS_CRASHED,
            "crashed (PID reused by an unrelated process)",
            EXIT_FAULT,
        ),
        (
            facts.phase == SERVICE_PHASE_WARMING,
            STATUS_WARMING,
            LABEL_WARMING,
            EXIT_WARMING,
        ),
        (
            not facts.port_listening,
            STATUS_CRASHED,
            LABEL_CRASHED_PORT_SILENT,
            EXIT_FAULT,
        ),
        (
            facts.heartbeat_stale,
            STATUS_CRASHED,
            LABEL_CRASHED_HEARTBEAT_STALE,
            EXIT_FAULT,
        ),
    ):
        if failed:
            return state, label, exit_code

    source = (
        "" if resolution.source == DISCOVERY_SOURCE_MACHINE_POINTER else " (legacy)"
    )
    return STATUS_RUNNING, f"running{source}", EXIT_RUNNING


#: Reconcile outcomes. ``already_converged`` means discovery agreed on the
#: first look; ``converged`` means the owner's own heartbeat repaired it inside
#: the bound; ``unresolved`` means it did not, which is a report, never a
#: repair attempt of our own.
RECONCILE_ALREADY = "already_converged"
RECONCILE_CONVERGED = "converged"
RECONCILE_UNRESOLVED = "unresolved"

#: Bounded by default so an operator command cannot hang on a daemon that will
#: never converge. One heartbeat interval is 15s, so the default spans two.
RECONCILE_TIMEOUT_SECONDS = 35.0
RECONCILE_INTERVAL_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class ReconcileOutcome:
    """The result of waiting for owner-published discovery to converge."""

    status: str
    attempts: int
    elapsed_s: float
    final: DiscoveryStatus
    detail: str

    @property
    def converged(self) -> bool:
        """Whether discovery ended in an agreeing, identity-confirmed state."""
        return self.status in {RECONCILE_ALREADY, RECONCILE_CONVERGED}

    def as_dict(self) -> dict[str, Any]:
        """Render the structured outcome an operator adapter emits."""
        return {
            "status": self.status,
            "converged": self.converged,
            "attempts": self.attempts,
            "elapsed_seconds": round(self.elapsed_s, 3),
            "detail": self.detail,
            "service": self.final.as_dict(),
        }


def _ignore_attempt(_attempt: int, _verdict: DiscoveryStatus) -> None:
    """Drop a poll observation, for callers that want no reporting."""


@dataclass(frozen=True, slots=True)
class ReconcileRequest:
    """Dependencies and timing controls for one bounded discovery reconcile."""

    resolve: Callable[[], MachineResolution]
    probe_liveness: Callable[[MachineResolution], LivenessSignals]
    probe_health: Callable[[int], dict[str, Any] | None]
    timeout_s: float = RECONCILE_TIMEOUT_SECONDS
    interval_s: float = RECONCILE_INTERVAL_SECONDS
    sleep: Callable[[float], None] | None = None
    monotonic: Callable[[], float] | None = None
    on_attempt: Callable[[int, DiscoveryStatus], None] = _ignore_attempt


def _is_finite_number(value: object) -> TypeGuard[float]:
    """Whether *value* is a concrete, non-boolean, finite real number."""
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _pointer_identity_matches(resolution: MachineResolution) -> bool:
    """The pointer advertises one live machine-pointer owner with a token.

    Source is the machine pointer, the holder and pointer pids are the same
    concrete process, and a non-empty identity token was published.
    """
    token = resolution.service_token
    return (
        resolution.source == DISCOVERY_SOURCE_MACHINE_POINTER
        and _is_positive_pid(resolution.holder_pid)
        and _is_positive_pid(resolution.pointer_pid)
        and resolution.pointer_pid == resolution.holder_pid
        and isinstance(token, str)
        and bool(token)
    )


def _heartbeat_within_stale_window(resolution: MachineResolution) -> bool:
    """The heartbeat age and stale window are finite and the age is within it."""
    heartbeat_age = resolution.heartbeat_age_s
    stale_after = resolution.stale_after_s
    if not _is_finite_number(heartbeat_age):
        return False
    if not _is_finite_number(stale_after):
        return False
    return stale_after > 0 and heartbeat_age <= stale_after


def _signals_confirm_pointer(
    signals: LivenessSignals, resolution: MachineResolution
) -> bool:
    """The live-probe signals all agree with the pointer's advertised identity."""
    return (
        signals.pid == resolution.pointer_pid
        and signals.pid_alive
        and signals.pid_matches_service
        and signals.port_listening
        and signals.service_token_match is True
    )


def _health_matches_pointer(
    health: dict[str, object], resolution: MachineResolution
) -> bool:
    """The live ``/health`` response's pid and token match the pointer's."""
    served_token = health.get("service_token")
    served_pid = health.get("pid")
    return (
        _is_positive_pid(served_pid)
        and served_pid == resolution.pointer_pid
        and isinstance(served_token, str)
        and bool(served_token)
        and served_token == resolution.service_token
    )


def _identity_confirmed(
    verdict: DiscoveryStatus, health: dict[str, object] | None
) -> bool:
    """Whether the serving daemon is the one the pointer advertises.

    Convergence requires agreement across every axis the pointer claims, not
    merely a reachable port: a live service answering on the advertised address
    is only the *right* service when its own identity token and process match
    what the owner published. Each axis is checked by a cohesive predicate; all
    must hold.
    """
    if health is None:
        return False
    resolution = verdict.resolution
    return (
        _pointer_identity_matches(resolution)
        and _heartbeat_within_stale_window(resolution)
        and _signals_confirm_pointer(verdict.signals, resolution)
        and _health_matches_pointer(health, resolution)
    )


def _is_positive_pid(value: object) -> bool:
    """Return whether *value* is a concrete, non-boolean process identity."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def reconcile_discovery(request: ReconcileRequest) -> ReconcileOutcome:
    """Wait boundedly for the owner's own heartbeat to republish discovery.

    Deliberately non-destructive: the singleton owner is the only process that
    may publish or delete its pointer, so the only correct repair is the
    owner's next heartbeat. This polls for that convergence and reports what it
    saw; it never writes, deletes, restarts, or terminates anything, which is
    what makes it safe to run against a healthy machine.

    ``on_attempt`` observes each non-terminal poll - the attempt number and the
    verdict that did not yet converge - just before the wait. It exists so an
    adapter can keep an operator informed across a wait measured in tens of
    seconds; it cannot influence the outcome, and the loop is identical without
    it.
    """
    import time as _time

    clock = request.monotonic or _time.monotonic
    wait = request.sleep or _time.sleep

    started = clock()
    deadline = started + max(0.0, request.timeout_s)
    attempts = 0
    verdict: DiscoveryStatus | None = None

    while True:
        attempts += 1
        resolution = request.resolve()
        signals = request.probe_liveness(resolution)
        health = (
            request.probe_health(resolution.port)
            if resolution.port is not None and signals.port_listening
            else None
        )
        verdict = compose_discovery_status(resolution, signals, health=health)

        if verdict.state == STATUS_RUNNING and _identity_confirmed(verdict, health):
            status = RECONCILE_ALREADY if attempts == 1 else RECONCILE_CONVERGED
            return ReconcileOutcome(
                status=status,
                attempts=attempts,
                elapsed_s=clock() - started,
                final=verdict,
                detail=verdict.label,
            )
        # Nothing holds the singleton: there is no owner to wait for, so
        # further polling cannot change the answer.
        if verdict.state == STATUS_STOPPED:
            return ReconcileOutcome(
                status=RECONCILE_UNRESOLVED,
                attempts=attempts,
                elapsed_s=clock() - started,
                final=verdict,
                detail="no service holds the machine singleton",
            )
        if clock() >= deadline:
            return ReconcileOutcome(
                status=RECONCILE_UNRESOLVED,
                attempts=attempts,
                elapsed_s=clock() - started,
                final=verdict,
                detail=(
                    f"{verdict.label}; discovery did not converge within "
                    f"{request.timeout_s:g}s"
                ),
            )
        request.on_attempt(attempts, verdict)
        wait(min(request.interval_s, max(0.0, deadline - clock())))
