"""Tests for the in-flight activity registry (#142).

Two layers, no mocks/skips/monkeypatch:

- Unit-style: drive ``_jobs.record_start`` / ``record_finish`` / ``snapshot``
  directly to assert the record schema, the bounded ring-buffer behaviour, and
  thread-safety under real concurrent writers.
- Integration (GPU): call the real ``reindex_vault`` / ``reindex_codebase``
  MCP tools against a real indexed workspace (reusing the session-scoped
  ``embedding_model`` fixture and the global-registry pattern from
  ``test_watcher_control.py``) and assert a finished ``trigger="tool"`` entry
  lands in the snapshot.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import TYPE_CHECKING, cast

import pytest

import vaultspec_rag.mcp._tools as tools

from ... import jobs as _jobs
from ... import server
from ...job_control import RunControlToken
from ...job_manager._control import _AttemptTerminal
from ...job_manager.manager import JobManager
from ...job_models import (
    DesiredJobState,
    JobInitiator,
    JobMode,
    JobOperation,
    JobSource,
    JobSpec,
    JobState,
)
from ...serviceclient._discovery import _default_service_port
from ...serviceclient._transport import _try_http_admin
from ._helpers import _make_root

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# Match the real service-job deadline used by storage survey integration. This
# is deliberately separate from the 30-second timeout for one admin HTTP call.
_JOB_COMPLETION_TIMEOUT_SECONDS = 120.0
_JOB_POLL_INTERVAL_SECONDS = 0.1
_TERMINAL_JOB_PHASES = frozenset({"done", "error", "failed"})


@pytest.fixture
def _clean_jobs(  # pyright: ignore[reportUnusedFunction]
) -> Iterator[None]:
    """Reset the registry before/after each test and stop any watcher.

    The reindex tools start a filesystem watcher via ``_ensure_watcher``
    as a side effect; stop them on teardown so the GPU integration tests
    do not leak watcher tasks across the session (mirrors
    ``test_watcher_control.py``).
    """
    _jobs.reset()
    yield
    server._stop_all_watchers()
    _jobs.reset()


async def _wait_for_terminal_job(
    job_id: str,
    *,
    timeout: float = _JOB_COMPLETION_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Wait within the established real service-job completion budget."""
    deadline = time.monotonic() + timeout
    last_response: dict[str, object] = {}
    last_job: dict[str, object] | None = None
    port = _default_service_port()
    assert port is not None, f"service port unavailable while waiting for job {job_id}"

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            pytest.fail(
                f"job {job_id} did not reach a terminal phase within {timeout:g}s; "
                f"last_job={last_job!r}; last_response={last_response!r}"
            )

        response = await asyncio.to_thread(
            _try_http_admin,
            "get_jobs",
            {"job_id": job_id},
            port,
            timeout=remaining,
        )
        last_response = response or {}
        raw_jobs = last_response.get("jobs", [])
        jobs = cast("list[dict[str, object]]", raw_jobs)
        last_job = next((job for job in jobs if job.get("id") == job_id), None)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            pytest.fail(
                f"job {job_id} did not reach a terminal phase within {timeout:g}s; "
                f"last_job={last_job!r}; last_response={last_response!r}"
            )
        if last_job is not None and last_job.get("phase") in _TERMINAL_JOB_PHASES:
            return last_job

        await asyncio.sleep(min(_JOB_POLL_INTERVAL_SECONDS, remaining))


def _assert_runtime_context(raw: object) -> dict[str, object]:
    assert isinstance(raw, dict)
    runtime = cast("dict[str, object]", raw)
    assert isinstance(runtime["pid"], int)
    assert isinstance(runtime["parent_pid"], int)
    assert isinstance(runtime["user"], str)
    assert isinstance(runtime["executable"], str)
    assert isinstance(runtime["prefix"], str)
    assert isinstance(runtime["base_prefix"], str)
    return runtime


def _assert_resource_snapshot(raw: object) -> dict[str, object]:
    assert isinstance(raw, dict)
    resources = cast("dict[str, object]", raw)
    assert isinstance(resources["rss_mb"], float)
    assert isinstance(resources["cuda_allocated_mb"], float)
    assert isinstance(resources["cuda_reserved_mb"], float)
    return resources


def _assert_running_job_snapshot(entry: dict[str, object], job_id: str) -> None:
    assert entry["id"] == job_id
    assert entry["source"] == "vault"
    assert entry["trigger"] == "tool"
    assert entry["phase"] == "running"
    assert isinstance(entry["started_at"], float)
    assert entry["finished_at"] is None
    assert entry["result"] is None
    _assert_runtime_context(entry["runtime"])
    resources = _assert_resources(entry)
    _assert_resource_snapshot(resources["started"])
    assert resources["finished"] is None


