"""Restart handoff, adoption and lifecycle waits against the real compiled monitor."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from .._loopback_http import LOOPBACK_OPENER
from .._process_probe import pid_alive, wait_for_exit
from ..config._types import EnvVar
from ..monitor_process import MonitorProcess, extend_handoff, stop_recorded_monitor
from .conftest import managed_env
from .test_monitor_process import _ports
from .test_monitor_process_integration import (
    compiled_monitor_required as compiled_monitor_required,
)

if TYPE_CHECKING:
    from collections.abc import Generator

pytestmark = pytest.mark.unit


@pytest.fixture
def backend_port() -> Generator[int]:
    with _ports(2) as listeners:
        port = listeners[0].getsockname()[1]
        # The monitor scans upward from the backend port plus one.
        listeners[-1].close()
        yield port


def _authorized_status(link: str) -> int:
    """Status of a bridge call presenting the link's capability."""
    base, _, capability = link.partition("/#capability=")
    request = Request(
        f"{base}/api/monitor/health",
        headers={"Authorization": f"Bearer {capability}"},
    )
    try:
        with LOOPBACK_OPENER.open(request, timeout=15) as response:
            return response.status
    except HTTPError as error:
        return error.code


def _end(monitor: MonitorProcess, pid: int) -> None:
    monitor.stop()
    if pid_alive(pid):
        stop_recorded_monitor()


def test_a_released_monitor_outlives_its_owner_and_is_adopted_with_its_link(
    isolated_singleton_dirs: Path, backend_port: int
) -> None:
    first = MonitorProcess(backend_port)
    first.start()
    assert first.process is not None
    pid = first.process.pid
    link = first.access
    assert link is not None
    second = MonitorProcess(backend_port)
    try:
        assert first.hand_off()
        first.stop()
        # The EOF the stop produced would close an unreleased monitor at once.
        time.sleep(3)
        assert pid_alive(pid)
        assert _authorized_status(link) != 401

        second.start()

        assert second.process is None
        assert second.identity is not None
        assert second.identity.pid == pid
        assert second.access == link
        assert second.discovery_fields()["monitor_pid"] == pid
        time.sleep(3)
        assert pid_alive(pid), "an adopted monitor must stay while its owner lives"
        assert second.stop()
        assert wait_for_exit(pid, timeout=10)
        assert not (isolated_singleton_dirs / "monitor.json").exists()
    finally:
        _end(second, pid)


def test_an_unadopted_handoff_closes_the_monitor_at_its_deadline(
    isolated_singleton_dirs: Path, backend_port: int
) -> None:
    monitor = MonitorProcess(backend_port)
    monitor.start()
    assert monitor.process is not None
    pid = monitor.process.pid
    try:
        assert monitor.hand_off(seconds=2)
        monitor.stop()
        assert wait_for_exit(pid, timeout=15)
    finally:
        _end(monitor, pid)
        (isolated_singleton_dirs / "monitor.json").unlink(missing_ok=True)


def test_a_handoff_from_a_different_executable_is_ended_not_adopted(
    isolated_singleton_dirs: Path, backend_port: int
) -> None:
    """Mutation it catches: dropping the executable digest from adoption.

    Without it a restart onto an upgraded or replaced binary keeps running the
    monitor the previous release launched. With the comparison removed this
    test adopted the released monitor and failed on ``second.process``;
    restored, it passed.
    """
    first = MonitorProcess(backend_port)
    first.start()
    assert first.process is not None
    pid = first.process.pid
    second = MonitorProcess(backend_port)
    try:
        assert first.hand_off()
        first.stop()
        # Released by a daemon that launched some other executable.
        record = isolated_singleton_dirs / "monitor.json"
        released = json.loads(record.read_text(encoding="utf-8"))
        released["executable_sha256"] = "0" * 64
        record.write_text(json.dumps(released), encoding="utf-8")

        second.start()

        assert second.process is not None
        assert second.process.pid != pid
        assert wait_for_exit(pid, timeout=10)
    finally:
        second.stop()
        _end(first, pid)


