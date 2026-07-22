"""Integration tests for CodebaseIndexer: full/incremental indexing and search."""

from __future__ import annotations

import hashlib
import os
from typing import TYPE_CHECKING, TypedDict

import pytest

from ...progress import NullProgressReporter

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ...embeddings import EmbeddingModel
    from ...indexer import CodebaseIndexer
    from ...store import CodeChunk, VaultStore
    from ..conftest import RagComponentsWithManifest

pytestmark = [pytest.mark.integration]

SAMPLE_PYTHON = '''\
"""Sample module for testing codebase indexing."""


def hello_world():
    """Print a greeting message."""
    print("Hello, world!")


class Calculator:
    """A simple calculator class."""

    def add(self, a: int, b: int) -> int:
        """Return the sum of two numbers."""
        return a + b

    def multiply(self, a: int, b: int) -> int:
        """Return the product of two numbers."""
        return a * b
'''

SAMPLE_PYTHON_2 = '''\
"""Another module for incremental indexing tests."""


def fibonacci(n: int) -> int:
    """Compute the nth Fibonacci number."""
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)
'''


class _CodeProject(TypedDict):
    code_indexer: CodebaseIndexer
    store: VaultStore
    model: EmbeddingModel
    root: Path
    src_dir: Path


@pytest.fixture
def code_project(
    rag_components: RagComponentsWithManifest,
    tmp_path: Path,
) -> Generator[_CodeProject]:
    """Create a temp project with Python source files and a CodebaseIndexer.

    Yields a dict with code_indexer, store, model, root, and the source dir.
    """
    from ... import CodebaseIndexer, VaultStore

    model = rag_components["model"]

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "sample.py").write_text(SAMPLE_PYTHON, encoding="utf-8")

    store = VaultStore(tmp_path)
    code_indexer = CodebaseIndexer(tmp_path, model, store)

    yield _CodeProject(
        code_indexer=code_indexer,
        store=store,
        model=model,
        root=tmp_path,
        src_dir=src_dir,
    )

    store.close()


