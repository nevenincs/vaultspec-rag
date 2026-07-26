"""Unit tests for ``jobs.py``.

Covers (no GPU required):
- The jobs facade contains no duplicated ``_bg_run`` closures, while both
  production runners in ``job_dispatch`` call ``load_model()`` before
  ``lease()`` (AST structural regression guard).
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
import os
import subprocess
import sys
import textwrap
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

from .. import job_manager, job_models
from .. import jobs as jobs_module
from ..job_control import PauseRequested, QuiesceGate, RunControlToken
from ..job_manager import JobManager
from ..job_models import (
    DesiredJobState,
    JobInitiator,
    JobMode,
    JobOperation,
    JobOutcome,
    JobResourceSnapshot,
    JobSource,
    JobSpec,
    JobState,
)
from ..jobs import (
    index_job_status,
    record_finish,
    record_start,
    reset,
    snapshot,
)
from ..service import ServiceRegistry

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ..embeddings import EmbeddingModel

pytestmark = [pytest.mark.unit]

# Dedup-identity placeholders, never touched on disk. Built with os.sep so
# each resolves absolute on both platforms: POSIX joins to "/name" outright,
# Windows' abspath resolves the drive-relative "\name" against the current
# drive - unlike a hardcoded drive-letter literal, which is absolute only on a
# host whose current drive happens to match and is a plain relative path (and
# therefore rejected by job_models.job_spec_error) on POSIX.
_TEST_PROJECT_ROOT = os.path.abspath(os.path.join(os.sep, "project"))
_TEST_PROJECT_ROOT_OTHER = os.path.abspath(os.path.join(os.sep, "other"))
_TEST_PROJECT_ROOT_DIFFERENT = os.path.abspath(os.path.join(os.sep, "different"))


def test_canonical_job_models_are_reexported_by_identity() -> None:
    assert set(job_models.__all__) <= set(jobs_module.__all__)
    for name in job_models.__all__:
        assert getattr(jobs_module, name) is getattr(job_models, name)


def test_job_manager_boundary_is_reexported_by_identity() -> None:
    assert jobs_module.JobManager is job_manager.JobManager
    assert jobs_module.MAX_RECORDS is job_manager.MAX_RECORDS
    assert job_manager.logger.name == jobs_module.logger.name == "vaultspec_rag.jobs"


def test_job_manager_import_does_not_load_legacy_jobs_facade() -> None:
    probe = """
import sys

sys.path.insert(0, sys.argv[1])

from vaultspec_rag.job_manager import JobManager as direct_manager  # absolute-import-ok

assert "vaultspec_rag.jobs" not in sys.modules

from vaultspec_rag.jobs import JobManager as compatibility_manager  # absolute-import-ok

