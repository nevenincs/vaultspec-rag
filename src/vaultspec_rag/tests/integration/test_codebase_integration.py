"""Integration tests for CodebaseIndexer: full/incremental indexing and search."""

from __future__ import annotations

import shutil

import pytest

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
    qdrant_dir = tmp_path / ".qdrant"
    if qdrant_dir.exists():
        shutil.rmtree(qdrant_dir)


class TestCodebaseFullIndex:
    """Tests for CodebaseIndexer.full_index with real source files."""

    @pytest.mark.timeout(120)
    def test_full_index_produces_chunks(self, code_project):
        result = code_project["code_indexer"].full_index()
        assert result.added > 0
        assert result.total > 0
        assert result.duration_ms >= 0

    @pytest.mark.timeout(120)
    def test_full_index_chunks_in_store(self, code_project):
        code_project["code_indexer"].full_index()
        store = code_project["store"]
        assert store.count_code() > 0

    @pytest.mark.timeout(120)
    def test_full_index_idempotent(self, code_project):
        indexer = code_project["code_indexer"]
        store = code_project["store"]

        indexer.full_index()
        first_count = store.count_code()

        indexer.full_index()
        second_count = store.count_code()

        assert first_count == second_count


class TestCodebaseIncrementalIndex:
    """Tests for CodebaseIndexer.incremental_index."""

    @pytest.mark.timeout(120)
    def test_incremental_after_full_no_changes(self, code_project):
        indexer = code_project["code_indexer"]
        indexer.full_index()

        result = indexer.incremental_index()
        assert result.added == 0
        assert result.removed == 0

    @pytest.mark.timeout(120)
    def test_incremental_detects_new_file(self, code_project):
        indexer = code_project["code_indexer"]
        store = code_project["store"]
        src_dir = code_project["src_dir"]

        indexer.full_index()
        count_before = store.count_code()

        (src_dir / "extra.py").write_text(SAMPLE_PYTHON_2, encoding="utf-8")
        result = indexer.incremental_index()

        assert result.added > 0
        assert store.count_code() > count_before


class TestCodebaseSearch:
    """Tests for searching indexed codebase chunks."""

    @pytest.mark.timeout(120)
    def test_search_codebase_returns_results(self, code_project):
        from vaultspec_rag import VaultSearcher

        code_project["code_indexer"].full_index()
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

        code_project["code_indexer"].full_index()
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

        code_project["code_indexer"].full_index()
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

        code_project["code_indexer"].full_index()
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

        code_project["code_indexer"].full_index()
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

        indexer.full_index()
        original = sample.read_text(encoding="utf-8")

        try:
            sample.write_text(
                original + "\n\ndef new_function():\n    return 42\n",
                encoding="utf-8",
            )
            result = indexer.incremental_index()
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
        indexer.full_index()
        count_before = store.count_code()
        assert count_before > 0

        # Delete the extra file and re-index incrementally
        extra.unlink()
        result = indexer.incremental_index()
        assert result.removed >= 1, f"Expected removed >= 1, got {result.removed}"
        assert store.count_code() < count_before


SAMPLE_VAULT_MD = """\
---
date: 2026-01-15
tags:
  - "#architecture"
  - "#testing"
feature: calculator
---
# Calculator Architecture

The calculator module provides basic arithmetic operations.
It supports addition and multiplication through a class-based interface.
"""


@pytest.fixture
def mixed_project(rag_components, tmp_path):
    """Project with both vault docs and source code for search_all tests."""
    from vaultspec_rag import (
        CodebaseIndexer,
        VaultDocument,
        VaultStore,
    )

    model = rag_components["model"]

    # Create source code
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "sample.py").write_text(SAMPLE_PYTHON, encoding="utf-8")

    # Create a vault doc
    vault_dir = tmp_path / ".vault" / "adr"
    vault_dir.mkdir(parents=True)
    (vault_dir / "calculator-architecture.md").write_text(
        SAMPLE_VAULT_MD,
        encoding="utf-8",
    )

    store = VaultStore(tmp_path)

    # Index code
    code_indexer = CodebaseIndexer(tmp_path, model, store)
    code_indexer.full_index()

    # Index the vault doc manually (no VaultIndexer scan needed)
    doc_text = (
        "Calculator Architecture\n\n"
        + SAMPLE_VAULT_MD.rsplit("---", maxsplit=1)[-1].strip()
    )
    vectors = model.encode_documents([doc_text])
    sparse = model.encode_documents_sparse([doc_text])
    vault_doc = VaultDocument(
        id="adr/calculator-architecture",
        path=".vault/adr/calculator-architecture.md",
        doc_type="adr",
        feature="calculator",
        date="2026-01-15",
        tags=["#architecture", "#testing"],
        related=[],
        title="Calculator Architecture",
        content=doc_text,
        vector=vectors[0].tolist(),
        sparse_indices=list(sparse[0].indices),
        sparse_values=list(sparse[0].values),
    )
    store.ensure_table()
    store.upsert_documents([vault_doc])

    yield {
        "store": store,
        "model": model,
        "root": tmp_path,
    }

    store.close()
    qdrant_dir = tmp_path / ".qdrant"
    if qdrant_dir.exists():
        shutil.rmtree(qdrant_dir)


