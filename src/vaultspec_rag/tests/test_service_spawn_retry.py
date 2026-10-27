"""A service that loses its port before it binds is started again, and only then.

``start_service_on_free_port`` recognises the one failure a retry can cure - the
port picked for the service was taken before the service bound it - from the
service's own log, and starts again on a fresh port. These tests run that
against real processes: a real uvicorn server that binds late, as the service
does after loading its models, and a real listening socket held on the port the
first attempt was given so the bind genuinely fails.

Mutations the tests below catch, each tried and each failing at the test it
names, then restored:

- reading the whole log instead of only what follows the mark fails
  ``test_a_bind_failure_before_the_mark_belongs_to_an_earlier_spawn``;
- retrying on any failure instead of the lost port fails
  ``test_a_service_that_fails_for_another_reason_is_not_started_again``;
- dropping the port from the match fails
  ``test_a_bind_failure_on_another_port_is_not_this_spawns_loss``.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from contextlib import suppress
from typing import TYPE_CHECKING

import psutil
import pytest

from ._ports import free_loopback_port
from .integration._helpers import _poll_health
from .integration._service_spawn import (
    ServicePortLostError,
    SpawnedService,
    SpawnLogMark,
    start_service_on_free_port,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

pytestmark = pytest.mark.unit

#: What uvicorn logs when it cannot bind, as it reads on each platform.
_POSIX_BIND_FAILURE = (
    "ERROR:    [Errno 98] error while attempting to bind on address "
    "('127.0.0.1', {port}): address already in use\n"
)
_WINDOWS_BIND_FAILURE = (
    "ERROR uvicorn.error: [Errno 13] error while attempting to bind on address "
    "('127.0.0.1', {port}): [winerror 10013] an attempt was made to access a "
    "socket in a way forbidden by its access permissions\n"
)

#: A real uvicorn server that waits before it binds, as the service does while
#: its models load, and answers health with the readiness the service reports.
_LATE_BINDING_SERVER = """
import sys
import time

import uvicorn


async def app(scope, receive, send):
    body = b'{"status": "ready"}'
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"application/json")],
    })
    await send({"type": "http.response.body", "body": body})


time.sleep(0.5)
uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), lifespan="off")
"""

#: A process that fails for a reason that has nothing to do with its port.
_FAILING_SERVER = """
import sys

