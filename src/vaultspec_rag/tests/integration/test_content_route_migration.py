"""Real-model indexing verifies destination-first ownership changes."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ...indexer._content_policy import (
    ContentKind,
    ContentRoute,
    RootContentPolicy,
    SourceProfileVersion,
)
from ...store_runtime import VaultStore

if TYPE_CHECKING:
    from pathlib import Path

    from ...embeddings import EmbeddingModel

pytestmark = [pytest.mark.integration]


def test_real_indexers_flip_ownership_destination_first(
    clean_config: None,
    embedding_model: EmbeddingModel,
    tmp_path: Path,
) -> None:
    del clean_config
    from ...indexer import CodebaseIndexer, DocumentIndexer
    from ...progress import NullProgressReporter

    source = tmp_path / "shared.py"
    source.write_text("def routed_value() -> int:\n    return 17\n", encoding="utf-8")
    code_policy = RootContentPolicy(SourceProfileVersion.CONVENTIONAL_V1)
    document_policy = RootContentPolicy(
        SourceProfileVersion.EXPLICIT_ONLY_V1,
        (ContentRoute("shared.py", ContentKind.DOCUMENT),),
    )
    store = VaultStore(tmp_path)
    try:
        code = CodebaseIndexer(
            tmp_path,
            embedding_model,
            store,
            options=CodebaseIndexer.Options(content_policy=code_policy),
        )
        code.full_index(
            reporter=NullProgressReporter(),
            preflight=code.preflight_content(),
        )
        assert store.count_code() > 0
        assert store.count_document() == 0

        document = DocumentIndexer(
            tmp_path,
            embedding_model,
            store,
            content_policy=document_policy,
        )
        document.full_index(
            reporter=NullProgressReporter(),
            preflight=document.preflight_content(),
        )
        assert store.count_code() == 0
        assert store.count_document() > 0

        code = CodebaseIndexer(
            tmp_path,
            embedding_model,
            store,
            options=CodebaseIndexer.Options(content_policy=code_policy),
        )
        code.full_index(
            reporter=NullProgressReporter(),
            preflight=code.preflight_content(),
        )
        assert store.count_code() > 0
        assert store.count_document() == 0
    finally:
        store.close()
