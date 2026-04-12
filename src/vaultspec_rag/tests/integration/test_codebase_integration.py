"""Integration tests for CodebaseIndexer: full/incremental indexing and search."""

from __future__ import annotations

import pytest

from vaultspec_rag.progress import NullProgressReporter

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


@pytest.fixture
def code_project(rag_components, tmp_path):
    """Create a temp project with Python source files and a CodebaseIndexer.

    Yields a dict with code_indexer, store, model, root, and the source dir.
    """
    from vaultspec_rag import CodebaseIndexer, VaultStore

    model = rag_components["model"]

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "sample.py").write_text(SAMPLE_PYTHON, encoding="utf-8")

    store = VaultStore(tmp_path)
    code_indexer = CodebaseIndexer(tmp_path, model, store)

    yield {
        "code_indexer": code_indexer,
        "store": store,
        "model": model,
        "root": tmp_path,
        "src_dir": src_dir,
    }

    store.close()


class TestCodebaseFullIndex:
    """Tests for CodebaseIndexer.full_index with real source files."""

    @pytest.mark.timeout(120)
    def test_full_index_produces_chunks(self, code_project):
        result = code_project["code_indexer"].full_index(
            reporter=NullProgressReporter()
        )
        assert result.added > 0
        assert result.total > 0
        assert result.duration_ms >= 0

    @pytest.mark.timeout(120)
    def test_full_index_chunks_in_store(self, code_project):
        code_project["code_indexer"].full_index(reporter=NullProgressReporter())
        store = code_project["store"]
        assert store.count_code() > 0

    @pytest.mark.timeout(120)
    def test_full_index_idempotent(self, code_project):
        indexer = code_project["code_indexer"]
        store = code_project["store"]

        indexer.full_index(reporter=NullProgressReporter())
        first_count = store.count_code()

        indexer.full_index(reporter=NullProgressReporter())
        second_count = store.count_code()

        assert first_count == second_count


class TestCodebaseIncrementalIndex:
    """Tests for CodebaseIndexer.incremental_index."""

    @pytest.mark.timeout(120)
    def test_incremental_after_full_no_changes(self, code_project):
        indexer = code_project["code_indexer"]
        indexer.full_index(reporter=NullProgressReporter())

        result = indexer.incremental_index(reporter=NullProgressReporter())
        assert result.added == 0
        assert result.removed == 0

    @pytest.mark.timeout(120)
    def test_incremental_detects_new_file(self, code_project):
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
    def test_search_codebase_returns_results(self, code_project):
        from vaultspec_rag import VaultSearcher

        code_project["code_indexer"].full_index(reporter=NullProgressReporter())
        model = code_project["model"]
        store = code_project["store"]
        root = code_project["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search_codebase("calculator add numbers", top_k=5)

        assert len(results) > 0
        assert all(r.source == "codebase" for r in results)

    @pytest.mark.timeout(120)
    def test_search_codebase_with_language_filter(self, code_project):
        from vaultspec_rag import VaultSearcher

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
    def test_search_codebase_finds_calculator_class(self, code_project):
        """Search for 'calculator' returns results with Calculator class content."""
        from vaultspec_rag import VaultSearcher

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
    def test_search_codebase_results_have_line_numbers(self, code_project):
        """Codebase search results must include line_start metadata."""
        from vaultspec_rag import VaultSearcher

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
    def test_search_codebase_snippet_contains_source_code(self, code_project):
        """Snippets should contain actual source code, not empty strings."""
        from vaultspec_rag import VaultSearcher

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
    def test_incremental_detects_modified_file(self, code_project):
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
    def test_incremental_detects_deleted_file(self, code_project):
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
        self, rag_components, tmp_path
    ):
        """Files matching .vaultragignore are not indexed."""
        from vaultspec_rag import CodebaseIndexer, VaultStore

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

            # vendor.py excluded — only app.py chunks should exist
            assert result.added > 0
            all_ids = store.get_all_code_ids()
            paths_indexed = {cid.split(":")[0] for cid in all_ids}
            assert "src/app.py" in paths_indexed
            assert "src/vendor.py" not in paths_indexed
        finally:
            store.close()

    @pytest.mark.timeout(120)
    def test_removing_vaultragignore_includes_previously_excluded(
        self, rag_components, tmp_path
    ):
        """Removing .vaultragignore causes previously excluded files to appear."""
        from vaultspec_rag import CodebaseIndexer, VaultStore

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
        self, rag_components, tmp_path
    ):
        """D1: .vaultragignore negation cannot un-ignore .gitignore entries."""
        from vaultspec_rag import CodebaseIndexer, VaultStore

        model = rag_components["model"]

        (tmp_path / "public.py").write_text(SAMPLE_PYTHON, encoding="utf-8")
        (tmp_path / "secret.py").write_text(SAMPLE_VENDOR, encoding="utf-8")

        # .gitignore excludes secret.py
        (tmp_path / ".gitignore").write_text("secret.py\n", encoding="utf-8")
        # .vaultragignore tries to un-ignore it — must fail
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
    def test_extra_excludes_applied_in_full_index(self, rag_components, tmp_path):
        """CLI --exclude patterns flow through extra_excludes to full_index."""
        from vaultspec_rag import CodebaseIndexer, VaultStore

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
