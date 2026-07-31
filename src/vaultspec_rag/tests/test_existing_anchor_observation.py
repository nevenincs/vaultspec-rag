"""Real no-create observations of captured service identity anchors."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest

from .._anchor_claim import AnchorOutcome, observe_existing_anchor
from .._machine_lock import (
    _probe_existing_machine_lock_holder,
    capture_pre_isolation_machine_lock,
    machine_lock_path,
)
from ..config._settings import reset_config
from ..config._types import EnvVar

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_PROCESS_TIMEOUT_SECONDS = 10.0
_HOLD_EXISTING_ANCHOR = """
import os
import sys
import time
from pathlib import Path

from vaultspec_rag._anchor_claim import (
    claim_anchor,
    record_claim_owner,
    release_anchor_claim,
)

anchor = Path(sys.argv[1])
ready_path = Path(sys.argv[2])
stop_path = Path(sys.argv[3])
claim = claim_anchor(anchor, pid_record=True, create_parent=True)
assert claim.descriptor is not None, claim
try:
    record_claim_owner(claim.descriptor)
    ready_path.write_text(str(os.getpid()), encoding="ascii")
    while not stop_path.exists():
        time.sleep(0.01)
finally:
    release_anchor_claim(claim.descriptor, pid_record=True)
"""


@contextmanager
def _relocated_machine_paths(tmp_path: Path) -> Generator[None]:
    """Point the no-argument capture facade at this test's real temp paths."""
    storage_key = EnvVar.QDRANT_STORAGE_DIR.value
    prior_storage = os.environ.get(storage_key)
    os.environ[storage_key] = str(tmp_path / "qdrant" / "storage")
    reset_config()
    try:
        yield
    finally:
        if prior_storage is None:
            os.environ.pop(storage_key, None)
        else:
            os.environ[storage_key] = prior_storage
        reset_config()


def test_deleted_existing_anchor_is_absent_and_never_recreated(tmp_path: Path) -> None:
    """Deletion before the single no-create open refuses without recreation."""
    identity_lock_path = tmp_path / "original-service.lock"
    identity_lock_path.write_text('{"pid": 123}', encoding="utf-8")
    identity_lock_path.unlink()

    observation = observe_existing_anchor(identity_lock_path, pid_record=True)

    assert observation.outcome is AnchorOutcome.ABSENT
    assert observation.descriptor is None
    assert observation.fault is None
    assert _probe_existing_machine_lock_holder(identity_lock_path) is None
    assert not identity_lock_path.exists()


def test_existing_anchor_observation_reports_an_open_fault(tmp_path: Path) -> None:
    """An existing directory is an unusable anchor, not a path to create."""
    observation = observe_existing_anchor(tmp_path, pid_record=True)

    assert observation.outcome is AnchorOutcome.UNAVAILABLE
    assert observation.descriptor is None
    assert observation.holder_pid == 0
    assert observation.fault is not None


def test_pre_isolation_machine_capture_derives_paths_without_creating(
    tmp_path: Path,
) -> None:
    """The public capture facade refuses an absent lock without creating it."""
    with _relocated_machine_paths(tmp_path):
        identity_lock_path = machine_lock_path()

        captured = capture_pre_isolation_machine_lock()

        assert captured is None
        assert not identity_lock_path.exists()


def test_existing_anchor_observation_reads_a_real_contended_owner_pid(
    tmp_path: Path,
) -> None:
    """A separate process's durable record is recovered without retention."""
    identity_lock_path = tmp_path / "original-service.lock"
    ready_path = tmp_path / "holder-ready"
    stop_path = tmp_path / "holder-stop"
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _HOLD_EXISTING_ANCHOR,
            str(identity_lock_path),
            str(ready_path),
            str(stop_path),
        ],
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + _PROCESS_TIMEOUT_SECONDS
        while not ready_path.is_file() and process.poll() is None:
            assert time.monotonic() < deadline, "real anchor holder did not start"
            time.sleep(0.01)
        assert ready_path.is_file(), "real anchor holder exited before readiness"
        expected_pid = int(ready_path.read_text(encoding="ascii"))

        observation = observe_existing_anchor(identity_lock_path, pid_record=True)

        assert observation.outcome is AnchorOutcome.CONTENDED
        assert observation.descriptor is None
        assert observation.fault is None
        assert observation.holder_pid == expected_pid
        assert _probe_existing_machine_lock_holder(identity_lock_path) == expected_pid
    finally:
        if process.poll() is None:
            stop_path.write_text("stop", encoding="ascii")
        try:
            process.wait(timeout=_PROCESS_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=_PROCESS_TIMEOUT_SECONDS)
        assert process.stderr is not None
        stderr = process.stderr.read()
        process.stderr.close()
        assert process.returncode == 0, stderr


def test_pre_isolation_machine_capture_refuses_after_root_registration(
    tmp_path: Path,
) -> None:
    """The no-argument facade cannot capture a post-root external lock."""
    with _relocated_machine_paths(tmp_path):
        identity_lock_path = machine_lock_path()
        ready_path = tmp_path / "capture-holder-ready"
        stop_path = tmp_path / "capture-holder-stop"
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                _HOLD_EXISTING_ANCHOR,
                str(identity_lock_path),
                str(ready_path),
                str(stop_path),
            ],
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + _PROCESS_TIMEOUT_SECONDS
            while not ready_path.is_file() and process.poll() is None:
                assert time.monotonic() < deadline, "real anchor holder did not start"
                time.sleep(0.01)
            assert ready_path.is_file(), "real anchor holder exited before readiness"

            assert capture_pre_isolation_machine_lock() is None
        finally:
            if process.poll() is None:
                stop_path.write_text("stop", encoding="ascii")
            try:
                process.wait(timeout=_PROCESS_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=_PROCESS_TIMEOUT_SECONDS)
            assert process.stderr is not None
            stderr = process.stderr.read()
            process.stderr.close()
            assert process.returncode == 0, stderr
