"""Real embedding and Qdrant coverage for isolated document ingestion."""

from __future__ import annotations

import shlex
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest

from ...progress import NullProgressReporter

if TYPE_CHECKING:
    from pathlib import Path

    from ...embeddings import EmbeddingModel

pytestmark = [pytest.mark.integration]


def _document_policy(pattern: str):
    from ...indexer._content_policy import (
        ContentKind,
        ContentRoute,
        RootContentPolicy,
        SourceProfileVersion,
    )

    return RootContentPolicy(
        SourceProfileVersion.CONVENTIONAL_V1,
        (ContentRoute(pattern, ContentKind.DOCUMENT),),
    )


@pytest.mark.timeout(600)
def test_raw_document_full_and_scoped_incremental_stay_isolated(
    embedding_model: EmbeddingModel,
    tmp_path: Path,
) -> None:
    from ...indexer import CodebaseIndexer, DocumentIndexer
    from ...store import VaultStore

    source = tmp_path / "reference.txt"
    source.write_text("Initial document-only material.", encoding="utf-8")
    code = tmp_path / "module.py"
    code.write_text("def source_only():\n    return 17\n", encoding="utf-8")
    policy = _document_policy("reference.txt")
    store = VaultStore(tmp_path)
    try:
        code_indexer = CodebaseIndexer(
            tmp_path,
            embedding_model,
            store,
            content_policy=policy,
        )
        document_indexer = DocumentIndexer(
            tmp_path,
            embedding_model,
            store,
            content_policy=policy,
        )

        code_indexer.full_index(
            reporter=NullProgressReporter(),
            preflight=code_indexer.preflight_content(),
        )
        document_indexer.full_index(
            reporter=NullProgressReporter(),
            preflight=document_indexer.preflight_content(),
        )

        assert store.get_code_ids_by_paths({"reference.txt"}) == []
        assert store.get_code_ids_by_paths({"module.py"})
        rows, _ = store.scroll_document_content(limit=10)
        assert [row["payload"]["source_path"] for row in rows] == ["reference.txt"]
        assert rows[0]["payload"]["content"] == "Initial document-only material."

        source.write_text("Discovered document-only change.", encoding="utf-8")
        discovered_outcome = document_indexer.incremental_index(
            reporter=NullProgressReporter(),
            preflight=document_indexer.preflight_content(),
        )
        assert (discovered_outcome.added, discovered_outcome.updated) == (0, 1)

        source.write_text("Scoped document-only change.", encoding="utf-8")
        scoped_outcome = document_indexer.incremental_index(
            reporter=NullProgressReporter(),
            changed_paths=[source],
            preflight=document_indexer.preflight_changed_paths([source]),
        )
        rows, _ = store.scroll_document_content(limit=10)
        assert (
            scoped_outcome.added,
            scoped_outcome.updated,
            scoped_outcome.preprocess_skipped,
        ) == (0, 1, 0)
        assert len(rows) == 1
        assert rows[0]["payload"]["content"] == "Scoped document-only change."
        assert store.get_code_ids_by_paths({"reference.txt"}) == []
    finally:
        store.close()


@pytest.mark.timeout(600)
def test_extracted_document_preserves_native_metadata_without_code_points(
    embedding_model: EmbeddingModel,
    tmp_path: Path,
) -> None:
    from ...indexer import CodebaseIndexer, DocumentIndexer
    from ...store import VaultStore

    extractor = tmp_path / "record_extractor.py"
    extractor.write_text(
        textwrap.dedent(
            """
            import json, sys
            source = sys.argv[1]
            print(json.dumps({
                "schema_version": 1,
                "preprocessor_id": "record-extractor",
                "preprocessor_version": "3.2",
                "source_path": source,
                "metadata": {"category": "finance"},
                "units": [{
                    "text": "Verified extracted revenue statement.",
                    "title": "Revenue",
                    "section": "Summary",
                    "anchor": source + "#page=7",
                    "locator": {"kind": "page", "value": 7},
                    "metadata": {"confidence": "verified"}
                }]
            }))
            """
        ),
        encoding="utf-8",
    )
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(extractor))} {{path}}"
    (tmp_path / ".vaultragpreprocess.toml").write_text(
        "version = 2\n\n"
        '[[rule]]\npattern = "*.record"\n'
        f"command = '''{command}'''\n"
        'target = "document"\nextractor_version = "3.2"\n'
        'on_error = "fail"\n',
        encoding="utf-8",
    )
    source = tmp_path / "annual.record"
    source.write_bytes(b"\x00\x81 source bytes consumed only by the extractor")
    policy = _document_policy("*.record")
    store = VaultStore(tmp_path)
    try:
        document_indexer = DocumentIndexer(
            tmp_path,
            embedding_model,
            store,
            content_policy=policy,
        )
        code_indexer = CodebaseIndexer(
            tmp_path,
            embedding_model,
            store,
            content_policy=policy,
        )
        result = document_indexer.full_index(
            reporter=NullProgressReporter(),
            preflight=document_indexer.preflight_content(),
        )
        code_indexer.full_index(
            reporter=NullProgressReporter(),
            preflight=code_indexer.preflight_content(),
        )

        assert (result.preprocess_ok, result.preprocess_skipped) == (1, 0)
        assert store.get_code_ids_by_paths({"annual.record"}) == []
        rows, _ = store.scroll_document_content(
            limit=10,
            source_paths={"annual.record"},
        )
        assert len(rows) == 1
        payload = rows[0]["payload"]
        assert payload["title"] == "Revenue"
        assert payload["section"] == "Summary"
        assert payload["anchor"].endswith("#page=7")
        assert payload["locator_kind"] == "page"
        assert payload["locator_value_int"] == 7
        assert payload["locator_end_int"] is None
        assert payload["document_metadata"] == {"category": "finance"}
        assert payload["unit_metadata"] == {"confidence": "verified"}
        assert payload["extractor_id"] == "record-extractor"
        assert payload["extractor_version"] == "3.2"
    finally:
        store.close()
