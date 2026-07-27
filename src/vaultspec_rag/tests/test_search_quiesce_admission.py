"""Search-admission quiesce gating for the GPU section (no GPU required)."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, cast

import pytest

from ..job_control import QuiesceGate
from ..search import VaultSearcher

if TYPE_CHECKING:
    from pathlib import Path

    from ..embeddings import EmbeddingModel
    from ..store_runtime import VaultStore

pytestmark = [pytest.mark.unit]

_THREAD_TIMEOUT_SECONDS = 5.0
_PARK_OBSERVE_SECONDS = 0.5


def _make_searcher(
    root: Path,
    *,
    gpu_lock: threading.Lock | None,
    quiesce_gate: QuiesceGate | None,
) -> VaultSearcher:
    """Build a searcher through the real constructor with inert GPU deps.

    ``_gpu_section`` never touches the model or the store, so sentinels are
    sufficient and keep the test CPU-only.
    """
    return VaultSearcher(
        root,
        cast("EmbeddingModel", object()),
        cast("VaultStore", object()),
        gpu_lock=gpu_lock,
        quiesce_gate=quiesce_gate,
    )


def _join_thread(thread: threading.Thread) -> None:
    """Join a test worker and fail with a bounded diagnostic if it is stuck."""
    thread.join(timeout=_THREAD_TIMEOUT_SECONDS)
    assert not thread.is_alive(), f"worker {thread.name!r} did not stop"


def test_gpu_section_admission_blocks_until_gate_resumes(tmp_path: Path) -> None:
    """A paused gate parks GPU-section entry even with no GPU lock configured.

    Guard: the bounded join is mandatory so a broken-open gate (entry proceeds
    despite pause) fails the still-alive assertion instead of hanging. The
    mutation that proves red is dropping the gate wait from ``_gpu_section``.
    """
    gate = QuiesceGate()
    searcher = _make_searcher(tmp_path, gpu_lock=None, quiesce_gate=gate)
    reached = threading.Event()
    finished: list[str] = []
    gate.pause()

    def run() -> None:
        reached.set()
        with searcher._gpu_section():
            pass
        finished.append("returned")

    worker = threading.Thread(target=run, name="search-admission-worker")
    worker.start()
    # The gate must reopen even on a red assertion, or the parked non-daemon
    # worker outlives the test and hangs the whole suite at interpreter exit.
    try:
        assert reached.wait(timeout=_THREAD_TIMEOUT_SECONDS)
        worker.join(timeout=_PARK_OBSERVE_SECONDS)
        assert worker.is_alive(), "search admission did not park at the paused gate"
        assert finished == []
    finally:
        gate.resume()
    _join_thread(worker)
    assert finished == ["returned"]


def test_admission_wait_parks_before_acquiring_gpu_lock(tmp_path: Path) -> None:
    """A quiesced entrant must not hold the GPU lock while parked.

    Guard: while the worker is parked at the gate, the shared GPU lock must
    remain free for tenants already past admission. The mutation that proves
    red is moving the gate wait after the ``gpu_lock`` acquire.
    """
    gate = QuiesceGate()
    gpu_lock = threading.Lock()
    searcher = _make_searcher(tmp_path, gpu_lock=gpu_lock, quiesce_gate=gate)
    reached = threading.Event()
    finished: list[str] = []
    gate.pause()

    def run() -> None:
        reached.set()
        with searcher._gpu_section():
            pass
        finished.append("returned")

    worker = threading.Thread(target=run, name="search-admission-lock-worker")
    worker.start()
    # The gate must reopen even on a red assertion, or the parked non-daemon
    # worker outlives the test and hangs the whole suite at interpreter exit.
    try:
        assert reached.wait(timeout=_THREAD_TIMEOUT_SECONDS)
        worker.join(timeout=_PARK_OBSERVE_SECONDS)
        assert worker.is_alive(), "search admission did not park at the paused gate"
        assert gpu_lock.acquire(blocking=False), (
            "a parked entrant is holding the GPU lock; the gate wait must "
            "complete before the lock is acquired"
        )
        gpu_lock.release()
    finally:
        gate.resume()
    _join_thread(worker)
    assert finished == ["returned"]


def test_gateless_searcher_admission_is_unchanged(tmp_path: Path) -> None:
    """Without an injected gate the GPU section admits immediately."""
    searcher = _make_searcher(tmp_path, gpu_lock=None, quiesce_gate=None)
    with searcher._gpu_section():
        pass
