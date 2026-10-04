"""CPU checks of durable rebuild contracts at real source entry boundaries."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from functools import partial
from types import MethodType
from typing import TYPE_CHECKING, Literal, cast

import pytest

from ..indexer import CodebaseIndexer, DocumentIndexer, VaultIndexer
from ..indexer._content_discovery import CodeContentDiscovery
from ..indexer._document_indexer import DocumentIndexPreflight
from ..indexer._run_ledger_models import RunAuthority
from ..job_control import PauseRequested, RunControlToken
from ..job_dispatch import _AttemptDispatch, _bind_index_attempt
from ..job_manager.manager import JobManager
from ..job_manager.models import JobAttemptContext
from ..job_models import (
    DesiredJobState,
    JobInitiator,
    JobMode,
    JobOperation,
    JobSource,
    JobSpec,
    JobState,
    ResumeStrategy,
)
from ..job_persistence import load_persisted_state
from ..progress import NullProgressReporter
from ..service import ServiceRegistry
from ..service_quiesce import QuiesceState

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from ..indexer import IndexResult
    from ..indexer._codebase_indexer import CodeIndexPreflight
    from ..job_manager.state import AttemptExit

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
