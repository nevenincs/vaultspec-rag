"""Operator rebuild reconciliation through real publication and retry ledgers."""

from __future__ import annotations

import os
import time
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from .. import store_schema
from .._job_errors import JobError, JobErrorKind
from .._source_types import PublicSourceType
from .._store_writes import workspace_volume_path
from ..indexer._run_ledger_models import (
    FinalizationPhase,
    RunAuthority,
    RunTerminalState,
    index_run_ledger_path,
)
from ..indexer._run_ledger_runtime import RunLedger
from ..job_manager.manager import JobManager
from ..job_manager.models import JobAttemptContext, JobExecutionResult
from ..job_models import JobMode, JobSource, JobState
from ..service import ServiceRegistry
from ..service_quiesce import ServiceQuiesceController
from ..store_runtime import configured_backend_identity
from ..watcher_controller import ControllerMeasurement, ControllerState
from ..watcher_execution import (
    controller_retry_at_from_retry_state,
    controller_scope_from_retry_state,
)
from ..watcher_intake import _new_controller
from ..watcher_retry import (
    WatcherCircuitState,
    WatcherPathEvent,
    WatcherPathObservation,
    WatcherScopeRefusal,
    WatcherSource,
    write_state,
)
from ..watcher_retry_policy import (
    _ADMISSION_RESERVATIONS,
    WatcherRetryPolicy,
    _WatcherRetryOptions,
)
from ..watcher_runtime import (
    WatcherConvergenceSlot,
    reconcile_completed_rebuild,
    reconcile_restarted_slot,
)
from ._run_ledger_test_support import ledger_test_signature
from ._watcher_job_snapshot import watcher_job_snapshot

if TYPE_CHECKING:
    from pathlib import Path

    from ..job_models import JobSnapshot
    from ..watcher_retry import WatcherRetryState

pytestmark = pytest.mark.unit


def _observe(policy: WatcherRetryPolicy, path: str) -> None:
    now = time.time()
    policy.mark_scope_pending(
        (
            WatcherPathObservation(
                relative_path=path,
                source=policy.state.source,
                first_observed_at=now,
                latest_observed_at=now,
                event_kinds=frozenset({WatcherPathEvent.MODIFIED}),
                generation=policy.state.convergence_generation + 1,
            ),
        ),
        now=now,
    )


def _refused_policy(root: Path, source: WatcherSource) -> WatcherRetryPolicy:
    policy = WatcherRetryPolicy.for_root(root, source)
    _observe(policy, "src/old.py")
    admitted = policy.admit()
    assert admitted.attempt_generation is not None
    policy.record_failure(
        JobError(JobErrorKind.FULL_REINDEX_REQUIRED, "membership proof changed"),
        admitted.attempt_generation,
    )
    return policy


def _published_rebuild(root: Path, source: WatcherSource) -> JobSnapshot:
    started = time.time()
    collections = {
        WatcherSource.CODE: store_schema.CODE_COLLECTION,
        WatcherSource.VAULT: store_schema.VAULT_COLLECTION,
        WatcherSource.DOCUMENT: store_schema.DOCUMENT_COLLECTION,
    }
    signature = replace(
        ledger_test_signature(root),
        source_type=PublicSourceType(source.value),
        collection_identity=collections[source],
        payload_schema=store_schema.STORAGE_SCHEMA_VERSION,
        backend_identity=configured_backend_identity(root),
    )
    ledger = RunLedger(index_run_ledger_path(workspace_volume_path(root)))
    generation = ledger.start_generation(signature)
    ledger.establish_verified_publication(
        generation.generation_id, RunAuthority.REBUILD, ()
    )
    for phase in (
        FinalizationPhase.STALE_RECONCILED,
        FinalizationPhase.METADATA_PUBLISHED,
        FinalizationPhase.GENERATION_PUBLISHED,
    ):
        ledger.advance_finalization(generation.generation_id, phase)
    ledger.finish_generation(generation.generation_id, RunTerminalState.SUCCEEDED)
    finished = time.time()
    snapshot = watcher_job_snapshot(root, JobState.SUCCEEDED)
    return replace(
        snapshot,
        spec=replace(
            snapshot.spec,
            source=JobSource(source.value),
            mode=JobMode.REBUILD,
            authority=RunAuthority.REBUILD,
        ),
        timestamps=replace(
            snapshot.timestamps,
            started_at=started,
            finished_at=finished,
            state_changed_at=finished,
        ),
    )