assert compatibility_manager is direct_manager
"""
    completed = subprocess.run(
        [sys.executable, "-c", probe, str(Path(__file__).parents[2])],
        capture_output=True,
        text=True,
        timeout=30.0,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""


# ---------------------------------------------------------------------------
# AST regression guard
# ---------------------------------------------------------------------------


def _function_node_named(tree: ast.Module, name: str) -> ast.FunctionDef:
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


def _parse_job_dispatch_module() -> ast.Module:
    import vaultspec_rag.job_dispatch as dispatch_mod

    src = inspect.getsource(dispatch_mod)
    return ast.parse(textwrap.dedent(src))


class TestIndexDispatchLoadModelBeforeLease:
    """AST guard for the extracted production indexing dispatch module."""

    def test_dispatch_implementations_are_extracted_from_jobs_facade(self) -> None:
        jobs_tree = _parse_jobs_module()
        jobs_functions = {
            node.name
            for node in ast.walk(jobs_tree)
            if isinstance(node, ast.FunctionDef)
        }
        dispatch_tree = _parse_job_dispatch_module()
        dispatch_functions = {
            node.name
            for node in ast.walk(dispatch_tree)
            if isinstance(node, ast.FunctionDef)
        }
        assert "_bg_run" not in jobs_functions
        assert {"_run_vault_attempt", "_run_code_attempt"} <= dispatch_functions

    def test_load_model_before_lease_in_vault_dispatch(self) -> None:
        tree = _parse_job_dispatch_module()
        node = _function_node_named(tree, "_run_vault_attempt")
        calls = _call_names_in_order(node)
        assert "load_model" in calls, "_run_vault_attempt must call load_model()"
        assert "lease" in calls, "_run_vault_attempt must call lease()"
        load_idx = calls.index("load_model")
        lease_idx = calls.index("lease")
        assert load_idx < lease_idx, (
            f"load_model() (pos {load_idx}) must appear before lease() "
            f"(pos {lease_idx}) in _run_vault_attempt"
        )

    def test_load_model_before_lease_in_codebase_dispatch(self) -> None:
        tree = _parse_job_dispatch_module()
        node = _function_node_named(tree, "_run_code_attempt")
        calls = _call_names_in_order(node)
        assert "load_model" in calls, "_run_code_attempt must call load_model()"
        assert "lease" in calls, "_run_code_attempt must call lease()"
        load_idx = calls.index("load_model")
        lease_idx = calls.index("lease")
        assert load_idx < lease_idx, (
            f"load_model() (pos {load_idx}) must appear before lease() "
            f"(pos {lease_idx}) in _run_code_attempt"
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
        from ..server._routes_jobs import _job_matches

        record = self._paused_canonical_record()
        now = cast("float", record["created_at"])
        assert _job_matches(
            record,
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
        )
        assert not _job_matches(
            record,
            phase=None,
            source=None,
            trigger=None,
            query=None,
            failed=False,
            job_id=None,
            since_seconds=None,
            now=now,
            desired_state="running",
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
        from typing import get_args, get_type_hints

        from typer.models import OptionInfo

        from ..cli._service_jobs import service_jobs

        annotation = get_type_hints(service_jobs, include_extras=True)["json_mode"]
        option = next(
            meta for meta in get_args(annotation)[1:] if isinstance(meta, OptionInfo)
        )
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
            _TEST_PROJECT_ROOT,
            JobMode.INCREMENTAL,
        )
        initiator = JobInitiator("cli", "server job create", _TEST_PROJECT_ROOT)

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
                _TEST_PROJECT_ROOT_OTHER,
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
            _TEST_PROJECT_ROOT,
            JobMode.REBUILD,
        )
        initiator = JobInitiator("http", "POST /jobs", _TEST_PROJECT_ROOT)

        original = manager.create(spec, initiator, idempotency_key="request-7")
        replay = manager.create(spec, initiator, idempotency_key="request-7")
        conflict = manager.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.CODE,
                _TEST_PROJECT_ROOT_DIFFERENT,
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
            Path(str(get_config().status_dir)).expanduser() / "jobs-state.json"
        )
        assert memory_only.state_path is None

    def test_managed_state_path_expands_home_relative_status_dir(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A ``~``-prefixed status dir never resolves to a cwd-relative ``~``.

        Binds to the ``expanduser()`` in the managed state-path resolution:
        without it, a service started from any working directory persists its
        canonical job state under ``./~/...`` relative to that directory,
        forking durable job state per start directory instead of sharing the
        one managed home location.
        """
        from pathlib import Path

        from ..config import EnvVar, reset_config

        monkeypatch.setenv(EnvVar.STATUS_DIR.value, "~/.vaultspec-rag-jobs-guard")
        reset_config()
        try:
            managed = JobManager(max_nonterminal=1)
            assert managed.state_path is not None
            assert "~" not in managed.state_path.parts
            assert managed.state_path == (
                Path.home() / ".vaultspec-rag-jobs-guard" / "jobs-state.json"
            )
        finally:
            monkeypatch.undo()
            reset_config()

    def test_idempotency_aliases_and_key_length_are_bounded(self) -> None:
        manager = JobManager(
            max_nonterminal=1,
            max_terminal_history=1,
            state_path=None,
        )
        spec = JobSpec(
            JobOperation.INDEX,
            JobSource.VAULT,
            _TEST_PROJECT_ROOT,
            JobMode.INCREMENTAL,
        )
        initiator = JobInitiator("http", "POST /jobs", _TEST_PROJECT_ROOT)

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
        missing_root = manager.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.VAULT,
                None,
                JobMode.INCREMENTAL,
            ),
            JobInitiator("http", "POST /jobs", None),
        )
        relative_root = manager.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.CODE,
                "relative/project",
                JobMode.REBUILD,
            ),
            JobInitiator("cli", "server job create", "relative/project"),
        )

        assert maintenance.code == "invalid_job_spec"
        assert invalid_source.code == "invalid_job_spec"
        assert missing_root.code == "invalid_job_spec"
        assert relative_root.code == "invalid_job_spec"
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


