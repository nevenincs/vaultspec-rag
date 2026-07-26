"""Guard tests for the durable record of what produced a collection.

Pure filesystem logic: no GPU, no Qdrant, no service. The managed service
directory is isolated to a temp path through the real
``VAULTSPEC_RAG_STATUS_DIR`` environment seam, as the sibling manifest tests do.

Every test here is a guard or a negative assertion, so each has been observed
failing for its intended reason before being trusted; the mutation each one
catches is named in its own comment so a later reader does not loosen it.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from .. import store_schema
from .._store_models import root_collection_prefix
from ..storage_identity import load_identity, record_identity, sidecar_path
from ..storage_manifest import (
    load_manifest,
    manifest_path,
    record_collection_identity,
    record_root,
    rekey_prefix,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ..store import VaultStore

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def isolate_manifest_dir(isolated_status_dir: Path) -> None:
    """Resolve the manifest under a temp managed dir for every test here."""
    del isolated_status_dir


def _identity(**overrides: object) -> store_schema.CollectionIdentity:
    """Build a complete identity, overriding named fields."""
    base: dict[str, object] = {
        "dense_model": "acme/dense-v1",
        "sparse_model": "acme/sparse-v1",
        "dense_dim": 1024,
        "distance": "Cosine",
        "dense_vector_name": "dense",
        "sparse_vector_name": "sparse",
        "storage_schema_version": store_schema.STORAGE_SCHEMA_VERSION,
    }
    base.update(overrides)
    return store_schema.CollectionIdentity(**base)  # type: ignore[arg-type]


def test_record_root_preserves_a_stale_schema_version(tmp_path: Path) -> None:
    """Opening a store must not relabel a stale namespace as current.

    The guard is the preserve in ``record_root``. Mutation it catches: building
    the entry with ``store_schema.STORAGE_SCHEMA_VERSION`` instead of the
    existing entry's value.

    The second call MUST pass ``last_indexed``. Without it the idempotence
    check short-circuits and returns the existing entry unwritten, so the test
    passes whether or not the preserve is present - it would be testing the
    no-op path. Passing a stamp forces the write path, which is also the one
    every real index run takes, because each stamps ``last_indexed``. An
    earlier revision of this test omitted it and was proven inert against the
    very mutation it names.
    """
    root = tmp_path / "proj"
    root.mkdir()
    record_root(root, backend="server")
    prefix = root_collection_prefix(root)

    # Write a namespace that predates the current shape generation, exactly as
    # an older release would have left it on disk.
    path = manifest_path()
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["roots"][prefix]["storage_schema_version"] = 1
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert load_manifest()[prefix].storage_schema_version == 1

    record_root(root, backend="server", last_indexed="2026-07-25T00:00:00")

    assert load_manifest()[prefix].storage_schema_version == 1


def test_record_root_preserves_stamped_identity(tmp_path: Path) -> None:
    """A store open must not drop the identity a create stamped.

    Mutation it catches: dropping ``collection_identity`` from the entry
    ``record_root`` rebuilds, which silently downgrades every later verdict for
    this namespace to ``unverifiable``.
    """
    root = tmp_path / "proj"
    root.mkdir()
    record_root(root, backend="server")
    record_collection_identity(
        root, backend="server", collection="r1_vault_docs", identity=_identity()
    )

    record_root(root, backend="server", last_indexed="2026-07-25T00:00:00")

    got = load_identity(root, backend="server", collection="r1_vault_docs")
    assert got is not None
    assert got.dense_model == "acme/dense-v1"


def test_rekey_carries_identity_rather_than_restamping(tmp_path: Path) -> None:
    """A migrate moves data; it must not launder its provenance.

    Mutation it catches: restamping ``storage_schema_version`` with the current
    constant in ``rekey_prefix``, which would let a stale namespace present as
    conforming purely by being moved.
    """
    root = tmp_path / "proj"
    root.mkdir()
    record_root(root, backend="server")
    prefix = root_collection_prefix(root)
    record_collection_identity(
        root, backend="server", collection="r1_vault_docs", identity=_identity()
    )
    path = manifest_path()
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["roots"][prefix]["storage_schema_version"] = 1
    path.write_text(json.dumps(raw), encoding="utf-8")

    entry = rekey_prefix(prefix, root=root, backend="server")

    assert entry.storage_schema_version == 1
    assert "r1_vault_docs" in entry.collection_identity


def test_local_identity_round_trips_through_the_sidecar(tmp_path: Path) -> None:
    """Local mode records identity in its own storage dir, not the manifest."""
    root = tmp_path / "proj"
    local_dir = root / ".vaultspec-rag" / "qdrant"
    local_dir.mkdir(parents=True)

    record_identity(
        root,
        backend="local",
        collection="vault_docs",
        identity=_identity(dense_model="local/dense"),
        local_dir=local_dir,
    )

    assert sidecar_path(local_dir).exists()
    got = load_identity(
        root, backend="local", collection="vault_docs", local_dir=local_dir
    )
    assert got is not None
    assert got.dense_model == "local/dense"


def test_local_identity_writes_no_manifest_entry(tmp_path: Path) -> None:
    """Local roots must stay out of the manifest the reclaimer reads.

    The survey classifies a namespace by matching manifest entries against live
    server collections; a local entry matches nothing and would present as an
    unattributable namespace. Mutation it catches: routing the local branch of
    ``record_identity`` through ``record_collection_identity``.
    """
    root = tmp_path / "proj"
    local_dir = root / ".vaultspec-rag" / "qdrant"
    local_dir.mkdir(parents=True)

    record_identity(
        root,
        backend="local",
        collection="vault_docs",
        identity=_identity(),
        local_dir=local_dir,
    )

    assert root_collection_prefix(root) not in load_manifest()


def test_second_local_stamp_preserves_the_first(tmp_path: Path) -> None:
    """Stamping one collection must not drop a sibling's record.

    Mutation it catches: writing the sidecar from a fresh dict instead of
    merging into the loaded one, which would leave only the last collection
    stamped and silently downgrade the others to ``unverifiable``.
    """
    root = tmp_path / "proj"
    local_dir = root / ".vaultspec-rag" / "qdrant"
    local_dir.mkdir(parents=True)

    record_identity(
        root,
        backend="local",
        collection="vault_docs",
        identity=_identity(dense_model="first"),
        local_dir=local_dir,
    )
    record_identity(
        root,
        backend="local",
        collection="codebase_docs",
        identity=_identity(dense_model="second"),
        local_dir=local_dir,
    )

    first = load_identity(
        root, backend="local", collection="vault_docs", local_dir=local_dir
    )
    assert first is not None
    assert first.dense_model == "first"


def test_absent_identity_reads_as_none_never_as_a_match(tmp_path: Path) -> None:
    """Absent evidence must stay absent rather than defaulting to current.

    Mutation it catches: having ``from_payload`` substitute defaults for a
    missing field, which would manufacture the provenance the type exists to
    prove and score an unstamped collection as conforming.
    """
    root = tmp_path / "proj"
    local_dir = root / ".vaultspec-rag" / "qdrant"
    local_dir.mkdir(parents=True)

    assert (
        load_identity(
            root, backend="local", collection="vault_docs", local_dir=local_dir
        )
        is None
    )
    assert store_schema.CollectionIdentity.from_payload({"dense_model": "m"}) is None
    assert store_schema.CollectionIdentity.from_payload("not-a-dict") is None


def test_unstamped_collection_is_unverifiable_not_conforming() -> None:
    """The three-verdict rule: no stamp is an unknown, never a pass.

    Mutation it catches: returning ``CONFORMING`` for a ``None`` stamp in
    ``evaluate_conformance``, which is precisely the silent-pass this mechanism
    exists to remove.
    """
    verdict = store_schema.evaluate_conformance(
        None, expected=_identity(), live_dense_dim=1024
    )
    assert verdict.verdict == store_schema.UNVERIFIABLE
    assert not verdict.is_conforming


def test_same_width_model_swap_is_nonconforming_but_not_fatal() -> None:
    """The silent case: equal width hides a different model from scoring.

    Mutation it catches: dropping the ``dense_model`` comparison, which returns
    the code to reporting a model swap as conforming. ``geometry_fatal`` is
    asserted False because refusing here would remove search for the duration
    of the rebuild that is the remedy.
    """
    verdict = store_schema.evaluate_conformance(
        _identity(dense_model="old/model"),
        expected=_identity(dense_model="new/model"),
        live_dense_dim=1024,
    )
    assert verdict.verdict == store_schema.NONCONFORMING
    assert not verdict.geometry_fatal
    assert "old/model" in verdict.reason


class TestStoreVerifiesOnEnsure:
    """End-to-end verification against a real local-mode collection.

    Local Qdrant runs in-process, so these exercise the real create, the real
    stamp, and the real geometry read-back without a service or a network.
    """

    @staticmethod
    def _open(root: Path, dim: int = 64) -> VaultStore:
        from ..store import VaultStore

        return VaultStore(root, embedding_dim=dim)

    def test_created_collection_is_conforming(self, tmp_path: Path) -> None:
        store = self._open(tmp_path)
        try:
            store.ensure_table()
            verdicts = store.conformance_verdicts()
        finally:
            store.close()

        assert verdicts["vault_docs"].verdict == store_schema.CONFORMING

    def test_width_change_refuses_at_ensure(self, tmp_path: Path) -> None:
        """A reopen at a different width must refuse before any write.

        Mutation it catches: not raising on ``geometry_fatal``. Without the
        raise the store proceeds and the disagreement resurfaces much later as
        a rejected upsert that burns the full retry budget labelled transient.
        """
        from ..store import StorageGeometryError

        store = self._open(tmp_path, dim=64)
        try:
            store.ensure_table()
        finally:
            store.close()

        reopened = self._open(tmp_path, dim=128)
        try:
            with pytest.raises(StorageGeometryError, match="128"):
                reopened.ensure_table()
        finally:
            reopened.close()

    def test_model_swap_is_nonconforming_and_does_not_raise(
        self, tmp_path: Path
    ) -> None:
        """The silent case, end to end: readable, reported, not refused.

        Mutation it catches: raising on any nonconforming verdict rather than
        only on the geometry-fatal ones, which would take search down for the
        duration of the rebuild that is the remedy.
        """
        store = self._open(tmp_path)
        local_dir = store.db_path
        try:
            store.ensure_table()
        finally:
            store.close()

        # Rewrite the stamp as an older model of identical width - the exact
        # shape that no epoch, digest, or dimension check can see.
        path = sidecar_path(local_dir)
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["collections"]["vault_docs"]["dense_model"] = "superseded/model"
        path.write_text(json.dumps(raw), encoding="utf-8")

        reopened = self._open(tmp_path)
        try:
            reopened.ensure_table()
            verdict = reopened.conformance_verdicts()["vault_docs"]
        finally:
            reopened.close()

        assert verdict.verdict == store_schema.NONCONFORMING
        assert not verdict.geometry_fatal
        assert "superseded/model" in verdict.reason

    def test_missing_stamp_is_unverifiable_and_does_not_raise(
        self, tmp_path: Path
    ) -> None:
        """A pre-upgrade collection must not degrade or block.

        Mutation it catches: treating a missing stamp as nonconforming, which
        would degrade every host on first upgrade, or as conforming, which
        restores the silent pass.
        """
        store = self._open(tmp_path)
        local_dir = store.db_path
        try:
            store.ensure_table()
        finally:
            store.close()

        sidecar_path(local_dir).unlink()

        reopened = self._open(tmp_path)
        try:
            reopened.ensure_table()
            verdict = reopened.conformance_verdicts()["vault_docs"]
        finally:
            reopened.close()

        assert verdict.verdict == store_schema.UNVERIFIABLE


def test_width_disagreement_is_fatal() -> None:
    """A width mismatch makes vectors unscorable, so it refuses.

    Mutation it catches: setting ``geometry_fatal=False`` on the width branch,
    which would let the caller degrade instead of refusing and hand Qdrant
    wrong-size vectors to reject slowly under the retry budget.
    """
    verdict = store_schema.evaluate_conformance(
        _identity(dense_dim=768), expected=_identity(dense_dim=1024), live_dense_dim=768
    )
    assert verdict.verdict == store_schema.NONCONFORMING
    assert verdict.geometry_fatal
