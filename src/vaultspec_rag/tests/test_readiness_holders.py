"""Holders are reported by readiness, and never make a machine look unhealthy.

A held environment serves requests perfectly well. The holders matter only to
an operator about to replace it, so this dimension exists to be read before a
repair is attempted - not to fail a health check.
"""

from __future__ import annotations

import subprocess
import sys
import time
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

# Each poll walks the whole process table, so the interval is slack and the
# deadline is generous: a dozen workers scanning at once turn a scan that costs
# a second alone into one costing many, and a tight poll is what starves them.
_SCAN_BUDGET_SECONDS = 120.0
_WAIT_SECONDS = 90.0
_POLL_SECONDS = 0.5
_HOLDER_LIFETIME_SECONDS = 120


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
    holders = report.to_dict()["environment_holders"]
    assert isinstance(holders, dict)
    assert holders["held"] is True


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
    # The production budget is sized for an HTTP route, and a scan walking a
    # thousand processes does not fit inside it on a runner hosting a dozen
    # parallel workers. What this test proves is the SHAPE of the snapshot, so
    # it buys the scan the time it needs rather than asserting against a
    # timeout that reports "cannot tell" and reads as a missing holder.
    monkeypatch.setattr(
        "vaultspec_rag._readiness._HOLDER_SCAN_BUDGET_SECONDS", _SCAN_BUDGET_SECONDS
    )
    child = subprocess.Popen(
        [str(interpreter), "-c", f"import time; time.sleep({_HOLDER_LIFETIME_SECONDS})"]
    )
    try:
        deadline = time.monotonic() + _WAIT_SECONDS
        snapshot = _environment_holders_readiness()
        while time.monotonic() < deadline and not snapshot.held:
            time.sleep(_POLL_SECONDS)
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
