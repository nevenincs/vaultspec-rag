"""Integration tests for CodebaseIndexer: full/incremental indexing and search."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

import pytest

from ...progress import NullProgressReporter

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ...embeddings import EmbeddingModel
    from ...indexer import CodebaseIndexer
    from ...store import VaultStore
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


class TestCodebaseFullIndex:
    """Tests for CodebaseIndexer.full_index with real source files."""

    @pytest.mark.timeout(120)
    def test_full_index_produces_chunks(self, code_project: _CodeProject) -> None:
        result = code_project["code_indexer"].full_index(
            reporter=NullProgressReporter()
        )
        assert result.added > 0
        assert result.total > 0
        assert result.duration_ms >= 0

    @pytest.mark.timeout(120)
    def test_full_index_chunks_in_store(self, code_project: _CodeProject) -> None:
        code_project["code_indexer"].full_index(reporter=NullProgressReporter())
        store = code_project["store"]
        assert store.count_code() > 0

    @pytest.mark.timeout(120)
    def test_full_index_idempotent(self, code_project: _CodeProject) -> None:
        indexer = code_project["code_indexer"]
        store = code_project["store"]

        indexer.full_index(reporter=NullProgressReporter())
        first_count = store.count_code()

        indexer.full_index(reporter=NullProgressReporter())
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
        code_project["code_indexer"].full_index(reporter=NullProgressReporter())
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
        indexer.full_index(reporter=NullProgressReporter())

        result = indexer.incremental_index(reporter=NullProgressReporter())
        assert result.added == 0
        assert result.removed == 0

    @pytest.mark.timeout(120)
    def test_incremental_detects_new_file(self, code_project: _CodeProject) -> None:
        indexer = code_project["code_indexer"]
        store = code_project["store"]
        src_dir = code_project["src_dir"]

        indexer.full_index(reporter=NullProgressReporter())
        count_before = store.count_code()

        (src_dir / "extra.py").write_text(SAMPLE_PYTHON_2, encoding="utf-8")
        result = indexer.incremental_index(reporter=NullProgressReporter())

        assert result.added > 0
        assert store.count_code() > count_before


class TestCodebaseSearch:
    """Tests for searching indexed codebase chunks."""

    @pytest.mark.timeout(120)
    def test_search_codebase_returns_results(self, code_project: _CodeProject) -> None:
        from ... import VaultSearcher

        code_project["code_indexer"].full_index(reporter=NullProgressReporter())
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
        code_project["code_indexer"].full_index(reporter=NullProgressReporter())

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
        code_project["code_indexer"].full_index(reporter=NullProgressReporter())

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

        code_project["code_indexer"].full_index(reporter=NullProgressReporter())
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

        code_project["code_indexer"].full_index(reporter=NullProgressReporter())
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

        code_project["code_indexer"].full_index(reporter=NullProgressReporter())
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

        code_project["code_indexer"].full_index(reporter=NullProgressReporter())
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

        indexer.full_index(reporter=NullProgressReporter())
        original = sample.read_text(encoding="utf-8")

        try:
            sample.write_text(
                original + "\n\ndef new_function():\n    return 42\n",
                encoding="utf-8",
            )
            result = indexer.incremental_index(reporter=NullProgressReporter())
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
        indexer.full_index(reporter=NullProgressReporter())
        count_before = store.count_code()
        assert count_before > 0

        # Delete the extra file and re-index incrementally
        extra.unlink()
        result = indexer.incremental_index(reporter=NullProgressReporter())
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
            result = indexer.full_index(reporter=NullProgressReporter())

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
            indexer.full_index(reporter=NullProgressReporter())
            ids_before = store.get_all_code_ids()
            paths_before = {cid.split(":")[0] for cid in ids_before}
            assert "src/vendor.py" not in paths_before

            # Remove .vaultragignore and re-index
            ignore_file.unlink()
            indexer2 = CodebaseIndexer(tmp_path, model, store)
            indexer2.full_index(clean=True, reporter=NullProgressReporter())
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
            indexer.full_index(reporter=NullProgressReporter())
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
            indexer.full_index(reporter=NullProgressReporter())
            all_ids = store.get_all_code_ids()
            paths_indexed = {cid.split(":")[0] for cid in all_ids}
            assert "src/app.py" in paths_indexed
            assert "src/temp.py" not in paths_indexed
        finally:
            store.close()
