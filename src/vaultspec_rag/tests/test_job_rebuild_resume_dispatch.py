"""CPU checks of durable rebuild contracts at real source entry boundaries."""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field, replace
from functools import partial
from types import MethodType
from typing import TYPE_CHECKING, Literal, cast

import pytest

from .._source_types import PublicSourceType
from ..indexer import CodebaseIndexer, DocumentIndexer, VaultIndexer
from ..indexer._content_discovery import CodeContentDiscovery
from ..indexer._document_indexer import DocumentIndexPreflight
from ..indexer._rebuild_lifecycle import RebuildClaim, capture_reset_epoch
from ..indexer._run_ledger_models import RunAuthority, RunOperation
from ..job_control import PauseRequested, RunControlToken
from ..job_dispatch import _AttemptDispatch, _bind_index_attempt, _run_claimed_rebuild
from ..job_manager.manager import JobManager
from ..job_manager.models import JobAttemptContext, JobExecutionResult
from ..job_models import (
    DesiredJobState,
    JobInitiator,
    JobMode,
    JobOperation,
    JobOutcome,
    JobSource,
    JobSpec,
    JobState,
    ResumeStrategy,
)
from ..job_persistence import load_persisted_state
from ..progress import NullProgressReporter
from ..service import ServiceRegistry
from ..service_quiesce import QuiesceState, ServiceQuiesceController

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable
    from pathlib import Path

    from ..indexer import IndexResult
    from ..indexer._codebase_indexer import CodeIndexPreflight
    from ..job_manager.state import AttemptExit
    from ..job_models import JobSnapshot
    from ..store_runtime import VaultStore

pytestmark = [pytest.mark.unit]

_SOURCES = (JobSource.CODE, JobSource.DOCUMENT, JobSource.VAULT)
type _Recovery = Literal["fresh", "quiesce", "operator", "restored"]


def _durable_contract(
    tmp_path: Path,
    source: JobSource,
    recovery: _Recovery,
    *,
    mode: JobMode = JobMode.REBUILD,
    authority: RunAuthority = RunAuthority.REBUILD,
) -> tuple[JobManager, _AttemptDispatch]:
    root = tmp_path / "corpus"
    root.mkdir()
    state_path = tmp_path / "jobs.json"
    registry = ServiceRegistry()
    manager = JobManager(
        max_nonterminal=1,
        state_path=state_path,
        quiesce_controller=registry._quiesce_controller,
    )
    created = manager.create(
        JobSpec(JobOperation.INDEX, source, str(root), mode, authority),
        JobInitiator("test", "rebuild-resume", str(root)),
    )
    assert created.job is not None
    job_id = created.job.id
    if recovery == "operator":
        assert manager.set_desired_state(job_id, DesiredJobState.PAUSED).code == (
            "job_paused"
        )
        assert manager.set_desired_state(job_id, DesiredJobState.RUNNING).code == (
            "resume_requested"
        )
    elif recovery != "fresh":
        assert manager.defer_unstarted_for_quiesce(job_id).code == (
            "quiesce_deferred_before_start"
        )
        registry._quiesce_controller.begin_pause()
        prepared = manager.prepare_quiesced_resume(expected_state=QuiesceState.PAUSING)
        assert prepared.job_ids == (job_id,)
        registry._quiesce_controller.abort_pause()
        if recovery == "restored":
            manager = JobManager(
                max_nonterminal=1,
                state_path=state_path,
                quiesce_controller=registry._quiesce_controller,
            )
            assert manager.restore_persisted().code == "job_state_restored"
    snapshot = manager.get(job_id)
    assert snapshot is not None and snapshot.state is JobState.QUEUED
    assert snapshot.spec == created.job.spec
    assert not snapshot.runtime.worker_active
    assert not tuple(root.iterdir()), "unstarted recovery touched source storage"
    assert load_persisted_state(state_path).jobs[0] == snapshot
    if recovery != "fresh":
        assert snapshot.attempt.number == 2
        assert snapshot.attempt.resumed_from_attempt == 1
        assert snapshot.attempt.resume_strategy is ResumeStrategy.RECONCILE
    return manager, _AttemptDispatch(source, job_id, root, mode, authority, registry)


