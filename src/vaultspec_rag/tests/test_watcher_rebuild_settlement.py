"""Explicit publication success reconciles only obsolete watcher refusal."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import replace
from functools import partial
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from .. import store_schema
from .._job_errors import JobError, JobErrorKind
from .._publication_state import _collection, acquire_publication_snapshot
from .._source_types import PublicSourceType
from .._store_writes import workspace_volume_path
from ..indexer._publication_proof import ProofMissingError
from ..indexer._run_ledger_models import RunAuthority, index_run_ledger_path
from ..indexer._run_ledger_runtime import RunLedger
from ..job_dispatch import IndexJobBinding, _finish_index_job, bind_index_job
from ..job_manager.manager import JobManager
from ..job_manager.models import JobExecutionResult
from ..job_models import (
    IndexResilienceSnapshot,
    JobInitiator,
    JobMode,
    JobOperation,
    JobSource,
    JobSpec,
    JobState,
)
from ..server import _watcher
from ..server._watcher import _WatcherScheduler
from ..service import ServiceRegistry
from ..service_quiesce import ServiceQuiesceController
from ..store_runtime import configured_backend_identity
from ..watcher_controller import ControllerState
from ..watcher_intake import (
    _ControllerBinding,
    _new_controller,
    _register_controller_binding,
)
from ..watcher_retry import (
    STATE_DIRECTORY,
    WatcherCircuitState,
    WatcherPathEvent,
    WatcherPathObservation,
    WatcherRetryStateError,
    WatcherScopeRefusal,
    WatcherSource,
    process_identity_is_live,
    read_state,
    write_state,
)
from ..watcher_retry_policy import _ADMISSION_RESERVATIONS, WatcherRetryPolicy
from ..watcher_runtime import WatcherConvergenceSlot, reconcile_restarted_slot
from ._run_ledger_test_support import (
    ledger_test_publish_and_compact,
    ledger_test_signature,
)
from ._watcher_job_snapshot import watcher_job_snapshot

if TYPE_CHECKING:
    from pathlib import Path

    from ..job_manager.models import JobAttemptContext
    from ..job_models import JobSnapshot
    from ..watcher_retry import WatcherRetryState

pytestmark = pytest.mark.unit


def _observation(
    source: WatcherSource, path: str, *, now: float = 1.0
) -> WatcherPathObservation:
    return WatcherPathObservation(
        relative_path=path,
        source=source,
        first_observed_at=now,
        latest_observed_at=now,
        event_kinds=frozenset({WatcherPathEvent.MODIFIED}),
        generation=1,
    )


def _refused(
    root: Path, source: WatcherSource = WatcherSource.CODE
) -> WatcherRetryPolicy:
    policy = WatcherRetryPolicy.for_root(root, source, now=1.0)
    # This base refusal has no exact scope; scoped preservation uses its own intake.
    policy.mark_convergence_pending(now=1.0)
    attempt = policy.admit(now=2.0).attempt_generation
    assert attempt is not None
    policy.record_failure(
        JobError(
            JobErrorKind.FULL_REINDEX_REQUIRED, "publication requires explicit rebuild"
        ),
        attempt,
        now=3.0,
        random_unit=0.0,
    )
    return policy


def _certified_generation(root: Path, source: WatcherSource) -> str:
    """Publish actual empty canonical authority for a completed fixture run."""
    public_source = PublicSourceType(source.value)
    try:
        return acquire_publication_snapshot(root, public_source).proof.generation_id
    except ProofMissingError:
        pass
    ledger = RunLedger(index_run_ledger_path(workspace_volume_path(root)))
    signature = replace(
        ledger_test_signature(root),
        source_type=public_source,
        collection_identity=_collection(public_source),
        backend_identity=configured_backend_identity(root),
        payload_schema=store_schema.STORAGE_SCHEMA_VERSION,
        clean=True,
    )
    generation = ledger.start_generation(signature)
    ledger_test_publish_and_compact(ledger, generation.generation_id)
    return generation.generation_id


def _rebuilt(root: Path, source: WatcherSource = WatcherSource.CODE) -> JobSnapshot:
    snapshot = watcher_job_snapshot(root, JobState.SUCCEEDED)
    return replace(
        snapshot,
        spec=replace(
            snapshot.spec,
            source=JobSource(source.value),
            mode=JobMode.REBUILD,
            authority=RunAuthority.REBUILD,
        ),
        initiator=JobInitiator("cli", "explicit rebuild", str(root)),
        timestamps=replace(snapshot.timestamps, started_at=10.0, finished_at=20.0),
        result="full generation published",
        resilience=IndexResilienceSnapshot(
            generation_id=_certified_generation(root, source),
            terminal_outcome="succeeded",
            checkpoint_compatible=True,
        ),
    )


def _persist_exited_owner_attempt(
    root: Path,
    job_id: str | None,
    *,
    exact_paths: bool = True,
    source: WatcherSource = WatcherSource.CODE,
) -> WatcherRetryState:
    """Leave a real scoped attempt whose recorded child process has exited."""
    from ..config._settings import get_config

    child = dedent(
        """\
        import sys
        from dataclasses import replace
        from pathlib import Path
        from vaultspec_rag._job_errors import JobErrorKind
        from vaultspec_rag.watcher_retry import (
            WatcherCircuitState, WatcherPathEvent, WatcherPathObservation,
            WatcherScopeRefusal, WatcherSource, write_state,
        )
        from vaultspec_rag.watcher_retry_policy import WatcherRetryPolicy

        source = WatcherSource(sys.argv[4])
        policy = WatcherRetryPolicy.for_root(Path(sys.argv[1]), source)
        def observe(path, timestamp):
            return WatcherPathObservation(
                path, source, timestamp, timestamp,
                frozenset({WatcherPathEvent.MODIFIED}), 1,
            )
        exact_paths = sys.argv[3] == 'exact'
        if exact_paths:
            policy.mark_scope_pending((observe('src/captured.py', 1.0),), now=1.0)
        else:
            policy.mark_convergence_pending(now=1.0)
        decision = policy.admit_reserved(
            policy.reserve_admission(), job_id=sys.argv[2] or None, now=2.0,
        )
        assert decision.admitted
        if exact_paths:
            policy.mark_scope_pending((observe('src/later.py', 12.0),), now=12.0)
        else:
            policy.mark_convergence_pending(now=4.0)
        write_state(policy._path, replace(
            policy.state, scope_refusal=WatcherScopeRefusal.FULL_REINDEX_REQUIRED,
            last_error_kind=JobErrorKind.FULL_REINDEX_REQUIRED, last_failure_at=3.0,
            circuit_state=WatcherCircuitState.OPEN,
        ))
        """
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            child,
            str(root),
            job_id or "",
            "exact" if exact_paths else "unknown",
            source.value,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=20.0,
    )
    assert completed.returncode == 0
    cfg = get_config()
    state = read_state(
        root / cfg.data_dir / STATE_DIRECTORY / f"{source.value}.json",
        scope_max_paths=cfg.watch_scope_max_paths,
        scope_max_bytes=cfg.watch_scope_max_bytes,
    )
    assert state.attempt_owner_pid is not None
    assert state.attempt_owner_create_time is not None
    assert not process_identity_is_live(
        state.attempt_owner_pid, state.attempt_owner_create_time
    )
    return state


async def _complete_job(
    manager: JobManager, spec: JobSpec, initiator: JobInitiator
) -> JobSnapshot:
    created = manager.create(spec, initiator)
    assert created.job is not None
    finished = asyncio.Event()

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        assert spec.project_root is not None
        from pathlib import Path

        context.set_resilience(
            IndexResilienceSnapshot(
                generation_id=_certified_generation(
                    Path(spec.project_root), WatcherSource(spec.source.value)
                ),
                terminal_outcome="succeeded",
                checkpoint_compatible=True,
            )
        )
        return JobExecutionResult(summary="generation published")

    def on_finished(
        _snapshot: JobSnapshot,
        _duration: float,
        _result: JobExecutionResult | None,
        _error: BaseException | None,
    ) -> None:
        finished.set()

    assert manager.bind_dispatch(created.job.id, runner, on_finished=on_finished).job
    assert (await manager.dispatch_async(created.job.id)).job
    joined = await manager.wait_for_attempt(created.job.id, timeout_seconds=30.0)
    assert joined.code == "attempt_released", joined
    assert finished.is_set(), joined
    snapshot = manager.get(created.job.id)
    assert snapshot is not None and snapshot.state is JobState.SUCCEEDED
    return snapshot


@pytest.mark.parametrize("source", tuple(WatcherSource))
def test_successful_explicit_rebuild_clears_old_refusal_durably(
    tmp_path: Path, source: WatcherSource
) -> None:
    policy = _refused(tmp_path, source)
    controller = _new_controller(policy)
    assert controller.snapshot.state is ControllerState.REFUSED
    before = policy.state.convergence_generation

    assert WatcherRetryPolicy.reconcile_rebuild(_rebuilt(tmp_path, source))
    reloaded = WatcherRetryPolicy.for_root(tmp_path, source)
    assert reloaded.state.scope_refusal is None
    assert reloaded.state.last_error_kind is None
    assert reloaded.state.circuit_state is WatcherCircuitState.CLOSED
    assert reloaded.state.convergence_generation == before + 1
    assert not reloaded.state.convergence_pending
    assert _new_controller(reloaded).snapshot.state is ControllerState.IDLE
    # Repeated completion cannot create another dirty generation.
    assert not WatcherRetryPolicy.reconcile_rebuild(_rebuilt(tmp_path, source))
    assert reloaded.refresh().convergence_generation == before + 1


@pytest.mark.parametrize(
    "state", [JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED]
)
def test_unsuccessful_rebuild_preserves_refusal(
    tmp_path: Path, state: JobState
) -> None:
    policy = _refused(tmp_path)
    before = policy.state
    # Mutation: accepting terminal states other than success clears this refusal.
    assert not WatcherRetryPolicy.reconcile_rebuild(
        replace(_rebuilt(tmp_path), state=state)
    )
    assert policy.refresh() == before


@pytest.mark.parametrize(
    ("mode", "authority"),
    [
        (JobMode.INCREMENTAL, RunAuthority.PUBLICATION),
        (JobMode.INCREMENTAL, RunAuthority.REBUILD),
        (JobMode.REBUILD, RunAuthority.PUBLICATION),
    ],
)
def test_incremental_or_unauthorized_success_cannot_clear_refusal(
    tmp_path: Path, mode: JobMode, authority: RunAuthority
) -> None:
    policy = _refused(tmp_path)
    before = policy.state
    snapshot = _rebuilt(tmp_path)
    # Mutation: removing mode/authority guards grants full authority to an increment.
    assert not WatcherRetryPolicy.reconcile_rebuild(
        replace(snapshot, spec=replace(snapshot.spec, mode=mode, authority=authority))
    )
    assert policy.refresh() == before


def test_foreign_root_and_source_success_leave_original_refusal(tmp_path: Path) -> None:
    policy = _refused(tmp_path)
    before = policy.state
    snapshot = _rebuilt(tmp_path)
    assert not WatcherRetryPolicy.reconcile_rebuild(
        replace(
            snapshot,
            spec=replace(snapshot.spec, project_root=str(tmp_path / "foreign")),
        )
    )
    assert not WatcherRetryPolicy.reconcile_rebuild(
        _rebuilt(tmp_path, WatcherSource.DOCUMENT)
    )
    assert policy.refresh() == before
    assert not (tmp_path / "foreign").exists()
    assert not policy._path.with_name("document.json").exists()


@pytest.mark.parametrize("foreign", ["root", "source"])
def test_rebuild_rejects_a_foreign_existing_policy(
    tmp_path: Path, foreign: str
) -> None:
    original = _refused(tmp_path)
    other = _refused(
        tmp_path / "foreign" if foreign == "root" else tmp_path,
        WatcherSource.DOCUMENT if foreign == "source" else WatcherSource.CODE,
    )
    before = other.state

    # Mutation: reusing foreign policy ownership grants a rebuild the wrong scope.
    assert not WatcherRetryPolicy.reconcile_rebuild(_rebuilt(tmp_path), other)
    assert other.refresh() == before
    assert original.refresh().scope_refusal is WatcherScopeRefusal.FULL_REINDEX_REQUIRED


def test_rebuild_cannot_clear_a_refusal_recorded_after_it_started(
    tmp_path: Path,
) -> None:
    policy = _refused(tmp_path)
    before = replace(policy.state, last_failure_at=12.0, updated_at=12.0)
    write_state(policy._path, before)
    # Mutation: removing the failure-time fence erases a newer refusal.
    assert not WatcherRetryPolicy.reconcile_rebuild(_rebuilt(tmp_path))
    assert policy.refresh() == before


def test_rebuild_preserves_unknown_scope_from_a_new_recovery_marker(
    tmp_path: Path,
) -> None:
    policy = _refused(tmp_path)
    previous_generation = policy.state.convergence_generation
    marker = policy.write_recovery_marker()
    assert marker.is_file()

    # A cancelled intake can hand off a newer batch without exact paths.
    assert not WatcherRetryPolicy.reconcile_rebuild(_rebuilt(tmp_path))
    recovered = policy.refresh()
    assert recovered.convergence_pending
    assert recovered.scope_refusal is WatcherScopeRefusal.FULL_REINDEX_REQUIRED
    assert recovered.last_error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
    assert recovered.convergence_generation > previous_generation
    assert not recovered.pending_paths and not recovered.captured_paths


@pytest.mark.parametrize("later_paths", [True, False])
def test_new_marker_preserves_unknown_scope_alongside_captured_paths(
    tmp_path: Path, later_paths: bool
) -> None:
    policy = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE, now=1.0)
    policy.mark_scope_pending(
        (_observation(WatcherSource.CODE, "src/captured.py"),), now=1.0
    )
    attempt = policy.admit_reserved(
        policy.reserve_admission(), job_id="watcher-active", now=2.0
    ).attempt_generation
    assert attempt is not None
    if later_paths:
        policy.mark_scope_pending(
            (_observation(WatcherSource.CODE, "src/later.py", now=12.0),), now=12.0
        )
    before = replace(
        policy.state,
        scope_refusal=WatcherScopeRefusal.FULL_REINDEX_REQUIRED,
        last_error_kind=JobErrorKind.FULL_REINDEX_REQUIRED,
        last_failure_at=3.0,
        circuit_state=WatcherCircuitState.OPEN,
    )
    write_state(policy._path, before)
    # A distinct intake owner loses additional scope, not this admitted job.
    intake = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE)
    marker = intake.write_recovery_marker()

    # Mutation: forgetting unknown intent when exact paths remain clears the marker.
    assert not WatcherRetryPolicy.reconcile_rebuild(_rebuilt(tmp_path))
    recovered = policy.refresh()
    assert not marker.exists()
    assert recovered.unscoped_required
    assert recovered.pending_paths == before.pending_paths
    assert recovered.captured_paths == before.captured_paths
    assert recovered.attempt_token == before.attempt_token

    policy.record_success(attempt, now=recovered.updated_at + 1.0)
    # Mutation: ordinary captured success must not settle unrelated unknown work.
    assert policy.state.convergence_pending
    assert policy.state.unscoped_required
    assert policy.state.scope_refusal is WatcherScopeRefusal.FULL_REINDEX_REQUIRED
    assert policy.state.last_error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
    assert policy.state.circuit_state is WatcherCircuitState.OPEN
    assert not policy.state.captured_paths
    assert policy.state.attempt_token is None
    assert policy.state.pending_paths == before.pending_paths

    observed_at = policy.state.updated_at + 1.0
    policy.mark_scope_pending(
        (_observation(WatcherSource.CODE, "src/after.py", now=observed_at),),
        now=observed_at,
    )
    # Mutation: one new exact batch cannot narrow a previously unknown batch.
    assert policy.state.unscoped_required
    assert policy.state.scope_refusal is WatcherScopeRefusal.FULL_REINDEX_REQUIRED
    assert policy.state.last_error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
    assert not policy.admit(now=observed_at + 1.0).admitted
    assert not WatcherRetryPolicy.reconcile_rebuild(_rebuilt(tmp_path))

    covered = _rebuilt(tmp_path)
    covered = replace(
        covered,
        timestamps=replace(
            covered.timestamps,
            started_at=observed_at + 2.0,
            finished_at=observed_at + 3.0,
        ),
    )
    assert WatcherRetryPolicy.reconcile_rebuild(covered)
    assert not policy.refresh().unscoped_required
    assert policy.state.scope_refusal is None
    assert policy.state.convergence_pending
    assert policy.state.pending_paths


def test_own_marker_restores_captured_paths_before_clearing_the_fence(
    tmp_path: Path,
) -> None:
    policy = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE, now=1.0)
    policy.mark_scope_pending(
        (_observation(WatcherSource.CODE, "src/captured.py"),), now=1.0
    )
    assert policy.admit_reserved(
        policy.reserve_admission(), job_id="watcher-active", now=2.0
    ).admitted
    before = policy.state
    marker = policy.write_recovery_marker()

    recovered = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE)

    # Mutation: retaining captured paths after clearing their fence corrupts state.
    assert recovered.refresh() == recovered.state
    assert recovered.state.pending_paths == before.captured_paths
    assert not recovered.state.captured_paths
    assert recovered.state.attempt_generation is None
    assert recovered.state.attempt_job_id is None
    assert recovered.state.unscoped_required
    assert recovered.state.scope_refusal is WatcherScopeRefusal.FULL_REINDEX_REQUIRED
    assert not marker.exists()


@pytest.mark.parametrize("outcome", ["interrupted", "failed", "requires-full"])
def test_other_scoped_outcomes_preserve_unrelated_unknown_marker_intent(
    tmp_path: Path, outcome: str
) -> None:
    policy = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE, now=1.0)
    policy.mark_scope_pending(
        (_observation(WatcherSource.CODE, "src/captured.py"),), now=1.0
    )
    attempt = policy.admit_reserved(
        policy.reserve_admission(), job_id="watcher-active", now=2.0
    ).attempt_generation
    assert attempt is not None
    intake = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE)
    intake.write_recovery_marker()
    observed_at = policy.refresh().updated_at

    if outcome == "interrupted":
        policy.record_interrupted(attempt, now=observed_at + 1.0)
    else:
        policy.record_failure(
            JobError(
                JobErrorKind.FULL_REINDEX_REQUIRED
                if outcome == "requires-full"
                else JobErrorKind.UNAVAILABLE,
                "scoped attempt could not publish",
            ),
            attempt,
            now=observed_at + 1.0,
            random_unit=0.0,
        )

    # Mutation: scoped cancellation/failure must not replace unknown intent.
    assert policy.state.convergence_pending
    assert policy.state.unscoped_required
    assert policy.state.scope_refusal is WatcherScopeRefusal.FULL_REINDEX_REQUIRED
    assert policy.state.last_error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
    assert policy.state.circuit_state is WatcherCircuitState.OPEN
    assert [item.relative_path for item in policy.state.pending_paths] == [
        "src/captured.py"
    ]
    assert policy.state.attempt_job_id is None
    assert not policy.admit(now=observed_at + 2.0).admitted
    covered = _rebuilt(tmp_path)
    covered = replace(
        covered,
        timestamps=replace(
            covered.timestamps,
            started_at=observed_at + 3.0,
            finished_at=observed_at + 4.0,
        ),
    )
    assert WatcherRetryPolicy.reconcile_rebuild(covered)
    assert not policy.refresh().unscoped_required
    assert policy.state.scope_refusal is None


async def test_restart_settles_rebuild_without_readopting_its_owned_dead_token(
    tmp_path: Path,
) -> None:
    manager_path = tmp_path / "manager.json"
    manager = JobManager(
        state_path=manager_path, quiesce_controller=ServiceQuiesceController()
    )
    watcher = await _complete_job(
        manager,
        JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            str(tmp_path),
            JobMode.INCREMENTAL,
            RunAuthority.PUBLICATION,
        ),
        JobInitiator("watcher", "watcher_code_index", str(tmp_path)),
    )
    abandoned = _persist_exited_owner_attempt(tmp_path, watcher.id)
    token = abandoned.attempt_token
    assert token is not None and token not in _ADMISSION_RESERVATIONS
    await _complete_job(
        manager,
        JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            str(tmp_path),
            JobMode.REBUILD,
            RunAuthority.REBUILD,
        ),
        JobInitiator("cli", "explicit rebuild", str(tmp_path)),
    )
    restored = JobManager(
        state_path=manager_path, quiesce_controller=ServiceQuiesceController()
    )
    assert restored.restore_persisted().code == "job_state_restored"
    policy = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE)
    assert policy._owned_attempt_token == token
    assert _ADMISSION_RESERVATIONS[token]
    slot = WatcherConvergenceSlot(
        JobSource.CODE, tmp_path.resolve(), ServiceRegistry(), policy
    )
    try:
        # Mutation: constructing another adopting policy here collides with this owner.
        failures: list[str] = []
        try:
            await reconcile_restarted_slot(slot, restored)
        except WatcherRetryStateError as error:
            failures.append(str(error))
        assert failures == []
        assert policy.state.scope_refusal is None
        assert policy.state.attempt_generation is None
        assert policy.state.attempt_job_id is None
        assert not policy.state.captured_paths
        assert [item.relative_path for item in policy.state.pending_paths] == [
            "src/later.py"
        ]
        assert slot.dirty_paths() == frozenset({tmp_path.resolve() / "src/later.py"})
        assert token not in _ADMISSION_RESERVATIONS
        assert policy._owned_attempt_token is None
    finally:
        if policy.state.attempt_generation is not None:
            policy.record_interrupted(policy.state.attempt_generation)


def test_off_controller_callback_never_reserves_an_abandoned_attempt(
    tmp_path: Path,
) -> None:
    abandoned = _persist_exited_owner_attempt(tmp_path, "watcher-abandoned")
    token = abandoned.attempt_token
    assert token is not None and token not in _ADMISSION_RESERVATIONS
    reservations = dict(_ADMISSION_RESERVATIONS)
    manager = JobManager(
        state_path=tmp_path / "manager.json",
        quiesce_controller=ServiceQuiesceController(),
    )
    binding = IndexJobBinding(manager, "full", ServiceRegistry(), None, None)

    _finish_index_job(
        _rebuilt(tmp_path),
        10.0,
        JobExecutionResult(summary="published"),
        None,
        binding=binding,
    )

    # Mutation: settlement loader adoption strands this token in an ephemeral policy.
    try:
        assert reservations == _ADMISSION_RESERVATIONS
        policy = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE)
        assert policy.state.scope_refusal is None
        assert policy.state.attempt_token == token
        assert policy._owned_attempt_token == token
        assert _ADMISSION_RESERVATIONS[token]
        assert policy.state.attempt_generation is not None
        policy.record_interrupted(policy.state.attempt_generation)
        assert token not in _ADMISSION_RESERVATIONS
    finally:
        _ADMISSION_RESERVATIONS.pop(token, None)


def test_rebuild_preserves_an_owned_abandoned_scoped_fence(tmp_path: Path) -> None:
    abandoned = _persist_exited_owner_attempt(tmp_path, "watcher-abandoned")
    policy = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE)
    token = abandoned.attempt_token
    assert token is not None
    try:
        assert WatcherRetryPolicy.reconcile_rebuild(_rebuilt(tmp_path), policy)
        # Mutation: treating a fenced job as legacy abandons its exact captured scope.
        assert policy.state.attempt_generation == abandoned.attempt_generation
        assert policy.state.attempt_job_id == abandoned.attempt_job_id
        assert policy.state.attempt_token == token
        assert policy.state.captured_paths == abandoned.captured_paths
        assert _ADMISSION_RESERVATIONS[token]
        assert policy.state.attempt_generation is not None
        policy.record_interrupted(policy.state.attempt_generation)
    finally:
        _ADMISSION_RESERVATIONS.pop(token, None)


@pytest.mark.parametrize("settlement", ["callback", "restart"])
@pytest.mark.parametrize("exact_paths", [True, False])
async def test_covering_rebuild_clears_a_dead_legacy_fence_without_restamping(
    tmp_path: Path, settlement: str, exact_paths: bool
) -> None:
    abandoned = _persist_exited_owner_attempt(tmp_path, None, exact_paths=exact_paths)
    assert abandoned.attempt_generation is not None
    manager_path = tmp_path / "manager.json"
    manager = JobManager(
        state_path=manager_path, quiesce_controller=ServiceQuiesceController()
    )
    rebuilt = await _complete_job(
        manager,
        JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            str(tmp_path),
            JobMode.REBUILD,
            RunAuthority.REBUILD,
        ),
        JobInitiator("cli", "explicit rebuild", str(tmp_path)),
    )
    if settlement == "callback":
        binding = IndexJobBinding(manager, rebuilt.id, ServiceRegistry(), None, None)
        _finish_index_job(
            rebuilt,
            1.0,
            JobExecutionResult(summary="published"),
            None,
            binding=binding,
        )
    policy = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE)
    if settlement == "restart":
        # Mutation: restamping an existing terminal refusal blocks older job truth.
        assert policy.state.last_failure_at == abandoned.last_failure_at
        assert policy.state.updated_at == abandoned.updated_at
        restored = JobManager(
            state_path=manager_path, quiesce_controller=ServiceQuiesceController()
        )
        assert restored.restore_persisted().code == "job_state_restored"
        slot = WatcherConvergenceSlot(
            JobSource.CODE, tmp_path.resolve(), ServiceRegistry(), policy
        )
        await reconcile_restarted_slot(slot, restored)

    # Mutation: preserving a covered dead legacy claim recreates refusal at reload.
    assert policy.state.attempt_generation is None
    assert policy.state.attempt_token is None
    assert policy.state.scope_refusal is None
    assert policy.state.last_error_kind is None
    assert policy.state.pending_paths == abandoned.pending_paths
    reloaded = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE)
    assert reloaded.state.scope_refusal is None
    assert reloaded.state.last_error_kind is None
    assert reloaded.state.convergence_pending is bool(abandoned.pending_paths)


@pytest.mark.parametrize("fence", ["live-owner", "newer-start", "newer-unknown"])
def test_rebuild_preserves_uncovered_legacy_attempt_fences(
    tmp_path: Path, fence: str
) -> None:
    if fence == "live-owner":
        policy = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE, now=1.0)
        policy.mark_scope_pending(
            (_observation(WatcherSource.CODE, "src/before.py"),), now=1.0
        )
        assert policy.admit(now=2.0).admitted
        before = replace(
            policy.state,
            scope_refusal=WatcherScopeRefusal.FULL_REINDEX_REQUIRED,
            last_error_kind=JobErrorKind.FULL_REINDEX_REQUIRED,
            last_failure_at=3.0,
            circuit_state=WatcherCircuitState.OPEN,
        )
        write_state(policy._path, before)
    else:
        before = _persist_exited_owner_attempt(tmp_path, None)
        policy = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE)
        before = replace(
            before,
            attempt_started_at=(12.0 if fence == "newer-start" else 2.0),
            unscoped_required=fence == "newer-unknown",
            updated_at=12.0,
        )
        write_state(policy._path, before)
    try:
        settled = WatcherRetryPolicy.reconcile_rebuild(_rebuilt(tmp_path))
        assert settled is (fence != "newer-unknown")
        after = policy.refresh()
        # Mutation: releasing live or newer claims loses their execution fence.
        assert after.attempt_generation == before.attempt_generation
        assert after.attempt_token == before.attempt_token
        assert after.attempt_started_at == before.attempt_started_at
        assert after.attempt_owner_pid == before.attempt_owner_pid
        assert after.attempt_owner_create_time == before.attempt_owner_create_time
        assert after.pending_paths == before.pending_paths
    finally:
        if fence == "live-owner" and policy.state.attempt_generation is not None:
            policy.record_interrupted(policy.state.attempt_generation)


@pytest.mark.parametrize("unscoped_required", [True, False])
@pytest.mark.parametrize("observed_at", [5.0, 12.0])
def test_rebuild_fences_unknown_pending_scope_by_its_observation_time(
    tmp_path: Path, unscoped_required: bool, observed_at: float
) -> None:
    policy = _refused(tmp_path)
    before = replace(
        policy.state,
        convergence_pending=True,
        unscoped_required=unscoped_required,
        updated_at=observed_at,
    )
    write_state(policy._path, before)

    settled = WatcherRetryPolicy.reconcile_rebuild(_rebuilt(tmp_path))

    assert settled is (observed_at <= 10.0)
    after = policy.refresh()
    if observed_at > 10.0:
        assert after.convergence_pending
        assert after.unscoped_required is unscoped_required
        assert after.scope_refusal is WatcherScopeRefusal.FULL_REINDEX_REQUIRED
        assert after.last_failure_at == before.last_failure_at
        assert after.updated_at == before.updated_at
    else:
        assert not after.convergence_pending
        assert not after.unscoped_required
        assert after.scope_refusal is None


@pytest.mark.parametrize("later_paths", [True, False])
def test_rebuild_preserves_new_pending_paths_and_captured_attempt_fence(
    tmp_path: Path, later_paths: bool
) -> None:
    policy = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE, now=1.0)
    policy.mark_scope_pending(
        (_observation(WatcherSource.CODE, "src/captured.py"),), now=1.0
    )
    admitted = policy.admit_reserved(
        policy.reserve_admission(), job_id="watcher-active", now=2.0
    )
    assert admitted.admitted
    if later_paths:
        policy.mark_scope_pending(
            (_observation(WatcherSource.CODE, "src/later.py", now=12.0),), now=12.0
        )
    before = replace(
        policy.state,
        scope_refusal=WatcherScopeRefusal.FULL_REINDEX_REQUIRED,
        last_error_kind=JobErrorKind.FULL_REINDEX_REQUIRED,
        last_failure_at=3.0,
        circuit_state=WatcherCircuitState.OPEN,
    )
    write_state(policy._path, before)

    assert WatcherRetryPolicy.reconcile_rebuild(_rebuilt(tmp_path))
    after = policy.refresh()
    # Mutation: consuming paths or clearing ownership loses the later batch.
    assert after.pending_paths == before.pending_paths
    assert after.captured_paths == before.captured_paths
    assert after.attempt_generation == before.attempt_generation
    assert after.attempt_job_id == before.attempt_job_id
    assert after.attempt_token == before.attempt_token
    assert after.attempt_started_at == before.attempt_started_at
    assert after.attempt_owner_pid == before.attempt_owner_pid
    assert after.attempt_owner_create_time == before.attempt_owner_create_time
    assert after.convergence_pending
    assert not policy.admit(now=21.0).admitted
    assert admitted.attempt_generation is not None
    policy.record_success(admitted.attempt_generation, now=22.0)
    assert [item.relative_path for item in policy.state.pending_paths] == (
        ["src/later.py"] if later_paths else []
    )
    assert policy.state.convergence_pending is later_paths


@pytest.mark.parametrize(
    "refusal",
    [
        WatcherScopeRefusal.SCOPE_STATE_INVALID,
        WatcherScopeRefusal.SCOPE_CAPACITY_EXCEEDED,
    ],
)
def test_rebuild_does_not_clear_other_scope_refusals(
    tmp_path: Path, refusal: WatcherScopeRefusal
) -> None:
    policy = _refused(tmp_path)
    before = replace(policy.state, scope_refusal=refusal)
    write_state(policy._path, before)
    assert not WatcherRetryPolicy.reconcile_rebuild(_rebuilt(tmp_path))
    assert policy.refresh() == before


@pytest.mark.parametrize("malformation", ["corrupt", "foreign-root", "foreign-source"])
def test_rebuild_does_not_rewrite_invalid_durable_state(
    tmp_path: Path, malformation: str
) -> None:
    policy = _refused(tmp_path)
    raw = json.loads(policy._path.read_text(encoding="utf-8"))
    if malformation == "foreign-root":
        raw["canonical_root"] = str(tmp_path / "foreign")
    elif malformation == "foreign-source":
        raw["source"] = WatcherSource.DOCUMENT.value
    text = "corrupt" if malformation == "corrupt" else json.dumps(raw)
    policy._path.write_text(text, encoding="utf-8")

    with pytest.raises(WatcherRetryStateError):
        WatcherRetryPolicy.reconcile_rebuild(_rebuilt(tmp_path))
    assert policy._path.read_text(encoding="utf-8") == text


@pytest.mark.parametrize("result", [None, ""])
def test_unknown_publication_result_cannot_clear_refusal(
    tmp_path: Path, result: str | None
) -> None:
    policy = _refused(tmp_path)
    before = policy.state
    assert not WatcherRetryPolicy.reconcile_rebuild(
        replace(_rebuilt(tmp_path), result=result)
    )
    assert policy.refresh() == before


@pytest.mark.parametrize("source", tuple(WatcherSource))
@pytest.mark.parametrize(
    "history",
    [
        "matching",
        "foreign-root",
        "foreign-source",
        "incremental",
        "failed",
        "newer-refusal",
    ],
)
async def test_restart_reconciles_success_persisted_before_settlement(
    tmp_path: Path, source: WatcherSource, history: str
) -> None:
    policy = _refused(tmp_path, source)
    manager_path = tmp_path / "manager.json"
    manager = JobManager(
        state_path=manager_path,
        quiesce_controller=ServiceQuiesceController(),
    )
    history_source = (
        (WatcherSource.DOCUMENT if source is WatcherSource.CODE else WatcherSource.CODE)
        if history == "foreign-source"
        else source
    )
    history_root = tmp_path / "foreign" if history == "foreign-root" else tmp_path
    history_mode = JobMode.INCREMENTAL if history == "incremental" else JobMode.REBUILD
    history_authority = (
        RunAuthority.PUBLICATION if history == "incremental" else RunAuthority.REBUILD
    )
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource(history_source.value),
            str(history_root),
            history_mode,
            history_authority,
        ),
        JobInitiator("cli", "explicit rebuild", str(history_root)),
    )
    assert created.job is not None
    finished = asyncio.Event()

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        if history == "failed":
            raise RuntimeError("full publication failed")
        context.set_resilience(
            IndexResilienceSnapshot(
                generation_id=_certified_generation(history_root, history_source),
                terminal_outcome="succeeded",
                checkpoint_compatible=True,
            )
        )
        return JobExecutionResult(summary="full publication completed")

    def on_finished(
        _snapshot: JobSnapshot,
        _duration: float,
        _result: JobExecutionResult | None,
        _error: BaseException | None,
    ) -> None:
        # The process can die after job success is durable but before retry settlement.
        finished.set()

    assert manager.bind_dispatch(created.job.id, runner, on_finished=on_finished).job
    assert (await manager.dispatch_async(created.job.id)).job
    joined = await manager.wait_for_attempt(created.job.id, timeout_seconds=30.0)
    assert joined.code == "attempt_released", joined
    assert finished.is_set(), joined
    assert policy.refresh().scope_refusal is WatcherScopeRefusal.FULL_REINDEX_REQUIRED
    if history == "newer-refusal":
        completed = manager.get(created.job.id)
        assert completed is not None and completed.timestamps.finished_at is not None
        newer = completed.timestamps.finished_at + 0.01
        write_state(
            policy._path,
            replace(policy.state, last_failure_at=newer, updated_at=newer),
        )

    restored = JobManager(
        state_path=manager_path,
        quiesce_controller=ServiceQuiesceController(),
    )
    assert restored.restore_persisted().code == "job_state_restored"
    restarted_policy = WatcherRetryPolicy.for_root(tmp_path, source)
    slot = WatcherConvergenceSlot(
        JobSource(source.value), tmp_path.resolve(), ServiceRegistry(), restarted_policy
    )

    # Mutation: omitting historical rebuild reconciliation leaves a permanent refusal.
    await reconcile_restarted_slot(slot, restored)

    if history == "matching":
        assert restarted_policy.state.scope_refusal is None
        assert restarted_policy.state.last_error_kind is None
    else:
        assert (
            restarted_policy.state.scope_refusal
            is WatcherScopeRefusal.FULL_REINDEX_REQUIRED
        )
        assert (
            restarted_policy.state.last_error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
        )
    assert not restarted_policy.state.convergence_pending
    assert not slot.has_work()


def test_canonical_binding_owns_settlement_after_manager_restart(
    tmp_path: Path,
) -> None:
    policy = _refused(tmp_path)
    state_path = tmp_path / "manager.json"
    quiesce = ServiceQuiesceController()
    manager = JobManager(state_path=state_path, quiesce_controller=quiesce)
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            str(tmp_path),
            JobMode.REBUILD,
            RunAuthority.REBUILD,
        ),
        JobInitiator("cli", "explicit rebuild", str(tmp_path)),
        start_paused=True,
    )
    assert created.job is not None
    restored = JobManager(state_path=state_path, quiesce_controller=quiesce)
    assert restored.restore_persisted().code == "job_state_restored"
    callbacks: list[JobSnapshot] = []

    def finished(
        snapshot: JobSnapshot,
        _duration: float,
        _result: JobExecutionResult | None,
        _error: BaseException | None,
    ) -> None:
        callbacks.append(snapshot)

    binding = IndexJobBinding(
        restored, created.job.id, ServiceRegistry(), None, None, on_finished=finished
    )
    assert bind_index_job(binding).job is not None
    # The restored canonical production binding carries the same completion owner.
    dispatch = restored._dispatchers[created.job.id]
    assert dispatch is not None and dispatch.on_finished is not None
    dispatch.on_finished(
        replace(_rebuilt(tmp_path), id=created.job.id),
        10.0,
        JobExecutionResult(summary="published"),
        None,
    )

    assert policy.refresh().scope_refusal is None
    assert len(callbacks) == 1


async def test_completion_callback_runs_after_real_manager_persists_success(
    tmp_path: Path,
) -> None:
    policy = _refused(tmp_path)
    manager = JobManager(
        state_path=tmp_path / "manager.json",
        quiesce_controller=ServiceQuiesceController(),
    )
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            str(tmp_path),
            JobMode.REBUILD,
            RunAuthority.REBUILD,
        ),
        JobInitiator("cli", "explicit rebuild", str(tmp_path)),
    )
    assert created.job is not None
    finished = asyncio.Event()
    verified: list[JobState] = []

    def on_finished(
        snapshot: JobSnapshot,
        _duration: float,
        _result: JobExecutionResult | None,
        _error: BaseException | None,
    ) -> None:
        persisted_manager = JobManager(
            state_path=tmp_path / "manager.json",
            quiesce_controller=ServiceQuiesceController(),
        )
        assert persisted_manager.restore_persisted().code == "job_state_restored"
        persisted = persisted_manager.get(snapshot.id)
        assert persisted is not None
        verified.append(persisted.state)
        finished.set()

    binding = IndexJobBinding(
        manager, created.job.id, ServiceRegistry(), None, None, on_finished=on_finished
    )

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        context.set_resilience(
            IndexResilienceSnapshot(
                generation_id=_certified_generation(tmp_path, WatcherSource.CODE),
                terminal_outcome="succeeded",
                checkpoint_compatible=True,
            )
        )
        return JobExecutionResult(summary="publication complete")

    assert (
        manager.bind_dispatch(
            created.job.id,
            runner,
            on_finished=partial(_finish_index_job, binding=binding),
        ).job
        is not None
    )
    assert (await manager.dispatch_async(created.job.id)).job is not None
    joined = await manager.wait_for_attempt(created.job.id, timeout_seconds=30.0)
    assert joined.code == "attempt_released", joined
    assert finished.is_set(), joined

    assert verified == [JobState.SUCCEEDED]
    assert policy.refresh().scope_refusal is None


async def test_live_controller_reconciles_the_settled_refusal(tmp_path: Path) -> None:
    policy = _refused(tmp_path)
    registry = ServiceRegistry()
    slot = WatcherConvergenceSlot(JobSource.CODE, tmp_path.resolve(), registry, policy)
    controller = _new_controller(policy)
    _register_controller_binding(_ControllerBinding(controller, slot, policy))
    scheduler = _watcher._watcher_scheduler
    assert scheduler is not None
    initial_state = controller.snapshot.state
    assert initial_state is ControllerState.REFUSED
    try:
        assert WatcherRetryPolicy.reconcile_rebuild(_rebuilt(tmp_path))
        _watcher._wake_watcher_scheduler()
        async with asyncio.timeout(30.0):
            while controller.snapshot.state is not ControllerState.CONVERGED:
                await asyncio.sleep(0.01)
        assert controller.snapshot.state is ControllerState.CONVERGED
        assert controller.snapshot.remediation is None
    finally:
        scheduler.unregister_root(tmp_path)
        assert await _watcher._wait_for_watcher_scheduler_release(
            tmp_path, asyncio.get_running_loop().time() + 30.0
        )


async def test_scheduler_detach_joins_normalized_root_callback(tmp_path: Path) -> None:
    policy = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE)
    controller = _new_controller(policy)
    assert controller.snapshot.canonical_root == os.path.normcase(
        str(tmp_path.resolve())
    )
    scheduler = _WatcherScheduler(
        reevaluation_seconds=5.0, monotonic=asyncio.get_running_loop().time
    )
    entered = asyncio.Event()
    release = asyncio.Event()

    async def reevaluate() -> None:
        entered.set()
        await release.wait()

    scheduler.register(controller, reevaluate=reevaluate, admit=lambda _selection: None)
    cycle = asyncio.create_task(scheduler._run_cycle())
    await entered.wait()
    scheduler.unregister_root(tmp_path)
    # Mutation: comparing mixed-case paths to canonical keys leaves this owner live.
    assert scheduler.empty
    joined = asyncio.create_task(
        scheduler.wait_root_released(
            tmp_path, deadline=asyncio.get_running_loop().time() + 5.0
        )
    )
    await asyncio.sleep(0)
    # Mutation: missing normalization reports release while the callback runs.
    assert not joined.done()
    release.set()
    assert await joined
    await cycle