def _create_paused_vault_job(manager: JobManager) -> str:
    spec = JobSpec(
        JobOperation.INDEX,
        JobSource.VAULT,
        _TEST_PROJECT_ROOT,
        JobMode.INCREMENTAL,
    )
    initiator = JobInitiator("cli", "server job create", _TEST_PROJECT_ROOT)
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
    replay = manager.set_desired_state(
        job_id,
        DesiredJobState.PAUSED,
        expected_revision=1,
    )
    assert replay.code == "already_satisfied"
    conflict = manager.set_desired_state(
        job_id,
        DesiredJobState.RUNNING,
        expected_revision=1,
    )
    assert conflict.code == "revision_conflict"
    return job_id


def _resume_paused_job(manager: JobManager, job_id: str) -> None:
    resumed = manager.set_desired_state(
        job_id,
        DesiredJobState.RUNNING,
        expected_revision=2,
    )
    assert resumed.job is not None
    assert resumed.job.attempt.number == 2
    assert resumed.job.state is JobState.QUEUED


def _assert_delivered_pause_requeues_resume(
    manager: JobManager,
    job_id: str,
    task: asyncio.Task[Any],
    control: RunControlToken,
) -> None:
    started = manager.start_attempt(job_id, task=task, control=control)
    assert started.job is not None
    assert started.job.state is JobState.RUNNING
    pause = manager.set_desired_state(job_id, DesiredJobState.PAUSED)
    assert pause.code == "pause_requested"
    with pytest.raises(PauseRequested):
        control.checkpoint()

    committed_resume = manager.set_desired_state(job_id, DesiredJobState.RUNNING)
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
    stale = manager.acknowledge_control(job_id, attempt=2, task=task)
    assert stale.code == "stale_attempt_ignored"


class TestManagedJobTransitions:
    """Revision and attempt identity make lifecycle races deterministic."""

    @pytest.mark.asyncio
    async def test_shutdown_closes_the_attempt_claim_boundary(self) -> None:
        manager = JobManager(max_nonterminal=1, state_path=None)
        created = manager.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.CODE,
                _TEST_PROJECT_ROOT,
                JobMode.INCREMENTAL,
            ),
            JobInitiator("service", "shutdown-race", _TEST_PROJECT_ROOT),
        )
        assert created.job is not None
        task = asyncio.create_task(asyncio.Event().wait())
        try:
            assert manager.begin_shutdown() == ()
            outcome = manager.start_attempt(
                created.job.id,
                task=task,
                control=RunControlToken(),
            )
            assert outcome.code == "dispatch_stopped"
            retained = manager.get(created.job.id)
            assert retained is not None
            assert retained.state is JobState.QUEUED
            assert retained.runtime.task_active is False
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_pause_resume_race_requeues_after_delivered_unwind(self) -> None:
        manager = JobManager(max_nonterminal=2, state_path=None)
        job_id = _create_paused_vault_job(manager)
        _resume_paused_job(manager, job_id)

        task = asyncio.create_task(asyncio.Event().wait())
        control = RunControlToken()
        try:
            _assert_delivered_pause_requeues_resume(manager, job_id, task, control)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_progress_requires_the_exact_current_attempt_and_task(self) -> None:
        manager = JobManager(max_nonterminal=1, state_path=None)
        spec = JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            _TEST_PROJECT_ROOT,
            JobMode.INCREMENTAL,
        )
        created = manager.create(
            spec,
            JobInitiator("watcher", "watcher_code_index", _TEST_PROJECT_ROOT),
        )
        assert created.job is not None
        owner_task = asyncio.create_task(asyncio.Event().wait())
        stale_task = asyncio.create_task(asyncio.Event().wait())
        try:
            assert (
                manager.start_attempt(
                    created.job.id,
                    task=owner_task,
                    control=RunControlToken(),
                ).code
                == "attempt_started"
            )
            assert (
                manager.update_progress(
                    created.job.id,
                    attempt=1,
                    task=stale_task,
                    step="embed",
                    completed=1,
                    total=2,
                ).code
                == "stale_attempt_ignored"
            )
            assert (
                manager.update_progress(
                    created.job.id,
                    attempt=1,
                    task=owner_task,
                    step=cast("str", 7),
                ).code
                == "invalid_progress"
            )
            assert (
                manager.update_progress(
                    created.job.id,
                    attempt=1,
                    task=owner_task,
                    step="embed",
                    completed=cast("int", 1.5),
                    total=cast("int", 2.0),
                ).code
                == "invalid_progress"
            )
            updated = manager.update_progress(
                created.job.id,
                attempt=1,
                task=owner_task,
                step="embed",
                completed=1,
                total=2,
            )
            assert updated.code == "progress_updated"
            assert updated.job is not None
            assert updated.job.progress is not None
            assert updated.job.progress.step == "embed"
            assert updated.job.progress.completed == 1
            assert updated.job.revision == created.job.revision + 2
            assert (
                manager.update_progress(
                    created.job.id,
                    attempt=2,
                    task=owner_task,
                    step="publish",
                ).code
                == "stale_attempt_ignored"
            )
            unchanged = manager.get(created.job.id)
            assert unchanged is not None
            assert unchanged.progress == updated.job.progress
        finally:
            owner_task.cancel()
            stale_task.cancel()
            for task in (owner_task, stale_task):
                with pytest.raises(asyncio.CancelledError):
                    await task

    @pytest.mark.asyncio
    async def test_cancellation_is_immediate_or_acknowledged_after_unwind(
        self,
    ) -> None:
        spec = JobSpec(
            JobOperation.INDEX,
            JobSource.VAULT,
            _TEST_PROJECT_ROOT,
            JobMode.INCREMENTAL,
        )
        initiator = JobInitiator("cli", "server job stop", _TEST_PROJECT_ROOT)

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
            _TEST_PROJECT_ROOT,
            JobMode.REBUILD,
        )
        initiator = JobInitiator("http", "POST /jobs", _TEST_PROJECT_ROOT)
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


