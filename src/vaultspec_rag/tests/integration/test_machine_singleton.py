"""Machine-scoped service-lock tests (plan W03.P05).

No mocks, no GPU: the lock is an OS advisory lock, so a "foreign holder" is a
real subprocess that actually holds the lock (not merely a pid written to the
file). A dead or empty lock file carries no OS lock, so acquiring over it
succeeds - the crash-safe property (the OS releases a dead holder's lock).
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
    machine_lock_live_holder,
    machine_lock_path,
    release_machine_lock,
)
from ...config import EnvVar, reset_config

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# A child that acquires the real machine lock, announces its own pid, and holds
# it. It announces os.getpid() (not the Popen pid) because a launcher/uv shim
# may spawn the real interpreter as a grandchild.
_HOLD = (
    "import os,sys,time;"
    "os.environ['VAULTSPEC_RAG_QDRANT_STORAGE_DIR']=sys.argv[1];"
    "from vaultspec_rag.config import reset_config; reset_config();"
    "from vaultspec_rag._machine_lock import acquire_machine_lock;"
    "ok,_=acquire_machine_lock();"
    "print('ACQUIRED:'+str(os.getpid()) if ok else 'FAILED', flush=True);"
    "time.sleep(60)"
)


def _spawn_lock_holder(storage_dir: str) -> tuple[subprocess.Popen[str], int]:
    """Spawn a child that holds the machine lock; return (proc, holder pid)."""
    proc = subprocess.Popen(
        [sys.executable, "-c", _HOLD, storage_dir],
        stdout=subprocess.PIPE,
        text=True,
    )
    line = proc.stdout.readline() if proc.stdout is not None else ""
    if not line.startswith("ACQUIRED:"):
        proc.kill()
        proc.wait(timeout=5)
        msg = f"lock-holder child failed to acquire: {line!r}"
        raise AssertionError(msg)
    return proc, int(line.split(":", 1)[1].strip())


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
        path = machine_lock_path()
        if path.exists():
            path.unlink()
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
        storage = os.environ[EnvVar.QDRANT_STORAGE_DIR.value]
        proc, holder_pid = _spawn_lock_holder(storage)
        try:
            assert isolated_lock.exists()
            acquired, holder = acquire_machine_lock()
            assert acquired is False
            assert holder == holder_pid
            # The advisory-lock probe agrees the holder is live.
            assert machine_lock_live_holder() == holder_pid
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

    def test_dead_holder_lock_is_acquirable(self, isolated_lock: Path) -> None:
        # A lock file left by a dead holder carries no OS lock (the OS released
        # it on death), so acquiring over it succeeds - no manual reclaim.
        isolated_lock.parent.mkdir(parents=True, exist_ok=True)
        isolated_lock.write_text(json.dumps({"pid": 2_000_000_000}), encoding="utf-8")
        acquired, holder = acquire_machine_lock()
        assert acquired is True
        assert holder == os.getpid()

    def test_empty_lock_file_is_not_a_deadlock(self, isolated_lock: Path) -> None:
        # An empty/corrupt lock file from a crash carries no OS lock either, so
        # it is acquirable - never a permanent machine-wide deadlock.
        isolated_lock.parent.mkdir(parents=True, exist_ok=True)
        isolated_lock.write_text("", encoding="utf-8")
        acquired, holder = acquire_machine_lock()
        assert acquired is True
        assert holder == os.getpid()

    def test_release_is_idempotent_and_only_releases_our_lock(
        self, isolated_lock: Path
    ) -> None:
        # Releasing when we hold nothing is a no-op; a foreign holder's lock is
        # never released by our release.
        release_machine_lock()  # holds nothing - no error
        storage = os.environ[EnvVar.QDRANT_STORAGE_DIR.value]
        proc, holder_pid = _spawn_lock_holder(storage)
        try:
            assert isolated_lock.exists()
            release_machine_lock()  # we are not the holder
            assert machine_lock_live_holder() == holder_pid
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
