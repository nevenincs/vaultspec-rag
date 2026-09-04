"""Holders are reported by readiness, and never make a machine look unhealthy.

A held environment serves requests perfectly well. The holders matter only to
an operator about to replace it, so this dimension exists to be read before a
repair is attempted - not to fail a health check.
"""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from .._readiness import (
    DependencyReadiness,
    EnvironmentHoldersReadiness,
    ReadinessReport,
    ReadinessStatus,
    _environment_holders_readiness,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def test_a_held_environment_is_still_a_ready_one() -> None:
    """Holders never enter the aggregate readiness boolean.

    Guard assertion: were this dimension a dependency node, every machine with
    an editor session open on its tool environment would report not ready, and
    an operator would start hunting a fault that does not exist.
    """
    report = ReadinessReport(
        dependencies=[
            DependencyReadiness(name="torch", status=ReadinessStatus.READY),
            DependencyReadiness(name="models", status=ReadinessStatus.READY),
            DependencyReadiness(name="qdrant", status=ReadinessStatus.READY),
        ],
        environment_holders=EnvironmentHoldersReadiness(
            scanned=True,
            held=True,
            certain=True,
            holders=[{"pid": 4321, "relation": "image", "image": "python.exe"}],
        ),
    )

    assert report.ready
    assert report.to_dict()["environment_holders"]["held"] is True


def test_the_snapshot_never_publishes_a_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Holder facts reach an HTTP route, so argument vectors stay out of them.

    Guard assertion: a command line can carry a token or a path an operator
    never chose to expose, and this snapshot is served over the network.
    """
    root = tmp_path / "env"
    created = subprocess.run(
        ["uv", "venv", str(root)], capture_output=True, check=False
    )
    if created.returncode != 0:
        pytest.skip(f"could not create a virtual environment: {created.stderr!r}")
    interpreter = root / "Scripts" / "python.exe"
    if not interpreter.exists():
        interpreter = root / "bin" / "python"

    monkeypatch.setattr(sys, "prefix", str(root))
    child = subprocess.Popen([str(interpreter), "-c", "import time; time.sleep(60)"])
    try:
        deadline = __import__("time").monotonic() + 20.0
        snapshot = _environment_holders_readiness()
        while __import__("time").monotonic() < deadline and not snapshot.held:
            __import__("time").sleep(0.1)
            snapshot = _environment_holders_readiness()
    finally:
        child.terminate()
        child.wait(timeout=30)

    assert snapshot.held, "a live interpreter in the environment was not reported"
    assert any(holder["pid"] == child.pid for holder in snapshot.holders)
    assert all("cmdline" not in holder for holder in snapshot.holders)
    assert all(
        set(holder) == {"pid", "relation", "image"} for holder in snapshot.holders
    )


def test_a_polled_route_does_not_pay_for_a_process_table_walk() -> None:
    """Readiness skips the holder scan unless a caller asks for it.

    Guard assertion: the walk costs seconds on a busy machine, and this
    snapshot answers an HTTP route. A default-on scan would either slow every
    poll or, budgeted short enough to be safe, report "cannot tell" every time
    and teach an operator to ignore the dimension.
    """
    from .._readiness import compute_readiness

    holders = compute_readiness().environment_holders

    assert holders.scanned is False
    assert holders.certain is False
    assert holders.holders == []
