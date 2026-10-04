"""Machine ownership remains uncertain when its actual anchor cannot be inspected."""

from __future__ import annotations

import errno
from pathlib import Path

import pytest

from .. import _anchor_claim as anchor_claim
from .. import _machine_lock as machine_lock
from ..serviceclient import _discovery as discovery
from .test_service_stop_port import (
    _starting_process,
)
from .test_service_stop_port import (
    isolated_stop_status as isolated_stop_status,
)

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize(
    "boundary",
    ["stat_permission", "stat_io", "open_permission", "open_io", "open_not_directory"],
)
def test_unreadable_machine_lock_is_degraded_instead_of_absent(
    isolated_stop_status: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    """Mutation proved: treating a real inspection fault as absence fails."""
    del isolated_stop_status
    with _starting_process(
        ["-m", "vaultspec_rag.server", "--port", "8766"], hold_machine_lock=True
    ) as holder:
        target = machine_lock.machine_lock_path()
        original = target.read_bytes()
        failure = (
            PermissionError(errno.EACCES, "machine anchor access refused")
            if boundary.endswith("permission")
            else OSError(errno.EIO, "machine anchor inspection failed")
        )
        if boundary == "open_not_directory":
            failure = NotADirectoryError(
                errno.ENOTDIR, "machine anchor path unavailable"
            )
        if boundary.startswith("stat"):
            actual_stat = Path.stat

            def refused_stat(path: Path, *, follow_symlinks: bool = True):
                if path == target:
                    raise failure
                return actual_stat(path, follow_symlinks=follow_symlinks)

            monkeypatch.setattr(Path, "stat", refused_stat)
        else:
            actual_open = anchor_claim._open_anchor

            def refused_open(path: Path, *, create: bool, shared: bool) -> int:
                if path == target:
                    raise failure
                return actual_open(path, create=create, shared=shared)

            monkeypatch.setattr(anchor_claim, "_open_anchor", refused_open)

        resolution = discovery.resolve_machine_service()

        assert resolution.state == discovery.DISCOVERY_STATE_DEGRADED, (
            "uncertain machine lock was reported absent"
        )
        assert resolution.reason == discovery.DISCOVERY_REASON_PROBE_FAILED
        with pytest.raises(type(failure)):
            machine_lock.probe_machine_lock()
        assert holder.poll() is None
        assert target.read_bytes() == original


def test_a_confirmed_missing_machine_anchor_is_absent(
    isolated_stop_status: Path,
) -> None:
    del isolated_stop_status
    target = machine_lock.machine_lock_path()
    assert not target.exists()

    probe = machine_lock.probe_machine_lock()

    assert not probe.held
    assert probe.holder_pid == 0
    assert not target.exists(), "a read-only missing probe created its anchor"
