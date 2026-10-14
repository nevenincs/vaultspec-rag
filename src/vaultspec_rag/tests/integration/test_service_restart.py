"""``server restart`` run end to end against real service daemons.

Every case runs the shipped command in a child process: the verb composes the
stop and start verbs as children of its own and reads the one envelope each of
them prints, so what matters is what real processes put on their real streams.
Each service listens on a port of its own, under an isolated status directory
and storage directory, so none of them can reach the machine's resident service.

The refusals are real as well. A listener that holds the port and answers
nothing is what a foreign program on the service's port looks like, and a
discovery record naming a live process that is not the service is what a record
whose pid was reused looks like.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from ..._process_probe import pid_alive
from ..._python_child import inline_command, module_command
from ...config._types import EnvVar
from ...monitor_process import stop_recorded_monitor
from ...serviceclient._discovery import read_service_status
from .._session_job_anchor import anchor_spawned_process_to_session
from ..conftest import managed_env
from ._helpers import _poll_health
from ._service_lifecycle_helpers import _port_is_listening, _service_processes_on_port
from .conftest import _live_service_context

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Mapping
    from pathlib import Path

pytestmark = [pytest.mark.subprocess_gpu]

#: Upper bound on one verb run. The restart waits for its start step, which
#: loads the models, so this is a hang guard sized well past a loaded host.
_VERB_TIMEOUT_SECONDS = 600.0

#: Gap between looks at a verb that is still running.
_WATCH_INTERVAL_SECONDS = 0.05

#: How long a daemon is given to publish its next heartbeat, which it does on
#: a fixed interval of fifteen seconds.
_HEARTBEAT_WAIT_SECONDS = 45.0


@dataclass(frozen=True, slots=True)
class _Outcome:
    """What one verb run exited with and printed."""

    returncode: int
    stdout: str
    stderr: str

    def describe(self) -> str:
        return (
            f"exit={self.returncode}\nstdout:\n{self.stdout}\n"
            f"stderr tail:\n{self.stderr[-3000:]}"
        )

    @property
    def envelope(self) -> dict[str, object]:
        """The one envelope the verb printed, which is all it may print."""
        lines = [line for line in self.stdout.splitlines() if line.strip()]
        assert len(lines) == 1, f"expected one envelope\n{self.describe()}"
        return cast("dict[str, object]", json.loads(lines[0]))

    @property
    def data(self) -> dict[str, object]:
        return cast("dict[str, object]", self.envelope["data"])


def _cli(
    verb: str,
    port: int,
    *,
    explicit_port: bool = True,
    env: Mapping[str, str] | None = None,
    watch: Callable[[], None] | None = None,
) -> _Outcome:
    """Run ``server <verb> --json`` in a child process and capture its output.

    Without ``explicit_port`` the flag is left off, so the steps a restart
    composes take their port from the environment alone. *env* is added to the
    child's environment. The port is in it in every case, so a step that falls
    back to its default can never reach the machine's own service port.
    *watch* is called repeatedly while the child runs, for a caller that has to
    see what the verb does on the way to its outcome.
    """
    arguments = ["server", verb, "--json"]
    if explicit_port:
        arguments += ["--port", str(port)]
    environment = {
        **os.environ,
        "PYTHONUTF8": "1",
        EnvVar.PORT.value: str(port),
        **(env or {}),
    }
    # Files rather than pipes: a verb that prints more than a pipe holds would
    # block on a reader that is busy watching it.
    with (
        tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as out,
        tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as err,
    ):
        process = subprocess.Popen(
            module_command(sys.executable, "vaultspec_rag", *arguments),
            stdout=out,
            stderr=err,
            env=environment,
        )
        deadline = time.monotonic() + _VERB_TIMEOUT_SECONDS
        while True:
            try:
                process.wait(timeout=_WATCH_INTERVAL_SECONDS)
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    process.kill()
                    process.wait()
                    raise AssertionError(
                        f"server {verb} did not finish within "
                        f"{_VERB_TIMEOUT_SECONDS:.0f}s"
                    ) from None
                if watch is not None:
                    watch()
        out.seek(0)
        err.seek(0)
        return _Outcome(process.returncode, out.read(), err.read())


def _discovery() -> dict[str, object]:
    """The service discovery record the daemon under test published."""
    status = read_service_status()
    assert status is not None, "the service published no discovery record"
    return cast("dict[str, object]", status)


def _after_next_heartbeat(seen: object) -> dict[str, object]:
    """Return the discovery record once its heartbeat differs from *seen*."""
    deadline = time.monotonic() + _HEARTBEAT_WAIT_SECONDS
    while time.monotonic() < deadline:
        status = read_service_status()
        if status is not None and status.get("last_heartbeat") != seen:
            return cast("dict[str, object]", status)
        time.sleep(0.25)
    raise AssertionError(
        f"no heartbeat followed {seen!r} within {_HEARTBEAT_WAIT_SECONDS:.0f}s"
    )


def _monitor_record(status_dir: Path) -> dict[str, object] | None:
    """Read the monitor's ownership record, or ``None`` while it is unreadable.

    The record is replaced whole, so a read that races a replacement fails
    outright and never returns half of one; the caller simply looks again.
    """
    try:
        raw: object = json.loads(
            (status_dir / "monitor.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None
    return cast("dict[str, object]", raw) if isinstance(raw, dict) else None


def _keep_with_session(status: dict[str, object]) -> int:
    """Bind the daemon a restart started to the session, and return its pid.

    A restart starts its daemon through the shipped start verb, never through
    the anchored spawn the other live-service tests use, so the session
    cannot bind it at birth. Binding it here means a run killed before this
    test's teardown still takes it down. What the session binds is the
    launcher, as in the anchored spawn: the daemon it started exits with it.
    The launcher is bound only when it is one of the processes running the
    service on this port, never a pid merely recorded as the daemon's parent.
    """
    launcher = status.get("parent_pid")
    if launcher in _service_processes_on_port(cast("int", status["port"])):
        anchor_spawned_process_to_session(cast("int", launcher))
    return cast("int", status["pid"])


@contextmanager
def _running_service(tmp_path: Path) -> Generator[int]:
    """Run a real daemon on a port of its own, and clean up after a restart.

    A restart replaces the daemon and may leave a monitor that has outlived its
    owner, which the daemon teardown alone does not reap. Whatever is recorded
    is reaped once the daemon is gone, still under the daemon's own directories.
    """
    environment: dict[str, str | None] = {}
    try:
        with _live_service_context(tmp_path) as (port, _status_dir, applied):
            environment = applied
            yield port
    finally:
        if environment:
            with managed_env(**environment):
                stop_recorded_monitor()


@contextmanager
def _foreign_listener() -> Generator[int]:
    """Hold a loopback port with a real listener that never answers.

    The backlog is large so that every connect a verb makes completes its
    handshake; a full backlog would drop connects, which a verb reads as a
    refusal and not as something listening.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        yield int(listener.getsockname()[1])


