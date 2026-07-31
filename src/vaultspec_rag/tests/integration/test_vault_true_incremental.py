"""Each vault change class reaches the outcome it costs, and no other.

A wrong fingerprint degrades in silence. It never raises, never returns a bad
answer, and never fails an assertion that only checks the index is correct -
because it *is* correct, just paid for at hundreds of times the price. The
only assertions that can see the defect are the ones that count what the run
did rather than what it produced: whether a document re-embedded, whether its
stored vectors moved, whether the classification reached the encoder at all.

Every guard here has been driven red by the mutation named in its docstring
and restored green in one sequence; the mutations are recorded so a later
reader can repeat them instead of loosening an assertion whose narrowness
looks accidental.

Real GPU + real Qdrant, no mocks/skips, per the project test mandate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import TypeAdapter, ValidationError
from vaultspec_core.config import (
    reset_config,
)
from vaultspec_core.vaultcore import (
    scan_vault,
)

from ...config._settings import get_config
from ...config._settings import reset_config as reset_rag_config
from ...progress import NullProgressReporter
from ...synthetic import build_synthetic_vault

if TYPE_CHECKING:
    from pathlib import Path

    from ...embeddings import EmbeddingModel
    from ...indexer import VaultIndexer
    from ...store_runtime import VaultStore

pytestmark = [pytest.mark.integration]

_TAG_LIST = TypeAdapter(list[str])


def _write_preserving_newlines(path: Path, text: str) -> None:
    """Write *text* verbatim.

    The default translates every ``\\n`` to ``os.linesep``, which reflows the
    whole file on Windows. A guard for "only the stamp moved" that silently
    rewrote every line of the document would be testing something else.
    """
    path.write_text(text, encoding="utf-8", newline="")


def _bump_stamp(path: Path, stamp: str) -> None:
    """Insert or refresh ``modified:`` in *path*'s frontmatter, nothing else."""
    text = path.read_text(encoding="utf-8")
    end = text.index("\n---\n", 4)
    head, tail = text[4:end], text[end:]
    lines = [line for line in head.splitlines() if not line.startswith("modified:")]
    lines.append(f"modified: '{stamp}'")
    _write_preserving_newlines(path, "---\n" + "\n".join(lines) + tail)


def _add_tag(path: Path, tag: str) -> None:
    """Append one entry to the frontmatter ``tags:`` list, and nothing else.

    Anchored on the ``tags:`` key rather than on the list-item prefix, because
    ``related:`` is a list too - appending after the last ``  - `` line would
    quietly edit the wrong field and prove nothing about tags.
    """
    text = path.read_text(encoding="utf-8")
    end = text.index("\n---\n", 4)
    head, tail = text[4:end], text[end:]
    lines = head.splitlines()
    lines.insert(lines.index("tags:") + 1, f"  - '{tag}'")
    _write_preserving_newlines(path, "---\n" + "\n".join(lines) + tail)


def _delete_one_chunk(store: VaultStore, doc_id: str, ordinal: int) -> None:
    """Remove exactly one stored chunk point, fabricating a damaged collection.

    Reaches the store's point deletion directly because no production path
    removes a single interior ordinal - which is the point: the state being
    fabricated is one the indexer must survive, not one it creates.
    """
    from qdrant_client import models

    store.ensure_table()
    store._delete_points(
        collection_name=store.TABLE_NAME,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="doc_id",
                        match=models.MatchValue(value=doc_id),
                    ),
                    models.FieldCondition(
                        key="chunk_ordinal",
                        match=models.MatchValue(value=ordinal),
                    ),
                ],
            ),
        ),
    )


def _doc_id(path: Path, docs_dir: Path) -> str:
    """Mirror the indexer's path -> doc-id scheme for assertions."""
    rel = str(path.relative_to(docs_dir)).replace("\\", "/")
    return rel.rsplit(".", 1)[0] if "." in rel else rel


