"""The vault publication records how much breadth it serves, or publishes nothing.

A vault collection can lose most of its chunks and keep answering queries: every
surviving point is valid, so searches succeed and health stays green. The only
thing that can tell a truncated collection from a small one is a figure recorded
when the index published, so these tests hold the writer to three properties.

The figures describe the collection at the publication instant, after this run's
deletes have landed - a claim taken any earlier would outlive the corpus it
counted and read as loss forever. The figures and the document entries land in
one atomic replacement, so no reader can ever see the new entries published
without the breadth that describes them. And a publication that cannot obtain
the figures leaves the previous sidecar exactly where it was, because an index
nobody can reconcile is worse than a stale one that verifies.

No mocks, stubs, or patches: real local stores in temp directories, points
written through the production upsert path with plain zero vectors and no model,
sidecars written by the production writer, and every failure raised from a real
store subclass overriding exactly one seam.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

import pytest

from ..._index_breadth import (
    VAULT_PUBLISHED_DOCUMENTS_KEY,
    VAULT_PUBLISHED_POINTS_KEY,
    index_meta_path,
    read_vault_breadth_claim,
)
from ..._source_types import PublicSourceType

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from ...indexer import VaultIndexer
    from ...store_runtime import VaultStore

pytestmark = [pytest.mark.integration]

#: Documents and how many chunks each contributes. Deliberately uneven so the
#: point count and the document count can never coincide by accident - a writer
#: that stamped one figure into both keys would pass on a flat corpus.
_CORPUS: dict[str, int] = {"adr/first": 3, "adr/second": 1, "research/third": 2}

_TOTAL_POINTS = sum(_CORPUS.values())
_TOTAL_DOCUMENTS = len(_CORPUS)


def _seed(store: VaultStore, corpus: dict[str, int]) -> None:
    """Upsert real zero-vector chunks for *corpus* - no model involved."""
    from ..._store_models import VaultChunk
    from ...config._settings import get_config

    dimension = int(get_config().embedding_dimension)
    store.upsert_document_chunks(
        [
            VaultChunk(
                doc_id=doc_id,
                ordinal=ordinal,
                chunk_count=chunks,
                text=f"section {ordinal} of {doc_id}",
                path=f"{doc_id}.md",
                doc_type="adr",
                feature="breadth",
                date="2026-01-01",
                tags=[],
                related=[],
                title=doc_id,
                doc_content=f"body of {doc_id}" if ordinal == 0 else None,
                vector=[0.0] * dimension,
            )
            for doc_id, chunks in corpus.items()
            for ordinal in range(chunks)
        ],
        write_policy=None,
    )


def _hashes(corpus: dict[str, int]) -> dict[str, str]:
    """Return the content-hash entries a publication of *corpus* would carry."""
    return {doc_id: f"{index:0128x}" for index, doc_id in enumerate(corpus)}


def _indexer(root: Path, store: VaultStore) -> VaultIndexer:
    """Build the production indexer over a real store, with no model."""
    from ...indexer import VaultIndexer

    return VaultIndexer(root, cast("Any", None), store)


class TestPublishedBreadthDescribesTheServedCollection:
    """A landed publication carries figures matching what it serves."""

    def test_both_figures_are_recorded_and_neither_stands_in_for_the_other(
        self,
        tmp_path: Path,
        isolated_singleton_dirs: Path,
    ) -> None:
        """The sidecar names points and documents as two distinct figures."""
        del isolated_singleton_dirs
        from ...store_runtime import VaultStore

        store = VaultStore(tmp_path)
        try:
            _seed(store, _CORPUS)
            _indexer(tmp_path, store)._write_meta(_hashes(_CORPUS))

            claim = read_vault_breadth_claim(tmp_path)
            assert claim is not None
            # Catches a writer that stamps the same observation into both
            # reserved keys: the corpus is uneven, so 6 points across 3
            # documents can only be reported correctly by two real counts.
            assert claim.published_points == _TOTAL_POINTS
            assert claim.published_documents == _TOTAL_DOCUMENTS
            assert claim.named_documents == _TOTAL_DOCUMENTS
        finally:
            store.close()

    def test_the_document_entries_survive_the_reserved_keys(
        self,
        tmp_path: Path,
        isolated_singleton_dirs: Path,
    ) -> None:
        """Reserved keys stay out of the document-id set the sidecar carries."""
        del isolated_singleton_dirs
        from ...store_runtime import VaultStore

        store = VaultStore(tmp_path)
        try:
            _seed(store, _CORPUS)
            indexer = _indexer(tmp_path, store)
            indexer._write_meta(_hashes(_CORPUS))

            # Catches a reserved key chosen without the ``__`` prefix: it would
            # be read back as a document stem here and counted as a deleted
            # document on the next incremental run.
            assert indexer._load_meta() == _hashes(_CORPUS)
            raw = indexer._read_meta_raw()
            assert raw[VAULT_PUBLISHED_POINTS_KEY] == str(_TOTAL_POINTS)
            assert raw[VAULT_PUBLISHED_DOCUMENTS_KEY] == str(_TOTAL_DOCUMENTS)
        finally:
            store.close()

    def test_a_claim_never_outlives_the_corpus_it_counted(
        self,
        tmp_path: Path,
        isolated_singleton_dirs: Path,
    ) -> None:
        """A republication after a delete claims the survivors, not the dead.

        The production deletion call runs between the two publications, which
        is the ordering the writer has to respect: a figure taken before the
        delete - or carried over from the previous publication - would claim
        breadth the collection no longer holds and read as permanent loss.
        """
        del isolated_singleton_dirs
        from ...store_runtime import VaultStore

        store = VaultStore(tmp_path)
        try:
            _seed(store, _CORPUS)
            indexer = _indexer(tmp_path, store)
            indexer._write_meta(_hashes(_CORPUS))
            before = read_vault_breadth_claim(tmp_path)
            assert before is not None
            assert before.published_points == _TOTAL_POINTS

            survivors = {
                doc_id: chunks
                for doc_id, chunks in _CORPUS.items()
                if doc_id != "adr/first"
            }
            store.delete_documents(["adr/first"])
            indexer._write_meta(_hashes(survivors))

            after = read_vault_breadth_claim(tmp_path)
            assert after is not None
            # Catches the count being hoisted above the delete, or reused from
            # the previous publication: either leaves 6 stamped here while the
            # collection holds 3.
            claimed = after.published_points
            assert claimed is not None
            assert claimed == sum(survivors.values())
            assert after.published_documents == len(survivors)
            assert claimed < _TOTAL_POINTS
            assert claimed == store.count()
        finally:
            store.close()


class TestPublicationOrdering:
    """The breadth lands with the entries, never after them."""

    def test_the_figures_are_taken_before_the_new_state_is_readable(
        self,
        tmp_path: Path,
        isolated_singleton_dirs: Path,
    ) -> None:
        """Nothing can read entries whose breadth has not been recorded yet.

        The store subclass reads the sidecar from disk at the moment the second
        figure is observed. At that instant the published sidecar must still be
        the previous one, because the entries and both figures are written in a
        single atomic replacement afterwards.
        """
        del isolated_singleton_dirs
        from ...store_runtime import VaultStore

        observed: list[dict[str, object] | None] = []
        meta_path = index_meta_path(tmp_path, PublicSourceType.VAULT)

        class SidecarWatchingStore(VaultStore):
            """Real store that snapshots the sidecar as breadth is observed."""

            def get_all_ids(self) -> set[str]:
                observed.append(
                    json.loads(meta_path.read_text(encoding="utf-8"))
                    if meta_path.exists()
                    else None
                )
                return super().get_all_ids()

        store = SidecarWatchingStore(tmp_path)
        try:
            _seed(store, _CORPUS)
            indexer = _indexer(tmp_path, store)

            indexer._write_meta(_hashes(_CORPUS))
            # Catches the sidecar being written before the figures are taken:
            # the first publication would already be on disk here.
            assert observed == [None]

            survivors = dict(_CORPUS)
            del survivors["adr/second"]
            store.delete_documents(["adr/second"])
            indexer._write_meta(_hashes(survivors))

            assert len(observed) == 2
            mid_flight = observed[1]
            assert mid_flight is not None
            # The second observation must still see the first publication whole
            # - its entries and its figures - never a half-replaced sidecar.
            assert mid_flight[VAULT_PUBLISHED_POINTS_KEY] == str(_TOTAL_POINTS)
            assert mid_flight[VAULT_PUBLISHED_DOCUMENTS_KEY] == str(_TOTAL_DOCUMENTS)
            assert "adr/second" in mid_flight
        finally:
            store.close()


class TestAnUncountablePublicationLeavesThePreviousOneIntact:
    """An interruption at the reconciliation-to-publication seam publishes nothing."""

    def test_a_failed_point_count_publishes_nothing(
        self,
        tmp_path: Path,
        isolated_singleton_dirs: Path,
    ) -> None:
        del isolated_singleton_dirs
        from ...store_runtime import VaultStore

        class PointCountFailsAfterFirstPublication(VaultStore):
            """Real store whose point count dies at the publication seam."""

            counts_before_failure = 1

            def count(self) -> int:
                if self.counts_before_failure <= 0:
                    raise OSError("injected count failure at the publication seam")
                self.counts_before_failure -= 1
                return super().count()

        self._assert_previous_publication_survives(
            tmp_path, PointCountFailsAfterFirstPublication(tmp_path)
        )

    def test_a_failed_document_count_publishes_nothing(
        self,
        tmp_path: Path,
        isolated_singleton_dirs: Path,
    ) -> None:
        """The second figure is not optional: without it there is no publication.

        The point count succeeds here, so a writer that treated the document
        figure as best-effort would land a points-only sidecar over a corpus
        that had already shrunk.
        """
        del isolated_singleton_dirs
        from ...store_runtime import VaultStore

        class DocumentCountFailsAfterFirstPublication(VaultStore):
            """Real store whose document scan dies at the publication seam."""

            scans_before_failure = 1

            def get_all_ids(self) -> set[str]:
                if self.scans_before_failure <= 0:
                    raise OSError("injected scan failure at the publication seam")
                self.scans_before_failure -= 1
                return super().get_all_ids()

        self._assert_previous_publication_survives(
            tmp_path, DocumentCountFailsAfterFirstPublication(tmp_path)
        )

    def _assert_previous_publication_survives(
        self, root: Path, store: VaultStore
    ) -> None:
        """Publish once, then crash a second publication and check nothing moved."""
        try:
            _seed(store, _CORPUS)
            indexer = _indexer(root, store)
            indexer._write_meta(_hashes(_CORPUS))
            meta_path = index_meta_path(root, PublicSourceType.VAULT)
            published = meta_path.read_bytes()

            survivors = dict(_CORPUS)
            del survivors["research/third"]
            store.delete_documents(["research/third"])
            with pytest.raises(OSError, match=r"injected \w+ failure"):
                indexer._write_meta(_hashes(survivors))

            # Catches the sidecar being written from figures the writer could
            # not obtain, or from placeholder zeroes: either replaces a claim
            # that still verifies with one that cannot be reconciled at all.
            assert meta_path.read_bytes() == published
            claim = read_vault_breadth_claim(root)
            assert claim is not None
            assert claim.published_points == _TOTAL_POINTS
            assert claim.published_documents == _TOTAL_DOCUMENTS
            assert "research/third" in indexer._load_meta()
            assert not list(meta_path.parent.glob("*.tmp"))
        finally:
            store.close()


class TestAnAbsentFigureCannotTell:
    """Ignorance about breadth is never reported as a claim of zero."""

    def test_no_sidecar_yields_no_claim(self, tmp_path: Path) -> None:
        assert read_vault_breadth_claim(tmp_path) is None

    def test_a_sidecar_from_an_older_build_is_not_incomplete(
        self, tmp_path: Path
    ) -> None:
        """A sidecar predating the keys must not be read as an empty index."""
        self._write_sidecar(tmp_path, _hashes(_CORPUS))

        claim = read_vault_breadth_claim(tmp_path)
        assert claim is not None
        # Catches a parser defaulting an absent figure to zero: the collection
        # would then be judged against a claim of nothing and pass forever, or
        # - read the other way - be reported as having lost everything.
        assert claim.published_points is None
        assert claim.published_documents is None
        assert claim.named_documents == _TOTAL_DOCUMENTS

    @pytest.mark.parametrize(
        "value",
        ["", "not-a-number", "-1", -1, [], {}, 1.5],
        ids=["empty", "text", "negative-text", "negative", "list", "dict", "float"],
    )
    def test_an_unusable_figure_cannot_tell(
        self, tmp_path: Path, value: object
    ) -> None:
        """An unparsable or negative figure is ignorance, not a shortfall."""
        self._write_sidecar(
            tmp_path,
            {
                **_hashes(_CORPUS),
                VAULT_PUBLISHED_POINTS_KEY: value,
                VAULT_PUBLISHED_DOCUMENTS_KEY: value,
            },
        )

        claim = read_vault_breadth_claim(tmp_path)
        assert claim is not None
        assert claim.published_points is None
        assert claim.published_documents is None

    @pytest.mark.parametrize(("raw", "expected"), [("7", 7), (7, 7), ("0", 0)])
    def test_a_usable_figure_is_read_verbatim(
        self, tmp_path: Path, raw: object, expected: int
    ) -> None:
        """A genuine zero is a claim; only an absent figure is "cannot tell"."""
        self._write_sidecar(tmp_path, {VAULT_PUBLISHED_POINTS_KEY: raw})

        claim = read_vault_breadth_claim(tmp_path)
        assert claim is not None
        assert claim.published_points == expected

    def _write_sidecar(self, root: Path, payload: Mapping[str, object]) -> None:
        """Write a vault sidecar verbatim, as a build of any vintage would."""
        path = index_meta_path(root, PublicSourceType.VAULT)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
