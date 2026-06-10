"""Targeted (changed-paths) reindex integration tests (issue #151).

Proves the scoped ``incremental_index(changed_paths=...)`` path on both
indexers reconciles only the paths it is handed: an edit to one file
re-embeds exactly that file, a deletion removes only that file's
content, and a path the indexer does not own is a no-op. Backward
compatibility of the argument-less full-scan path is also asserted.

Real GPU + real Qdrant, no mocks/skips, per the project test mandate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from vaultspec_core.config import (  # pyright: ignore[reportMissingTypeStubs]
    reset_config,
)
from vaultspec_core.vaultcore import (  # pyright: ignore[reportMissingTypeStubs]
    scan_vault,
)

from ...config import get_config
from ...config import reset_config as reset_rag_config
from ...progress import NullProgressReporter
from ..corpus import build_synthetic_vault

if TYPE_CHECKING:
    from pathlib import Path

    from ...embeddings import EmbeddingModel
    from ...indexer import CodebaseIndexer, VaultIndexer
    from ...store import VaultStore

pytestmark = [pytest.mark.integration]


def _vault_doc_id(path: Path, docs_dir: Path) -> str:
    """Mirror the indexer's path -> doc-id scheme for assertions."""
    rel = str(path.relative_to(docs_dir)).replace("\\", "/")
    return rel.rsplit(".", 1)[0] if "." in rel else rel


def _build_vault(
    root: Path, model: EmbeddingModel, *, n_docs: int = 6
) -> tuple[VaultStore, VaultIndexer]:
    """Build and fully index a small synthetic vault at *root*."""
    from ... import VaultIndexer, VaultStore

    reset_config()
    reset_rag_config()
    build_synthetic_vault(root, n_docs=n_docs, seed=7)
    store = VaultStore(root)
    indexer = VaultIndexer(root, model, store)
    indexer.full_index(reporter=NullProgressReporter())
    return store, indexer


class TestVaultScopedReindex:
    """Scoped vault reindex processes only the changed paths."""

    @pytest.mark.timeout(180)
    def test_edit_reindexes_only_the_named_path(
        self, embedding_model: EmbeddingModel, tmp_path: Path
    ) -> None:
        store, indexer = _build_vault(tmp_path, embedding_model)
        try:
            docs_dir = tmp_path / get_config().docs_dir
            paths = sorted(scan_vault(tmp_path))
            target, other = paths[0], paths[1]
            target_id = _vault_doc_id(target, docs_dir)
            other_id = _vault_doc_id(other, docs_dir)

            meta_before = indexer._load_meta()

            # Edit BOTH files on disk, but hand the indexer only `target`.
            target.write_text(
                target.read_text(encoding="utf-8") + "\n\nedit-marker-target\n",
                encoding="utf-8",
            )
            other.write_text(
                other.read_text(encoding="utf-8") + "\n\nedit-marker-other\n",
                encoding="utf-8",
            )

            result = indexer.incremental_index(
                reporter=NullProgressReporter(),
                changed_paths={target},
            )

            meta_after = indexer._load_meta()
            # Only the named path was reconciled.
            assert result.updated == 1
            assert result.added == 0
            assert result.removed == 0
            # `target` was rehashed; `other` was left entirely alone even
            # though its bytes changed on disk - proof the scope held.
            assert meta_after[target_id] != meta_before[target_id]
            assert meta_after[other_id] == meta_before[other_id]
            # No id was dropped by the partial metadata write.
            assert set(meta_after) == set(meta_before)
        finally:
            store.close()

    @pytest.mark.timeout(180)
    def test_delete_removes_only_that_doc(
        self, embedding_model: EmbeddingModel, tmp_path: Path
    ) -> None:
        store, indexer = _build_vault(tmp_path, embedding_model)
        try:
            docs_dir = tmp_path / get_config().docs_dir
            paths = sorted(scan_vault(tmp_path))
            target, other = paths[0], paths[1]
            target_id = _vault_doc_id(target, docs_dir)
            other_id = _vault_doc_id(other, docs_dir)

            assert target_id in store.get_all_ids()
            target.unlink()

            result = indexer.incremental_index(
                reporter=NullProgressReporter(),
                changed_paths={target},
            )

            assert result.removed == 1
            assert result.added == 0
            assert result.updated == 0
            ids_after = store.get_all_ids()
            assert target_id not in ids_after
            assert other_id in ids_after
            assert target_id not in indexer._load_meta()
        finally:
            store.close()

    @pytest.mark.timeout(180)
    def test_path_outside_vault_is_noop(
        self, embedding_model: EmbeddingModel, tmp_path: Path
    ) -> None:
        store, indexer = _build_vault(tmp_path, embedding_model)
        try:
            meta_before = indexer._load_meta()
            count_before = store.count()

            stray = tmp_path / "not_a_vault_doc.md"
            stray.write_text("# stray\n\nnot under the vault\n", encoding="utf-8")

            result = indexer.incremental_index(
                reporter=NullProgressReporter(),
                changed_paths={stray},
            )

            assert (result.added, result.updated, result.removed) == (0, 0, 0)
            assert store.count() == count_before
            assert indexer._load_meta() == meta_before
        finally:
            store.close()

    @pytest.mark.timeout(180)
    def test_argument_less_call_still_full_scans(
        self, embedding_model: EmbeddingModel, tmp_path: Path
    ) -> None:
        store, indexer = _build_vault(tmp_path, embedding_model)
        try:
            # No changed_paths: the full-scan path runs and finds nothing new.
            result = indexer.incremental_index(reporter=NullProgressReporter())
            assert result.added == 0
            assert result.updated == 0
            assert result.removed == 0
            assert result.total == store.count()
        finally:
            store.close()


