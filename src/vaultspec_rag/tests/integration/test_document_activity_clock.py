"""End-to-end proof that a document index run refreshes the activity clock.

The persisted ``last_indexed`` stamp is the activity clock the reclaim
tier reads, and it is written only in server mode - a local on-disk store
no-ops the stamp. So this is the only backend that can observe it, which
takes a real pinned Qdrant binary and a real embedding model.

Code and vault runs have always refreshed it. This module pins that a
document run does too, through the real indexer against a real server.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from ...config import EnvVar, reset_config
from ...progress import NullProgressReporter
from ._helpers import _document_policy, provisioned_qdrant_binary, serve_qdrant

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pytest import TempPathFactory

    from ...embeddings import EmbeddingModel
    from ...qdrant_runtime._supervise import QdrantSupervisor

pytestmark = [pytest.mark.integration]

#: A stamp no clock would produce, planted so a refresh is provable without
#: depending on the manifest's one-second stamp resolution.
_STALE_STAMP = "1999-01-01T00:00:00+00:00"


@pytest.fixture(scope="module")
def real_qdrant_binary() -> Path:
    """Provision (or reuse) the pinned real Qdrant binary."""
    return provisioned_qdrant_binary()


@pytest.fixture(scope="module")
def qdrant_server(
    real_qdrant_binary: Path,
    tmp_path_factory: TempPathFactory,
) -> Iterator[QdrantSupervisor]:
    """One real qdrant server on ephemeral ports with temp storage."""
    yield from serve_qdrant(real_qdrant_binary, tmp_path_factory.mktemp("qdrant-clock"))


@pytest.fixture
def server_mode(qdrant_server: QdrantSupervisor) -> Iterator[QdrantSupervisor]:
    """Point store construction at the running server via the URL knob."""
    prev = os.environ.get(EnvVar.QDRANT_URL.value)
    os.environ[EnvVar.QDRANT_URL.value] = qdrant_server.url
    reset_config()
    try:
        yield qdrant_server
    finally:
        if prev is None:
            os.environ.pop(EnvVar.QDRANT_URL.value, None)
        else:
            os.environ[EnvVar.QDRANT_URL.value] = prev
        reset_config()


@pytest.mark.timeout(900)
def test_a_document_run_refreshes_the_persisted_activity_clock(
    server_mode: QdrantSupervisor,  # noqa: ARG001  # activates the URL env seam
    isolated_status_dir: Path,
    embedding_model: EmbeddingModel,
    tmp_path: Path,
) -> None:
    """A completed document run must not leave a stale activity stamp.

    The stale stamp is planted first: overwriting it is what separates a
    real refresh from a store that merely recorded its own backend when
    it opened.
    """
    del isolated_status_dir
    from ...indexer import DocumentIndexer
    from ...storage_manifest import load_manifest, record_root
    from ...store import VaultStore, root_collection_prefix

    (tmp_path / "reference.txt").write_text(
        "Server-mode document material for the activity clock.", encoding="utf-8"
    )
    policy = _document_policy("reference.txt")
    prefix = root_collection_prefix(tmp_path)
    store = VaultStore(tmp_path)
    try:
        assert store._server_mode is True, "the clock only exists in server mode"
        indexer = DocumentIndexer(
            tmp_path,
            embedding_model,
            store,
            content_policy=policy,
        )
        record_root(tmp_path, backend="server", last_indexed=_STALE_STAMP)

        result = indexer.full_index(
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        assert result.added > 0, "the document run indexed nothing"

        entry = load_manifest().get(prefix)
        assert entry is not None, "the document run recorded no manifest entry"
        assert entry.last_indexed != _STALE_STAMP, (
            "a completed document run left the planted stale stamp in place, so "
            "a document-only root reads as idle to the reclaim tier"
        )
    finally:
        store.close()
