"""Managed attempts cannot inherit a resident indexer's prior memory facts."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, cast

import pytest

from .._publication_state import acquire_publication_snapshot
from .._source_types import PublicSourceType
from ..config._settings import get_config
from ..index_profiles import SupportMeasurement
from ..indexer import CodebaseIndexer, DocumentIndexer
from ..indexer._content_policy import (
    ContentKind,
    ContentRoute,
    RootContentPolicy,
    SourceProfileVersion,
)
from ..indexer._publication_proof import ProofReceiptState
from ..indexer._run_ledger_models import RunLedgerStateError, ledger_connection
from ..indexer._run_ledger_publication_storage import hydrate_receipt, receipt_row_by_id
from ..job_dispatch import _indexer_resilience, _observe_index_resilience
from ..job_manager.manager import JobManager
from ..job_models import IndexResilienceSnapshot, JobSource
from ..memory_probe import route_forward_peak_mib
from ..progress import NullProgressReporter
from ..store_runtime import VaultStore
from ._indexer_fixtures import support_measurement
from ._store_fixtures import get_all_document_content_ids
from .test_live_checkpoint_resilience import _running, unloaded_model

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

    from ..embeddings import EmbeddingModel
    from ..indexer._vault_prep import IndexResult
    from ..job_manager.state import AttemptExit

__all__ = ["unloaded_model"]
pytestmark = [pytest.mark.unit]

_PRIOR_PEAK = 12_021.8
_CURRENT_PEAK = 1_234.0
_ADMITTED = IndexResilienceSnapshot(
    rss_ceiling_mib=16_384.0,
    cuda_ceiling_mib=13_000.0,
    support_profile="managed-service",
)


@dataclass
class _Case:
    root: Path
    source: JobSource
    path: Path
    indexer: CodebaseIndexer | DocumentIndexer
    peak: list[float]

    def run(self, *, incremental: bool = False, scoped: bool = False) -> IndexResult:
        """Execute the public API with fresh real discovery and authority."""
        indexer = self.indexer
        if isinstance(indexer, CodebaseIndexer):
            if scoped:
                return indexer.incremental_index(
                    reporter=NullProgressReporter(),
                    changed_paths=(),
                    preflight=indexer.preflight_changed_paths(()),
                )
            code_preflight = indexer.preflight_content()
            if incremental:
                return indexer.incremental_index(
                    reporter=NullProgressReporter(), preflight=code_preflight
                )
            return indexer.full_index(
                clean=True, reporter=NullProgressReporter(), preflight=code_preflight
            )
        if scoped:
            return indexer.incremental_index(
                reporter=NullProgressReporter(),
                changed_paths=(),
                preflight=indexer.preflight_changed_paths(()),
            )
        preflight = indexer.preflight_content()
        if incremental:
            return indexer.incremental_index(
                reporter=NullProgressReporter(), preflight=preflight
            )
        return indexer.full_index(
            clean=True, reporter=NullProgressReporter(), preflight=preflight
        )


@pytest.fixture(params=[JobSource.CODE, JobSource.DOCUMENT])
def case(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    unloaded_model: EmbeddingModel,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[_Case]:
    """Use isolated storage and a real unloaded model; replace only forwarding."""
    get_config(
        {
            "embedding_dimension": 2,
            "qdrant_url": None,
            "sparse_enabled": False,
            "reranker_enabled": False,
            "index_chunk_workers": 1,
            "index_reuse_enabled": False,
        }
    )
    peak = [_PRIOR_PEAK]

    def encode(texts: list[str], **_options: object) -> list[list[float]]:
        assert route_forward_peak_mib(peak[0]), "forward recorder was not registered"
        budget = (
            indexer._support_budget.memory_budget
            if isinstance(indexer, CodebaseIndexer)
            else indexer._memory_budget
        )
        assert budget is not None and budget.snapshot is not None
        budget.sample_readings(
            label="synthetic CPU forward capture",
            rss_mib=budget.snapshot.rss_mib,
            cuda_mib=(peak[0], peak[0] + 100.0),
        )
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(unloaded_model, "encode_documents_on_device", encode)
    source: JobSource = request.param
    name = "module.py" if source is JobSource.CODE else "guide.txt"
    path = tmp_path / name
    path.write_text("def alpha():\n    return 1\n", encoding="utf-8")
    (tmp_path / ".vaultragignore").write_text("jobs.json\n", encoding="utf-8")
    policy = RootContentPolicy(
        SourceProfileVersion.CONVENTIONAL_V1,
        (ContentRoute("guide.txt", ContentKind.DOCUMENT),),
    )
    with VaultStore(tmp_path, embedding_dim=2) as store:
        indexer = (
            CodebaseIndexer(
                tmp_path,
                unloaded_model,
                store,
                options=CodebaseIndexer.Options(content_policy=policy),
            )
            if source is JobSource.CODE
            else DocumentIndexer(tmp_path, unloaded_model, store, content_policy=policy)
        )
        yield _Case(tmp_path, source, path, indexer, peak)


@pytest.fixture
def publications(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, list[IndexResilienceSnapshot]]:
    """Capture publications while retaining actual ownership and persistence."""
    observed: dict[str, list[IndexResilienceSnapshot]] = {}
    original = JobManager.update_resilience

    def update(
        manager: JobManager,
        job_id: str,
        *,
        task: asyncio.Task[AttemptExit],
        resilience: IndexResilienceSnapshot,
    ) -> bool:
        accepted = original(manager, job_id, task=task, resilience=resilience)
        if accepted:
            observed.setdefault(job_id, []).append(resilience)
        return accepted

    monkeypatch.setattr(JobManager, "update_resilience", update)
    return observed


async def _managed_run(
    case: _Case, operation: Callable[[], IndexResult]
) -> tuple[str, IndexResilienceSnapshot, IndexResult]:
    """Keep attempt observation and the public run together in one CPU worker."""
    with _running(case.root, case.source) as context:
        context.set_resilience(_ADMITTED)

        def execute() -> IndexResult:
            with _observe_index_resilience(context, case.indexer, _ADMITTED):
                return operation()

        result = await asyncio.to_thread(execute)
        job = context.manager.get(context.job_id)
        assert job is not None and job.resilience is not None
        return context.job_id, job.resilience, result


def _assert_unknown_peaks(snapshot: IndexResilienceSnapshot, message: str) -> None:
    assert (
        snapshot.peak_rss_mib,
        snapshot.peak_cuda_allocated_mib,
        snapshot.peak_cuda_reserved_mib,
    ) == (None, None, None), message


@pytest.mark.parametrize("incremental", [False, True], ids=["full", "incremental"])
@pytest.mark.asyncio
async def test_new_checkpoint_and_terminal_peaks_belong_to_attempt(
    case: _Case,
    publications: dict[str, list[IndexResilienceSnapshot]],
    incremental: bool,
) -> None:
    """Omitting the observation-entry reset exposes the preceding forward peak."""
    _, prior, _ = await _managed_run(case, case.run)
    assert prior.peak_cuda_allocated_mib == _PRIOR_PEAK
    case.path.write_text("def alpha():\n    return 2\n", encoding="utf-8")
    case.peak[0] = _CURRENT_PEAK
    job_id, terminal, _ = await _managed_run(
        case, lambda: case.run(incremental=incremental)
    )
    opened = next(
        fact for fact in publications[job_id] if fact.generation_id is not None
    )
    _assert_unknown_peaks(
        opened, "new checkpoint must not inherit previous attempt memory peaks"
    )
    assert terminal.peak_cuda_allocated_mib == _CURRENT_PEAK
    assert prior.peak_cuda_allocated_mib == _PRIOR_PEAK
    assert terminal.generation_id != prior.generation_id
    assert terminal.committed_units > 0
    assert terminal.terminal_outcome == "succeeded"
    for fact in (opened, terminal):
        assert fact.rss_ceiling_mib == _ADMITTED.rss_ceiling_mib
        assert fact.cuda_ceiling_mib == _ADMITTED.cuda_ceiling_mib
        assert fact.support_profile == _ADMITTED.support_profile


@pytest.mark.asyncio
async def test_preflight_refusal_retains_exception_and_unknown_memory(
    case: _Case,
) -> None:
    """A real preflight-root refusal must not publish the preceding run's budget."""
    _, prior, _ = await _managed_run(case, case.run)
    assert prior.peak_cuda_allocated_mib == _PRIOR_PEAK
    with _running(case.root, case.source) as context:

        def refuse() -> None:
            with _observe_index_resilience(context, case.indexer, _ADMITTED):
                indexer = case.indexer
                if isinstance(indexer, CodebaseIndexer):
                    preflight = replace(
                        indexer.preflight_content(), root_dir=case.root / "foreign"
                    )
                    indexer.full_index(
                        reporter=NullProgressReporter(), preflight=preflight
                    )
                else:
                    document_preflight = replace(
                        indexer.preflight_content(), root_dir=case.root / "foreign"
                    )
                    indexer.full_index(
                        reporter=NullProgressReporter(), preflight=document_preflight
                    )

        expected = (
            "code index preflight root does not match the indexer root"
            if case.source is JobSource.CODE
            else "document index preflight belongs to another root"
        )
        with pytest.raises(ValueError, match=f"^{expected}$"):
            await asyncio.to_thread(refuse)
        job = context.manager.get(context.job_id)
        assert job is not None and job.resilience is not None
        _assert_unknown_peaks(
            job.resilience, "preflight refusal must not inherit previous memory peaks"
        )
        assert job.resilience.generation_id is None
        assert case.indexer.memory_budget_snapshot is None
        if isinstance(case.indexer, CodebaseIndexer):
            assert support_measurement(case.indexer) == SupportMeasurement(0, 0)
            assert case.indexer._support_budget._support_limits is None
            assert case.indexer._support_budget._support_profile_name is None