@contextmanager
def _unrelated_process() -> Generator[subprocess.Popen[bytes]]:
    """Run a live process that is not a service, and end it on exit.

    It exits when its stdin closes, so ending it leaves nothing behind
    whichever interpreter shim launched it.
    """
    process = subprocess.Popen(
        inline_command(sys.executable, "import sys; sys.stdin.read()"),
        stdin=subprocess.PIPE,
    )
    try:
        yield process
    finally:
        if process.stdin is not None:
            process.stdin.close()
        process.wait(timeout=30)


@pytest.mark.timeout(900)
def test_a_running_service_restarts_and_keeps_its_monitor(tmp_path: Path) -> None:
    """A restart replaces the daemon, and the open monitor page stays connected.

    The proof is the monitor itself, not the envelope's word for it: the
    restarted daemon records the very process, and the very access link, the
    first daemon had.

    Mutations it catches: dropping the monitor release leaves the envelope
    reporting the monitor as not kept and fails that assertion; claiming it
    kept without releasing it reports it kept, and fails the monitor process
    comparison instead. Each fails alone, and restoring the verb passes.
    """
    with _running_service(tmp_path) as port:
        before = _discovery()
        old_pid = cast("int", before["pid"])
        monitor_pid = cast("int", before["monitor_pid"])
        link = before["monitor_url"]
        assert pid_alive(monitor_pid)

        outcome = _cli("restart", port)

        assert outcome.returncode == 0, outcome.describe()
        envelope = outcome.envelope
        data = outcome.data
        assert envelope["command"] == "service.restart"
        assert envelope["ok"] is True
        assert data["status"] == "restarted"
        assert data["monitor_kept"] is True
        assert data["port"] == port
        after = _discovery()
        new_pid = _keep_with_session(after)
        assert new_pid != old_pid
        assert not pid_alive(old_pid)
        assert _poll_health(port)["pid"] == new_pid
        assert after["monitor_pid"] == monitor_pid
        assert pid_alive(monitor_pid)
        assert after["monitor_url"] == link
        assert data["monitor_url"] == link