def _build_code(
    root: Path, model: EmbeddingModel
) -> tuple[VaultStore, CodebaseIndexer, Path, Path]:
    """Build a tiny source tree and fully index it at *root*."""
    from ... import CodebaseIndexer, VaultStore

    reset_config()
    reset_rag_config()
    build_synthetic_vault(root, n_docs=3, seed=11)
    pkg = root / "pkg"
    pkg.mkdir(parents=True, exist_ok=True)
    a = pkg / "alpha.py"
    b = pkg / "beta.py"
    a.write_text("def alpha():\n    return 'alpha-one'\n", encoding="utf-8")
    b.write_text("def beta():\n    return 'beta-one'\n", encoding="utf-8")
    store = VaultStore(root)
    code_indexer = CodebaseIndexer(root, model, store)
    code_indexer.full_index(reporter=NullProgressReporter())
    return store, code_indexer, a, b


class TestCodeScopedReindex:
    """Scoped codebase reindex processes only the changed files."""

    @pytest.mark.timeout(180)
    def test_edit_reindexes_only_the_named_file(
        self, embedding_model: EmbeddingModel, tmp_path: Path
    ) -> None:
        store, code_indexer, a, b = _build_code(tmp_path, embedding_model)
        try:
            a_rel = str(a.relative_to(tmp_path)).replace("\\", "/")
            b_rel = str(b.relative_to(tmp_path)).replace("\\", "/")
            meta_before = code_indexer._load_meta()

            # Edit both, hand the indexer only `a`.
            a.write_text("def alpha():\n    return 'alpha-two'\n", encoding="utf-8")
            b.write_text("def beta():\n    return 'beta-two'\n", encoding="utf-8")

            result = code_indexer.incremental_index(
                reporter=NullProgressReporter(),
                changed_paths={a},
            )

            meta_after = code_indexer._load_meta()
            assert result.updated == 1
            assert result.added == 0
            assert result.removed == 0
            assert meta_after[a_rel] != meta_before[a_rel]
            assert meta_after[b_rel] == meta_before[b_rel]
        finally:
            store.close()

    @pytest.mark.timeout(180)
    def test_delete_removes_only_that_file(
        self, embedding_model: EmbeddingModel, tmp_path: Path
    ) -> None:
        store, code_indexer, a, b = _build_code(tmp_path, embedding_model)
        try:
            a_rel = str(a.relative_to(tmp_path)).replace("\\", "/")
            b_rel = str(b.relative_to(tmp_path)).replace("\\", "/")

            assert code_indexer._get_chunk_ids_for_files({a_rel})
            a.unlink()

            result = code_indexer.incremental_index(
                reporter=NullProgressReporter(),
                changed_paths={a},
            )

            assert result.removed == 1
            assert not code_indexer._get_chunk_ids_for_files({a_rel})
            assert code_indexer._get_chunk_ids_for_files({b_rel})
            assert a_rel not in code_indexer._load_meta()
        finally:
            store.close()

    @pytest.mark.timeout(180)
    def test_gitignored_file_is_noop(
        self, embedding_model: EmbeddingModel, tmp_path: Path
    ) -> None:
        store, code_indexer, _a, _b = _build_code(tmp_path, embedding_model)
        try:
            (tmp_path / ".gitignore").write_text("pkg/ignored.py\n", encoding="utf-8")
            ignored = tmp_path / "pkg" / "ignored.py"
            ignored.write_text("def ignored():\n    return 0\n", encoding="utf-8")
            meta_before = code_indexer._load_meta()

            result = code_indexer.incremental_index(
                reporter=NullProgressReporter(),
                changed_paths={ignored},
            )

            assert (result.added, result.updated, result.removed) == (0, 0, 0)
            assert code_indexer._load_meta() == meta_before
        finally:
            store.close()