def _stored_vectors(store: VaultStore, doc_id: str) -> dict[str, list[float]]:
    """Return the dense vector of every stored chunk of *doc_id*.

    Read through the donor path because it is the one store read that returns
    vectors, which is precisely what must be proven not to have moved.
    """
    counts = store.get_chunk_counts(doc_ids={doc_id})
    keys = [f"{doc_id}#c{ordinal}" for ordinal in range(counts.get(doc_id, 0))]
    points = store.retrieve_donor_points(store.TABLE_NAME, keys)
    return {key: list(point.dense) for key, point in points.items()}


def _stored_payload(store: VaultStore, doc_id: str) -> dict[str, object]:
    """Return the ordinal-0 payload of *doc_id* as the store holds it."""
    points = store.retrieve_donor_points(store.TABLE_NAME, [f"{doc_id}#c0"])
    return dict(points[f"{doc_id}#c0"].payload)


def _stored_tags(store: VaultStore, point_key: str) -> list[str]:
    """Return the tag list a stored point carries.

    Narrowed rather than asserted against directly, so a payload whose tags
    came back as something other than a list of strings fails as that, instead
    of as a confusing membership error inside a guard about refreshing.
    """
    points = store.retrieve_donor_points(store.TABLE_NAME, [point_key])
    payload: dict[str, object] = dict(points[point_key].payload)
    raw_tags: object = payload.get("tags")
    try:
        return _TAG_LIST.validate_python(raw_tags, strict=True)
    except ValidationError as exc:
        raise AssertionError(f"{point_key} has no tag list: {raw_tags!r}") from exc


def _build_vault(
    root: Path, model: EmbeddingModel, *, n_docs: int = 6
) -> tuple[VaultStore, VaultIndexer]:
    """Build and fully index a small synthetic vault at *root*."""
    from ... import VaultIndexer
    from ...store_runtime import VaultStore

    reset_config()
    reset_rag_config()
    build_synthetic_vault(root, n_docs=n_docs, seed=13)
    store = VaultStore(root)
    indexer = VaultIndexer(root, model, store)
    indexer.full_index(reporter=NullProgressReporter())
    return store, indexer


class TestStampOnlyChangeIsFree:
    """A ``modified:`` bump reaches neither the encoder nor the store."""

    @pytest.mark.timeout(300)
    def test_a_stamp_bump_drives_no_work_at_all(
        self, embedding_model: EmbeddingModel, tmp_path: Path
    ) -> None:
        """Mutation that drives this red: weaken the fingerprint back to a raw
        whole-file digest - in ``_vault_fingerprint.fingerprint_text``, return
        ``raw`` instead of the encoded split. The ``updated == 0`` assertion
        then fails with ``updated == 6``, because every stamped document reads
        as modified.
        """
        store, indexer = _build_vault(tmp_path, embedding_model)
        try:
            paths = sorted(scan_vault(tmp_path))
            docs_dir = tmp_path / get_config().docs_dir
            sampled = _doc_id(paths[0], docs_dir)
            vectors_before = _stored_vectors(store, sampled)
            assert vectors_before, "the sampled document must have stored vectors"

            for path in paths:
                _bump_stamp(path, "2026-07-29")

            result = indexer.incremental_index(reporter=NullProgressReporter())

            assert result.updated == 0, (
                "a modified-stamp bump re-embedded documents; the fingerprint "
                "is seeing volatile frontmatter it must not see"
            )
            assert result.payload_updated == 0, (
                "a modified-stamp bump reached the store; the stamp is not in "
                "any payload, so nothing about it can be stale"
            )
            assert result.added == 0
            assert result.removed == 0
            assert _stored_vectors(store, sampled) == vectors_before
        finally:
            store.close()

    @pytest.mark.timeout(300)
    def test_the_stamp_bump_is_still_recorded_in_the_sidecar(
        self, embedding_model: EmbeddingModel, tmp_path: Path
    ) -> None:
        """Unchanged is a classification, not a refusal to look.

        The sidecar must still absorb the new bytes, or every later run
        re-derives the same "unchanged" answer from the same stale entry, and
        the stat gate can never short-circuit it.
        """
        store, indexer = _build_vault(tmp_path, embedding_model)
        try:
            paths = sorted(scan_vault(tmp_path))
            docs_dir = tmp_path / get_config().docs_dir
            sampled = _doc_id(paths[0], docs_dir)
            before = indexer._load_meta()[sampled]

            for path in paths:
                _bump_stamp(path, "2026-07-29")
            indexer.incremental_index(reporter=NullProgressReporter())

            assert indexer._load_meta()[sampled] != before
        finally:
            store.close()


