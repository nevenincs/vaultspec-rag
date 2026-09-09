"""Contract checks for the archive reader, the restore refusals, and the carry.

No GPU, no managed service, nothing stubbed. The archive is a real
directory the reader actually walks, and the refusals that need to ask a
server what it already holds are driven against a real in-memory Qdrant
client - a genuine client with genuine local storage, not a stand-in for
one. The round trip that needs a supervised server lives in the
integration suite.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import pytest

from .._publication_state import acquire_publication_snapshot
from .._source_types import PublicSourceType
from ..storage_restore import (
    RestoreRequest,
    _restore_publication_proofs,
    read_archive,
    restore_archive,
)
from ._storage_archive import ARCHIVE_COLLECTION, ARCHIVE_PREFIX, write_archive

if TYPE_CHECKING:
    from pathlib import Path

    from qdrant_client import QdrantClient

pytestmark = [pytest.mark.unit]


@pytest.fixture
def memory_client() -> QdrantClient:
    """A real Qdrant client over in-memory storage.

    Every refusal asserted here is reached before any snapshot recovery, so
    the local backend's lack of a snapshot API is never exercised. What the
    client is used for - reporting which collections already exist under a
    prefix - it does for real.
    """
    from qdrant_client import QdrantClient

    return QdrantClient(":memory:")


def test_read_archive_accepts_a_complete_namespace_without_mutation(
    tmp_path: Path,
) -> None:
    archive = write_archive(tmp_path / "archive")

    read = read_archive(archive)

    assert read.prefix == ARCHIVE_PREFIX
    assert read.schema_version == 2
    assert [(item.source, item.points, item.identity) for item in read.collections] == [
        (ARCHIVE_COLLECTION, 7, None)
    ]


def test_read_archive_refuses_a_missing_snapshot_before_restore(tmp_path: Path) -> None:
    archive = write_archive(tmp_path / "archive")
    (archive / "vault.snapshot").unlink()

    with pytest.raises(RuntimeError, match="missing or empty"):
        read_archive(archive)


def test_read_archive_refuses_an_empty_snapshot_before_restore(tmp_path: Path) -> None:
    """A zero-length artifact is present but carries nothing to recover.

    Mutation: dropped the ``st_size <= 0`` half of the reader's file check.
    Observed this fail on DID NOT RAISE, the empty archive reading as
    complete and its collection offered for restore.
    """
    archive = write_archive(tmp_path / "empty-archive", snapshot=b"")

    with pytest.raises(RuntimeError, match="missing or empty"):
        read_archive(archive)


def test_read_archive_refuses_an_unparseable_completion_stamp(tmp_path: Path) -> None:
    archive = write_archive(tmp_path / "archive")
    manifest = archive / "snapshot-manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["completed_at"] = "not-a-timestamp"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="incomplete"):
        read_archive(archive)


def test_read_archive_carries_the_archived_schema_generation(tmp_path: Path) -> None:
    """Restore never converts a generation, so the reader must report the old one.

    A reader that reported the current schema version would let a restore
    stamp a destination manifest claiming a generation the recovered points
    were never written under, which is the migration behaviour this project
    declined to build.

    Mutation: returned the current storage schema version instead of the
    parsed one. Observed this fail on the assertion below, reading 2 where
    the archive recorded 1.
    """
    archive = write_archive(tmp_path / "old-archive", schema_version=1)

    assert read_archive(archive).schema_version == 1


@pytest.mark.usefixtures("isolated_status_dir")
def test_restore_rekeys_and_publishes_archived_proof(tmp_path: Path) -> None:
    archive = read_archive(write_archive(tmp_path / "archive"))
    destination = tmp_path / "destination"
    destination.mkdir()

    _restore_publication_proofs(destination, archive.publication_proofs)

    snapshot = acquire_publication_snapshot(destination, PublicSourceType.VAULT)
    assert snapshot.proof.aggregate.indexed_identities == 1
    assert snapshot.proof.aggregate.retained_points == 7
    assert snapshot.proof.compatibility_key.root_identity == str(destination.resolve())


class TestRestoreRefusesRatherThanGuesses:
    """Every ambiguity is a refusal naming its own reason, never a best effort.

    A restore that guesses is worse than one that stops: it writes into a
    namespace the operator did not mean, and the archive it came from may be
    the only remaining copy.
    """

    def test_local_mode_is_refused_before_the_archive_is_even_read(
        self, memory_client: QdrantClient, tmp_path: Path
    ) -> None:
        """A local store has one namespace and nothing to restore into.

        The archive deliberately does not exist: reaching the reader at all
        would raise instead of returning this refusal, which is what pins the
        ordering rather than merely the outcome.

        Mutation: moved the local-mode check below ``read_archive``. Observed
        this fail with RuntimeError "archive manifest is unreadable" instead
        of returning a refusal.
        """
        result = restore_archive(
            memory_client,
            RestoreRequest(
                archive_dir=tmp_path / "no-such-archive",
                destination_root=tmp_path / "destination",
                local_mode=True,
                dry_run=True,
            ),
        )

        assert result.status == "refused"
        assert result.reason == "local_mode_unsupported"
        assert result.collections == ()

    def test_a_populated_destination_is_refused_and_nothing_is_written(
        self, memory_client: QdrantClient, tmp_path: Path
    ) -> None:
        """There is no flag that overrides this; the data already there wins.

        Mutation: dropped the ``if existing:`` refusal. Observed this fail on
        the ``reason`` assertion below, reading
        ``windows_server_archive_restore_unsupported``. The status stayed
        ``refused`` because this platform refuses an applied restore anyway -
        which is why the reason, not the status, is the assertion that holds
        this guard up. Do not narrow this test to ``status``; on Windows that
        would pass with the refusal removed.
        """
        from .._store_models import root_collection_prefix

        archive = write_archive(tmp_path / "archive")
        destination_root = tmp_path / "destination"
        destination_root.mkdir()
        prefix = root_collection_prefix(destination_root)
        occupant = f"{prefix}vault_docs"
        memory_client.create_collection(collection_name=occupant, vectors_config={})

        result = restore_archive(
            memory_client,
            RestoreRequest(
                archive_dir=archive,
                destination_root=destination_root,
                local_mode=False,
                dry_run=False,
            ),
        )

        assert result.status == "refused"
        assert result.reason == "destination_exists"
        # The occupant is untouched: a refusal that had already dropped or
        # overwritten it would be the exact data loss this guard exists for.
        assert [c.name for c in memory_client.get_collections().collections] == [
            occupant
        ]

    def test_a_dry_run_names_the_destination_and_creates_nothing(
        self, memory_client: QdrantClient, tmp_path: Path
    ) -> None:
        """The preview is the only chance to check the list before committing.

        Mutation: removed the dry-run short circuit. Observed this fail with
        ``NotImplementedError: REST client is not supported`` raised from the
        snapshot recovery API - the preview had walked into the recovery call
        it must never reach. The failure lands before the assertions below
        rather than on one of them, and that is the proof: reaching the
        recovery API at all is the defect, and on this backend it cannot even
        be attempted quietly.
        """
        from .._store_models import root_collection_prefix

        archive = write_archive(tmp_path / "archive")
        destination_root = tmp_path / "destination"
        destination_root.mkdir()
        prefix = root_collection_prefix(destination_root)

        result = restore_archive(
            memory_client,
            RestoreRequest(
                archive_dir=archive,
                destination_root=destination_root,
                local_mode=False,
                dry_run=True,
            ),
        )

        assert result.status == "would_restore"
        assert result.destination_prefix == prefix
        # The archived name is re-keyed onto the destination prefix, not
        # carried across verbatim from the source namespace.
        assert result.collections == (
            ARCHIVE_COLLECTION.replace(ARCHIVE_PREFIX, prefix),
        )
        assert memory_client.get_collections().collections == []


class TestRestoreCarriesArchivedProvenance:
    """A restore creates no vectors, so it may not stamp current provenance.

    Restamping would have the manifest assert that the recovered points were
    built by this process, with this model, under this schema generation -
    none of which the restore knows or did.
    """

    def test_the_manifest_entry_carries_the_archived_identity_verbatim(
        self, isolated_status_dir: Path, tmp_path: Path
    ) -> None:
        """The archive's own record is the only honest provenance.

        Mutation: passed ``STORAGE_SCHEMA_VERSION`` and a freshly described
        identity instead of the archived ones. Observed this fail on the
        schema-generation assertion below, the entry claiming the current
        generation for points written under an older one.
        """
        del isolated_status_dir
        from .._store_models import root_collection_prefix
        from ..storage_manifest import load_manifest, record_restored_archive
        from ..store_schema import CollectionIdentity

        destination_root = tmp_path / "destination"
        destination_root.mkdir()
        prefix = root_collection_prefix(destination_root)
        name = f"{prefix}vault_docs"
        archived = CollectionIdentity(
            dense_model="archived-dense-model",
            sparse_model=None,
            dense_dim=384,
            distance="Cosine",
            dense_vector_name="dense",
            sparse_vector_name="sparse",
            storage_schema_version=1,
        )

        record_restored_archive(
            destination_root,
            storage_schema_version=1,
            collections=(name,),
            identities={name: archived},
        )

        entry = load_manifest()[prefix]
        assert entry.storage_schema_version == 1
        assert entry.collection_identity[name] == archived
        assert entry.backend == "server"

    def test_an_identity_less_archive_stays_unverifiable(
        self, isolated_status_dir: Path, tmp_path: Path
    ) -> None:
        """Absent provenance must stay absent, not be filled in helpfully.

        Every archive written so far carries no per-collection identity. A
        restore that invented one would make an unverifiable namespace look
        checked, and the survey would stop flagging it.

        Mutation: defaulted the missing identity to a described current one.
        Observed this fail on the empty-mapping assertion below.
        """
        del isolated_status_dir
        from .._store_models import root_collection_prefix
        from ..storage_manifest import load_manifest, record_restored_archive

        destination_root = tmp_path / "destination"
        destination_root.mkdir()
        prefix = root_collection_prefix(destination_root)

        record_restored_archive(
            destination_root,
            storage_schema_version=2,
            collections=(f"{prefix}vault_docs",),
            identities={},
        )

        assert load_manifest()[prefix].collection_identity == {}


@pytest.mark.usefixtures("isolated_status_dir")
class TestRetriedPartialDropStaysRestorable:
    """A namespace archived twice keeps both attempts recoverable.

    Archive-before-destroy holds at the moment of destruction and used to be
    defeated at the moment of recovery. The archive destination is fixed per
    namespace and its manifest is published in place, so the retry after a
    partial drop - the designed, recorded path once a drop fails part-way -
    surveyed only the survivor, archived only the survivor, and rewrote the
    manifest to name only the survivor. The snapshot of the collection the
    first attempt destroyed stayed on disk, named by nothing.

    Nothing downstream could notice: recovery builds its destination names,
    point counts, provenance and reported collection list from the manifest
    records alone and never compares them against the directory. The operator
    recovered half the namespace and was told it was whole.

    The archiver is driven for real here rather than described. Only the
    server is stood in for - snapshot creation is the one call a local backend
    does not implement - and the merge, the manifest, the artifacts and the
    reader are all the production ones.
    """

    @staticmethod
    def _archived_twice(tmp_path: Path) -> tuple[Path, str, str]:
        """Archive a two-collection namespace, destroy half of it, archive again.

        The exact on-disk sequence a partial drop leaves behind: both
        collections snapshotted, one destroyed by a drop that then failed, and
        the next cycle's archive seeing only what survived.
        """
        from .._store_models import root_collection_prefix
        from ..storage_manifest import record_collection_identity, record_root
        from ..storage_reclamation import archive_prefix
        from ..store_schema import CODE_COLLECTION, VAULT_COLLECTION
        from .test_storage_ops import _CycleClient, _identity

        root = tmp_path / "namespace"
        root.mkdir()
        prefix = root_collection_prefix(root)
        code, vault = prefix + CODE_COLLECTION, prefix + VAULT_COLLECTION
        record_root(root, backend="server")
        record_collection_identity(
            root,
            backend="server",
            collection=code,
            identity=_identity(dense_model="superseded/dense"),
        )
        snapshots_dir = tmp_path / "snapshots"
        archive_dir = tmp_path / "archive"
        client = _CycleClient({code: 5, vault: 7}, snapshots_dir=snapshots_dir)

        server = cast("QdrantClient", client)

        archive_prefix(
            server, prefix, snapshots_dir=snapshots_dir, archive_dir=archive_dir
        )
        # The partial drop: the loop destroyed the first collection and the
        # second one's delete failed, so the namespace survives half gone.
        client.delete_collection(collection_name=code)
        archive_prefix(
            server, prefix, snapshots_dir=snapshots_dir, archive_dir=archive_dir
        )
        return archive_dir / prefix.rstrip("_"), code, vault

    def test_the_retry_still_names_the_earlier_artifact(self, tmp_path: Path) -> None:
        """The published manifest names both collections, at their own counts.

        Read straight off disk, ahead of the reader, because this is the claim
        the reader's own refusal would otherwise mask: an overwritten manifest
        leaves an unnamed artifact beside it, and the reader refuses that, so a
        test that only called the reader would fail on a refusal rather than on
        the record that went missing.

        The counts are asserted per collection because they are what proves the
        carried record is the FIRST attempt's. Both artifacts existing says
        nothing on its own; a record describing five points for a collection
        the second attempt never counted can only have come from the first.

        Two mutations, each run alone against this test.

        Returning nothing from the merge - the overwrite this closes - fails
        the name assertion, observed reporting only the surviving collection.

        Carrying every prior record indiscriminately instead, which is what a
        merge that skipped its own rules would do, fails the same assertion
        with the survivor named twice: once for the artifact this attempt wrote
        and once for the one it replaced.
        """
        archive, code, vault = self._archived_twice(tmp_path)

        payload = json.loads(
            (archive / "snapshot-manifest.json").read_text(encoding="utf-8")
        )

        records = payload["collections"]
        assert [record["name"] for record in records] == [code, vault]
        assert {record["name"]: record["points"] for record in records} == {
            code: 5,
            vault: 7,
        }

    def test_both_attempts_artifacts_are_restorable_after_the_retry(
        self, tmp_path: Path
    ) -> None:
        """The reader offers both collections, with real bytes behind each.

        What the test above proves about the record, this proves about
        recovery: the reader accepts the directory, resolves an artifact for
        every collection, and carries the destroyed collection's provenance
        rather than degrading it to unverifiable - which is the difference
        between recovering a namespace and recovering something that merely
        resembles one.

        Two mutations, each run alone against this test.

        Returning nothing from the merge fails the collection assertion,
        observed offering only the survivor: the archive reads as complete and
        is a namespace short.

        Carrying every prior record indiscriminately fails on ``read_archive``
        refusing the manifest for naming the survivor twice, which is the
        reader's own guard against a record that cannot map to one
        destination.
        """
        archive, code, vault = self._archived_twice(tmp_path)

        read = read_archive(archive)

        assert [item.source for item in read.collections] == [code, vault]
        assert all(item.snapshot.is_file() for item in read.collections)
        assert all(item.snapshot.stat().st_size > 0 for item in read.collections)
        destroyed = next(item for item in read.collections if item.source == code)
        assert destroyed.identity is not None
        assert destroyed.identity.dense_model == "superseded/dense"


def test_read_archive_refuses_a_snapshot_its_manifest_does_not_name(
    tmp_path: Path,
) -> None:
    """An unaccounted artifact stops the recovery and is named in the refusal.

    The second guard, independent of the archiver's merge so that it holds even
    if the merge is regressed. What it prevents is not a crash: a
    manifest-driven restore would quietly recover the subset it was told about
    and report that subset as the whole namespace.

    The artifact's own name is asserted, not just the refusal. An operator who
    is stopped here has to be able to act, and a message saying only that
    something is unaccounted for names no file to go and look at.

    Mutation: removed the refusal. Observed this fail with DID NOT RAISE, the
    archive reading as complete and offering one collection for restore while a
    second artifact sat beside it.
    """
    archive = write_archive(tmp_path / "archive")
    (archive / "from-an-earlier-attempt.snapshot").write_bytes(b"snapshot")

    with pytest.raises(RuntimeError) as refusal:
        read_archive(archive)

    assert "does not name" in str(refusal.value)
    assert "from-an-earlier-attempt.snapshot" in str(refusal.value)


def test_read_archive_accepts_a_stray_file_that_is_not_a_snapshot(
    tmp_path: Path,
) -> None:
    """The refusal is scoped to artifacts that carry data, and stays scoped.

    The discriminator for the test above. A guard that refused any unlisted
    file would satisfy that test just as well while turning an operator's own
    note, left in an archive directory during a recovery, into a recovery that
    cannot proceed - a failure invented by the guard rather than found by it.

    Mutation: widened the refusal to every file the manifest does not name.
    Observed this fail on the archive being refused for a text file.
    """
    archive = write_archive(tmp_path / "archive")
    (archive / "operator-notes.txt").write_text("checked 2026", encoding="utf-8")

    assert read_archive(archive).prefix == ARCHIVE_PREFIX


@pytest.mark.usefixtures("isolated_status_dir")
def test_an_archive_that_abandoned_part_way_leaves_nothing_unaccounted_for(
    tmp_path: Path,
) -> None:
    """An abandoned attempt does not make the next complete archive unrestorable.

    The companion to the refusal, and the reason the archiver has to sweep
    rather than only publish. An attempt that raises part-way has already
    moved snapshots into the directory under no manifest at all, and the next
    attempt takes fresh ones under fresh names rather than adopting them. Left
    alone, that residue is a snapshot the published manifest does not name -
    so recovery would refuse an archive that is in fact complete, permanently,
    over a file that was never published and describes nothing the archive
    still needs.

    That is the sequence this codebase must expect rather than tolerate: a
    server too slow to finish an archive is the condition the whole reclaim
    path is built around, and the retry is its designed answer.

    Mutation: dropped the sweep and published the manifest alone. Observed
    this fail on ``read_archive`` refusing the completed archive, naming the
    abandoned attempt's snapshot.
    """
    from .._store_models import root_collection_prefix
    from ..storage_manifest import record_root
    from ..storage_reclamation import archive_prefix
    from ..store_schema import CODE_COLLECTION, VAULT_COLLECTION
    from .test_storage_ops import _CycleClient

    root = tmp_path / "namespace"
    root.mkdir()
    prefix = root_collection_prefix(root)
    code, vault = prefix + CODE_COLLECTION, prefix + VAULT_COLLECTION
    record_root(root, backend="server")
    snapshots_dir = tmp_path / "snapshots"
    archive_dir = tmp_path / "archive"
    # Sorted order reaches the code collection first, so its snapshot lands
    # before the vault one raises and the attempt is abandoned holding it.
    client = _CycleClient({code: 5, vault: 7}, snapshots_dir=snapshots_dir)
    client.aborting_snapshots = {vault}
    server = cast("QdrantClient", client)
    with pytest.raises(OSError, match="timed out"):
        archive_prefix(
            server, prefix, snapshots_dir=snapshots_dir, archive_dir=archive_dir
        )

    archive_prefix(server, prefix, snapshots_dir=snapshots_dir, archive_dir=archive_dir)

    read = read_archive(archive_dir / prefix.rstrip("_"))
    assert [item.source for item in read.collections] == [code, vault]
