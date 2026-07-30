"""Cross-domain lifecycle isolation through real indexing and storage."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ..._store_models import DocumentChunk, DocumentPayload
from ...api import clean
from ...config._settings import get_config
from ...indexer import CodebaseIndexer
from ...indexer._document_meta import (
    DocumentFileMetadata,
    DocumentIndexMetadata,
    document_metadata_path,
    write_document_meta,
)
from ...indexer._preprocess_cache import preprocess_cache_dir
from ...progress import NullProgressReporter
from ...registry import get_registry
from ...store_runtime import VaultStore

if TYPE_CHECKING:
    from ...embeddings import EmbeddingModel

pytestmark = [pytest.mark.integration, pytest.mark.timeout(600)]


def _write_document_extractor_route(
    root: Path,
    extractor: Path,
) -> None:
    python = str(Path(sys.executable).resolve()).replace("\\", "/")
    command = str(extractor.resolve()).replace("\\", "/")
    (root / ".vaultragpreprocess.toml").write_text(
        "version = 2\n\n"
        "[[rule]]\n"
        'pattern = "*.blob"\n'
        f'command = \'"{python}" "{command}" {{path}}\'\n'
        'target = "document"\n'
        'extractor_version = "1"\n'
        'on_error = "fail"\n',
        encoding="utf-8",
    )


def _document_chunk(dimension: int) -> DocumentChunk:
    return DocumentChunk(
        "document-lifecycle-sentinel",
        DocumentPayload(
            source_path="manual.blob",
            unit_ordinal=0,
            content_fingerprint="document-content-v1",
            content="Document lifecycle state must survive code maintenance.",
            extractor_id="document-lifecycle",
            extractor_version="1",
        ),
        vector=[0.0] * dimension,
    )


def test_code_job_and_cleanup_preserve_document_state(
    clean_config: None,
    embedding_model: EmbeddingModel,
    tmp_path: Path,
) -> None:
    """Code work neither launches a document extractor nor cleans its state."""
    del clean_config
    get_config({"sparse_enabled": False, "index_support_profile": "embedded-local"})
    source = tmp_path / "module.py"
    source.write_text(
        "def lifecycle_value() -> int:\n    return 41\n",
        encoding="utf-8",
    )
    document = tmp_path / "manual.blob"
    document.write_bytes(b"document-only binary input")
    sentinel = tmp_path / "document-extractor-ran.flag"
    extractor = tmp_path / "extractor.py"
    extractor.write_text(
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('ran', encoding='utf-8')\n",
        encoding="utf-8",
    )
    (tmp_path / ".vaultragignore").write_text("/extractor.py\n", encoding="utf-8")
    _write_document_extractor_route(tmp_path, extractor)

    cfg = get_config()
    data_root = tmp_path / cfg.data_dir
    cache_root = preprocess_cache_dir(data_root)
    cache_root.mkdir(parents=True)
    cache_sentinel = cache_root / "document-cache-sentinel.json"
    cache_sentinel.write_bytes(b'{"document":"preserved"}')
    chunk = _document_chunk(embedding_model.dimension)
    metadata_path = document_metadata_path(tmp_path)
    write_document_meta(
        metadata_path,
        DocumentIndexMetadata(
            membership_fingerprint="membership-v1",
            content_fingerprint="content-v1",
            policy_snapshot="policy-v1",
            files=(
                DocumentFileMetadata(
                    document.name,
                    chunk.payload.content_fingerprint,
                    (chunk.id,),
                ),
            ),
            generation_id="document-generation-v1",
        ),
    )
    metadata_before = metadata_path.read_bytes()
    cache_before = cache_sentinel.read_bytes()

    store = VaultStore(tmp_path, embedding_dim=embedding_model.dimension)
    try:
        store.upsert_document_content_chunks([chunk], write_policy=None)
        ids_before = store.get_all_document_content_ids()
        indexer = CodebaseIndexer(tmp_path, embedding_model, store)
        result = indexer.full_index(
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        assert result.files == 1
        assert result.total > 0
        assert not sentinel.exists()
        assert store.get_all_document_content_ids() == ids_before
        assert metadata_path.read_bytes() == metadata_before
        assert cache_sentinel.read_bytes() == cache_before
    finally:
        store.close()

    assert clean(tmp_path, clean_type="code", registry=get_registry()) == ["codebase"]
    reopened = VaultStore(tmp_path, embedding_dim=embedding_model.dimension)
    try:
        assert reopened.get_all_document_content_ids() == ids_before
        assert metadata_path.read_bytes() == metadata_before
        assert cache_sentinel.read_bytes() == cache_before
        assert not sentinel.exists()
    finally:
        reopened.close()