def test_a_released_monitor_is_taken_back_when_the_stop_does_not_happen(
    isolated_singleton_dirs: Path, backend_port: int
) -> None:
    """A restart whose stop failed leaves the daemon serving with its monitor.

    Mutations it catches: a reclaim that leaves the release in place, which
    keeps the monitor out of discovery and fails the discovery assertion; and
    one that leaves the record keeping it open for a successor, which fails
    the deadline assertion.
    """
    monitor = MonitorProcess(backend_port)
    monitor.start()
    assert monitor.process is not None
    pid = monitor.process.pid
    try:
        assert monitor.hand_off()
        assert monitor.discovery_fields() == {}

        assert monitor.reclaim()

        assert monitor.discovery_fields().get("monitor_pid") == pid
        record = json.loads(
            (isolated_singleton_dirs / "monitor.json").read_text(encoding="utf-8")
        )
        assert record["handoff_until"] == 0.0
        assert record["access"] == ""
        assert not monitor.reclaim(), "nothing is released twice"
        assert monitor.stop()
        assert wait_for_exit(pid, timeout=10)
    finally:
        _end(monitor, pid)


def test_a_renewed_handoff_keeps_the_monitor_until_renewal_stops(
    isolated_singleton_dirs: Path, backend_port: int
) -> None:
    """A restart still provisioning keeps the monitor open; one that died does not.

    The handoff is two seconds and is renewed past that while the owner is
    gone, which is a restart waiting on a long start step. Once renewal stops
    the monitor closes within a window. Mutation: renewal that writes nothing
    lets the monitor close at its first deadline and fails the alive assertion;
    renewal that revives an expired handoff fails the final refusal; restoring
    both passes.
    """
    monitor = MonitorProcess(backend_port)
    monitor.start()
    assert monitor.process is not None
    pid = monitor.process.pid
    try:
        assert monitor.hand_off(seconds=2)
        monitor.stop()
        renewed_until = time.monotonic() + 6
        while time.monotonic() < renewed_until:
            assert extend_handoff(seconds=2)
            time.sleep(0.5)
        assert pid_alive(pid), "a renewed handoff closed the monitor"

        assert wait_for_exit(pid, timeout=15)
        assert not extend_handoff(seconds=2), "an expired handoff was revived"
    finally:
        _end(monitor, pid)
        (isolated_singleton_dirs / "monitor.json").unlink(missing_ok=True)


def _page_budgets(served: object) -> dict[str, dict[str, float]]:
    """What the page waits on each verb, given what the server *served*."""
    node = shutil.which("node")
    assert node is not None
    source = Path(__file__).resolve().parents[2] / "monitor/lifecycle-budget.ts"
    script = (
        "import { pageBudgetMilliseconds, lifecycleBudgetMilliseconds } "
        f"from {json.dumps(source.as_uri())};"
        f"const served = {json.dumps(served)};"
        "console.log(JSON.stringify({"
        "page: Object.fromEntries(['start','stop','restart'].map("
        "(verb) => [verb, pageBudgetMilliseconds(verb, served)])),"
        "fallback: lifecycleBudgetMilliseconds()}));"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_the_page_waits_what_the_monitor_server_serves(
    isolated_singleton_dirs: Path, backend_port: int
) -> None:
    """A raised readiness window reaches the page's wait through the server.

    The server reads the window from its environment and reports its waits
    with the lifecycle state; the page waits those rather than the default it
    would otherwise assume, and the default only when nothing was served.
    Mutation: the page ignoring what was served waits the default start and
    fails the served-start assertion; the server not serving its waits leaves
    no budget in the reply and fails the raised-window assertion; restoring
    both passes.
    """
    del isolated_singleton_dirs
    with managed_env(**{EnvVar.QDRANT_READY_TIMEOUT.value: "900"}):
        monitor = MonitorProcess(backend_port)
        monitor.start()
    assert monitor.process is not None
    pid = monitor.process.pid
    link = monitor.access
    assert link is not None
    try:
        base, _, capability = link.partition("/#capability=")
        request = Request(
            f"{base}/api/monitor/lifecycle",
            headers={"Authorization": f"Bearer {capability}"},
        )
        with LOOPBACK_OPENER.open(request, timeout=60) as response:
            served = json.loads(response.read())["budget"]
        budgets = _page_budgets(served)
        assert served["start"] > budgets["fallback"]["start"], (
            "the raised readiness window did not reach the served wait"
        )
        assert budgets["page"] == served, "the page did not wait what was served"
        assert _page_budgets(None)["page"] == budgets["fallback"]
    finally:
        _end(monitor, pid)