class TestMetadataOnlyChangeSkipsTheGpu:
    """A tags-only edit refreshes payloads and leaves vectors byte-identical."""

    @pytest.mark.timeout(300)
    def test_a_tag_edit_updates_payloads_without_re_embedding(
        self, embedding_model: EmbeddingModel, tmp_path: Path
    ) -> None:
        """Mutation that drives this red: route metadata into the re-embed
        branch - in ``_vault_indexer._classify_documents``, add
        ``VaultDelta.METADATA`` results to ``body`` instead of ``metadata``.
        The ``updated == 0`` assertion then fails with ``updated == 1``.
        """
        store, indexer = _build_vault(tmp_path, embedding_model)
        try:
            paths = sorted(scan_vault(tmp_path))
            docs_dir = tmp_path / get_config().docs_dir
            target = paths[0]
            target_id = _doc_id(target, docs_dir)
            vectors_before = _stored_vectors(store, target_id)
            assert vectors_before

            _add_tag(target, "#late-curation")

            result = indexer.incremental_index(reporter=NullProgressReporter())

            assert result.payload_updated == 1, (
                "a tags-only edit did not take the payload-only branch"
            )
            assert result.updated == 0, (
                "a tags-only edit re-embedded; the body digest is seeing "
                "frontmatter it must not see"
            )
            assert _stored_vectors(store, target_id) == vectors_before, (
                "the payload-only branch moved the stored vectors"
            )
            assert "#late-curation" in _stored_tags(store, f"{target_id}#c0"), (
                "the payload-only branch did not refresh what it exists to refresh"
            )
        finally:
            store.close()

    @pytest.mark.timeout(300)
    def test_a_multi_chunk_document_counts_as_one_document(
        self, embedding_model: EmbeddingModel, tmp_path: Path
    ) -> None:
        """``payload_updated`` names documents, and a document is not a chunk.

        The branch writes one store call per chunk, so the chunk list was the
        nearest number to hand and reporting it read correctly for every
        single-chunk document - which is most of them. This pins the figure
        against a document that splits, where the two disagree.
        """
        store, indexer = _build_vault(tmp_path, embedding_model)
        try:
            docs_dir = tmp_path / get_config().docs_dir
            wide = docs_dir / "adr" / "many-chunked-decision.md"
            body = "\n\n".join(
                f"## section {index}\n\n" + ("filler prose about storage. " * 60)
                for index in range(6)
            )
            _write_preserving_newlines(
                wide,
                "---\ntags:\n  - '#adr'\n  - '#wide'\n"
                "date: '2026-07-29'\nrelated:\n  []\n---\n\n"
                f"# many chunked decision\n\n{body}\n",
            )
            indexer.incremental_index(reporter=NullProgressReporter())
            chunk_count = store.get_chunk_counts(
                doc_ids={"adr/many-chunked-decision"},
            )["adr/many-chunked-decision"]
            assert chunk_count > 1, (
                "the fixture document must split, or this proves nothing"
            )

            _add_tag(wide, "#late-curation")
            result = indexer.incremental_index(reporter=NullProgressReporter())

            assert result.payload_updated == 1, (
                f"reported {result.payload_updated} documents for one document "
                f"of {chunk_count} chunks"
            )
            refreshed = store.retrieve_donor_points(
                store.TABLE_NAME,
                [f"adr/many-chunked-decision#c{n}" for n in range(chunk_count)],
            )
            assert len(refreshed) == chunk_count
            for key in refreshed:
                assert "#late-curation" in _stored_tags(store, key), (
                    f"{key} kept a stale payload; the refresh missed a chunk"
                )
        finally:
            store.close()

    @pytest.mark.timeout(300)
    def test_a_punctured_ordinal_range_re_embeds_instead(
        self, embedding_model: EmbeddingModel, tmp_path: Path
    ) -> None:
        """A document missing a point in the middle must not take this branch.

        The payload-only write addresses points by assumed ordinal. Against a
        missing ordinal it reaches nothing and raises nothing, so the document
        would keep a stale payload forever with every count agreeing. The
        stored-chunk-count reading cannot see this - it is the highest ordinal
        plus one, so a hole reports the same number as a whole document - which
        is why the check reads the exact stored ordinals instead.

        Mutation that drives this red: in ``_plan_payload_refresh``, compare
        the highest stored ordinal plus one against the chunk count instead of
        comparing the ordinal set itself - the count-based reading this check
        replaced. The punctured document is then accepted onto the payload
        branch and ``payload_updated == 0`` fails with ``payload_updated == 1``.

        Note that comparing set *size* rather than the set does NOT drive it
        red: a hole makes the size disagree too. Only the max-plus-one reading
        is blind to an interior gap, which is exactly why it was the defect.
        """
        store, indexer = _build_vault(tmp_path, embedding_model)
        try:
            docs_dir = tmp_path / get_config().docs_dir
            wide = docs_dir / "adr" / "punctured-decision.md"
            body = "\n\n".join(
                f"## part {index}\n\n" + ("prose about retention. " * 60)
                for index in range(12)
            )
            _write_preserving_newlines(
                wide,
                "---\ntags:\n  - '#adr'\n  - '#punctured'\n"
                "date: '2026-07-29'\nrelated:\n  []\n---\n\n"
                f"# punctured decision\n\n{body}\n",
            )
            indexer.incremental_index(reporter=NullProgressReporter())
            doc_id = "adr/punctured-decision"
            ordinals = store.get_stored_chunk_ordinals({doc_id})[doc_id]
            assert len(ordinals) > 2, "the fixture must split, or this proves nothing"

            # Punch a hole: drop exactly one middle ordinal, leaving the
            # range's reach unchanged so the count-based reading still reports
            # a whole document. Deleting the point directly rather than
            # re-upserting survivors, because the survivors would have to be
            # re-encoded to be written back and this is about the store's
            # shape, not about vectors.
            hole = sorted(ordinals)[1]
            _delete_one_chunk(store, doc_id, hole)
            punctured = store.get_stored_chunk_ordinals({doc_id})[doc_id]
            assert hole not in punctured
            assert store.get_chunk_counts(doc_ids={doc_id})[doc_id] == len(ordinals), (
                "the count reading must still look whole, or the hole is "
                "detectable without reading the ordinals and this proves nothing"
            )

            _add_tag(wide, "#late-curation")
            result = indexer.incremental_index(reporter=NullProgressReporter())

            assert result.payload_updated == 0, (
                "a punctured document took the payload-only branch, where the "
                "write cannot reach its missing point"
            )
            assert result.updated == 1, (
                "a punctured document was neither payload-refreshed nor "
                "re-embedded; its stale payload has no path back"
            )
            assert store.get_stored_chunk_ordinals({doc_id})[doc_id] == ordinals, (
                "the re-embed did not restore the missing point"
            )
        finally:
            store.close()

    @pytest.mark.timeout(300)
    def test_an_untouched_document_keeps_its_payload(
        self, embedding_model: EmbeddingModel, tmp_path: Path
    ) -> None:
        """The refresh is scoped to the document that changed."""
        store, indexer = _build_vault(tmp_path, embedding_model)
        try:
            paths = sorted(scan_vault(tmp_path))
            docs_dir = tmp_path / get_config().docs_dir
            target, other = paths[0], paths[1]
            other_id = _doc_id(other, docs_dir)
            payload_before = _stored_payload(store, other_id)

            _add_tag(target, "#late-curation")
            indexer.incremental_index(reporter=NullProgressReporter())

            assert _stored_payload(store, other_id) == payload_before
        finally:
            store.close()