def _context(manager: JobManager, dispatch: _AttemptDispatch) -> JobAttemptContext:
    task = asyncio.current_task()
    assert task is not None
    snapshot = manager.get(dispatch.job_id)
    assert snapshot is not None
    return JobAttemptContext(
        manager,
        dispatch.job_id,
        snapshot.attempt.number,
        cast("asyncio.Task[AttemptExit]", task),
        RunControlToken(),
        dispatch.authority,
    )


def _source_entry(
    source: JobSource,
) -> CodebaseIndexer | DocumentIndexer | VaultIndexer:
    # Every full_index entry checks real control before reading instance state.
    # Stopping at that checkpoint observes delivery without constructing models.
    if source is JobSource.CODE:
        return object.__new__(CodebaseIndexer)
    if source is JobSource.DOCUMENT:
        return object.__new__(DocumentIndexer)
    return object.__new__(VaultIndexer)


def _bind(
    context: JobAttemptContext,
    dispatch: _AttemptDispatch,
) -> tuple[Callable[[], IndexResult], CodeIndexPreflight, DocumentIndexPreflight]:
    preflight = CodeContentDiscovery(dispatch.root).preflight_content()
    document_preflight = DocumentIndexPreflight(dispatch.root, preflight.policy, ())
    operation = _bind_index_attempt(
        context,
        dispatch,
        indexer=_source_entry(dispatch.source),
        reporter=NullProgressReporter(),
        preflight=(
            preflight
            if dispatch.source is JobSource.CODE
            else document_preflight
            if dispatch.source is JobSource.DOCUMENT
            else None
        ),
    )
    return operation, preflight, document_preflight


def _full_entry_locals(signal: PauseRequested, source: JobSource) -> dict[str, object]:
    methods = {
        JobSource.CODE: CodebaseIndexer.full_index,
        JobSource.DOCUMENT: DocumentIndexer.full_index,
        JobSource.VAULT: VaultIndexer.full_index,
    }
    traceback = signal.__traceback__
    while traceback is not None:
        if traceback.tb_frame.f_code is methods[source].__code__:
            return cast("dict[str, object]", traceback.tb_frame.f_locals)
        traceback = traceback.tb_next
    raise AssertionError("rebuild did not enter its actual full_index source method")


@pytest.mark.parametrize("source", _SOURCES)
@pytest.mark.parametrize("recovery", ["fresh", "quiesce", "operator", "restored"])
async def test_rebuild_keeps_clean_authority_at_real_source_entry(
    tmp_path: Path, source: JobSource, recovery: _Recovery
) -> None:
    """A lineage-based clean=False mutant must fail actual delivered arguments."""
    manager, dispatch = _durable_contract(tmp_path, source, recovery)
    context = _context(manager, dispatch)
    operation, code_preflight, document_preflight = _bind(context, dispatch)
    context.control.request_pause()
    with pytest.raises(PauseRequested) as caught:
        operation()
    delivered = _full_entry_locals(caught.value, source)
    assert delivered["clean"] is True, "resumed rebuild lost clean replacement intent"
    assert delivered["authority"] is RunAuthority.REBUILD
    assert delivered["run_control"] is context.control
    if source is JobSource.CODE:
        assert delivered["preflight"] is code_preflight
    elif source is JobSource.DOCUMENT:
        assert delivered["preflight"] is document_preflight
    else:
        assert "preflight" not in delivered
    assert not tuple(dispatch.root.iterdir())


