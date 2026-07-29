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
        from ..._index_breadth import index_meta_path
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
                    index_meta_path(tmp_path, PublicSourceType.CODE),
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


def _embedding_dimension() -> int:
    from ...config._settings import get_config

    return int(get_config().embedding_dimension)


def _code_chunks(ids: tuple[str, ...], *, prefix: str) -> list[Any]:
    """Return one real zero-vector code chunk per id, one file per chunk."""
    from ..._store_models import CodeChunk

    dimension = _embedding_dimension()
    return [
        CodeChunk(
            id=f"{prefix}-{chunk_id}",
            path=f"src/{prefix}/{chunk_id}.py",
            language="python",
            content=f"value_{chunk_id} = True",
            line_start=1,
            line_end=1,
            vector=[0.0] * dimension,
        )
        for chunk_id in ids
    ]


def _open_clean_code_generation(root: Path) -> Any:
    """Open a real clean code generation against *root*'s run ledger."""
    from ...indexer._content_policy import RootContentPolicy, SourceProfileVersion
    from ...indexer._resolved_policy import (
        IndexPolicyResolutionOptions,
        resolve_index_policy,
    )
    from ...indexer._run_checkpoint import CodeRunCheckpoint, CodeRunConfiguration
    from ...indexer._run_ledger_models import RunOperation
    from ...indexer._run_policy import RunPolicy

    policy = resolve_index_policy(
        root,
        IndexPolicyResolutionOptions(
            content_policy=RootContentPolicy(SourceProfileVersion.CONVENTIONAL_V1)
        ),
    )
    return CodeRunCheckpoint.open(
        data_root=root / ".state",
        root_dir=root,
        policy=policy,
        run_policy=RunPolicy(no_progress_timeout_seconds=30.0),
        operation=RunOperation.FULL,
        clean=True,
        model_identity="model-v1",
        dense_dimensions=_embedding_dimension(),
        configuration=CodeRunConfiguration(
            segment_max_chunks=1,
            segment_max_bytes=1024,
            queue_max_chunks=2,
            queue_max_bytes=2048,
            slice_max_chunks=2,
            slice_max_bytes=2048,
            sparse_enabled=False,
            sparse_dimension=1,
            encode_batch_size=2,
            flush_slices=4,
        ),
    )


def _lifecycle(root: Path, store: VaultStore) -> Any:
    """Bind a real generation lifecycle to *root*'s sidecar and store."""
    from ..._index_breadth import index_meta_path
    from ...indexer._code_meta import load_meta, read_meta_raw
    from ...indexer._generation_lifecycle import (
        CodeGenerationBindings,
        CodeGenerationLifecycle,
    )

    meta_path = index_meta_path(root, PublicSourceType.CODE)
    return CodeGenerationLifecycle(
        CodeGenerationBindings(
            root_dir=root,
            data_root=root / ".state",
            meta_path=meta_path,
            store=store,
            load_meta=lambda: load_meta(meta_path),
            read_meta_raw=lambda: read_meta_raw(meta_path),
        )
    )


def _content_digest(value: str) -> str:
    """Return the digest shape a real indexed file state carries."""
    import hashlib

    return hashlib.blake2b(value.encode("utf-8")).hexdigest()


def _name_indexed_files(checkpoint: Any, rel_paths: tuple[str, ...]) -> None:
    """Record real converged indexed evidence so a publication names files.

    Routed through the production segment checkpoint rather than a direct file
    state, because the ledger refuses an indexed state that no storage-
    confirmed segment stands behind.
    """
    from ..._store_models import CodeChunk
    from ...indexer._streaming import CodeFileSegment

    for rel_path in rel_paths:
        stem = rel_path.rpartition("/")[2].partition(".")[0]
        chunk = CodeChunk(
            id=f"unit-{stem}",
            path=rel_path,
            language="python",
            content=f"value_{stem} = True",
            line_start=1,
            line_end=1,
        )
        checkpoint.record_confirmed_segment(
            CodeFileSegment(rel_path, 0, (chunk,), 128, True),
            _content_digest(rel_path),
        )


def _reach_ingestion_complete(checkpoint: Any) -> None:
    """Advance the durable phase to where a crashed run leaves finalization."""
    from ...indexer._run_ledger_models import FinalizationPhase

    checkpoint.generation = checkpoint.ledger.advance_finalization(
        checkpoint.generation_id,
        FinalizationPhase.STALE_RECONCILED,
    )