@pytest.mark.parametrize("source", list(WatcherSource))
def test_verified_explicit_rebuild_clears_refusal_and_keeps_later_exact_events(
    tmp_path: Path, source: WatcherSource
) -> None:
    root = tmp_path.resolve()
    policy = _refused_policy(root, source)
    snapshot = _published_rebuild(root, source)
    _observe(policy, "src/later.py")
    previous_generation = policy.state.convergence_generation

    assert reconcile_completed_rebuild(snapshot)

    restored = WatcherRetryPolicy.for_root(root, source)
    state = restored.state
    assert state.scope_refusal is None
    assert state.last_error_kind is None
    assert state.circuit_state is WatcherCircuitState.CLOSED
    assert state.consecutive_failures == 0
    assert state.convergence_generation == previous_generation + 1
    assert [item.relative_path for item in state.pending_paths] == ["src/later.py"]
    assert _new_controller(restored).snapshot.state is ControllerState.COLLECTING
    assert not reconcile_completed_rebuild(snapshot)
    assert restored.admit().admitted


def test_verified_rebuild_converges_empty_scope_with_closed_circuit(
    tmp_path: Path,
) -> None:
    # Mutation: retaining prior retry metadata during observation/evaluation
    # reports a successfully rebuilt empty controller as converged and open.
    root = tmp_path.resolve()
    policy = _refused_policy(root, WatcherSource.CODE)
    controller = _new_controller(policy)
    assert controller.snapshot.circuit_state is WatcherCircuitState.OPEN
    snapshot = _published_rebuild(root, WatcherSource.CODE)
    assert reconcile_completed_rebuild(snapshot)
    state = policy.refresh()
    controller.observe(
        controller_scope_from_retry_state(state),
        circuit_state=state.circuit_state,
        retry_at=controller_retry_at_from_retry_state(state),
    )
    observed = controller.evaluate(
        ControllerMeasurement(generation=1, observed_at=time.monotonic()),
        circuit_state=state.circuit_state,
        retry_at=controller_retry_at_from_retry_state(state),
    )

    assert observed.state is ControllerState.CONVERGED
    assert observed.circuit_state is WatcherCircuitState.CLOSED
    assert observed.retry_at is None
    assert observed.remediation is None


async def test_restart_recovers_a_completed_rebuild_before_its_watcher_callback(
    tmp_path: Path,
) -> None:
    root = tmp_path.resolve()
    policy = _refused_policy(root, WatcherSource.CODE)
    manager = JobManager(quiesce_controller=ServiceQuiesceController())
    requested = watcher_job_snapshot(root, JobState.QUEUED)
    outcome = manager.create(
        replace(requested.spec, mode=JobMode.REBUILD, authority=RunAuthority.REBUILD),
        requested.initiator,
    )
    assert outcome.job is not None
    job_id = outcome.job.id

    def publish(_context: JobAttemptContext) -> JobExecutionResult:
        _published_rebuild(root, WatcherSource.CODE)
        return JobExecutionResult(summary="verified rebuild completed")

    manager.bind_dispatch(job_id, publish)
    await manager.dispatch_async(job_id)
    await manager.wait_for_attempt(job_id, timeout_seconds=10.0)
    finished = manager.get(job_id)
    assert finished is not None and finished.state is JobState.SUCCEEDED
    assert policy.state.scope_refusal is not None
    _observe(policy, "src/after-rebuild.py")
    restarted = WatcherRetryPolicy.for_root(root, WatcherSource.CODE)
    slot = WatcherConvergenceSlot(JobSource.CODE, root, ServiceRegistry(), restarted)

    await reconcile_restarted_slot(slot, manager)

    assert restarted.state.scope_refusal is None
    assert restarted.state.circuit_state is WatcherCircuitState.CLOSED
    assert [item.relative_path for item in restarted.state.pending_paths] == [
        "src/after-rebuild.py"
    ]
    assert _new_controller(restarted).snapshot.state is ControllerState.COLLECTING


