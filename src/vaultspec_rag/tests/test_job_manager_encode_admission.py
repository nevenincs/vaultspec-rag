"""Cohesive unit coverage for job-management behavior."""

from __future__ import annotations

import asyncio
import inspect
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from .. import jobs as jobs_module
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
from ..service_quiesce import ServiceQuiesceController
from ._job_roots import _TEST_PROJECT_ROOT, _TEST_PROJECT_ROOT_OTHER

if TYPE_CHECKING:
    from collections.abc import Iterator


pytestmark = [pytest.mark.unit]


class TestEncodeAdmissionGate:
    """One machine-wide encode slot admits at most one encode-bearing job.

    The subject is the real dispatch path: ``JobManager.bind_dispatch`` +
    ``dispatch_async`` running instrumented fake-encode runners in the
    production worker machinery. Only the encode work itself is fake.
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
    async def _wait_admitted(
        manager: JobManager,
        job_id: str,
        *,
        timeout: float,
    ) -> float:
        """Return the admission stamp, or raise ``TimeoutError`` if unset."""
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            job = manager.get(job_id)
            assert job is not None
            admitted = job.timestamps.admission_acquired_at
            if admitted is not None:
                return admitted
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(f"job {job_id} was not admitted in {timeout}s")
            await asyncio.sleep(0.01)

    @staticmethod
    async def _wait_terminal(manager: JobManager, job_id: str) -> None:
        deadline = asyncio.get_running_loop().time() + 30.0
        while True:
            job = manager.get(job_id)
            assert job is not None
            if job.state.is_terminal:
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(f"job {job_id} did not finish")
            await asyncio.sleep(0.01)

    @pytest.mark.asyncio
    async def test_two_concurrent_encode_jobs_serialize_on_the_slot(self) -> None:

        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=4,
            state_path=None,
        )
        initiator = JobInitiator("test", "encode-gate", None)
        first = manager.create(self._encode_spec(_TEST_PROJECT_ROOT), initiator)
        second = manager.create(self._encode_spec(_TEST_PROJECT_ROOT_OTHER), initiator)
        assert first.job is not None
        assert second.job is not None

        gauge_lock = threading.Lock()
        in_flight = 0
        max_in_flight = 0
        release_first = threading.Event()

        def fake_encode(hold: bool) -> Any:
            def runner(context: JobAttemptContext) -> JobExecutionResult:
                nonlocal in_flight, max_in_flight
                del context
                with gauge_lock:
                    in_flight += 1
                    max_in_flight = max(max_in_flight, in_flight)
                try:
                    if hold:
                        assert release_first.wait(timeout=30.0)
                finally:
                    with gauge_lock:
                        in_flight -= 1
                return JobExecutionResult(summary="fake encode ok")

            return runner

        assert manager.bind_dispatch(first.job.id, fake_encode(True)).code == (
            "dispatch_bound"
        )
        assert manager.bind_dispatch(second.job.id, fake_encode(False)).code == (
            "dispatch_bound"
        )
        try:
            assert (await manager.dispatch_async(first.job.id)).code == (
                "attempt_started"
            )
            await self._wait_admitted(manager, first.job.id, timeout=10.0)
            assert (await manager.dispatch_async(second.job.id)).code == (
                "attempt_started"
            )

            # The intended assertion of this guard: while the first encode
            # job holds the machine-wide slot, the second is dispatched and
            # RUNNING but must stay unadmitted. Widening or bypassing the
            # encode limiter admits it within milliseconds and turns this
            # into an immediate failure.
            with pytest.raises(TimeoutError):
                await self._wait_admitted(manager, second.job.id, timeout=1.0)
            waiting = manager.get(second.job.id)
            assert waiting is not None
            assert waiting.state is JobState.RUNNING
            assert waiting.timestamps.admission_acquired_at is None
            assert waiting.timestamps.started_at is not None
        finally:
            release_first.set()

        await self._wait_terminal(manager, first.job.id)
        await self._wait_terminal(manager, second.job.id)
        assert max_in_flight == 1, (
            "encode-bearing jobs overlapped despite the admission slot"
        )
        self._assert_admission_wait_measured(manager, first.job.id, second.job.id)

    @staticmethod
    def _assert_admission_wait_measured(
        manager: JobManager,
        first_id: str,
        second_id: str,
    ) -> None:
        """The stamp makes the gate measurable: wait two spans slot one."""
        done_first = manager.get(first_id)
        done_second = manager.get(second_id)
        assert done_first is not None
        assert done_second is not None
        assert done_first.state is JobState.SUCCEEDED
        assert done_second.state is JobState.SUCCEEDED
        first_admitted = done_first.timestamps.admission_acquired_at
        second_admitted = done_second.timestamps.admission_acquired_at
        second_started = done_second.timestamps.started_at
        assert first_admitted is not None
        assert second_admitted is not None
        assert second_started is not None
        assert second_admitted >= first_admitted
        assert second_admitted - second_started >= 1.0
        assert done_second.to_dict()["admission_acquired_at"] == second_admitted

    @pytest.mark.asyncio
    async def test_admission_stamp_is_recorded_for_a_solo_job(self) -> None:
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=2,
            state_path=None,
        )
        initiator = JobInitiator("test", "encode-gate", None)
        created = manager.create(self._encode_spec(_TEST_PROJECT_ROOT), initiator)
        assert created.job is not None

        def runner(context: JobAttemptContext) -> JobExecutionResult:
            del context
            return JobExecutionResult(summary="ok")

        manager.bind_dispatch(created.job.id, runner)
        await manager.dispatch_async(created.job.id)
        await self._wait_terminal(manager, created.job.id)
        done = manager.get(created.job.id)
        assert done is not None
        admitted = done.timestamps.admission_acquired_at
        started = done.timestamps.started_at
        assert admitted is not None
        assert started is not None
        assert admitted >= started

    def test_only_encode_bearing_specs_take_the_encode_slot(self) -> None:
        from ..job_models import is_encode_bearing

        for source in (JobSource.VAULT, JobSource.CODE, JobSource.DOCUMENT):
            assert is_encode_bearing(
                JobSpec(JobOperation.INDEX, source, _TEST_PROJECT_ROOT, JobMode.REBUILD)
            )
        assert not is_encode_bearing(
            JobSpec(JobOperation.MAINTENANCE, JobSource.MAINTENANCE, None, None)
        )
        assert not is_encode_bearing(
            JobSpec(JobOperation.INDEX, JobSource.MAINTENANCE, None, None)
        )

    def test_encode_slot_is_single_capacity_and_reported(self) -> None:
        async def probe() -> None:
            from ..concurrency import get_encode_limiter, limiter_stats

            limiter = get_encode_limiter()
            assert int(limiter.total_tokens) == 1
            stats = limiter_stats()
            assert stats["encode"]["total_tokens"] == 1
            assert stats["encode"]["borrowed_tokens"] == 0

        asyncio.run(probe())

    def test_maintenance_and_search_paths_never_name_the_encode_slot(self) -> None:
        """Lifecycle-inert and read-only modules stay outside the gate.

        A source scan, not an import trick: the storage-maintenance tick and
        the search path must never acquire the encode admission slot, or a
        wedged encode job could starve maintenance or interactive search.
        """
        package_root = Path(inspect.getfile(jobs_module)).parent
        for rel in (
            "storage_survey_ops.py",
            "storage_reconciliation.py",
            "storage_migration.py",
            "storage_reclamation.py",
            "storage_manifest.py",
            "search/_searcher.py",
            "server/_lifespan.py",
        ):
            source = (package_root / rel).read_text(encoding="utf-8")
            assert "get_encode_limiter" not in source, (
                f"{rel} must not reference the encode admission slot"
            )
