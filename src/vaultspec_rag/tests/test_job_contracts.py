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
    PersistedManagerState,
    load_persisted_state,
    save_persisted_state,
)
from ..service import ServiceRegistry
from ..service_quiesce import ServiceQuiesceController

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..embeddings import EmbeddingModel

#: Includes the helpers a sibling suite imports from here. Declared so a
#: checker reads them as this module's surface rather than as helpers it
#: defines and never calls.
__all__ = [
    "_age",
    "_contract_class",
    "_declared_members",
    "_deeply_nested",
    "_fully_populated_snapshot",
    "_generation",
    "_identical",
    "_nested_past_the_encoders_limit",
    "_owner_class",
    "_parse_job_dispatch_module",
    "_parse_jobs_module",
    "_resources",
    "_round_trip_cases",
    "_runtime",
    "_self_referential",
    "_sibling_declarations",
    "_snapshot_in_state",
    "_spec",
    "_telemetry_construction",
    "_telemetry_of",
    "_telemetry_refusal",
    "_temporaries",
    "_valid_snapshot",
    "test_job_manager_import_does_not_pull_in_jobs",
    "test_job_manager_logs_under_the_jobs_namespace",
    "test_job_manager_rejects_unknown_attributes",
    "test_job_models_are_defined_exactly_once",
    "test_shared_owner_surface_is_declared_not_dynamic",
]


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
    "_control_quiesce.py",
    "_execution.py",
    "_persistence.py",
    "_progress.py",
    "_records.py",
)


def _sibling_declarations(package: Path, module_name: str) -> set[str]:
    """Return members declared by the other owner classes in this package."""
    declared: set[str] = set()
    for other in _OWNER_MODULES:
        if other == module_name:
            continue
        tree = ast.parse((package / other).read_text(encoding="utf-8"))
        declared |= _declared_members(_owner_class(tree))
    return declared


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
        # An owner may be split across sibling modules that mix into it, so
        # what one half declares counts as declared for the other. Without
        # this the guard reads a legitimate split as a dynamic reference.
        local = _declared_members(owner) | _sibling_declarations(package, module_name)
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
