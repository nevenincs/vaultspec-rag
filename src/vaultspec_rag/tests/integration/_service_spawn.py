"""Start the real service on a port it is still able to bind.

A port picked with ``free_loopback_port`` is released before the service is
spawned, and the service does not bind it until its models are loaded - tens of
seconds later. On a machine shared with other processes, containers and
dynamic port reservations, something else takes the port in that window. The
service then logs uvicorn's bind failure and exits, and a test that waits on
health sits out its whole budget for a service that will never answer.

That failure is recognisable: uvicorn names the port it could not bind in the
service's own output. :func:`start_service_on_free_port` reads that output while
it waits for readiness, and on seeing it starts again on a fresh port. It
retries that one condition only - a service that fails for any other reason
fails the caller exactly as it would without the helper, so a real startup
defect is never masked by a second attempt.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...cli._process import _terminate_pid
from ...cli._service_status import _write_service_status
from .._ports import free_loopback_port
from .._session_job_anchor import spawn_anchored_service
from ._helpers import _poll_health, _wait_for_exit

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = [
    "ServicePortLostError",
    "SpawnLogMark",
    "SpawnedService",
    "publish_status_then_await_health",
    "start_service_on_free_port",
]

#: Attempts at one service start before the lost port is reported as the failure.
_PORT_ATTEMPTS = 3

#: The wait for readiness, which is the budget the callers of a bare health poll
#: already had.
_READY_TIMEOUT_SECONDS = 90.0

#: How long a failed attempt's launcher gets to exit before it is reported.
_ATTEMPT_EXIT_SECONDS = 15.0

#: What asyncio raises, and uvicorn logs, when the listening socket cannot be
#: bound: the sockaddr tuple follows, ``('127.0.0.1', 62825)`` for IPv4.
_BIND_FAILURE = "error while attempting to bind on address"


class ServicePortLostError(RuntimeError):
    """The service could not bind the port it was started on."""


@dataclass(frozen=True, slots=True)
class SpawnLogMark:
    """The point in a service log where one spawn's own output begins.

    A log file is reused by every spawn that names it, so what an earlier
    service wrote there says nothing about the one just started. Reading only
    past the recorded offset is what keeps a previous attempt's bind failure
    from condemning the next one.
    """

    path: Path
    offset: int

    @classmethod
    def at_end(cls, path: Path) -> SpawnLogMark:
        """Mark the current end of *path*, or its start when it does not exist."""
        try:
            return cls(path, path.stat().st_size)
        except FileNotFoundError:
            return cls(path, 0)

    def shows_port_lost(self, port: int) -> bool:
        """Whether this spawn's output reports a failed bind of *port*."""
        try:
            with self.path.open("rb") as stream:
                size = stream.seek(0, 2)
                # A log that shrank below the mark was rotated; everything in
                # it is newer than the spawn.
                stream.seek(self.offset if size >= self.offset else 0)
                written = stream.read().decode("utf-8", errors="replace")
        except FileNotFoundError:
            return False
        pattern = rf"{re.escape(_BIND_FAILURE)} \('[^']*', {port}[,)]"
        return re.search(pattern, written) is not None

    def raise_if_port_lost(self, port: int) -> None:
        """Raise :class:`ServicePortLostError` when *port* failed to bind."""
        if self.shows_port_lost(port):
            msg = (
                f"service could not bind port {port}: something else took it "
                f"after it was picked (see {self.path})"
            )
            raise ServicePortLostError(msg)


@dataclass(frozen=True, slots=True)
class SpawnedService:
    """One spawn of the service: its launcher, its port, and its own log output."""

    pid: int
    port: int
    log: SpawnLogMark


def _await_health(service: SpawnedService, remaining: float) -> None:
    _poll_health(service.port, timeout=remaining, spawn_log=service.log)


def publish_status_then_await_health(service: SpawnedService, remaining: float) -> None:
    """Record the spawn in the status file, as a start verb does, then await health.

    The service's own first heartbeat finds the file this writes only if it
    exists before the models finish loading, so the order is part of what a
    caller using this is exercising.
    """
    _write_service_status(service.pid, service.port)
    _await_health(service, remaining)


def _terminate_and_reap(service: SpawnedService) -> None:
    _terminate_pid(service.pid)
    if not _wait_for_exit(service.pid, timeout=_ATTEMPT_EXIT_SECONDS):
        msg = (
            f"service launcher {service.pid} on port {service.port} did not "
            f"exit within {_ATTEMPT_EXIT_SECONDS:.0f}s of being terminated"
        )
        raise AssertionError(msg)


def start_service_on_free_port(
    log_path: Path,
    *,
    spawn: Callable[[int, Path], int] = spawn_anchored_service,
    ready: Callable[[SpawnedService, float], None] = _await_health,
    cleanup: Callable[[SpawnedService], None] = _terminate_and_reap,
    timeout: float = _READY_TIMEOUT_SECONDS,
) -> SpawnedService:
    """Pick a port, spawn the service on it, and wait until it is ready.

    Returns the ready service; the caller owns stopping it. When the service
    reports that its port was taken before it could bind, that attempt is
    cleaned up and another is made on a fresh port, up to three times and while
    *timeout* seconds, counted from the first spawn, remain. Any other failure
    from *spawn* or *ready* cleans up the attempt and propagates unchanged.

    *spawn* starts the service on a port, writing to the log it is given, and
    returns the launcher pid. *ready* waits for readiness within the seconds it
    is given and must read the service's output through ``service.log`` so a
    lost port surfaces as :class:`ServicePortLostError`. *cleanup* must leave
    the attempt's processes gone: the next attempt starts a service that cannot
    claim the machine while the last still holds it.
    """
    deadline = time.monotonic() + timeout
    ports: list[int] = []
    last_lost: ServicePortLostError | None = None
    while len(ports) < _PORT_ATTEMPTS and (
        last_lost is None or time.monotonic() < deadline
    ):
        port = free_loopback_port()
        ports.append(port)
        log = SpawnLogMark.at_end(log_path)
        service = SpawnedService(spawn(port, log_path), port, log)
        try:
            ready(service, max(0.0, deadline - time.monotonic()))
        except ServicePortLostError as lost:
            cleanup(service)
            last_lost = lost
            continue
        except BaseException:
            cleanup(service)
            raise
        return service
    msg = (
        f"service lost its port before binding it on all {len(ports)} attempts "
        f"it was given (ports {ports}); the last report was: {last_lost}"
    )
    raise ServicePortLostError(msg) from last_lost