@pytest.mark.parametrize("job_bound", [False, True])
async def test_rebuild_callback_preserves_dead_fence_for_startup_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, job_bound: bool
) -> None:
    # Mutation: adopting a dead attempt in the completion callback strands its
    # token and prevents the canonical startup owner from recovering it.
    root = tmp_path.resolve()
    policy = WatcherRetryPolicy.for_root(root, WatcherSource.CODE)
    _observe(policy, "src/captured.py")
    admitted = policy.admit_reserved(
        policy.reserve_admission(), job_id="lost-watcher" if job_bound else None
    )
    assert admitted.attempt_generation is not None
    token = policy.state.attempt_token
    assert token is not None

    def dead_owner(_state: WatcherRetryState) -> bool:
        # The recorded owner is this test process, whose liveness is outside
        # the pure ownership transition under test.
        return False

    monkeypatch.setattr(
        "vaultspec_rag.watcher_retry_policy._attempt_owner_is_live", dead_owner
    )
    manager = JobManager(quiesce_controller=ServiceQuiesceController())
    requested = watcher_job_snapshot(root, JobState.QUEUED)
    outcome = manager.create(
        replace(requested.spec, mode=JobMode.REBUILD, authority=RunAuthority.REBUILD),
        requested.initiator,
    )
    assert outcome.job is not None
    job_id = outcome.job.id

    def publish(_context: JobAttemptContext) -> JobExecutionResult:
        _published_rebuild(root, WatcherSource.CODE)
        return JobExecutionResult(summary="verified rebuild completed")

    manager.bind_dispatch(job_id, publish)
    await manager.dispatch_async(job_id)
    await manager.wait_for_attempt(job_id, timeout_seconds=10.0)
    completed = manager.get(job_id)
    assert completed is not None and completed.state is JobState.SUCCEEDED
    _observe(policy, "src/later.py")

    assert not reconcile_completed_rebuild(completed)
    assert token not in _ADMISSION_RESERVATIONS
    restarted = WatcherRetryPolicy.for_root(root, WatcherSource.CODE)
    slot = WatcherConvergenceSlot(JobSource.CODE, root, ServiceRegistry(), restarted)
    try:
        await reconcile_restarted_slot(slot, manager)
        assert restarted.state.scope_refusal is None
        assert restarted.state.attempt_generation is None
        assert restarted.state.circuit_state is WatcherCircuitState.CLOSED
        assert token not in _ADMISSION_RESERVATIONS
        assert [item.relative_path for item in restarted.state.pending_paths] == [
            "src/captured.py",
            "src/later.py",
        ]
        assert _new_controller(restarted).snapshot.state is ControllerState.COLLECTING
    finally:
        if restarted.state.attempt_generation is not None:
            restarted.record_interrupted(restarted.state.attempt_generation)


@pytest.mark.parametrize(
    "alteration", ["failed", "incremental", "authority", "source", "root", "stale"]
)
def test_unrelated_or_unverified_job_cannot_clear_rebuild_refusal(
    tmp_path: Path, alteration: str
) -> None:
    # Mutation: removing a named job-authority check lets that job clear the
    # refusal even though it cannot prove this source was explicitly rebuilt.
    root = tmp_path.resolve()
    policy = _refused_policy(root, WatcherSource.CODE)
    snapshot = _published_rebuild(root, WatcherSource.CODE)
    if alteration == "failed":
        snapshot = replace(snapshot, state=JobState.FAILED)
    elif alteration == "incremental":
        snapshot = replace(
            snapshot, spec=replace(snapshot.spec, mode=JobMode.INCREMENTAL)
        )
    elif alteration == "authority":
        snapshot = replace(
            snapshot, spec=replace(snapshot.spec, authority=RunAuthority.PUBLICATION)
        )
    elif alteration == "source":
        snapshot = replace(
            snapshot, spec=replace(snapshot.spec, source=JobSource.VAULT)
        )
    elif alteration == "root":
        snapshot = _published_rebuild(root / "foreign", WatcherSource.CODE)
    else:
        snapshot = replace(
            snapshot,
            timestamps=replace(snapshot.timestamps, started_at=0.0, finished_at=1.0),
        )

    assert not policy.reconcile_rebuild(snapshot)
    assert policy.refresh().scope_refusal is not None
    assert not policy.admit(now=time.time() + 1000.0).admitted