class TestCodebaseSearchNexus:
    """Known-answer tests against the real test-project/src/ Nexus codebase.

    These tests verify that CodebaseIndexer correctly indexes the 6 Python
    source files in test-project/src/ and that search returns relevant
    results for Nexus-specific identifiers.
    """

    @pytest.mark.timeout(120)
    def test_finds_nexus_pipeline_executor(self, rag_components_with_code):
        """'NexusPipelineExecutor' should surface executor.py in top results."""
        from vaultspec_rag import VaultSearcher

        searcher = VaultSearcher(
            rag_components_with_code["root"],
            rag_components_with_code["model"],
            rag_components_with_code["store"],
        )
        results = searcher.search_codebase("NexusPipelineExecutor dispatch", top_k=5)

        assert len(results) > 0
        paths = [r.path for r in results]
        assert any("executor" in p for p in paths), (
            f"Expected executor.py in results, got: {paths}"
        )

    @pytest.mark.timeout(120)
    def test_finds_worker_pool(self, rag_components_with_code):
        """'WorkerPool priority queue' should surface worker_pool.py."""
        from vaultspec_rag import VaultSearcher

        searcher = VaultSearcher(
            rag_components_with_code["root"],
            rag_components_with_code["model"],
            rag_components_with_code["store"],
        )
        results = searcher.search_codebase(
            "WorkerPool priority queue scheduler",
            top_k=5,
        )

        assert len(results) > 0
        paths = [r.path for r in results]
        assert any("worker_pool" in p or "scheduler" in p for p in paths), (
            f"Expected worker_pool.py in results, got: {paths}"
        )

    @pytest.mark.timeout(120)
    def test_finds_connector_registry(self, rag_components_with_code):
        """'ConnectorRegistry register handler' should surface registry.py."""
        from vaultspec_rag import VaultSearcher

        searcher = VaultSearcher(
            rag_components_with_code["root"],
            rag_components_with_code["model"],
            rag_components_with_code["store"],
        )
        results = searcher.search_codebase(
            "ConnectorRegistry register handler",
            top_k=5,
        )

        assert len(results) > 0
        paths = [r.path for r in results]
        assert any("registry" in p or "connector" in p for p in paths), (
            f"Expected registry.py in results, got: {paths}"
        )

    @pytest.mark.timeout(120)
    def test_nexus_results_have_python_language(self, rag_components_with_code):
        """All test-project/src/ chunks should be detected as Python."""
        from vaultspec_rag import VaultSearcher

        searcher = VaultSearcher(
            rag_components_with_code["root"],
            rag_components_with_code["model"],
            rag_components_with_code["store"],
        )
        results = searcher.search_codebase("pipeline executor stage", top_k=10)

        assert len(results) > 0
        for r in results:
            assert r.language == "python", (
                f"Expected python, got {r.language} for {r.path}"
            )

    @pytest.mark.timeout(120)
    def test_nexus_snippet_contains_source(self, rag_components_with_code):
        """Snippets from Nexus code chunks should contain actual Python source."""
        from vaultspec_rag import VaultSearcher

        searcher = VaultSearcher(
            rag_components_with_code["root"],
            rag_components_with_code["model"],
            rag_components_with_code["store"],
        )
        results = searcher.search_codebase(
            "execution graph dependency counter",
            top_k=5,
        )

        assert len(results) > 0
        for r in results:
            assert len(r.snippet.strip()) > 0, f"Result {r.id} has empty snippet"
            assert r.line_start is not None and r.line_start >= 1

    @pytest.mark.timeout(120)
    def test_code_count_matches_expected_chunks(self, rag_components_with_code):
        """test-project/src/ has 6 Python files; store should have > 0 code chunks."""
        store = rag_components_with_code["store"]
        count = store.count_code()
        assert count > 0, "Expected code chunks from test-project/src/ to be indexed"
        # 6 files with multiple functions/classes each; expect at least 10 chunks
        assert count >= 10, (
            f"Expected >= 10 code chunks from 6 Nexus source files, got {count}"
        )


class TestSearchAllMixed:
    """search_all() must return results from both vault and codebase."""

    @pytest.mark.timeout(120)
    def test_search_all_returns_both_sources(self, mixed_project):
        """search_all on a project with vault+code returns both sources."""
        from vaultspec_rag import VaultSearcher

        searcher = VaultSearcher(
            mixed_project["root"],
            mixed_project["model"],
            mixed_project["store"],
        )
        results = searcher.search_all("calculator architecture", top_k=10)

        sources = {r.source for r in results}
        assert "vault" in sources, "search_all must include vault results"
        assert "codebase" in sources, "search_all must include codebase results"

    @pytest.mark.timeout(120)
    def test_search_all_scores_normalized(self, mixed_project):
        """search_all scores should be normalized to reasonable bounds."""
        from vaultspec_rag import VaultSearcher

        searcher = VaultSearcher(
            mixed_project["root"],
            mixed_project["model"],
            mixed_project["store"],
        )
        results = searcher.search_all("calculator add multiply", top_k=10)

        assert len(results) > 0
        for r in results:
            assert isinstance(r.score, float)
            assert r.score >= 0.0, f"Negative score: {r.score}"