class TestBodyChangeStillReEmbeds:
    """The branch that must keep costing what it costs."""

    @pytest.mark.timeout(300)
    def test_a_body_edit_re_embeds_the_document(
        self, embedding_model: EmbeddingModel, tmp_path: Path
    ) -> None:
        """Mutation that drives this red: drop the body from the fingerprint -
        in ``_vault_fingerprint.fingerprint_text``, digest a constant instead
        of ``normalized``. The ``updated == 1`` assertion then fails with
        ``updated == 0``, and the vectors stay stale against the new body.
        """
        store, indexer = _build_vault(tmp_path, embedding_model)
        try:
            paths = sorted(scan_vault(tmp_path))
            docs_dir = tmp_path / get_config().docs_dir
            target = paths[0]
            target_id = _doc_id(target, docs_dir)
            vectors_before = _stored_vectors(store, target_id)
            assert vectors_before

            _write_preserving_newlines(
                target,
                target.read_text(encoding="utf-8")
                + "\n\nA sentence about orbital mechanics and tidal locking.\n",
            )

            result = indexer.incremental_index(reporter=NullProgressReporter())

            assert result.updated == 1, (
                "a body edit did not re-embed; the stored vectors no longer "
                "describe the document"
            )
            assert result.payload_updated == 0, (
                "a body edit took the payload-only branch, leaving stale vectors behind"
            )
            assert _stored_vectors(store, target_id) != vectors_before
        finally:
            store.close()