@pytest.mark.parametrize("source", _SOURCES)
async def test_resumed_incremental_binds_its_actual_incremental_method(
    tmp_path: Path, source: JobSource
) -> None:
    """A mode-widening mutant must fail the concrete bound method assertion."""
    manager, dispatch = _durable_contract(
        tmp_path,
        source,
        "quiesce",
        mode=JobMode.INCREMENTAL,
        authority=RunAuthority.PUBLICATION,
    )
    context = _context(manager, dispatch)
    operation, code_preflight, document_preflight = _bind(context, dispatch)
    assert isinstance(operation, partial)
    method = operation.func
    assert isinstance(method, MethodType)
    methods = {
        JobSource.CODE: CodebaseIndexer.incremental_index,
        JobSource.DOCUMENT: DocumentIndexer.incremental_index,
        JobSource.VAULT: VaultIndexer.incremental_index,
    }
    assert method.__func__ is methods[source], (
        "incremental attempt widened to full execution"
    )
    assert "clean" not in operation.keywords
    assert operation.keywords["authority"] is RunAuthority.PUBLICATION
    assert operation.keywords["run_control"] is context.control
    if source is JobSource.CODE:
        assert operation.keywords["preflight"] is code_preflight
    elif source is JobSource.DOCUMENT:
        assert operation.keywords["preflight"] is document_preflight


@pytest.mark.parametrize(
    ("dispatch_authority", "context_authority", "message"),
    [
        (
            RunAuthority.PUBLICATION,
            RunAuthority.REBUILD,
            "persisted dispatch authority",
        ),
        (RunAuthority.PUBLICATION, RunAuthority.PUBLICATION, "cannot run a full"),
        (
            RunAuthority.AUDIT_VERIFICATION,
            RunAuthority.AUDIT_VERIFICATION,
            "audit-verification",
        ),
    ],
)
async def test_binding_refuses_an_unsupported_authority_before_source_entry(
    tmp_path: Path,
    dispatch_authority: RunAuthority,
    context_authority: RunAuthority,
    message: str,
) -> None:
    """Removing each canonical authority guard must reach DID NOT RAISE."""
    manager, dispatch = _durable_contract(tmp_path, JobSource.VAULT, "quiesce")
    context = replace(_context(manager, dispatch), authority=context_authority)
    dispatch = replace(dispatch, authority=dispatch_authority)
    if context_authority is not dispatch_authority:
        dispatch = replace(dispatch, mode=JobMode.INCREMENTAL)
    with pytest.raises(RuntimeError, match=message):
        _bind(context, dispatch)


@pytest.mark.parametrize("source", [JobSource.CODE, JobSource.DOCUMENT])
async def test_binding_requires_the_actual_admitted_preflight(
    tmp_path: Path, source: JobSource
) -> None:
    """Removing the preflight guard must reach DID NOT RAISE."""
    manager, dispatch = _durable_contract(tmp_path, source, "quiesce")
    with pytest.raises(RuntimeError, match="requires its admitted preflight"):
        _bind_index_attempt(
            _context(manager, dispatch),
            dispatch,
            indexer=_source_entry(source),
            reporter=NullProgressReporter(),
        )


def _claim_frame_locals(signal: PauseRequested) -> dict[str, object]:
    traceback = signal.__traceback__
    while traceback is not None:
        if traceback.tb_frame.f_code is _run_claimed_rebuild.__code__:
            return cast("dict[str, object]", traceback.tb_frame.f_locals)
        traceback = traceback.tb_next
    raise AssertionError("rebuild did not run under its job's rebuild claim")


@pytest.mark.parametrize("source", _SOURCES)
async def test_a_rebuild_attempt_runs_under_the_claim_its_job_recorded(
    tmp_path: Path, source: JobSource
) -> None:
    """Every source's rebuild entry runs under the job's own durable claim.

    Mutation: returning the bare ``full_index`` partial for one source
    dropped the claim frame and failed the frame lookup; restoring the
    claimed wrapper passed.
    """
    manager, dispatch = _durable_contract(tmp_path, source, "fresh")
    context = _context(manager, dispatch)
    operation, _code, _document = _bind(context, dispatch)
    context.control.request_pause()
    with pytest.raises(PauseRequested) as caught:
        operation()
    claim = _claim_frame_locals(caught.value)["claim"]
    assert isinstance(claim, RebuildClaim)
    snapshot = manager.get(dispatch.job_id)
    assert snapshot is not None
    assert claim.generation_id == snapshot.rebuild_generation_id
    assert claim.bind == context.bind_rebuild_generation


_WAIT_SECONDS = 20.0


