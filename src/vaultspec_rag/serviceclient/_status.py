"""Canonical operator status composed from typed discovery and health signals.

The service domain owns operability, so the verdict an operator sees is derived
here once and rendered by the adapters (``server status``, ``server doctor``)
rather than recomputed per surface. Keeping the composition pure - the caller
supplies already-probed liveness signals - lets this module stay import-light
and free of any ``vaultspec_rag.cli`` dependency while still expressing the
whole contract.
"""

from __future__ import annotations

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
    from typing import Any

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

__all__ = [
    "EXIT_FAULT",
    "EXIT_RUNNING",
    "EXIT_STOPPED",
    "EXIT_WARMING",
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
    health: dict[str, Any] | None = None

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
        payload: dict[str, Any] = {
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
    health: dict[str, Any] | None = None,
) -> DiscoveryStatus:
    """Compose the canonical operator verdict for *resolution*.

    Degraded discovery is reported before any liveness reasoning: when the
    singleton owner has not published a trustworthy address there is no address
    worth probing, and rendering such a machine as stopped would invite an
    operator to start a daemon that can only lose the singleton race.
    """
    facts = signals or LivenessSignals()

    if resolution.state == DISCOVERY_STATE_DEGRADED:
        return DiscoveryStatus(
            state=STATUS_DEGRADED,
            label=_degraded_label(resolution),
            exit_code=EXIT_FAULT,
            resolution=resolution,
            signals=facts,
            health=health,
        )

    if resolution.state == DISCOVERY_STATE_ABSENT:
        return DiscoveryStatus(
            state=STATUS_STOPPED,
            label="stopped (no service is running)",
            exit_code=EXIT_STOPPED,
            resolution=resolution,
            signals=facts,
            health=health,
        )

    # Ready: an address resolved, so the liveness facts decide whether the
    # daemon behind it is actually serving.
    if not facts.pid_alive:
        return DiscoveryStatus(
            state=STATUS_CRASHED,
            label="crashed (recorded process is not running)",
            exit_code=EXIT_FAULT,
            resolution=resolution,
            signals=facts,
            health=health,
        )
    if not facts.pid_matches_service:
        return DiscoveryStatus(
            state=STATUS_CRASHED,
            label="crashed (PID reused by an unrelated process)",
            exit_code=EXIT_FAULT,
            resolution=resolution,
            signals=facts,
            health=health,
        )
    # A daemon that stamped ``warming`` holds the singleton and is loading
    # models: its silent port and unstarted heartbeat are expected, so this is
    # checked before either is treated as a fault.
    if facts.phase == SERVICE_PHASE_WARMING:
        return DiscoveryStatus(
            state=STATUS_WARMING,
            label="warming (loading models, not yet serving)",
            exit_code=EXIT_WARMING,
            resolution=resolution,
            signals=facts,
            health=health,
        )
    if not facts.port_listening:
        return DiscoveryStatus(
            state=STATUS_CRASHED,
            label="crashed (port silent)",
            exit_code=EXIT_FAULT,
            resolution=resolution,
            signals=facts,
            health=health,
        )
    if facts.heartbeat_stale:
        return DiscoveryStatus(
            state=STATUS_CRASHED,
            label="crashed (heartbeat stale)",
            exit_code=EXIT_FAULT,
            resolution=resolution,
            signals=facts,
            health=health,
        )

    source = (
        "" if resolution.source == DISCOVERY_SOURCE_MACHINE_POINTER else " (legacy)"
    )
    return DiscoveryStatus(
        state=STATUS_RUNNING,
        label=f"running{source}",
        exit_code=EXIT_RUNNING,
        resolution=resolution,
        signals=facts,
        health=health,
    )


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


def _identity_confirmed(
    verdict: DiscoveryStatus, health: dict[str, Any] | None
) -> bool:
    """Whether the serving daemon is the one the pointer advertises.

    Convergence requires agreement across every axis the pointer claims, not
    merely a reachable port: a live service answering on the advertised address
    is only the *right* service when its own identity token and process match
    what the owner published.
    """
    if health is None:
        return False
    served_token = health.get("service_token")
    expected = verdict.resolution.service_token
    token_claimed = isinstance(expected, str) and bool(expected)
    if token_claimed and (
        not isinstance(served_token, str) or served_token != expected
    ):
        return False
    served_pid = health.get("pid")
    pointer_pid = verdict.resolution.pointer_pid
    pid_comparable = (
        isinstance(served_pid, int)
        and not isinstance(served_pid, bool)
        and pointer_pid is not None
    )
    return not (pid_comparable and served_pid != pointer_pid)


def reconcile_discovery(
    resolve: Callable[[], MachineResolution],
    probe_liveness: Callable[[MachineResolution], LivenessSignals],
    probe_health: Callable[[int], dict[str, Any] | None],
    *,
    timeout_s: float = RECONCILE_TIMEOUT_SECONDS,
    interval_s: float = RECONCILE_INTERVAL_SECONDS,
    sleep: Callable[[float], None] | None = None,
    monotonic: Callable[[], float] | None = None,
) -> ReconcileOutcome:
    """Wait boundedly for the owner's own heartbeat to republish discovery.

    Deliberately non-destructive: the singleton owner is the only process that
    may publish or delete its pointer, so the only correct repair is the
    owner's next heartbeat. This polls for that convergence and reports what it
    saw; it never writes, deletes, restarts, or terminates anything, which is
    what makes it safe to run against a healthy machine.
    """
    import time as _time

    clock = monotonic or _time.monotonic
    wait = sleep or _time.sleep

    started = clock()
    deadline = started + max(0.0, timeout_s)
    attempts = 0
    verdict: DiscoveryStatus | None = None

    while True:
        attempts += 1
        resolution = resolve()
        signals = probe_liveness(resolution)
        health = (
            probe_health(resolution.port)
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
                    f"{verdict.label}; discovery did not converge within {timeout_s:g}s"
                ),
            )
        wait(min(interval_s, max(0.0, deadline - clock())))
