"""The service's lifecycle, its health verdict, and why it is degraded.

Lifecycle is what the machine shows from outside the process: discovery, the
recorded PID, the port and the heartbeat. Health is what a live service says
about itself. They are separate because a stopped or crashed service cannot
describe itself, and a paused one is alive but deliberately not serving.
"""

from __future__ import annotations

from enum import StrEnum

from .._operator_commands import server_doctor_command, server_start_command

__all__ = [
    "EXIT_FAULT",
    "EXIT_RUNNING",
    "EXIT_STARTING",
    "EXIT_STOPPED",
    "DegradationReason",
    "HealthVerdict",
    "ServiceLifecycle",
]

#: Broker-facing exit codes: 0 running, 3 stopped, 4 a service that should be
#: serving but is not, 5 starting. Supervisors already key on these, so every
#: lifecycle member maps onto one of them rather than minting a code each
#: broker would have to learn.
EXIT_RUNNING = 0
EXIT_STOPPED = 3
EXIT_FAULT = 4
EXIT_STARTING = 5


class ServiceLifecycle(StrEnum):
    """Where the service process is, as observed from outside it.

    ``STARTING`` is the startup model load. Resuming after a pause is a
    quiesce state of a running service and is never labelled as starting.
    """

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    CRASHED_PID_DEAD = "crashed_pid_dead"
    CRASHED_PID_REUSED = "crashed_pid_reused"
    CRASHED_PORT_SILENT = "crashed_port_silent"
    CRASHED_HEARTBEAT_STALE = "crashed_heartbeat_stale"
    NOT_SERVING = "not_serving"
    DISCOVERY_DEGRADED = "discovery_degraded"

    @property
    def label(self) -> str:
        """Plain-language statement of where the service is."""
        return {
            ServiceLifecycle.STOPPED: "stopped",
            ServiceLifecycle.STARTING: "starting (loading models, not yet serving)",
            ServiceLifecycle.RUNNING: "running",
            ServiceLifecycle.CRASHED_PID_DEAD: (
                "crashed (its process is no longer running)"
            ),
            ServiceLifecycle.CRASHED_PID_REUSED: (
                "crashed (its process ID now belongs to another program)"
            ),
            ServiceLifecycle.CRASHED_PORT_SILENT: (
                "crashed (its port gives no usable answer)"
            ),
            ServiceLifecycle.CRASHED_HEARTBEAT_STALE: (
                "crashed (it stopped reporting that it is alive)"
            ),
            ServiceLifecycle.NOT_SERVING: (
                "running but unable to serve (its search models never loaded)"
            ),
            ServiceLifecycle.DISCOVERY_DEGRADED: (
                "unreachable (a service holds this machine but its address "
                "cannot be trusted)"
            ),
        }[self]

    @property
    def exit_code(self) -> int:
        """The broker-facing exit code for this lifecycle."""
        if self is ServiceLifecycle.RUNNING:
            return EXIT_RUNNING
        if self is ServiceLifecycle.STOPPED:
            return EXIT_STOPPED
        if self is ServiceLifecycle.STARTING:
            return EXIT_STARTING
        return EXIT_FAULT

    @property
    def is_live(self) -> bool:
        """Whether a service process is up, serving or not yet."""
        return self in {ServiceLifecycle.RUNNING, ServiceLifecycle.STARTING}

    @property
    def remediation(self) -> str | None:
        """What the operator should do, or ``None`` when nothing is needed."""
        if self.is_live:
            return None
        if self is ServiceLifecycle.DISCOVERY_DEGRADED:
            return f"Run `{server_doctor_command()}` to see what holds this machine."
        if self is ServiceLifecycle.NOT_SERVING:
            return (
                f"Run `{server_doctor_command()}` to see why the models did not "
                f"load, then restart it with `{server_start_command()}`."
            )
        return f"Start it with `{server_start_command()}`."


class HealthVerdict(StrEnum):
    """What a live service says about its ability to serve."""

    READY = "ready"
    PAUSED = "paused"
    DEGRADED = "degraded"
    ERROR = "error"

    @property
    def label(self) -> str:
        """Plain-language statement of the service's health."""
        return {
            HealthVerdict.READY: "ready for searches",
            HealthVerdict.PAUSED: "paused (holding no GPU memory, not serving)",
            HealthVerdict.DEGRADED: "serving with problems",
            HealthVerdict.ERROR: "not able to serve",
        }[self]

    @property
    def is_serving(self) -> bool:
        """Whether searches are answered, possibly with reduced quality."""
        return self in {HealthVerdict.READY, HealthVerdict.DEGRADED}


class DegradationReason(StrEnum):
    """Why a live service is not fully healthy.

    The service emits the code with its detail; renderers key on the code and
    never parse the detail.
    """

    MODELS_NOT_LOADED = "models_not_loaded"
    VECTOR_SERVICE_UNAVAILABLE = "vector_service_unavailable"
    NONCONFORMING = "nonconforming"
    QUARANTINED = "quarantined"
    STORE_CARRIED_ACROSS = "store_carried_across"
    JOBS_STALLED = "jobs_stalled"
    JOBS_DEGRADED = "jobs_degraded"
    JOB_FAILED = "job_failed"

    @property
    def label(self) -> str:
        """Plain-language statement of the problem."""
        return {
            DegradationReason.MODELS_NOT_LOADED: "the search models are not loaded",
            DegradationReason.VECTOR_SERVICE_UNAVAILABLE: (
                "the vector database is not running"
            ),
            DegradationReason.NONCONFORMING: (
                "some indexes were built with a different embedding model"
            ),
            DegradationReason.QUARANTINED: (
                "some indexes failed to load and were set aside"
            ),
            DegradationReason.STORE_CARRIED_ACROSS: (
                "the vector database was upgraded and older versions can no "
                "longer read it"
            ),
            DegradationReason.JOBS_STALLED: "indexing jobs are stalled",
            DegradationReason.JOBS_DEGRADED: "indexing jobs are degraded",
            DegradationReason.JOB_FAILED: "the latest indexing job failed",
        }[self]
