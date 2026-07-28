"""Tests for VaultIndexer: full/incremental indexing and document preparation."""

from __future__ import annotations

import logging
import multiprocessing
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import TYPE_CHECKING

import pytest

from ...progress import NullProgressReporter
from ..benchmarks.bench_large_index_resilience import (
    CorpusSpec,
    MeasuredIndexRun,
    measure_full_index,
    prepare_corpus,
    retain_benchmark_evidence,
)
from ._helpers import _document_policy

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import TempPathFactory

    from ...embeddings import EmbeddingModel
    from ..conftest import RagComponentsWithManifest


pytestmark = [pytest.mark.integration]


def _configure_cpu_code_index(
    dimension: int,
    **overrides: object,
) -> None:
    """Select a tiny real CPU encoder while retaining production indexing."""
    from ...config._settings import get_config

    values: dict[str, object] = {
        "data_dir": ".index-memory-test",
        "embedding_batch_size": 1,
        "embedding_dimension": dimension,
        "embedding_encode_batch_size": 1,
        "embedding_code_encode_batch_size": 1,
        "index_chunk_workers": 1,
        "index_segment_max_chunks": 1,
        "index_queue_max_chunks": 1,
        "qdrant_url": None,
        "sparse_enabled": False,
    }
    values.update(overrides)
    get_config(values)


@pytest.fixture
def cpu_code_embedding_model(clean_config: None) -> EmbeddingModel:
    """Build the production embedding API around a real CPU BoW encoder."""
    del clean_config
    from sentence_transformers.sentence_transformer import SentenceTransformer
    from sentence_transformers.sentence_transformer.modules import BoW

    from ...embeddings import EmbeddingModel, QueryEmbeddingCache

    backend = SentenceTransformer(
        modules=[BoW(["alpha", "beta", "gamma", "index", "memory"])],
        device="cpu",
    )
    dimension = backend.get_embedding_dimension()
    assert dimension is not None
    _configure_cpu_code_index(dimension)

    model = EmbeddingModel.__new__(EmbeddingModel)
    model._dense_model = backend
    model._device = "cpu"
    model.dimension = dimension
    model.query_cache = QueryEmbeddingCache()
    return model


def _write_code_memory_corpus(root: Path, count: int = 4) -> None:
    """Write a small real source corpus with independent chunk identities."""
    source = root / "src"
    source.mkdir(parents=True, exist_ok=True)
    for ordinal in range(count):
        (source / f"memory_{ordinal:03d}.py").write_text(
            f"def memory_{ordinal:03d}() -> str:\n"
            f'    return "alpha beta gamma index memory {ordinal:03d}"\n',
            encoding="utf-8",
        )


def _assert_code_pipeline_released(indexer: object) -> None:
    """Assert physical consumer, worker, and writer ownership is released."""
    from ...indexer import CodebaseIndexer

    assert isinstance(indexer, CodebaseIndexer)
    assert not [
        thread
        for thread in threading.enumerate()
        if thread.name == "codebase-indexer-consumer"
    ]
    assert not multiprocessing.active_children()
    assert indexer._writer_lock.acquire(blocking=False)
    indexer._writer_lock.release()


def _wait_for_document_write_lock(indexer: object, *, timeout: float = 10.0) -> None:
    """Wait until a real document run has encoded and reached its store write."""
    from ...indexer import DocumentIndexer

    assert isinstance(indexer, DocumentIndexer)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = indexer.memory_budget_snapshot
        if snapshot is not None and "after-dense-forward" in snapshot.label:
            return
        time.sleep(0.01)
    raise AssertionError("document run did not reach the contended write lock")


# ---- Indexer Tests ----


class TestVaultIndexer:
    """Tests for the indexing pipeline with real vault data."""

    @pytest.mark.timeout(60)
    def test_full_index_counts(self, rag_components: RagComponentsWithManifest) -> None:
        result = rag_components["index_result"]
        assert result.total > 0
        assert result.added > 0
        assert result.duration_ms >= 0
        assert result.device == "cuda"

    @pytest.mark.timeout(60)
    def test_index_matches_store_count(
        self, rag_components: RagComponentsWithManifest
    ) -> None:
        result = rag_components["index_result"]
        store = rag_components["store"]
        assert result.total == store.count()

    @pytest.mark.timeout(300)
    def test_incremental_index_no_changes(
        self, rag_components_full: RagComponentsWithManifest
    ) -> None:
        """Incremental index with no changes should report zero additions.

        Requires full corpus because incremental_index() scans the full
        vault and compares against stored ids.
        """
        indexer = rag_components_full["indexer"]
        result = indexer.incremental_index(reporter=NullProgressReporter())
        # No new files, no modifications, no deletions
        assert result.added == 0
        assert result.removed == 0
        # Total should match the full index
        assert result.total == rag_components_full["index_result"].total


