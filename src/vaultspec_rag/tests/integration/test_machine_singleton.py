"""Machine-scoped service-lock tests (plan W03.P05).

No mocks, no GPU: the lock is exercised through the real filesystem with the
storage dir relocated via the genuine env knob; a real spawned subprocess
stands in for a live foreign holder, and a dead pid stands in for a stale lock.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from ...cli._process import (
    acquire_machine_lock,
    machine_lock_path,
    release_machine_lock,
)
from ...config import EnvVar, reset_config

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_SLEEP = "import time; time.sleep(60)"


@pytest.fixture
def isolated_lock(tmp_path: Path) -> Iterator[Path]:
    """Relocate the machine lock under a temp storage dir via the env knob."""
    key = EnvVar.QDRANT_STORAGE_DIR.value
    previous = os.environ.get(key)
    os.environ[key] = str(tmp_path / "qdrant-server" / "storage")
    reset_config()
    try:
        yield machine_lock_path()
    finally:
        release_machine_lock()
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous
        reset_config()


class TestMachineLock:
    def test_acquire_then_release(self, isolated_lock: Path) -> None:
        acquired, holder = acquire_machine_lock()
        assert acquired is True
        assert holder == os.getpid()
        assert isolated_lock.exists()
        release_machine_lock()
        assert not isolated_lock.exists()

    def test_second_acquire_refused_while_foreign_holder_alive(
        self, isolated_lock: Path
    ) -> None:
        proc = subprocess.Popen([sys.executable, "-c", _SLEEP])
        try:
            isolated_lock.parent.mkdir(parents=True, exist_ok=True)
            isolated_lock.write_text(json.dumps({"pid": proc.pid}), encoding="utf-8")
            acquired, holder = acquire_machine_lock()
            assert acquired is False
            assert holder == proc.pid
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

    def test_stale_lock_from_dead_holder_is_reclaimed(
        self, isolated_lock: Path
    ) -> None:
        isolated_lock.parent.mkdir(parents=True, exist_ok=True)
        isolated_lock.write_text(json.dumps({"pid": 2_000_000_000}), encoding="utf-8")
        acquired, holder = acquire_machine_lock()
        assert acquired is True
        assert holder == os.getpid()
