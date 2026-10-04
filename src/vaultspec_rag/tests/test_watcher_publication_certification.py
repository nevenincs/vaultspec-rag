"""Job success settles watcher refusal only with exact durable publication."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from .._job_errors import JobError, JobErrorKind
from .._publication_state import acquire_publication_snapshot
from .._source_types import PublicSourceType
from ..indexer._content_policy import AdmissionDisposition, AdmissionReason, ContentKind
from ..indexer._document_checkpoint import DocumentRunCheckpoint
from ..indexer._file_state import FileState, FileStateKind
from ..indexer._publication_proof import ProofProvenance
from ..indexer._run_checkpoint import CodeRunCheckpoint
from ..indexer._run_ledger_models import (
    FinalizationPhase,
    RunAuthority,
    RunOperation,
    RunTerminalState,
)
from ..indexer._run_policy import RunPolicy
from ..indexer._vault_checkpoint import VaultRunCheckpoint
from ..job_dispatch import (
    IndexJobBinding,
    _checkpoint_resilience,
    bind_index_job,
)
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
from ..service import ServiceRegistry
from ..service_quiesce import ServiceQuiesceController
from ..watcher_retry import (
    WatcherCircuitState,
    WatcherScopeRefusal,
    WatcherSource,
    write_state,
)
from ..watcher_retry_policy import _ADMISSION_RESERVATIONS, WatcherRetryPolicy
from ..watcher_runtime import (
    WatcherConvergenceSlot,
    reconcile_completed_rebuild,
    reconcile_restarted_slot,
)
from ._run_ledger_test_support import (
    ledger_test_digest,
    ledger_test_publish_and_compact,
)
from ._watcher_fixtures import dirty_paths
from .test_watcher_rebuild_reconciliation import _published_rebuild, _refused_policy
from .test_watcher_rebuild_settlement import _persist_exited_owner_attempt
from .test_watcher_retry import _path_observation

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ..embeddings import EmbeddingModel
    from ..indexer._checkpoint_common import RunCheckpointBase
    from ..indexer._run_ledger_models import RunSignature
    from ..indexer._run_ledger_runtime import RunLedger
    from ..job_manager.models import JobAttemptContext
    from ..job_models import JobSnapshot
    from ..store_runtime import VaultStore
    from ..watcher_retry import WatcherRetryState

pytestmark = pytest.mark.unit


def _new_checkpoint(
    root: Path,
    source: WatcherSource,
    *,
    operation: RunOperation = RunOperation.FULL,
) -> RunCheckpointBase:
    published = acquire_publication_snapshot(root, PublicSourceType(source.value))
    ledger = published.ledger
    signature = replace(
        ledger.generation(published.proof.generation_id).signature, operation=operation
    )
    generation = ledger.start_generation(signature)
    checkpoint_type = {
        WatcherSource.CODE: CodeRunCheckpoint,
        WatcherSource.DOCUMENT: DocumentRunCheckpoint,
        WatcherSource.VAULT: VaultRunCheckpoint,
    }[source]
    return checkpoint_type(
        ledger,
        generation,
        None,
        RunPolicy(no_progress_timeout_seconds=30),
        (
            RunAuthority.REBUILD
            if operation is RunOperation.FULL
            else RunAuthority.PUBLICATION
        ),
        None,
    )


def _contradict_generation_signature(
    signature: RunSignature, failure: str, root: Path
) -> RunSignature:
    if failure == "incremental-owner":
        return replace(signature, operation=RunOperation.INCREMENTAL)
    if failure == "foreign-owner-root":
        return replace(signature, root_identity=str(root / "other"))
    if failure == "foreign-owner-source":
        return replace(signature, source_type=PublicSourceType.DOCUMENT)
    if failure == "foreign-owner-backend":
        return replace(signature, backend_identity="other-backend")
    assert failure == "foreign-owner-collection"
    return replace(signature, collection_identity="other-collection")


def _contradict_persisted_publication(
    ledger: RunLedger, generation_id: str, failure: str, root: Path
) -> None:
    """Persist typed contradictions without fabricating ledger responses."""
    with sqlite3.connect(ledger.path) as connection:
        if failure == "unpublished-phase":
            connection.execute(
                "UPDATE generations SET finalization_phase = ? WHERE generation_id = ?",
                (FinalizationPhase.INGESTING.value, generation_id),
            )
        elif failure == "incremental-owner" or failure.startswith("foreign-owner-"):
            signature = _contradict_generation_signature(
                ledger.generation(generation_id).signature, failure, root
            )
            connection.execute(
                "UPDATE generations SET signature_json = ?, "
                "signature_fingerprint = ? WHERE generation_id = ?",
                (signature.canonical_json, signature.fingerprint, generation_id),
            )
        else:
            assert failure == "unverified-proof"
            connection.execute(
                "UPDATE publication_proofs SET provenance = ?, verified_at = NULL "
                "WHERE generation_id = ?",
                (ProofProvenance.DELTA_DERIVED.value, generation_id),
            )
        connection.commit()


@pytest.mark.parametrize(
    "failure",
    [
        "missing-resilience",
        "missing-generation",
        "unknown-generation",
        "foreign-generation",
        "superseded-generation",
        "failed-attempt-outcome",
        "missing-proof",
        "failed-generation",
        "unpublished-generation",
        "unpublished-phase",
        "incremental-owner",
        "foreign-owner-root",
        "foreign-owner-source",
        "foreign-owner-backend",
        "foreign-owner-collection",
        "unverified-proof",
    ],
)
def test_uncertified_job_success_preserves_the_refusal(
    tmp_path: Path, failure: str
) -> None:
    policy = _refused_policy(tmp_path)
    before = policy.state
    snapshot = _published_rebuild(tmp_path)
    assert snapshot.resilience is not None
    published = acquire_publication_snapshot(tmp_path, PublicSourceType.CODE)
    ledger = published.ledger
    generation_id = published.proof.generation_id
    resilience = snapshot.resilience
    if failure == "missing-resilience":
        snapshot = replace(snapshot, resilience=None)
    elif failure == "missing-generation":
        snapshot = replace(snapshot, resilience=replace(resilience, generation_id=None))
    elif failure == "unknown-generation":
        snapshot = replace(
            snapshot, resilience=replace(resilience, generation_id="gone")
        )
    elif failure == "failed-attempt-outcome":
        # A later resume of this generation cannot certify this failed job attempt.
        snapshot = replace(
            snapshot, resilience=replace(resilience, terminal_outcome="failed")
        )
    elif failure == "missing-proof":
        ledger.clear_publication_source(
            PublicSourceType.CODE,
            published.proof.compatibility_key.root_identity,
            published.proof.compatibility_key.backend_identity,
        )
    elif failure in {
        "foreign-generation",
        "superseded-generation",
        "failed-generation",
        "unpublished-generation",
    }:
        checkpoint = _new_checkpoint(tmp_path, WatcherSource.CODE)
        generation_id = checkpoint.generation_id
        if failure != "foreign-generation":
            ledger.establish_verified_publication(
                generation_id, RunAuthority.REBUILD, ()
            )
        if failure in {"failed-generation", "superseded-generation"}:
            for phase in (
                FinalizationPhase.STALE_RECONCILED,
                FinalizationPhase.METADATA_PUBLISHED,
                FinalizationPhase.GENERATION_PUBLISHED,
            ):
                ledger.advance_finalization(generation_id, phase)
            ledger.finish_generation(
                generation_id,
                RunTerminalState.FAILED
                if failure == "failed-generation"
                else RunTerminalState.SUCCEEDED,
                detail="publication failed after committing proof",
            )
        if failure != "superseded-generation":
            snapshot = replace(
                snapshot, resilience=replace(resilience, generation_id=generation_id)
            )
    else:
        # Typed but contradictory persisted rows must not certify a full run.
        _contradict_persisted_publication(ledger, generation_id, failure, tmp_path)

    # Mutation: accepting job success alone erases one of these unsafe refusals.
    snapshot = replace(
        snapshot, timestamps=replace(snapshot.timestamps, finished_at=time.time())
    )
    assert not policy.reconcile_rebuild(snapshot)
    assert policy.refresh() == before


@pytest.mark.parametrize("result", [None, "", " "])
def test_missing_publication_result_preserves_refusal(
    tmp_path: Path, result: str | None
) -> None:
    policy = _refused_policy(tmp_path)
    snapshot = replace(_published_rebuild(tmp_path), result=result)
    before = policy.state

    # Mutation: an unknown terminal result cannot certify publication success.
    assert not policy.reconcile_rebuild(snapshot)
    assert policy.refresh() == before


@pytest.mark.parametrize("settlement", ["callback", "history"])
async def test_document_extraction_failure_cannot_settle_from_legacy_job_success(
    tmp_path: Path, settlement: str
) -> None:
    policy = _refused_policy(tmp_path, WatcherSource.DOCUMENT)
    _published_rebuild(tmp_path, WatcherSource.DOCUMENT)
    checkpoint = _new_checkpoint(tmp_path, WatcherSource.DOCUMENT)
    assert isinstance(checkpoint, DocumentRunCheckpoint)
    checkpoint.ledger.record_file_state(
        checkpoint.generation_id,
        FileState.failed(
            "guide.pdf",
            FileStateKind.EXTRACT_RETRYABLE,
            ContentKind.DOCUMENT,
            "extractor could not read document",
            content_hash=ledger_test_digest("pdf"),
        ),
    )
    checkpoint.mark_failed("document_extraction_failed: guide.pdf")
    assert (
        checkpoint.ledger.generation(checkpoint.generation_id).terminal_state
        is RunTerminalState.FAILED
    )
    manager_path = tmp_path / "manager.json"
    manager = JobManager(
        state_path=manager_path, quiesce_controller=ServiceQuiesceController()
    )
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.DOCUMENT,
            str(tmp_path),
            JobMode.REBUILD,
            RunAuthority.REBUILD,
        ),
        JobInitiator("cli", "explicit rebuild", str(tmp_path)),
    )
    assert created.job is not None
    finished = asyncio.Event()
    before = policy.state

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        context.set_resilience(
            _checkpoint_resilience(
                checkpoint,
                IndexResilienceSnapshot(),
                peak_rss_mib=None,
                peak_cuda_allocated_mib=None,
                peak_cuda_reserved_mib=None,
            )
        )
        # This reproduces persisted job truth from the previous dispatcher.
        return JobExecutionResult(
            summary="+0 /0 -0", preprocess_failures=("guide.pdf",)
        )

    def on_finished(
        snapshot: JobSnapshot,
        _duration: float,
        _result: JobExecutionResult | None,
        _error: BaseException | None,
    ) -> None:
        if settlement == "callback":
            reconcile_completed_rebuild(snapshot)
        finished.set()

    assert manager.bind_dispatch(created.job.id, runner, on_finished=on_finished).job
    assert (await manager.dispatch_async(created.job.id)).job
    joined = await manager.wait_for_attempt(created.job.id, timeout_seconds=30.0)
    assert joined.code == "attempt_released", joined
    assert finished.is_set(), joined
    persisted = manager.get(created.job.id)
    assert persisted is not None and persisted.state is JobState.SUCCEEDED
    assert persisted.resilience is not None
    assert persisted.resilience.terminal_outcome == "failed"
    if settlement == "history":
        restored = JobManager(
            state_path=manager_path, quiesce_controller=ServiceQuiesceController()
        )
        assert restored.restore_persisted().code == "job_state_restored"
        restarted = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.DOCUMENT)
        await reconcile_restarted_slot(
            WatcherConvergenceSlot(
                JobSource.DOCUMENT, tmp_path.resolve(), ServiceRegistry(), restarted
            ),
            restored,
        )

    assert policy.refresh() == before
    assert policy.state.scope_refusal is WatcherScopeRefusal.FULL_REINDEX_REQUIRED


async def _persist_historical_incremental_job(
    root: Path,
    source: WatcherSource,
    outcome: RunTerminalState | None,
    *,
    failed_job: bool = False,
    missing_terminal_outcome: bool = False,
) -> tuple[JobManager, str]:
    _published_rebuild(root, source)
    checkpoint = _new_checkpoint(root, source, operation=RunOperation.INCREMENTAL)
    if outcome is not None and outcome is not RunTerminalState.RUNNING:
        checkpoint.ledger.finish_generation(
            checkpoint.generation_id,
            outcome,
            detail="historical source attempt did not publish",
        )
    manager_path = root / "manager.json"
    manager = JobManager(
        state_path=manager_path, quiesce_controller=ServiceQuiesceController()
    )
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource(source.value),
            str(root),
            JobMode.INCREMENTAL,
            RunAuthority.PUBLICATION,
        ),
        JobInitiator("watcher", f"watcher_{source.value}_index", str(root)),
    )
    assert created.job is not None
    finished = asyncio.Event()

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        if outcome is not None:
            resilience = _checkpoint_resilience(
                checkpoint,
                IndexResilienceSnapshot(),
                peak_rss_mib=None,
                peak_cuda_allocated_mib=None,
                peak_cuda_reserved_mib=None,
            )
            context.set_resilience(
                replace(resilience, terminal_outcome=None)
                if missing_terminal_outcome
                else resilience
            )
        if failed_job:
            raise JobError(
                JobErrorKind.FULL_REINDEX_REQUIRED,
                "source generation did not publish",
            )
        return JobExecutionResult(summary="legacy indexing returned")

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
    persisted = manager.get(created.job.id)
    assert persisted is not None
    assert persisted.state is (JobState.FAILED if failed_job else JobState.SUCCEEDED)
    if failed_job:
        assert persisted.error_kind == JobErrorKind.FULL_REINDEX_REQUIRED.value
    restored = JobManager(
        state_path=manager_path, quiesce_controller=ServiceQuiesceController()
    )
    assert restored.restore_persisted().code == "job_state_restored"
    return restored, persisted.id


def _unrefused_dead_source_attempt(
    root: Path, source: WatcherSource, job_id: str, *, recover_attempt: bool = True
) -> tuple[WatcherRetryState, WatcherRetryPolicy]:
    before = _persist_exited_owner_attempt(root, source, job_id)
    unowned = WatcherRetryPolicy.for_root(root, source, recover_abandoned_attempt=False)
    before = replace(
        before,
        scope_refusal=None,
        last_error_kind=None,
        last_error_detail=None,
        last_failure_at=None,
        consecutive_failures=0,
        next_retry_at=0.0,
        circuit_state=WatcherCircuitState.CLOSED,
    )
    write_state(unowned._path, before)
    return before, WatcherRetryPolicy.for_root(
        root, source, recover_abandoned_attempt=recover_attempt
    )


@pytest.mark.parametrize("source", [WatcherSource.DOCUMENT, WatcherSource.VAULT])
@pytest.mark.parametrize(
    ("outcome", "missing_terminal_outcome"),
    [
        *[
            pytest.param(state, False, id=state.value)
            for state in RunTerminalState
            if state is not RunTerminalState.SUCCEEDED
        ],
        pytest.param(None, False, id="missing-resilience"),
        pytest.param(RunTerminalState.FAILED, True, id="missing-terminal"),
    ],
)
async def test_restart_refuses_a_historical_unpublished_source_success(
    tmp_path: Path,
    source: WatcherSource,
    outcome: RunTerminalState | None,
    missing_terminal_outcome: bool,
) -> None:
    restored, job_id = await _persist_historical_incremental_job(
        tmp_path, source, outcome, missing_terminal_outcome=missing_terminal_outcome
    )
    before, policy = _unrefused_dead_source_attempt(tmp_path, source, job_id)
    token = before.attempt_token
    assert token is not None
    slot = WatcherConvergenceSlot(
        JobSource(source.value), tmp_path.resolve(), ServiceRegistry(), policy
    )
    try:
        await reconcile_restarted_slot(slot, restored)
        # Mutation: job success cannot consume an explicitly unpublished source run.
        assert policy.state.last_error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
        assert policy.state.scope_refusal is WatcherScopeRefusal.FULL_REINDEX_REQUIRED
        assert policy.state.circuit_state is WatcherCircuitState.OPEN
        # Mutation: typed refusal must restore captured scope and retain newer paths.
        assert [item.relative_path for item in policy.state.pending_paths] == [
            "src/captured.py",
            "src/later.py",
        ]
        assert policy.state.convergence_pending
        assert not policy.state.captured_paths
        assert policy.state.attempt_generation is None
        assert policy.state.attempt_job_id is None
        assert policy.state.attempt_token is None
        assert token not in _ADMISSION_RESERVATIONS
        assert dirty_paths(slot) == frozenset(
            {
                tmp_path.resolve() / "src/captured.py",
                tmp_path.resolve() / "src/later.py",
            }
        )
        assert not policy.admit().admitted
    finally:
        if policy.state.attempt_generation is not None:
            policy.record_interrupted(policy.state.attempt_generation)


@pytest.mark.parametrize("outcome", [None, RunTerminalState.FAILED])
async def test_restart_accepts_code_noop_with_previous_failed_or_absent_projection(
    tmp_path: Path, outcome: RunTerminalState | None
) -> None:
    restored, job_id = await _persist_historical_incremental_job(
        tmp_path, WatcherSource.CODE, outcome
    )
    before, policy = _unrefused_dead_source_attempt(
        tmp_path, WatcherSource.CODE, job_id
    )
    token = before.attempt_token
    assert token is not None
    try:
        await reconcile_restarted_slot(
            WatcherConvergenceSlot(
                JobSource.CODE, tmp_path.resolve(), ServiceRegistry(), policy
            ),
            restored,
        )
        # Mutation: requiring a fresh owner rejects validated unchanged code.
        assert policy.state.last_error_kind is None
        assert policy.state.scope_refusal is None
        assert [item.relative_path for item in policy.state.pending_paths] == [
            "src/later.py"
        ]
        assert not policy.state.captured_paths
        assert policy.state.attempt_generation is None
        assert token not in _ADMISSION_RESERVATIONS
    finally:
        if policy.state.attempt_generation is not None:
            policy.record_interrupted(policy.state.attempt_generation)


def _install_cpu_source_result(
    root: Path,
    source: WatcherSource,
    mode: JobMode,
    outcome: RunTerminalState | None,
    monkeypatch: pytest.MonkeyPatch,
) -> ServiceRegistry:
    """Stage contradictory source returns at the real dispatch boundary.

    Corrected source pipelines cannot deliberately return normally after a
    failed checkpoint, omit an always-required owner, or reuse a previous
    owner on demand. The two source entry points stage those adversarial
    returns while creating real checkpoints that the actual observer sees.
    Two admission replacements retain real policy validation but avoid GPU
    admission for deliberately unloaded CPU fixtures; the registry lease
    supplies that same actual source indexer without loading a model.
    Checkpoints, ledger publication, the observer, JobManager, binding,
    dispatch, typed rejection, and callback settlement all remain real.
    """
    from .. import _job_admission
    from ..indexer import CodebaseIndexer, DocumentIndexer, IndexResult, VaultIndexer

    indexer = {
        WatcherSource.CODE: CodebaseIndexer,
        WatcherSource.DOCUMENT: DocumentIndexer,
        WatcherSource.VAULT: VaultIndexer,
    }[source](root, cast("EmbeddingModel", None), cast("VaultStore", None))

    def returned_source_result(*_args: object, **_kwargs: object) -> IndexResult:
        if outcome is not None:
            checkpoint = _new_checkpoint(
                root,
                source,
                operation=(
                    RunOperation.FULL
                    if mode is JobMode.REBUILD
                    else RunOperation.INCREMENTAL
                ),
            )
            if outcome is RunTerminalState.SUCCEEDED:
                checkpoint.ledger.record_file_state(
                    checkpoint.generation_id,
                    FileState.policy_rejected(
                        "src/generated.py",
                        AdmissionDisposition(
                            ContentKind.CODE, False, AdmissionReason.PREPROCESS_SKIPPED
                        ),
                        content_hash=ledger_test_digest("safe skipped source"),
                    ),
                )
                ledger_test_publish_and_compact(
                    checkpoint.ledger, checkpoint.generation_id
                )
            else:
                checkpoint.ledger.finish_generation(
                    checkpoint.generation_id,
                    RunTerminalState.FAILED,
                    detail="returned_source_attempt_failed",
                )
        return IndexResult(
            total=0,
            added=0,
            updated=0,
            removed=0,
            duration_ms=0,
            device="cpu",
            preprocess_skipped=int(outcome is RunTerminalState.SUCCEEDED),
            preprocess_failures=["source: returned diagnostic"] if outcome else [],
        )

    monkeypatch.setattr(type(indexer), "full_index", returned_source_result)
    monkeypatch.setattr(type(indexer), "incremental_index", returned_source_result)
    monkeypatch.setattr(
        _job_admission,
        "validate_code_job_admission",
        _job_admission.validate_code_index_policy,
    )
    monkeypatch.setattr(
        _job_admission,
        "validate_document_job_admission",
        _job_admission.validate_document_index_policy,
    )
    runtime = SimpleNamespace(
        code_indexer=indexer, document_indexer=indexer, vault_indexer=indexer
    )
    registry = ServiceRegistry()

    @contextmanager
    def compute_lease(_root: Path) -> Generator[SimpleNamespace]:
        yield SimpleNamespace(runtime=runtime)

    monkeypatch.setattr(registry, "compute_lease", compute_lease)
    return registry


async def _dispatch_cpu_source_job(
    root: Path, source: WatcherSource, mode: JobMode, registry: ServiceRegistry
) -> tuple[JobSnapshot, JobExecutionResult | None]:
    manager = JobManager(
        state_path=root / "manager.json", quiesce_controller=ServiceQuiesceController()
    )
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource(source.value),
            str(root),
            mode,
            RunAuthority.REBUILD
            if mode is JobMode.REBUILD
            else RunAuthority.PUBLICATION,
        ),
        JobInitiator("cli", "source dispatch", str(root)),
    )
    assert created.job is not None
    finished = asyncio.Event()
    results: list[JobExecutionResult | None] = []

    def on_finished(
        _snapshot: JobSnapshot,
        _duration: float,
        result: JobExecutionResult | None,
        _error: BaseException | None,
    ) -> None:
        results.append(result)
        finished.set()

    assert bind_index_job(
        IndexJobBinding(
            manager, created.job.id, registry, None, None, on_finished=on_finished
        )
    ).job
    assert (await manager.dispatch_async(created.job.id)).job
    joined = await manager.wait_for_attempt(created.job.id, timeout_seconds=30.0)
    assert joined.code == "attempt_released", joined
    assert finished.is_set(), joined
    snapshot = manager.get(created.job.id)
    assert snapshot is not None and snapshot.state.is_terminal
    assert len(results) == 1
    registry.close_all()
    return snapshot, results[0]


@pytest.mark.parametrize("source", tuple(WatcherSource))
@pytest.mark.parametrize("mode", [JobMode.REBUILD, JobMode.INCREMENTAL])
async def test_production_dispatch_refuses_returned_failed_source_checkpoint(
    tmp_path: Path,
    source: WatcherSource,
    mode: JobMode,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _published_rebuild(tmp_path, source)
    registry = _install_cpu_source_result(
        tmp_path, source, mode, RunTerminalState.FAILED, monkeypatch
    )
    snapshot, _result = await _dispatch_cpu_source_job(tmp_path, source, mode, registry)

    # Mutation: removing the source's dispatch check persists false job success.
    assert snapshot.state is JobState.FAILED
    assert snapshot.error_kind == JobErrorKind.FULL_REINDEX_REQUIRED.value, (
        snapshot.result
    )
    assert "returned_source_attempt_failed" in (snapshot.result or "")
    assert snapshot.resilience is not None
    assert snapshot.resilience.generation_id is not None
    assert snapshot.resilience.terminal_outcome == RunTerminalState.FAILED.value


@pytest.mark.parametrize("outcome", [None, RunTerminalState.SUCCEEDED])
async def test_production_dispatch_preserves_code_noop_and_safe_skip_diagnostics(
    tmp_path: Path,
    outcome: RunTerminalState | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _published_rebuild(tmp_path)
    mode = JobMode.INCREMENTAL if outcome is None else JobMode.REBUILD
    registry = _install_cpu_source_result(
        tmp_path, WatcherSource.CODE, mode, outcome, monkeypatch
    )
    snapshot, result = await _dispatch_cpu_source_job(
        tmp_path, WatcherSource.CODE, mode, registry
    )

    assert snapshot.state is JobState.SUCCEEDED, snapshot.result
    assert snapshot.error_kind is None
    assert result is not None
    if outcome is RunTerminalState.SUCCEEDED:
        assert result.preprocess_failures == ("source: returned diagnostic",)
    else:
        assert snapshot.resilience is not None
        assert snapshot.resilience.generation_id is None


@pytest.mark.parametrize("reused", [False, True])
@pytest.mark.parametrize(
    ("source", "mode"),
    [
        (source, mode)
        for source in WatcherSource
        for mode in (JobMode.REBUILD, JobMode.INCREMENTAL)
        if source is not WatcherSource.CODE or mode is JobMode.REBUILD
    ],
)
async def test_dispatch_requires_a_current_owner_for_always_opening_work(
    tmp_path: Path,
    source: WatcherSource,
    mode: JobMode,
    reused: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _published_rebuild(tmp_path, source)
    if reused:
        previous = _new_checkpoint(tmp_path, source)
        ledger_test_publish_and_compact(previous.ledger, previous.generation_id)
    registry = _install_cpu_source_result(tmp_path, source, mode, None, monkeypatch)
    snapshot, result = await _dispatch_cpu_source_job(tmp_path, source, mode, registry)

    # Mutation: a prior publication cannot replace this attempt's missing owner.
    assert snapshot.state is JobState.FAILED
    assert snapshot.error_kind == JobErrorKind.FULL_REINDEX_REQUIRED.value
    assert "this attempt's publication checkpoint" in (snapshot.result or "")
    assert result is None
    assert snapshot.resilience is not None
    assert snapshot.resilience.generation_id is None


async def _complete_certified_full_job(
    manager: JobManager, root: Path, source: WatcherSource
) -> JobSnapshot:
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource(source.value),
            str(root),
            JobMode.REBUILD,
            RunAuthority.REBUILD,
        ),
        JobInitiator("cli", "explicit certified rebuild", str(root)),
    )
    assert created.job is not None
    finished = asyncio.Event()

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        checkpoint = _new_checkpoint(root, source)
        ledger_test_publish_and_compact(checkpoint.ledger, checkpoint.generation_id)
        context.set_resilience(
            _checkpoint_resilience(
                checkpoint,
                IndexResilienceSnapshot(),
                peak_rss_mib=None,
                peak_cuda_allocated_mib=None,
                peak_cuda_reserved_mib=None,
            )
        )
        return JobExecutionResult(summary="actual full generation published")

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
    assert snapshot.resilience is not None
    assert snapshot.resilience.terminal_outcome == RunTerminalState.SUCCEEDED.value
    return snapshot


def _record_newer_source_evidence(
    unowned: WatcherRetryPolicy,
    source: WatcherSource,
    rebuilt: JobSnapshot,
    newer_evidence: str,
) -> None:
    if newer_evidence == "unknown-marker":
        assert unowned.write_recovery_marker() is not None
    elif newer_evidence == "scope-capacity":
        unowned.mark_scope_pending(
            tuple(
                _path_observation(f"scope/{index}.txt", source=source)
                for index in range(unowned._scope_max_paths + 1)
            )
        )
    elif newer_evidence == "refusal":
        assert rebuilt.timestamps.finished_at is not None
        write_state(
            unowned._path,
            replace(
                unowned.state,
                scope_refusal=WatcherScopeRefusal.FULL_REINDEX_REQUIRED,
                last_error_kind=JobErrorKind.FULL_REINDEX_REQUIRED,
                last_error_detail="newer explicit refusal",
                last_failure_at=rebuilt.timestamps.finished_at + 1.0,
                circuit_state=WatcherCircuitState.OPEN,
                updated_at=rebuilt.timestamps.finished_at + 1.0,
            ),
        )


@pytest.mark.parametrize(
    ("source", "failed_job", "unknown_outcome"),
    [
        pytest.param(WatcherSource.DOCUMENT, False, None, id="document"),
        pytest.param(WatcherSource.VAULT, False, None, id="vault"),
        *[
            pytest.param(source, True, None, id=f"failed-{source.value}")
            for source in WatcherSource
        ],
        *[
            pytest.param(source, False, outcome, id=f"{outcome}-{source.value}")
            for source in (WatcherSource.DOCUMENT, WatcherSource.VAULT)
            for outcome in ("missing-resilience", "missing-terminal")
        ],
    ],
)
@pytest.mark.parametrize(
    "newer_evidence", ["none", "unknown-marker", "refusal", "scope-capacity"]
)
async def test_restart_reconciles_old_false_success_with_rebuild_and_newer_evidence(
    tmp_path: Path,
    source: WatcherSource,
    newer_evidence: str,
    failed_job: bool,
    unknown_outcome: str | None,
) -> None:
    manager, job_id = await _persist_historical_incremental_job(
        tmp_path,
        source,
        None if unknown_outcome == "missing-resilience" else RunTerminalState.FAILED,
        failed_job=failed_job,
        missing_terminal_outcome=unknown_outcome == "missing-terminal",
    )
    failed = manager.get(job_id)
    assert failed is not None and failed.timestamps.finished_at is not None
    _before, unowned = _unrefused_dead_source_attempt(
        tmp_path, source, job_id, recover_attempt=False
    )
    token = unowned.state.attempt_token
    assert token is not None
    assert token not in _ADMISSION_RESERVATIONS
    rebuilt = await _complete_certified_full_job(manager, tmp_path, source)
    assert rebuilt.timestamps.started_at is not None
    assert rebuilt.timestamps.finished_at is not None
    assert failed.timestamps.finished_at <= rebuilt.timestamps.started_at
    unowned = WatcherRetryPolicy.for_root(
        tmp_path, source, recover_abandoned_attempt=False
    )
    _record_newer_source_evidence(unowned, source, rebuilt, newer_evidence)
    restored = JobManager(
        state_path=tmp_path / "manager.json",
        quiesce_controller=ServiceQuiesceController(),
    )
    assert restored.restore_persisted().code == "job_state_restored"
    policy = WatcherRetryPolicy.for_root(tmp_path, source)
    before = policy.state
    assert policy._owned_attempt_token == token
    slot = WatcherConvergenceSlot(
        JobSource(source.value), tmp_path.resolve(), ServiceRegistry(), policy
    )
    try:
        await reconcile_restarted_slot(slot, restored)
        if newer_evidence == "none":
            # Mutation: restamping old terminal failure blocks the later actual rebuild.
            assert policy.state.scope_refusal is None
            assert policy.state.last_error_kind is None
        else:
            # Mutation: old failure timing must retain newer refusal/unknown evidence.
            expected_refusal = (
                WatcherScopeRefusal.SCOPE_CAPACITY_EXCEEDED
                if newer_evidence == "scope-capacity"
                else WatcherScopeRefusal.FULL_REINDEX_REQUIRED
            )
            assert policy.state.scope_refusal is expected_refusal
            assert policy.state.last_error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
            assert policy.state.updated_at >= before.updated_at
            if newer_evidence == "unknown-marker":
                assert policy.state.unscoped_required
            elif newer_evidence == "refusal":
                assert policy.state.last_failure_at == before.last_failure_at
                assert policy.state.last_error_detail == "newer explicit refusal"
            else:
                assert policy.state.last_error_detail == before.last_error_detail
        assert [item.relative_path for item in policy.state.pending_paths] == [
            "src/captured.py",
            "src/later.py",
        ]
        assert policy.state.convergence_pending
        assert policy.state.attempt_generation is None
        assert policy.state.attempt_job_id is None
        assert policy.state.attempt_token is None
        assert token not in _ADMISSION_RESERVATIONS
        assert not policy.state.captured_paths
    finally:
        if policy.state.attempt_generation is not None:
            policy.record_interrupted(policy.state.attempt_generation)


@pytest.mark.parametrize("newer_marker", [False, True])
async def test_restart_settles_historical_code_success_at_its_recorded_time(
    tmp_path: Path, newer_marker: bool
) -> None:
    manager, job_id = await _persist_historical_incremental_job(
        tmp_path, WatcherSource.CODE, None
    )
    _before, unowned = _unrefused_dead_source_attempt(
        tmp_path, WatcherSource.CODE, job_id, recover_attempt=False
    )
    if not newer_marker:
        unowned.write_recovery_marker()
        unowned = WatcherRetryPolicy.for_root(
            tmp_path, WatcherSource.CODE, recover_abandoned_attempt=False
        )
    await _complete_certified_full_job(manager, tmp_path, WatcherSource.CODE)
    if newer_marker:
        unowned.write_recovery_marker()
    restored = JobManager(
        state_path=tmp_path / "manager.json",
        quiesce_controller=ServiceQuiesceController(),
    )
    assert restored.restore_persisted().code == "job_state_restored"
    policy = WatcherRetryPolicy.for_root(tmp_path, WatcherSource.CODE)
    before = policy.state
    slot = WatcherConvergenceSlot(
        JobSource.CODE, tmp_path.resolve(), ServiceRegistry(), policy
    )

    await reconcile_restarted_slot(slot, restored)

    # Mutation: restart time cannot turn an old successful outcome into new scope.
    if newer_marker:
        assert policy.state.scope_refusal is WatcherScopeRefusal.FULL_REINDEX_REQUIRED
        assert policy.state.unscoped_required
        assert policy.state.updated_at >= before.updated_at
    else:
        assert policy.state.scope_refusal is None
        assert policy.state.last_error_kind is None
        assert not policy.state.unscoped_required
        assert policy.state.circuit_state is WatcherCircuitState.CLOSED
    assert [item.relative_path for item in policy.state.pending_paths] == [
        "src/later.py"
    ]
    assert not policy.state.captured_paths
    assert policy.state.attempt_generation is None
    assert policy.state.attempt_token is None
