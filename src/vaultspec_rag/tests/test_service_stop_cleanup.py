"""Stop cleanup preserves a successor under the canonical discovery write lock."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest

from .._process_probe import pid_image_path
from ..cli import _service_stop as service_stop
from ..cli._service_status import _write_service_status
from ..serviceclient import _discovery as discovery
from .test_service_stop_port import (
    _port_stop,
    _starting_process,
)
from .test_service_stop_port import (
    isolated_stop_status as isolated_stop_status,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ..cli._process import TerminationResult

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize("explicit_port", [True, False])
@pytest.mark.parametrize("successor_port_changed", [True, False])
def test_a_stop_finishing_after_successor_publication_preserves_discovery(
    isolated_stop_status: Path,
    monkeypatch: pytest.MonkeyPatch,
    explicit_port: bool,
    successor_port_changed: bool,
) -> None:
    """Mutation proved: unconditional old-stop cleanup erases the successor."""
    from ._ports import free_loopback_port

    port = free_loopback_port()
    successor_port = port + 1 if successor_port_changed else port
    actual_termination = service_stop._terminate_and_confirm
    with (
        _starting_process(["-m", "vaultspec_rag.server", "--port", str(port)]) as old,
        _starting_process(
            ["-m", "vaultspec_rag.server", "--port", str(successor_port)]
        ) as successor,
    ):
        _write_service_status(old.pid, port)

        def publish_after_termination(
            pid: int,
            *,
            console_group_signal: bool = True,
            expected_start_time: float | None = None,
        ) -> TerminationResult:
            result = actual_termination(
                pid,
                console_group_signal=console_group_signal,
                expected_start_time=expected_start_time,
            )
            discovery._replace_service_status(
                {"pid": successor.pid, "port": successor_port}
            )
            return result

        monkeypatch.setattr(
            service_stop, "_terminate_and_confirm", publish_after_termination
        )
        exit_code, envelope = _port_stop(port if explicit_port else None)

        assert exit_code == 0, envelope
        assert isolated_stop_status.exists(), "old stop erased successor discovery"
        assert json.loads(isolated_stop_status.read_text(encoding="utf-8")) == {
            "pid": successor.pid,
            "port": successor_port,
        }
        assert successor.poll() is None, "old stop terminated the successor"
        assert old.poll() is not None


@pytest.mark.parametrize(
    "successor", [{"pid": 2002, "port": 8766}, {"pid": 1001, "port": 8767}]
)
def test_conditional_delete_preserves_a_successor(
    tmp_path: Path, successor: dict[str, int]
) -> None:
    """Mutation proved: deleting a different identity fails; restoration passes."""
    status = tmp_path / "service.json"
    discovery._replace_service_status(successor, path=status)
    original = status.read_bytes()

    deleted = discovery._delete_service_status(
        path=status, expected_pid=1001, expected_port=8766
    )

    assert not deleted, "conditional cleanup deleted a successor"
    assert status.read_bytes() == original


def test_conditional_delete_removes_only_the_expected_identity(tmp_path: Path) -> None:
    status = tmp_path / "service.json"
    discovery._replace_service_status({"pid": 1001, "port": 8766}, path=status)

    assert discovery._delete_service_status(
        path=status, expected_pid=1001, expected_port=8766
    )
    assert not status.exists()


@pytest.mark.parametrize("raw", ["{broken", "[]"])
def test_unreadable_conditional_identity_is_retained(tmp_path: Path, raw: str) -> None:
    """Mutation proved: an unknown record cannot authorize cleanup."""
    status = tmp_path / "service.json"
    status.write_text(raw, encoding="utf-8")

    assert not discovery._delete_service_status(
        path=status, expected_pid=1001, expected_port=8766
    ), "unknown discovery identity was deleted"
    assert status.read_text(encoding="utf-8") == raw


def test_identity_is_compared_after_the_contended_write_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutation proved: comparing before the shared lock loses a replacement."""
    status = tmp_path / "service.json"
    discovery._replace_service_status({"pid": 1001, "port": 8766}, path=status)
    successor = {"pid": 2002, "port": 8766}
    child_code = (
        "import json, sys\n"
        "from pathlib import Path\n"
        "from vaultspec_rag._atomic_write import write_json_atomically\n"
        "from vaultspec_rag.serviceclient._discovery import status_write_lock\n"
        "status = Path(sys.argv[1])\n"
        "with status_write_lock(status, timeout=30.0):\n"
        "    print('held', flush=True)\n"
        "    assert sys.stdin.readline().strip() == 'publish'\n"
        f"    write_json_atomically(status, {successor!r})\n"
    )
    interpreter = pid_image_path(os.getpid())
    assert interpreter is not None
    publisher = subprocess.Popen(
        [interpreter, "-c", child_code, str(status)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
    )
    actual_lock = discovery.status_write_lock
    deletion_waiting = threading.Event()

    @contextlib.contextmanager
    def observed_lock(path: Path, *, timeout: float = 1.0) -> Generator[None]:
        deletion_waiting.set()
        with actual_lock(path, timeout=timeout):
            yield

    try:
        assert publisher.stdout is not None
        assert publisher.stdout.readline().strip() == "held"
        monkeypatch.setattr(discovery, "status_write_lock", observed_lock)
        with ThreadPoolExecutor(max_workers=1) as executor:
            deletion = executor.submit(
                discovery._delete_service_status,
                path=status,
                timeout=30.0,
                expected_pid=1001,
                expected_port=8766,
            )
            assert deletion_waiting.wait(10.0), "deletion never reached the shared lock"
            assert not deletion.done(), "deletion bypassed the publisher's lock"
            assert publisher.stdin is not None
            publisher.stdin.write("publish\n")
            publisher.stdin.flush()
            publisher.wait(timeout=10.0)
            assert publisher.returncode == 0

            assert not deletion.result(timeout=10.0), (
                "pre-lock identity comparison deleted the replacement"
            )
        assert json.loads(status.read_text(encoding="utf-8")) == successor
    finally:
        if publisher.poll() is None:
            publisher.kill()
        publisher.wait(timeout=10.0)
        if publisher.stdin is not None:
            publisher.stdin.close()
        if publisher.stdout is not None:
            publisher.stdout.close()
