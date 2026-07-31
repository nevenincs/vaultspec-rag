"""Cohesive unit coverage for job-management behavior."""

from __future__ import annotations

import ast
import inspect
import json
import math
import subprocess
import sys
import textwrap
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from .. import job_models
from .. import jobs as jobs_module
from ..job_manager import state as state_module
from ..job_manager._execution import logger as execution_logger
from ..job_manager.manager import JobManager
from ..job_models import (
    DesiredJobState,
    IndexResilienceSnapshot,
    JobAttempt,
    JobInitiator,
    JobMode,
    JobOperation,
    JobProgress,
    JobResourceSnapshot,
    JobRuntimeSnapshot,
    JobSnapshot,
    JobSource,
    JobSpec,
    JobState,
    JobTimestamps,
    ProcessResourceSnapshot,
    capabilities_for_state,
)
from ..job_persistence import (
    IdempotencyBinding,
    PersistedManagerState,
    load_persisted_state,
    save_persisted_state,
)
from ..service import ServiceRegistry
from ..service_quiesce import ServiceQuiesceController

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..embeddings import EmbeddingModel

pytestmark = [pytest.mark.unit]


def test_job_models_are_defined_exactly_once() -> None:
    # These names used to be re-exported through ``jobs`` as a compatibility
    # facade, and this test asserted the forwarding held. The facade is gone:
    # ``job_models`` is the definition site and consumers import from it. What
    # still matters is that no SECOND definition appears - two classes with one
    # name is how an isinstance check starts failing for no visible reason.
    for name in job_models.__all__:
        owner = getattr(job_models, name)
        assert getattr(owner, "__module__", job_models.__name__).endswith(
            ("job_models", "enum", "builtins")
        ), f"{name} is defined outside job_models ({owner!r})"
    assert not set(job_models.__all__) & set(jobs_module.__all__), (
        "jobs must not re-export job_models names; import them from job_models"
    )


def test_job_manager_logs_under_the_jobs_namespace() -> None:
    # The shared logger name is a real contract (operators filter on it) and is
    # independent of how the modules import each other.
    assert execution_logger.name == jobs_module.logger.name == "vaultspec_rag.jobs"


_OWNER_MODULES = (
    "_control.py",
    "_execution.py",
    "_persistence.py",
    "_progress.py",
    "_records.py",
)


def _owner_class(tree: ast.Module) -> ast.ClassDef:
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    owners = [node for node in classes if node.name.startswith("JobManager")]
    assert len(owners) == 1, "each owner module defines exactly one owner class"
    return owners[0]


def _declared_members(node: ast.ClassDef) -> set[str]:
    declared: set[str] = set()
    for statement in node.body:
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
            declared.add(statement.name)
        elif isinstance(statement, ast.AnnAssign) and isinstance(
            statement.target, ast.Name
        ):
            declared.add(statement.target.id)
    return declared


def _contract_class() -> ast.ClassDef:
    source = Path(state_module.__file__).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef) and node.name == "JobManagerState":
            for base in node.bases:
                if isinstance(base, ast.Name) and base.id == "Protocol":
                    return node
    raise AssertionError("job_manager.state declares no JobManagerState protocol")


def test_shared_owner_surface_is_declared_not_dynamic() -> None:
    # Responsibility for one coordinator is split across several owner classes,
    # so each one reaches state and behaviour a sibling owns. That surface has
    # to be declared member by member on the shared contract. A catch-all
    # ``__getattr__`` there would satisfy every such reference by typing it as
    # ``Any``, which silently retires type checking across the whole package -
    # and no configured rule reports it, so nothing else would catch the
    # regression. Both halves below are load-bearing: the first keeps the
    # escape hatch out, the second keeps the declarations complete.
    contract = _contract_class()
    declared = _declared_members(contract)

    assert "__getattr__" not in declared, (
        "JobManagerState must declare its members explicitly; a __getattr__ "
        "escape hatch types every cross-owner reference as Any"
    )

    package = Path(state_module.__file__).parent
    undeclared: dict[str, set[str]] = {}
    for module_name in _OWNER_MODULES:
        tree = ast.parse((package / module_name).read_text(encoding="utf-8"))
        owner = _owner_class(tree)
        local = _declared_members(owner)
        reached = {
            node.attr
            for node in ast.walk(owner)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        }
        missing = reached - local - declared
        if missing:
            undeclared[module_name] = missing

    assert not undeclared, (
        f"owner modules reach undeclared members on JobManagerState: {undeclared}"
    )


