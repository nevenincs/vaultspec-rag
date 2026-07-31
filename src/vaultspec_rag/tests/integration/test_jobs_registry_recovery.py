"""Focused real-behavior coverage for the jobs registry."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING, cast

import pytest

from ... import jobs as _jobs
from ...job_control import RunControlToken
from ...job_manager._control import AttemptTerminal
from ...job_manager.manager import JobManager
from ...job_models import (
    DesiredJobState,
    JobInitiator,
    JobMode,
    JobOperation,
    JobOutcomeStatus,
    JobSource,
    JobSpec,
    JobState,
)
from ...server._lifespan import _start_job_manager
from ...server._routes import _service_job_snapshot
from ...server._routes_jobs import _job_with_liveness
from ...service import ServiceRegistry
from ...service_quiesce import ServiceQuiesceController
from .._job_manager_transition_helpers import pending_attempt

if TYPE_CHECKING:
    from ...job_manager.state import AttemptExit


def _exited_process_pid() -> int:
    """Return the pid of a process that has already exited.

    A literal high pid is a guess the OS is free to contradict; a pid this
    process reaped is observably dead, which is what the liveness guard needs
    to distinguish from a running owner.
    """
    with subprocess.Popen(
        [sys.executable, "-c", ""],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ) as process:
        process.wait()
        return process.pid


class TestJobResourceDeletion:
    """Deletion and resolution span both registries the jobs list unions."""

    pytestmark = pytest.mark.unit

    @staticmethod
    def _terminal_job_with_activity_record(root: Path) -> str:
        """Admit one canonical job, shadow it, and drive it terminal."""
        manager = _jobs.get_job_manager()
        outcome = manager.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.CODE,
                str(root),
                JobMode.INCREMENTAL,
            ),
            JobInitiator(
                kind="cli",
                command="reindex_codebase",
                project_root=str(root),
            ),
        )
        assert outcome.job is not None
        job_id = outcome.job.id
        _jobs.record_start(
            JobSource.CODE,
            "tool",
            project_root=root,
            command="reindex_codebase",
            _record_id=job_id,
        )
        _jobs.record_finish(job_id, result="ok")
        manager.set_desired_state(job_id, DesiredJobState.CANCELLED)
        return job_id

    @pytest.mark.usefixtures("isolated_status_dir")
    def test_delete_removes_the_shadowing_activity_record(
        self,
        _clean_jobs: None,
        tmp_path: Path,
    ) -> None:
        """A deleted job must not return through the other registry.

        Canonical history and the activity ring hold the same job under one id,
        and the jobs list is their union. Deleting canonical history alone left
        the shadow behind, which then surfaced as a row the operator had just
        deleted and could no longer address.
        """
        job_id = self._terminal_job_with_activity_record(tmp_path)
        assert any(row["id"] == job_id for row in _service_job_snapshot())

        outcome = _jobs.delete_job(job_id)

        assert outcome.status is JobOutcomeStatus.OK
        assert outcome.code == "job_deleted"
        # The union, not either half: a shadow surviving here is the bug.
        assert not any(row["id"] == job_id for row in _service_job_snapshot())
        assert _jobs.find_job(job_id) is None

    @pytest.mark.usefixtures("isolated_status_dir")
    def test_activity_only_record_is_addressable_and_deletable(
        self,
        _clean_jobs: None,
    ) -> None:
        """A listed row with no canonical twin must resolve and delete.

        Maintenance cycles and restart-restored runs only ever exist as
        activity records. They were listed but not addressable, so every
        control verb - which resolves through the detail route - reported the
        id missing for a row plainly on screen.
        """
        job_id = _jobs.record_start(
            JobSource.MAINTENANCE,
            "schedule",
            command="storage_maintenance",
        )
        _jobs.record_finish(job_id, result="swept")
        assert _jobs.get_job_manager().get(job_id) is None
        assert any(row["id"] == job_id for row in _service_job_snapshot())

        assert _jobs.find_job(job_id) is not None
        outcome = _jobs.delete_job(job_id)

        assert outcome.status is JobOutcomeStatus.OK
        assert outcome.code == "job_deleted"
        assert not any(row["id"] == job_id for row in _service_job_snapshot())

    @pytest.mark.usefixtures("isolated_status_dir")
    def test_delete_refuses_a_running_activity_record(
        self,
        _clean_jobs: None,
        tmp_path: Path,
    ) -> None:
        """Deletion is history-only and never reaches unfinished work.

        Guard: reaching an activity record with no terminal check would let
        delete silently drop the only trace of a run still in flight. The
        assertion below names ``job_not_terminal`` exactly, because a bare
        "errored" check passes for every rejection reason.
        """
        job_id = _jobs.record_start(
            JobSource.CODE,
            "watcher",
            project_root=tmp_path,
        )

        outcome = _jobs.delete_job(job_id)

        assert outcome.status is JobOutcomeStatus.ERROR
        assert outcome.code == "job_not_terminal"
        assert any(row["id"] == job_id for row in _service_job_snapshot())

    def test_activity_record_reports_truthful_capabilities(
        self,
        _clean_jobs: None,
    ) -> None:
        """Every listed row states what it supports, whichever registry owns it."""
        running_id = _jobs.record_start(JobSource.VAULT, "tool")
        finished_id = _jobs.record_start(JobSource.VAULT, "tool")
        _jobs.record_finish(finished_id, result="ok")

        rows = {
            str(row["id"]): row
            for row in (
                _job_with_liveness(record, now=time.time())
                for record in _jobs.snapshot()
            )
        }

        assert rows[finished_id]["capabilities"] == {
            "pausable": False,
            "resumable": False,
            "cancellable": False,
            "retryable": False,
            "deletable": True,
            "force_killable": False,
        }
        running_capabilities = cast(
            "dict[str, object]", rows[running_id]["capabilities"]
        )
        assert running_capabilities["deletable"] is False


class TestInterruptedRestoreOwnership:
    """Restart adoption never claims work another live process still owns."""

    pytestmark = pytest.mark.unit

    @staticmethod
    def _write_active_snapshot(
        status_dir: Path,
        entries: list[dict[str, object]],
    ) -> None:
        (status_dir / "jobs-active.json").write_text(
            json.dumps({"active": entries}),
            encoding="utf-8",
        )

    def test_live_owner_is_skipped_and_dead_owner_is_restored(
        self,
        _clean_jobs: None,
        isolated_status_dir: Path,
    ) -> None:
        """Guard: adopting a live process's run publishes a phantom record.

        The running-jobs snapshot is one machine-wide path written by every
        process that indexes, so an entry found there is not necessarily this
        service's abandoned work. Adopting one that is still running invents an
        ``interrupted`` row under an id this service cannot address - exactly
        the unaddressable rows deletion cannot clear.

        The dead-owner and missing-pid assertions are the other direction: a
        guard that skipped everything would pass a live-owner-only check while
        silently discarding every genuinely interrupted run.
        """
        self._write_active_snapshot(
            isolated_status_dir,
            [
                {
                    "id": "owned-by-a-live-process",
                    "source": "code",
                    "trigger": "tool",
                    "started_at": 1.0,
                    "progress": None,
                    "initiator": None,
                    "pid": os.getpid(),
                },
                {
                    "id": "owned-by-a-dead-process",
                    "source": "vault",
                    "trigger": "watcher",
                    "started_at": 1.0,
                    "progress": None,
                    "initiator": None,
                    "pid": _exited_process_pid(),
                },
                {
                    "id": "written-before-the-pid-field",
                    "source": "code",
                    "trigger": "tool",
                    "started_at": 1.0,
                    "progress": None,
                    "initiator": None,
                },
            ],
        )

        restored = _jobs.restore_interrupted()

        ids = {str(entry["id"]) for entry in _jobs.snapshot()}
        assert "owned-by-a-live-process" not in ids
        assert "owned-by-a-dead-process" in ids
        assert "written-before-the-pid-field" in ids
        assert restored == 2

    def test_running_record_carries_its_owning_pid(
        self,
        _clean_jobs: None,
        isolated_status_dir: Path,
    ) -> None:
        """The snapshot records an owner, or the guard above has nothing to read."""
        _jobs.record_start(JobSource.VAULT, "tool")

        raw = (isolated_status_dir / "jobs-active.json").read_text(encoding="utf-8")
        entries = cast(
            "list[dict[str, object]]",
            cast("dict[str, object]", json.loads(raw))["active"],
        )

        assert [entry["pid"] for entry in entries] == [os.getpid()]


class TestManagedJobPersistence:
    """Canonical lifecycle state survives real atomic filesystem boundaries."""

    pytestmark = pytest.mark.unit

    def test_paused_state_and_idempotency_restore_under_the_same_id(
        self,
        tmp_path: Path,
    ) -> None:
        state_path = tmp_path / "managed-jobs.json"
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=2,
            state_path=state_path,
        )
        spec = JobSpec(
            JobOperation.INDEX,
            JobSource.VAULT,
            str(tmp_path),
            JobMode.INCREMENTAL,
        )
        initiator = JobInitiator("http", "POST /jobs", str(tmp_path))

        created = manager.create(spec, initiator, idempotency_key="persist-1")
        assert created.job is not None
        job_id = created.job.id
        assert state_path.exists()
        queued_payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert queued_payload["jobs"][0]["state"] == "queued"

        paused = manager.set_desired_state(job_id, DesiredJobState.PAUSED)
        assert paused.job is not None
        assert paused.job.state is JobState.PAUSED
        paused_payload = json.loads(state_path.read_text(encoding="utf-8"))
        assert paused_payload["jobs"][0]["state"] == "paused"
        assert list(tmp_path.glob(".managed-jobs.json.*.tmp")) == []

        restarted = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=2,
            state_path=state_path,
        )
        restored = restarted.restore_persisted()
        assert restored.code == "job_state_restored"
        snapshot = restarted.get(job_id)
        assert snapshot is not None
        assert snapshot.state is JobState.PAUSED
        assert snapshot.revision == paused.job.revision
        replay = restarted.create(
            spec,
            initiator,
            idempotency_key="persist-1",
        )
        assert replay.code == "idempotency_replayed"
        assert replay.job == snapshot

    def test_equivalent_deduplication_binding_restores_and_replays(
        self,
        tmp_path: Path,
    ) -> None:
        state_path = tmp_path / "managed-jobs.json"
        project_root = tmp_path / "project"
        project_root.mkdir()
        canonical_spec = JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            str(project_root),
            JobMode.INCREMENTAL,
        )
        alias_spec = JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            str(project_root / "uncreated" / ".."),
            JobMode.INCREMENTAL,
        )
        canonical_initiator = JobInitiator(
            "watcher",
            "watcher_code_index",
            str(project_root),
        )
        alias_initiator = JobInitiator(
            "http",
            "POST /jobs",
            str(project_root),
        )
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=2,
            state_path=state_path,
        )

        created = manager.create(canonical_spec, canonical_initiator)
        deduplicated = manager.create(
            alias_spec,
            alias_initiator,
            idempotency_key="equivalent-request",
        )
        assert created.job is not None
        assert deduplicated.job is not None
        assert deduplicated.job.id == created.job.id

        restarted = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=2,
            state_path=state_path,
        )
        assert restarted.restore_persisted().code == "job_state_restored"
        replay = restarted.create(
            alias_spec,
            alias_initiator,
            idempotency_key="equivalent-request",
        )

        assert replay.code == "idempotency_replayed"
        assert replay.job is not None
        assert replay.job.id == created.job.id

    @pytest.mark.asyncio
    async def test_exact_task_ownership_and_interrupted_recovery(
        self,
        tmp_path: Path,
    ) -> None:
        state_path = tmp_path / "managed-jobs.json"
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=2,
            state_path=state_path,
        )
        spec = JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            str(tmp_path),
            JobMode.REBUILD,
        )
        initiator = JobInitiator("cli", "server job create", str(tmp_path))
        created = manager.create(spec, initiator)
        assert created.job is not None
        owner_task = asyncio.create_task(pending_attempt())
        stale_task = asyncio.create_task(pending_attempt())
        try:
            started = manager.start_attempt(
                created.job.id,
                task=owner_task,
                control=RunControlToken(),
            )
            assert started.job is not None
            assert started.job.state is JobState.RUNNING
            assert (
                manager.acknowledge_control(
                    created.job.id,
                    attempt=1,
                    task=stale_task,
                ).code
                == "stale_attempt_ignored"
            )
            owned = manager.get(created.job.id)
            assert owned is not None
            assert owned.runtime.task_active is True

            payload = json.loads(state_path.read_text(encoding="utf-8"))
            payload["jobs"][0]["runtime"]["pid"] = 123456
            payload["jobs"][0]["runtime"]["executable"] = "old-service.exe"
            state_path.write_text(json.dumps(payload), encoding="utf-8")

            restarted = JobManager(
                quiesce_controller=ServiceQuiesceController(),
                max_nonterminal=2,
                state_path=state_path,
            )
            assert restarted.restore_persisted().code == "job_state_restored"
            interrupted = restarted.get(created.job.id)
            assert interrupted is not None
            assert interrupted.state is JobState.INTERRUPTED
            assert interrupted.timestamps.finished_at is not None
            assert interrupted.runtime.task_active is False
            assert interrupted.runtime.pid == 123456
            assert interrupted.runtime.executable == "old-service.exe"
            persisted = json.loads(state_path.read_text(encoding="utf-8"))["jobs"]
            assert len(persisted) == 1
            assert persisted[0]["state"] == "interrupted"
        finally:
            owner_task.cancel()
            stale_task.cancel()
            for task in (owner_task, stale_task):
                with pytest.raises(asyncio.CancelledError):
                    await task

    @pytest.mark.asyncio
    async def test_interrupted_recovery_displaces_older_terminal_history(
        self,
        tmp_path: Path,
    ) -> None:
        state_path = tmp_path / "managed-jobs.json"
        completed_root = tmp_path / "completed"
        interrupted_root = tmp_path / "interrupted"
        completed_root.mkdir()
        interrupted_root.mkdir()
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=2,
            max_terminal_history=1,
            state_path=state_path,
        )
        completed = manager.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.VAULT,
                str(completed_root),
                JobMode.INCREMENTAL,
            ),
            JobInitiator("http", "POST /jobs", str(completed_root)),
        )
        assert completed.job is not None
        completed_task = asyncio.create_task(pending_attempt())
        interrupted_task = asyncio.create_task(pending_attempt())
        try:
            assert (
                manager.start_attempt(
                    completed.job.id,
                    task=completed_task,
                    control=RunControlToken(),
                ).code
                == "attempt_started"
            )
            assert (
                manager.finish_attempt(
                    completed.job.id,
                    AttemptTerminal(
                        attempt=1,
                        task=completed_task,
                        state=JobState.SUCCEEDED,
                        result="done",
                    ),
                ).code
                == "job_finished"
            )
            interrupted = manager.create(
                JobSpec(
                    JobOperation.INDEX,
                    JobSource.CODE,
                    str(interrupted_root),
                    JobMode.REBUILD,
                ),
                JobInitiator("watcher", "watcher_code_index", str(interrupted_root)),
            )
            assert interrupted.job is not None
            assert (
                manager.start_attempt(
                    interrupted.job.id,
                    task=interrupted_task,
                    control=RunControlToken(),
                ).code
                == "attempt_started"
            )

            restarted = JobManager(
                quiesce_controller=ServiceQuiesceController(),
                max_nonterminal=2,
                max_terminal_history=1,
                state_path=state_path,
            )
            assert restarted.restore_persisted().code == "job_state_restored"
            terminal = restarted.terminal()

            assert len(terminal) == 1
            assert terminal[0].id == interrupted.job.id
            assert terminal[0].state is JobState.INTERRUPTED

            restarted_again = JobManager(
                quiesce_controller=ServiceQuiesceController(),
                max_nonterminal=2,
                max_terminal_history=1,
                state_path=state_path,
            )
            assert restarted_again.restore_persisted().code == "job_state_restored"
            retained_again = restarted_again.terminal()
            assert [job.id for job in retained_again] == [interrupted.job.id]
            assert retained_again[0].state is JobState.INTERRUPTED
        finally:
            completed_task.cancel()
            interrupted_task.cancel()
            for task in (completed_task, interrupted_task):
                with pytest.raises(asyncio.CancelledError):
                    await task

    def test_lower_terminal_retention_filters_obsolete_idempotency(
        self,
        tmp_path: Path,
    ) -> None:
        state_path = tmp_path / "managed-jobs.json"
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            max_terminal_history=3,
            state_path=state_path,
        )
        requests: list[tuple[JobSpec, JobInitiator, str, str]] = []
        for index in range(3):
            root = tmp_path / f"project-{index}"
            spec = JobSpec(
                JobOperation.INDEX,
                JobSource.VAULT,
                str(root),
                JobMode.INCREMENTAL,
            )
            initiator = JobInitiator("http", "POST /jobs", str(root))
            key = f"request-{index}"
            created = manager.create(spec, initiator, idempotency_key=key)
            assert created.job is not None
            assert (
                manager.set_desired_state(
                    created.job.id,
                    DesiredJobState.CANCELLED,
                ).code
                == "job_cancelled"
            )
            requests.append((spec, initiator, key, created.job.id))

        restarted = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            max_terminal_history=1,
            state_path=state_path,
        )
        assert restarted.restore_persisted().code == "job_state_restored"
        latest_spec, latest_initiator, latest_key, latest_id = requests[-1]
        assert [job.id for job in restarted.terminal()] == [latest_id]

        replay = restarted.create(
            latest_spec,
            latest_initiator,
            idempotency_key=latest_key,
        )
        assert replay.code == "idempotency_replayed"
        assert replay.job is not None
        assert replay.job.id == latest_id

    def test_atomic_replacement_never_exposes_partial_json(
        self, tmp_path: Path
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
        initiator = JobInitiator("watcher", "watcher_vault_index", str(tmp_path))
        created = manager.create(spec, initiator)
        assert created.job is not None

        stopped = threading.Event()
        failures: list[Exception] = []
        observed_versions: list[int] = []

        def read_state() -> None:
            while not stopped.is_set():
                try:
                    payload = json.loads(state_path.read_text(encoding="utf-8"))
                    observed_versions.append(cast("int", payload["version"]))
                    time.sleep(0.0005)
                except PermissionError:
                    # Windows can briefly deny a reader while os.replace owns
                    # the directory entry; that is not a partial-file read.
                    continue
                except Exception as exc:
                    failures.append(exc)
                    stopped.set()

        reader = threading.Thread(target=read_state)
        reader.start()
        try:
            for _iteration in range(12):
                assert (
                    manager.set_desired_state(
                        created.job.id,
                        DesiredJobState.PAUSED,
                    ).status.value
                    == "ok"
                )
                assert (
                    manager.set_desired_state(
                        created.job.id,
                        DesiredJobState.RUNNING,
                    ).status.value
                    == "accepted"
                )
        finally:
            stopped.set()
            reader.join(timeout=5)

        assert not reader.is_alive()
        assert failures == []
        assert observed_versions
        assert set(observed_versions) == {1}
        assert list(tmp_path.glob(".managed-jobs.json.*.tmp")) == []

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

    def test_failed_persistence_rolls_back_reversible_intent(
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
        created = manager.create(spec, initiator, idempotency_key="rollback-1")
        assert created.job is not None

        state_path.unlink()
        state_path.mkdir()
        outcome = manager.set_desired_state(
            created.job.id,
            DesiredJobState.PAUSED,
        )

        assert outcome.code == "job_persistence_failed"
        unchanged = manager.get(created.job.id)
        assert unchanged == created.job
        assert (
            manager.create(
                spec,
                initiator,
                idempotency_key="rollback-1",
            ).code
            == "idempotency_replayed"
        )
        assert list(tmp_path.glob(".managed-jobs.json.*.tmp")) == []

    @pytest.mark.asyncio
    async def test_failed_terminal_persistence_can_be_flushed_and_recovered(
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
            JobSource.CODE,
            str(tmp_path),
            JobMode.REBUILD,
        )
        initiator = JobInitiator("cli", "server job create", str(tmp_path))
        created = manager.create(spec, initiator)
        assert created.job is not None
        task = asyncio.create_task(pending_attempt())
        try:
            manager.start_attempt(
                created.job.id,
                task=task,
                control=RunControlToken(),
            )
            state_path.unlink()
            state_path.mkdir()
            outcome = manager.finish_attempt(
                created.job.id,
                AttemptTerminal(
                    attempt=1,
                    task=task,
                    state=JobState.FAILED,
                    result="real worker failure",
                    error_kind="other",
                ),
            )

            assert outcome.code == "job_persistence_failed"
            assert outcome.job is not None
            assert outcome.job.state is JobState.FAILED
            assert manager.get(created.job.id) == outcome.job
            assert outcome.job.runtime.task_active is False
            assert manager.persistence_dirty is True

            state_path.rmdir()
            flushed = manager.flush_persistence()
            assert flushed.code == "persistence_flushed"
            assert manager.persistence_dirty is False
            assert manager.flush_persistence().code == "persistence_clean"

            restarted = JobManager(
                quiesce_controller=ServiceQuiesceController(),
                max_nonterminal=1,
                state_path=state_path,
            )
            assert restarted.restore_persisted().code == "job_state_restored"
            recovered = restarted.get(created.job.id)
            assert recovered is not None
            assert recovered.state is JobState.FAILED
            assert recovered.result == "real worker failure"
            assert recovered.runtime.task_active is False
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

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

    def test_version_and_timestamp_invariants_are_strict(
        self,
        tmp_path: Path,
    ) -> None:
        state_path = tmp_path / "managed-jobs.json"
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
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
        payload = json.loads(state_path.read_text(encoding="utf-8"))

        for invalid_version in (True, 1.0):
            payload["version"] = invalid_version
            state_path.write_text(json.dumps(payload), encoding="utf-8")
            invalid = JobManager(
                quiesce_controller=ServiceQuiesceController(),
                max_nonterminal=1,
                state_path=state_path,
            )
            assert invalid.restore_persisted().code == "job_state_quarantined"
            assert invalid.list_jobs() == []

        payload["version"] = 1
        job = payload["jobs"][0]
        job["control_acknowledged_at"] = job["created_at"]
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        unrequested_ack = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            state_path=state_path,
        )
        assert unrequested_ack.restore_persisted().code == "job_state_quarantined"
        assert unrequested_ack.list_jobs() == []

        job["control_acknowledged_at"] = None
        job["state"] = "failed"
        job["started_at"] = job["created_at"] + 2
        job["state_changed_at"] = job["created_at"] + 1
        job["finished_at"] = job["created_at"]
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        impossible_finish = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            state_path=state_path,
        )
        assert impossible_finish.restore_persisted().code == "job_state_quarantined"
        assert impossible_finish.list_jobs() == []

    def test_legacy_v1_start_paused_round_trip_has_control_request_lineage(
        self,
        tmp_path: Path,
    ) -> None:
        state_path = tmp_path / "managed-jobs.json"
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            state_path=state_path,
        )
        created = manager.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.CODE,
                str(tmp_path),
                JobMode.REBUILD,
            ),
            JobInitiator("cli", "server job create", str(tmp_path)),
            start_paused=True,
        )

        assert created.job is not None
        assert created.job.state is JobState.PAUSED
        assert created.job.timestamps.control_requested_at is not None
        assert (
            created.job.timestamps.control_acknowledged_at
            == created.job.timestamps.control_requested_at
        )
        legacy_v1 = json.loads(state_path.read_text(encoding="utf-8"))
        legacy_v1["jobs"][0]["control_requested_at"] = None
        state_path.write_text(json.dumps(legacy_v1), encoding="utf-8")

        restarted = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            state_path=state_path,
        )
        assert restarted.restore_persisted().code == "job_state_restored"
        assert restarted.get(created.job.id) == created.job
        migrated = json.loads(state_path.read_text(encoding="utf-8"))["jobs"][0]
        assert migrated["control_requested_at"] == migrated["control_acknowledged_at"]

    @pytest.mark.asyncio
    async def test_lower_capacity_still_recovers_crashed_attempts(
        self,
        tmp_path: Path,
    ) -> None:
        state_path = tmp_path / "managed-jobs.json"
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=3,
            state_path=state_path,
        )
        tasks: list[asyncio.Task[AttemptExit]] = []
        try:
            for index in range(3):
                root = tmp_path / f"project-{index}"
                created = manager.create(
                    JobSpec(
                        JobOperation.INDEX,
                        JobSource.VAULT,
                        str(root),
                        JobMode.INCREMENTAL,
                    ),
                    JobInitiator("watcher", "watcher_vault_index", str(root)),
                )
                assert created.job is not None
                task = asyncio.create_task(pending_attempt())
                tasks.append(task)
                assert (
                    manager.start_attempt(
                        created.job.id,
                        task=task,
                        control=RunControlToken(),
                    ).code
                    == "attempt_started"
                )

            restarted = JobManager(
                quiesce_controller=ServiceQuiesceController(),
                max_nonterminal=1,
                state_path=state_path,
            )
            outcome = restarted.restore_persisted()
            assert outcome.code == "job_state_restored"
            assert restarted.active() == []
            assert len(restarted.terminal()) == 3
            assert all(
                job.state is JobState.INTERRUPTED for job in restarted.terminal()
            )
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with pytest.raises(asyncio.CancelledError):
                    await task

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

    def test_lowered_capacity_admits_restored_work_and_refuses_new(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A capacity cut below recorded work must not cost the daemon its start.

        The bound governs admission of new jobs, so a valid file holding more
        queued work than the lowered setting is real intent, not corruption:
        restoring it must succeed and keep every ID. Refusing to start would
        repeat identically on every retry with no way back but hand-editing
        state, and dropping the excess would silently evict controllable work.
        The bound still has to bite on new creation, which is what drains the
        overflow, so both halves are asserted together.
        """
        state_path = tmp_path / "managed-jobs.json"
        roots = [tmp_path / f"project-{index}" for index in range(3)]
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=3,
            state_path=state_path,
        )
        recorded: list[str] = []
        for root in roots:
            created = manager.create(
                JobSpec(
                    JobOperation.INDEX,
                    JobSource.VAULT,
                    str(root),
                    JobMode.INCREMENTAL,
                ),
                JobInitiator("watcher", "watcher_vault_index", str(root)),
            )
            assert created.job is not None
            recorded.append(created.job.id)

        restarted = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=1,
            state_path=state_path,
        )
        with caplog.at_level(logging.WARNING, logger="vaultspec_rag.jobs"):
            outcome = restarted.restore_persisted()

        assert outcome.status is JobOutcomeStatus.OK
        assert outcome.code == "job_state_restored"
        assert sorted(job.id for job in restarted.active()) == sorted(recorded)
        assert all(job.state is JobState.QUEUED for job in restarted.active())
        assert "event=restored_over_capacity" in caplog.text
        assert "restored_nonterminal=3" in caplog.text
        assert "configured_capacity=1" in caplog.text

        refused = restarted.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.VAULT,
                str(tmp_path / "project-new"),
                JobMode.INCREMENTAL,
            ),
            JobInitiator("watcher", "watcher_vault_index", str(tmp_path)),
        )
        assert refused.status is JobOutcomeStatus.ERROR
        assert refused.code == "job_capacity_exceeded"

    @pytest.mark.parametrize(
        "sequence",
        [
            "created",
            "start_paused",
            "paused",
            "quiesce_deferred",
            "cancelled",
            "resumed",
            "failed_unstarted",
            "retried",
            "deleted",
            "idempotent",
        ],
    )
    def test_every_persisted_transition_reloads(
        self,
        tmp_path: Path,
        sequence: str,
    ) -> None:
        """What the manager writes, the loader must accept.

        The loader enforces relational rules over a whole generation -
        timestamp ordering, terminal state against the finish clock, observed
        against desired state, attempt lineage - that no single frozen record
        can check on its own. A transition that persists a combination those
        rules reject does not fail when it is written; it fails one boot
        later, in another process, with the write long gone. Driving each
        supported transition and reading the real file back through the real
        loader is what turns that into an immediate failure here.
        """
        from ...job_persistence import load_persisted_state

        state_path = tmp_path / "managed-jobs.json"
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=4,
            state_path=state_path,
        )

        def admit(
            name: str,
            *,
            start_paused: bool = False,
            idempotency_key: str | None = None,
        ) -> str:
            created = manager.create(
                JobSpec(
                    JobOperation.INDEX,
                    JobSource.CODE,
                    str(tmp_path / name),
                    JobMode.REBUILD,
                ),
                JobInitiator("test", "transition_reload", None),
                start_paused=start_paused,
                idempotency_key=idempotency_key,
            )
            assert created.job is not None
            return created.job.id

        if sequence == "created":
            admit("a")
        elif sequence == "start_paused":
            admit("a", start_paused=True)
        elif sequence == "paused":
            manager.set_desired_state(admit("a"), DesiredJobState.PAUSED)
        elif sequence == "quiesce_deferred":
            # Work parked by a quiesce is persisted paused while still wanting
            # to run, and the resume pass selects on exactly that pair. A
            # loader refusing it rejects the daemon's own shutdown artifact.
            assert (
                manager.defer_unstarted_for_quiesce(admit("a")).code
                == "quiesce_deferred_before_start"
            )
        elif sequence == "cancelled":
            manager.set_desired_state(admit("a"), DesiredJobState.CANCELLED)
        elif sequence == "resumed":
            manager.set_desired_state(
                admit("a", start_paused=True), DesiredJobState.RUNNING
            )
        elif sequence == "failed_unstarted":
            manager.fail_unstarted(admit("a"), result="no runtime")
        elif sequence == "retried":
            job_id = admit("a")
            manager.fail_unstarted(job_id, result="no runtime")
            assert manager.retry(job_id).code == "job_retry_created"
        elif sequence == "deleted":
            job_id = admit("a")
            manager.fail_unstarted(job_id, result="no runtime")
            assert manager.delete(job_id).code == "job_deleted"
        else:
            admit("a", idempotency_key="replay-key")

        # The real file the daemon would find on its next start, read by the
        # real loader that start would use.
        assert state_path.is_file()
        load_persisted_state(state_path)
