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

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from .._job_errors import JobError, JobErrorKind
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
from ..indexer._run_ledger_models import (
    RunAuthority,
    RunTerminalState,
    index_run_ledger_path,
    ledger_connection,
)
from ..indexer._run_ledger_runtime import RunLedger
from ..indexer._vault_indexer import VaultIndexer
from ..progress import NullProgressReporter
from ..store_runtime import VaultStore
from .test_index_lifecycle import _index_events

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

_CONFIG: dict[str, object] = {
    "embedding_dimension": 2,
    "sparse_enabled": False,
    "qdrant_url": None,
    "reranker_enabled": False,
    "index_reuse_enabled": False,
    "index_chunk_workers": 1,
}


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

    def ledger_path(self) -> Path:
        from .._store_writes import workspace_volume_path

        return index_run_ledger_path(workspace_volume_path(self.root.resolve()))

    def reset_state(self, source: PublicSourceType) -> SourceResetState | None:
        return RunLedger(self.ledger_path()).source_reset_state(
            source, str(self.root.resolve()), self.store.backend_identity
        )

    def latest_generation_state(self, source: PublicSourceType) -> RunTerminalState:
        with ledger_connection(self.ledger_path()) as connection:
            row = connection.execute(
                "SELECT terminal_state FROM generations WHERE source_type = ? "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (source.value,),
            ).fetchone()
        assert row is not None, f"no {source.value} generation was opened"
        return RunTerminalState(row[0])


@pytest.fixture
def built_root(tmp_path: Path, isolated_singleton_dirs: Path) -> Generator[_Root]:
    """A root whose three sources each published once and then gained old content."""
    del isolated_singleton_dirs
    get_config(dict(_CONFIG))
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


@pytest.mark.parametrize("source", CONCRETE_SOURCES, ids=lambda s: s.value)
def test_a_failed_reset_classifies_its_rebuild_and_reports_the_failure(
    built_root: _Root,
    source: PublicSourceType,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A reset that never gets its locks leaves no unowned running rebuild.

    Another holder keeps the source's collection lock, so the reset expires
    at the run's no-progress deadline before recording any intent. Every
    domain must then mark its generation interrupted and report the failure
    through the shared lifecycle events, with the old index untouched.

    Mutation: unwrapping the reset in ``reset_for_rebuild`` from
    ``preserve_incomplete_generation`` left the generation ``running`` and
    failed the terminal-state equality for every domain; restoring it passed.
    Mutation: moving the document checkpoint open and reset back ahead of
    ``run_index_lifecycle`` emitted no lifecycle event and failed the event
    equality for documents only; restoring it passed.
    """
    built = built_root
    get_config({**_CONFIG, "index_no_progress_timeout_seconds": 1.0})
    collection = built.collection(source)
    before = built.reset_state(source)
    contents = built.contents(collection)
    held = built.store._lock_for(collection)

    with ThreadPoolExecutor(max_workers=1) as executor:
        held.acquire()
        try:
            with caplog.at_level(logging.INFO):
                running = executor.submit(built.full_index, source)
                with pytest.raises(JobError) as stopped:
                    running.result(timeout=30.0)
        finally:
            held.release()

    assert stopped.value.error_kind is JobErrorKind.NO_PROGRESS_TIMEOUT
    assert built.latest_generation_state(source) is RunTerminalState.REBUILD_INCOMPLETE
    events = [
        (name, fields["source"])
        for name, fields in _index_events(caplog)
        if fields.get("mode") == "full"
    ]
    assert events == [("started", source.value), ("failed", source.value)]
    assert built.reset_state(source) == before
    assert built.contents(collection) == contents