class TestLargeCodeIndexHighWater:
    """Real-CUDA N/two-N evidence for bounded production retention."""

    @pytest.mark.timeout(180)
    def test_small_file_segments_share_one_real_encode_and_store_slice(
        self,
        embedding_model: EmbeddingModel,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from ... import CodebaseIndexer
        from ...store_runtime import VaultStore

        spec = CorpusSpec(files=2, chunks_per_file=3)
        prepare_corpus(tmp_path, spec)
        store = VaultStore(tmp_path)
        try:
            indexer = CodebaseIndexer(tmp_path, embedding_model, store)
            with caplog.at_level(logging.INFO, logger="vaultspec_rag.store_ingest"):
                result = indexer.full_index(
                    reporter=NullProgressReporter(),
                    preflight=indexer.preflight_content(),
                )
            assert result.total == spec.expected_chunks
            assert any(
                record.getMessage()
                == f"Upserted {spec.expected_chunks} codebase chunk(s)"
                for record in caplog.records
            )
        finally:
            store.close()

    @pytest.mark.performance
    @pytest.mark.timeout(900)
    def test_rss_and_cuda_high_water_remain_bounded_as_corpus_doubles(
        self,
        embedding_model: EmbeddingModel,
        tmp_path_factory: TempPathFactory,
    ) -> None:
        from ... import CodebaseIndexer
        from ...config._settings import get_config
        from ...index_profiles import get_index_support_profile
        from ...store_runtime import VaultStore

        def _run(files: int) -> MeasuredIndexRun:
            root = tmp_path_factory.mktemp(f"large-code-{files}")
            spec = CorpusSpec(files=files, chunks_per_file=3)
            prepare_corpus(root, spec)
            store = VaultStore(root)
            try:
                indexer = CodebaseIndexer(root, embedding_model, store)
                measured = measure_full_index(
                    indexer,
                    indexer.preflight_content(),
                    clean=True,
                )
                assert measured.result.total == spec.expected_chunks
                assert indexer.support_measurement.generated_chunks == (
                    spec.expected_chunks
                )
                return measured
            finally:
                store.close()

        n_run = _run(192)
        two_n_run = _run(384)
        n_resources = n_run.resources
        two_n_resources = two_n_run.resources
        n_chunks = n_run.result.total
        two_n_chunks = two_n_run.result.total
        growth_allowance_mb = {
            "rss": 512.0,
            "cuda_allocated": 256.0,
            "cuda_reserved": 512.0,
        }
        limits = get_index_support_profile(get_config().index_support_profile).code
        mib = 1024**2
        checks = {
            "chunk_count_doubled": two_n_chunks == n_chunks * 2,
            "rss_growth_bounded": two_n_resources.rss_growth_mb
            <= n_resources.rss_growth_mb + growth_allowance_mb["rss"],
            "cuda_allocated_growth_bounded": (
                two_n_resources.cuda_allocated_growth_mb
                <= n_resources.cuda_allocated_growth_mb
                + growth_allowance_mb["cuda_allocated"]
            ),
            "cuda_reserved_growth_bounded": (
                two_n_resources.cuda_reserved_growth_mb
                <= n_resources.cuda_reserved_growth_mb
                + growth_allowance_mb["cuda_reserved"]
            ),
            "n_rss_within_profile": n_resources.peak_rss_mb * mib <= limits.rss_bytes,
            "two_n_rss_within_profile": two_n_resources.peak_rss_mb * mib
            <= limits.rss_bytes,
            "n_cuda_within_profile": n_resources.peak_cuda_reserved_mb * mib
            <= limits.cuda_bytes,
            "two_n_cuda_within_profile": (
                two_n_resources.peak_cuda_reserved_mb * mib <= limits.cuda_bytes
            ),
        }
        retain_benchmark_evidence(
            "n-two-n-high-water",
            {
                "n": {
                    "files": 192,
                    "chunks": n_chunks,
                    "wall_seconds": n_run.wall_seconds,
                    "resources": asdict(n_resources),
                },
                "two_n": {
                    "files": 384,
                    "chunks": two_n_chunks,
                    "wall_seconds": two_n_run.wall_seconds,
                    "resources": asdict(two_n_resources),
                },
                "growth_allowance_mb": growth_allowance_mb,
                "profile_ceilings_mb": {
                    "rss": limits.rss_bytes / mib,
                    "cuda_reserved": limits.cuda_bytes / mib,
                },
                "checks": checks,
            },
        )
        assert two_n_chunks == n_chunks * 2

        # The active queue and GPU slice are bounded independently of corpus
        # cardinality. Doubling past the 512-chunk slice boundary may move the
        # allocator to its next block, but cannot retain corpus-proportional
        # process or device memory.
        assert checks["rss_growth_bounded"]
        assert two_n_resources.cuda_allocated_growth_mb <= (
            n_resources.cuda_allocated_growth_mb + growth_allowance_mb["cuda_allocated"]
        )
        assert two_n_resources.cuda_reserved_growth_mb <= (
            n_resources.cuda_reserved_growth_mb + growth_allowance_mb["cuda_reserved"]
        )

        for resources in (n_resources, two_n_resources):
            assert resources.peak_rss_mb * mib <= limits.rss_bytes
            assert resources.peak_cuda_reserved_mb * mib <= limits.cuda_bytes


class TestCodeIndexMemoryCeilings:
    """Production code indexing terminates cleanly at admitted memory limits."""

    @pytest.mark.timeout(30)
    def test_low_rss_ceiling_returns_typed_outcome_and_releases_pipeline(
        self,
        cpu_code_embedding_model: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        from ... import CodebaseIndexer
        from ..._job_errors import JobError, JobErrorKind
        from ...job_dispatch import _code_resilience
        from ...store_runtime import VaultStore

        _configure_cpu_code_index(
            cpu_code_embedding_model.dimension,
            index_rss_ceiling_mb=1.0,
        )
        _write_code_memory_corpus(tmp_path)

        with VaultStore(
            tmp_path,
            embedding_dim=cpu_code_embedding_model.dimension,
        ) as store:
            indexer = CodebaseIndexer(tmp_path, cpu_code_embedding_model, store)
            with pytest.raises(JobError) as stopped:
                indexer.full_index(
                    reporter=NullProgressReporter(),
                    preflight=indexer.preflight_content(),
                )

            assert stopped.value.error_kind is JobErrorKind.RSS_MEMORY_CEILING
            snapshot = indexer.memory_budget_snapshot
            assert snapshot is not None
            assert snapshot.label == "before code dispatch"
            assert snapshot.rss_available
            rss_ceiling_mb = snapshot.rss_ceiling_mb
            assert rss_ceiling_mb is not None
            assert rss_ceiling_mb == 1.0
            assert snapshot.peak_rss_mb > rss_ceiling_mb
            resilience = _code_resilience(indexer)
            assert resilience.rss_ceiling_mb == rss_ceiling_mb
            assert resilience.peak_rss_mb == snapshot.peak_rss_mb
            assert store.count_code() == 0
            _assert_code_pipeline_released(indexer)

    @pytest.mark.cuda
    @pytest.mark.timeout(60)
    def test_low_cuda_ceiling_returns_typed_outcome_and_releases_pipeline(
        self,
        clean_config: None,
        embedding_model: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        """A ceiling a hair above the resident baseline breaches on a forward.

        The ceiling must be derived from the resident baseline, because that is
        the figure enforcement subtracts from both sides. Deriving it from the
        live reserved reading instead makes the test order-dependent: reserved
        is allocator cache, which no ceiling governs, and an earlier run in the
        same process leaves it far above what the models actually hold. The
        ceiling then lands above anything this corpus can allocate, admission
        releases the cache anyway, and the index completes - passing alone and
        failing DID NOT RAISE behind any test that warmed the allocator.

        Proven able to fail: dropping the ``+ 0.001`` pins the ceiling at the
        baseline, admission refuses before dispatch, and with no forward ever
        sampled this fails on ``assert snapshot is not None``; restored, the
        first slice breaches mid-run.
        """
        del clean_config
        from ... import CodebaseIndexer
        from ..._job_errors import JobError, JobErrorKind
        from ...config._settings import get_config
        from ...job_dispatch import _code_resilience
        from ...memory_probe import (
            current_cuda_mb,
            current_rss_mb,
            sample_resident_cuda_baseline,
        )
        from ...store_runtime import VaultStore

        # The same call production makes once each shared model finishes
        # loading; the fixture above loaded one.
        baseline_mb = sample_resident_cuda_baseline()
        assert baseline_mb > 0.0, (
            "premise: the embedding model must be resident on the device"
        )
        # Stated because the whole guard rests on it, and because its absence is
        # otherwise unreadable: enforcement clamps the peak net of this figure at
        # zero, so a baseline describing memory already released puts every
        # ceiling out of reach and this test fails with a bare DID NOT RAISE.
        assert baseline_mb == pytest.approx(current_cuda_mb()[0], abs=1.0), (
            "premise: the recorded baseline must describe memory still resident"
        )
        # Positive headroom, so admission admits the run; small enough that the
        # first real forward's activations cross it.
        ceiling_mb = baseline_mb + 0.001
        get_config(
            {
                "index_cuda_ceiling_mb": ceiling_mb,
                "index_rss_ceiling_mb": current_rss_mb() + 1024.0,
            }
        )
        _write_code_memory_corpus(tmp_path)

        with VaultStore(tmp_path, embedding_dim=embedding_model.dimension) as store:
            indexer = CodebaseIndexer(tmp_path, embedding_model, store)
            with pytest.raises(JobError) as stopped:
                indexer.full_index(
                    reporter=NullProgressReporter(),
                    preflight=indexer.preflight_content(),
                )

            assert stopped.value.error_kind is JobErrorKind.CUDA_MEMORY_CEILING
            snapshot = indexer.memory_budget_snapshot
            assert snapshot is not None
            assert "after-dense-forward" in snapshot.label
            assert snapshot.cuda_available
            cuda_ceiling_mb = snapshot.cuda_ceiling_mb
            assert cuda_ceiling_mb is not None
            assert cuda_ceiling_mb == ceiling_mb
            # The captured forward peak is what the ceiling governs; reserved
            # rides above it as a diagnostic the comparison never reads.
            assert snapshot.peak_cuda_allocated_mb > cuda_ceiling_mb
            assert snapshot.peak_cuda_reserved_mb >= snapshot.peak_cuda_allocated_mb
            resilience = _code_resilience(indexer)
            assert resilience.cuda_ceiling_mb == cuda_ceiling_mb
            assert resilience.peak_cuda_allocated_mb == snapshot.peak_cuda_allocated_mb
            assert resilience.peak_cuda_reserved_mb == snapshot.peak_cuda_reserved_mb
            assert store.count_code() == 0
            _assert_code_pipeline_released(indexer)


class TestCodeIndexBlockedStoreDeadline:
    """A blocked real local write cannot retain the index writer authority."""

    @pytest.mark.timeout(30)
    def test_blocked_store_consumer_releases_queue_and_writer_at_deadline(
        self,
        cpu_code_embedding_model: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        from ... import CodebaseIndexer
        from ..._job_errors import JobError, JobErrorKind
        from ...store_runtime import VaultStore

        _configure_cpu_code_index(
            cpu_code_embedding_model.dimension,
            index_no_progress_timeout_seconds=2.0,
        )
        _write_code_memory_corpus(tmp_path, count=8)
        gpu_gate = threading.Lock()

        with VaultStore(
            tmp_path,
            embedding_dim=cpu_code_embedding_model.dimension,
        ) as store:
            store.ensure_code_table()
            indexer = CodebaseIndexer(
                tmp_path,
                cpu_code_embedding_model,
                store,
                options=CodebaseIndexer.Options(
                    gpu_lock=gpu_gate,
                ),
            )
            point_lock = store._collection_locks[store.CODE_TABLE_NAME]
            gpu_gate.acquire()
            point_lock_held = False
            try:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    indexing = executor.submit(
                        indexer.full_index,
                        reporter=NullProgressReporter(),
                        preflight=indexer.preflight_content(),
                    )
                    wait_deadline = time.monotonic() + 5.0
                    while time.monotonic() < wait_deadline:
                        if (
                            indexer.support_measurement.generated_chunks >= 3
                            and indexer._writer_lock.locked()
                        ):
                            break
                        time.sleep(0.01)
                    else:
                        raise AssertionError(
                            "producer did not fill the bounded queue before deadline"
                        )

                    point_lock.acquire()
                    point_lock_held = True
                    gpu_gate.release()

                    # The deadline outcome is the invariant; the generous
                    # result timeout is only a hang-guard, never a race
                    # against machine load.
                    with pytest.raises(JobError) as stopped:
                        indexing.result(timeout=20.0)

                    assert stopped.value.error_kind is JobErrorKind.NO_PROGRESS_TIMEOUT
                    assert store.count_code() == 0
                    _assert_code_pipeline_released(indexer)
            finally:
                if gpu_gate.locked():
                    gpu_gate.release()
                if point_lock_held:
                    point_lock.release()

        _assert_code_pipeline_released(indexer)


class TestDocumentIndexMemoryAndWriteDeadline:
    """Document indexing enforces the same memory and write-liveness account."""

    @pytest.mark.timeout(30)
    def test_document_memory_budget_projects_real_peaks_and_effective_ceilings(
        self,
        cpu_code_embedding_model: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        from ... import DocumentIndexer
        from ...config._settings import get_config
        from ...job_dispatch import _document_resilience
        from ...store_runtime import VaultStore

        _configure_cpu_code_index(
            cpu_code_embedding_model.dimension,
            index_rss_ceiling_mb=4096.0,
        )
        source = tmp_path / "bounded.txt"
        source.write_text("alpha beta document memory", encoding="utf-8")
        policy = _document_policy("bounded.txt")

        with VaultStore(
            tmp_path,
            embedding_dim=cpu_code_embedding_model.dimension,
        ) as store:
            indexer = DocumentIndexer(
                tmp_path,
                cpu_code_embedding_model,
                store,
                content_policy=policy,
            )
            result = indexer.full_index(
                reporter=NullProgressReporter(),
                preflight=indexer.preflight_content(),
            )

            assert result.total > 0
            snapshot = indexer.memory_budget_snapshot
            assert snapshot is not None
            assert snapshot.peak_rss_mb > 0.0
            assert snapshot.rss_ceiling_mb == min(
                4096.0,
                indexer._support_limits().rss_bytes / 1024**2,
            )
            resilience = _document_resilience(indexer)
            assert resilience.peak_rss_mb == snapshot.peak_rss_mb
            assert resilience.peak_cuda_allocated_mb == 0.0
            assert resilience.peak_cuda_reserved_mb == 0.0
            assert resilience.rss_ceiling_mb == snapshot.rss_ceiling_mb
            assert resilience.support_profile == get_config().index_support_profile

    @pytest.mark.timeout(30)
    def test_low_document_rss_ceiling_is_typed_and_canonical(
        self,
        cpu_code_embedding_model: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        from ... import DocumentIndexer
        from ..._job_errors import JobError, JobErrorKind
        from ...job_dispatch import _document_resilience
        from ...store_runtime import VaultStore

        _configure_cpu_code_index(
            cpu_code_embedding_model.dimension,
            index_rss_ceiling_mb=1.0,
        )
        source = tmp_path / "limited.txt"
        source.write_text("alpha beta document ceiling", encoding="utf-8")
        policy = _document_policy("limited.txt")

        with VaultStore(
            tmp_path,
            embedding_dim=cpu_code_embedding_model.dimension,
        ) as store:
            indexer = DocumentIndexer(
                tmp_path,
                cpu_code_embedding_model,
                store,
                content_policy=policy,
            )
            with pytest.raises(JobError) as stopped:
                indexer.full_index(
                    reporter=NullProgressReporter(),
                    preflight=indexer.preflight_content(),
                )

            assert stopped.value.error_kind is JobErrorKind.RSS_MEMORY_CEILING
            snapshot = indexer.memory_budget_snapshot
            assert snapshot is not None
            assert snapshot.peak_rss_mb > 1.0
            resilience = _document_resilience(indexer)
            assert resilience.peak_rss_mb == snapshot.peak_rss_mb
            assert resilience.rss_ceiling_mb == snapshot.rss_ceiling_mb == 1.0
            assert resilience.terminal_outcome == "failed"
            assert store.count_document() == 0

    @pytest.mark.timeout(30)
    def test_blocked_document_write_polls_cancel_and_releases_writer(
        self,
        cpu_code_embedding_model: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        from ... import DocumentIndexer
        from ...job_control import CancelRequested, RunControlToken
        from ...store_runtime import VaultStore

        _configure_cpu_code_index(
            cpu_code_embedding_model.dimension,
            index_no_progress_timeout_seconds=10.0,
        )
        source = tmp_path / "cancelled.txt"
        source.write_text("alpha beta blocked document write", encoding="utf-8")
        policy = _document_policy("cancelled.txt")
        control = RunControlToken()

        with VaultStore(
            tmp_path,
            embedding_dim=cpu_code_embedding_model.dimension,
        ) as store:
            store.ensure_document_table()
            indexer = DocumentIndexer(
                tmp_path,
                cpu_code_embedding_model,
                store,
                content_policy=policy,
            )
            point_lock = store._collection_locks[store.DOCUMENT_TABLE_NAME]
            point_lock.acquire()
            try:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    indexing = executor.submit(
                        indexer.full_index,
                        reporter=NullProgressReporter(),
                        preflight=indexer.preflight_content(),
                        run_control=control,
                    )
                    _wait_for_document_write_lock(indexer)

                    control.request_cancel()
                    # CancelRequested (not the 10s no-progress JobError) is
                    # the invariant that cancellation won the race; the
                    # result timeout is only a hang-guard.
                    with pytest.raises(CancelRequested):
                        indexing.result(timeout=20.0)
            finally:
                point_lock.release()

            assert store.count_document() == 0
            assert indexer._writer_lock.acquire(blocking=False)
            indexer._writer_lock.release()

    @pytest.mark.timeout(30)
    def test_blocked_document_write_expires_at_no_progress_deadline(
        self,
        cpu_code_embedding_model: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        from ... import DocumentIndexer
        from ..._job_errors import JobError, JobErrorKind
        from ...store_runtime import VaultStore

        _configure_cpu_code_index(
            cpu_code_embedding_model.dimension,
            index_no_progress_timeout_seconds=2.0,
        )
        source = tmp_path / "timed-out.txt"
        source.write_text("alpha beta blocked document deadline", encoding="utf-8")
        policy = _document_policy("timed-out.txt")

        with VaultStore(
            tmp_path,
            embedding_dim=cpu_code_embedding_model.dimension,
        ) as store:
            store.ensure_document_table()
            indexer = DocumentIndexer(
                tmp_path,
                cpu_code_embedding_model,
                store,
                content_policy=policy,
            )
            point_lock = store._collection_locks[store.DOCUMENT_TABLE_NAME]
            point_lock.acquire()
            try:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    indexing = executor.submit(
                        indexer.full_index,
                        reporter=NullProgressReporter(),
                        preflight=indexer.preflight_content(),
                    )
                    _wait_for_document_write_lock(indexer)
                    # The typed no-progress outcome is the invariant; the
                    # generous result timeout is only a hang-guard.
                    with pytest.raises(JobError) as stopped:
                        indexing.result(timeout=20.0)
                    assert stopped.value.error_kind is JobErrorKind.NO_PROGRESS_TIMEOUT
            finally:
                point_lock.release()

            assert store.count_document() == 0
            assert indexer._writer_lock.acquire(blocking=False)
            indexer._writer_lock.release()


# ---- Document Preparation Tests ----


class TestDocumentPreparation:
    """Tests for individual document preparation."""

    @pytest.mark.timeout(60)
    def test_prepare_real_document(
        self, rag_components: RagComponentsWithManifest
    ) -> None:
        from vaultspec_core.vaultcore import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
            scan_vault,
        )

        from ... import prepare_document

        root: Path = rag_components["root"]
        docs = list(scan_vault(root))
        assert len(docs) > 0, "Synthetic vault should have documents"

        doc = prepare_document(docs[0], root)
        assert doc is not None
        assert doc.id
        assert doc.path
        assert doc.doc_type in ("adr", "audit", "exec", "plan", "reference", "research")
        assert doc.content

    @pytest.mark.timeout(300)
    def test_prepare_all_documents(
        self, rag_components: RagComponentsWithManifest
    ) -> None:
        from vaultspec_core.vaultcore import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
            scan_vault,
        )

        from ... import prepare_document
        from ...config._settings import get_config

        root: Path = rag_components["root"]
        docs_dir: Path = root / get_config().docs_dir
        prepared = 0
        skipped = 0
        for path in scan_vault(root):
            doc = prepare_document(path, root)
            if doc is not None:
                prepared += 1
                rel = str(path.relative_to(docs_dir)).replace("\\", "/")
                expected_id = rel.rsplit(".", 1)[0] if "." in rel else rel
                assert doc.id == expected_id
            else:
                skipped += 1

        assert prepared > 0, "Should prepare at least some documents"


# ---- Index edge cases ----


class TestIndexEdgeCases:
    """Edge cases for indexing operations."""

    @pytest.mark.timeout(300)
    def test_double_full_index_idempotent(
        self, rag_components_full: RagComponentsWithManifest
    ) -> None:
        """Two full_index() calls should yield the same document count."""
        indexer = rag_components_full["indexer"]
        store = rag_components_full["store"]

        first_count: int = store.count()

        # Run full index again
        result = indexer.full_index(reporter=NullProgressReporter())
        second_count: int = store.count()

        assert first_count == second_count, (
            f"Full index should be idempotent: {first_count} vs {second_count}"
        )
        assert result.total == second_count

    @pytest.mark.timeout(300)
    def test_incremental_after_full_stable(
        self, rag_components_full: RagComponentsWithManifest
    ) -> None:
        """Incremental index after full should report zero changes."""
        indexer = rag_components_full["indexer"]
        result = indexer.incremental_index(reporter=NullProgressReporter())

        assert result.added == 0, f"Expected 0 added, got {result.added}"
        assert result.removed == 0, f"Expected 0 removed, got {result.removed}"
        assert result.total == rag_components_full["index_result"].total

    @pytest.mark.timeout(300)
    def test_full_index_clean_on_empty_corpus_purges_all(
        self,
        embedding_model: EmbeddingModel,
        tmp_path_factory: TempPathFactory,
    ) -> None:
        """A clean full_index on a vault whose every source file has been
        deleted must leave the collection empty. Previously the
        empty-docs early-return silently preserved the old rows.
        """
        from ...indexer import VaultIndexer
        from ...store_runtime import VaultStore
        from ..corpus import build_synthetic_vault

        root: Path = tmp_path_factory.mktemp("full-index-empty-regression")
        manifest = build_synthetic_vault(root, n_docs=6, seed=310)
        store = VaultStore(root)
        try:
            indexer = VaultIndexer(root, embedding_model, store)
            initial = indexer.full_index(
                clean=True,
                reporter=NullProgressReporter(),
            )
            assert initial.added == len(manifest.docs)
            assert store.count() == len(manifest.docs)

            # Delete every indexed .md file, then run a clean full
            # index - the store must end up empty.
            for doc in manifest.docs:
                doc.path.unlink()

            result = indexer.full_index(
                clean=True,
                reporter=NullProgressReporter(),
            )
            assert result.added == 0
            assert result.total == 0
            assert store.count() == 0, (
                "clean=True full_index on an empty vault must purge "
                "every previously-indexed row"
            )
        finally:
            store.close()

    @pytest.mark.timeout(300)
    def test_all_synthetic_docs_have_frontmatter(
        self, rag_components: RagComponentsWithManifest
    ) -> None:
        """All synthetic vault docs should have valid frontmatter (tags + date)."""
        from vaultspec_core.vaultcore import (  # pyright: ignore[reportMissingTypeStubs]
            parse_vault_metadata,
            scan_vault,
        )

        root: Path = rag_components["root"]
        for path in scan_vault(root):
            content = path.read_text(encoding="utf-8")
            metadata, _body = parse_vault_metadata(content)
            assert metadata.tags or metadata.date is not None, (
                f"Synthetic doc {path.name} should have frontmatter"
            )


class TestIncrementalModifyAndDelete:
    """R26-M4: incremental_index detects modified and deleted vault files."""

    @pytest.mark.timeout(300)
    def test_incremental_detects_modified_file(
        self, rag_components_full: RagComponentsWithManifest
    ) -> None:
        """Modifying a file's content triggers an update on incremental re-index."""
        from vaultspec_core.vaultcore import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
            scan_vault,
        )

        indexer = rag_components_full["indexer"]
        root: Path = rag_components_full["root"]

        # Pick the first vault doc
        paths = list(scan_vault(root))
        assert len(paths) > 0
        target = paths[0]
        original_content = target.read_text(encoding="utf-8")

        try:
            # Modify the file
            target.write_text(
                original_content + "\n<!-- test modification -->\n",
                encoding="utf-8",
            )
            result = indexer.incremental_index(reporter=NullProgressReporter())
            assert result.updated >= 1, f"Expected >= 1 updated, got {result.updated}"
        finally:
            # Restore original content
            target.write_text(original_content, encoding="utf-8")
            # Re-index to restore metadata
            indexer.incremental_index(reporter=NullProgressReporter())

    @pytest.mark.timeout(300)
    def test_incremental_detects_deleted_file(
        self, rag_components_full: RagComponentsWithManifest
    ) -> None:
        """Removing a file from disk triggers a removal on incremental re-index."""
        from vaultspec_core.vaultcore import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
            scan_vault,
        )

        indexer = rag_components_full["indexer"]
        root: Path = rag_components_full["root"]
        store = rag_components_full["store"]

        paths = list(scan_vault(root))
        assert len(paths) > 0
        target = paths[0]
        original_content = target.read_text(encoding="utf-8")
        count_before: int = store.count()

        try:
            target.unlink()
            result = indexer.incremental_index(reporter=NullProgressReporter())
            assert result.removed >= 1, f"Expected >= 1 removed, got {result.removed}"
            assert store.count() < count_before
        finally:
            # Restore the file
            target.write_text(original_content, encoding="utf-8")
            # Re-index to restore
            indexer.incremental_index(reporter=NullProgressReporter())


# ---------------------------------------------------------------------------
# A resumed run over a tree that is still being written.
# ---------------------------------------------------------------------------


def _revise_code_memory_corpus(root: Path, count: int, marker: str) -> None:
    """Rewrite every corpus file in place, changing content but not structure.

    Content only: a file that vanished or stopped parsing would fail the run
    for a reason that has nothing to do with drift, and the claim under test is
    specifically that changed content no longer aborts it.
    """
    source = root / "src"
    for ordinal in range(count):
        (source / f"memory_{ordinal:03d}.py").write_text(
            f"def memory_{ordinal:03d}() -> str:\n"
            f'    return "alpha beta gamma index memory'
            f' {marker} {ordinal:03d}"\n',
            encoding="utf-8",
        )


class _CorpusChurn:
    """A real second writer rewriting the tree while an index runs.

    Not a stub for concurrency - it is the condition itself. #262 was observed
    against a tree of roughly 710 files being rewritten by another process, and
    the window this exercises only exists while something else is writing.
    """

    def __init__(self, root: Path, count: int) -> None:
        self._root = root
        self._count = count
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._churn,
            name="corpus-churn",
            daemon=True,
        )
        self.revisions = 0

    def _churn(self) -> None:
        while not self._stop.is_set():
            self.revisions += 1
            _revise_code_memory_corpus(
                self._root,
                self._count,
                f"rev{self.revisions:04d}",
            )
            time.sleep(0.005)

    def __enter__(self) -> _CorpusChurn:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=30)


def _cancel_after_first_code_slice(store: object, token: object) -> None:
    """Cancel only once production storage has published one real slice."""
    from ...job_control import RunControlToken
    from ...store_runtime import VaultStore

    assert isinstance(store, VaultStore)
    assert isinstance(token, RunControlToken)
    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        if store.count_code() > 0:
            assert token.request_cancel()
            return
        time.sleep(0.01)
    raise AssertionError("the code run never published a slice to cancel")


@pytest.mark.timeout(600)
def test_a_resumed_code_run_over_a_moving_tree_completes(
    cpu_code_embedding_model: EmbeddingModel,
    tmp_path: Path,
) -> None:
    """A resumed run whose tree keeps changing finishes instead of aborting.

    The reported defect: a resumed generation carries indexed evidence, a file
    changes between the digest snapshot and the moment its units are recorded,
    and the indexed-path upsert guard fails the entire job. Both preconditions
    are built here for real - an interrupted attempt to resume from, and a
    second process rewriting the tree throughout the run.

    The assertion is deliberately the whole-run outcome rather than a
    particular drift count. Whether any single path lands inside the window is
    a matter of timing, and a test that demanded it would be flaky; a run that
    aborts, however, is the defect, and that cannot happen by timing.
    """
    from ... import CodebaseIndexer
    from ...job_control import CancelRequested, RunControlToken
    from ...store_runtime import VaultStore

    count = 8
    _write_code_memory_corpus(tmp_path, count)
    dimension = cpu_code_embedding_model.dimension
    with VaultStore(tmp_path, embedding_dim=dimension) as store:
        indexer = CodebaseIndexer(tmp_path, cpu_code_embedding_model, store)

        # Interrupt a real attempt so the next one resumes carrying the indexed
        # paths of a generation that never published.
        token = RunControlToken()
        with ThreadPoolExecutor(max_workers=1) as executor:
            canceller = executor.submit(_cancel_after_first_code_slice, store, token)
            with pytest.raises(CancelRequested):
                indexer.full_index(
                    reporter=NullProgressReporter(),
                    preflight=indexer.preflight_content(),
                    run_control=token,
                )
            canceller.result(timeout=60)

        interrupted = indexer.last_checkpoint
        assert interrupted is not None
        assert not interrupted.generation.complete

        # Resume while the tree is actively rewritten underneath the run.
        with _CorpusChurn(tmp_path, count) as churn:
            result = indexer.full_index(
                reporter=NullProgressReporter(),
                preflight=indexer.preflight_content(),
            )
            assert churn.revisions > 0

        # The run reached a real outcome rather than dying on the guard, and it
        # reports its drift accounting either way.
        assert result.total > 0
        assert result.drift is not None
        assert set(result.drift) == {
            "superseded_paths",
            "deferred_paths",
            "collisions_observed",
            "retry_budget",
        }
        _assert_code_pipeline_released(indexer)


@pytest.mark.subprocess_gpu
class TestNoCudaHeadroomRefusedAtAdmission:
    """A ceiling under the resident baseline is refused before any forward."""

    def test_a_ceiling_at_the_baseline_refuses_before_dispatch(
        self,
        clean_config: None,
        embedding_model: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        """Admission refuses, naming the configured ceiling as the cause.

        Enforcement compares peak and ceiling net of the resident baseline, so
        a ceiling pinned AT that baseline leaves exactly zero admissible
        headroom. Every forward would breach it, each reporting a "0.0 MiB
        ceiling" that names neither the baseline that consumed it nor the knob
        that would restore it. Refusing once, up front, replaces all of them.

        Run here rather than beside the ceiling arithmetic because the premise
        is a real resident baseline: the unit module loads no models, so its
        baseline is structurally zero and nothing can be pinned beneath it.
        Pinning the ceiling AT whatever that sample reports needs no assumption
        about how the figure moves afterwards: zero headroom is refused however
        large or small the baseline turns out to be.

        Proven able to fail: returning early from ``_require_cuda_headroom``
        instead of raising lets admission succeed and this fails with DID NOT
        RAISE; restored, it refuses.
        """
        del clean_config
        from ... import CodebaseIndexer
        from ..._job_errors import JobError, JobErrorKind
        from ...config._settings import get_config
        from ...memory_probe import sample_resident_cuda_baseline
        from ...store_runtime import VaultStore

        # Production records the baseline after each shared model finishes
        # loading; the fixture above loaded one, so this is that same call
        # rather than a figure invented here.
        baseline_mb = sample_resident_cuda_baseline()
        assert baseline_mb > 0.0, (
            "premise: the embedding model must be resident on the device"
        )
        get_config({"index_cuda_ceiling_mb": baseline_mb})
        _write_code_memory_corpus(tmp_path)

        with VaultStore(tmp_path, embedding_dim=embedding_model.dimension) as store:
            indexer = CodebaseIndexer(tmp_path, embedding_model, store)
            with pytest.raises(JobError) as refused:
                indexer.full_index(
                    reporter=NullProgressReporter(),
                    preflight=indexer.preflight_content(),
                )

            assert refused.value.error_kind is JobErrorKind.CUDA_MEMORY_CEILING
            assert "at or below" in refused.value.detail
            assert "resident model baseline" in refused.value.detail
            # Refused BEFORE any forward: nothing was encoded or written, and
            # no mid-run slice label appears in the message.
            assert "after-dense-forward" not in refused.value.detail
            assert store.count_code() == 0