def test_job_manager_rejects_unknown_attributes() -> None:
    manager = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        max_nonterminal=1,
        state_path=None,
    )

    with pytest.raises(AttributeError):
        _ = manager.misspelled_manager_attribute


def test_job_manager_import_does_not_pull_in_jobs() -> None:
    probe = """
import sys

sys.path.insert(0, sys.argv[1])

from vaultspec_rag.job_manager.manager import JobManager  # absolute-import-ok

assert JobManager is not None
assert "vaultspec_rag.jobs" not in sys.modules
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


def _parse_jobs_module() -> ast.Module:
    import vaultspec_rag.jobs as jobs_mod

    src = inspect.getsource(jobs_mod)
    return ast.parse(textwrap.dedent(src))


def _parse_job_dispatch_module() -> ast.Module:
    import vaultspec_rag.job_dispatch as dispatch_mod

    src = inspect.getsource(dispatch_mod)
    return ast.parse(textwrap.dedent(src))


class TestIndexDispatchIsExtracted:
    """AST guard for the extracted production indexing dispatch module.

    The load-model-before-lease ordering this class used to check on two
    named runners is now checked package-wide, on all fourteen functions
    that pair the two calls rather than the two that had a test.
    """

    @staticmethod
    def _defined_names(tree: ast.Module) -> set[str]:
        """Return every function name the module defines, sync or async.

        ``ast`` gives the two no common base, so both are named. Filtering
        ``FunctionDef`` alone let an ``async def`` back into the facade
        unseen, and ``jobs`` already defines one.
        """
        return {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        }

    def test_dispatch_implementations_are_extracted_from_jobs_facade(self) -> None:
        jobs_functions = self._defined_names(_parse_jobs_module())
        dispatch_functions = self._defined_names(_parse_job_dispatch_module())
        assert "_bg_run" not in jobs_functions
        assert {"_run_vault_attempt", "_run_indexing_attempt"} <= dispatch_functions


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
# Persisted job state: the writer refuses everything the loader rejects
# ---------------------------------------------------------------------------


def _valid_snapshot() -> JobSnapshot:
    """Return one queued job that the real loader accepts unchanged."""
    spec = JobSpec(
        operation=JobOperation.INDEX,
        source=JobSource.CODE,
        project_root=str(Path(__file__).resolve().parent),
        mode=JobMode.INCREMENTAL,
    )
    return JobSnapshot(
        id="job-1",
        revision=1,
        spec=spec,
        state=JobState.QUEUED,
        desired_state=DesiredJobState.RUNNING,
        capabilities=capabilities_for_state(spec, JobState.QUEUED),
        attempt=JobAttempt(number=1),
        timestamps=JobTimestamps(created_at=1000.0, state_changed_at=1000.0),
        progress=JobProgress(
            step="chunking", completed=3, total=9, last_updated=1000.0
        ),
        result=None,
        error_kind=None,
        initiator=JobInitiator(kind="cli", command="index", project_root=None),
        runtime=_runtime(),
        resources=JobResourceSnapshot(started=_resources(), finished=None),
        resilience=IndexResilienceSnapshot(committed_units=2),
        gpu_lock_wait_seconds=0.25,
    )


def _resources(
    *,
    rss_mib: float = 512.5,
    cuda_allocated_mib: float = 0.0,
    cuda_reserved_mib: float = 0.0,
) -> ProcessResourceSnapshot:
    return ProcessResourceSnapshot(
        rss_mib=rss_mib,
        cuda_allocated_mib=cuda_allocated_mib,
        cuda_reserved_mib=cuda_reserved_mib,
    )


def _runtime() -> JobRuntimeSnapshot:
    return JobRuntimeSnapshot(
        pid=1,
        parent_pid=0,
        user="operator",
        executable="python",
        prefix="",
        base_prefix="",
        virtual_env=None,
    )


# Each case names the exact message its own branch raises. A shared or
# loosened matcher would pass on whichever branch happened to fire, which is
# the failure mode this table exists to rule out - do not relax these.
_REFUSED_AT_CONSTRUCTION: list[tuple[str, str, Callable[[], object]]] = [
    (
        "memory reading is null",
        "rss_mib must be a finite non-negative number",
        lambda: _resources(rss_mib=cast("float", None)),
    ),
    (
        "cuda allocated reading is null",
        "cuda_allocated_mib must be a finite non-negative number",
        lambda: _resources(cuda_allocated_mib=cast("float", None)),
    ),
    (
        "cuda reserved reading is null",
        "cuda_reserved_mib must be a finite non-negative number",
        lambda: _resources(cuda_reserved_mib=cast("float", None)),
    ),
    (
        "memory reading is negative",
        "rss_mib must be a finite non-negative number",
        lambda: _resources(rss_mib=-1.0),
    ),
    (
        "memory reading is not a number",
        "rss_mib must be a finite non-negative number",
        lambda: _resources(rss_mib=math.nan),
    ),
    (
        "memory reading is a string",
        "rss_mib must be a finite non-negative number",
        lambda: _resources(rss_mib=cast("float", "512")),
    ),
    (
        "memory reading is a boolean",
        "rss_mib must be a finite non-negative number",
        lambda: _resources(rss_mib=cast("float", True)),
    ),
    (
        "runtime pid is negative",
        "pid must be a non-negative integer",
        lambda: replace(_runtime(), pid=-1),
    ),
    (
        "runtime pid is a boolean",
        "pid must be a non-negative integer",
        lambda: replace(_runtime(), pid=cast("int", True)),
    ),
    (
        "runtime user is null",
        "user must be a string",
        lambda: replace(_runtime(), user=cast("str", None)),
    ),
    (
        "runtime activity flag is not a boolean",
        "task_active must be a boolean",
        lambda: replace(_runtime(), task_active=cast("bool", 1)),
    ),
    (
        "progress step is empty",
        "step must be a non-empty string",
        lambda: JobProgress(step="", completed=0, total=None, last_updated=1.0),
    ),
    (
        "progress count is negative",
        "completed must be a non-negative integer",
        lambda: JobProgress(step="a", completed=-1, total=None, last_updated=1.0),
    ),
    (
        "progress exceeds its total",
        "completed must not exceed total",
        lambda: JobProgress(step="a", completed=5, total=4, last_updated=1.0),
    ),
    (
        "progress stamp is null",
        "last_updated must be a finite number",
        lambda: JobProgress(
            step="a", completed=0, total=None, last_updated=cast("float", None)
        ),
    ),
    (
        "creation stamp is null",
        "created_at must be a finite number",
        lambda: JobTimestamps(created_at=cast("float", None), state_changed_at=1000.0),
    ),
    (
        "state-change stamp is infinite",
        "state_changed_at must be a finite number",
        lambda: JobTimestamps(created_at=1000.0, state_changed_at=math.inf),
    ),
    (
        "optional stamp is a string",
        "started_at must be a finite number or None",
        lambda: JobTimestamps(
            created_at=1000.0, state_changed_at=1000.0, started_at=cast("float", "now")
        ),
    ),
    (
        "initiator kind is empty",
        "kind must be a non-empty string",
        lambda: JobInitiator(kind="", command="index", project_root=None),
    ),
    (
        "initiator command is empty",
        "command must be a non-empty string",
        lambda: JobInitiator(kind="cli", command="", project_root=None),
    ),
    (
        "attempt number is a boolean",
        "number must be an integer of at least 1",
        lambda: JobAttempt(number=cast("int", True)),
    ),
    (
        "attempt number is zero",
        "number must be an integer of at least 1",
        lambda: JobAttempt(number=0),
    ),
    (
        "resource flag is not a boolean",
        "writer_lock_held must be a boolean",
        lambda: JobResourceSnapshot(
            started=None, finished=None, writer_lock_held=cast("bool", 1)
        ),
    ),
    (
        "checkpoint compatibility is not a boolean",
        "checkpoint_compatible must be a boolean or None",
        lambda: IndexResilienceSnapshot(checkpoint_compatible=cast("bool", 1)),
    ),
    (
        "resilience peak is negative",
        "peak_rss_mib must be a finite non-negative number or None",
        lambda: IndexResilienceSnapshot(peak_rss_mib=-1.0),
    ),
    (
        "resilience label is not a string",
        "generation_id must be a string or None",
        lambda: IndexResilienceSnapshot(generation_id=cast("str", 7)),
    ),
    (
        "job id is empty",
        "id must be a non-empty string",
        lambda: replace(_valid_snapshot(), id=""),
    ),
    (
        "job revision is zero",
        "revision must be an integer of at least 1",
        lambda: replace(_valid_snapshot(), revision=0),
    ),
    (
        "job revision is a boolean",
        "revision must be an integer of at least 1",
        lambda: replace(_valid_snapshot(), revision=cast("int", True)),
    ),
    (
        "lock wait is negative",
        "gpu_lock_wait_seconds must be a finite non-negative number or None",
        lambda: replace(_valid_snapshot(), gpu_lock_wait_seconds=-0.5),
    ),
    (
        "telemetry block is not string-keyed",
        "reuse must be a mapping with string keys or None",
        lambda: replace(
            _valid_snapshot(), reuse=cast("dict[str, object]", {1: "vectors"})
        ),
    ),
]


class TestPersistedJobStateWriteSide:
    """Every value the loader rejects must be refused where it is produced.

    A reading that is invalid on read but accepted on write puts a record on
    disk that only fails one boot later, in another process, on a path with no
    recovery. These pin the refusal to construction, where the traceback still
    names the producer.
    """

    @pytest.mark.parametrize(
        ("message", "construct"),
        [(message, construct) for _, message, construct in _REFUSED_AT_CONSTRUCTION],
        ids=[name for name, _, _ in _REFUSED_AT_CONSTRUCTION],
    )
    def test_a_value_the_loader_rejects_cannot_be_constructed(
        self, message: str, construct: Callable[[], object]
    ) -> None:
        with pytest.raises(ValueError, match=message):
            construct()

    def test_an_idempotency_binding_refuses_an_empty_job_id(self) -> None:
        snapshot = _valid_snapshot()
        with pytest.raises(TypeError, match="idempotency job_id must be a non-empty"):
            IdempotencyBinding(
                signature=(snapshot.spec, snapshot.initiator, False), job_id=""
            )

    def test_a_constructible_generation_survives_the_real_writer(
        self, tmp_path: Path
    ) -> None:
        state = PersistedManagerState(jobs=(_valid_snapshot(),), bindings=())
        path = tmp_path / "jobs-state.json"
        save_persisted_state(path, state)
        assert load_persisted_state(path) == state

    def test_a_quiesce_parked_job_reloads_through_the_real_loader(
        self, tmp_path: Path
    ) -> None:
        # A service quiesce parks queued work as paused while its intent stays
        # running, and resume selects on exactly that pair to tell it from work
        # an operator paused. The loader used to refuse the pair, so the manager
        # wrote a generation it could not read back.
        state_path = tmp_path / "jobs-state.json"
        root = str(tmp_path)
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=4,
            state_path=state_path,
        )
        created = manager.create(
            JobSpec(JobOperation.INDEX, JobSource.CODE, root, JobMode.INCREMENTAL),
            JobInitiator("service", "reindex_codebase", root),
        )
        assert created.job is not None
        deferred = manager.defer_unstarted_for_quiesce(created.job.id)
        assert deferred.job is not None
        assert deferred.job.state is JobState.PAUSED
        assert deferred.job.desired_state is DesiredJobState.RUNNING

        restored = load_persisted_state(state_path)
        assert [job.id for job in restored.jobs] == [created.job.id]
        assert restored.jobs[0].state is JobState.PAUSED
        assert restored.jobs[0].desired_state is DesiredJobState.RUNNING

    def test_paused_work_may_not_persist_cancelled_intent(self, tmp_path: Path) -> None:
        # Widening the paused pair set to admit running intent must not retire
        # the check: paused-but-cancelled remains incoherent.
        snapshot = replace(
            _valid_snapshot(),
            state=JobState.PAUSED,
            desired_state=DesiredJobState.CANCELLED,
        )
        path = tmp_path / "jobs-state.json"
        save_persisted_state(path, PersistedManagerState(jobs=(snapshot,), bindings=()))
        with pytest.raises(ValueError, match="observed and desired states disagree"):
            load_persisted_state(path)

    def test_the_loader_still_refuses_a_null_memory_reading(
        self, tmp_path: Path
    ) -> None:
        # The loader's strictness is the invariant; the writer's permissiveness
        # was the defect. Loosening this read path to tolerate damaged records
        # would hide the next producer bug instead of surfacing it.
        path = tmp_path / "jobs-state.json"
        save_persisted_state(
            path, PersistedManagerState(jobs=(_valid_snapshot(),), bindings=())
        )
        payload = cast(
            "dict[str, object]", json.loads(path.read_text(encoding="utf-8"))
        )
        jobs = cast("list[dict[str, object]]", payload["jobs"])
        resources = cast("dict[str, object]", jobs[0]["resources"])
        cast("dict[str, object]", resources["started"])["rss_mib"] = None
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(TypeError, match="resource rss_mib must be numeric"):
            load_persisted_state(path)


# ---------------------------------------------------------------------------
# jobs module basic lifecycle
# ---------------------------------------------------------------------------