class TestOneBadByteCannotWedgeIndexing:
    """A file the fingerprint cannot decode must not abort the run."""

    @pytest.mark.timeout(300)
    def test_an_undecodable_document_is_skipped_not_fatal(
        self, embedding_model: EmbeddingModel, tmp_path: Path
    ) -> None:
        """The fingerprint reads and parses; the digest it replaced only hashed.

        A decode error raised from the fingerprint escapes the hashing phase,
        whose per-file failure capture catches ``OSError`` alone, and aborts the
        whole run - then aborts every retry while the file remains, so indexing
        stays wedged until an operator finds one byte. Before the split
        fingerprint such a file hashed fine and was skipped at the parse phase.

        Mutation that drives this red: in ``fingerprint_bytes``, decode without
        catching ``UnicodeDecodeError``. This test then fails with that
        exception escaping ``incremental_index``.
        """
        store, indexer = _build_vault(tmp_path, embedding_model)
        try:
            docs_dir = tmp_path / get_config().docs_dir
            good = docs_dir / "adr" / "still-indexable.md"
            _write_preserving_newlines(
                good,
                "---\ntags:\n  - '#adr'\n  - '#survivor'\n"
                "date: '2026-07-29'\nrelated:\n  []\n---\n\n"
                "# still indexable\n\nThis one decodes perfectly well.\n",
            )
            broken = docs_dir / "adr" / "one-bad-byte.md"
            broken.write_bytes(
                b"---\ntags:\n  - '#adr'\n  - '#broken'\n"
                b"date: '2026-07-29'\nrelated:\n  []\n---\n\n"
                b"# one bad byte\n\nA caf\xe9 encoded as cp1252.\n"
            )

            # Reaching this line at all is most of the assertion: the run
            # completed instead of raising out of the hashing phase.
            result = indexer.incremental_index(reporter=NullProgressReporter())

            stored = store.get_all_ids()
            assert "adr/still-indexable" in stored, (
                "the decodable new document was not indexed; the undecodable "
                "one took the run down with it"
            )
            assert "adr/one-bad-byte" not in stored, (
                "an undecodable document reached the store"
            )
            # ``added`` counts documents the sidecar had not seen, which
            # includes the undecodable one - it fingerprints fine and is only
            # dropped later, at the parse phase. That over-count predates the
            # split fingerprint (the raw-bytes digest hashed such files too),
            # so it is recorded here rather than asserted away.
            assert result.added == 2

            # And again: a wedged run fails identically on every retry, so one
            # clean pass is not enough to prove the wedge is gone.
            repeat = indexer.incremental_index(reporter=NullProgressReporter())

            assert store.get_all_ids() == stored, "the retry disturbed the index"
            # The undecodable file stays in the "new" set on every run, because
            # that set is the difference against the *store*, which it can never
            # enter. So it is re-parsed and re-skipped each run - one file's
            # worth of work, bounded and constant, and the same before the split
            # fingerprint. What matters is that it never re-embeds anything and
            # never grows.
            assert repeat.added == 1
            assert repeat.updated == 0
            assert repeat.payload_updated == 0
        finally:
            store.close()


