"""Benchmark: amortized cost of one managed progress publication.

One progress publish once paid a full manager-state persist - JSON
serialization, an fsync, and an atomic replace, under the manager lock -
measured at ~5.5 ms/call on a near-empty state. Publications now land in
memory and coalesce their durable write onto a time budget, so the amortized
per-publish cost must sit far below one full persist. This pins that ratio
with the real manager, a real started attempt, and the real durable writer;
it prints absolute numbers and asserts only ratios, so it holds on any
machine.

CPU and disk only: no model, no store, no service. Marked ``performance``;
invoke by file path.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import pytest

from ...job_control import RunControlToken
from ...job_manager.manager import JobManager
from ...job_manager.models import ProgressUpdate
from ...job_models import (
    JobInitiator,
    JobMode,
    JobOperation,
    JobSource,
    JobSpec,
)
from ...job_persistence import load_persisted_state, save_persisted_state
from ...service_quiesce import ServiceQuiesceController

if TYPE_CHECKING:
    from pathlib import Path

_N_PUBLISHES = 5000
_PERSIST_ROUNDS = 100


@pytest.mark.performance
async def test_progress_publish_amortized_cost(tmp_path: Path) -> None:
    state_path = tmp_path / "jobs-state.json"
    manager = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        max_nonterminal=1,
        state_path=state_path,
    )
    created = manager.create(
        JobSpec(JobOperation.INDEX, JobSource.CODE, str(tmp_path), JobMode.INCREMENTAL),
        JobInitiator("service", "reindex_codebase", str(tmp_path)),
    )
    assert created.job is not None
    job_id = created.job.id
    task = asyncio.create_task(asyncio.Event().wait())
    try:
        started = manager.start_attempt(
            job_id,
            task=task,
            control=RunControlToken(),
        )
        assert started.code == "attempt_started"

        # Baseline: the full durable persist each publish used to pay,
        # through the real writer, on this manager's real serialized state.
        baseline_state = load_persisted_state(state_path)
        baseline_path = tmp_path / "baseline-state.json"
        start = time.perf_counter()
        for _ in range(_PERSIST_ROUNDS):
            save_persisted_state(baseline_path, baseline_state)
        persist_ms = (time.perf_counter() - start) / _PERSIST_ROUNDS * 1000

        start = time.perf_counter()
        for i in range(_N_PUBLISHES):
            outcome = manager.update_progress(
                job_id,
                ProgressUpdate(1, task, "hash", completed=i, total=_N_PUBLISHES),
            )
            assert outcome.code == "progress_updated"
        publish_ms = (time.perf_counter() - start) / _N_PUBLISHES * 1000

        live = manager.get(job_id)
        assert live is not None
        assert live.progress is not None
        assert live.progress.completed == _N_PUBLISHES - 1

        print(
            f"\n[progress-publish benchmark] publishes={_N_PUBLISHES}\n"
            f"  full state persist   {persist_ms:8.4f} ms/call"
            f"  (the old per-publish price)\n"
            f"  amortized publish    {publish_ms:8.4f} ms/call\n"
            f"  speedup              {persist_ms / publish_ms:8.1f}x",
        )

        # The class fix this pins: a loop publish must not pay a per-call
        # durable write. 20x leaves headroom for a saturated machine while
        # still failing any reintroduced per-publish persist outright, since
        # that regression collapses the ratio to ~1x.
        assert publish_ms < persist_ms / 20
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