def test_success_without_current_publication_cannot_clear_refusal(
    tmp_path: Path,
) -> None:
    # Mutation: trusting job success without reading proof clears refusal after
    # its publication has been removed or changed to an incompatible backend.
    root = tmp_path.resolve()
    policy = _refused_policy(root, WatcherSource.CODE)
    snapshot = _published_rebuild(root, WatcherSource.CODE)
    ledger = RunLedger(index_run_ledger_path(workspace_volume_path(root)))
    ledger.clear_publication_source(
        PublicSourceType.CODE, str(root), configured_backend_identity(root)
    )

    assert not reconcile_completed_rebuild(snapshot)
    assert policy.refresh().scope_refusal is not None


def test_rebuild_before_a_new_refusal_cannot_clear_it(tmp_path: Path) -> None:
    # Mutation: ignoring the failure time reuses an older successful rebuild
    # as authority to clear a refusal caused by later incompatible evidence.
    root = tmp_path.resolve()
    snapshot = _published_rebuild(root, WatcherSource.CODE)
    policy = _refused_policy(root, WatcherSource.CODE)

    assert not reconcile_completed_rebuild(snapshot)
    assert policy.refresh().scope_refusal is not None


@pytest.mark.parametrize("failure_kind", ["capacity", "marker", "legacy_missing_time"])
@pytest.mark.parametrize("outcome", ["success", "failed", "interrupted"])
def test_attempt_settlement_preserves_newer_scope_refusal_until_a_new_rebuild(
    tmp_path: Path, failure_kind: str, outcome: str
) -> None:
    # Mutation: clearing refusal time on captured-attempt success permits an
    # older verified full proof to erase newer unknown scope on restart.
    root = tmp_path.resolve()
    old_rebuild = _published_rebuild(root, WatcherSource.CODE)
    state_path = workspace_volume_path(root) / "watcher-retry" / "code.json"
    policy = WatcherRetryPolicy(
        state_path,
        _WatcherRetryOptions(
            canonical_root=os.path.normcase(str(root)),
            source=WatcherSource.CODE,
            base_seconds=1.0,
            max_seconds=2.0,
            jitter_fraction=0.0,
            failure_threshold=3,
            scope_max_paths=1,
        ),
    )
    _observe(policy, "src/captured.py")
    admitted = policy.admit_reserved(policy.reserve_admission(), job_id="watcher")
    assert admitted.attempt_generation is not None
    if failure_kind == "marker":
        observer = WatcherRetryPolicy.for_root(root, WatcherSource.CODE)
        observer.write_recovery_marker()
        refused = policy.refresh()
        assert refused.scope_refusal is WatcherScopeRefusal.FULL_REINDEX_REQUIRED
    else:
        _observe(policy, "src/overflow.py")
        refused = policy.state
        assert refused.scope_refusal is WatcherScopeRefusal.SCOPE_CAPACITY_EXCEEDED
        assert refused.pending_paths == ()
        assert policy.refresh().scope_refusal is refused.scope_refusal
    assert refused.last_failure_at is not None

    if outcome == "success":
        settled = policy.record_success(admitted.attempt_generation)
    elif outcome == "failed":
        settled = policy.record_failure(
            TimeoutError("captured attempt failed"), admitted.attempt_generation
        )
    else:
        settled = policy.record_interrupted(admitted.attempt_generation)

    assert settled.scope_refusal is refused.scope_refusal
    assert settled.last_error_kind is refused.last_error_kind
    assert settled.last_error_detail == refused.last_error_detail
    assert settled.last_failure_at == refused.last_failure_at
    assert settled.convergence_pending
    assert settled.circuit_state is WatcherCircuitState.OPEN
    assert settled.next_retry_at == 0.0
    if failure_kind == "legacy_missing_time":
        write_state(
            state_path,
            replace(
                settled,
                last_error_kind=None,
                last_error_detail=None,
                last_failure_at=None,
                circuit_state=WatcherCircuitState.CLOSED,
            ),
        )
    assert not policy.reconcile_rebuild(old_rebuild)
    assert policy.refresh().scope_refusal is not None
    assert not policy.admit().admitted

    new_rebuild = _published_rebuild(root, WatcherSource.CODE)
    assert policy.reconcile_rebuild(new_rebuild)
    assert policy.state.scope_refusal is None
    assert policy.state.last_error_kind is None
    assert policy.state.circuit_state is WatcherCircuitState.CLOSED


