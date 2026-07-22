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
    "STATUS_CRASHED",
    "STATUS_DEGRADED",
    "STATUS_RUNNING",
    "STATUS_STOPPED",
    "STATUS_WARMING",
    "DiscoveryStatus",
    "LivenessSignals",
    "compose_discovery_status",
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