print("startup failed: models could not be loaded", flush=True)
sys.exit(3)
"""


def _kill_tree(pid: int) -> None:
    """Kill *pid* and everything it started; a venv launcher starts the server."""
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    doomed = [parent, *parent.children(recursive=True)]
    for process in doomed:
        with suppress(psutil.NoSuchProcess):
            process.kill()
    psutil.wait_procs(doomed, timeout=15.0)


class _Spawner:
    """Starts real child processes on the port asked for, holding some of them.

    The first ``hold`` ports it is asked for get a real listening socket before
    the child starts, so the child's bind fails for the reason a taken port
    fails it.
    """

    def __init__(self, script: str, *, hold: int = 0) -> None:
        self.script = script
        self.hold = hold
        self.ports: list[int] = []
        self.cleaned: list[int] = []
        self._held: list[socket.socket] = []
        self._launched: list[subprocess.Popen[bytes]] = []

    def spawn(self, port: int, log_path: Path) -> int:
        self.ports.append(port)
        if len(self.ports) <= self.hold:
            holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            holder.bind(("127.0.0.1", port))
            holder.listen()
            self._held.append(holder)
        with log_path.open("ab") as output:
            process = subprocess.Popen(
                [sys.executable, "-c", self.script, str(port)],
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        self._launched.append(process)
        return process.pid

    def clean_up_attempt(self, service: SpawnedService) -> None:
        self.cleaned.append(service.port)
        _kill_tree(service.pid)

    def release(self) -> None:
        for process in self._launched:
            _kill_tree(process.pid)
            process.wait(timeout=15.0)
        for holder in self._held:
            holder.close()


@pytest.fixture
def make_spawner() -> Generator[Callable[..., _Spawner]]:
    created: list[_Spawner] = []

    def make(script: str, *, hold: int = 0) -> _Spawner:
        spawner = _Spawner(script, hold=hold)
        created.append(spawner)
        return spawner

    try:
        yield make
    finally:
        for spawner in created:
            spawner.release()


@pytest.mark.parametrize(
    "bind_failure",
    [_POSIX_BIND_FAILURE, _WINDOWS_BIND_FAILURE],
    ids=["posix", "windows"],
)
def test_the_uvicorn_bind_failure_is_a_lost_port(
    tmp_path: Path, bind_failure: str
) -> None:
    log_path = tmp_path / "service.log"
    log_path.write_text("Loading models\n", encoding="utf-8")
    mark = SpawnLogMark.at_end(log_path)
    assert not mark.shows_port_lost(62825), "a log with no failure reported a loss"

    with log_path.open("a", encoding="utf-8") as log:
        log.write("EmbeddingModel loaded\n")
        log.write(bind_failure.format(port=62825))
    assert mark.shows_port_lost(62825)
    with pytest.raises(ServicePortLostError, match="62825"):
        mark.raise_if_port_lost(62825)


def test_a_bind_failure_before_the_mark_belongs_to_an_earlier_spawn(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "service.log"
    log_path.write_text(_POSIX_BIND_FAILURE.format(port=62825), encoding="utf-8")

    mark = SpawnLogMark.at_end(log_path)

    assert not mark.shows_port_lost(62825), (
        "a bind failure written before this spawn condemned the spawn"
    )
    mark.raise_if_port_lost(62825)


def test_a_bind_failure_on_another_port_is_not_this_spawns_loss(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "service.log"
    mark = SpawnLogMark.at_end(log_path)
    log_path.write_text(_POSIX_BIND_FAILURE.format(port=62826), encoding="utf-8")

    assert not mark.shows_port_lost(62825), (
        "a bind failure on a different port reported this port lost"
    )
    assert mark.shows_port_lost(62826)


def test_a_log_that_does_not_exist_yet_is_marked_at_its_start(tmp_path: Path) -> None:
    log_path = tmp_path / "service.log"

    mark = SpawnLogMark.at_end(log_path)
    assert not mark.shows_port_lost(62825)

    log_path.write_text(_POSIX_BIND_FAILURE.format(port=62825), encoding="utf-8")
    assert mark.shows_port_lost(62825)


def test_a_rotated_log_is_read_from_its_start(tmp_path: Path) -> None:
    log_path = tmp_path / "service.log"
    log_path.write_text("x" * 4096, encoding="utf-8")
    mark = SpawnLogMark.at_end(log_path)

    # The active file was replaced by a shorter one: everything in it is newer
    # than the mark.
    log_path.write_text(_POSIX_BIND_FAILURE.format(port=62825), encoding="utf-8")

    assert mark.shows_port_lost(62825)


def test_health_polling_reports_a_lost_port_without_waiting_out_its_timeout(
    tmp_path: Path,
) -> None:
    port = free_loopback_port()
    log_path = tmp_path / "service.log"
    mark = SpawnLogMark.at_end(log_path)
    log_path.write_text(_POSIX_BIND_FAILURE.format(port=port), encoding="utf-8")

    started = time.monotonic()
    with pytest.raises(ServicePortLostError):
        _poll_health(port, timeout=60.0, spawn_log=mark)

    assert time.monotonic() - started < 5.0


def test_health_polling_ignores_a_bind_failure_from_before_the_spawn(
    tmp_path: Path,
) -> None:
    port = free_loopback_port()
    log_path = tmp_path / "service.log"
    log_path.write_text(_POSIX_BIND_FAILURE.format(port=port), encoding="utf-8")
    mark = SpawnLogMark.at_end(log_path)

    with pytest.raises(TimeoutError, match="not ready"):
        _poll_health(port, timeout=0.3, spawn_log=mark)


def test_a_lost_port_is_retried_on_a_fresh_port(
    tmp_path: Path, make_spawner: Callable[..., _Spawner]
) -> None:
    log_path = tmp_path / "service.log"
    spawner = make_spawner(_LATE_BINDING_SERVER, hold=1)

    service = start_service_on_free_port(
        log_path,
        spawn=spawner.spawn,
        cleanup=spawner.clean_up_attempt,
        timeout=60.0,
    )

    assert len(spawner.ports) == 2, f"expected one retry, spawned on {spawner.ports}"
    first_port, second_port = spawner.ports
    assert first_port != second_port
    assert service.port == second_port
    assert spawner.cleaned == [first_port], (
        "only the attempt that lost its port is cleaned up; the ready one is "
        "handed to the caller"
    )
    assert _poll_health(service.port, timeout=5.0)["status"] == "ready"
    log = log_path.read_text(encoding="utf-8", errors="replace")
    assert log.count("error while attempting to bind on address") == 1, log


def test_every_attempt_losing_its_port_fails_as_a_lost_port(
    tmp_path: Path, make_spawner: Callable[..., _Spawner]
) -> None:
    log_path = tmp_path / "service.log"
    spawner = make_spawner(_LATE_BINDING_SERVER, hold=3)

    with pytest.raises(ServicePortLostError, match="all 3 attempts"):
        start_service_on_free_port(
            log_path,
            spawn=spawner.spawn,
            cleanup=spawner.clean_up_attempt,
            timeout=60.0,
        )

    assert len(spawner.ports) == 3
    assert spawner.cleaned == spawner.ports, "a failed attempt was left running"


def test_a_service_that_fails_for_another_reason_is_not_started_again(
    tmp_path: Path, make_spawner: Callable[..., _Spawner]
) -> None:
    log_path = tmp_path / "service.log"
    spawner = make_spawner(_FAILING_SERVER)

    with pytest.raises(TimeoutError, match="not ready"):
        start_service_on_free_port(
            log_path,
            spawn=spawner.spawn,
            cleanup=spawner.clean_up_attempt,
            timeout=2.0,
        )

    assert len(spawner.ports) == 1, (
        f"a failure that is not a lost port was retried: {spawner.ports}"
    )
    assert spawner.cleaned == spawner.ports
