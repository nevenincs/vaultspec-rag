"""Unit tests for ``jobs.py``.

Covers (no GPU required):
- Both ``_bg_run`` closures in ``start_reindex_vault`` and
  ``start_reindex_codebase`` call ``load_model()`` before ``lease()``
  (AST structural assertion — regression guard for the fix).
- ``ServiceRegistry.load_model()`` is idempotent: a second call when
  ``_model`` is already set returns immediately without touching CUDA
  (proven by injecting a sentinel and asserting it is unchanged).
- ``jobs`` module-level helpers (``record_start``/``record_finish``/
  ``snapshot``) are exercised to ensure basic lifecycle correctness.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import logging
import textwrap
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, cast

import pytest

from ..job_control import PauseRequested, RunControlToken
from ..jobs import (
    DesiredJobState,
    JobInitiator,
    JobManager,
    JobMode,
    JobOperation,
    JobOutcome,
    JobResourceSnapshot,
    JobSource,
    JobSpec,
    JobState,
    record_finish,
    record_start,
    reset,
    snapshot,
)
from ..service import ServiceRegistry

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ..embeddings import EmbeddingModel

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# AST regression guard
# ---------------------------------------------------------------------------


def _function_node_named(  # pyright: ignore[reportUnusedFunction]
    tree: ast.Module, name: str
) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Function '{name}' not found in AST")


def _call_names_in_order(func_node: ast.FunctionDef) -> list[str]:
    """Return the dotted call names in textual order within *func_node*."""
    names: list[str] = []
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            match node.func:
                case ast.Attribute(attr=attr):
                    names.append(attr)
                case ast.Name(id=name):
                    names.append(name)
                case _:
                    pass
    return names


def _parse_jobs_module() -> ast.Module:
    import vaultspec_rag.jobs as jobs_mod

    src = inspect.getsource(jobs_mod)
    return ast.parse(textwrap.dedent(src))


class TestBgRunLoadModelBeforeLease:
    """AST-level guard: load_model() must precede lease() in both closures."""

    def _find_bg_run_nodes(self, tree: ast.Module) -> list[ast.FunctionDef]:
        return [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_bg_run"
        ]

    def test_two_bg_run_closures_exist(self) -> None:
        tree = _parse_jobs_module()
        nodes = self._find_bg_run_nodes(tree)
        assert len(nodes) == 2, (
            f"Expected exactly 2 _bg_run closures, found {len(nodes)}"
        )

    def test_load_model_before_lease_in_vault_bg_run(self) -> None:
        tree = _parse_jobs_module()
        nodes = self._find_bg_run_nodes(tree)
        # First _bg_run belongs to start_reindex_vault
        calls = _call_names_in_order(nodes[0])
        assert "load_model" in calls, "_bg_run (vault) must call load_model()"
        assert "lease" in calls, "_bg_run (vault) must call lease()"
        load_idx = calls.index("load_model")
        lease_idx = calls.index("lease")
        assert load_idx < lease_idx, (
            f"load_model() (pos {load_idx}) must appear before lease() "
            f"(pos {lease_idx}) in _bg_run (vault)"
        )

    def test_load_model_before_lease_in_codebase_bg_run(self) -> None:
        tree = _parse_jobs_module()
        nodes = self._find_bg_run_nodes(tree)
        # Second _bg_run belongs to start_reindex_codebase
        calls = _call_names_in_order(nodes[1])
        assert "load_model" in calls, "_bg_run (code) must call load_model()"
        assert "lease" in calls, "_bg_run (code) must call lease()"
        load_idx = calls.index("load_model")
        lease_idx = calls.index("lease")
        assert load_idx < lease_idx, (
            f"load_model() (pos {load_idx}) must appear before lease() "
            f"(pos {lease_idx}) in _bg_run (code)"
        )


# ---------------------------------------------------------------------------
# load_model() idempotency — no GPU needed
# ---------------------------------------------------------------------------


class TestLoadModelIdempotency:
    """load_model() is a no-op when _model is already set."""

    def test_second_call_does_not_overwrite_existing_model(self) -> None:
        """Inject a sentinel into _model; second load_model() must leave it."""
        reg = ServiceRegistry()
        sentinel = cast("EmbeddingModel", object())
        # Bypass the real EmbeddingModel construction by injecting directly.
        reg._model = sentinel
        reg.load_model()  # must return without touching _model
        assert reg._model is sentinel, (
            "load_model() must be idempotent: it replaced the existing model"
        )

    def test_model_property_raises_before_load(self) -> None:
        reg = ServiceRegistry()
        with pytest.raises(RuntimeError, match="call load_model\\(\\) first"):
            _ = reg.model

    def test_model_property_succeeds_after_sentinel_inject(self) -> None:
        reg = ServiceRegistry()
        sentinel = cast("EmbeddingModel", object())
        reg._model = sentinel
        assert reg.model is sentinel


# ---------------------------------------------------------------------------
# jobs module basic lifecycle
# ---------------------------------------------------------------------------


class TestJobsLifecycle:
    def setup_method(self) -> None:
        reset()

    def test_record_start_returns_id(self) -> None:
        job_id = record_start("vault", "tool")
        assert isinstance(job_id, str) and len(job_id) == 32

    def test_snapshot_contains_started_record(self) -> None:
        job_id = record_start("vault", "tool")
        records = snapshot()
        ids = [r["id"] for r in records]
        assert job_id in ids

    def test_record_finish_transitions_to_done(self) -> None:
        job_id = record_start("code", "watcher")
        record_finish(job_id, result="ok")
        records = {r["id"]: r for r in snapshot()}
        assert records[job_id]["phase"] == "done"

    def test_record_finish_transitions_to_error(self) -> None:
        job_id = record_start("vault", "watcher")
        record_finish(job_id, error="boom")
        records = {r["id"]: r for r in snapshot()}
        assert records[job_id]["phase"] == "error"
        assert records[job_id]["result"] == "boom"

    def test_snapshot_is_newest_first(self) -> None:
        id1 = record_start("vault", "tool")
        id2 = record_start("code", "tool")
        ids = [r["id"] for r in snapshot()]
        assert ids.index(id2) < ids.index(id1)

    def test_started_record_defaults_preprocess_fields(self) -> None:
        job_id = record_start("code", "tool")
        record = {r["id"]: r for r in snapshot()}[job_id]
        assert record["preprocess_ok"] == 0
        assert record["preprocess_skipped"] == 0
        assert record["preprocess_failures"] == []

    def test_record_finish_surfaces_preprocess_failures(self) -> None:
        job_id = record_start("code", "tool")
        failures = ["docs/a.pdf: extractor timeout", "docs/b.xls: exit 1"]
        record_finish(
            job_id,
            result="+0 /0 -0 (5ms) ~2",
            preprocess_ok=3,
            preprocess_skipped=2,
            preprocess_failures=failures,
        )
        record = {r["id"]: r for r in snapshot()}[job_id]
        assert record["preprocess_ok"] == 3
        assert record["preprocess_skipped"] == 2
        assert record["preprocess_failures"] == failures

    def test_serialized_preprocess_failures_are_copied(self) -> None:
        job_id = record_start("code", "tool")
        failures = ["docs/a.pdf: timeout"]
        record_finish(job_id, preprocess_failures=failures)
        serialized = {r["id"]: r for r in snapshot()}[job_id]
        surfaced = serialized["preprocess_failures"]
        assert surfaced == failures
        # The snapshot is a defensive copy: mutating it must not touch live
        # registry state, nor the caller's list survive into the record.
        assert isinstance(surfaced, list)
        cast("list[str]", surfaced).append("docs/c.pdf: injected")
        again = {r["id"]: r for r in snapshot()}[job_id]
        assert again["preprocess_failures"] == failures

    def test_job_events_preserve_job_id_and_phase_fields(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.INFO, logger="vaultspec_rag.jobs"):
            job_id = record_start("vault", "tool", command="reindex_vault")
            record_finish(job_id, result="ok")

        messages = [
            record.getMessage()
            for record in caplog.records
            if record.name == "vaultspec_rag.jobs"
        ]
        assert any(
            "service.job event=started" in message
            and f"job_id={job_id}" in message
            and "source=vault" in message
            and "phase=running" in message
            for message in messages
        )
        assert any(
            "service.job event=finished" in message
            and f"job_id={job_id}" in message
            and "phase=done" in message
            for message in messages
        )


class TestJobErrorKind:
    """Failed jobs carry a stable ``error_kind`` classification."""

    def setup_method(self) -> None:
        reset()

    def _finished(
        self,
        *,
        result: str | None = None,
        error: str | None = None,
    ) -> dict[str, object]:
        job_id = record_start("code", "tool")
        record_finish(job_id, result=result, error=error)
        return {r["id"]: r for r in snapshot()}[job_id]

    def test_disk_full_error_is_classified(self) -> None:
        record = self._finished(error="[Errno 28] No space left on device")
        assert record["error_kind"] == "disk_full"

    def test_wal_disk_full_text_is_classified(self) -> None:
        record = self._finished(
            error=(
                "Service internal error: No space left on device: "
                "WAL buffer size exceeds available disk space"
            )
        )
        assert record["error_kind"] == "disk_full"

    def test_timeout_error_is_classified(self) -> None:
        record = self._finished(error="the read operation timed out")
        assert record["error_kind"] == "timeout"

    def test_unclassified_error_is_other(self) -> None:
        record = self._finished(error="boom")
        assert record["error_kind"] == "other"

    def test_success_has_no_error_kind(self) -> None:
        record = self._finished(result="+1 /0 -0 (5ms)")
        assert record["error_kind"] is None

    def test_started_record_defaults_error_kind_none(self) -> None:
        job_id = record_start("vault", "tool")
        record = {r["id"]: r for r in snapshot()}[job_id]
        assert record["error_kind"] is None


class TestJobStallShaping:
    """The /jobs shaping computes the service-domain ``stalled`` flag."""

    def _running_record(
        self,
        *,
        step: str,
        age_seconds: float,
        now: float,
    ) -> dict[str, object]:
        return {
            "id": "j1",
            "phase": "running",
            "started_at": now - age_seconds - 10.0,
            "finished_at": None,
            "error_kind": None,
            "progress": {
                "step": step,
                "completed": 0,
                "total": 100,
                "last_updated": now - age_seconds,
            },
        }

    def test_running_job_past_threshold_is_stalled(self) -> None:
        from ..server._routes_jobs import _job_with_liveness

        now = 1_000_000.0
        record = self._running_record(
            step="embed + upsert chunks", age_seconds=400.0, now=now
        )
        assert _job_with_liveness(record, now=now)["stalled"] is True

    def test_waiting_job_is_never_stalled(self) -> None:
        from ..server._routes_jobs import _job_with_liveness

        now = 1_000_000.0
        record = self._running_record(step="queued", age_seconds=400.0, now=now)
        assert _job_with_liveness(record, now=now)["stalled"] is False

    def test_fresh_progress_is_not_stalled(self) -> None:
        from ..server._routes_jobs import _job_with_liveness

        now = 1_000_000.0
        record = self._running_record(step="embed", age_seconds=10.0, now=now)
        assert _job_with_liveness(record, now=now)["stalled"] is False

    def test_summary_counts_stalled_and_error_kinds(self) -> None:
        from ..server._routes_jobs import _job_summary

        now = 1_000_000.0
        stalled = self._running_record(step="embed", age_seconds=400.0, now=now)
        failed: dict[str, object] = {
            "id": "j2",
            "phase": "error",
            "started_at": now - 50.0,
            "finished_at": now - 40.0,
            "error_kind": "disk_full",
            "progress": None,
        }
        summary = _job_summary([stalled, failed], now=now)
        assert summary["stalled"] == 1
        assert summary["error_kinds"] == {"disk_full": 1}


class TestJobsHumanSummarySignpost:
    """The human jobs feed routes scripted consumers to --json: its summary
    unconditionally contains the words "active" and "waiting", so grepping it
    for job states self-deadlocks."""

    def test_summary_carries_the_json_signpost(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from ..cli._service_jobs import _render_jobs_feed

        _render_jobs_feed({"total": 0, "returned": 0}, [], port=8766)
        out = capsys.readouterr().out
        assert "0 active, 0 waiting" in out
        assert "--json" in out
        assert "Scripting:" in out

    def test_json_help_warns_about_the_summary_words(self) -> None:
        import re

        from ..cli._service_jobs import service_jobs

        source = inspect.getsource(service_jobs)
        match = re.search(r'"--json",\s*help=\(([^)]*)\)', source)
        assert match is not None
        assert "scripted waits" in match.group(1)


class TestInterruptedJobRestore:
    """Jobs a dead daemon left running come back as ``interrupted``."""

    @pytest.fixture(autouse=True)
    def _own_status_dir(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> Iterator[None]:
        from ..config import reset_config

        monkeypatch.setenv("VAULTSPEC_RAG_STATUS_DIR", str(tmp_path / "status"))
        reset_config()
        reset()
        yield
        reset()
        reset_config()

    def test_running_job_survives_a_simulated_daemon_death(self) -> None:
        from ..jobs import restore_interrupted

        job_id = record_start("code", "tool", command="reindex_codebase")
        # Simulate the daemon dying: the in-memory ring vanishes, the
        # persisted snapshot stays.
        reset()
        assert snapshot() == []
        assert restore_interrupted() == 1
        records = {r["id"]: r for r in snapshot()}
        record = records[job_id]
        assert record["phase"] == "interrupted"
        assert record["result"] == "daemon terminated while this job was running"
        initiator = record["initiator"]
        assert isinstance(initiator, dict)
        assert cast("dict[str, object]", initiator)["command"] == "reindex_codebase"

    def test_finished_jobs_are_not_restored(self) -> None:
        from ..jobs import restore_interrupted

        job_id = record_start("vault", "tool")
        record_finish(job_id, result="ok")
        reset()
        assert restore_interrupted() == 0
        assert snapshot() == []

    def test_restore_is_not_repeated_on_second_startup(self) -> None:
        from ..jobs import restore_interrupted

        record_start("code", "tool")
        reset()
        assert restore_interrupted() == 1
        reset()
        assert restore_interrupted() == 0

    def test_missing_snapshot_restores_nothing(self) -> None:
        from ..jobs import restore_interrupted

        assert restore_interrupted() == 0


class TestMachineServiceTestGuard:
    """The terminate path refuses to act from an unisolated test run."""

    def test_unisolated_pytest_env_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from ..cli._service_stop import _refuse_terminate_from_unisolated_test

        monkeypatch.delenv("VAULTSPEC_RAG_STATUS_DIR", raising=False)
        monkeypatch.delenv("VAULTSPEC_RAG_QDRANT_STORAGE_DIR", raising=False)
        with pytest.raises(RuntimeError, match="refusing to terminate"):
            _refuse_terminate_from_unisolated_test()

    def test_isolated_env_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from ..cli._service_stop import _refuse_terminate_from_unisolated_test

        monkeypatch.setenv("VAULTSPEC_RAG_STATUS_DIR", "somewhere-isolated")
        _refuse_terminate_from_unisolated_test()


class TestSuiteIsolationGuard:
    """The session conftest points the machine-singleton dirs at tmp."""

    def test_machine_dirs_are_isolated_for_the_suite(self) -> None:
        import os
        from pathlib import Path

        from ..config import EnvVar

        machine_default = Path("~/.vaultspec-rag").expanduser()
        status = os.environ.get(EnvVar.STATUS_DIR.value)
        storage = os.environ.get(EnvVar.QDRANT_STORAGE_DIR.value)
        assert status is not None
        assert storage is not None
        assert Path(status).expanduser() != machine_default
        assert not Path(storage).expanduser().is_relative_to(machine_default)


class TestManagedJobAdmission:
    """The canonical manager owns admission and replay under real contention."""

    def test_concurrent_equivalent_creates_share_one_exact_job(self) -> None:
        manager = JobManager(max_nonterminal=1, state_path=None)
        spec = JobSpec(
            JobOperation.INDEX,
            JobSource.VAULT,
            "Y:/project",
            JobMode.INCREMENTAL,
        )
        initiator = JobInitiator("cli", "server job create", "Y:/project")

        def submit(_index: int) -> JobOutcome:
            return manager.create(spec, initiator)

        with ThreadPoolExecutor(max_workers=8) as workers:
            outcomes = list(workers.map(submit, range(32)))

        created = [outcome for outcome in outcomes if outcome.code == "job_created"]
        assert len(created) == 1
        assert created[0].job is not None
        exact_id = created[0].job.id
        assert {outcome.job.id for outcome in outcomes if outcome.job is not None} == {
            exact_id
        }
        assert manager.get(exact_id) is not None
        assert manager.get(exact_id[:8]) is None

        capacity = manager.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.CODE,
                "Y:/other",
                JobMode.REBUILD,
            ),
            initiator,
        )
        assert capacity.code == "job_capacity_exceeded"

    def test_idempotency_replays_only_the_original_request(self) -> None:
        manager = JobManager(max_nonterminal=2, state_path=None)
        spec = JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            "Y:/project",
            JobMode.REBUILD,
        )
        initiator = JobInitiator("http", "POST /jobs", "Y:/project")

        original = manager.create(spec, initiator, idempotency_key="request-7")
        replay = manager.create(spec, initiator, idempotency_key="request-7")
        conflict = manager.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.CODE,
                "Y:/different",
                JobMode.REBUILD,
            ),
            initiator,
            idempotency_key="request-7",
        )

        assert original.code == "job_created"
        assert replay.code == "idempotency_replayed"
        assert replay.job == original.job
        assert conflict.code == "idempotency_key_conflict"
        assert conflict.job == original.job

    def test_default_storage_is_managed_and_memory_only_is_explicit(self) -> None:
        from pathlib import Path

        from ..config import get_config

        managed = JobManager(max_nonterminal=1)
        memory_only = JobManager(max_nonterminal=1, state_path=None)

        assert managed.state_path == (
            Path(str(get_config().status_dir)) / "jobs-state.json"
        )
        assert memory_only.state_path is None

    def test_idempotency_aliases_and_key_length_are_bounded(self) -> None:
        manager = JobManager(
            max_nonterminal=1,
            max_terminal_history=1,
            state_path=None,
        )
        spec = JobSpec(
            JobOperation.INDEX,
            JobSource.VAULT,
            "Y:/project",
            JobMode.INCREMENTAL,
        )
        initiator = JobInitiator("http", "POST /jobs", "Y:/project")

        assert manager.create(spec, initiator, idempotency_key="key-0").code == (
            "job_created"
        )
        assert manager.create(spec, initiator, idempotency_key="key-1").code == (
            "active_job_exists"
        )
        assert manager.create(spec, initiator, idempotency_key="key-2").code == (
            "active_job_exists"
        )
        assert manager.create(spec, initiator, idempotency_key="key-0").code == (
            "active_job_exists"
        )
        assert manager.create(spec, initiator, idempotency_key="x" * 257).code == (
            "invalid_idempotency_key"
        )

    def test_invalid_job_kinds_are_not_admitted(self) -> None:
        manager = JobManager(max_nonterminal=1, state_path=None)
        maintenance = manager.create(
            JobSpec(
                JobOperation.MAINTENANCE,
                JobSource.MAINTENANCE,
                None,
                None,
            ),
            JobInitiator("schedule", "storage maintenance", None),
        )
        invalid_source = manager.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.MAINTENANCE,
                None,
                JobMode.INCREMENTAL,
            ),
            JobInitiator("schedule", "invalid index", None),
        )

        assert maintenance.code == "invalid_job_spec"
        assert invalid_source.code == "invalid_job_spec"
        assert manager.active() == []

    def test_equivalent_root_spellings_deduplicate(self, tmp_path: Path) -> None:
        manager = JobManager(max_nonterminal=2, state_path=None)
        initiator = JobInitiator("cli", "server job create", str(tmp_path))
        canonical = JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            str(tmp_path),
            JobMode.INCREMENTAL,
        )
        alias = JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            str(tmp_path / "uncreated" / ".."),
            JobMode.INCREMENTAL,
        )

        created = manager.create(canonical, initiator)
        deduplicated = manager.create(alias, initiator)

        assert created.code == "job_created"
        assert deduplicated.code == "active_job_exists"
        assert deduplicated.job == created.job


class TestManagedJobTransitions:
    """Revision and attempt identity make lifecycle races deterministic."""

    @pytest.mark.asyncio
    async def test_pause_resume_race_requeues_after_delivered_unwind(self) -> None:
        manager = JobManager(max_nonterminal=2, state_path=None)
        spec = JobSpec(
            JobOperation.INDEX,
            JobSource.VAULT,
            "Y:/project",
            JobMode.INCREMENTAL,
        )
        initiator = JobInitiator("cli", "server job create", "Y:/project")
        created = manager.create(spec, initiator)
        assert created.job is not None
        job_id = created.job.id

        stale_change = manager.set_desired_state(
            job_id,
            DesiredJobState.PAUSED,
            expected_revision=0,
        )
        assert stale_change.code == "revision_conflict"

        paused = manager.set_desired_state(
            job_id,
            DesiredJobState.PAUSED,
            expected_revision=1,
        )
        assert paused.job is not None
        assert paused.job.state is JobState.PAUSED
        assert paused.job.revision == 2
        assert (
            manager.set_desired_state(
                job_id,
                DesiredJobState.PAUSED,
                expected_revision=1,
            ).code
            == "already_satisfied"
        )
        assert (
            manager.set_desired_state(
                job_id,
                DesiredJobState.RUNNING,
                expected_revision=1,
            ).code
            == "revision_conflict"
        )

        resumed = manager.set_desired_state(
            job_id,
            DesiredJobState.RUNNING,
            expected_revision=2,
        )
        assert resumed.job is not None
        assert resumed.job.attempt.number == 2
        assert resumed.job.state is JobState.QUEUED

        task = asyncio.create_task(asyncio.Event().wait())
        control = RunControlToken()
        try:
            started = manager.start_attempt(job_id, task=task, control=control)
            assert started.job is not None
            assert started.job.state is JobState.RUNNING
            assert (
                manager.set_desired_state(job_id, DesiredJobState.PAUSED).code
                == "pause_requested"
            )
            with pytest.raises(PauseRequested):
                control.checkpoint()

            committed_resume = manager.set_desired_state(
                job_id, DesiredJobState.RUNNING
            )
            assert committed_resume.job is not None
            assert committed_resume.job.state is JobState.PAUSING
            assert committed_resume.job.desired_state is DesiredJobState.RUNNING

            acknowledged = manager.acknowledge_control(
                job_id,
                attempt=2,
                task=task,
            )
            assert acknowledged.code == "resume_requeued"
            assert acknowledged.job is not None
            assert acknowledged.job.state is JobState.QUEUED
            assert acknowledged.job.attempt.number == 3
            assert (
                manager.acknowledge_control(job_id, attempt=2, task=task).code
                == "stale_attempt_ignored"
            )
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_cancellation_is_immediate_or_acknowledged_after_unwind(
        self,
    ) -> None:
        spec = JobSpec(
            JobOperation.INDEX,
            JobSource.VAULT,
            "Y:/project",
            JobMode.INCREMENTAL,
        )
        initiator = JobInitiator("cli", "server job stop", "Y:/project")

        queued_manager = JobManager(max_nonterminal=1, state_path=None)
        queued = queued_manager.create(spec, initiator)
        assert queued.job is not None
        immediate = queued_manager.set_desired_state(
            queued.job.id,
            DesiredJobState.CANCELLED,
        )
        assert immediate.job is not None
        assert immediate.job.state is JobState.CANCELLED
        assert immediate.job.timestamps.control_acknowledged_at is not None
        assert (
            queued_manager.set_desired_state(
                queued.job.id,
                DesiredJobState.CANCELLED,
                expected_revision=1,
            ).code
            == "already_satisfied"
        )

        running_manager = JobManager(max_nonterminal=1, state_path=None)
        running = running_manager.create(spec, initiator)
        assert running.job is not None
        task = asyncio.create_task(asyncio.Event().wait())
        control = RunControlToken()
        try:
            running_manager.start_attempt(running.job.id, task=task, control=control)
            assert running_manager.set_worker_active(
                running.job.id,
                task=task,
                active=True,
            )
            assert running_manager.set_execution_resources(
                running.job.id,
                task=task,
                resources=JobResourceSnapshot(
                    started=None,
                    finished=None,
                    pipeline_active=True,
                ),
            )
            running_manager.set_desired_state(
                running.job.id,
                DesiredJobState.PAUSED,
            )
            cancelling = running_manager.set_desired_state(
                running.job.id,
                DesiredJobState.CANCELLED,
            )
            assert cancelling.job is not None
            assert cancelling.job.state is JobState.CANCELLING
            control_snapshot = control.snapshot()
            assert control_snapshot.desired is not None
            assert control_snapshot.desired.value == "cancel"
            assert (
                running_manager.acknowledge_control(
                    running.job.id,
                    attempt=1,
                    task=task,
                ).code
                == "resources_still_owned"
            )
            assert running_manager.set_worker_active(
                running.job.id,
                task=task,
                active=False,
            )
            assert running_manager.set_execution_resources(
                running.job.id,
                task=task,
                resources=JobResourceSnapshot(started=None, finished=None),
            )
            acknowledged = running_manager.acknowledge_control(
                running.job.id,
                attempt=1,
                task=task,
            )
            assert acknowledged.job is not None
            assert acknowledged.job.state is JobState.CANCELLED
            assert (
                running_manager.set_desired_state(
                    running.job.id,
                    DesiredJobState.RUNNING,
                ).code
                == "invalid_transition"
            )
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_terminal_first_writer_retry_and_delete_contract(self) -> None:
        manager = JobManager(
            max_nonterminal=2,
            max_terminal_history=2,
            state_path=None,
        )
        spec = JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            "Y:/project",
            JobMode.REBUILD,
        )
        initiator = JobInitiator("http", "POST /jobs", "Y:/project")
        created = manager.create(spec, initiator)
        assert created.job is not None
        job_id = created.job.id
        task = asyncio.create_task(asyncio.Event().wait())
        control = RunControlToken()
        try:
            assert manager.start_attempt(job_id, task=task, control=control).code == (
                "attempt_started"
            )
            failed = manager.finish_attempt(
                job_id,
                attempt=1,
                task=task,
                state=JobState.FAILED,
                result="index failed",
                error_kind="other",
            )
            assert failed.job is not None
            assert failed.job.state is JobState.FAILED
            assert (
                manager.finish_attempt(
                    job_id,
                    attempt=1,
                    task=task,
                    state=JobState.SUCCEEDED,
                    result="late success",
                ).job
                == failed.job
            )
            assert (
                manager.set_desired_state(job_id, DesiredJobState.RUNNING).code
                == "invalid_transition"
            )
            assert (
                manager.set_desired_state(
                    job_id,
                    DesiredJobState.CANCELLED,
                    mode="force",
                ).code
                == "force_termination_unavailable"
            )

            retried = manager.retry(job_id)
            assert retried.job is not None
            assert retried.job.id != job_id
            assert retried.job.attempt.parent_job_id == job_id
            assert manager.delete(retried.job.id).code == "job_not_terminal"
            assert manager.delete(job_id).code == "job_deleted"
            assert manager.get(job_id) is None
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
