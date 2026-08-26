"""test codebase integration: the search half."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ...progress import NullProgressReporter
from .conftest import (
    SAMPLE_PYTHON,
    SAMPLE_VENDOR,
    _CodeProject,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ..conftest import RagComponentsWithManifest

pytestmark = [pytest.mark.integration]


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

        searcher = VaultSearcher(root, model, store, reranker=code_project["reranker"])
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
            reranker=code_project["reranker"],
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
            reranker=code_project["reranker"],
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
    def test_search_codebase_include_path_without_a_glob_selects_the_subtree(
        self, code_project: _CodeProject
    ) -> None:
        """A plain --include-path names a location, not one literal path.

        This is the form an operator types. A directory is never itself an
        indexed path, so matching it literally returned nothing at all while
        reading as a working narrow.
        """
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
            reranker=code_project["reranker"],
        )

        results = searcher.search_codebase(
            "calculator",
            top_k=10,
            include_paths=["src"],
        )
        paths = {r.path for r in results}
        # Drop the subtree expansion from expand_path_pattern and this is empty.
        assert paths, "include_paths=['src'] matched nothing under src/"
        for p in paths:
            assert p.startswith("src/"), f"include_paths=['src'] kept {p}"

    @pytest.mark.timeout(120)
    def test_search_codebase_inline_path_token_narrows_by_location(
        self, code_project: _CodeProject
    ) -> None:
        """``path:`` in the query narrows the same way --include-path does.

        Routed to the exact-path store filter, the token pushed a directory
        into a keyword equality match no indexed path can satisfy, so the
        search returned nothing and reported a plain no-match.
        """
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
            reranker=code_project["reranker"],
        )

        results = searcher.search_codebase("calculator path:src/", top_k=10)
        paths = {r.path for r in results}
        assert paths, "path:src/ matched nothing under src/"
        for p in paths:
            assert p.startswith("src/"), f"path:src/ kept {p}"

    @pytest.mark.timeout(120)
    def test_a_path_filter_that_excludes_everything_is_reported(
        self, code_project: _CodeProject
    ) -> None:
        """An emptied page must carry the evidence that the filter emptied it.

        Nothing else distinguishes it from a query that matched nothing, and
        the adapters render the difference to the operator.
        """
        from ... import VaultSearcher

        code_project["code_indexer"].full_index(
            reporter=NullProgressReporter(),
            preflight=code_project["code_indexer"].preflight_content(),
        )

        searcher = VaultSearcher(
            code_project["root"],
            code_project["model"],
            code_project["store"],
            reranker=code_project["reranker"],
        )

        notes: dict[str, object] = {}
        results = searcher.search_codebase(
            "calculator",
            top_k=10,
            include_paths=["does/not/exist"],
            notes=notes,
        )

        assert not results
        recorded = notes["path_filter"]
        assert isinstance(recorded, dict)
        detail = cast("dict[str, object]", recorded)
        assert detail["patterns"] == ["does/not/exist"]
        assert cast("int", detail["candidates_before_filter"]) > 0

    @pytest.mark.timeout(120)
    def test_a_path_filter_that_keeps_results_is_not_reported(
        self, code_project: _CodeProject
    ) -> None:
        """The evidence is absent when the filter narrowed rather than emptied."""
        from ... import VaultSearcher

        code_project["code_indexer"].full_index(
            reporter=NullProgressReporter(),
            preflight=code_project["code_indexer"].preflight_content(),
        )

        searcher = VaultSearcher(
            code_project["root"],
            code_project["model"],
            code_project["store"],
            reranker=code_project["reranker"],
        )

        notes: dict[str, object] = {}
        results = searcher.search_codebase(
            "calculator",
            top_k=10,
            include_paths=["src"],
            notes=notes,
        )

        assert results
        assert "path_filter" not in notes

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

        searcher = VaultSearcher(root, model, store, reranker=code_project["reranker"])
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
            reranker=code_project["reranker"],
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
            reranker=code_project["reranker"],
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
            reranker=code_project["reranker"],
        )
        results = searcher.search_codebase("hello world greeting", top_k=5)

        assert len(results) > 0
        for r in results:
            assert len(r.snippet.strip()) > 0, f"Result {r.id} has empty snippet"
            assert r.path.endswith(".py"), f"Expected .py path, got {r.path}"


class TestVaultragignore:
    """Integration tests for .vaultragignore exclusion (two-spec OR).

    These verify the full pipeline: .vaultragignore file on disk ->
    _scan_codebase() -> full_index() -> chunks in Qdrant, using real
    GPU embeddings and real Qdrant storage.
    """

    @pytest.mark.timeout(120)
    def test_vaultragignore_excludes_file_from_full_index(
        self, rag_components: RagComponentsWithManifest, tmp_path: Path
    ) -> None:
        """Files matching .vaultragignore are not indexed."""
        from ... import CodebaseIndexer
        from ...store_runtime import VaultStore

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
        from ... import CodebaseIndexer
        from ...store_runtime import VaultStore

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
        """.vaultragignore negation cannot un-ignore .gitignore entries."""
        from ... import CodebaseIndexer
        from ...store_runtime import VaultStore

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
        from ... import CodebaseIndexer
        from ...store_runtime import VaultStore

        model = rag_components["model"]

        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "app.py").write_text(SAMPLE_PYTHON, encoding="utf-8")
        (src_dir / "temp.py").write_text(SAMPLE_VENDOR, encoding="utf-8")

        store = VaultStore(tmp_path)
        try:
            indexer = CodebaseIndexer(
                tmp_path,
                model,
                store,
                options=CodebaseIndexer.Options(extra_excludes=["src/temp.py"]),
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