async def _until(predicate: Callable[[], bool], what: str) -> None:
    deadline = time.monotonic() + _WAIT_SECONDS
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.01)


class _AttemptCrashError(RuntimeError):
    """The attempt stops without delivering any control, as a dying process does."""


@dataclass
class _RebuildHarness:
    """A real job manager running a vault rebuild over real local storage.

    The attempt runner drives the production checkpoint open, reset and
    write-policy-fenced store write under the dispatcher's rebuild claim,
    then stops at a durable unit boundary for the control the test sends.
    """

    root: Path
    state_path: Path
    store: VaultStore
    manager: JobManager
    unit_recorded: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)
    attempts: list[tuple[str, int, bool]] = field(default_factory=list)
    crash_next: bool = False

    def runner(self, context: JobAttemptContext) -> JobExecutionResult:
        return _run_claimed_rebuild(context, partial(self._attempt, context))

    def _attempt(self, context: JobAttemptContext) -> JobExecutionResult:
        from .._store_models import VaultChunk
        from ..indexer._rebuild_lifecycle import capture_reset_epoch
        from ..indexer._vault_checkpoint import VaultRunCheckpoint
        from ._run_ledger_test_support import ledger_test_unit

        checkpoint = VaultRunCheckpoint.open(
            self.root,
            backend_identity=self.store.backend_identity,
            authority=RunAuthority.REBUILD,
            operation=RunOperation.FULL,
            run_control=context.control,
        )
        checkpoint.reset_for_rebuild(
            self.store,
            began_under=capture_reset_epoch(
                self.root, PublicSourceType.VAULT, self.store.backend_identity
            ),
        )
        unit = ledger_test_unit("doc", 0, 1)
        with checkpoint.preserve_incomplete_generation():
            resumed = checkpoint.ledger.unit_committed(checkpoint.generation_id, unit)
            epoch = capture_reset_epoch(
                self.root, PublicSourceType.VAULT, self.store.backend_identity
            ).epoch
            self.attempts.append((checkpoint.generation_id, epoch, resumed))
            if not resumed:
                self.store.upsert_document_chunks(
                    [
                        VaultChunk(
                            doc_id="doc",
                            ordinal=0,
                            chunk_count=1,
                            text="replacement",
                            doc_content="replacement",
                            path="doc.md",
                            doc_type="adr",
                            feature="rebuild",
                            date="2026-10-12",
                            tags=[],
                            related=[],
                            title="Replacement",
                            vector=[1.0, 0.0],
                        )
                    ],
                    write_policy=checkpoint.run_policy.store_write_policy,
                )
                checkpoint.ledger.record_storage_confirmed_units(
                    checkpoint.generation_id, (unit,)
                )
                self.unit_recorded.set()
                assert self.release.wait(_WAIT_SECONDS), "control never arrived"
                if self.crash_next:
                    self.crash_next = False
                    raise _AttemptCrashError("the attempt died at its unit checkpoint")
            checkpoint.run_policy.checkpoint("durable unit boundary")
        return JobExecutionResult(summary="rebuilt")

    def request(
        self,
        *,
        source: JobSource = JobSource.VAULT,
        request_id: str | None = None,
    ) -> JobOutcome:
        """Submit one explicit rebuild request the way an adapter does."""
        return self.manager.create(
            JobSpec(
                JobOperation.INDEX,
                source,
                str(self.root),
                JobMode.REBUILD,
                RunAuthority.REBUILD,
            ),
            JobInitiator("test", "rebuild-claim", str(self.root)),
            job_id=request_id,
        )

    def create(self, *, request_id: str | None = None) -> str:
        created = self.request(request_id=request_id)
        assert created.job is not None
        return created.job.id

    def start(self, job_id: str) -> None:
        self.unit_recorded.clear()
        self.release.clear()
        assert self.manager.bind_dispatch(job_id, self.runner).code == (
            "dispatch_bound"
        )
        assert self.manager.dispatch(job_id).code == "attempt_started"

    async def control(self, job_id: str, desired: DesiredJobState) -> JobSnapshot:
        await _until(self.unit_recorded.is_set, "the first durable unit")
        self.manager.set_desired_state(job_id, desired)
        self.release.set()
        expected = (
            JobState.PAUSED if desired is DesiredJobState.PAUSED else JobState.CANCELLED
        )
        await _until(lambda: self._state(job_id) is expected, expected.value)
        snapshot = self.manager.get(job_id)
        assert snapshot is not None
        return snapshot

    async def finish(self, job_id: str, expected: JobState) -> JobSnapshot:
        await _until(lambda: self._state(job_id) is expected, expected.value)
        snapshot = self.manager.get(job_id)
        assert snapshot is not None
        return snapshot

    def _state(self, job_id: str) -> JobState | None:
        snapshot = self.manager.get(job_id)
        return None if snapshot is None else snapshot.state

    def points(self) -> int:
        return self.store.client.count(self.store.TABLE_NAME, exact=True).count

    async def stop(self) -> None:
        requested = self.manager.begin_shutdown()
        shutdown = await self.manager.wait_for_shutdown(
            requested, timeout_seconds=_WAIT_SECONDS
        )
        assert shutdown.clean


