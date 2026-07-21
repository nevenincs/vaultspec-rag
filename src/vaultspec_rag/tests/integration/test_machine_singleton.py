"""Machine-scoped service-lock tests (plan W03.P05).

No mocks, no GPU: the lock is an OS advisory lock, so a "foreign holder" is a
real subprocess that actually holds the lock (not merely a pid written to the
file). A dead or empty lock file carries no OS lock, so acquiring over it
succeeds - the crash-safe property (the OS releases a dead holder's lock).
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from ...cli._process import (
    acquire_machine_lock,
    machine_lock_live_holder,
    release_machine_lock,
)
from ...config import EnvVar
from ._machine_lock_holder import spawn_foreign_machine_lock_holder

if TYPE_CHECKING:
    from pathlib import Path


class TestMachineLock:
    def test_acquire_release_then_reacquire(self, isolated_lock: Path) -> None:
        acquired, holder = acquire_machine_lock()
        assert acquired is True
        assert holder == os.getpid()
        assert isolated_lock.exists()
        release_machine_lock()
        # The file persists (its existence is not the authority); releasing
        # frees the OS lock, so the lock is immediately re-acquirable.
        reacquired, holder2 = acquire_machine_lock()
        assert reacquired is True
        assert holder2 == os.getpid()
        release_machine_lock()

    def test_second_acquire_refused_while_foreign_holder_alive(
        self, isolated_lock: Path
    ) -> None:
        storage = os.environ[EnvVar.QDRANT_STORAGE_DIR.value]
        foreign_holder = spawn_foreign_machine_lock_holder(storage)
        holder_pid = foreign_holder.holder_pid
        try:
            assert isolated_lock.exists()
            assert foreign_holder.launcher_pid != holder_pid
            acquired, holder = acquire_machine_lock()
            assert acquired is False
            assert holder == holder_pid
            # The advisory-lock probe agrees the holder is live.
            assert machine_lock_live_holder() == holder_pid
            # Reproduce the Windows launcher/holder split: awaiting the
            # launcher is not evidence that the actual lock holder exited.
            foreign_holder.terminate_launcher()
            assert machine_lock_live_holder() == holder_pid
        finally:
            evidence = foreign_holder.stop()
        assert evidence.lock_released is True
        assert evidence.launcher_alive_at_release is False
        assert machine_lock_live_holder() == 0

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
        foreign_holder = spawn_foreign_machine_lock_holder(storage)
        holder_pid = foreign_holder.holder_pid
        try:
            assert isolated_lock.exists()
            assert foreign_holder.launcher_pid != holder_pid
            release_machine_lock()  # we are not the holder
            assert machine_lock_live_holder() == holder_pid
        finally:
            evidence = foreign_holder.stop()
        assert evidence.lock_released is True
        assert evidence.launcher_alive_at_release is True
        assert machine_lock_live_holder() == 0