def _assert_done_job_snapshot(entry: dict[str, object], job_id: str) -> None:
    assert entry["id"] == job_id
    assert entry["phase"] == "done"
    finished_at = entry["finished_at"]
    started_at = entry["started_at"]
    assert isinstance(finished_at, float)
    assert isinstance(started_at, float)
    assert finished_at >= started_at
    assert entry["result"] == "+1 /0 -0 (5ms)"
    assert isinstance(_assert_resources(entry)["finished"], dict)


def _assert_resources(entry: dict[str, object]) -> dict[str, object]:
    resources = entry["resources"]
    assert isinstance(resources, dict)
    return cast("dict[str, object]", resources)


# --------------------------------------------------------------------------- #
# Unit-style: schema, bounding, concurrency                                   #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_record_start_then_finish_produces_done_snapshot(_clean_jobs: None) -> None:
    job_id = _jobs.record_start(JobSource.VAULT, "tool")

    running = _jobs.snapshot()
    assert len(running) == 1
    _assert_running_job_snapshot(running[0], job_id)

    _jobs.record_finish(job_id, result="+1 /0 -0 (5ms)")

    finished = _jobs.snapshot()
    assert len(finished) == 1
    _assert_done_job_snapshot(finished[0], job_id)


@pytest.mark.unit
def test_record_finish_with_error_sets_error_phase(_clean_jobs: None) -> None:
    job_id = _jobs.record_start(JobSource.CODE, "watcher")
    _jobs.record_finish(job_id, error="boom")

    entry = _jobs.snapshot()[0]
    assert entry["source"] == "code"
    assert entry["trigger"] == "watcher"
    assert entry["phase"] == "error"
    assert entry["result"] == "boom"
    assert isinstance(entry["finished_at"], float)


@pytest.mark.unit
def test_record_finish_unknown_id_is_noop(_clean_jobs: None) -> None:
    job_id = _jobs.record_start(JobSource.VAULT, "tool")
    _jobs.record_finish("does-not-exist", result="ignored")

    entries = _jobs.snapshot()
    assert len(entries) == 1
    assert entries[0]["id"] == job_id
    assert entries[0]["phase"] == "running"


@pytest.mark.unit
def test_snapshot_is_newest_first(_clean_jobs: None) -> None:
    first = _jobs.record_start(JobSource.VAULT, "tool")
    second = _jobs.record_start(JobSource.CODE, "tool")
    third = _jobs.record_start(JobSource.VAULT, "watcher")

    ids = [entry["id"] for entry in _jobs.snapshot()]
    assert ids == [third, second, first]


@pytest.mark.unit
def test_snapshot_returns_independent_copies(_clean_jobs: None) -> None:
    _jobs.record_start(JobSource.VAULT, "tool", command="reindex_vault")
    snap = _jobs.snapshot()
    snap[0]["phase"] = "tampered"
    initiator = snap[0]["initiator"]
    assert isinstance(initiator, dict)
    initiator = cast("dict[str, object]", initiator)
    initiator["command"] = "tampered"
    resources = snap[0]["resources"]
    assert isinstance(resources, dict)
    resources = cast("dict[str, object]", resources)
    started_resources = resources["started"]
    assert isinstance(started_resources, dict)
    started_resources = cast("dict[str, object]", started_resources)
    started_resources["rss_mb"] = -1.0

    assert _jobs.snapshot()[0]["phase"] == "running"
    next_initiator = _jobs.snapshot()[0]["initiator"]
    assert isinstance(next_initiator, dict)
    next_initiator = cast("dict[str, object]", next_initiator)
    assert next_initiator["command"] == "reindex_vault"
    next_resources = _jobs.snapshot()[0]["resources"]
    assert isinstance(next_resources, dict)
    next_resources = cast("dict[str, object]", next_resources)
    next_started_resources = next_resources["started"]
    assert isinstance(next_started_resources, dict)
    next_started_resources = cast("dict[str, object]", next_started_resources)
    assert next_started_resources["rss_mb"] != -1.0


@pytest.mark.unit
def test_registry_is_bounded(_clean_jobs: None) -> None:
    overflow = _jobs.MAX_RECORDS + 50
    ids = [_jobs.record_start(JobSource.VAULT, "tool") for _ in range(overflow)]

    snap = _jobs.snapshot()
    assert len(snap) == _jobs.MAX_RECORDS

    # Newest-first: the most recent record must be the last id started, and
    # the oldest retained must be the first id NOT evicted.
    assert snap[0]["id"] == ids[-1]
    assert snap[-1]["id"] == ids[-_jobs.MAX_RECORDS]

    # Evicted ids are gone entirely.
    retained_ids = {entry["id"] for entry in snap}
    assert ids[0] not in retained_ids