@pytest.fixture
async def harness(tmp_path: Path) -> AsyncGenerator[_RebuildHarness]:
    from ..config._settings import get_config
    from ..store_runtime import VaultStore

    get_config({"qdrant_url": None, "embedding_dimension": 2, "sparse_enabled": False})
    root = tmp_path / "corpus"
    root.mkdir()
    state_path = tmp_path / "jobs.json"
    with VaultStore(root, embedding_dim=2) as store:
        store.ensure_table()
        built = _RebuildHarness(
            root,
            state_path,
            store,
            JobManager(
                quiesce_controller=ServiceQuiesceController(),
                max_nonterminal=2,
                state_path=state_path,
            ),
        )
        try:
            yield built
        finally:
            await built.stop()


async def test_a_paused_rebuild_resumes_its_own_generation_after_restart(
    harness: _RebuildHarness,
) -> None:
    """Pause acknowledges at a durable unit and resume keeps that unit.

    The pause is acknowledged after the first confirmed replacement unit,
    with every execution resource released and the generation recorded on
    the persisted job. A restarted manager restores the paused job, and its
    resume continues the same generation: the unit is not rewritten, the
    reset is not repeated, and the replacement point survives.

    Mutation: building the dispatcher's claim without its ``bind`` left the
    job's generation unrecorded and failed the recorded-generation
    assertion (the resume would then have reset again); restoring it passed.
    """
    job_id = harness.create()
    harness.start(job_id)
    paused = await harness.control(job_id, DesiredJobState.PAUSED)

    generation_id, epoch, resumed = harness.attempts[0]
    assert (epoch, resumed) == (1, False)
    assert paused.rebuild_generation_id == generation_id
    assert not paused.resources.holds_anything
    assert load_persisted_state(harness.state_path).jobs[0].rebuild_generation_id == (
        generation_id
    )
    assert harness.points() == 1

    await harness.stop()
    harness.manager = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        max_nonterminal=2,
        state_path=harness.state_path,
    )
    assert harness.manager.restore_persisted().code == "job_state_restored"
    restored = harness.manager.get(job_id)
    assert restored is not None
    assert restored.state is JobState.PAUSED
    assert restored.rebuild_generation_id == generation_id

    assert harness.manager.set_desired_state(job_id, DesiredJobState.RUNNING).code == (
        "resume_requested"
    )
    harness.start(job_id)
    finished = await harness.finish(job_id, JobState.SUCCEEDED)

    assert harness.attempts[1] == (generation_id, 1, True)
    assert finished.rebuild_generation_id == generation_id
    assert harness.points() == 1


