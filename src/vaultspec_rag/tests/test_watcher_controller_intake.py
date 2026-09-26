"""Exact durable collection tests for watcher controller intake."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, cast

import pytest
from watchfiles import Change

from ..job_manager.manager import JobManager
from ..job_manager.models import JobAttemptContext, JobExecutionResult
from ..job_models import JobSource, JobState
from ..server._watcher_measurements import WatcherServiceMeasurement
from ..service import ServiceRegistry
from ..service_quiesce import ServiceQuiesceController
from ..watcher_controller import (
    ControllerMeasurement,
    ControllerReason,
    ControllerSnapshot,
    ControllerState,
    WatcherController,
)
from ..watcher_execution import (
    _CreatedWatcherJobRequest,
    controller_scope_from_retry_state,
    submit_watcher_job,
)
from ..watcher_intake import (
    _ClassifiedWatcherChange,
    _classify_watcher_changes,
    _ControllerBinding,
    _new_controller,
    _persist_and_observe_batch,
    _register_controller_binding,
    _WatcherEventBatch,
)
from ..watcher_retry import (
    WatcherPathEvent,
    WatcherPathObservation,
    WatcherSource,
)
from ..watcher_retry_policy import (
    WatcherRetryPolicy,
)
from ..watcher_runtime import WatcherChangeRouting, WatcherConvergenceSlot

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from ..indexer._codebase_indexer import CodeExecutionPreflight
    from ..indexer._document_indexer import DocumentExecutionPreflight
    from ..job_models import JobInitiator, JobOutcome, JobSnapshot, JobSpec
    from ..watcher_admission import AdmissionSelection

pytestmark = pytest.mark.unit


def _binding(
    root: Path,
    source: WatcherSource,
    registry: ServiceRegistry,
) -> _ControllerBinding:
    policy = WatcherRetryPolicy.for_root(root, source)
    slot = WatcherConvergenceSlot(JobSource(source.value), root, registry, policy)
    return _ControllerBinding(_new_controller(policy), slot, policy)


def test_classification_is_immutable_and_does_not_acknowledge_slots(
    tmp_path: Path,
) -> None:
    registry = ServiceRegistry()
    vault = _binding(tmp_path, WatcherSource.VAULT, registry)
    code = _binding(tmp_path, WatcherSource.CODE, registry)
    document = _binding(tmp_path, WatcherSource.DOCUMENT, registry)
    vault_path = tmp_path / ".vault" / "adr" / "decision.md"
    code_path = tmp_path / ".gitignore"
    code_path.write_text("generated/\n", encoding="utf-8")

    batch = _classify_watcher_changes(
        [(Change.modified, str(vault_path)), (Change.added, str(code_path))],
        routing=WatcherChangeRouting(
            root_dir=tmp_path,
            vault_dir=tmp_path / ".vault",
            policy=None,
            vault_slot=vault.slot,
            code_slot=code.slot,
            document_slot=document.slot,
        ),
    )

    assert [(change.source, change.path, change.event) for change in batch.changes] == [
        (WatcherSource.VAULT, vault_path, WatcherPathEvent.MODIFIED),
        (WatcherSource.CODE, code_path, WatcherPathEvent.ADDED),
        (WatcherSource.DOCUMENT, code_path, WatcherPathEvent.ADDED),
    ]
    assert vault.slot.dirty_paths() == frozenset()
    assert code.slot.dirty_paths() == frozenset()


async def test_exact_scope_is_durable_before_legacy_slot_acknowledgement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ServiceRegistry()
    binding = _binding(tmp_path.resolve(), WatcherSource.CODE, registry)
    changed = tmp_path.resolve() / "src" / "example.py"
    persisted_before_ack: list[bool] = []

    async def persist(
        policy: WatcherRetryPolicy,
        observations: tuple[WatcherPathObservation, ...],
        **_kwargs: object,
    ) -> bool:
        persisted_before_ack.append(binding.slot.dirty_paths() == frozenset())
        policy.mark_scope_pending(observations, now=time.time())
        return False

    monkeypatch.setattr(
        "vaultspec_rag.watcher_intake.persist_watcher_observations", persist
    )
    batch = _WatcherEventBatch(
        (
            _ClassifiedWatcherChange(
                WatcherSource.CODE,
                changed,
                WatcherPathEvent.MODIFIED,
            ),
        )
    )

    cancelled = await _persist_and_observe_batch(
        batch,
        (binding,),
        root_dir=tmp_path.resolve(),
    )

    assert cancelled is False
    assert persisted_before_ack == [True]
    assert binding.slot.dirty_paths() == frozenset({changed})
    state = binding.retry_policy.state
    assert [(item.relative_path, item.event_kinds) for item in state.pending_paths] == [
        ("src/example.py", frozenset({WatcherPathEvent.MODIFIED}))
    ]
    assert binding.controller.snapshot.state is ControllerState.COLLECTING
    assert binding.controller.snapshot.next_decision_at is not None


async def test_cancellation_is_delivered_after_every_source_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ServiceRegistry()
    root = tmp_path.resolve()
    code = _binding(root, WatcherSource.CODE, registry)
    document = _binding(root, WatcherSource.DOCUMENT, registry)
    committed: list[WatcherSource] = []

    async def persist(
        policy: WatcherRetryPolicy,
        observations: tuple[WatcherPathObservation, ...],
        *,
        source: WatcherSource,
        **_kwargs: object,
    ) -> bool:
        policy.mark_scope_pending(observations, now=time.time())
        committed.append(source)
        return source is WatcherSource.CODE

    monkeypatch.setattr(
        "vaultspec_rag.watcher_intake.persist_watcher_observations", persist
    )
    batch = _WatcherEventBatch(
        (
            _ClassifiedWatcherChange(
                WatcherSource.CODE, root / "src" / "a.py", WatcherPathEvent.ADDED
            ),
            _ClassifiedWatcherChange(
                WatcherSource.DOCUMENT,
                root / "docs" / "a.pdf",
                WatcherPathEvent.ADDED,
            ),
        )
    )

    cancelled = await _persist_and_observe_batch(
        batch,
        (code, document),
        root_dir=root,
    )

    assert cancelled is True
    assert committed == [WatcherSource.CODE, WatcherSource.DOCUMENT]
    assert code.retry_policy.state.pending_paths
    assert document.retry_policy.state.pending_paths


def _ready_binding(root: Path) -> _ControllerBinding:
    registry = ServiceRegistry()
    policy = WatcherRetryPolicy.for_root(root, WatcherSource.CODE)
    policy.mark_scope_pending(
        (
            WatcherPathObservation(
                relative_path="src/example.py",
                source=WatcherSource.CODE,
                first_observed_at=time.time(),
                latest_observed_at=time.time(),
                event_kinds=frozenset({WatcherPathEvent.MODIFIED}),
                generation=1,
            ),
        ),
        now=time.time(),
    )
    scope = controller_scope_from_retry_state(policy.state)
    controller = WatcherController(
        ControllerSnapshot(
            canonical_root=str(root),
            source=WatcherSource.CODE,
            state=ControllerState.READY,
            reason=ControllerReason.QUIET_TREE_DEADLINE,
            scope=scope,
            observed_at=time.time(),
            monotonic_at=time.monotonic(),
            next_decision_at=time.monotonic(),
            freshness_deadline=time.monotonic() + 300.0,
        ),
        monotonic=time.monotonic,
        wall_clock=time.time,
    )
    slot = WatcherConvergenceSlot(JobSource.CODE, root, registry, policy)
    return _ControllerBinding(controller, slot, policy)


async def test_production_reevaluation_consumes_service_measurement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = _ready_binding(tmp_path.resolve())
    callbacks: dict[str, object] = {}

    def register(
        _controller: WatcherController,
        *,
        reevaluate: Callable[[], Awaitable[None] | None],
        admit: Callable[[AdmissionSelection], Awaitable[None] | None],
    ) -> None:
        callbacks.update(reevaluate=reevaluate, admit=admit)

    def capture(
        _registry: ServiceRegistry,
        *,
        generation: int,
        observed_at: float,
        **_kwargs: object,
    ) -> WatcherServiceMeasurement:
        measurement = ControllerMeasurement(
            generation=generation,
            observed_at=observed_at,
            storage_available=False,
            service_quiesced=False,
        )
        return WatcherServiceMeasurement(
            generation=measurement.generation,
            observed_at=measurement.observed_at,
            controller=measurement,
            active_index_generations=(),
            machine_pressure_tier="nominal",
            requested_cost=None,
            effective_cost=None,
            failure_kind=None,
            circuit_state=None,
            unavailable=frozenset(),
        )

    monkeypatch.setattr(
        "vaultspec_rag.server._watcher._register_watcher_controller", register
    )
    monkeypatch.setattr(
        "vaultspec_rag.server._watcher_measurements.capture_watcher_measurement",
        capture,
    )

    _register_controller_binding(binding)
    reevaluate = cast("Callable[[], Awaitable[None]]", callbacks["reevaluate"])
    await reevaluate()

    assert binding.controller.snapshot.state is ControllerState.BACKPRESSURED
    assert binding.controller.snapshot.reason is ControllerReason.STORAGE_PRESSURE
    assert binding.controller.snapshot.measurement is not None
    assert binding.controller.snapshot.measurement.generation == 1


@pytest.mark.parametrize("failure_site", ["preflight", "create"])
async def test_precreation_exception_restores_exact_durable_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_site: str,
) -> None:
    binding = _ready_binding(tmp_path.resolve())

    class FailingManager:
        def get(self, _job_id: str) -> JobSnapshot | None:
            return None

        def create(self, *_args: object, **_kwargs: object) -> JobSnapshot:
            raise RuntimeError("create exploded")

    async def preflight(
        *_args: object, **_kwargs: object
    ) -> tuple[CodeExecutionPreflight | None, DocumentExecutionPreflight | None]:
        if failure_site == "preflight":
            raise RuntimeError("preflight exploded")
        return None, None

    monkeypatch.setattr(
        "vaultspec_rag.watcher_execution._preflight_scoped_paths", preflight
    )
    monkeypatch.setattr(
        "vaultspec_rag.watcher_execution._jobs.get_job_manager",
        lambda: FailingManager(),
    )

    with pytest.raises(RuntimeError, match=f"{failure_site} exploded"):
        await submit_watcher_job(
            binding.slot,
            controller=binding.controller,
            now=time.monotonic(),
            secondary_graph_cache=None,
        )

    state = binding.retry_policy.state
    assert [item.relative_path for item in state.pending_paths] == ["src/example.py"]
    assert state.captured_paths == ()
    assert state.attempt_job_id is None
    assert binding.controller.snapshot.state is ControllerState.COLLECTING


async def _no_preflight(
    *_args: object, **_kwargs: object
) -> tuple[CodeExecutionPreflight | None, DocumentExecutionPreflight | None]:
    return None, None


def _real_manager(monkeypatch: pytest.MonkeyPatch) -> JobManager:
    manager = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        max_nonterminal=4,
        state_path=None,
    )
    monkeypatch.setattr(
        "vaultspec_rag.watcher_execution._preflight_scoped_paths", _no_preflight
    )
    monkeypatch.setattr(
        "vaultspec_rag.watcher_execution._jobs.get_job_manager", lambda: manager
    )
    return manager


async def test_change_observed_during_job_creation_still_dispatches_the_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Creating the job awaits a thread hop, and the intake task observes new
    # changes meanwhile. That moved the controller off ready, admission raised,
    # and the created job stayed queued with nothing to dispatch it; every later
    # admission then joined that job, wedging the source. Mutation: limiting
    # admission to a ready controller makes the submission raise instead of
    # dispatching.
    binding = _ready_binding(tmp_path.resolve())
    manager = _real_manager(monkeypatch)
    create = manager.create

    def create_while_a_change_arrives(
        spec: JobSpec,
        initiator: JobInitiator,
        *,
        job_id: str | None = None,
    ) -> JobOutcome:
        outcome = create(spec, initiator, job_id=job_id)
        binding.controller.observe(
            controller_scope_from_retry_state(binding.retry_policy.state)
        )
        return outcome

    dispatched: list[str] = []

    async def dispatch(request: _CreatedWatcherJobRequest) -> None:
        dispatched.append(request.snapshot.id)

    monkeypatch.setattr(manager, "create", create_while_a_change_arrives)
    monkeypatch.setattr(
        "vaultspec_rag.watcher_execution._dispatch_created_watcher_job", dispatch
    )

    await submit_watcher_job(
        binding.slot,
        controller=binding.controller,
        now=time.monotonic(),
        secondary_graph_cache=None,
    )

    assert dispatched == [binding.slot.job_id]
    assert binding.controller.snapshot.state is ControllerState.ADMITTED
    assert binding.controller.snapshot.job_id == binding.slot.job_id


async def test_failure_after_job_creation_settles_the_created_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Once the slot names the created job, later admissions join it rather than
    # create another, so a failure before dispatch must fail that job and
    # release its durable fence. Mutation: removing the post-creation guard
    # leaves the job queued and fails the state assertion below.
    binding = _ready_binding(tmp_path.resolve())
    manager = _real_manager(monkeypatch)
    created: list[str] = []

    async def dispatch(request: _CreatedWatcherJobRequest) -> None:
        created.append(request.snapshot.id)
        raise RuntimeError("dispatch exploded")

    monkeypatch.setattr(
        "vaultspec_rag.watcher_execution._dispatch_created_watcher_job", dispatch
    )

    with pytest.raises(RuntimeError, match="dispatch exploded"):
        await submit_watcher_job(
            binding.slot,
            controller=binding.controller,
            now=time.monotonic(),
            secondary_graph_cache=None,
        )

    [job_id] = created
    job = manager.get(job_id)
    assert job is not None
    assert job.state is JobState.FAILED
    state = binding.retry_policy.state
    assert state.attempt_job_id is None
    assert [item.relative_path for item in state.pending_paths] == ["src/example.py"]


async def test_failure_after_dispatch_leaves_the_running_attempt_to_its_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The post-creation guard also spans the dispatch call. Once the job has a
    # runtime owner, that owner settles the durable fence when it finishes;
    # settling it from the guard as well records a failure for work that is
    # still running. Mutation: dropping the runtime-owned early return clears
    # the fence and fails the attempt assertion below.
    binding = _ready_binding(tmp_path.resolve())
    manager = _real_manager(monkeypatch)
    release = threading.Event()
    created: list[str] = []

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        del context
        release.wait(timeout=10.0)
        return JobExecutionResult(summary="ok")

    async def dispatch_then_fail(request: _CreatedWatcherJobRequest) -> None:
        created.append(request.snapshot.id)
        manager.bind_dispatch(request.snapshot.id, runner)
        await manager.dispatch_async(request.snapshot.id)
        raise RuntimeError("reporting exploded")

    monkeypatch.setattr(
        "vaultspec_rag.watcher_execution._dispatch_created_watcher_job",
        dispatch_then_fail,
    )

    try:
        with pytest.raises(RuntimeError, match="reporting exploded"):
            await submit_watcher_job(
                binding.slot,
                controller=binding.controller,
                now=time.monotonic(),
                secondary_graph_cache=None,
            )
        [job_id] = created
        assert binding.retry_policy.state.attempt_job_id == job_id
        job = manager.get(job_id)
        assert job is not None
        assert job.state is not JobState.FAILED
    finally:
        release.set()
        for job_id in created:
            await manager.wait_for_attempt(job_id, timeout_seconds=10.0)