@pytest.mark.asyncio
async def test_dispatched_attempt_token_observes_shared_quiesce_gate() -> None:
    """Pausing the manager-injected gate parks a dispatched attempt's token.

    Guard: the negative half (the attempt does not pass its checkpoint while
    the gate is paused) is bounded so a token built without the shared gate
    fails the not-passed assertion instead of hanging. The mutation that
    proves red is constructing the dispatch token without the manager's gate.
    """
    gate = QuiesceGate()
    manager = JobManager(max_nonterminal=1, state_path=None, quiesce_gate=gate)
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            _TEST_PROJECT_ROOT,
            JobMode.REBUILD,
        ),
        JobInitiator("cli", "server job create", _TEST_PROJECT_ROOT),
    )
    assert created.job is not None
    job_id = created.job.id
    reached = threading.Event()
    passed = threading.Event()
    finished = threading.Event()

    def runner(
        context: job_manager.JobAttemptContext,
    ) -> job_manager.JobExecutionResult:
        reached.set()
        context.control.checkpoint()
        passed.set()
        return job_manager.JobExecutionResult(summary="done")

    def on_finished(
        snapshot: job_models.JobSnapshot,
        duration_seconds: float,
        result: job_manager.JobExecutionResult | None,
        error: BaseException | None,
    ) -> None:
        del snapshot, duration_seconds, result, error
        finished.set()

    assert (
        manager.bind_dispatch(job_id, runner, on_finished=on_finished).code
        == "dispatch_bound"
    )
    gate.pause()
    # The gate must reopen even on a red assertion, or the parked attempt
    # worker outlives the test and hangs the suite at interpreter exit.
    try:
        assert manager.dispatch(job_id).code == "attempt_started"
        assert await asyncio.to_thread(reached.wait, 5.0)
        assert not await asyncio.to_thread(passed.wait, 0.5), (
            "dispatched attempt did not park at the shared paused gate"
        )
    finally:
        gate.resume()
    assert await asyncio.to_thread(passed.wait, 5.0), (
        "dispatched attempt did not resume with the shared gate"
    )
    assert await asyncio.to_thread(finished.wait, 5.0)
    final = manager.get(job_id)
    assert final is not None
    assert final.state is JobState.SUCCEEDED


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
        import threading

        from ..job_manager import JobAttemptContext, JobExecutionResult

        manager = JobManager(max_nonterminal=4, state_path=None)
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
        from ..job_manager import JobAttemptContext, JobExecutionResult

        manager = JobManager(max_nonterminal=2, state_path=None)
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
            "storage_ops.py",
            "storage_manifest.py",
            "search/_searcher.py",
            "server/_lifespan.py",
        ):
            source = (package_root / rel).read_text(encoding="utf-8")
            assert "get_encode_limiter" not in source, (
                f"{rel} must not reference the encode admission slot"
            )