async def test_a_new_rebuild_job_resets_and_a_retry_of_the_replaced_one_fails(
    harness: _RebuildHarness,
) -> None:
    """Cancel acknowledges at a unit; only a new request resets again.

    A cancelled rebuild leaves its partial replacement. A new rebuild job
    claims nothing, so it starts a fresh generation and resets the source,
    discarding that partial work. A linked retry of the cancelled job then
    claims the generation the new rebuild replaced, and fails without
    resetting or touching the new rebuild's work.

    Mutation: building the retried job without its parent's
    ``rebuild_generation_id`` let the retry run as a new rebuild, which
    reset the source a third time and failed the retry-state assertion;
    restoring the carried generation passed.
    """
    first = harness.create()
    harness.start(first)
    cancelled = await harness.control(first, DesiredJobState.CANCELLED)
    first_generation = cancelled.rebuild_generation_id
    assert first_generation == harness.attempts[0][0]
    assert not cancelled.resources.holds_anything
    assert harness.points() == 1

    second = harness.create()
    assert second != first
    harness.start(second)
    await _until(harness.unit_recorded.is_set, "the new rebuild's first unit")
    second_generation, second_epoch, second_resumed = harness.attempts[1]
    assert second_generation != first_generation
    assert (second_epoch, second_resumed) == (2, False)
    harness.release.set()
    await harness.finish(second, JobState.SUCCEEDED)
    assert harness.points() == 1

    retried = harness.manager.retry(first)
    assert retried.job is not None
    assert retried.job.rebuild_generation_id == first_generation
    harness.start(retried.job.id)
    failed = await harness.finish(retried.job.id, JobState.FAILED)

    assert len(harness.attempts) == 2, "the replaced rebuild reopened a generation"
    assert "was replaced" in (failed.result or ""), failed.result
    assert failed.rebuild_generation_id == first_generation
    state = capture_reset_epoch(
        harness.root, PublicSourceType.VAULT, harness.store.backend_identity
    )
    assert state.epoch == 2
    assert harness.points() == 1


async def test_a_repeated_request_id_resets_the_source_at_most_once(
    harness: _RebuildHarness,
) -> None:
    """Submitting one request id again never starts a second reset.

    While the request runs, the repeat is the same job. Once it has finished,
    the id stays registered and the repeat is refused. Either way exactly one
    attempt reset the source, and its replacement point survives.

    Mutation: deleting the registered-id refusal from job creation let the
    finished request's id create a new job and failed the ``job_id_conflict``
    assertion; restoring it passed.
    """
    job_id = harness.create(request_id="request-1")
    harness.start(job_id)
    await _until(harness.unit_recorded.is_set, "the first durable unit")

    running_repeat = harness.request(request_id="request-1")
    assert running_repeat.code == "active_job_exists"
    assert running_repeat.job is not None
    assert running_repeat.job.id == job_id
    harness.release.set()
    await harness.finish(job_id, JobState.SUCCEEDED)

    finished_repeat = harness.request(request_id="request-1")
    assert finished_repeat.code == "job_id_conflict"

    assert len(harness.attempts) == 1
    state = capture_reset_epoch(
        harness.root, PublicSourceType.VAULT, harness.store.backend_identity
    )
    assert state.epoch == 1
    assert harness.points() == 1


async def test_queued_and_refused_rebuild_requests_delete_nothing(
    harness: _RebuildHarness,
) -> None:
    """Only a dispatched attempt resets; admission alone touches no storage.

    Two queued rebuilds have not run, and a third refused for capacity was
    never registered. The old point stays and no reset is recorded for any
    source.

    Mutation: recording the requested source's reset intent inside job
    creation failed the per-source reset-state assertion for ``vault``;
    restoring it passed.
    """
    from qdrant_client import models

    from .. import store_schema

    harness.store.client.upsert(
        harness.store.TABLE_NAME,
        points=[
            models.PointStruct(
                id=1,
                vector={store_schema.DENSE_VECTOR_NAME: [1.0, 0.0]},
                payload={"content": "old content"},
            )
        ],
        wait=True,
    )

    queued = harness.request()
    assert queued.code == "job_created"
    assert queued.job is not None
    assert queued.job.state is JobState.QUEUED
    assert harness.request(source=JobSource.CODE).code == "job_created"
    over_capacity = harness.request(source=JobSource.DOCUMENT)
    assert over_capacity.code == "job_capacity_exceeded"
    assert harness.points() == 1, "old content kept"
    for source in (
        PublicSourceType.VAULT,
        PublicSourceType.CODE,
        PublicSourceType.DOCUMENT,
    ):
        state = capture_reset_epoch(
            harness.root, source, harness.store.backend_identity
        )
        assert (state.epoch, state.phase) == (0, None), source