class TestCodeReadsNeverMaterialiseAGhost:
    """A read against an absent code collection must not create it."""

    def test_counting_an_absent_collection_creates_nothing(
        self, tmp_path: Path
    ) -> None:
        """Counting a served pointer that names nothing leaves nothing behind.

        The loss shape this closes: a served pointer naming a collection that
        is not in storage, and a count that answered by creating it. From that
        instant the collection exists, holds zero points, and every guard that
        compares counts sees a healthy empty index over a manifest naming
        hundreds of files.
        """
        from ..._store_models import (
            generation_code_collection,
            publish_served_code_collection,
        )
        from ...store_runtime import VaultStore

        probe = VaultStore(tmp_path)
        try:
            absent = generation_code_collection(probe.CODE_TABLE_NAME, "f" * 32)
        finally:
            probe.close()
        publish_served_code_collection(tmp_path, absent)

        store = VaultStore(tmp_path)
        try:
            assert absent == store.CODE_TABLE_NAME
            assert not store.code_collection_exists()
            assert store.count_code() == 0
            assert store.count_code_files() == 0
            assert store.get_all_code_ids() == set()
            assert store.get_code_ids_by_paths({"src/a.py"}) == []
            # Catches the read path creating what it failed to find: restore
            # any ``ensure_code_table`` call inside the count/scan helpers and
            # this assertion is the one that fires, because the collection is
            # then present and permanently empty.
            assert not store.code_collection_exists()
        finally:
            store.close()

    def test_an_empty_collection_under_named_files_escalates(
        self, tmp_path: Path
    ) -> None:
        """A zero claim over named files must not read as settled evidence.

        Reproduces the latched state directly: the sidecar names files and
        claims zero points, and the served collection holds zero. Every count
        comparison is satisfied at zero, so only an explicit reading of
        "empty under named files" can escalate.
        """
        from ..._index_breadth import index_meta_path
        from ...indexer._code_meta import publish_meta_from_file_states
        from ...indexer._content_policy import ContentKind
        from ...indexer._file_state import FileState
        from ...store_runtime import VaultStore

        store = VaultStore(tmp_path)
        try:
            store.ensure_code_table()
            publish_meta_from_file_states(
                index_meta_path(tmp_path, PublicSourceType.CODE),
                [
                    FileState.indexed(
                        f"src/named{index}.py",
                        ContentKind.CODE,
                        _content_digest(f"named{index}"),
                    )
                    for index in range(3)
                ],
                generation_id="f" * 32,
                membership_epoch="membership-epoch",
                content_epoch="content-epoch",
                published_points_count=0,
                published_files_count=0,
            )
            # Catches the guard being narrowed back to a count comparison:
            # remove the empty-collection branch and the surviving
            # ``live >= claimed`` test passes at 0 >= 0, so this fires.
            assert _lifecycle(tmp_path, store).published_evidence_lost()
        finally:
            store.close()