class TestGpuLockWaitTelemetry:
    """Timed GPU-lock acquisition accumulates per attempt and publishes."""

    def test_timed_acquire_credits_the_active_scope(self) -> None:
        import threading

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
        import threading

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
        import threading
        import time as time_module

        from ..job_control import timed_gpu_lock
        from ..job_manager import JobAttemptContext, JobExecutionResult

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
        import threading

        from ..job_manager import JobAttemptContext, JobExecutionResult

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
        from ..storage_ops import ReclaimPolicy, evaluate_reclaim
        from ..store import VaultStore

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
        for rel in ("store.py", "indexer/_donor_candidates.py"):
            source = (package_root / rel).read_text(encoding="utf-8")
            assert "get_encode_limiter" not in source, (
                f"{rel} must not reference the encode admission slot"
            )
            assert "QuiesceGate" not in source, (
                f"{rel} must not consult the quiesce gate"
            )


class TestInterruptedJobDegradationSplit:
    """An interrupted run degrades the project index view, never health.

    The two surfaces answer different questions and their degrading state sets
    differ because of it. Nothing else pins that difference, so a change to
    either selector would otherwise pass silently as a tidy-up; both directions
    are asserted here so the split reads as a decision rather than an oversight.
    """

    @pytest.mark.asyncio
    async def test_an_interrupted_run_degrades_the_project_index_status(
        self,
        tmp_path: Path,
    ) -> None:
        """The index that run was building is incomplete, so it must be flagged.

        The interruption is produced the way a daemon death produces it: a
        started attempt is persisted, and a fresh manager restores that state
        and finds an attempt no live worker owns. No state is hand-written.
        """
        state_path = tmp_path / "managed-jobs.json"
        manager = JobManager(max_nonterminal=2, state_path=state_path)
        created = manager.create(
            JobSpec(
                JobOperation.INDEX,
                JobSource.CODE,
                str(tmp_path),
                JobMode.INCREMENTAL,
            ),
            JobInitiator("service", "degradation split coverage", str(tmp_path)),
        )
        assert created.job is not None
        task = asyncio.create_task(asyncio.Event().wait())
        try:
            started = manager.start_attempt(
                created.job.id,
                task=task,
                control=RunControlToken(),
            )
            assert started.job is not None
            assert started.job.state is JobState.RUNNING

            restarted = JobManager(max_nonterminal=2, state_path=state_path)
            assert restarted.restore_persisted().code == "job_state_restored"
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        interrupted = restarted.get(created.job.id)
        assert interrupted is not None
        assert interrupted.state is JobState.INTERRUPTED

        status = index_job_status(tmp_path, manager=restarted, now=1_000_000.0)
        # The reason token is asserted, not merely the presence of an entry:
        # a "stalled" or "failed" entry here would mean the interrupted state
        # reached the check under some other branch and proves nothing.
        assert status["degraded_reasons"] == [
            {
                "source": "code",
                "job_id": created.job.id,
                "reason": "interrupted",
                "error_kind": "interrupted",
            }
        ]

    def test_an_interrupted_run_leaves_service_health_undegraded(
        self,
        isolated_status_dir: Path,
    ) -> None:
        """Serving is unimpaired by an interruption, so health must stay clean.

        The record is asserted present in the rollup before the empty reason
        list is asserted. Without that, the test could not tell "the health
        selector considered an interrupted job and declined it" from "no
        interrupted job ever reached the selector", and only the first is the
        property being defended.
        """
        del isolated_status_dir
        from ..jobs import restore_interrupted
        from ..server._lifespan import _jobs_health

        reset()
        try:
            job_id = record_start("code", "tool")
            # Losing the in-memory ring while the persisted snapshot survives
            # is exactly what a killed daemon leaves behind.
            reset()
            assert restore_interrupted() == 1
            records = {record["id"]: record for record in snapshot()}
            assert records[job_id]["phase"] == "interrupted"

            jobs_health, degraded_reasons = _jobs_health()
        finally:
            reset()

        states = cast("dict[str, int]", jobs_health["states"])
        assert states.get("interrupted") == 1, (
            "the interrupted record must reach the health rollup, or the "
            "empty reason list below would prove nothing"
        )
        # The empty reason list is asserted before the corroborating detail
        # below, so widening the health selector breaks the property this test
        # defends rather than an incidental consequence of it.
        assert degraded_reasons == []
        assert jobs_health["last_failed"] is None
