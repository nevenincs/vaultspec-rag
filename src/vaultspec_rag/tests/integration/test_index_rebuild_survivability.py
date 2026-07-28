"""Crash-shaped proof that a rebuild can never destroy what it serves.

The historical loss mechanism was an interrupted in-place clean rebuild: drop
the served collection up front, repopulate partially, crash - leaving a
near-empty collection under a sidecar that still claims the full corpus, with
searches answering confidently from the husk. These tests reproduce the crash
honestly per domain: real local stores, real sidecars written by the
production writers, and a real failure raised from inside the production
rebuild path by a subclass that overrides exactly one seam. After each crash
the served data must still be whole and the serve-time verdict must still be
``consistent`` (where the domain carries a claim at all).

No mocks, stubs, or patches: the failure injections are real subclasses of
the production indexer or store, raising from one overridden method.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from ..._index_integrity import VERDICT_CONSISTENT, evaluate_index_integrity
from ..._source_types import PublicSourceType
from ...progress import NullProgressReporter
from ..conftest import managed_env

if TYPE_CHECKING:
    from pathlib import Path

    from ...store_runtime import VaultStore

pytestmark = [pytest.mark.integration]


def _seed_vault_chunks(store: VaultStore, doc_ids: tuple[str, ...]) -> None:
    """Upsert one real zero-vector chunk per document - no model involved."""
    from ..._store_models import VaultChunk
    from ...config._settings import get_config

    dimension = int(get_config().embedding_dimension)
    store.upsert_document_chunks(
        [
            VaultChunk(
                doc_id=doc_id,
                ordinal=0,
                chunk_count=1,
                text=f"body of {doc_id}",
                path=f"adr/{doc_id}.md",
                doc_type="adr",
                feature="search",
                date="2026-01-01",
                tags=[],
                related=[],
                title=doc_id,
                doc_content=f"body of {doc_id}",
                vector=[0.0] * dimension,
            )
            for doc_id in doc_ids
        ],
        write_policy=None,
    )


def _seed_document_chunks(store: VaultStore, ids: tuple[str, ...]) -> None:
    """Upsert one real zero-vector document-native chunk per id."""
    from ..._store_models import DocumentChunk, DocumentPayload
    from ...config._settings import get_config

    dimension = int(get_config().embedding_dimension)
    store.upsert_document_content_chunks(
        [
            DocumentChunk(
                id=chunk_id,
                payload=DocumentPayload(
                    source_path=f"docs/{chunk_id}.pdf",
                    unit_ordinal=0,
                    content_fingerprint=f"fp-{chunk_id}",
                    content=f"content of {chunk_id}",
                ),
                vector=[0.0] * dimension,
            )
            for chunk_id in ids
        ],
        write_policy=None,
    )


def _write_document_manifest(root: Path, point_ids: tuple[str, ...]) -> None:
    """Publish a complete document manifest through the production writer."""
    from ...indexer._document_meta import (
        DocumentFileMetadata,
        DocumentIndexMetadata,
        document_metadata_path,
        write_document_meta,
    )

    write_document_meta(
        document_metadata_path(root),
        DocumentIndexMetadata(
            membership_fingerprint="membership",
            content_fingerprint="content",
            policy_snapshot="policy",
            files=(DocumentFileMetadata("docs/served.pdf", "hash", tuple(point_ids)),),
            generation_id="a" * 32,
        ),
    )


class TestVaultCleanRebuildSurvivesInterruption:
    def test_a_crash_after_preparation_leaves_the_served_points_intact(
        self, tmp_path: Path
    ) -> None:
        """A clean vault rebuild that dies mid-flight destroys nothing.

        The crash is raised by a real indexer subclass from the first seam
        past collection preparation, before any point is written - exactly
        where the old up-front drop had already emptied the collection.
        """
        from ...indexer import VaultIndexer
        from ...store_runtime import VaultStore

        class CrashAfterPreparation(VaultIndexer):
            """Real indexer whose reuse resolution dies like a torn run."""

            def _resolve_reuse(self) -> Any:
                raise OSError("injected crash after collection preparation")

        store = VaultStore(tmp_path)
        try:
            _seed_vault_chunks(store, ("d1", "d2", "d3", "d4", "d5"))
            assert store.count() == 5

            indexer = CrashAfterPreparation(
                tmp_path, model=cast("Any", None), store=store
            )
            with pytest.raises(OSError, match="injected crash"):
                indexer.full_index(clean=True, reporter=NullProgressReporter())

            # Catches the up-front drop being reintroduced in
            # ``_prepare_collection``: with the served collection dropped
            # before the crash point, this count reads 0 and the vault serves
            # nothing until the next successful run.
            assert store.count() == 5
        finally:
            store.close()


class TestDocumentCleanRebuildSurvivesInterruption:
    def test_a_crash_during_republication_keeps_the_claimed_corpus_served(
        self, tmp_path: Path
    ) -> None:
        """A clean document rebuild that dies mid-publication serves old data.

        Seeds a real served collection and a complete manifest through the
        production writer, then runs the production ``full_index(clean=True)``
        with a subclass whose publication step raises - the same instant an
        interrupted historical rebuild died. The served points and the
        manifest's claim must both survive, and the serve-time verdict must
        stay ``consistent``.
        """
        from ...indexer import DocumentIndexer
        from ...store_runtime import VaultStore

        class CrashDuringPublication(DocumentIndexer):
            """Real indexer whose publication step dies like a torn run."""

            def _publish_full_paths(self, *args: Any, **kwargs: Any) -> Any:
                del args, kwargs
                raise OSError("injected crash while republishing")

        with managed_env(VAULTSPEC_RAG_SPARSE_ENABLED="0"):
            store = VaultStore(tmp_path)
            try:
                ids = ("p1", "p2", "p3", "p4")
                _seed_document_chunks(store, ids)
                _write_document_manifest(tmp_path, ids)
                live = store.count_document()
                assert live == 4
                healthy = evaluate_index_integrity(
                    tmp_path,
                    PublicSourceType.DOCUMENT,
                    live,
                    claim_ttl_seconds=0.0,
                )
                assert healthy.verdict == VERDICT_CONSISTENT

                indexer = CrashDuringPublication(
                    tmp_path, model=cast("Any", None), store=store
                )
                with pytest.raises(OSError, match="injected crash"):
                    indexer.full_index(clean=True, reporter=NullProgressReporter())

                # Catches the up-front ``drop_document_table`` being
                # reintroduced ahead of publication: with the served
                # collection dropped before the crash, the count reads 0
                # under a manifest still claiming 4 and the verdict below
                # reads ``shrunken`` instead of ``consistent``.
                assert store.count_document() == 4
                verdict = evaluate_index_integrity(
                    tmp_path,
                    PublicSourceType.DOCUMENT,
                    store.count_document(),
                    claim_ttl_seconds=0.0,
                )
                assert verdict.verdict == VERDICT_CONSISTENT
            finally:
                store.close()


class TestCodeGenerationRebuildSurvivesInterruption:
    def test_a_storage_failure_mid_generation_build_never_moves_the_pointer(
        self, tmp_path: Path
    ) -> None:
        """The code domain's generation flow survives a torn replacement.

        The failure is a real store subclass whose code upsert dies after one
        successful batch - the interrupted-repopulation shape - while a
        replacement generation is being built beside the served collection.
        The served pointer must still name the old complete generation, its
        breadth claim must still verify, and the fragment must be left
        unreferenced rather than served.
        """
        from ..._index_breadth import code_meta_path
        from ..._store_models import (
            generation_code_collection,
            publish_generation_as_served,
            read_served_code_collection,
        )
        from ...config._settings import get_config
        from ...indexer._code_meta import publish_meta_from_file_states
        from ...store_runtime import VaultStore

        class FailingUpsertStore(VaultStore):
            """Real store whose code upserts start failing after one batch."""

            upserts_before_failure = 1

            def upsert_code_chunks(self, *args: Any, **kwargs: Any) -> None:
                if self.upserts_before_failure <= 0:
                    raise OSError("injected storage failure mid-rebuild")
                self.upserts_before_failure -= 1
                super().upsert_code_chunks(*args, **kwargs)

        from ..._store_models import CodeChunk

        dimension = int(get_config().embedding_dimension)

        def _chunks(ids: tuple[str, ...]) -> list[CodeChunk]:
            return [
                CodeChunk(
                    id=chunk_id,
                    path=f"src/{chunk_id}.py",
                    language="python",
                    content=f"value_{chunk_id} = True",
                    line_start=1,
                    line_end=1,
                    vector=[0.0] * dimension,
                )
                for chunk_id in ids
            ]

        store = FailingUpsertStore(tmp_path)
        try:
            # Publish generation A exactly as a finished run does: build
            # beside, record breadth from the store, then flip the pointer.
            derived = store.CODE_TABLE_NAME
            generation_a = generation_code_collection(derived, "a" * 32)
            store.ensure_code_table(generation_a)
            store.upsert_code_chunks(
                _chunks(("c1", "c2", "c3", "c4", "c5")),
                write_policy=None,
                collection=generation_a,
            )

            def _record_breadth() -> None:
                publish_meta_from_file_states(
                    code_meta_path(tmp_path),
                    [],
                    generation_id="a" * 32,
                    membership_epoch="membership-epoch",
                    content_epoch="content-epoch",
                    published_points_count=store.count_code(generation_a),
                )

            publish_generation_as_served(
                tmp_path, collection=generation_a, record_breadth=_record_breadth
            )

            # The torn replacement: generation B starts building beside the
            # served collection and its second upsert batch dies. Nothing
            # after the failure runs - no breadth record, no pointer move.
            generation_b = generation_code_collection(generation_a, "b" * 32)
            store.ensure_code_table(generation_b)
            with pytest.raises(OSError, match="injected storage failure"):
                for batch in (("n1", "n2"), ("n3", "n4")):
                    store.upsert_code_chunks(
                        _chunks(batch),
                        write_policy=None,
                        collection=generation_b,
                    )
        finally:
            store.close()

        serving = VaultStore(tmp_path)
        try:
            # Catches drop-then-build being reintroduced into the publication
            # flow: served data built in place would be the two-point fragment
            # here, and the verdict below would read ``shrunken``.
            assert read_served_code_collection(tmp_path) == generation_a
            assert generation_a == serving.CODE_TABLE_NAME
            live = serving.count_code()
            assert live == 5
            verdict = evaluate_index_integrity(
                tmp_path,
                PublicSourceType.CODE,
                live,
                claim_ttl_seconds=0.0,
            )
            assert verdict.verdict == VERDICT_CONSISTENT
        finally:
            serving.close()


class TestDocumentEvidenceEscalation:
    """A manifest the store no longer backs escalates instead of being trusted."""

    def _indexer(self, root: Path, store: VaultStore) -> Any:
        from ...indexer import DocumentIndexer

        return DocumentIndexer(root, model=cast("Any", None), store=store)

    def test_a_shortfall_below_the_claim_escalates(self, tmp_path: Path) -> None:
        from ...indexer._document_meta import (
            document_metadata_path,
            read_document_meta,
        )
        from ...store_runtime import VaultStore

        store = VaultStore(tmp_path)
        try:
            _seed_document_chunks(store, ("p1", "p2"))
            _write_document_manifest(tmp_path, ("p1", "p2", "p3", "p4"))
            previous = read_document_meta(document_metadata_path(tmp_path))
            assert previous is not None
            # Catches the escalation being widened with a tolerance or
            # removed: two live points under a four-point claim must escalate.
            assert self._indexer(tmp_path, store)._published_evidence_lost(previous)
        finally:
            store.close()

    def test_a_backed_claim_and_an_incomplete_manifest_do_not(
        self, tmp_path: Path
    ) -> None:
        import dataclasses

        from ...indexer._document_meta import (
            document_metadata_path,
            read_document_meta,
        )
        from ...store_runtime import VaultStore

        store = VaultStore(tmp_path)
        try:
            _seed_document_chunks(store, ("p1", "p2"))
            _write_document_manifest(tmp_path, ("p1", "p2"))
            previous = read_document_meta(document_metadata_path(tmp_path))
            assert previous is not None
            indexer = self._indexer(tmp_path, store)
            # A store that backs its claim exactly is trusted.
            assert not indexer._published_evidence_lost(previous)
            # An incomplete manifest claims nothing to hold the store to,
            # so even a huge nominal figure must not escalate - rebuilding
            # on ignorance is the storage rules' forbidden direction.
            incomplete = dataclasses.replace(
                _with_files(previous, ("p1", "p2", "p3", "p4")),
                complete=False,
            )
            assert not indexer._published_evidence_lost(incomplete)
        finally:
            store.close()


def _with_files(previous: Any, point_ids: tuple[str, ...]) -> Any:
    """Return a manifest identical to *previous* but claiming *point_ids*."""
    import dataclasses

    from ...indexer._document_meta import DocumentFileMetadata

    return dataclasses.replace(
        previous,
        files=(DocumentFileMetadata("docs/served.pdf", "hash", point_ids),),
    )
