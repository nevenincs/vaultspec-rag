"""Adversarial singleton verification (acceptance gate).

No mocks. The lock race is a REAL multi-process race - N separate processes
(spawn) race to acquire the machine lock and exactly one must win. The
attach/spawn cases drive the decision under injected adversarial holders
(foreign port holder, dead-owner orphan, unhealthy/corrupt qdrant) and assert
the policy never spawns a competitor and always names the cause. None of
these need the GPU.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ProcessPoolExecutor
from typing import TYPE_CHECKING

import pytest

from ..._machine_lock import (
    acquire_machine_lock,
    machine_lock_live_holder,
)
from ...config._settings import reset_config
from ...config._types import EnvVar
from ...qdrant_runtime._resolve import (
    QdrantEndpointProbe,
    QdrantIdentity,
    decide_qdrant_action,
    pid_start_time,
)
from ._machine_lock_holder import spawn_foreign_machine_lock_holder

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_STORAGE_ENV = EnvVar.QDRANT_STORAGE_DIR.value
_VERSION = "1.18.2"
_STORAGE = "/srv/storage"


def _race_worker(storage_dir: str) -> int:
    """Acquire the machine lock; return this process's pid on win, else 0.

    Top-level (picklable) so it survives the spawn start method. The winner
    holds the OS lock for its whole process lifetime (the open fd lives in the
    worker until the pool shuts down), so every loser - whenever it runs - sees
    the lock held and fails. No timing/sleep dependency.

    Returning the pid rather than a bare bool lets the caller count distinct
    WINNING PROCESSES. A ProcessPoolExecutor is free to run several tasks in one
    worker; a worker that already holds the lock re-acquires it through the
    same-process re-entrancy path and would report a win for every task it runs,
    so a True-count overcounts. Distinct winning pids cannot: one OS-lock holder
    means one pid, no matter how the pool schedules the tasks onto workers.
    """
    os.environ[_STORAGE_ENV] = storage_dir
    reset_config()
    acquired, _holder = acquire_machine_lock()
    return os.getpid() if acquired else 0


class TestConcurrentStartRace:
    def test_n_concurrent_acquires_yield_exactly_one_winner(
        self, isolated_lock: Path
    ) -> None:
        storage = str(isolated_lock.parent / "storage")
        workers = 8
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_race_worker, [storage] * workers))
        winners = {pid for pid in results if pid}
        assert len(winners) == 1, f"expected exactly one winning process, got {results}"

    def test_n_concurrent_acquires_over_dead_holder_yield_one_winner(
        self, isolated_lock: Path
    ) -> None:
        # The orphan-recovery path: a lock file left by a DEAD holder carries no
        # OS lock, so N concurrent starts racing over it must still converge to
        # exactly one winner (the file content is ignored; the OS lock is the
        # sole gate). Covers the reclaim race a fresh-lock race cannot.
        isolated_lock.parent.mkdir(parents=True, exist_ok=True)
        isolated_lock.write_text(json.dumps({"pid": 2_000_000_000}), encoding="utf-8")
        storage = str(isolated_lock.parent / "storage")
        workers = 8
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_race_worker, [storage] * workers))
        winners = {pid for pid in results if pid}
        assert len(winners) == 1, f"expected exactly one winning process, got {results}"


class TestInjectedHolderNeverYieldsCompetitor:
    def test_foreign_port_holder_is_refused_not_competed(self) -> None:
        # A listening holder with no managed identity: never spawn onto the
        # shared single-writer storage.
        probe = QdrantEndpointProbe(listening=True, ready=True, version=_VERSION)
        action, reason = decide_qdrant_action(
            probe,
            None,
            expected_port=8765,
            expected_version=_VERSION,
            expected_storage=_STORAGE,
        )
        assert action == "refuse"
        assert "competitor" in reason or "non-managed" in reason

    def test_injected_dead_owner_orphan_is_reaped_not_competed(self) -> None:
        probe = QdrantEndpointProbe(listening=True, ready=False, version="")
        identity = QdrantIdentity(
            storage_path=_STORAGE,
            version=_VERSION,
            owner_pid=2_000_000_000,
            http_port=8765,
            qdrant_pid=2_000_000_001,
        )
        action, _reason = decide_qdrant_action(
            probe,
            identity,
            expected_port=8765,
            expected_version=_VERSION,
            expected_storage=_STORAGE,
        )
        assert action == "reap_then_spawn"

    def test_live_foreign_machine_lock_holder_fast_fails(
        self, isolated_lock: Path
    ) -> None:
        # A live foreign holder of the OS lock: a second acquire from this
        # process must fast-fail, never displace it.
        storage = os.environ[_STORAGE_ENV]
        foreign_holder = spawn_foreign_machine_lock_holder(storage)
        holder_pid = foreign_holder.holder_pid
        try:
            assert isolated_lock.exists()
            assert foreign_holder.launcher_pid != holder_pid
            acquired, holder = acquire_machine_lock()
            assert acquired is False
            assert holder == holder_pid
            assert machine_lock_live_holder() == holder_pid
        finally:
            evidence = foreign_holder.stop()
        # The real holder releases first while the launcher is deliberately
        # still alive; only then may cleanup let the launcher exit.
        assert evidence.lock_released is True
        assert evidence.launcher_alive_at_release is True
        assert machine_lock_live_holder() == 0


class TestUnhealthyOrCorruptHolderRefusedWithCause:
    def test_unhealthy_holder_refused_with_named_cause(self) -> None:
        probe = QdrantEndpointProbe(listening=True, ready=False, version=_VERSION)
        identity = QdrantIdentity(
            storage_path=_STORAGE,
            version=_VERSION,
            owner_pid=os.getpid(),
            http_port=8765,
            qdrant_pid=os.getpid(),
            owner_start_time=pid_start_time(os.getpid()),
        )
        action, reason = decide_qdrant_action(
            probe,
            identity,
            expected_port=8765,
            expected_version=_VERSION,
            expected_storage=_STORAGE,
        )
        assert action == "refuse"
        assert "ready" in reason

    def test_version_mismatch_holder_refused_with_named_cause(self) -> None:
        probe = QdrantEndpointProbe(listening=True, ready=True, version="0.0.1")
        identity = QdrantIdentity(
            storage_path=_STORAGE,
            version=_VERSION,
            owner_pid=os.getpid(),
            http_port=8765,
            qdrant_pid=os.getpid(),
            owner_start_time=pid_start_time(os.getpid()),
        )
        action, reason = decide_qdrant_action(
            probe,
            identity,
            expected_port=8765,
            expected_version=_VERSION,
            expected_storage=_STORAGE,
        )
        assert action == "refuse"
        assert "version" in reason
