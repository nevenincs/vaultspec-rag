"""Tests for VaultIndexer: full/incremental indexing and document preparation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from ...progress import NullProgressReporter
from ..benchmarks.bench_large_index_resilience import (
    CorpusSpec,
    ResourceHighWater,
    measure_full_index,
    prepare_corpus,
)

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import TempPathFactory

    from ...embeddings import EmbeddingModel
    from ..conftest import RagComponentsWithManifest


pytestmark = [pytest.mark.integration]

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
        from ... import CodebaseIndexer, VaultStore

        spec = CorpusSpec(files=2, chunks_per_file=3)
        prepare_corpus(tmp_path, spec)
        store = VaultStore(tmp_path)
        try:
            indexer = CodebaseIndexer(tmp_path, embedding_model, store)
            with caplog.at_level(logging.INFO, logger="vaultspec_rag.store"):
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
        from ... import CodebaseIndexer, VaultStore
        from ...config import get_config
        from ...index_profiles import get_index_support_profile

        def _run(files: int) -> tuple[ResourceHighWater, int]:
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
                return measured.resources, measured.result.total
            finally:
                store.close()

        n_resources, n_chunks = _run(192)
        two_n_resources, two_n_chunks = _run(384)
        assert two_n_chunks == n_chunks * 2

        # The active queue and GPU slice are bounded independently of corpus
        # cardinality. Doubling past the 512-chunk slice boundary may move the
        # allocator to its next block, but cannot retain corpus-proportional
        # process or device memory.
        assert two_n_resources.rss_growth_mb <= n_resources.rss_growth_mb + 512.0
        assert two_n_resources.cuda_allocated_growth_mb <= (
            n_resources.cuda_allocated_growth_mb + 256.0
        )
        assert two_n_resources.cuda_reserved_growth_mb <= (
            n_resources.cuda_reserved_growth_mb + 512.0
        )

        limits = get_index_support_profile(get_config().index_support_profile).code
        mib = 1024**2
        for resources in (n_resources, two_n_resources):
            assert resources.peak_rss_mb * mib <= limits.rss_bytes
            assert resources.peak_cuda_reserved_mb * mib <= limits.cuda_bytes


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
        from ...config import get_config

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
        """Regression guard for F3.10 / F3.11: a clean full_index on a
        vault whose every source file has been deleted must leave the
        collection empty. Previously the empty-docs early-return
        silently preserved the old rows.
        """
        from ...indexer import VaultIndexer
        from ...store import VaultStore
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
