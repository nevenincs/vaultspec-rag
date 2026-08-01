"""Cohesive unit coverage for job-management behavior."""

from __future__ import annotations

import ast
import inspect
import json
import math
import os
import re
import subprocess
import sys
import textwrap
import time
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from .. import job_models
from .. import jobs as jobs_module
from .._atomic_write import write_json_atomically
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
    ResumeStrategy,
    capabilities_for_state,
)
from ..job_persistence import (
    IdempotencyBinding,
    NewerStateVersionError,
    PersistedManagerState,
    PersistenceWriteError,
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


_JSON_VALUE_MESSAGE = (
    "a JSON value: null, a boolean, a number, a string, an array, "
    "or an object with string keys"
)
_OBJECT_MESSAGE = "an object with string keys"


def _telemetry_refusal(path: str, requirement: str) -> str:
    """Return the escaped refusal a telemetry value at *path* must raise.

    Escaped because the path carries brackets and quotes; an unescaped matcher
    would silently become a much looser regex and pass on the wrong branch.
    """
    return re.escape(f"{path} must be {requirement}")


def _telemetry_construction(block: dict[str, object]) -> Callable[[], object]:
    return lambda: replace(_valid_snapshot(), reuse=block)


# Values a telemetry block may not carry, each paired with the exact path its
# refusal must name. A message naming only the block would leave a producer
# hunting for the offending key by hand, so the path is part of the contract.
_REFUSED_TELEMETRY_VALUES: list[tuple[str, dict[str, object], str]] = [
    (
        "a tuple",
        {"donor_collections": ("worktree-a",)},
        _telemetry_refusal("reuse['donor_collections']", _JSON_VALUE_MESSAGE),
    ),
    (
        "a set",
        {"donor_collections": {"worktree-a"}},
        _telemetry_refusal("reuse['donor_collections']", _JSON_VALUE_MESSAGE),
    ),
    (
        "an arbitrary object",
        {"donor": Path("/srv/donor")},
        _telemetry_refusal("reuse['donor']", _JSON_VALUE_MESSAGE),
    ),
    (
        "a nested non-string key",
        {"per_collection": {7: "hits"}},
        _telemetry_refusal("reuse['per_collection']", _OBJECT_MESSAGE),
    ),
    (
        "a non-finite rate",
        {"hit_rate": math.nan},
        _telemetry_refusal("reuse['hit_rate']", "a finite number"),
    ),
    (
        "an infinite saving",
        {"gpu_seconds_saved": math.inf},
        _telemetry_refusal("reuse['gpu_seconds_saved']", "a finite number"),
    ),
    (
        "a tuple buried in an array",
        {"buckets": [{"edges": (1, 2)}]},
        _telemetry_refusal("reuse['buckets'][0]['edges']", _JSON_VALUE_MESSAGE),
    ),
    (
        "a non-finite number buried in an array",
        {"buckets": [0.5, math.inf]},
        _telemetry_refusal("reuse['buckets'][1]", "a finite number"),
    ),
]


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
        r"reuse must be an object with string keys or None",
        lambda: replace(
            _valid_snapshot(), reuse=cast("dict[str, object]", {1: "vectors"})
        ),
    ),
    (
        "telemetry block is not a mapping",
        r"drift must be an object with string keys or None",
        lambda: replace(_valid_snapshot(), drift=cast("dict[str, object]", ["a"])),
    ),
    *[
        (
            f"telemetry carries {label}",
            expected,
            _telemetry_construction(value),
        )
        for label, value, expected in _REFUSED_TELEMETRY_VALUES
    ],
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

    def test_an_idempotency_binding_refuses_a_non_boolean_start_paused(self) -> None:
        # The loader checks this flag's type, so a binding carrying anything
        # else is written without complaint and refused one boot later.
        snapshot = _valid_snapshot()
        with pytest.raises(TypeError, match="idempotency start_paused must be boolean"):
            IdempotencyBinding(
                signature=(
                    snapshot.spec,
                    snapshot.initiator,
                    cast("bool", 1),
                ),
                job_id=snapshot.id,
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


_DESIRED_FOR_STATE: dict[JobState, DesiredJobState] = {
    JobState.QUEUED: DesiredJobState.RUNNING,
    JobState.RUNNING: DesiredJobState.RUNNING,
    JobState.PAUSING: DesiredJobState.PAUSED,
    JobState.PAUSED: DesiredJobState.PAUSED,
    JobState.CANCELLING: DesiredJobState.CANCELLED,
    JobState.CANCELLED: DesiredJobState.CANCELLED,
    JobState.SUCCEEDED: DesiredJobState.RUNNING,
    JobState.FAILED: DesiredJobState.RUNNING,
    JobState.INTERRUPTED: DesiredJobState.RUNNING,
    JobState.SUPERSEDED: DesiredJobState.RUNNING,
}


def _spec(
    *,
    source: JobSource = JobSource.CODE,
    mode: JobMode = JobMode.INCREMENTAL,
    project_root: str | None = None,
) -> JobSpec:
    return JobSpec(
        operation=JobOperation.INDEX,
        source=source,
        project_root=project_root or str(Path(__file__).resolve().parent),
        mode=mode,
    )


def _snapshot_in_state(
    state: JobState,
    *,
    job_id: str = "job-1",
    spec: JobSpec | None = None,
) -> JobSnapshot:
    """Return the leanest snapshot the manager could hold in *state*.

    Every lifecycle invariant the loader enforces is satisfied structurally:
    a live attempt carries a start, a terminal record carries a finish, and an
    idle record holds no execution resource.
    """
    resolved = spec if spec is not None else _spec()
    return JobSnapshot(
        id=job_id,
        revision=4,
        spec=resolved,
        state=state,
        desired_state=_DESIRED_FOR_STATE[state],
        capabilities=capabilities_for_state(resolved, state),
        attempt=JobAttempt(number=1),
        timestamps=JobTimestamps(
            created_at=1000.0,
            state_changed_at=1200.0,
            started_at=None if state is JobState.QUEUED else 1500.0,
            finished_at=2000.0 if state.is_terminal else None,
        ),
        progress=None,
        result=None,
        error_kind=None,
        initiator=JobInitiator(kind="cli", command="index", project_root=None),
        runtime=_runtime(),
        resources=JobResourceSnapshot(started=None, finished=None),
        resilience=None,
    )


def _fully_populated_snapshot() -> JobSnapshot:
    """Return a terminal snapshot with every optional field carrying a value."""
    spec = _spec(source=JobSource.VAULT, mode=JobMode.REBUILD)
    return replace(
        _snapshot_in_state(JobState.FAILED, spec=spec),
        attempt=JobAttempt(
            number=2,
            parent_job_id="job-0",
            resumed_from_attempt=1,
            resume_strategy=ResumeStrategy.RECONCILE,
        ),
        timestamps=JobTimestamps(
            created_at=1000.0,
            state_changed_at=1200.0,
            started_at=1500.0,
            finished_at=2000.0,
            control_requested_at=1600.0,
            control_acknowledged_at=1700.0,
            admission_acquired_at=1550.0,
        ),
        progress=JobProgress(
            step="encoding", completed=7, total=7, last_updated=1900.0
        ),
        result="failed after retry",
        error_kind="encode_error",
        initiator=JobInitiator(kind="mcp", command="reindex", project_root="/srv/app"),
        runtime=JobRuntimeSnapshot(
            pid=4242,
            parent_pid=1,
            user="operator",
            executable="python",
            prefix="/opt/venv",
            base_prefix="/usr",
            virtual_env="/opt/venv",
        ),
        resources=JobResourceSnapshot(
            started=_resources(rss_mib=101.5, cuda_allocated_mib=2.0),
            finished=_resources(rss_mib=202.25, cuda_reserved_mib=8.0),
        ),
        resilience=IndexResilienceSnapshot(
            generation_id="gen-9",
            committed_units=41,
            replayed_units=3,
            checkpoint_compatible=True,
            last_durable_progress_at=1850.0,
            no_progress_timeout_seconds=900.0,
            no_progress_remaining_seconds=0.0,
            circuit_state="open",
            next_retry_at=2400.0,
            peak_rss_mib=303.0,
            rss_ceiling_mib=4096.0,
            peak_cuda_allocated_mib=12.5,
            peak_cuda_reserved_mib=24.5,
            cuda_ceiling_mib=8192.0,
            support_profile="workstation",
            terminal_outcome="fault",
        ),
        reuse={
            "donors": 12,
            "ratio": 0.5,
            "label": "reuse ✓",
            "enabled": True,
            "absent": None,
            "buckets": [1, 2, 3],
            "nested": {"a": 1},
        },
        drift={"superseded": 4, "stale": 0},
        gpu_lock_wait_seconds=1.25,
    )


def _round_trip_cases() -> list[tuple[str, JobSnapshot]]:
    """Enumerate every snapshot shape the manager can legitimately produce."""
    cases: list[tuple[str, JobSnapshot]] = [
        (f"state {state.value}", _snapshot_in_state(state)) for state in JobState
    ]
    cases += [
        (
            f"spec {source.value}/{mode.value}",
            _snapshot_in_state(JobState.RUNNING, spec=_spec(source=source, mode=mode)),
        )
        for source in (JobSource.VAULT, JobSource.CODE, JobSource.DOCUMENT)
        for mode in JobMode
    ]
    cases.append(("every optional field present", _fully_populated_snapshot()))
    cases.append(
        (
            "every optional field absent",
            _snapshot_in_state(JobState.QUEUED),
        )
    )
    cases.append(
        (
            "empty-string fields",
            replace(
                _snapshot_in_state(JobState.SUCCEEDED),
                result="",
                error_kind="",
                initiator=JobInitiator(kind="cli", command="index", project_root=""),
                runtime=replace(_runtime(), user="", virtual_env=""),
                attempt=JobAttempt(number=1, parent_job_id=""),
                resilience=IndexResilienceSnapshot(generation_id="", circuit_state=""),
            ),
        )
    )
    cases.append(
        (
            "unicode fields",
            replace(
                _snapshot_in_state(JobState.SUCCEEDED),
                id="job-索引-🎉",
                result="succeeded ✓ naïve 日本語",
                initiator=JobInitiator(
                    kind="cli", command="索引 --全部", project_root="/srv/naïve"
                ),
                runtime=replace(_runtime(), user="Ωmega"),
                progress=JobProgress(
                    step="分块", completed=1, total=2, last_updated=1100.0
                ),
            ),
        )
    )
    cases.append(
        (
            "numeric boundaries",
            replace(
                _snapshot_in_state(JobState.SUCCEEDED),
                timestamps=JobTimestamps(
                    created_at=0.0,
                    state_changed_at=0.0,
                    started_at=5e-324,
                    finished_at=1e308,
                ),
                progress=JobProgress(step="s", completed=0, total=0, last_updated=0.0),
                resources=JobResourceSnapshot(
                    started=_resources(rss_mib=0.0),
                    finished=_resources(rss_mib=1e308),
                ),
                gpu_lock_wait_seconds=0.0,
                resilience=IndexResilienceSnapshot(
                    committed_units=0, replayed_units=2**53
                ),
            ),
        )
    )
    cases.append(
        (
            "integer-valued clocks",
            replace(
                _snapshot_in_state(JobState.SUCCEEDED),
                timestamps=JobTimestamps(
                    created_at=cast("float", 1000),
                    state_changed_at=cast("float", 1200),
                    started_at=cast("float", 1500),
                    finished_at=cast("float", 2000),
                ),
            ),
        )
    )
    return cases


_ROUND_TRIP_CASES = _round_trip_cases()


def _generation(*jobs: JobSnapshot) -> PersistedManagerState:
    return PersistedManagerState(jobs=jobs, bindings=())


def _age(path: Path, seconds: float) -> None:
    """Backdate *path* on the real filesystem, as an abandoned file would be."""
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def _temporaries(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p.name.endswith(".tmp"))


def _identical(left: object, right: object) -> bool:
    """Return whether two decoded values match in both value and type.

    Equality alone is too weak to see the losses that matter here: ``1``,
    ``1.0`` and ``True`` all compare equal, so a round trip that turned an
    integer into a float or a boolean would still pass an ``==`` assertion.
    """
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        mapping = cast("dict[str, object]", left)
        other = cast("dict[str, object]", right)
        return set(mapping) == set(other) and all(
            _identical(value, other[key]) for key, value in mapping.items()
        )
    if isinstance(left, list):
        items = cast("list[object]", left)
        others = cast("list[object]", right)
        return len(items) == len(others) and all(
            _identical(one, two) for one, two in zip(items, others, strict=True)
        )
    return left == right


def _telemetry_of(job: JobSnapshot) -> dict[str, object]:
    """Return a loaded job's reuse block, asserting it survived at all."""
    block = job.reuse
    assert block is not None
    return block


def _deeply_nested(depth: int) -> dict[str, object]:
    root: dict[str, object] = {}
    cursor = root
    for _ in range(depth):
        nested: dict[str, object] = {}
        cursor["n"] = nested
        cursor = nested
    return root


def _nested_past_the_encoders_limit() -> dict[str, object]:
    """Nest to a depth this interpreter's encoder is observed to refuse.

    The depth is probed rather than written down, because the ceiling is not a
    portable constant. One interpreter enforces a fixed recursion counter and
    refuses the same payload whatever stack it runs on; a later one derives the
    ceiling from the running thread's stack budget, so an identical block is
    refused on a one-megabyte stack and encoded on an eight-megabyte one. A
    hard-coded depth therefore states a precondition that silently stops being
    true, and the guard below passes its assertion by never reaching it.

    Probing the encoder that is about to run the assertion states the
    precondition truthfully instead. It errs safe in both directions: the real
    payload nests this block deeper still, inside the surrounding generation,
    and an interpreter that refused nothing fails here by name rather than
    leaving the guard vacuous.
    """
    depth = 1_024
    while depth <= 1_048_576:
        block = _deeply_nested(depth)
        try:
            json.dumps(block)
        except RecursionError:
            return block
        depth *= 2
    raise AssertionError("the encoder accepted every probed nesting depth")


def _self_referential() -> dict[str, object]:
    """A telemetry block no interpreter's encoder can ever write.

    Refused for what it is rather than for how deep it is, so unlike nesting it
    carries no dependence on a stack budget or a recursion counter.
    """
    inner: dict[str, object] = {}
    inner["self"] = inner
    return {"cycle": inner}


class TestPersistedJobStateRoundTrip:
    """Anything the manager can hold must survive a write and read unchanged.

    A field that serializes but does not load again strands its job history in
    a file the next start refuses, one process removed from whatever produced
    it. Enumerating the shapes here is what keeps that from being discovered
    on an operator's machine.
    """

    @pytest.mark.parametrize(
        "snapshot",
        [snapshot for _, snapshot in _ROUND_TRIP_CASES],
        ids=[name for name, _ in _ROUND_TRIP_CASES],
    )
    def test_a_snapshot_survives_the_write_and_read_unchanged(
        self, tmp_path: Path, snapshot: JobSnapshot
    ) -> None:
        path = tmp_path / "jobs-state.json"
        state = _generation(snapshot)
        save_persisted_state(path, state)
        assert load_persisted_state(path) == state

    def test_a_whole_generation_of_distinct_jobs_survives_with_its_bindings(
        self, tmp_path: Path
    ) -> None:
        # Nonterminal jobs must name distinct work, so each takes its own root.
        running = _snapshot_in_state(
            JobState.RUNNING,
            job_id="job-running",
            spec=_spec(source=JobSource.VAULT, project_root=str(tmp_path / "a")),
        )
        queued = _snapshot_in_state(
            JobState.QUEUED,
            job_id="job-queued",
            spec=_spec(source=JobSource.DOCUMENT, project_root=str(tmp_path / "b")),
        )
        finished = _fully_populated_snapshot()
        state = PersistedManagerState(
            jobs=(running, queued, finished),
            bindings=(
                (
                    "key-running",
                    IdempotencyBinding(
                        signature=(running.spec, running.initiator, False),
                        job_id=running.id,
                    ),
                ),
                (
                    "键-unicode",
                    IdempotencyBinding(
                        signature=(queued.spec, queued.initiator, True),
                        job_id=queued.id,
                    ),
                ),
            ),
        )
        path = tmp_path / "jobs-state.json"
        save_persisted_state(path, state)
        assert load_persisted_state(path) == state

    def _round_tripped_telemetry(
        self, tmp_path: Path, block: dict[str, object]
    ) -> dict[str, object]:
        snapshot = replace(_snapshot_in_state(JobState.SUCCEEDED), reuse=block)
        path = tmp_path / "jobs-state.json"
        save_persisted_state(path, _generation(snapshot))
        return _telemetry_of(load_persisted_state(path).jobs[0])

    def test_the_telemetry_a_run_actually_publishes_survives_intact(
        self, tmp_path: Path
    ) -> None:
        # The exact blocks the reuse and drift producers emit, spelled out
        # rather than sampled. These are what a real generation carries, so
        # they are what the round trip has to return unchanged - including the
        # value types, which plain equality would not notice losing.
        reuse: dict[str, object] = {
            "reuse_hits": 128,
            "reuse_misses": 32,
            "hit_rate": 0.8,
            "gpu_seconds_saved": 41.125,
            "donor_absent": False,
            "donor_collections": ["code_9f2a", "code_7b41"],
        }
        drift: dict[str, object] = {
            "superseded_paths": 3,
            "deferred_paths": ["src/pkg/a.py", "src/pkg/b.py"],
            "collisions_observed": 1,
            "retry_budget": 4,
        }
        snapshot = replace(
            _snapshot_in_state(JobState.SUCCEEDED), reuse=reuse, drift=drift
        )
        path = tmp_path / "jobs-state.json"
        save_persisted_state(path, _generation(snapshot))
        loaded = load_persisted_state(path).jobs[0]
        assert _identical(loaded.reuse, reuse)
        assert _identical(loaded.drift, drift)

    def test_every_value_a_telemetry_block_may_carry_returns_identical(
        self, tmp_path: Path
    ) -> None:
        # The whole admitted value space in one block, at depth. A block is
        # free to name whatever counters a run measured, so what pins the
        # contract is the value space rather than any key list.
        block: dict[str, object] = {
            "absent": None,
            "on": True,
            "off": False,
            "zero": 0,
            "negative": -17,
            "beyond_double_precision": 2**53 + 1,
            "ratio": 0.5,
            "smallest_subnormal": 5e-324,
            "largest_finite": 1e308,
            "label": "reuse ✓ 索引 naïve",
            "empty_text": "",
            "empty_array": [],
            "empty_object": {},
            "mixed_array": [1, 1.0, "1", True, None, [2], {"k": "v"}],
            "nested_object": {"a": {"b": {"c": [{"d": 1}]}}},
        }
        assert _identical(self._round_tripped_telemetry(tmp_path, block), block)

    def test_key_order_is_the_one_thing_a_telemetry_block_does_not_keep(
        self, tmp_path: Path
    ) -> None:
        # A deliberate loss, kept and stated rather than closed. The state file
        # is written with sorted keys so two equal generations produce equal
        # bytes; insertion order is the price. Mappings compare without it, so
        # nothing downstream can observe the difference - but the exact
        # transformation is asserted here rather than left to be rediscovered.
        block: dict[str, object] = {"z": 1, "m": 2, "a": 3}
        loaded = self._round_tripped_telemetry(tmp_path, block)
        assert loaded == block
        assert list(block) == ["z", "m", "a"]
        assert list(loaded) == ["a", "m", "z"]

    def test_a_value_shared_by_two_keys_returns_as_two_equal_copies(
        self, tmp_path: Path
    ) -> None:
        # The other deliberate loss. JSON has no notion of a shared reference,
        # so a block naming one object under two keys gets two independent
        # objects back. They compare equal, so no reader can tell - but a
        # producer that expected to mutate one and see both would be wrong.
        shared: list[object] = ["code_9f2a"]
        block: dict[str, object] = {"donors": shared, "fallbacks": shared}
        assert block["donors"] is block["fallbacks"]
        loaded = self._round_tripped_telemetry(tmp_path, block)
        assert _identical(loaded, block)
        assert loaded["donors"] is not loaded["fallbacks"]

    def test_the_loader_accepts_every_telemetry_shape_a_decode_can_yield(
        self, tmp_path: Path
    ) -> None:
        # The contract on these blocks exists to stop a producer writing a
        # value that will not come back. It must never be what stops a start
        # reading one, so the accepted set covers the decoder's whole output
        # range: a block assembled straight in the file, through no model at
        # all, still loads. Narrowing the contract below this would strand a
        # generation of job history over a decorative field.
        path = tmp_path / "jobs-state.json"
        save_persisted_state(path, _generation(_snapshot_in_state(JobState.SUCCEEDED)))
        payload = cast(
            "dict[str, object]", json.loads(path.read_text(encoding="utf-8"))
        )
        decoded = cast(
            "dict[str, object]",
            json.loads(
                '{"null":null,"true":true,"false":false,"big":-9007199254740993,'
                '"exp":1.5e-7,"text":"\\u7d22\\u5f15","deep":[1,[2,[3,[]]]],'
                '"object":{"nested":{"empty":{}}}}'
            ),
        )
        job = cast("list[dict[str, object]]", payload["jobs"])[0]
        job["reuse"] = decoded
        job["drift"] = decoded
        path.write_text(json.dumps(payload), encoding="utf-8")
        loaded = load_persisted_state(path).jobs[0]
        assert _identical(loaded.reuse, decoded)
        assert _identical(loaded.drift, decoded)

    def test_the_writer_refuses_the_one_decodable_value_the_contract_rejects(
        self, tmp_path: Path
    ) -> None:
        # The premise the argument above rests on. A non-finite number is the
        # only thing a JSON decode can produce that the telemetry contract
        # turns away, so it is the only place the reader could end up stricter
        # than the writer. It does not: the single JSON writer refuses it too,
        # which is why no file this daemon wrote can hold one, and why
        # refusing it at construction cannot cost a start.
        probe = tmp_path / "probe.json"
        with pytest.raises(ValueError, match="Out of range float values"):
            write_json_atomically(probe, {"telemetry": {"hit_rate": math.nan}})
        assert not probe.exists()
        assert _temporaries(tmp_path) == []

    @pytest.mark.parametrize(
        "state", list(JobState), ids=[state.value for state in JobState]
    )
    def test_discarded_capabilities_always_match_what_was_written(
        self, tmp_path: Path, state: JobState
    ) -> None:
        # Capabilities are written but never read back - the loader derives
        # them again. That is only safe while the derivation reproduces the
        # written block exactly, so this asserts the identity rather than
        # trusting it, for every state a record can be persisted in.
        snapshot = _snapshot_in_state(state)
        path = tmp_path / "jobs-state.json"
        save_persisted_state(path, _generation(snapshot))
        payload = cast(
            "dict[str, object]", json.loads(path.read_text(encoding="utf-8"))
        )
        jobs = cast("list[dict[str, object]]", payload["jobs"])
        written = cast("dict[str, bool]", jobs[0]["capabilities"])
        loaded = load_persisted_state(path).jobs[0]
        assert written == {
            "pausable": loaded.capabilities.pausable,
            "resumable": loaded.capabilities.resumable,
            "cancellable": loaded.capabilities.cancellable,
            "retryable": loaded.capabilities.retryable,
            "deletable": loaded.capabilities.deletable,
            "force_killable": loaded.capabilities.force_killable,
        }
        assert loaded.capabilities == snapshot.capabilities

    def test_a_start_paused_record_from_an_older_writer_gains_its_request_stamp(
        self, tmp_path: Path
    ) -> None:
        # The one deliberate asymmetry in the round trip. An older writer
        # emitted a start-paused job with an acknowledgement and no request,
        # which no current state machine can produce; loading repairs it. The
        # result is intentionally NOT the snapshot that was written.
        spec = _spec()
        acknowledged = 1000.0
        legacy = JobSnapshot(
            id="job-legacy",
            revision=1,
            spec=spec,
            state=JobState.PAUSED,
            desired_state=DesiredJobState.PAUSED,
            capabilities=capabilities_for_state(spec, JobState.PAUSED),
            attempt=JobAttempt(number=1),
            timestamps=JobTimestamps(
                created_at=acknowledged,
                state_changed_at=acknowledged,
                control_acknowledged_at=acknowledged,
            ),
            progress=None,
            result=None,
            error_kind=None,
            initiator=JobInitiator(kind="cli", command="index", project_root=None),
            runtime=_runtime(),
            resources=JobResourceSnapshot(started=None, finished=None),
            resilience=None,
        )
        path = tmp_path / "jobs-state.json"
        save_persisted_state(path, _generation(legacy))
        loaded = load_persisted_state(path).jobs[0]
        assert loaded.timestamps.control_requested_at == acknowledged
        assert loaded == replace(
            legacy,
            timestamps=replace(legacy.timestamps, control_requested_at=acknowledged),
        )


class TestPersistedJobStateSchemaContract:
    """What a build accepts must not narrow to the exact file it writes.

    A reader pinned to one version turns every future layout change into an
    operator losing their history, which is the failure this states, and
    tests, the boundaries of.
    """

    def _written_payload(self, tmp_path: Path) -> tuple[Path, dict[str, object]]:
        path = tmp_path / "jobs-state.json"
        save_persisted_state(path, _generation(_snapshot_in_state(JobState.QUEUED)))
        return path, cast(
            "dict[str, object]", json.loads(path.read_text(encoding="utf-8"))
        )

    def _rewrite(self, path: Path, payload: dict[str, object]) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_a_file_from_a_newer_build_is_refused_as_newer_not_as_damaged(
        self, tmp_path: Path
    ) -> None:
        # Reading a layout this build does not know would turn a misread
        # record into a wrong decision. The refusal carries its own type and
        # the numbers as fields, so a caller can tell an intact file it is too
        # old for from a damaged one without matching on message text.
        path, payload = self._written_payload(tmp_path)
        declared = 2
        payload["version"] = declared
        self._rewrite(path, payload)
        with pytest.raises(NewerStateVersionError) as caught:
            load_persisted_state(path)
        assert caught.value.declared_version == declared
        assert caught.value.maximum_readable < declared
        assert caught.value.minimum_readable <= caught.value.maximum_readable

    def test_the_newer_build_refusal_remains_a_value_error(self) -> None:
        # Every reader narrowing to the parse layer's error type must keep
        # catching this. Promoting it out of that hierarchy would silently
        # un-handle the case in callers that never named the new type -
        # mutate the base class to prove this assertion is the one that
        # fails.
        assert issubclass(NewerStateVersionError, ValueError)

    def test_a_file_older_than_this_build_reads_is_refused_as_older(
        self, tmp_path: Path
    ) -> None:
        path, payload = self._written_payload(tmp_path)
        payload["version"] = 0
        self._rewrite(path, payload)
        with pytest.raises(ValueError, match="no longer readable"):
            load_persisted_state(path)

    def test_a_foreign_schema_is_refused_by_name(self, tmp_path: Path) -> None:
        path, payload = self._written_payload(tmp_path)
        payload["schema"] = "vaultspec.rag.something-else"
        self._rewrite(path, payload)
        with pytest.raises(ValueError, match="declares schema"):
            load_persisted_state(path)

    @pytest.mark.parametrize(
        ("field", "value"),
        [("version", 0), ("schema", "vaultspec.rag.something-else")],
    )
    def test_only_a_too_new_file_carries_the_newer_build_refusal(
        self, tmp_path: Path, field: str, value: object
    ) -> None:
        # A layout below the readable floor is one this build genuinely cannot
        # interpret, with no newer sibling to preserve it for, and a foreign
        # schema is not this format at all. Widening the dedicated type to
        # either would tell an operator an intact file is waiting for a build
        # that reads it. Loosen the version comparison guarding the too-new
        # branch to prove this assertion is the one that fails.
        path, payload = self._written_payload(tmp_path)
        payload[field] = value
        self._rewrite(path, payload)
        with pytest.raises(ValueError) as caught:
            load_persisted_state(path)
        assert not isinstance(caught.value, NewerStateVersionError)

    def test_a_non_integer_version_is_refused(self, tmp_path: Path) -> None:
        path, payload = self._written_payload(tmp_path)
        payload["version"] = "1"
        self._rewrite(path, payload)
        with pytest.raises(ValueError, match="version must be an integer"):
            load_persisted_state(path)

    def test_fields_a_newer_writer_added_are_ignored_rather_than_refused(
        self, tmp_path: Path
    ) -> None:
        # Additive growth is what keeps the version from moving, so a file
        # carrying unknown keys at every level must still load unchanged.
        path, payload = self._written_payload(tmp_path)
        expected = load_persisted_state(path)
        payload["future_root_field"] = {"anything": True}
        job = cast("list[dict[str, object]]", payload["jobs"])[0]
        job["future_job_field"] = "ignored"
        cast("dict[str, object]", job["spec"])["future_spec_field"] = 1
        cast("dict[str, object]", job["runtime"])["future_runtime_field"] = None
        cast("dict[str, object]", job["resources"])["future_resource_field"] = []
        self._rewrite(path, payload)
        assert load_persisted_state(path) == expected

    def test_an_optional_field_a_newer_writer_added_defaults_when_absent(
        self, tmp_path: Path
    ) -> None:
        # The other half of additive growth: a build that writes a field must
        # still read a file written before that field existed.
        path, payload = self._written_payload(tmp_path)
        job = cast("list[dict[str, object]]", payload["jobs"])[0]
        for optional in (
            "resilience",
            "reuse",
            "drift",
            "gpu_lock_wait_seconds",
            "progress",
            "parent_job_id",
            "admission_acquired_at",
        ):
            del job[optional]
        self._rewrite(path, payload)
        loaded = load_persisted_state(path).jobs[0]
        assert loaded.resilience is None
        assert loaded.reuse is None
        assert loaded.drift is None
        assert loaded.gpu_lock_wait_seconds is None
        assert loaded.progress is None
        assert loaded.attempt.parent_job_id is None
        assert loaded.timestamps.admission_acquired_at is None


class TestPersistedJobStateLeavesNoDebris:
    """A write that fails must leave the state directory as it found it.

    Every temporary that outlives its write stays until an operator finds it,
    because nothing else looks at that directory again.
    """

    def test_a_replace_the_filesystem_refuses_leaves_no_temporary(
        self, tmp_path: Path
    ) -> None:
        # A real refusal, not a simulated one: a directory already occupies
        # the target name, so the temporary is written and the replace cannot
        # land. Nothing may survive that.
        path = tmp_path / "jobs-state.json"
        path.mkdir()
        with pytest.raises(PersistenceWriteError) as raised:
            save_persisted_state(path, _generation(_snapshot_in_state(JobState.QUEUED)))
        assert raised.value.published is False
        assert _temporaries(tmp_path) == []

    def test_a_successful_write_leaves_no_temporary(self, tmp_path: Path) -> None:
        path = tmp_path / "jobs-state.json"
        save_persisted_state(path, _generation(_snapshot_in_state(JobState.QUEUED)))
        assert _temporaries(tmp_path) == []

    @pytest.mark.parametrize(
        ("build_block", "cause"),
        [
            # Two refusals, because the encoder has two of them and each
            # translates through a different arm. Nesting past the encoder's
            # ceiling raises RecursionError, which is neither an OSError nor a
            # ValueError; a cycle raises ValueError. Letting either out
            # untranslated would break the one exception type every caller of
            # this function handles.
            pytest.param(_self_referential, ValueError, id="a-cycle"),
            pytest.param(
                _nested_past_the_encoders_limit, RecursionError, id="past-the-ceiling"
            ),
        ],
    )
    def test_a_payload_that_cannot_be_encoded_never_reaches_a_temporary(
        self,
        tmp_path: Path,
        build_block: Callable[[], dict[str, object]],
        cause: type[Exception],
    ) -> None:
        # Serialization happens before the temporary is named, so a payload
        # the encoder refuses cannot leave debris at all rather than leaving
        # debris that gets cleaned up. This is NOT a cleanup guard: breaking
        # the cleanup leaves it passing, which is the point.
        snapshot = replace(_snapshot_in_state(JobState.QUEUED), reuse=build_block())
        path = tmp_path / "jobs-state.json"
        with pytest.raises(PersistenceWriteError) as raised:
            save_persisted_state(path, _generation(snapshot))
        assert raised.value.published is False
        assert isinstance(raised.value.__cause__, cause)
        assert _temporaries(tmp_path) == []
        assert not path.exists()


class TestAbandonedTemporaryRecovery:
    """Temporaries a killed process left behind are reclaimed, evidence is not.

    Nothing in-process can clean up after a kill or a power loss, so the next
    start is the only place these can go - and the only place a dead one can
    be told apart from a write still running.
    """

    def _existing_state(self, tmp_path: Path) -> Path:
        path = tmp_path / "jobs-state.json"
        save_persisted_state(path, _generation(_snapshot_in_state(JobState.QUEUED)))
        return path

    def _abandoned(self, tmp_path: Path, name: str, *, age_hours: float) -> Path:
        temporary = tmp_path / name
        temporary.write_text('{"partial":', encoding="utf-8")
        _age(temporary, age_hours * 3600)
        return temporary

    def test_a_temporary_left_by_a_killed_writer_is_reclaimed(
        self, tmp_path: Path
    ) -> None:
        path = self._existing_state(tmp_path)
        abandoned = self._abandoned(
            tmp_path, ".jobs-state.json." + "a" * 32 + ".tmp", age_hours=48
        )
        assert load_persisted_state(path).jobs[0].id == "job-1"
        assert not abandoned.exists()

    def test_reclaiming_survives_an_absent_state_file(self, tmp_path: Path) -> None:
        # The kill that abandons a temporary can precede the first successful
        # publication, so reclaiming cannot depend on the state file existing.
        abandoned = self._abandoned(
            tmp_path, ".jobs-state.json.deadbeef.tmp", age_hours=48
        )
        with pytest.raises(FileNotFoundError):
            load_persisted_state(tmp_path / "jobs-state.json")
        assert not abandoned.exists()

    def test_a_temporary_still_inside_its_grace_window_is_spared(
        self, tmp_path: Path
    ) -> None:
        # A concurrent writer's in-flight temporary looks exactly like an
        # abandoned one apart from its age. Reclaiming it would delete a write
        # that is about to land, so recency alone must save it.
        path = self._existing_state(tmp_path)
        live = self._abandoned(tmp_path, ".jobs-state.json.beefcafe.tmp", age_hours=0)
        load_persisted_state(path)
        assert live.exists()

    @pytest.mark.parametrize(
        "preserved",
        [
            "jobs-state.json.invalid-20260101T000000Z",
            "jobs-state.json.invalid-20260101T000000Z-3",
            "jobs-state.json.from-newer-build-20260101T000000Z",
            "jobs-state.json.from-newer-build-20260101T000000Z-3",
        ],
    )
    def test_a_file_set_aside_as_evidence_is_never_reclaimed(
        self, tmp_path: Path, preserved: str
    ) -> None:
        # Preserved evidence outlives every grace window by design, whichever
        # condition set it aside. Each name is excluded because it carries
        # neither the leading dot nor the ``.tmp`` suffix, not because it is
        # unlikely to be matched - do not loosen either half of that test.
        # Reaping a file kept as the only copy of an operator's history would
        # be a worse defect than any this reclamation prevents.
        path = self._existing_state(tmp_path)
        evidence = tmp_path / preserved
        evidence.write_text("{}", encoding="utf-8")
        _age(evidence, 365 * 24 * 3600)
        load_persisted_state(path)
        assert evidence.exists()

    def test_a_temporary_belonging_to_another_file_is_never_reclaimed(
        self, tmp_path: Path
    ) -> None:
        path = self._existing_state(tmp_path)
        foreign = self._abandoned(
            tmp_path, ".managed-jobs.json.0123456789ab.tmp", age_hours=48
        )
        load_persisted_state(path)
        assert foreign.exists()

    def test_the_state_file_itself_is_never_reclaimed(self, tmp_path: Path) -> None:
        path = self._existing_state(tmp_path)
        _age(path, 365 * 24 * 3600)
        assert load_persisted_state(path).jobs[0].id == "job-1"
        assert path.exists()


# ---------------------------------------------------------------------------
# jobs module basic lifecycle
# ---------------------------------------------------------------------------
