"""Restoring managed jobs from state a crash left unreadable or inconsistent.

Quarantine is the outcome that matters here: a state file that cannot be
trusted must not be partially applied, and the daemon must still start.
The clock cases belong with them - a backwards wall-clock step is another
way the persisted record stops being readable in order.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path  # noqa: TC003
from typing import cast

import pytest

from ... import _job_values
from ...job_control import RunControlToken
from ...job_manager.manager import JobManager
from ...job_manager.models import ResourceUpdate
from ...job_models import (
    JobInitiator,
    JobMode,
    JobOperation,
    JobOutcomeStatus,
    JobSource,
    JobSpec,
    JobState,
)
from ...server._lifespan import _start_job_manager
from ...service import ServiceRegistry
from ...service_quiesce import ServiceQuiesceController
from .._job_manager_transition_helpers import pending_attempt


class TestManagedJobQuarantine:
    """Unreadable, inconsistent, and out-of-order persisted state."""

    pytestmark = pytest.mark.unit

    def test_invalid_state_quarantines_without_partial_restore(
        self,
        tmp_path: Path,
    ) -> None:
        state_path = tmp_path / "managed-jobs.json"
        truncated = '{"schema":"vaultspec.rag.jobs","version":1,"jobs":['
        state_path.write_text(truncated, encoding="utf-8")
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            state_path=state_path,
        )

        outcome = manager.restore_persisted()

        assert outcome.status is JobOutcomeStatus.OK
        assert outcome.code == "job_state_quarantined"
        assert manager.list_jobs() == []
        assert not state_path.exists()
        quarantined = list(tmp_path.glob("managed-jobs.json.invalid-*"))
        assert len(quarantined) == 1
        assert quarantined[0].read_text(encoding="utf-8") == truncated
        assert str(quarantined[0]) in outcome.message

    def test_structurally_valid_inconsistent_state_is_quarantined_unapplied(
        self,
        tmp_path: Path,
    ) -> None:
        state_path = tmp_path / "managed-jobs.json"
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            state_path=state_path,
        )
        spec = JobSpec(
            JobOperation.INDEX,
            JobSource.VAULT,
            str(tmp_path),
            JobMode.INCREMENTAL,
        )
        initiator = JobInitiator("http", "POST /jobs", str(tmp_path))
        manager.create(spec, initiator, idempotency_key="validation-1")
        payload = json.loads(state_path.read_text(encoding="utf-8"))

        payload["jobs"][0]["desired_state"] = "paused"
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        inconsistent = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            state_path=state_path,
        )
        assert inconsistent.restore_persisted().code == "job_state_quarantined"
        assert inconsistent.list_jobs() == []

        payload["jobs"][0]["desired_state"] = "running"
        payload["idempotency"][0]["job_id"] = "missing-job"
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        dangling = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            state_path=state_path,
        )
        assert dangling.restore_persisted().code == "job_state_quarantined"
        assert dangling.list_jobs() == []

        payload["idempotency"][0]["job_id"] = payload["jobs"][0]["id"]
        payload["jobs"][0]["state"] = "running"
        payload["jobs"][0]["started_at"] = None
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        unstarted = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            state_path=state_path,
        )
        assert unstarted.restore_persisted().code == "job_state_quarantined"
        assert unstarted.list_jobs() == []

        payload["jobs"][0]["state"] = "queued"
        payload["jobs"][0]["attempt"] = 2
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        unlinked_resume = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            state_path=state_path,
        )
        assert unlinked_resume.restore_persisted().code == "job_state_quarantined"
        assert unlinked_resume.list_jobs() == []

        payload["jobs"][0]["attempt"] = 1
        payload["jobs"][0]["resumed_from_attempt"] = 1
        payload["jobs"][0]["resume_strategy"] = "reconcile"
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        false_first_resume = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            state_path=state_path,
        )
        assert false_first_resume.restore_persisted().code == "job_state_quarantined"
        assert false_first_resume.list_jobs() == []
        # Five same-named quarantines in rapid succession must land as five
        # distinct siblings; losing one means a later quarantine replaced
        # earlier evidence.
        assert len(list(tmp_path.glob("managed-jobs.json.invalid-*"))) == 5

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("isolated_status_dir")
    async def test_null_resource_reading_quarantines_and_startup_proceeds(
        self,
        _clean_jobs: None,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A null resource reading must cost the history, never the daemon.

        The state file records job history - observability data - while the
        index itself lives in vector storage. A daemon refusing to start over
        one non-numeric field in its own shutdown artifact is a total outage
        the operator cannot self-service, so service startup must quarantine
        the file byte-for-byte, log the loss loudly, and come up with an
        empty registry.
        """
        state_path = tmp_path / "managed-jobs.json"
        seeded = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            state_path=state_path,
        )
        created = seeded.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.VAULT,
                str(tmp_path),
                JobMode.INCREMENTAL,
            ),
            JobInitiator("watcher", "watcher_vault_index", str(tmp_path)),
        )
        assert created.job is not None
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        payload["jobs"][0]["resources"]["started"] = {
            "rss_mib": None,
            "cuda_allocated_mib": 0.0,
            "cuda_reserved_mib": 0.0,
        }
        corrupted = json.dumps(payload)
        state_path.write_text(corrupted, encoding="utf-8")

        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            state_path=state_path,
        )
        with caplog.at_level(logging.ERROR, logger="vaultspec_rag.jobs"):
            await _start_job_manager(manager, ServiceRegistry())

        assert manager.list_jobs() == []
        assert not state_path.exists()
        quarantined = list(tmp_path.glob("managed-jobs.json.invalid-*"))
        assert len(quarantined) == 1
        assert quarantined[0].read_text(encoding="utf-8") == corrupted
        assert "state_quarantined" in caplog.text
        assert "resource rss_mib must be numeric" in caplog.text

    def test_unreadable_state_path_still_fails_restore(
        self,
        tmp_path: Path,
    ) -> None:
        """An unreadable state path is an environment fault, not a bad file.

        A directory squatting on the state path makes the read itself fail
        before any content is seen. Quarantining there would dress a
        filesystem fault up as corrupt history and let the daemon continue
        into the same fault on its next persist, so restore must keep
        reporting an error and move nothing.
        """
        state_path = tmp_path / "managed-jobs.json"
        state_path.mkdir()
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            state_path=state_path,
        )

        outcome = manager.restore_persisted()

        assert outcome.status is JobOutcomeStatus.ERROR
        assert outcome.code == "job_state_unreadable"
        assert state_path.is_dir()
        assert list(tmp_path.glob("managed-jobs.json.invalid-*")) == []
        assert manager.list_jobs() == []

    def test_quarantine_obstacle_fails_restore_with_evidence_kept(
        self,
        tmp_path: Path,
    ) -> None:
        """A blocked quarantine keeps the failure loud and the evidence put.

        With a non-file obstacle at the candidate destination the rename
        cannot preserve the invalid file; continuing anyway would leave the
        corrupt file in place for the first persist to overwrite. Restore
        must fail on the quarantine branch with the original file untouched.
        """
        state_path = tmp_path / "managed-jobs.json"
        state_path.write_text("not json", encoding="utf-8")
        # A directory obstacle at every candidate the clock could pick makes
        # the rename fail instead of being stepped around.
        now = int(time.time())
        for offset in range(-1, 6):
            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now + offset))
            (tmp_path / f"managed-jobs.json.invalid-{stamp}").mkdir()
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            state_path=state_path,
        )

        outcome = manager.restore_persisted()

        assert outcome.status is JobOutcomeStatus.ERROR
        assert outcome.code == "job_state_quarantine_failed"
        assert state_path.read_text(encoding="utf-8") == "not json"
        assert manager.list_jobs() == []

    @staticmethod
    def _rewind_the_wall_clock_under(state_path: Path, *, seconds: float) -> None:
        """Age the persisted stamps into the reader's future by ``seconds``.

        A wall clock that steps backwards leaves exactly this behind: a file
        the previous service life wrote while the clock was ahead of where it
        is now. Every stamp moves together, so the record stays internally
        consistent and loads cleanly - the damage appears only once this life
        stamps a new revision onto it from the corrected clock. Shifting the
        file rather than the machine's clock keeps the step confined to one
        temporary directory.
        """
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        for job in cast("list[dict[str, object]]", payload["jobs"]):
            for name in (
                "created_at",
                "state_changed_at",
                "started_at",
                "finished_at",
                "control_requested_at",
                "control_acknowledged_at",
                "admission_acquired_at",
            ):
                stamp = _job_values.measurement(job.get(name))
                if stamp is not None:
                    job[name] = stamp + seconds
            progress = job.get("progress")
            if isinstance(progress, dict):
                block = cast("dict[str, object]", progress)
                updated = _job_values.measurement(block.get("last_updated"))
                if updated is not None:
                    block["last_updated"] = updated + seconds
        state_path.write_text(json.dumps(payload), encoding="utf-8")

    @pytest.mark.asyncio
    async def test_a_backwards_clock_step_never_persists_an_unreadable_record(
        self,
        tmp_path: Path,
    ) -> None:
        """Recovery must not manufacture the file the next start refuses.

        Wall-clock time is not monotonic: a corrective sync, a restored
        virtual-machine snapshot or a container resync can move it backwards
        between two transitions of one job. Restore is the sharpest case,
        because it stamps a fresh interrupt onto stamps a previous service
        life wrote - so a step between those two lives makes the recovery
        write a record whose finish predates its own creation, and the start
        after that refuses the whole file and drops every job's history.

        No clock is manipulated here and no time source is injected. The step
        is carried by the only thing that outlives it, the file the previous
        life left behind, which is also how a real one reaches this code.
        """
        from ...job_persistence import load_persisted_state

        state_path = tmp_path / "managed-jobs.json"
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=2,
            state_path=state_path,
        )
        created = manager.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.CODE,
                str(tmp_path),
                JobMode.INCREMENTAL,
            ),
            JobInitiator("cli", "server job create", str(tmp_path)),
        )
        assert created.job is not None
        owner_task = asyncio.create_task(pending_attempt())
        try:
            assert (
                manager.start_attempt(
                    created.job.id,
                    task=owner_task,
                    control=RunControlToken(),
                ).code
                == "attempt_started"
            )
            self._rewind_the_wall_clock_under(state_path, seconds=3600.0)
            # The previous life's file is intact: the step damages nothing
            # already written, which is what makes the damage this test is
            # about attributable to the revision restore stamps onto it.
            assert len(load_persisted_state(state_path).jobs) == 1

            restarted = JobManager(
                quiesce_controller=ServiceQuiesceController(),
                max_nonterminal=2,
                state_path=state_path,
            )
            assert restarted.restore_persisted().code == "job_state_restored"
            interrupted = restarted.get(created.job.id)
            assert interrupted is not None
            assert interrupted.state is JobState.INTERRUPTED
            stamps = interrupted.timestamps
            assert stamps.finished_at is not None
            # Removing the floor in `ordered_stamp` puts the interrupt's raw
            # `time.time()` an hour behind creation and fails these two.
            assert stamps.state_changed_at >= stamps.created_at
            assert stamps.finished_at >= stamps.created_at

            # The record the next start actually reads, through the loader
            # that start uses. Unfloored, this raises "state change predates
            # creation" and the whole history is quarantined away.
            reloaded = load_persisted_state(state_path)
            assert len(reloaded.jobs) == 1
        finally:
            owner_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await owner_task

    @pytest.mark.asyncio
    async def test_a_backwards_clock_step_never_persists_an_early_admission(
        self,
        tmp_path: Path,
    ) -> None:
        """The admission clock is stamped outside the transition funnel.

        Admission is recorded as a resource fact rather than a state change,
        so it reaches the record by its own path and needs the same floor.
        Its caller reads the wall clock and passes the reading on unchanged,
        which is where the reading a stepped-back clock produces is supplied
        here.
        """
        from ...job_persistence import load_persisted_state

        state_path = tmp_path / "managed-jobs.json"
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=2,
            state_path=state_path,
        )
        created = manager.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.VAULT,
                str(tmp_path),
                JobMode.INCREMENTAL,
            ),
            JobInitiator("http", "POST /jobs", str(tmp_path)),
        )
        assert created.job is not None
        owner_task = asyncio.create_task(pending_attempt())
        try:
            started = manager.start_attempt(
                created.job.id,
                task=owner_task,
                control=RunControlToken(),
            )
            assert started.job is not None
            assert manager.update_execution_resources(
                created.job.id,
                task=owner_task,
                update=ResourceUpdate(
                    index_capacity_held=True,
                    admission_acquired_at=started.job.timestamps.created_at - 3600.0,
                ),
            )
            admitted = manager.get(created.job.id)
            assert admitted is not None
            admission = admitted.timestamps.admission_acquired_at
            assert admission is not None
            # Removing the floor stores the raw reading and fails this.
            assert admission >= admitted.timestamps.created_at

            # Unfloored, the next start reads "admission_acquired_at predates
            # creation" and quarantines the file.
            assert len(load_persisted_state(state_path).jobs) == 1
        finally:
            owner_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await owner_task
