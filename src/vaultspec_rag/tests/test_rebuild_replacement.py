"""Every full-index entry resets its own source and certifies the same target.

Each case drives the production full-index entry of one content kind over a
real local store and a real run ledger. The root's corpus is empty, so no
forward pass runs and nothing reaches the accelerator; the content being
discarded is planted directly in storage, recognisable by its payload, the
way an earlier build would have left it. The corpus counterpart, which writes
real replacement batches and observes storage at the first one, runs in the
GPU lane.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from .._publication_state import acquire_publication_snapshot
from .._source_types import CONCRETE_SOURCES, PublicSourceType
from ..config._settings import get_config
from ..indexer._codebase_indexer import CodebaseIndexer
from ..indexer._content_policy import (
    ContentKind,
    ContentRoute,
    RootContentPolicy,
    SourceProfileVersion,
)
from ..indexer._document_indexer import DocumentIndexer
from ..indexer._run_ledger_models import RunAuthority, index_run_ledger_path
from ..indexer._run_ledger_runtime import RunLedger
from ..indexer._vault_indexer import VaultIndexer
from ..progress import NullProgressReporter
from ..store_runtime import VaultStore

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ..embeddings import EmbeddingModel
    from ..indexer._run_ledger_models import PublicationProof, SourceResetState

pytestmark = [pytest.mark.unit]

_POLICY = RootContentPolicy(
    SourceProfileVersion.CONVENTIONAL_V1,
    (ContentRoute("docs/*.md", ContentKind.DOCUMENT),),
)

_OLD_MARKER = "OLD-ONLY-CONTENT"


class _NoForward:
    """The model boundary of a run that encodes nothing.

    The corpus is empty, so a forward here means the run encoded content it
    was never given.
    """

    device = "cpu"

    def encode_documents_on_device(
        self, texts: list[str], **_options: object
    ) -> list[list[float]]:
        raise AssertionError(f"an empty corpus reached the encoder: {texts!r}")

    def encode_documents_sparse(
        self, texts: list[str], **_options: object
    ) -> list[None]:
        raise AssertionError(f"an empty corpus reached the encoder: {texts!r}")


@dataclass
class _Root:
    root: Path
    store: VaultStore
    vault: VaultIndexer
    code: CodebaseIndexer
    document: DocumentIndexer

    def collection(self, source: PublicSourceType) -> str:
        if source is PublicSourceType.VAULT:
            return self.store.TABLE_NAME
        if source is PublicSourceType.CODE:
            return self.store.DERIVED_CODE_TABLE_NAME
        return self.store.DOCUMENT_TABLE_NAME

    def contents(self, collection: str) -> list[str]:
        points, _ = self.store.client.scroll(
            collection, limit=1000, with_payload=True, with_vectors=False
        )
        return sorted(str(point.payload) for point in points)

    def plant_old_content(self, collection: str) -> None:
        from qdrant_client import models

        from .. import store_schema

        self.store.client.upsert(
            collection,
            points=[
                models.PointStruct(
                    id=7,
                    vector={store_schema.DENSE_VECTOR_NAME: [1.0, 0.0]},
                    payload={"content": f"{_OLD_MARKER} in {collection}"},
                )
            ],
            wait=True,
        )

    def full_index(
        self,
        source: PublicSourceType,
        authority: RunAuthority = RunAuthority.REBUILD,
    ) -> None:
        reporter = NullProgressReporter()
        if source is PublicSourceType.VAULT:
            self.vault.full_index(clean=True, reporter=reporter, authority=authority)
        elif source is PublicSourceType.CODE:
            self.code.full_index(
                clean=True,
                reporter=reporter,
                preflight=self.code.preflight_content(),
                authority=authority,
            )
        else:
            self.document.full_index(
                clean=True,
                reporter=reporter,
                preflight=self.document.preflight_content(),
                authority=authority,
            )

    def incremental_index(self, source: PublicSourceType) -> None:
        reporter = NullProgressReporter()
        if source is PublicSourceType.VAULT:
            self.vault.incremental_index(reporter=reporter)
        elif source is PublicSourceType.CODE:
            self.code.incremental_index(
                reporter=reporter, preflight=self.code.preflight_content()
            )
        else:
            self.document.incremental_index(
                reporter=reporter, preflight=self.document.preflight_content()
            )

    def proof(self, source: PublicSourceType) -> PublicationProof:
        snapshot = acquire_publication_snapshot(self.root, source)
        proof = snapshot.proof
        snapshot.validate()
        return proof

    def reset_state(self, source: PublicSourceType) -> SourceResetState | None:
        from .._store_writes import workspace_volume_path

        ledger = RunLedger(
            index_run_ledger_path(workspace_volume_path(self.root.resolve()))
        )
        return ledger.source_reset_state(
            source, str(self.root.resolve()), self.store.backend_identity
        )


@pytest.fixture
def built_root(tmp_path: Path, isolated_singleton_dirs: Path) -> Generator[_Root]:
    """A root whose three sources each published once and then gained old content."""
    del isolated_singleton_dirs
    get_config(
        {
            "embedding_dimension": 2,
            "sparse_enabled": False,
            "qdrant_url": None,
            "reranker_enabled": False,
            "index_reuse_enabled": False,
            "index_chunk_workers": 1,
        }
    )
    root = (tmp_path / "root").resolve()
    root.mkdir()
    model = cast("EmbeddingModel", _NoForward())
    with VaultStore(root, embedding_dim=2) as store:
        built = _Root(
            root=root,
            store=store,
            vault=VaultIndexer(root, model, store),
            code=CodebaseIndexer(
                root, model, store, CodebaseIndexer.Options(content_policy=_POLICY)
            ),
            document=DocumentIndexer(root, model, store, content_policy=_POLICY),
        )
        for source in CONCRETE_SOURCES:
            built.full_index(source)
            built.plant_old_content(built.collection(source))
        yield built


@pytest.mark.parametrize("source", CONCRETE_SOURCES, ids=lambda s: s.value)
def test_full_index_discards_the_old_index_and_certifies_its_own_collection(
    built_root: _Root, source: PublicSourceType
) -> None:
    """The rebuild leaves its source empty, certified and alone in its namespace.

    Mutation: deleting the reset call from the indexer's full entry left the
    planted content in the canonical collection and failed the emptiness
    assertion; restoring it passed.
    """
    built = built_root
    siblings = [kind for kind in CONCRETE_SOURCES if kind is not source]
    sibling_proofs = {kind: built.proof(kind) for kind in siblings}
    sibling_contents = {
        kind: built.contents(built.collection(kind)) for kind in siblings
    }
    legacy = None
    if source is PublicSourceType.CODE:
        from ._historical_code_layout import create_historical_generation

        # A build under the earlier layout left this generation collection.
        legacy = create_historical_generation(built.store, "old")
        built.plant_old_content(legacy)
    before = built.reset_state(source)
    before_epoch = 0 if before is None else before.epoch

    built.full_index(source)

    collection = built.collection(source)
    assert built.store.client.collection_exists(collection)
    assert built.contents(collection) == [], "old content survived the rebuild"
    reset = built.reset_state(source)
    assert reset is not None and reset.complete
    assert reset.epoch == before_epoch + 1
    proof = built.proof(source)
    assert proof.generation_id == reset.generation_id, (
        "completion certified a generation other than the one that reset"
    )
    assert proof.aggregate.retained_points == 0
    if source is PublicSourceType.CODE:
        assert built.store.owned_code_collections() == (collection,)
        assert collection == built.store.CODE_TABLE_NAME
    for kind in siblings:
        assert built.proof(kind) == sibling_proofs[kind], kind
        assert built.contents(built.collection(kind)) == sibling_contents[kind], kind


@pytest.mark.parametrize("source", CONCRETE_SOURCES, ids=lambda s: s.value)
def test_incremental_run_never_resets(
    built_root: _Root, source: PublicSourceType
) -> None:
    """An incremental run leaves the epoch and the stored content alone.

    Mutation: resetting the source at the end of the incremental entry
    advanced the recorded epoch and failed the reset-state equality;
    restoring it passed.
    """
    built = built_root
    before = built.reset_state(source)
    contents = built.contents(built.collection(source))

    built.incremental_index(source)

    assert built.reset_state(source) == before
    assert built.contents(built.collection(source)) == contents


@pytest.mark.parametrize("source", CONCRETE_SOURCES, ids=lambda s: s.value)
def test_full_index_refuses_without_rebuild_authority(
    built_root: _Root, source: PublicSourceType
) -> None:
    """A full run is a rebuild; publication authority cannot reach it.

    Mutation: deleting the authority check from the full entry let the run
    through and failed the ``pytest.raises``; restoring it passed.
    """
    built = built_root
    before = built.reset_state(source)
    contents = built.contents(built.collection(source))

    with pytest.raises(PermissionError, match="requires rebuild authority"):
        built.full_index(source, authority=RunAuthority.PUBLICATION)

    assert built.reset_state(source) == before
    assert built.contents(built.collection(source)) == contents
