"""A stop ends the server, whichever process of the child's tree it is.

The supervisor runs whatever file the binary settings name. The pinned
release is one process; an operator's binary may be a launcher whose real
server is a process it starts. A stop that ends the launcher alone leaves
that server holding the port and the store while every surface says the
service stopped.

Every case hands a real supervisor a real launcher and a real worker, and
asks the operating system afterwards whether the worker is still there. The
worker does not watch its ancestors, so nothing but the stop can end it; it
sleeps between checks and ends on its own after two minutes, so a regressed
run leaves nothing behind for long.
"""

from __future__ import annotations

import contextlib
import time
from typing import TYPE_CHECKING

import psutil
import pytest

from ..qdrant_runtime._supervise import QdrantSupervisor
from ._fake_qdrant_binary import fake_qdrant_binary, unpinned
from ._ports import free_loopback_port

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

#: Records its pid, then waits. It ends only when it is ended, or after two
#: minutes on its own.
_WORKER = """
import os
import pathlib
import signal
import time

if {ignore_requests}:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
pathlib.Path({pidfile!r}).write_text(str(os.getpid()), encoding="utf-8")
print("serving", flush=True)
deadline = time.monotonic() + 120.0
while time.monotonic() < deadline:
    time.sleep(0.1)
"""


def _supervisor_of(
    tmp_path: Path, *, launcher_exits_first: bool, ignore_requests: bool = False
) -> tuple[QdrantSupervisor, Path]:
    pidfile = tmp_path / "worker.pid"
    launcher = fake_qdrant_binary(
        tmp_path,
        _WORKER.format(pidfile=str(pidfile), ignore_requests=ignore_requests),
        name="wrapped",
        launcher_exits_first=launcher_exits_first,
    )
    supervisor = QdrantSupervisor(
        unpinned(launcher),
        http_port=free_loopback_port(),
        storage_dir=tmp_path / "qdrant" / "storage",
        log_path=tmp_path / "qdrant.log",
    )
    return supervisor, pidfile


def _worker_started_by(supervisor: QdrantSupervisor, pidfile: Path) -> psutil.Process:
    """Spawn, and return the worker once it has recorded itself."""
    supervisor.spawn()
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if pidfile.is_file() and pidfile.read_text(encoding="utf-8").strip():
            worker = psutil.Process(int(pidfile.read_text(encoding="utf-8")))
            assert worker.pid != supervisor.pid, (
                "premise: the worker is not the supervised child itself"
            )
            return worker
        time.sleep(0.05)
    pytest.fail("the worker never started")


def _gone(worker: psutil.Process) -> bool:
    try:
        return not worker.is_running() or worker.status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


def _end_if_left(worker: psutil.Process | None) -> None:
    """End a worker a failing run left behind, so it does not outlive the test."""
    if worker is not None:
        with contextlib.suppress(psutil.Error):
            worker.kill()


def test_a_stop_ends_the_server_a_launcher_started(tmp_path: Path) -> None:
    """The launcher waits for its worker; the stop ends both.

    Mutation check: with the stop ending the supervised child alone, the
    launcher is ended and the worker runs on, so the stop either reports
    success with the worker alive - failing the last assertion - or, where
    the worker keeps the output pipe open, reports that it did not converge
    and fails the first. Restoring the tree stop passes.
    """
    supervisor, pidfile = _supervisor_of(tmp_path, launcher_exits_first=False)
    worker: psutil.Process | None = None
    try:
        worker = _worker_started_by(supervisor, pidfile)

        assert supervisor.stop(timeout=10.0), "the stop did not converge"
        assert supervisor.pid is None
        assert _gone(worker), "the server the launcher started outlived the stop"
    finally:
        _end_if_left(worker)


def test_a_worker_that_ignores_the_request_is_killed_with_its_launcher(
    tmp_path: Path,
) -> None:
    """Asking is followed by killing, and the kill reaches the whole tree.

    Mutation check: with the kill sent to the supervised child alone, a
    worker that ignores the request survives on any platform that delivers
    one, and the last assertion fails. Restoring the tree kill passes. On
    Windows every stop is a termination, so this passes for the same reason
    the first case does.
    """
    supervisor, pidfile = _supervisor_of(
        tmp_path, launcher_exits_first=False, ignore_requests=True
    )
    worker: psutil.Process | None = None
    try:
        worker = _worker_started_by(supervisor, pidfile)

        assert supervisor.stop(timeout=1.0), "the stop did not converge"
        assert _gone(worker), "a worker that ignored the request outlived the stop"
    finally:
        _end_if_left(worker)


def test_a_server_left_behind_by_a_launcher_that_exited_is_ended_too(
    tmp_path: Path,
) -> None:
    """The supervised child is already gone; what it started is still the tree.

    The launcher starts the worker and exits, so the supervisor sees a dead
    child. That is the state a restart begins from, and a restart that left
    the old server running would start a second one against the same store.

    Mutation check: with a child that already exited treated as having
    nothing left to stop, the worker runs on and the stop either fails to
    converge or reports success over a live worker; either assertion fails.
    Restoring the tree stop passes.
    """
    supervisor, pidfile = _supervisor_of(tmp_path, launcher_exits_first=True)
    worker: psutil.Process | None = None
    try:
        worker = _worker_started_by(supervisor, pidfile)
        deadline = time.monotonic() + 30.0
        while supervisor.is_alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not supervisor.is_alive(), "premise: the launcher has exited"
        assert not _gone(worker), "premise: the worker outlived its launcher"

        assert supervisor.stop(timeout=10.0), "the stop did not converge"
        assert _gone(worker), "the server a dead launcher left behind was not ended"
    finally:
        _end_if_left(worker)