@pytest.mark.unit
def test_concurrent_writers_do_not_corrupt(_clean_jobs: None) -> None:
    writers = 8
    per_writer = 100
    barrier = threading.Barrier(writers)

    def _worker() -> None:
        barrier.wait()
        for _ in range(per_writer):
            jid = _jobs.record_start(JobSource.VAULT, "tool")
            _jobs.record_finish(jid, result="ok")

    threads = [threading.Thread(target=_worker) for _ in range(writers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    snap = _jobs.snapshot()
    # The buffer is bounded, so the final count is exactly the cap (total
    # writes far exceed MAX_RECORDS).
    assert len(snap) == _jobs.MAX_RECORDS

    # No record is corrupt: every retained entry carries the full schema,
    # unique ids, and a consistent phase/result pairing.
    seen_ids: set[str] = set()
    for entry in snap:
        assert {
            "id",
            "source",
            "trigger",
            "phase",
            "started_at",
            "finished_at",
            "result",
            "progress",
            "initiator",
            "runtime",
            "resources",
        } <= set(entry)
        entry_id = entry["id"]
        assert isinstance(entry_id, str)
        assert entry_id not in seen_ids
        seen_ids.add(entry_id)
        assert entry["source"] == "vault"
        assert entry["trigger"] == "tool"
        # All work completed before join(), so every retained record is done.
        assert entry["phase"] == "done"
        assert entry["result"] == "ok"
        assert isinstance(entry["finished_at"], float)


class TestManagedJobPersistence:
    """Canonical lifecycle state survives real atomic filesystem boundaries."""

    pytestmark = pytest.mark.unit

    def test_paused_state_and_idempotency_restore_under_the_same_id(
        self,
        tmp_path: Path,
    ) -> None:
        state_path = tmp_path / "managed-jobs.json"
        manager = JobManager(max_nonterminal=2, state_path=state_path)
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

        restarted = JobManager(max_nonterminal=2, state_path=state_path)
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
        manager = JobManager(max_nonterminal=2, state_path=state_path)

        created = manager.create(canonical_spec, canonical_initiator)
        deduplicated = manager.create(
            alias_spec,
            alias_initiator,
            idempotency_key="equivalent-request",
        )
        assert created.job is not None
        assert deduplicated.job is not None
        assert deduplicated.job.id == created.job.id

        restarted = JobManager(max_nonterminal=2, state_path=state_path)
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
        manager = JobManager(max_nonterminal=2, state_path=state_path)
        spec = JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            str(tmp_path),
            JobMode.REBUILD,
        )
        initiator = JobInitiator("cli", "server job create", str(tmp_path))
        created = manager.create(spec, initiator)
        assert created.job is not None
        owner_task = asyncio.create_task(asyncio.Event().wait())
        stale_task = asyncio.create_task(asyncio.Event().wait())
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

            restarted = JobManager(max_nonterminal=2, state_path=state_path)
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
        completed_task = asyncio.create_task(asyncio.Event().wait())
        interrupted_task = asyncio.create_task(asyncio.Event().wait())
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
                    _AttemptTerminal(
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
        manager = JobManager(max_nonterminal=1, state_path=state_path)
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

    def test_invalid_state_does_not_partially_restore(self, tmp_path: Path) -> None:
        state_path = tmp_path / "managed-jobs.json"
        state_path.write_text(
            '{"schema":"vaultspec.rag.jobs","version":1,"jobs":[',
            encoding="utf-8",
        )
        manager = JobManager(max_nonterminal=1, state_path=state_path)

        outcome = manager.restore_persisted()

        assert outcome.code == "job_state_invalid"
        assert manager.list_jobs() == []

    def test_failed_persistence_rolls_back_reversible_intent(
        self,
        tmp_path: Path,
    ) -> None:
        state_path = tmp_path / "managed-jobs.json"
        manager = JobManager(max_nonterminal=1, state_path=state_path)
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
        manager = JobManager(max_nonterminal=1, state_path=state_path)
        spec = JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            str(tmp_path),
            JobMode.REBUILD,
        )
        initiator = JobInitiator("cli", "server job create", str(tmp_path))
        created = manager.create(spec, initiator)
        assert created.job is not None
        task = asyncio.create_task(asyncio.Event().wait())
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
                _AttemptTerminal(
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

            restarted = JobManager(max_nonterminal=1, state_path=state_path)
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

    def test_structurally_valid_inconsistent_state_is_rejected(
        self,
        tmp_path: Path,
    ) -> None:
        state_path = tmp_path / "managed-jobs.json"
        manager = JobManager(max_nonterminal=1, state_path=state_path)
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
        inconsistent = JobManager(max_nonterminal=1, state_path=state_path)
        assert inconsistent.restore_persisted().code == "job_state_invalid"
        assert inconsistent.list_jobs() == []

        payload["jobs"][0]["desired_state"] = "running"
        payload["idempotency"][0]["job_id"] = "missing-job"
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        dangling = JobManager(max_nonterminal=1, state_path=state_path)
        assert dangling.restore_persisted().code == "job_state_invalid"
        assert dangling.list_jobs() == []

        payload["idempotency"][0]["job_id"] = payload["jobs"][0]["id"]
        payload["jobs"][0]["state"] = "running"
        payload["jobs"][0]["started_at"] = None
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        unstarted = JobManager(max_nonterminal=1, state_path=state_path)
        assert unstarted.restore_persisted().code == "job_state_invalid"
        assert unstarted.list_jobs() == []

        payload["jobs"][0]["state"] = "queued"
        payload["jobs"][0]["attempt"] = 2
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        unlinked_resume = JobManager(max_nonterminal=1, state_path=state_path)
        assert unlinked_resume.restore_persisted().code == "job_state_invalid"
        assert unlinked_resume.list_jobs() == []

        payload["jobs"][0]["attempt"] = 1
        payload["jobs"][0]["resumed_from_attempt"] = 1
        payload["jobs"][0]["resume_strategy"] = "reconcile"
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        false_first_resume = JobManager(max_nonterminal=1, state_path=state_path)
        assert false_first_resume.restore_persisted().code == "job_state_invalid"
        assert false_first_resume.list_jobs() == []

    def test_version_and_timestamp_invariants_are_strict(
        self,
        tmp_path: Path,
    ) -> None:
        state_path = tmp_path / "managed-jobs.json"
        manager = JobManager(max_nonterminal=1, state_path=state_path)
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
            invalid = JobManager(max_nonterminal=1, state_path=state_path)
            assert invalid.restore_persisted().code == "job_state_invalid"
            assert invalid.list_jobs() == []

        payload["version"] = 1
        job = payload["jobs"][0]
        job["control_acknowledged_at"] = job["created_at"]
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        unrequested_ack = JobManager(max_nonterminal=1, state_path=state_path)
        assert unrequested_ack.restore_persisted().code == "job_state_invalid"
        assert unrequested_ack.list_jobs() == []

        job["control_acknowledged_at"] = None
        job["state"] = "failed"
        job["started_at"] = job["created_at"] + 2
        job["state_changed_at"] = job["created_at"] + 1
        job["finished_at"] = job["created_at"]
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        impossible_finish = JobManager(max_nonterminal=1, state_path=state_path)
        assert impossible_finish.restore_persisted().code == "job_state_invalid"
        assert impossible_finish.list_jobs() == []

    def test_legacy_v1_start_paused_round_trip_has_control_request_lineage(
        self,
        tmp_path: Path,
    ) -> None:
        state_path = tmp_path / "managed-jobs.json"
        manager = JobManager(max_nonterminal=1, state_path=state_path)
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

        restarted = JobManager(max_nonterminal=1, state_path=state_path)
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
        manager = JobManager(max_nonterminal=3, state_path=state_path)
        tasks: list[asyncio.Task[bool]] = []
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
                event = asyncio.Event()
                task = asyncio.create_task(event.wait())
                tasks.append(task)
                assert (
                    manager.start_attempt(
                        created.job.id,
                        task=task,
                        control=RunControlToken(),
                    ).code
                    == "attempt_started"
                )

            restarted = JobManager(max_nonterminal=1, state_path=state_path)
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


# --------------------------------------------------------------------------- #
# Integration (GPU): real reindex tools write tool-triggered records          #
# --------------------------------------------------------------------------- #


@pytest.mark.integration
@pytest.mark.subprocess_gpu
@pytest.mark.usefixtures("live_service")
async def test_reindex_vault_records_finished_tool_job(
    tmp_path: Path,
) -> None:
    root = _make_root(tmp_path)

    response = await tools.reindex_vault(project_root=str(root))
    assert isinstance(response, dict)
    assert response["ok"] is True
    assert "job_id" in response

    job_id: str = cast("str", response["job_id"])
    job = await _wait_for_terminal_job(job_id)
    assert job["source"] == "vault"
    assert job["trigger"] == "tool"
    assert job["phase"] == "done"
    assert isinstance(job["finished_at"], float)
    assert isinstance(job["result"], str)


@pytest.mark.integration
@pytest.mark.subprocess_gpu
@pytest.mark.usefixtures("live_service")
async def test_reindex_codebase_records_finished_tool_job(
    tmp_path: Path,
) -> None:
    root = _make_root(tmp_path)

    response = await tools.reindex_codebase(project_root=str(root))
    assert isinstance(response, dict)
    assert response["ok"] is True
    assert "job_id" in response

    job_id: str = cast("str", response["job_id"])
    job = await _wait_for_terminal_job(job_id)
    assert job["source"] == "code"
    assert job["trigger"] == "tool"
    assert job["phase"] == "done"
    assert isinstance(job["finished_at"], float)
    assert isinstance(job["result"], str)
