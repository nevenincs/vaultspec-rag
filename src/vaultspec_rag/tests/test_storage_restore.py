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
from typing import TYPE_CHECKING

import pytest

from ..storage_restore import RestoreRequest, read_archive, restore_archive
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
