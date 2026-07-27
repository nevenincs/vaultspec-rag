"""Cohesive unit coverage for job-management behavior."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, cast

import pytest

from ..job_manager.manager import JobManager
from ..job_models import (
    JobInitiator,
    JobMode,
    JobOperation,
    JobSource,
    JobSpec,
)
from ..jobs import (
    _FinishDetails,
    index_job_status,
    record_finish,
    record_start,
    reset,
    snapshot,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


pytestmark = [pytest.mark.unit]

_TEST_PROJECT_ROOT = os.path.abspath(os.path.join(os.sep, "project"))
_TEST_PROJECT_ROOT_OTHER = os.path.abspath(os.path.join(os.sep, "other"))
_TEST_PROJECT_ROOT_DIFFERENT = os.path.abspath(os.path.join(os.sep, "different"))


class TestJobsLifecycle:
    def setup_method(self) -> None:
        reset()

    def test_record_start_returns_id(self) -> None:
        job_id = record_start(JobSource.VAULT, "tool")
        assert isinstance(job_id, str) and len(job_id) == 32

    def test_snapshot_contains_started_record(self) -> None:
        job_id = record_start(JobSource.VAULT, "tool")
        records = snapshot()
        ids = [r["id"] for r in records]
        assert job_id in ids

    def test_record_finish_transitions_to_done(self) -> None:
        job_id = record_start(JobSource.CODE, "watcher")
        record_finish(job_id, result="ok")
        records = {r["id"]: r for r in snapshot()}
        assert records[job_id]["phase"] == "done"

    def test_record_finish_transitions_to_error(self) -> None:
        job_id = record_start(JobSource.VAULT, "watcher")
        record_finish(job_id, error="boom")
        records = {r["id"]: r for r in snapshot()}
        assert records[job_id]["phase"] == "error"
        assert records[job_id]["result"] == "boom"

    def test_snapshot_is_newest_first(self) -> None:
        id1 = record_start(JobSource.VAULT, "tool")
        id2 = record_start(JobSource.CODE, "tool")
        ids = [r["id"] for r in snapshot()]
        assert ids.index(id2) < ids.index(id1)

    def test_started_record_defaults_preprocess_fields(self) -> None:
        job_id = record_start(JobSource.CODE, "tool")
        record = {r["id"]: r for r in snapshot()}[job_id]
        assert record["preprocess_ok"] == 0
        assert record["preprocess_skipped"] == 0
        assert record["preprocess_failures"] == []

    def test_record_finish_surfaces_preprocess_failures(self) -> None:
        job_id = record_start(JobSource.CODE, "tool")
        failures = ["docs/a.pdf: extractor timeout", "docs/b.xls: exit 1"]
        record_finish(
            job_id,
            result="+0 /0 -0 (5ms) ~2",
            details=_FinishDetails(
                preprocess_ok=3,
                preprocess_skipped=2,
                preprocess_failures=failures,
            ),
        )
        record = {r["id"]: r for r in snapshot()}[job_id]
        assert record["preprocess_ok"] == 3
        assert record["preprocess_skipped"] == 2
        assert record["preprocess_failures"] == failures

    def test_serialized_preprocess_failures_are_copied(self) -> None:
        job_id = record_start(JobSource.CODE, "tool")
        failures = ["docs/a.pdf: timeout"]
        record_finish(job_id, details=_FinishDetails(preprocess_failures=failures))
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
            job_id = record_start(JobSource.VAULT, "tool", command="reindex_vault")
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
        job_id = record_start(JobSource.CODE, "tool")
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
        job_id = record_start(JobSource.VAULT, "tool")
        record = {r["id"]: r for r in snapshot()}[job_id]
        assert record["error_kind"] is None


class TestJobStallShaping:
    """The /jobs shaping computes the service-domain ``stalled`` flag."""

    def _paused_canonical_record(self) -> dict[str, object]:
        manager = JobManager(max_nonterminal=2, state_path=None)
        created = manager.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.VAULT,
                _TEST_PROJECT_ROOT,
                JobMode.INCREMENTAL,
            ),
            JobInitiator("cli", "server job create", _TEST_PROJECT_ROOT),
            start_paused=True,
        )
        assert created.job is not None
        return created.job.to_dict()

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

    def test_legacy_paused_projection_is_never_running_or_stalled(self) -> None:
        from ..server._routes_jobs import _job_with_liveness

        now = 1_000_000.0
        record = self._running_record(step="paused", age_seconds=400.0, now=now)
        record["resources"] = {}
        shaped = _job_with_liveness(record, now=now)

        assert shaped["state"] == "paused"
        assert shaped["phase"] == "paused"
        assert shaped["stalled"] is False
        assert "current" not in cast("dict[str, object]", shaped["resources"])

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

    def test_canonical_paused_snapshot_keeps_compatibility_shape(self) -> None:
        from ..server._routes_jobs import _job_with_liveness

        record = self._paused_canonical_record()
        now = cast("float", record["created_at"]) + 400.0
        shaped = _job_with_liveness(record, now=now)

        assert shaped["state"] == "paused"
        assert shaped["desired_state"] == "paused"
        assert shaped["phase"] == "paused"
        assert shaped["source"] == "vault"
        assert shaped["trigger"] == "tool"
        assert shaped["runtime_seconds"] is None
        assert shaped["control_request_age_seconds"] == 400.0
        assert shaped["control_acknowledged_age_seconds"] == 400.0
        assert shaped["control_acknowledgement_seconds"] == 0.0
        assert shaped["control_pending_age_seconds"] is None
        assert shaped["stalled"] is False
        assert "current" not in cast("dict[str, object]", shaped["resources"])

    def test_canonical_filters_use_state_desired_state_and_capabilities(self) -> None:
        from ..server._routes_jobs import JobFilter, _job_matches

        record = self._paused_canonical_record()
        now = cast("float", record["created_at"])
        assert _job_matches(
            record,
            JobFilter(
                phase="paused",
                source="vault",
                trigger="tool",
                query="project",
                failed=False,
                job_id=str(record["id"])[:8],
                since_seconds=0.0,
                now=now,
                state="paused",
                desired_state="paused",
                controllable=True,
            ),
        )
        assert not _job_matches(
            record,
            JobFilter(
                phase=None,
                source=None,
                trigger=None,
                query=None,
                failed=False,
                job_id=None,
                since_seconds=None,
                now=now,
                desired_state="running",
            ),
        )

    def test_transitional_stall_uses_pending_control_age(self) -> None:
        from ..server._routes_jobs import _job_with_liveness

        now = 1_000_000.0
        record = self._paused_canonical_record()
        record.update(
            {
                "state": "pausing",
                "phase": "running",
                "control_requested_at": now - 400.0,
                "control_acknowledged_at": None,
                "progress": None,
                "resources": {},
            }
        )
        shaped = _job_with_liveness(record, now=now)

        assert shaped["phase"] == "pausing"
        assert shaped["control_pending_age_seconds"] == 400.0
        assert shaped["stalled"] is True
        assert "current" not in cast("dict[str, object]", shaped["resources"])

    def test_summary_and_ordering_are_canonical_and_actionable(self) -> None:
        from ..server._routes_jobs import _job_summary, _prioritise_running_jobs

        now = 1_000_000.0
        paused = self._paused_canonical_record()
        pausing = {
            **paused,
            "id": "pausing",
            "state": "pausing",
            "desired_state": "paused",
            "control_requested_at": now - 10.0,
            "control_acknowledged_at": None,
        }
        failed: dict[str, object] = {
            "id": "failed",
            "phase": "error",
            "source": "codebase",
            "trigger": "watcher",
            "error_kind": "disk_full",
        }
        succeeded: dict[str, object] = {"id": "succeeded", "phase": "done"}
        records = [succeeded, failed, paused, pausing]

        ordered = _prioritise_running_jobs(records)
        assert [record["id"] for record in ordered] == [
            "pausing",
            paused["id"],
            "failed",
            "succeeded",
        ]
        summary = _job_summary(records, now=now)
        assert summary["states"] == {
            "succeeded": 1,
            "failed": 1,
            "paused": 1,
            "pausing": 1,
        }
        assert summary["desired_states"] == {"unknown": 2, "paused": 2}
        assert summary["active"] == 2
        assert summary["terminal"] == 2
        assert summary["transitional"] == 1
        assert summary["controllable"] == 2
        assert summary["control_pending"] == 1
        assert summary["error_kinds"] == {"disk_full": 1}


def test_index_job_status_reports_latest_generation_and_degradation(
    tmp_path: Path,
) -> None:
    manager = JobManager(max_nonterminal=3, state_path=None)
    initiator = JobInitiator("service", "status coverage", str(tmp_path))
    created = {
        source: manager.create(
            JobSpec(
                JobOperation.INDEX,
                source,
                str(tmp_path),
                JobMode.INCREMENTAL,
            ),
            initiator,
        )
        for source in (JobSource.VAULT, JobSource.CODE, JobSource.DOCUMENT)
    }
    document = created[JobSource.DOCUMENT].job
    assert document is not None
    assert (
        manager.fail_unstarted(
            document.id,
            result="extractor unavailable",
        ).job
        is not None
    )

    status = index_job_status(tmp_path, manager=manager, now=1_000_000.0)
    sources = cast("dict[str, object]", status["sources"])
    document_status = cast("dict[str, object]", sources["document"])
    assert set(sources) == {"vault", "code", "document"}
    assert document_status["job_id"] == document.id
    assert document_status["generation"] == 1
    assert document_status["state"] == "failed"
    assert document_status["desired_state"] == "running"
    assert document_status["attempt"] == {
        "number": 1,
        "parent_job_id": None,
        "resumed_from_attempt": None,
        "resume_strategy": None,
    }
    assert document_status["progress"] is None
    timestamps = cast("dict[str, object]", document_status["timestamps"])
    assert timestamps["finished_at"] is not None
    assert status["degraded_reasons"] == [
        {
            "source": "document",
            "job_id": document.id,
            "reason": "failed",
            "error_kind": "unavailable",
        }
    ]


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
        # Read the declared option metadata rather than regexing the module
        # source. The source form is a formatting choice - `help="..."` and
        # `help=("..." "...")` declare the same option - so a regex demanding
        # the parenthesised form fails on a pure reformat that changed no
        # behaviour. Reading the file also made this assertion sensitive to an
        # edit landing mid-run, because `inspect.getsource` goes through
        # `linecache`. The declared metadata is what Typer renders, which is
        # the contract this test exists to defend.
        from typer.main import get_command

        from ..cli._app import app

        server = get_command(app).get_command(None, "server")
        assert server is not None
        jobs = server.get_command(None, "jobs")
        assert jobs is not None
        option = next(parameter for parameter in jobs.params if parameter.name == "json")
        assert "scripted waits" in (option.help or "")


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

        job_id = record_start(JobSource.CODE, "tool", command="reindex_codebase")
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

        job_id = record_start(JobSource.VAULT, "tool")
        record_finish(job_id, result="ok")
        reset()
        assert restore_interrupted() == 0
        assert snapshot() == []

    def test_restore_is_not_repeated_on_second_startup(self) -> None:
        from ..jobs import restore_interrupted

        record_start(JobSource.CODE, "tool")
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