@pytest.mark.timeout(900)
def test_a_restart_brings_the_service_back_on_the_port_it_ran_on(
    tmp_path: Path,
) -> None:
    """With no port given, the replacement comes back where the service ran.

    The configured port names another free port, so a start step left to its
    own default would bring the service back somewhere else. Mutation it
    catches: handing the start step the caller's port rather than the running
    service's, which starts the replacement on the configured port and fails
    the port assertion.
    """
    from .._ports import free_loopback_port

    with _running_service(tmp_path) as port:
        elsewhere = free_loopback_port()
        assert elsewhere != port

        outcome = _cli("restart", elsewhere, explicit_port=False)

        assert outcome.returncode == 0, outcome.describe()
        assert outcome.data["status"] == "restarted"
        assert outcome.data["port"] == port
        new_pid = _keep_with_session(_discovery())
        assert _poll_health(port)["pid"] == new_pid
        assert not _port_is_listening(elsewhere)


@pytest.mark.timeout(900)
def test_a_stopped_service_is_started_by_a_restart(tmp_path: Path) -> None:
    """A restart of a service that is not running starts it, and says started.

    The service is stopped for real first. With nothing running there is no
    monitor to keep, so the restart reports the monitor as not kept and the
    start step's own monitor link is the one it passes on.

    Mutation it catches: reporting every restart as one that stopped a running
    service says restarted for started and fails the status assertion.
    """
    with _running_service(tmp_path) as port:
        old_pid = cast("int", _discovery()["pid"])
        stopped = _cli("stop", port)
        assert stopped.returncode == 0, stopped.describe()
        assert stopped.data["status"] == "stopped"
        assert not pid_alive(old_pid)

        outcome = _cli("restart", port)

        assert outcome.returncode == 0, outcome.describe()
        data = outcome.data
        assert outcome.envelope["command"] == "service.restart"
        assert outcome.envelope["ok"] is True
        assert data["status"] == "started"
        assert data["monitor_kept"] is False
        assert data["port"] == port
        after = _discovery()
        new_pid = _keep_with_session(after)
        assert new_pid != old_pid
        assert _poll_health(port)["pid"] == new_pid
        assert data["monitor_url"] == after["monitor_url"]