def _stored_partial_chunk(path: str, chunk_id: str) -> CodeChunk:
    """Return one real-store-valid remnant of an interrupted publication."""
    from ...config import get_config
    from ...store import CodeChunk

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

    @pytest.mark.timeout(180)
    def test_scoped_new_file_replaces_prior_partial_ids(
        self,
        code_project: _CodeProject,
    ) -> None:
        from ...indexer import _chunk_worker
        from .test_indexer_progress_integration import CountingProgressReporter

        root = code_project["root"]
        store = code_project["store"]
        indexer = code_project["code_indexer"]
        indexer.full_index(
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        rel_path = "src/new_partial.py"
        source = root / rel_path
        source.write_text("def current_value():\n    return 42\n", encoding="utf-8")
        expected = _chunk_worker.chunk_and_hash_file(source, root)
        stale_id = f"{rel_path}:stale-attempt"
        store.upsert_code_chunks(
            [_stored_partial_chunk(rel_path, stale_id)],
            write_policy=None,
        )

        reporter = CountingProgressReporter()
        indexer.incremental_index(
            reporter=reporter,
            changed_paths=[source],
            preflight=indexer.preflight_changed_paths([source]),
        )

        ids = set(store.get_code_ids_by_paths({rel_path}))
        assert ids == {chunk.id for chunk in expected.chunks}
        assert (
            indexer._load_meta()[rel_path]  # pyright: ignore[reportPrivateUsage]
            == expected.content_hash
        )
        assert "scan changed" in reporter.phase_names()
        assert "prepare collection" not in reporter.phase_names()

    @pytest.mark.timeout(180)
    def test_unscoped_new_file_replaces_prior_partial_ids(
        self,
        code_project: _CodeProject,
    ) -> None:
        from ...indexer import _chunk_worker
        from .test_indexer_progress_integration import CountingProgressReporter

        root = code_project["root"]
        store = code_project["store"]
        indexer = code_project["code_indexer"]
        indexer.full_index(
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        rel_path = "src/unscoped_partial.py"
        source = root / rel_path
        source.write_text("unscoped_value = 'current'\n", encoding="utf-8")
        expected = _chunk_worker.chunk_and_hash_file(source, root)
        stale_id = f"{rel_path}:stale-attempt"
        store.upsert_code_chunks(
            [_stored_partial_chunk(rel_path, stale_id)],
            write_policy=None,
        )

        reporter = CountingProgressReporter()
        indexer.incremental_index(
            reporter=reporter,
            preflight=indexer.preflight_content(),
        )

        ids = set(store.get_code_ids_by_paths({rel_path}))
        assert ids == {chunk.id for chunk in expected.chunks}
        assert (
            indexer._load_meta()[rel_path]  # pyright: ignore[reportPrivateUsage]
            == expected.content_hash
        )
        assert "chunk + embed" in reporter.phase_names()
        assert "prepare collection" not in reporter.phase_names()

    @pytest.mark.timeout(180)
    def test_control_preserves_storage_confirmed_generation_points(
        self,
        code_project: _CodeProject,
    ) -> None:
        """Control before finalization leaves checkpointed storage intact."""
        from ...indexer._run_ledger import RunOperation
        from ...indexer._streaming import CodeFileSegment
        from ...job_control import CancelRequested, RunControlToken

        indexer = code_project["code_indexer"]
        store = code_project["store"]
        indexer.full_index(
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )

        rel_path = "src/confirmed_before_control.py"
        point_id = f"{rel_path}:confirmed"
        chunk = _stored_partial_chunk(rel_path, point_id)
        store.upsert_code_chunks([chunk], write_policy=None)
        policy = indexer.resolve_policy_snapshot()
        limits = indexer._resolve_code_pipeline_limits()  # pyright: ignore[reportPrivateUsage]
        checkpoint = indexer._open_run_checkpoint(  # pyright: ignore[reportPrivateUsage]
            policy=policy,
            operation=RunOperation.INCREMENTAL,
            clean=False,
            limits=limits,
            run_control=RunControlToken(),
        )
        digest = hashlib.blake2b(chunk.content.encode("utf-8")).hexdigest()
        segment = CodeFileSegment(
            path=rel_path,
            ordinal=0,
            chunks=(chunk,),
            estimated_bytes=max(1, len(chunk.content.encode("utf-8"))),
            is_file_end=True,
        )
        checkpoint.record_confirmed_segment(segment, digest)

        token = RunControlToken()
        assert token.request_cancel()
        with pytest.raises(CancelRequested):
            indexer._commit_incremental_replacement(  # pyright: ignore[reportPrivateUsage]
                policy=policy,
                existing_ids=set(),
                published_ids={point_id},
                prior_ids_by_path={rel_path: set()},
                deleted_paths=set(),
                checkpoint=checkpoint,
                metadata={rel_path: digest},
                files_count=1,
                protect_replacement=False,
                reporter=NullProgressReporter(),
                run_control=token,
            )

        assert store.get_code_ids_by_paths({rel_path}) == [point_id]
        assert checkpoint.ledger.unit_committed(
            checkpoint.generation_id,
            checkpoint.unit_for(segment, digest),
        )

    @pytest.mark.timeout(180)
    def test_scoped_untracked_disappearance_removes_prior_partial_ids(
        self,
        code_project: _CodeProject,
    ) -> None:
        from .test_indexer_progress_integration import CountingProgressReporter

        root = code_project["root"]
        store = code_project["store"]
        indexer = code_project["code_indexer"]
        indexer.full_index(
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        rel_path = "src/disappeared_partial.py"
        missing = root / rel_path
        stale_id = f"{rel_path}:stale-attempt"
        store.upsert_code_chunks(
            [_stored_partial_chunk(rel_path, stale_id)],
            write_policy=None,
        )

        reporter = CountingProgressReporter()
        result = indexer.incremental_index(
            reporter=reporter,
            changed_paths=[missing],
            preflight=indexer.preflight_changed_paths([missing]),
        )

        assert store.get_code_ids_by_paths({rel_path}) == []
        assert rel_path not in indexer._load_meta()  # pyright: ignore[reportPrivateUsage]
        assert result.removed == 0
        assert "scan changed" in reporter.phase_names()
        assert "prepare collection" not in reporter.phase_names()


class TestCodeEmbedFormatRebuild:
    """A pre-header store triggers a one-time clean rebuild."""

    @pytest.mark.timeout(180)
    def test_missing_embed_marker_triggers_rebuild(
        self, code_project: _CodeProject
    ) -> None:
        import json

        from ...config import get_config

        indexer = code_project["code_indexer"]
        store = code_project["store"]
        indexer.full_index(
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        chunk_total = store.count_code()
        assert chunk_total > 0

        cfg = get_config()
        meta_path = code_project["root"] / cfg.data_dir / cfg.code_index_metadata_file
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta.pop("__code_embed_schema__")
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

        result = indexer.incremental_index(
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        # A rebuild re-embeds everything instead of a no-op pass.
        assert result.added == chunk_total
        stamped = json.loads(meta_path.read_text(encoding="utf-8"))
        assert stamped["__code_embed_schema__"] == "2"


class TestCodebaseFullIndex:
    """Tests for CodebaseIndexer.full_index with real source files."""

    @pytest.mark.timeout(120)
    def test_full_index_produces_chunks(self, code_project: _CodeProject) -> None:
        result = code_project["code_indexer"].full_index(
            reporter=NullProgressReporter(),
            preflight=code_project["code_indexer"].preflight_content(),
        )
        assert result.added > 0
        assert result.total > 0
        assert result.duration_ms >= 0

    @pytest.mark.timeout(120)
    def test_full_index_chunks_in_store(self, code_project: _CodeProject) -> None:
        code_project["code_indexer"].full_index(
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
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        first_count = store.count_code()

        indexer.full_index(
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
        vault_indexer.full_index(clean=True, reporter=NullProgressReporter())

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
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )

        result = indexer.incremental_index(
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
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        count_before = store.count_code()

        (src_dir / "extra.py").write_text(SAMPLE_PYTHON_2, encoding="utf-8")
        result = indexer.incremental_index(
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )

        assert result.added > 0
        assert store.count_code() > count_before

    @pytest.mark.timeout(180)
    @pytest.mark.parametrize("scoped", [False, True], ids=["unscoped", "scoped"])
    def test_incremental_uses_weighted_segments(
        self,
        code_project: _CodeProject,
        scoped: bool,
    ) -> None:
        from ...config import EnvVar, reset_config
        from ...indexer import _chunk_worker
        from .test_indexer_progress_integration import CountingProgressReporter

        indexer = code_project["code_indexer"]
        store = code_project["store"]
        root = code_project["root"]
        source = code_project["src_dir"] / "many_units.py"
        indexer.full_index(
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        source.write_text(
            "\n\n".join(
                (
                    f"def unit_{index}() -> str:\n"
                    f'    payload = "{str(index) * 900}"\n'
                    "    return payload"
                )
                for index in range(6)
            )
            + "\n",
            encoding="utf-8",
        )
        expected = _chunk_worker.chunk_and_hash_file(source, root)
        expected_ids = {chunk.id for chunk in expected.chunks}
        assert len(expected_ids) > 2

        overrides = {
            EnvVar.INDEX_SEGMENT_MAX_CHUNKS.value: "1",
            EnvVar.INDEX_QUEUE_MAX_CHUNKS.value: "2",
            EnvVar.INDEX_CHUNK_WORKERS.value: "1",
        }
        previous = {key: os.environ.get(key) for key in overrides}
        try:
            os.environ.update(overrides)
            reset_config()
            reporter = CountingProgressReporter()
            result = indexer.incremental_index(
                reporter=reporter,
                changed_paths=[source] if scoped else None,
                preflight=(
                    indexer.preflight_changed_paths([source])
                    if scoped
                    else indexer.preflight_content()
                ),
            )
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            reset_config()

        rel_path = "src/many_units.py"
        assert result.added == 1
        assert set(store.get_code_ids_by_paths({rel_path})) == expected_ids
        assert (
            indexer._load_meta()[rel_path]  # pyright: ignore[reportPrivateUsage]
            == expected.content_hash
        )
        assert "chunk + embed" in reporter.phase_names()
        assert "chunk files" not in reporter.phase_names()
        assert "embed + upsert chunks" not in reporter.phase_names()

    @pytest.mark.timeout(240)
    @pytest.mark.parametrize("scoped", [False, True], ids=["unscoped", "scoped"])
    def test_incremental_rolls_back_then_retries_real_failure(
        self,
        code_project: _CodeProject,
        scoped: bool,
    ) -> None:
        import hashlib
        import shlex
        import sys
        import textwrap

        from ...config import EnvVar, reset_config
        from ...indexer._preprocess_runner import PreprocessAbortError
        from .test_indexer_progress_integration import (
            CountingProgressReporter,
            _assert_phase_balanced,
        )

        indexer = code_project["code_indexer"]
        store = code_project["store"]
        root = code_project["root"]
        src_dir = code_project["src_dir"]
        script = root / "conditional_preprocessor.py"
        script.write_text(
            textwrap.dedent(
                """
                import json
                import pathlib
                import sys
                import time

                source = pathlib.Path(sys.argv[1])
                content = source.read_text(encoding="utf-8")
                if "FAIL" in content:
                    time.sleep(1.0)
                    sys.exit(7)
                print(json.dumps({
                    "schema_version": 1,
                    "preprocessor_id": "conditional",
                    "preprocessor_version": "1",
                    "source_path": str(source),
                    "text": "successful conditional extraction",
                }))
                """
            ),
            encoding="utf-8",
        )
        command = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} {{path}}"
        (root / ".vaultragpreprocess.toml").write_text(
            "version = 2\n"
            "[[rule]]\n"
            'pattern = "*.fatal"\n'
            'target = "code"\n'
            'extractor_version = "1"\n'
            f"command = '''{command}'''\n"
            'on_error = "fail"\n',
            encoding="utf-8",
        )
        indexer.full_index(
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        metadata_before = indexer._load_meta()  # pyright: ignore[reportPrivateUsage]

        good = src_dir / "a_good.py"
        failing = src_dir / "z_fail.fatal"
        good.write_text(
            "def stored_before_failure():\n    return True\n", encoding="utf-8"
        )
        failing.write_text("FAIL\n", encoding="utf-8")
        attempted = {"src/a_good.py", "src/z_fail.fatal"}

        overrides = {
            EnvVar.INDEX_SEGMENT_MAX_CHUNKS.value: "1",
            EnvVar.INDEX_QUEUE_MAX_CHUNKS.value: "2",
            EnvVar.INDEX_CHUNK_WORKERS.value: "1",
        }
        previous = {key: os.environ.get(key) for key in overrides}
        try:
            os.environ.update(overrides)
            reset_config()
            failure_reporter = CountingProgressReporter()
            with pytest.raises(PreprocessAbortError):
                indexer.incremental_index(
                    reporter=failure_reporter,
                    changed_paths=[good, failing] if scoped else None,
                    preflight=(
                        indexer.preflight_changed_paths([good, failing])
                        if scoped
                        else indexer.preflight_content()
                    ),
                )

            _assert_phase_balanced(failure_reporter.events)
            assert "chunk + embed" in failure_reporter.phase_names()
            assert store.get_code_ids_by_paths(attempted) == []
            assert (
                indexer._load_meta()  # pyright: ignore[reportPrivateUsage]
                == metadata_before
            )

            failing.write_text("SUCCEED\n", encoding="utf-8")
            retry_reporter = CountingProgressReporter()
            result = indexer.incremental_index(
                reporter=retry_reporter,
                changed_paths=[good, failing] if scoped else None,
                preflight=(
                    indexer.preflight_changed_paths([good, failing])
                    if scoped
                    else indexer.preflight_content()
                ),
            )
            _assert_phase_balanced(retry_reporter.events)
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            reset_config()

        assert result.added == 2
        assert store.get_code_ids_by_paths(attempted)
        metadata_after = indexer._load_meta()  # pyright: ignore[reportPrivateUsage]
        assert (
            metadata_after["src/a_good.py"]
            == hashlib.blake2b(good.read_bytes()).hexdigest()
        )
        assert (
            metadata_after["src/z_fail.fatal"]
            == hashlib.blake2b(failing.read_bytes()).hexdigest()
        )
        assert "delete removed" in retry_reporter.phase_names()
        assert "write metadata" in retry_reporter.phase_names()


class TestCodebaseSearch:
    """Tests for searching indexed codebase chunks."""

    @pytest.mark.timeout(120)
    def test_search_codebase_returns_results(self, code_project: _CodeProject) -> None:
        from ... import VaultSearcher

        code_project["code_indexer"].full_index(
            reporter=NullProgressReporter(),
            preflight=code_project["code_indexer"].preflight_content(),
        )
        model = code_project["model"]
        store = code_project["store"]
        root = code_project["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search_codebase("calculator add numbers", top_k=5)

        assert len(results) > 0
        assert all(r.source == "codebase" for r in results)

    @pytest.mark.timeout(120)
    def test_search_codebase_exclude_path_glob(
        self, code_project: _CodeProject
    ) -> None:
        """--exclude-path drops matching files post-query."""
        from ... import VaultSearcher

        # Add a second file under tests/ that would otherwise rank high
        # for the query, so we can prove exclude really prunes.
        tests_dir = code_project["src_dir"].parent / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_sample.py").write_text(SAMPLE_PYTHON, encoding="utf-8")
        code_project["code_indexer"].full_index(
            reporter=NullProgressReporter(),
            preflight=code_project["code_indexer"].preflight_content(),
        )

        searcher = VaultSearcher(
            code_project["root"],
            code_project["model"],
            code_project["store"],
        )

        # Without exclude: tests/ paths should appear in the candidate set.
        unfiltered = searcher.search_codebase("calculator add", top_k=10)
        unfiltered_paths = {r.path for r in unfiltered}
        assert any(p.startswith("tests/") for p in unfiltered_paths), (
            f"Expected a tests/ hit in the unfiltered set, got: {unfiltered_paths}"
        )

        # With exclude: every tests/ path must be gone.
        filtered = searcher.search_codebase(
            "calculator add",
            top_k=10,
            exclude_paths=["tests/**"],
        )
        filtered_paths = {r.path for r in filtered}
        assert not any(p.startswith("tests/") for p in filtered_paths), (
            f"tests/ paths leaked past --exclude-path: {filtered_paths}"
        )

    @pytest.mark.timeout(120)
    def test_search_codebase_include_path_glob(
        self, code_project: _CodeProject
    ) -> None:
        """--include-path keeps only matching files post-query."""
        from ... import VaultSearcher

        tests_dir = code_project["src_dir"].parent / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_sample.py").write_text(SAMPLE_PYTHON, encoding="utf-8")
        code_project["code_indexer"].full_index(
            reporter=NullProgressReporter(),
            preflight=code_project["code_indexer"].preflight_content(),
        )

        searcher = VaultSearcher(
            code_project["root"],
            code_project["model"],
            code_project["store"],
        )

        results = searcher.search_codebase(
            "calculator",
            top_k=10,
            include_paths=["src/**"],
        )
        paths = {r.path for r in results}
        # Every survivor must start with src/.
        for p in paths:
            assert p.startswith("src/"), (
                f"include_paths=['src/**'] kept non-src/ path: {p}"
            )

    @pytest.mark.timeout(120)
    def test_search_codebase_with_language_filter(
        self, code_project: _CodeProject
    ) -> None:
        from ... import VaultSearcher

        code_project["code_indexer"].full_index(
            reporter=NullProgressReporter(),
            preflight=code_project["code_indexer"].preflight_content(),
        )
        model = code_project["model"]
        store = code_project["store"]
        root = code_project["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search_codebase(
            "hello world",
            top_k=5,
            language="python",
        )

        assert isinstance(results, list)
        for r in results:
            assert r.language == "python"

    @pytest.mark.timeout(120)
    def test_search_codebase_finds_calculator_class(
        self, code_project: _CodeProject
    ) -> None:
        """Search for 'calculator' returns results with Calculator class content."""
        from ... import VaultSearcher

        code_project["code_indexer"].full_index(
            reporter=NullProgressReporter(),
            preflight=code_project["code_indexer"].preflight_content(),
        )
        searcher = VaultSearcher(
            code_project["root"],
            code_project["model"],
            code_project["store"],
        )
        results = searcher.search_codebase("calculator add multiply", top_k=5)

        assert len(results) > 0
        snippets = " ".join(r.snippet for r in results).lower()
        assert "calculator" in snippets or "add" in snippets, (
            f"Expected 'calculator' or 'add' in snippets, got: {snippets[:300]}"
        )

    @pytest.mark.timeout(120)
    def test_search_codebase_results_have_line_numbers(
        self, code_project: _CodeProject
    ) -> None:
        """Codebase search results must include line_start metadata."""
        from ... import VaultSearcher

        code_project["code_indexer"].full_index(
            reporter=NullProgressReporter(),
            preflight=code_project["code_indexer"].preflight_content(),
        )
        searcher = VaultSearcher(
            code_project["root"],
            code_project["model"],
            code_project["store"],
        )
        results = searcher.search_codebase("function definition", top_k=5)

        assert len(results) > 0
        for r in results:
            assert r.line_start is not None, f"Result {r.id} missing line_start"
            assert r.line_start >= 1

    @pytest.mark.timeout(120)
    def test_search_codebase_snippet_contains_source_code(
        self, code_project: _CodeProject
    ) -> None:
        """Snippets should contain actual source code, not empty strings."""
        from ... import VaultSearcher

        code_project["code_indexer"].full_index(
            reporter=NullProgressReporter(),
            preflight=code_project["code_indexer"].preflight_content(),
        )
        searcher = VaultSearcher(
            code_project["root"],
            code_project["model"],
            code_project["store"],
        )
        results = searcher.search_codebase("hello world greeting", top_k=5)

        assert len(results) > 0
        for r in results:
            assert len(r.snippet.strip()) > 0, f"Result {r.id} has empty snippet"
            assert r.path.endswith(".py"), f"Expected .py path, got {r.path}"


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
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        count_before = store.count_code()
        assert count_before > 0

        # Delete the extra file and re-index incrementally
        extra.unlink()
        result = indexer.incremental_index(
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        assert result.removed >= 1, f"Expected removed >= 1, got {result.removed}"
        assert store.count_code() < count_before


SAMPLE_VENDOR = '''\
"""Vendored library that should be excluded from indexing."""


def vendor_helper():
    """Do vendor things."""
    return "vendor"
'''


class TestVaultragignore:
    """Integration tests for .vaultragignore exclusion (D1 two-spec OR).

    These verify the full pipeline: .vaultragignore file on disk ->
    _scan_codebase() -> full_index() -> chunks in Qdrant, using real
    GPU embeddings and real Qdrant storage.
    """

    @pytest.mark.timeout(120)
    def test_vaultragignore_excludes_file_from_full_index(
        self, rag_components: RagComponentsWithManifest, tmp_path: Path
    ) -> None:
        """Files matching .vaultragignore are not indexed."""
        from ... import CodebaseIndexer, VaultStore

        model = rag_components["model"]

        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "app.py").write_text(SAMPLE_PYTHON, encoding="utf-8")
        (src_dir / "vendor.py").write_text(SAMPLE_VENDOR, encoding="utf-8")

        # Exclude vendor.py via .vaultragignore
        (tmp_path / ".vaultragignore").write_text("src/vendor.py\n", encoding="utf-8")

        store = VaultStore(tmp_path)
        try:
            indexer = CodebaseIndexer(tmp_path, model, store)
            result = indexer.full_index(
                reporter=NullProgressReporter(),
                preflight=indexer.preflight_content(),
            )

            # vendor.py excluded - only app.py chunks should exist
            assert result.added > 0
            all_ids = store.get_all_code_ids()
            paths_indexed = {cid.split(":")[0] for cid in all_ids}
            assert "src/app.py" in paths_indexed
            assert "src/vendor.py" not in paths_indexed
        finally:
            store.close()

    @pytest.mark.timeout(120)
    def test_removing_vaultragignore_includes_previously_excluded(
        self, rag_components: RagComponentsWithManifest, tmp_path: Path
    ) -> None:
        """Removing .vaultragignore causes previously excluded files to appear."""
        from ... import CodebaseIndexer, VaultStore

        model = rag_components["model"]

        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "app.py").write_text(SAMPLE_PYTHON, encoding="utf-8")
        (src_dir / "vendor.py").write_text(SAMPLE_VENDOR, encoding="utf-8")

        ignore_file = tmp_path / ".vaultragignore"
        ignore_file.write_text("src/vendor.py\n", encoding="utf-8")

        store = VaultStore(tmp_path)
        try:
            indexer = CodebaseIndexer(tmp_path, model, store)
            indexer.full_index(
                reporter=NullProgressReporter(),
                preflight=indexer.preflight_content(),
            )
            ids_before = store.get_all_code_ids()
            paths_before = {cid.split(":")[0] for cid in ids_before}
            assert "src/vendor.py" not in paths_before

            # Remove .vaultragignore and re-index
            ignore_file.unlink()
            indexer2 = CodebaseIndexer(tmp_path, model, store)
            indexer2.full_index(
                clean=True,
                reporter=NullProgressReporter(),
                preflight=indexer2.preflight_content(),
            )
            ids_after = store.get_all_code_ids()
            paths_after = {cid.split(":")[0] for cid in ids_after}
            assert "src/vendor.py" in paths_after
            assert "src/app.py" in paths_after
        finally:
            store.close()

    @pytest.mark.timeout(120)
    def test_vaultragignore_negation_cannot_override_gitignore(
        self, rag_components: RagComponentsWithManifest, tmp_path: Path
    ) -> None:
        """D1: .vaultragignore negation cannot un-ignore .gitignore entries."""
        from ... import CodebaseIndexer, VaultStore

        model = rag_components["model"]

        (tmp_path / "public.py").write_text(SAMPLE_PYTHON, encoding="utf-8")
        (tmp_path / "secret.py").write_text(SAMPLE_VENDOR, encoding="utf-8")

        # .gitignore excludes secret.py
        (tmp_path / ".gitignore").write_text("secret.py\n", encoding="utf-8")
        # .vaultragignore tries to un-ignore it - must fail
        (tmp_path / ".vaultragignore").write_text("!secret.py\n", encoding="utf-8")

        store = VaultStore(tmp_path)
        try:
            indexer = CodebaseIndexer(tmp_path, model, store)
            indexer.full_index(
                reporter=NullProgressReporter(),
                preflight=indexer.preflight_content(),
            )
            all_ids = store.get_all_code_ids()
            paths_indexed = {cid.split(":")[0] for cid in all_ids}
            assert "public.py" in paths_indexed
            assert "secret.py" not in paths_indexed, (
                ".vaultragignore negation must not override .gitignore"
            )
        finally:
            store.close()

    @pytest.mark.timeout(120)
    def test_extra_excludes_applied_in_full_index(
        self, rag_components: RagComponentsWithManifest, tmp_path: Path
    ) -> None:
        """CLI --exclude patterns flow through extra_excludes to full_index."""
        from ... import CodebaseIndexer, VaultStore

        model = rag_components["model"]

        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "app.py").write_text(SAMPLE_PYTHON, encoding="utf-8")
        (src_dir / "temp.py").write_text(SAMPLE_VENDOR, encoding="utf-8")

        store = VaultStore(tmp_path)
        try:
            indexer = CodebaseIndexer(
                tmp_path, model, store, extra_excludes=["src/temp.py"]
            )
            indexer.full_index(
                reporter=NullProgressReporter(),
                preflight=indexer.preflight_content(),
            )
            all_ids = store.get_all_code_ids()
            paths_indexed = {cid.split(":")[0] for cid in all_ids}
            assert "src/app.py" in paths_indexed
            assert "src/temp.py" not in paths_indexed
        finally:
            store.close()
