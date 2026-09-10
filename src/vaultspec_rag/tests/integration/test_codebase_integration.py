"""Integration tests for CodebaseIndexer: full/incremental indexing and search."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ...indexer._run_ledger_models import RunAuthority
from ...progress import NullProgressReporter
from .conftest import (
    SAMPLE_PYTHON_2,
    _CodeProject,
)

if TYPE_CHECKING:
    from ..._store_models import CodeChunk

pytestmark = [pytest.mark.integration]


def _stored_partial_chunk(path: str, chunk_id: str) -> CodeChunk:
    """Return one real-store-valid remnant of an interrupted publication."""
    from ..._store_models import CodeChunk
    from ...config._settings import get_config

    return CodeChunk(
        id=chunk_id,
        path=path,
        language="python",
        content="interrupted_publication = True",
        line_start=1,
        line_end=1,
        vector=[0.0] * int(get_config().embedding_dimension),
    )


class TestIncrementalPublicationRecovery:
    """Production incrementals converge remnants left before metadata commit."""

    def test_clean_resume_does_not_drop_confirmed_segments_again(
        self,
        code_project: _CodeProject,
    ) -> None:
        """A rebuild-incomplete generation resumes its confirmed collection."""
        from ..._store_models import generation_code_collection
        from ...indexer import _chunk_worker
        from ...indexer._generation_lifecycle import CodeGenerationOpenRequest
        from ...indexer._run_ledger_models import RunOperation, RunTerminalState
        from ...indexer._slicing import iter_code_file_segments
        from ...indexer._streaming_types import CodeFileSegment, CodeFileSegmentRequest
        from ...job_control import RunControlToken

        indexer = code_project["code_indexer"]
        store = code_project["store"]
        root = code_project["root"]
        source = code_project["src_dir"] / "sample.py"
        preflight = indexer.preflight_content()
        policy = preflight.policy
        limits = indexer._consumer_pipeline.resolve_limits()
        checkpoint = indexer._lifecycle.open_checkpoint(
            CodeGenerationOpenRequest(
                policy=policy,
                operation=RunOperation.FULL,
                clean=True,
                configuration=limits.run_configuration,
                dense_dimensions=limits.dense_dimension,
                sparse_enabled=limits.sparse_enabled,
                run_control=RunControlToken(),
                authority=RunAuthority.REBUILD,
            )
        )

        # A clean rebuild writes into the collection named for its generation
        # and leaves the served one answering reads, so an interrupted attempt
        # is reproduced by seeding the generation collection, not the served
        # one.
        build_target = generation_code_collection(
            store.CODE_TABLE_NAME,
            checkpoint.generation_id,
        )
        store.ensure_code_table()
        store.ensure_code_table(build_target)
        chunked = _chunk_worker.chunk_and_hash_file(source, root)
        segments = tuple(
            iter_code_file_segments(
                CodeFileSegmentRequest(
                    chunks=chunked.chunks,
                    max_chunks=limits.segment_max_chunks,
                    max_bytes=limits.segment_max_bytes,
                    dense_dimension=limits.dense_dimension,
                    sparse_enabled=limits.sparse_enabled,
                    sparse_dimension=limits.sparse_dimension,
                )
            )
        )
        expected_ids: set[str] = set()
        for segment in segments:
            stored_chunks = tuple(
                _stored_partial_chunk(segment.path, chunk.id)
                for chunk in segment.chunks
            )
            store.upsert_code_chunks(
                list(stored_chunks),
                write_policy=None,
                collection=build_target,
            )
            stored_segment = CodeFileSegment(
                path=segment.path,
                ordinal=segment.ordinal,
                chunks=stored_chunks,
                estimated_bytes=segment.estimated_bytes,
                is_file_end=segment.is_file_end,
            )
            checkpoint.record_confirmed_segment(
                stored_segment,
                chunked.content_hash,
            )
            expected_ids.update(chunk.id for chunk in stored_chunks)

        with (
            pytest.raises(RuntimeError, match="interrupted clean attempt"),
            checkpoint.preserve_incomplete_generation(),
        ):
            raise RuntimeError("interrupted clean attempt")
        incomplete = checkpoint.ledger.generation(checkpoint.generation_id)
        assert incomplete.terminal_state is RunTerminalState.REBUILD_INCOMPLETE

        indexer.full_index(
            authority=RunAuthority.REBUILD,
            clean=True,
            reporter=NullProgressReporter(),
            preflight=preflight,
        )

        assert set(store.get_all_code_ids()) == expected_ids
        # Chunk identities are deterministic, so matching ids alone cannot tell
        # a resumed generation from one that re-encoded the whole file into a
        # fresh collection. The seeded marker content can: it survives only
        # where the confirmed points themselves were carried through.
        rows, _ = store.scroll_code_content(
            source_paths={segment.path for segment in segments}
        )
        assert {str(row["payload"]["content"]) for row in rows} == {
            "interrupted_publication = True"
        }
        resumed = checkpoint.ledger.generation(checkpoint.generation_id)
        assert resumed.complete


class TestCodeEmbedFormatRebuild:
    """A pre-header store triggers a one-time clean rebuild."""


class TestCodebaseFullIndex:
    """Tests for CodebaseIndexer.full_index with real source files."""

    @pytest.mark.timeout(120)
    def test_full_index_produces_chunks(self, code_project: _CodeProject) -> None:
        result = code_project["code_indexer"].full_index(
            authority=RunAuthority.REBUILD,
            reporter=NullProgressReporter(),
            preflight=code_project["code_indexer"].preflight_content(),
        )
        assert result.added > 0
        assert result.total > 0
        assert result.duration_ms >= 0

    @pytest.mark.timeout(120)
    def test_full_index_chunks_in_store(self, code_project: _CodeProject) -> None:
        code_project["code_indexer"].full_index(
            authority=RunAuthority.REBUILD,
            reporter=NullProgressReporter(),
            preflight=code_project["code_indexer"].preflight_content(),
        )
        store = code_project["store"]
        assert store.count_code() > 0

    @pytest.mark.timeout(120)
    def test_full_index_idempotent(self, code_project: _CodeProject) -> None:
        indexer = code_project["code_indexer"]
        store = code_project["store"]

        indexer.full_index(
            authority=RunAuthority.REBUILD,
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        first_count = store.count_code()

        indexer.full_index(
            authority=RunAuthority.REBUILD,
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        second_count = store.count_code()

        assert first_count == second_count

    @pytest.mark.timeout(180)
    def test_rebuild_vault_preserves_code_collection(
        self, code_project: _CodeProject
    ) -> None:
        """drop_table on vault must not touch code chunks.

        A whole-directory rmtree on the shared Qdrant path would
        silently destroy the code collection on
        ``--rebuild --type vault``. The scoped-drop path uses
        ``store.drop_table()`` / ``store.drop_code_table()`` so
        each collection is independent.
        """
        from ... import VaultIndexer

        store = code_project["store"]
        model = code_project["model"]
        root = code_project["root"]

        # Seed both collections.
        code_project["code_indexer"].full_index(
            authority=RunAuthority.REBUILD,
            reporter=NullProgressReporter(),
            preflight=code_project["code_indexer"].preflight_content(),
        )
        code_count_before = store.count_code()
        assert code_count_before > 0, "test prelude must produce code chunks"

        vault_indexer = VaultIndexer(root, model, store)
        # Vault may be empty for this fixture; ensure_table still works.
        store.ensure_table()

        # Simulate the scoped rebuild: drop ONLY vault.
        store.drop_table()
        store.ensure_table()
        vault_indexer.full_index(
            clean=True,
            reporter=NullProgressReporter(),
            authority=RunAuthority.REBUILD,
        )

        # Code collection must survive untouched.
        assert store.count_code() == code_count_before, (
            "scoped vault rebuild leaked into the code collection - "
            "the shutil.rmtree regression is back"
        )


class TestCodebaseIncrementalIndex:
    """Tests for CodebaseIndexer.incremental_index."""

    @pytest.mark.timeout(120)
    def test_incremental_after_full_no_changes(
        self, code_project: _CodeProject
    ) -> None:
        indexer = code_project["code_indexer"]
        indexer.full_index(
            authority=RunAuthority.REBUILD,
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )

        result = indexer.incremental_index(
            authority=RunAuthority.PUBLICATION,
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        assert result.added == 0
        assert result.removed == 0

    @pytest.mark.timeout(120)
    def test_incremental_detects_new_file(self, code_project: _CodeProject) -> None:
        indexer = code_project["code_indexer"]
        store = code_project["store"]
        src_dir = code_project["src_dir"]

        indexer.full_index(
            authority=RunAuthority.REBUILD,
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        count_before = store.count_code()

        (src_dir / "extra.py").write_text(SAMPLE_PYTHON_2, encoding="utf-8")
        result = indexer.incremental_index(
            authority=RunAuthority.PUBLICATION,
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )

        assert result.added > 0
        assert store.count_code() > count_before

    def test_an_empty_source_converges_instead_of_failing_the_run(
        self,
        code_project: _CodeProject,
    ) -> None:
        """One file with no content must not abort an indexing job.

        A file caught mid-save reads as zero bytes and yields no chunks. That
        is not a chunking defect - there was nothing to chunk - and treating it
        as one let a single editor save fail an entire run, which is how a
        transient race became a failed generation and, through resume, a
        sustained outage.

        The rejection is stable only against the hash that evidenced it, so a
        mid-save file is classified again once its real content lands while a
        genuinely empty file stays converged. Neither retries forever.
        """
        from ...indexer._content_policy import AdmissionReason
        from ...indexer._file_state import FileStateKind

        indexer = code_project["code_indexer"]
        store = code_project["store"]
        src_dir = code_project["src_dir"]

        (src_dir / "empty_mid_save.py").write_text("", encoding="utf-8")

        result = indexer.full_index(
            authority=RunAuthority.REBUILD,
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )

        # The run completes and the other files are indexed.
        assert store.count_code() > 0
        assert result.added >= 1

        from ...indexer._content_policy import ContentKind
        from ...indexer._run_ledger_models import index_run_ledger_path
        from ...indexer._run_ledger_runtime import RunLedger

        data_root = indexer._data_root
        ledger = RunLedger(index_run_ledger_path(data_root))
        generation = ledger.latest_generation(ContentKind.CODE)
        assert generation is not None
        state = ledger.file_states_for_paths(
            generation.generation_id,
            ("src/empty_mid_save.py",),
        ).get("src/empty_mid_save.py")
        assert state is not None
        assert state.state is FileStateKind.POLICY_REJECTED
        assert state.admission_reason is AdmissionReason.SOURCE_EMPTY
        # Converged, so it neither blocks the run nor demands a retry.
        assert state.converged


class TestCodebaseIncrementalModifyDelete:
    """Incremental indexing detects file modifications and deletions."""

    @pytest.mark.timeout(120)
    def test_incremental_detects_modified_file(
        self, code_project: _CodeProject
    ) -> None:
        """Modifying a source file triggers updated > 0 on incremental re-index."""
        indexer = code_project["code_indexer"]
        src_dir = code_project["src_dir"]
        sample = src_dir / "sample.py"

        indexer.full_index(
            authority=RunAuthority.REBUILD,
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        original = sample.read_text(encoding="utf-8")

        try:
            sample.write_text(
                original + "\n\ndef new_function():\n    return 42\n",
                encoding="utf-8",
            )
            result = indexer.incremental_index(
                authority=RunAuthority.PUBLICATION,
                reporter=NullProgressReporter(),
                preflight=indexer.preflight_content(),
            )
            assert result.updated >= 1 or result.added >= 1, (
                f"Expected updated/added >= 1 after modify, got "
                f"updated={result.updated}, added={result.added}"
            )
        finally:
            sample.write_text(original, encoding="utf-8")

    @pytest.mark.timeout(120)
    def test_incremental_detects_deleted_file(self, code_project: _CodeProject) -> None:
        """Removing a source file triggers removed > 0 on incremental re-index."""
        indexer = code_project["code_indexer"]
        store = code_project["store"]
        src_dir = code_project["src_dir"]

        # Add a second file then index
        extra = src_dir / "extra.py"
        extra.write_text(SAMPLE_PYTHON_2, encoding="utf-8")
        indexer.full_index(
            authority=RunAuthority.REBUILD,
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        count_before = store.count_code()
        assert count_before > 0

        # Delete the extra file and re-index incrementally
        extra.unlink()
        result = indexer.incremental_index(
            authority=RunAuthority.PUBLICATION,
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        assert result.removed >= 1, f"Expected removed >= 1, got {result.removed}"
        assert store.count_code() < count_before