@pytest.mark.timeout(900)
def test_a_refused_stop_gives_the_released_monitor_back(tmp_path: Path) -> None:
    """A restart whose stop is refused leaves the daemon serving with its monitor.

    The restart runs under a status directory whose record names a live process
    that is not the service, which is how a record looks once its pid has been
    reused. The service is found through the machine's own pointer, so the
    monitor is released to it, and the stop step then refuses to end a process
    it cannot identify. The release is watched while it stands, and the
    restart must end it.

    Mutations it catches: dropping the release fails the assertion that the
    monitor was ever released, so the take-back below cannot pass for want of
    anything to take back; dropping the take-back leaves the release standing
    and fails the ownership record assertion. Restoring the verb passes.
    """
    with _running_service(tmp_path) as port, _unrelated_process() as stranger:
        before = _discovery()
        pid = cast("int", before["pid"])
        monitor_pid = cast("int", before["monitor_pid"])
        link = before["monitor_url"]
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        record = elsewhere / "service.json"
        record.write_text(
            json.dumps({"pid": stranger.pid, "port": port}), encoding="utf-8"
        )
        released: list[dict[str, object]] = []

        def watch_the_release() -> None:
            ownership = _monitor_record(tmp_path)
            if (
                ownership is not None
                and cast("float", ownership["handoff_until"]) > time.time()
            ):
                released.append(ownership)

        outcome = _cli(
            "restart",
            port,
            explicit_port=False,
            env={EnvVar.STATUS_DIR.value: str(elsewhere)},
            watch=watch_the_release,
        )

        assert outcome.returncode == 1, outcome.describe()
        envelope = outcome.envelope
        assert envelope["command"] == "service.restart"
        assert envelope["ok"] is False
        assert envelope["error"] == "restart_stop_failed"
        assert envelope["message"] == "Service stop skipped"
        assert released, "the restart never released the monitor"
        assert released[0]["access"] == link
        assert record.is_file()
        assert pid_alive(pid)
        assert pid_alive(stranger.pid)
        assert _poll_health(port)["pid"] == pid
        ownership = _monitor_record(tmp_path)
        assert ownership is not None
        assert ownership["handoff_until"] == 0.0
        assert ownership["access"] == ""
        assert pid_alive(monitor_pid)
        published = _after_next_heartbeat(_discovery()["last_heartbeat"])
        assert published.get("monitor_pid") == monitor_pid
        assert published.get("monitor_url") == link


@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_a_port_holder_that_will_not_identify_fails_the_restart_at_its_stop() -> None:
    """A stop that cannot identify the port holder fails the restart at its stop.

    A silent listener holds the port, so the stop step refuses to terminate
    anything it cannot identify and reports that. The restart must say its
    stop failed and must not go on to start.

    Mutation it catches: ignoring a failed stop goes on to a start that the
    listener refuses, so the restart reports its start failed and the error
    assertion fails. Restoring the verb passes.
    """
    with _foreign_listener() as port:
        outcome = _cli("restart", port, env={EnvVar.SERVICE_ADMIN_TIMEOUT.value: "2"})

        assert outcome.returncode == 1, outcome.describe()
        envelope = outcome.envelope
        assert envelope["command"] == "service.restart"
        assert envelope["ok"] is False
        assert envelope["error"] == "restart_stop_failed"
        assert envelope["message"] == "The port is held by an unconfirmed process"
        assert _port_is_listening(port)
        assert read_service_status() is None
        assert _service_processes_on_port(port) == {}


@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_a_refused_start_fails_the_restart_at_its_start() -> None:
    """A start that is refused fails the restart, and nothing is left running.

    With no service to stop, the stop step succeeds, and the start step takes
    its port from the environment and finds a listener on it.

    Mutation it catches: ignoring a failed start reports the restart as having
    started a service, exits zero, and fails the exit status assertion.
    Restoring the verb passes.
    """
    with _foreign_listener() as port:
        outcome = _cli("restart", port, explicit_port=False)

        assert outcome.returncode == 1, outcome.describe()
        envelope = outcome.envelope
        assert envelope["command"] == "service.restart"
        assert envelope["ok"] is False
        assert envelope["error"] == "restart_start_failed"
        assert envelope["message"] == "Service start failed"
        assert read_service_status() is None
        assert _service_processes_on_port(port) == {}
