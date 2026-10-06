"""A dead server's one automatic restart is spent when it starts a process.

The service restarts a dead Qdrant server once in its lifetime. An attempt
that is refused before any process exists - the binary could not be read, or
no longer passes its check - started nothing. Counting it as the restart left
a server down for the life of the daemon because an antivirus scan held the
executable for a second. So a refused attempt is counted apart, retried on
later heartbeats up to a bound, and its reason is carried to every surface
that reports the server as dead.

Real launchers on the real filesystem, a real supervisor, and the heartbeat's
own liveness check; "it never ran" is a file the launcher would have written.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from .._readiness import ReadinessStatus, compute_readiness
from ..config._types import EnvVar
from ..operator_state._installation import ComputeCapability
from ..operator_state._models import ComputeReport
from ..qdrant_runtime._constants import BinarySource, ResolvedBinary
from ..qdrant_runtime._provision import file_sha256
from ..qdrant_runtime._supervise import (
    QdrantSupervisor,
    active_supervisor,
    set_active_supervisor,
)
from ..server._lifecycle import _qdrant_liveness_tick
from ._fake_qdrant_binary import fake_qdrant_binary, unpinned, unreadable
from ._ports import free_loopback_port
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("isolated_singleton_dirs")]

# Writes a file and exits: the only trace a launcher leaves of having run.
_RECORDS_THAT_IT_RAN = """
import pathlib

pathlib.Path({marker!r}).write_text("ran", encoding="utf-8")
"""


def _launcher(tmp_path: Path) -> tuple[Path, Path]:
    marker = tmp_path / "it-ran.txt"
    launcher = fake_qdrant_binary(
        tmp_path, _RECORDS_THAT_IT_RAN.format(marker=str(marker)), name="marker"
    )
    return launcher, marker


def _supervisor(binary: ResolvedBinary, tmp_path: Path) -> QdrantSupervisor:
    return QdrantSupervisor(
        binary,
        http_port=free_loopback_port(),
        storage_dir=tmp_path / "qdrant" / "storage",
        log_path=tmp_path / "qdrant.log",
    )


@pytest.fixture
def supervised(tmp_path: Path) -> Generator[tuple[QdrantSupervisor, Path, Path]]:
    """A supervisor installed as the service's own, with nothing running yet."""
    launcher, marker = _launcher(tmp_path)
    supervisor = _supervisor(unpinned(launcher), tmp_path)
    previous = active_supervisor()
    set_active_supervisor(supervisor)
    try:
        yield supervisor, launcher, marker
    finally:
        set_active_supervisor(previous)
        assert supervisor.stop(timeout=10.0)


def _ran_within(marker: Path, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if marker.exists():
            return True
        time.sleep(0.05)
    return marker.exists()


def test_an_attempt_that_could_not_read_the_binary_does_not_spend_the_restart(
    supervised: tuple[QdrantSupervisor, Path, Path],
) -> None:
    """The next heartbeat tries again, and that one starts the server.

    Mutation check: with every attempt counted as the restart, the first
    tick leaves the count at one, the second tick attempts nothing, and the
    count assertion after the first tick fails with one. Restoring the
    accounting passes.
    """
    supervisor, launcher, marker = supervised

    with unreadable(launcher):
        _qdrant_liveness_tick()

    assert supervisor.restart_count == 0
    assert supervisor.refused_restarts == 1
    assert not supervisor.restart_exhausted
    assert "cannot be read" in supervisor.restart_refusal
    assert supervisor.state().to_dict()["restart_refusal"] == (
        supervisor.restart_refusal
    )
    assert not marker.exists(), "a binary that could not be read was run"

    supervisor.restart(timeout=1.0)

    assert _ran_within(marker, 30.0), "the retried restart started nothing"
    assert supervisor.restart_count == 1
    assert supervisor.refused_restarts == 0
    assert supervisor.restart_refusal == ""
    assert supervisor.restart_exhausted


def test_a_binary_that_stays_unusable_is_not_retried_for_ever(
    tmp_path: Path,
) -> None:
    """Refused attempts stop after a bound, and none of them ran anything.

    Mutation check: with the heartbeat asking only whether a restart has
    started a process, a binary that never passes its check is hashed on
    every tick for as long as the daemon runs, and the loop below fails its
    own bound. Restoring the bound passes.
    """
    launcher, marker = _launcher(tmp_path)
    never_passes = ResolvedBinary(
        path=launcher, source=BinarySource.OPERATOR_SETTING, sha256="0" * 64
    )
    supervisor = _supervisor(never_passes, tmp_path)
    previous = active_supervisor()
    set_active_supervisor(supervisor)
    try:
        ticks = 0
        while not supervisor.restart_exhausted:
            _qdrant_liveness_tick()
            ticks += 1
            assert ticks <= 20, "refused restarts were never given up on"
        attempted = supervisor.refused_restarts

        _qdrant_liveness_tick()

        assert supervisor.refused_restarts == attempted == ticks
        assert supervisor.restart_count == 0
        assert EnvVar.QDRANT_BINARY_SHA256.value in supervisor.restart_refusal
        assert not marker.exists(), "a binary that failed its check was run"
    finally:
        set_active_supervisor(previous)
        assert supervisor.stop(timeout=10.0)


def test_a_dead_server_is_reported_with_its_cause_and_both_commands(
    supervised: tuple[QdrantSupervisor, Path, Path],
) -> None:
    """The readiness row says why the restart started nothing, and what to run.

    The daemon restarts a dead server once on its own, so a server still
    reported dead needs a new daemon: the remedy is a stop and then a start,
    and one command alone would leave the operator where they began.

    Mutation check: with the refusal no longer carried in the runtime state,
    the row names no cause and the ``cannot be read`` assertion fails; with
    the remedy dropped from the row, the ``server stop`` assertion fails.
    Restoring each passes.
    """
    supervisor, launcher, _marker = supervised
    with unreadable(launcher):
        _qdrant_liveness_tick()
    assert supervisor.refused_restarts == 1, "premise: the restart was refused"

    with managed_env(
        **{
            EnvVar.QDRANT_BINARY.value: str(launcher),
            EnvVar.QDRANT_BINARY_SHA256.value: file_sha256(launcher),
            EnvVar.LOCAL_ONLY.value: None,
            EnvVar.QDRANT_SERVER.value: None,
            EnvVar.QDRANT_URL.value: None,
        }
    ):
        report = compute_readiness(
            compute=ComputeReport(capability=ComputeCapability.READY)
        )

    row = report.dimension("qdrant")
    assert row is not None
    assert row.status == ReadinessStatus.NOT_READY, row.detail
    assert "is not live" in row.detail
    assert "cannot be read" in row.detail
    assert "`vaultspec-rag server stop`, then `vaultspec-rag server start`" in (
        row.detail
    )