@pytest.mark.parametrize("failure_kind", ["capacity", "marker"])
@pytest.mark.parametrize("job_bound", [False, True])
@pytest.mark.parametrize("missing_time", [False, True])
def test_abandoned_attempt_rebuild_must_postdate_its_later_scope_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
    job_bound: bool,
    missing_time: bool,
) -> None:
    # Mutation: using only the abandoned attempt start admits a verified
    # rebuild whose proof predates unknown scope recorded during that attempt.
    root = tmp_path.resolve()
    state_path = workspace_volume_path(root) / "watcher-retry" / "code.json"
    policy = WatcherRetryPolicy(
        state_path,
        _WatcherRetryOptions(
            canonical_root=os.path.normcase(str(root)),
            source=WatcherSource.CODE,
            base_seconds=1.0,
            max_seconds=2.0,
            jitter_fraction=0.0,
            failure_threshold=3,
            scope_max_paths=1,
        ),
    )
    _observe(policy, "src/captured.py")
    admitted = policy.admit_reserved(
        policy.reserve_admission(), job_id="watcher" if job_bound else None
    )
    assert admitted.attempt_generation is not None
    old_rebuild = _published_rebuild(root, WatcherSource.CODE)
    if failure_kind == "marker":
        observer = WatcherRetryPolicy.for_root(root, WatcherSource.CODE)
        observer.write_recovery_marker()
        policy.refresh()
    else:
        _observe(policy, "src/overflow.py")
    refused = policy.state
    assert refused.scope_refusal is not None
    if missing_time:
        write_state(state_path, replace(refused, last_failure_at=None))

    def dead_owner(_state: WatcherRetryState) -> bool:
        return False

    monkeypatch.setattr(
        "vaultspec_rag.watcher_retry_policy._attempt_owner_is_live", dead_owner
    )
    restarted = WatcherRetryPolicy.for_root(root, WatcherSource.CODE)
    try:
        assert not restarted.reconcile_rebuild(
            old_rebuild, resolve_abandoned_attempt=True
        )
        assert restarted.state.scope_refusal is refused.scope_refusal
        assert restarted.state.last_failure_at == (
            None if missing_time and job_bound else refused.last_failure_at
        )
        new_rebuild = _published_rebuild(root, WatcherSource.CODE)
        assert restarted.reconcile_rebuild(new_rebuild, resolve_abandoned_attempt=True)
        assert restarted.state.scope_refusal is None
        assert restarted.state.attempt_generation is None
        assert restarted.state.circuit_state is WatcherCircuitState.CLOSED
        assert [item.relative_path for item in restarted.state.pending_paths] == [
            "src/captured.py"
        ]
    finally:
        if restarted.state.attempt_generation is not None:
            restarted.record_interrupted(restarted.state.attempt_generation)


def test_rebuild_does_not_create_state_for_an_unwatched_root(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    snapshot = _published_rebuild(root, WatcherSource.CODE)
    state_directory = workspace_volume_path(root) / "watcher-retry"

    assert not reconcile_completed_rebuild(snapshot)
    assert not state_directory.exists()