async def test_a_model_change_during_a_pause_never_mixes_epochs(
    harness: _RebuildHarness,
) -> None:
    """Resuming under another embedding model never continues the old generation.

    The paused generation's replacement vectors came from the first model. A
    resume under the second may not add vectors to that generation or keep
    them: it opens a fresh generation, resets again, rebuilds from nothing,
    and records the new generation on the job so a later attempt continues
    that one.

    Mutation: letting the ledger resume an active generation whatever its
    signature (dropping the fingerprint comparison) continued the paused
    generation over its first-model unit and failed the ``fresh generation``
    assertion; restoring it passed.
    """
    from ..config._settings import get_config

    job_id = harness.create()
    harness.start(job_id)
    paused = await harness.control(job_id, DesiredJobState.PAUSED)
    generation_id = paused.rebuild_generation_id
    assert generation_id is not None

    await harness.stop()
    get_config(
        {
            "qdrant_url": None,
            "embedding_dimension": 2,
            "sparse_enabled": False,
            "embedding_model": "another/dense-model",
        }
    )
    harness.manager = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        max_nonterminal=2,
        state_path=harness.state_path,
    )
    assert harness.manager.restore_persisted().code == "job_state_restored"
    assert harness.manager.set_desired_state(job_id, DesiredJobState.RUNNING).code == (
        "resume_requested"
    )
    harness.start(job_id)
    harness.release.set()
    await _until(
        lambda: (
            (snapshot := harness.manager.get(job_id)) is not None
            and snapshot.state.is_terminal
        ),
        "the resumed attempt to end",
    )
    finished = harness.manager.get(job_id)
    assert finished is not None
    state = capture_reset_epoch(
        harness.root, PublicSourceType.VAULT, harness.store.backend_identity
    )
    fresh_generation, fresh_epoch, resumed = harness.attempts[1]
    assert fresh_generation != generation_id, "fresh generation"
    assert (fresh_epoch, resumed) == (2, False)
    assert finished.state is JobState.SUCCEEDED
    assert finished.rebuild_generation_id == fresh_generation
    assert (state.epoch, state.generation_id) == (2, fresh_generation)
    assert harness.points() == 1


async def test_a_crash_at_a_unit_checkpoint_keeps_the_confirmed_unit(
    harness: _RebuildHarness,
) -> None:
    """A crash after a unit is confirmed loses nothing; the retry resumes it.

    The attempt dies at the durable unit boundary, after its replacement unit
    was stored and recorded. The failed job keeps the generation it recorded,
    and its linked retry continues that generation over the same reset epoch:
    the recorded unit is found committed and is not rewritten, and the
    replacement point survives.

    Mutation: making the retry claim nothing (starting a new rebuild) reset
    the source again and failed the ``resumed`` assertion; restoring the
    carried generation passed.
    """
    job_id = harness.create()
    harness.crash_next = True
    harness.start(job_id)
    await _until(harness.unit_recorded.is_set, "the first durable unit")
    harness.release.set()
    crashed = await harness.finish(job_id, JobState.FAILED)

    generation_id, epoch, resumed = harness.attempts[0]
    assert (epoch, resumed) == (1, False)
    assert crashed.rebuild_generation_id == generation_id
    assert harness.points() == 1

    retried = harness.manager.retry(job_id)
    assert retried.job is not None
    harness.start(retried.job.id)
    # A resumed attempt finds its unit committed and never waits; an attempt
    # that started over would wait here for the release.
    harness.release.set()
    finished = await harness.finish(retried.job.id, JobState.SUCCEEDED)

    assert harness.attempts[1] == (generation_id, 1, True), "resumed"
    assert finished.rebuild_generation_id == generation_id
    state = capture_reset_epoch(
        harness.root, PublicSourceType.VAULT, harness.store.backend_identity
    )
    assert (state.epoch, state.generation_id) == (1, generation_id)
    assert harness.points() == 1
