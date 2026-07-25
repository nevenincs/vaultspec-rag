"""Indexer pools must not outlive a hard-killed owner.

Exercises the real thing: a driver process builds a pool through the
production constructor, and the test kills that process the way an operator
stop or a crash does - an unblockable kill that runs no ``atexit`` handler and
unwinds no ``with`` block, so the pool's own shutdown path never executes. Every
worker must still be gone afterwards.

Without the guard this is exactly how a full worker cohort is stranded: pool
workers park in ``call_queue.get()``, every worker holds the queue's write
handle so the read end never reaches EOF, and Windows neither reaps orphans
nor tears down a process group when a parent dies.
"""

from __future__ import annotations

import contextlib
import os
import pathlib
import subprocess
import sys
import time

import psutil
import pytest

from vaultspec_rag.indexer import _pool_guard

_WORKERS = 4
_READY_TIMEOUT_SECONDS = 120.0
_EXIT_TIMEOUT_SECONDS = 60.0

# Built through the production constructor, so the workers carry whatever guard
# production gives them - the test cannot pass by assembling a safer pool than
# the indexer actually uses.
_DRIVER = """\
import multiprocessing
import os
import sys
import time

from vaultspec_rag.indexer._pool_guard import spawn_pool


def _occupy(_index: int) -> int:
    # Hold the slot so the pool is forced to start every worker rather than
    # replaying one warm worker across the whole batch.
    time.sleep(6)
    return os.getpid()


def main() -> None:
    workers = int(sys.argv[1])
    ctx = multiprocessing.get_context("spawn")
    with spawn_pool(max_workers=workers, mp_context=ctx) as pool:
        pids = sorted(set(pool.map(_occupy, range(workers))))
        print("PIDS=" + ",".join(str(pid) for pid in pids), flush=True)
        print("READY", flush=True)
        # Park with the pool idle but alive, which is the state a mid-index
        # daemon is in when the stop verb reaches it.
        time.sleep(600)


if __name__ == "__main__":
    main()
"""


def _driver_environment() -> dict[str, str]:
    """Point the driver at the same source tree this test imported."""
    source_root = pathlib.Path(_pool_guard.__file__).resolve().parents[2]
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        os.pathsep.join([str(source_root), existing]) if existing else str(source_root)
    )
    return env


def _read_worker_pids(proc: subprocess.Popen[str]) -> list[int]:
    """Collect the worker pids the driver reports, up to its READY line."""
    assert proc.stdout is not None
    pids: list[int] = []
    deadline = time.monotonic() + _READY_TIMEOUT_SECONDS
    for line in proc.stdout:
        stripped = line.strip()
        if stripped.startswith("PIDS="):
            pids = [
                int(raw) for raw in stripped.removeprefix("PIDS=").split(",") if raw
            ]
        elif stripped == "READY":
            return pids
        if time.monotonic() > deadline:
            raise AssertionError("driver did not signal READY in time")
    stderr = proc.stderr.read() if proc.stderr is not None else ""
    raise AssertionError(f"driver exited before READY; stderr:\n{stderr}")


def _survivors(pids: list[int], timeout: float) -> list[int]:
    """Wait up to *timeout* for every pid to disappear; return what is left."""
    deadline = time.monotonic() + timeout
    alive = [pid for pid in pids if psutil.pid_exists(pid)]
    while alive and time.monotonic() < deadline:
        time.sleep(0.1)
        alive = [pid for pid in alive if psutil.pid_exists(pid)]
    return alive


def _reap(proc: subprocess.Popen[str], pids: list[int]) -> None:
    """Leave nothing behind when the assertions fail."""
    if proc.poll() is None:
        proc.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=10)
    for pid in pids:
        with contextlib.suppress(psutil.Error):
            psutil.Process(pid).kill()


@pytest.mark.robustness
def test_pool_workers_do_not_survive_a_hard_killed_owner(
    tmp_path: pathlib.Path,
) -> None:
    driver_path = tmp_path / "pool_driver.py"
    driver_path.write_text(_DRIVER, encoding="utf-8")

    proc = subprocess.Popen(
        [sys.executable, str(driver_path), str(_WORKERS)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_driver_environment(),
    )
    worker_pids: list[int] = []
    try:
        worker_pids = _read_worker_pids(proc)
        # Guards the negative below: a run that never started its workers would
        # otherwise "prove" the absence of orphans.
        assert len(worker_pids) == _WORKERS
        assert all(psutil.pid_exists(pid) for pid in worker_pids)

        # SIGKILL / TerminateProcess: the owner gets no chance to shut the pool
        # down, which is what the Windows service stop verb escalates to.
        proc.kill()
        proc.wait(timeout=_EXIT_TIMEOUT_SECONDS)

        stranded = _survivors(worker_pids, _EXIT_TIMEOUT_SECONDS)
        assert stranded == [], f"pool workers outlived their owner: {stranded}"
    finally:
        _reap(proc, worker_pids)
