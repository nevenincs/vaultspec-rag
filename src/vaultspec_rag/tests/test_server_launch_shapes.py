"""A running service is found by its command line, whichever release started it.

The service is started with the interpreter's safe-path flag ahead of the
module switch. Releases before that started it without the flag, and a
service one of them started is still running when the next command line is
installed over it: the new command line has to find it, confirm it and stop
it. Everything that finds a service process reads its command line, so each
of those readers is run here against both shapes.

The readers are exercised against a real process carrying the real command
line. It is the witness module the stop tests use: a stand-in under the
server's module name that prints a line and sleeps, so no service starts.

The same readers classify the stdio adapter an assistant session starts,
which is a server launch with no port. Its command line is written by another
package; the cases here hold that it is read correctly with the flag as well,
so that package can add it without anything changing here.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
from typing import TYPE_CHECKING, cast

import psutil
import pytest

from .._process_probe import (
    is_server_launch,
    pid_argv,
    pid_image_path,
    pid_terminated,
    server_launch_option,
    server_launch_port,
)
from ..cli._process import (
    _discover_late_service_pids,
    _is_our_service,
    _is_service_command,
    _service_launch_command,
)
from ..cli._service_status import _write_service_status
from ..cli._service_stop import _orphan_daemon_pids
from ..serviceclient._discovery import _merge_service_status
from ._ports import free_loopback_port
from .test_service_stop_port import (
    _port_stop,
    _witness_environment,
    _write_witness_module,
    isolated_stop_status,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

__all__ = ["isolated_stop_status"]

_TOKEN = "recorded-launch"


def _previous_release_command(interpreter: str, port: int, token: str) -> list[str]:
    """The command line releases before the safe-path flag started a service with."""
    return [
        interpreter,
        "-m",
        "vaultspec_rag.server",
        "--port",
        str(port),
        "--launch-token",
        token,
    ]


_SHAPES: dict[str, Callable[[str, int, str], list[str]]] = {
    "this-release": _service_launch_command,
    "previous-release": _previous_release_command,
}


@contextlib.contextmanager
def _running_witness(
    shape: str, port: int, tmp_path: Path
) -> Generator[subprocess.Popen[str]]:
    """Keep a process alive under a service command line of *shape*."""
    # The interpreter image itself, not its environment's launcher, so the pid
    # recorded is the process that carries the command line on every platform.
    interpreter = pid_image_path(psutil.Process().pid)
    assert interpreter is not None
    module_root = _write_witness_module(tmp_path / "witness")
    child = subprocess.Popen(
        _SHAPES[shape](interpreter, port, _TOKEN),
        stdout=subprocess.PIPE,
        text=True,
        env=_witness_environment(module_root),
        creationflags=0x00000200 if sys.platform == "win32" else 0,
        start_new_session=sys.platform != "win32",
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "up"
        yield child
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=10)
        if child.stdout is not None:
            child.stdout.close()


def test_the_launch_command_carries_the_safe_path_flag_and_is_read_back() -> None:
    """What the spawn writes is what the recognisers read.

    Shown to fail by dropping the safe-path flag from the recogniser's list of
    interpreter options: the port is no longer read and the second assertion
    fires. Passes with the option restored.
    """
    command = _service_launch_command("python", 8766, _TOKEN)

    assert command[:3] == ["python", "-P", "-m"]
    assert server_launch_port(command) == 8766
    assert server_launch_option(command, "--launch-token") == _TOKEN
    assert _is_service_command(command, 8766, launch_token=_TOKEN)
    assert not _is_service_command(command, 8767, launch_token=_TOKEN)
    assert not _is_service_command(command, 8766, launch_token="another-launch")


@pytest.mark.parametrize(
    ("arguments", "port"),
    [
        (["python", "-P", "-m", "vaultspec_rag.server"], None),
        (["python", "-m", "vaultspec_rag.server"], None),
        (["python", "-P", "-m", "vaultspec_rag.server", "--read-only"], None),
        (["python3.13", "-P", "-m", "vaultspec_rag.server", "--port", "8766"], 8766),
        (["python", "-m", "vaultspec_rag.server", "--port=8766"], 8766),
    ],
)
def test_a_server_launch_is_recognised_with_and_without_the_flag(
    arguments: list[str], port: int | None
) -> None:
    """The adapter and the service are both read in either shape.

    A launch with no port is the stdio adapter, which a stop must never
    target and a holder report must name as an adapter. Shown to fail by the
    same mutation as above: the flagged cases stop being server launches.
    """
    assert is_server_launch(arguments)
    assert server_launch_port(arguments) == port


@pytest.mark.parametrize(
    "arguments",
    [
        ["uv", "run", "--no-sync", "python", "-P", "-m", "vaultspec_rag.server"],
        ["python", "-P", "-c", "pass", "-m", "vaultspec_rag.server", "--port", "8766"],
        ["python", "-P", "other.py", "-m", "vaultspec_rag.server", "--port", "8766"],
        ["python", "-P", "--", "-m", "vaultspec_rag.server", "--port", "8766"],
    ],
)
def test_the_flag_does_not_make_foreign_arguments_a_server_launch(
    arguments: list[str],
) -> None:
    """Accepting the flag admits nothing that was refused without it."""
    assert not is_server_launch(arguments)
    assert server_launch_port(arguments) is None


@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_running_service_is_found_by_every_reader_of_its_command_line(
    shape: str, tmp_path: Path
) -> None:
    """Confirmation, the orphan sweep and late-launch discovery all find it.

    Shown to fail, for the shape this release starts, by dropping the
    safe-path flag from the recogniser's list of interpreter options: the
    first assertion fires. The previous release's shape keeps passing under
    that mutation, which is the point of holding both.
    """
    port = free_loopback_port()
    with _running_witness(shape, port, tmp_path) as child:
        assert is_server_launch(pid_argv(child.pid) or []), shape
        assert _is_our_service(
            child.pid,
            port=port,
            require_launch_witness=True,
            expected_launch_token=_TOKEN,
        )
        assert not _is_our_service(
            child.pid,
            port=port,
            require_launch_witness=True,
            expected_launch_token="another-launch",
        )
        assert not _is_our_service(
            child.pid, port=port + 1, require_launch_witness=True
        )
        assert child.pid in _orphan_daemon_pids(port)
        discovered, error = _discover_late_service_pids(
            port=port, launch_token=_TOKEN, budget=120.0
        )
        assert not error
        assert child.pid in discovered


@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_stop_ends_a_service_started_with_either_command_line(
    shape: str, tmp_path: Path, isolated_stop_status: Path
) -> None:
    """``server stop`` confirms and ends a service this or the last release began.

    The service is still starting, so nothing answers on its port and the
    command line is the only identity the stop has. Shown to fail, for the
    shape this release starts, by the same recogniser mutation: the stop
    reports the identity unconfirmed and leaves the process running.
    """
    port = free_loopback_port()
    with _running_witness(shape, port, tmp_path) as child:
        _write_service_status(child.pid, port)
        _merge_service_status({"phase": "warming", "launch_token": _TOKEN})

        exit_code, envelope = _port_stop(port)

        assert exit_code == 0, envelope
        data = cast("dict[str, object]", envelope["data"])
        assert data["status"] == "stopped", envelope
        assert data["pid"] == child.pid
        assert pid_terminated(child.pid), "the service was reported stopped and was not"
        assert not isolated_stop_status.exists()
