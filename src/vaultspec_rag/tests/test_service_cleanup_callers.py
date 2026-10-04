"""Recorded-identity cleanup in start and status retains a successor pointer."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from ..cli import _service_start as service_start
from ..cli import _status_render as status_render
from ..operator_state._service import ServiceLifecycle
from ..serviceclient import _discovery as discovery
from .test_service_stop_port import (
    _starting_process,
)
from .test_service_stop_port import (
    isolated_stop_status as isolated_stop_status,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize("caller", ["status", "attach", "start_died"])
def test_recorded_dead_process_cleanup_preserves_a_successor(
    isolated_stop_status: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caller: str,
) -> None:
    """Mutation proved: dropping the caller's expected identity loses discovery."""
    with _starting_process([]) as dead:
        dead_pid = dead.pid
    assert dead.poll() is not None
    old: dict[str, object] = {"pid": dead_pid, "port": 8766}
    successor = {"pid": 99_999_999, "port": 8767}
    discovery._replace_service_status(successor)

    if caller == "status":
        signals = status_render._evaluate_service_signals(old)
        assert signals.state is ServiceLifecycle.CRASHED_PID_DEAD
    elif caller == "attach":
        # Stage the already-read old snapshot; all subsequent process probes
        # and the locked deletion use the actual dead child and real record.
        def old_snapshot() -> dict[str, object]:
            return old

        monkeypatch.setattr(service_start, "read_service_status", old_snapshot)
        assert service_start._existing_service_running() is None
    else:
        failure = service_start._fail_start_died(
            dead_pid, 8766, tmp_path / "absent.log", True
        )
        assert failure.exit_code == 1
        assert json.loads(capsys.readouterr().out)["error"] == "start_died"

    assert isolated_stop_status.exists(), "stale caller erased successor discovery"
    assert json.loads(isolated_stop_status.read_text(encoding="utf-8")) == successor
