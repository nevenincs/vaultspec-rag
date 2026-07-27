"""Cohesive unit coverage for job-management behavior."""

from __future__ import annotations

import asyncio
import inspect
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from .. import job_models
from .. import jobs as jobs_module
from ..job_control import QuiesceGate
from ..job_manager.manager import JobManager
from ..job_manager.models import JobAttemptContext, JobExecutionResult
from ..job_models import (
    JobInitiator,
    JobMode,
    JobOperation,
    JobSource,
    JobSpec,
    JobState,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


pytestmark = [pytest.mark.unit]

_TEST_PROJECT_ROOT = os.path.abspath(os.path.join(os.sep, "project"))
_TEST_PROJECT_ROOT_OTHER = os.path.abspath(os.path.join(os.sep, "other"))
_TEST_PROJECT_ROOT_DIFFERENT = os.path.abspath(os.path.join(os.sep, "different"))


class TestGpuLockWaitTelemetry:
    """Timed GPU-lock acquisition accumulates per attempt and publishes."""

    def test_timed_acquire_credits_the_active_scope(self) -> None:

        from ..job_control import gpu_lock_wait_scope, timed_gpu_lock

        lock = threading.Lock()
        lock.acquire()
        releaser = threading.Timer(0.2, lock.release)
        releaser.start()
        try:
            with gpu_lock_wait_scope() as accumulator:
                with timed_gpu_lock(lock):
                    pass
                assert accumulator.seconds >= 0.1, (
                    "the contended acquisition wait was not credited"
                )
        finally:
            releaser.cancel()
            if lock.locked():
                lock.release()

    def test_timed_acquire_without_a_scope_is_inert(self) -> None:

        from ..job_control import timed_gpu_lock

        lock = threading.Lock()
        with timed_gpu_lock(lock):
            assert lock.locked()
        assert not lock.locked()
        with timed_gpu_lock(None):
            pass

    @pytest.mark.asyncio
    async def test_lock_wait_publishes_on_the_job_record(self) -> None:
        """The attempt's lock wait lands beside the admission stamp."""
        import time as time_module

        from ..job_control import timed_gpu_lock

        manager = JobManager(max_nonterminal=2, state_path=None)
        initiator = JobInitiator("test", "gpu-wait-telemetry", None)
        created = manager.create(
            JobSpec(
                JobOperation.INDEX, JobSource.VAULT, _TEST_PROJECT_ROOT, JobMode.REBUILD
            ),
            initiator,
        )
        assert created.job is not None
        gpu_lock = threading.Lock()

        def runner(context: JobAttemptContext) -> JobExecutionResult:
            del context
            gpu_lock.acquire()
            releaser = threading.Timer(0.2, gpu_lock.release)
            releaser.start()
            try:
                with timed_gpu_lock(gpu_lock):
                    time_module.sleep(0.05)
            finally:
                releaser.cancel()
            return JobExecutionResult(summary="encoded")

        manager.bind_dispatch(created.job.id, runner)
        await manager.dispatch_async(created.job.id)
        deadline = asyncio.get_running_loop().time() + 30.0
        while True:
            job = manager.get(created.job.id)
            assert job is not None
            if job.state.is_terminal:
                break
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("telemetry job did not finish")
            await asyncio.sleep(0.01)
        assert job.state is JobState.SUCCEEDED
        waited = job.gpu_lock_wait_seconds
        assert waited is not None
        # The wait credited is the contended acquisition, not the held span.
        assert waited >= 0.1
        published = job.to_dict()
        assert published["gpu_lock_wait_seconds"] == waited
        assert "admission_acquired_at" in published


class TestQuiesceAdmissionComposition:
    """The quiesce hold gate and the encode admission slot compose safely.

    Acquisition order is one-way and fixed: the admission slot is acquired
    first (the attempt's worker limiter), and the quiesce gate is consulted
    only inside the already-admitted attempt at unprotected checkpoints. No
    code path waits on the admission slot while parked at the gate on the
    same thread, so pause-during-held-slot can park the holder but never
    deadlock the manager, and resume always reclaims.
    """

    @pytest.fixture(autouse=True)
    def _fresh_limiters(self) -> Iterator[None]:
        from .. import concurrency

        concurrency.reset_limiters()
        yield
        concurrency.reset_limiters()

    @staticmethod
    def _encode_spec(root: str) -> JobSpec:
        return JobSpec(JobOperation.INDEX, JobSource.VAULT, root, JobMode.REBUILD)

    @staticmethod
    async def _await_terminal(
        manager: JobManager,
        job_id: str,
    ) -> job_models.JobSnapshot:
        """Return the job's terminal snapshot within the convergence bound."""
        deadline = asyncio.get_running_loop().time() + 30.0
        while True:
            job = manager.get(job_id)
            assert job is not None
            if job.state.is_terminal:
                return job
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(f"job {job_id} did not converge after resume")
            await asyncio.sleep(0.01)

    @staticmethod
    async def _assert_queued_job_stays_unadmitted(
        manager: JobManager,
        job_id: str,
    ) -> None:
        """Bounded observation, not a deadlock: dispatched yet unadmitted."""
        assert (await manager.dispatch_async(job_id)).code == "attempt_started"
        await asyncio.sleep(0.5)
        waiting = manager.get(job_id)
        assert waiting is not None
        assert waiting.state is JobState.RUNNING
        assert waiting.timestamps.admission_acquired_at is None

    @pytest.mark.asyncio
    async def test_pause_during_held_slot_parks_holder_and_resume_admits_queued(
        self,
    ) -> None:
        """Pause while an encode job holds the slot is bounded, never lost.

        The holder parks at its next unprotected checkpoint WITH the slot
        still held (its admission stamp is already set - the order proof),
        the queued encode job stays honestly unadmitted, and resume lets
        the holder finish so the queued job reclaims the slot. Stubbing
        the gate out of the checkpoint makes the holder finish while
        paused and turns the parked assertion red; that is the mutation
        this guard catches.
        """

        gate = QuiesceGate()
        manager = JobManager(
            max_nonterminal=4,
            state_path=None,
            quiesce_gate=gate,
        )
        initiator = JobInitiator("test", "quiesce-composition", None)
        holder = manager.create(self._encode_spec(_TEST_PROJECT_ROOT), initiator)
        queued = manager.create(self._encode_spec(_TEST_PROJECT_ROOT_OTHER), initiator)
        assert holder.job is not None
        assert queued.job is not None

        entered = threading.Event()
        proceed = threading.Event()
        holder_done = threading.Event()

        def holding_runner(context: JobAttemptContext) -> JobExecutionResult:
            entered.set()
            assert proceed.wait(timeout=30.0)
            context.control.checkpoint()
            holder_done.set()
            return JobExecutionResult(summary="holder done")

        def queued_runner(context: JobAttemptContext) -> JobExecutionResult:
            del context
            return JobExecutionResult(summary="queued done")

        assert manager.bind_dispatch(holder.job.id, holding_runner).code == (
            "dispatch_bound"
        )
        assert manager.bind_dispatch(queued.job.id, queued_runner).code == (
            "dispatch_bound"
        )
        try:
            assert (await manager.dispatch_async(holder.job.id)).code == (
                "attempt_started"
            )
            assert await asyncio.to_thread(entered.wait, 10.0)
            # Order proof: the slot was acquired before the gate is ever
            # consulted - the holder is admitted before it can park.
            held = manager.get(holder.job.id)
            assert held is not None
            assert held.timestamps.admission_acquired_at is not None

            gate.pause()
            proceed.set()
            # The holder parks at the paused gate while keeping the slot.
            # A gate stubbed out of the checkpoint finishes here instead.
            assert not await asyncio.to_thread(holder_done.wait, 0.5), (
                "holder passed its checkpoint while the gate was paused"
            )

            # The queued encode job stays honestly unadmitted behind the
            # parked holder's slot.
            await self._assert_queued_job_stays_unadmitted(manager, queued.job.id)
        finally:
            gate.resume()
            proceed.set()

        done_holder = await self._await_terminal(manager, holder.job.id)
        done_queued = await self._await_terminal(manager, queued.job.id)
        assert done_holder.state is JobState.SUCCEEDED
        assert done_queued.state is JobState.SUCCEEDED
        # Resume reclaimed the slot: the queued job was really admitted.
        assert done_queued.timestamps.admission_acquired_at is not None

    @pytest.mark.asyncio
    async def test_exempt_paths_complete_while_slot_borrowed_and_gate_paused(
        self,
        tmp_path: Path,
    ) -> None:
        """Donor reads and the maintenance tick never wait on either gate.

        Every managed job is encode-bearing by construction, so the
        admission exemptions live outside the job runtime: donor reads
        (store) and the storage-maintenance evaluation. With the encode
        slot fully borrowed AND the quiesce gate paused, both must still
        complete within a bound - routing either through the slot or the
        gate turns the timeout below into a red hang report.
        """
        from datetime import UTC, datetime

        from ..concurrency import get_encode_limiter
        from ..storage_reclamation import ReclaimPolicy, evaluate_reclaim
        from ..store_runtime import VaultStore

        gate = QuiesceGate()
        gate.pause()
        limiter = get_encode_limiter()
        try:
            async with limiter:  # the single encode slot is fully borrowed

                def _donor_read() -> dict[str, object]:
                    store = VaultStore(tmp_path)
                    try:
                        return dict(
                            store.retrieve_donor_points(
                                "nonexistent-donor-collection",
                                ["chunk-a", "chunk-b"],
                            )
                        )
                    finally:
                        store.close()

                hits = await asyncio.wait_for(
                    asyncio.to_thread(_donor_read),
                    timeout=30.0,
                )
                # Absence is the fail-fast contract: local mode supports no
                # donors, and the read returns instead of parking anywhere.
                assert hits == {}

                decisions = await asyncio.wait_for(
                    asyncio.to_thread(
                        evaluate_reclaim,
                        [],
                        {},
                        now=datetime.now(tz=UTC),
                        policy=ReclaimPolicy(),
                    ),
                    timeout=30.0,
                )
                assert decisions == []
        finally:
            gate.resume()

    def test_donor_reads_never_consult_gate_or_encode_slot(self) -> None:
        """Donor reads and store code stay off both gates by construction.

        A source scan mirrors the encode-slot scan above: the store (donor
        reads included) and donor candidate selection must never wait on
        the quiesce gate or the encode admission slot, so a paused daemon
        holding the slot can never deadlock a reuse donor lookup.
        """
        package_root = Path(inspect.getfile(jobs_module)).parent
        for rel in (
            "store_runtime.py",
            "store_collections.py",
            "store_ingest.py",
            "store_catalog.py",
            "store_donors.py",
            "indexer/_donor_candidates.py",
        ):
            source = (package_root / rel).read_text(encoding="utf-8")
            assert "get_encode_limiter" not in source, (
                f"{rel} must not reference the encode admission slot"
            )
            assert "QuiesceGate" not in source, (
                f"{rel} must not consult the quiesce gate"
            )
