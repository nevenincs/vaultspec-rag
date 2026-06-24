"""Adversarial singleton verification (plan W04.P07 / acceptance gate).

No mocks. S22 is a REAL multi-process race - N separate processes (spawn) race
to acquire the machine lock and exactly one must win. S23/S24 drive the
attach/spawn decision under injected adversarial holders (foreign port holder,
dead-owner orphan, unhealthy/corrupt qdrant) and assert the policy never spawns
a competitor and always names the cause. None of these need the GPU.
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ProcessPoolExecutor
from typing import TYPE_CHECKING

import pytest

from ..._machine_lock import acquire_machine_lock, machine_lock_path
from ...config import EnvVar, reset_config
from ...qdrant_runtime._resolve import (
    QdrantEndpointProbe,
    QdrantIdentity,
    decide_qdrant_action,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_STORAGE_ENV = EnvVar.QDRANT_STORAGE_DIR.value
_VERSION = "1.18.2"
_STORAGE = "/srv/storage"


def _race_worker(storage_dir: str) -> bool:
    """Acquire the machine lock in a fresh process; hold briefly if won.

    Top-level (picklable) so it survives the spawn start method. The winner
    sleeps so its pid stays alive across the race window - a winner that exited
    immediately would look like a stale (dead) holder and let a peer reclaim.
    """
    os.environ[_STORAGE_ENV] = storage_dir
    reset_config()
    acquired, _holder = acquire_machine_lock()
    if acquired:
        time.sleep(2.0)
    return acquired


@pytest.fixture
def isolated_lock(tmp_path: Path) -> Iterator[Path]:
    previous = os.environ.get(_STORAGE_ENV)
    os.environ[_STORAGE_ENV] = str(tmp_path / "qdrant-server" / "storage")
    reset_config()
    try:
        yield machine_lock_path()
    finally:
        # The winning child holds the lock; remove the file directly (the
        # parent is not the holder, so release_machine_lock would no-op).
        path = machine_lock_path()
        if path.exists():
            path.unlink()
        if previous is None:
            os.environ.pop(_STORAGE_ENV, None)
        else:
            os.environ[_STORAGE_ENV] = previous
        reset_config()


class TestConcurrentStartRace:
    def test_n_concurrent_acquires_yield_exactly_one_winner(
        self, isolated_lock: Path
    ) -> None:
        storage = str(isolated_lock.parent / "storage")
        workers = 8
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_race_worker, [storage] * workers))
        assert sum(results) == 1, f"expected exactly one winner, got {results}"


class TestInjectedHolderNeverYieldsCompetitor:
    def test_foreign_port_holder_is_refused_not_competed(self) -> None:
        # A listening holder with no managed identity: never spawn onto the
        # shared single-writer storage.
        probe = QdrantEndpointProbe(listening=True, ready=True, version=_VERSION)
        action, reason = decide_qdrant_action(
            probe, None, expected_version=_VERSION, expected_storage=_STORAGE
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
            probe, identity, expected_version=_VERSION, expected_storage=_STORAGE
        )
        assert action == "reap_then_spawn"

    def test_live_foreign_machine_lock_holder_fast_fails(
        self, isolated_lock: Path
    ) -> None:
        # A live foreign holder injected into the machine lock: a second
        # acquire from this process must fast-fail, never displace it.
        import json
        import subprocess
        import sys

        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"]
        )
        try:
            isolated_lock.parent.mkdir(parents=True, exist_ok=True)
            isolated_lock.write_text(
                json.dumps({"pid": proc.pid}), encoding="utf-8"
            )
            acquired, holder = acquire_machine_lock()
            assert acquired is False
            assert holder == proc.pid
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)


class TestUnhealthyOrCorruptHolderRefusedWithCause:
    def test_unhealthy_holder_refused_with_named_cause(self) -> None:
        probe = QdrantEndpointProbe(listening=True, ready=False, version=_VERSION)
        identity = QdrantIdentity(
            storage_path=_STORAGE,
            version=_VERSION,
            owner_pid=os.getpid(),
            http_port=8765,
            qdrant_pid=os.getpid(),
        )
        action, reason = decide_qdrant_action(
            probe, identity, expected_version=_VERSION, expected_storage=_STORAGE
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
        )
        action, reason = decide_qdrant_action(
            probe, identity, expected_version=_VERSION, expected_storage=_STORAGE
        )
        assert action == "refuse"
        assert "version" in reason
