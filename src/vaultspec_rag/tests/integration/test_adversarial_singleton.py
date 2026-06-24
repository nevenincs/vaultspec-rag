"""Adversarial singleton verification (plan W04.P07 / acceptance gate).

No mocks. S22 is a REAL multi-process race - N separate processes (spawn) race
to acquire the machine lock and exactly one must win. S23/S24 drive the
attach/spawn decision under injected adversarial holders (foreign port holder,
dead-owner orphan, unhealthy/corrupt qdrant) and assert the policy never spawns
a competitor and always names the cause. None of these need the GPU.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from typing import TYPE_CHECKING

import pytest

from ..._machine_lock import (
    acquire_machine_lock,
    machine_lock_live_holder,
    machine_lock_path,
)
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


def _race_worker(storage_dir: str) -> bool:
    """Acquire the machine lock in a fresh process; report whether won.

    Top-level (picklable) so it survives the spawn start method. The winner
    holds the OS lock for its whole process lifetime (the open fd lives in the
    worker until the pool shuts down), so every loser - whenever it runs - sees
    the lock held and fails. No timing/sleep dependency.
    """
    os.environ[_STORAGE_ENV] = storage_dir
    reset_config()
    acquired, _holder = acquire_machine_lock()
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

    def test_n_concurrent_acquires_over_dead_holder_yield_one_winner(
        self, isolated_lock: Path
    ) -> None:
        # The orphan-recovery path: a lock file left by a DEAD holder carries no
        # OS lock, so N concurrent starts racing over it must still converge to
        # exactly one winner (the file content is ignored; the OS lock is the
        # sole gate). Covers the reclaim race a fresh-lock race cannot.
        isolated_lock.parent.mkdir(parents=True, exist_ok=True)
        isolated_lock.write_text(
            json.dumps({"pid": 2_000_000_000}), encoding="utf-8"
        )
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
        # A live foreign holder of the OS lock: a second acquire from this
        # process must fast-fail, never displace it.
        storage = os.environ[_STORAGE_ENV]
        proc, holder_pid = _spawn_lock_holder(storage)
        try:
            assert isolated_lock.exists()
            acquired, holder = acquire_machine_lock()
            assert acquired is False
            assert holder == holder_pid
            assert machine_lock_live_holder() == holder_pid
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