@pytest.mark.parametrize("scoped", [False, True], ids=["unscoped", "empty-scope"])
@pytest.mark.asyncio
async def test_unchanged_attempt_owns_only_observations_it_takes(
    case: _Case,
    publications: dict[str, list[IndexResilienceSnapshot]],
    scoped: bool,
) -> None:
    _, prior, _ = await _managed_run(case, case.run)
    assert prior.peak_cuda_allocated_mib == _PRIOR_PEAK
    before = acquire_publication_snapshot(
        case.root, PublicSourceType(case.source.value)
    )
    before.validate()
    point_ids = (
        case.indexer.store.get_all_code_ids()
        if case.source is JobSource.CODE
        else get_all_document_content_ids(case.indexer.store)
    )
    failure: RunLedgerStateError | None = None
    outcome: tuple[str, IndexResilienceSnapshot, IndexResult] | None = None
    try:
        outcome = await _managed_run(
            case, lambda: case.run(incremental=True, scoped=scoped)
        )
    except RunLedgerStateError as exc:
        failure = exc
    assert failure is None, "unchanged document attempt must settle its empty receipt"
    assert outcome is not None
    job_id, terminal, result = outcome
    assert (result.added, result.updated, result.removed) == (0, 0, 0)
    after = acquire_publication_snapshot(case.root, PublicSourceType(case.source.value))
    after.validate()
    assert after.proof == replace(
        before.proof,
        reservation_sequence=before.proof.reservation_sequence
        + (1 if case.source is JobSource.DOCUMENT else 0),
    )
    if case.source is JobSource.CODE:
        _assert_unknown_peaks(
            terminal, "unchanged attempt must not inherit previous memory peaks"
        )
        assert terminal.generation_id is None
        assert terminal.committed_units == 0
    else:
        opened = next(
            fact for fact in publications[job_id] if fact.generation_id is not None
        )
        _assert_unknown_peaks(
            opened, "unchanged checkpoint must start without old peaks"
        )
        assert terminal.peak_cuda_allocated_mib == 0.0
        assert terminal.generation_id != prior.generation_id
        assert get_all_document_content_ids(case.indexer.store) == point_ids
        checkpoint = case.indexer.last_checkpoint
        assert checkpoint is not None and checkpoint.receipt is not None
        assert checkpoint.ledger.committed_unit_count(checkpoint.generation_id) == 0
        with ledger_connection(checkpoint.ledger.path) as connection:
            row = receipt_row_by_id(connection, checkpoint.receipt.receipt_id)
            assert row is not None
            receipt = hydrate_receipt(connection, row)
        assert receipt.state is ProofReceiptState.ROLLED_BACK
        assert not receipt.mutations and not receipt.deltas
        with pytest.raises(
            RunLedgerStateError,
            match=r"^effective publication reads require a sealed forward receipt$",
        ):
            checkpoint.ledger.effective_file_state_page(
                receipt.receipt_id,
                checkpoint.generation_id,
                rel_paths=(case.path.name,),
                candidates=(),
            )
    assert terminal.support_profile == _ADMITTED.support_profile
    case.path.write_text("def alpha():\n    return 3\n", encoding="utf-8")
    case.peak[0] = _CURRENT_PEAK
    _, next_attempt, _ = await _managed_run(case, lambda: case.run(incremental=True))
    assert next_attempt.peak_cuda_allocated_mib == _CURRENT_PEAK


def test_code_projection_without_budget_keeps_unobserved_peaks_unknown(
    tmp_path: Path, unloaded_model: EmbeddingModel
) -> None:
    """Restoring the old measurement fallback fabricates peaks without a budget."""
    indexer = CodebaseIndexer(tmp_path, unloaded_model, cast("VaultStore", None))
    fact = _indexer_resilience(indexer, None, _ADMITTED)
    _assert_unknown_peaks(fact, "unobserved attempt memory peaks must remain unknown")