class TestUnscopedEscalationConverges:
    """The watcher's escalation converges without re-embedding the corpus."""

    @pytest.mark.timeout(600)
    def test_an_unscoped_pass_over_a_churned_corpus_re_embeds_only_real_edits(
        self, embedding_model: EmbeddingModel, tmp_path: Path
    ) -> None:
        """A failed watcher attempt escalates the next run to an unscoped pass
        over the whole corpus. That pass is this call - ``changed_paths=None``
        is exactly what the escalation hands the indexer - so what it costs is
        what an escalation costs.

        Mutation that drives this red: the same fingerprint weakening as the
        stamp guard. ``updated == 1`` then fails with ``updated == 6``.
        """
        store, indexer = _build_vault(tmp_path, embedding_model)
        try:
            paths = sorted(scan_vault(tmp_path))
            edited = paths[0]

            for path in paths:
                _bump_stamp(path, "2026-07-29")
            _write_preserving_newlines(
                edited,
                edited.read_text(encoding="utf-8") + "\n\nA genuine body edit.\n",
            )

            result = indexer.incremental_index(
                reporter=NullProgressReporter(),
                changed_paths=None,
            )

            assert result.updated == 1, (
                "the unscoped convergence pass re-embedded documents whose "
                "bodies never moved"
            )
            assert result.added == 0
            assert result.removed == 0
        finally:
            store.close()

    @pytest.mark.timeout(600)
    def test_the_pass_still_converges_the_whole_corpus(
        self, embedding_model: EmbeddingModel, tmp_path: Path
    ) -> None:
        """Narrowing the work must not narrow the convergence guarantee.

        The escalation exists because a failed attempt leaves unknown state.
        An unscoped pass must therefore still reconcile documents nobody told
        it about - including one added and one removed behind its back.
        """
        store, indexer = _build_vault(tmp_path, embedding_model)
        try:
            docs_dir = tmp_path / get_config().docs_dir
            paths = sorted(scan_vault(tmp_path))
            removed_id = _doc_id(paths[0], docs_dir)
            paths[0].unlink()
            added = docs_dir / "adr" / "unannounced-arrival.md"
            _write_preserving_newlines(
                added,
                "---\ntags:\n  - '#adr'\n  - '#arrival'\n"
                "date: '2026-07-29'\nrelated:\n  []\n---\n\n"
                "# unannounced arrival\n\nNobody told the watcher about this.\n",
            )

            result = indexer.incremental_index(
                reporter=NullProgressReporter(),
                changed_paths=None,
            )

            assert result.added == 1
            assert result.removed == 1
            stored = store.get_all_ids()
            assert "adr/unannounced-arrival" in stored
            assert removed_id not in stored
        finally:
            store.close()