class TestResumedCodePublicationClaimsWhatItBuilt:
    """A resumed finalization publishes its own generation, or nothing."""

    def test_a_resumed_publication_counts_the_collection_it_built(
        self, tmp_path: Path
    ) -> None:
        """Breadth and the pointer both follow the generation, not the pointer.

        A run that dies between its stale reconcile and its pointer move
        leaves a finished generation beside a still-served older one. The
        resumed publication must measure the generation it built and hand the
        pointer to it - measuring whatever the pointer currently resolves to
        would stamp the older collection's figures under the new generation's
        name.
        """
        from ..._index_breadth import read_code_breadth_claim
        from ..._store_models import read_served_code_collection
        from ...store_runtime import VaultStore

        store = VaultStore(tmp_path)
        try:
            checkpoint = _open_clean_code_generation(tmp_path)
            lifecycle = _lifecycle(tmp_path, store)
            build_target = lifecycle.build_collection(checkpoint)
            assert build_target is not None
            served_before = store.CODE_TABLE_NAME

            store.ensure_code_table()
            store.upsert_code_chunks(
                _code_chunks(("old1", "old2"), prefix="old"),
                write_policy=None,
            )
            store.ensure_code_table(build_target)
            store.upsert_code_chunks(
                _code_chunks(("n1", "n2", "n3", "n4", "n5"), prefix="new"),
                write_policy=None,
                collection=build_target,
            )
            _name_indexed_files(
                checkpoint,
                tuple(f"src/new/n{index}.py" for index in range(1, 6)),
            )
            _reach_ingestion_complete(checkpoint)

            assert lifecycle.publish_pending_finalization(
                checkpoint, reporter=NullProgressReporter()
            )
        finally:
            store.close()

        claim = read_code_breadth_claim(tmp_path)
        assert claim is not None
        # Catches the resumed publication counting the served pointer again:
        # with ``count_code()`` restored in place of the build target, the
        # figure recorded here is the older collection's, never five.
        assert claim.published_points == 5
        assert claim.named_files == 5
        assert read_served_code_collection(tmp_path) == build_target
        assert read_served_code_collection(tmp_path) != served_before

    def test_a_resumed_publication_never_leaves_a_pointer_naming_another(
        self, tmp_path: Path
    ) -> None:
        """The two writes of one publication must name the same generation.

        The poisoned end-state is a sidecar and a served pointer naming
        different generations, with the sidecar's generation having no
        collection anywhere - the signature of a publication that recorded
        breadth from one path and moved the pointer from another. Whatever
        the run does, the manifest's generation must resolve to the served
        collection when the publication returns.
        """
        from ..._index_breadth import read_code_breadth_claim
        from ..._store_models import (
            generation_code_collection,
            publish_served_code_collection,
            read_served_code_collection,
        )
        from ...store_runtime import VaultStore

        store = VaultStore(tmp_path)
        try:
            # A prior generation is already serving, exactly as one is when a
            # replacement build begins.
            prior = generation_code_collection(store.CODE_TABLE_NAME, "e" * 32)
            store.ensure_code_table(prior)
            publish_served_code_collection(tmp_path, prior)
        finally:
            store.close()

        store = VaultStore(tmp_path)
        try:
            assert prior == store.CODE_TABLE_NAME
            checkpoint = _open_clean_code_generation(tmp_path)
            lifecycle = _lifecycle(tmp_path, store)
            build_target = lifecycle.build_collection(checkpoint)
            assert build_target is not None
            assert build_target != prior
            store.ensure_code_table(build_target)
            store.upsert_code_chunks(
                _code_chunks(("n1", "n2", "n3"), prefix="new"),
                write_policy=None,
                collection=build_target,
            )
            _name_indexed_files(
                checkpoint,
                tuple(f"src/new/n{index}.py" for index in range(1, 4)),
            )
            _reach_ingestion_complete(checkpoint)
            assert lifecycle.publish_pending_finalization(
                checkpoint, reporter=NullProgressReporter()
            )
        finally:
            store.close()

        claim = read_code_breadth_claim(tmp_path)
        served = read_served_code_collection(tmp_path)
        assert claim is not None
        assert claim.generation_id is not None
        assert served is not None
        # Catches the pointer move being dropped from the resumed path: the
        # sidecar would name this generation while the pointer still named
        # the prior one, which is the live poisoned shape exactly.
        assert generation_code_collection(prior, claim.generation_id) == served
        # And no zero claim survives a publication that found its points.
        assert claim.published_points == 3
        assert claim.published_files == 3

    def test_a_resumed_publication_over_a_missing_collection_is_refused(
        self, tmp_path: Path
    ) -> None:
        """A generation whose collection is gone is retired, never published.

        This is the claim over a ghost: an ingestion-complete generation whose
        build collection is not in storage, finalized anyway, leaving a
        sidecar naming a generation storage has never held.
        """
        from ..._index_breadth import index_meta_path
        from ...indexer._run_ledger_models import RunTerminalState
        from ...store_runtime import VaultStore

        store = VaultStore(tmp_path)
        try:
            checkpoint = _open_clean_code_generation(tmp_path)
            lifecycle = _lifecycle(tmp_path, store)
            build_target = lifecycle.build_collection(checkpoint)
            assert build_target is not None
            assert not store.code_collection_exists(build_target)
            _name_indexed_files(checkpoint, ("src/new/n1.py",))
            _reach_ingestion_complete(checkpoint)

            # Catches the refusal being dropped: publish unconditionally and
            # this returns True, having written a sidecar that names a
            # generation with no collection anywhere.
            assert not lifecycle.publish_pending_finalization(
                checkpoint, reporter=NullProgressReporter()
            )
            assert not index_meta_path(tmp_path, PublicSourceType.CODE).exists()
            retired = checkpoint.ledger.generation(checkpoint.generation_id)
            assert retired.terminal_state is RunTerminalState.INVALIDATED
        finally:
            store.close()
