"""Document publication evidence that cannot certify storage fails closed.

The document sidecar and the run ledger are two independent durable records,
and only one of them has to be lost for the pair to disagree. A sidecar that
is complete, current, and fully backed by the store proves nothing about
whether the ledger still holds a generation the next incremental can build
on: the manifest is trusted, the run opens, and the open refuses because
there is no compatible parent. Every incremental then fails - the store is
intact, so the breadth check that would otherwise rebuild sees nothing wrong,
and nothing else ever repairs it.

The refusal must preserve the existing collection and manifest. The mutation
guard replaces ``full_index`` with a function that fails the test, proving the
incremental path cannot silently authorize corpus-wide work.

The canonical audit boundary is stricter still: missing or non-current ledger
state, incompatible proof ancestry, and corrupt receipts all refuse before a
backend opens. Audit authority observes proof but never creates, repairs, or
migrates it.
"""

from __future__ import annotations

import hashlib
import sqlite3
from typing import TYPE_CHECKING, Any, Never, cast

import pytest

from .. import store_schema
from .._index_integrity import audit_index_sources
from .._job_errors import JobError, JobErrorKind
from .._source_types import PublicSourceType
from .._store_models import DocumentChunk, DocumentPayload
from .._store_writes import workspace_volume_path
from ..config._types import EnvVar
from ..indexer._content_policy import ContentKind
from ..indexer._document_indexer import DocumentIndexer
from ..indexer._document_meta import (
    DOCUMENT_EMBED_SCHEMA,
    DocumentFileMetadata,
    DocumentIndexMetadata,
    document_metadata_path,
    read_document_meta,
    write_document_meta,
)
from ..indexer._run_ledger_models import (
    SCHEMA_VERSION,
    RunAuthority,
    RunOperation,
    RunSignature,
    RunTerminalState,
    index_run_ledger_path,
)
from ..indexer._run_ledger_runtime import RunLedger
from ..progress import NullProgressReporter
from ..store_runtime import VaultStore, configured_backend_identity
from .conftest import managed_env

if TYPE_CHECKING:
    from pathlib import Path

    from ..indexer._publication_proof import ProofCompatibilityKey
    from ..indexer._resolved_policy import ResolvedIndexPolicy
    from ..indexer._run_ledger_models import RunGeneration

pytestmark = [pytest.mark.unit]

#: A source the manifest still names and the working tree no longer holds, so
#: the escalated reconciliation has real work to do without encoding anything.
_DELETED_SOURCE = "guide.md"

#: An evidence generation the ledger does not hold. The sidecar cites it, and
#: nothing resolves it - the dangling reference this escalation exists for.
_DANGLING_GENERATION = "0" * 32


def _audit_ledger_path(root_dir: Path) -> Path:
    return index_run_ledger_path(workspace_volume_path(root_dir.resolve()))


def _audit_without_storage(root_dir: Path) -> dict[str, object]:
    def _forbidden_store() -> Never:
        pytest.fail("rebuild-required audit opened storage")

    return audit_index_sources(
        root_dir,
        PublicSourceType.DOCUMENT,
        RunAuthority.AUDIT_VERIFICATION,
        _forbidden_store,
    )


def _assert_document_rebuild_required(
    result: dict[str, object],
    *,
    error_kind: str,
) -> None:
    assert result["ok"] is False
    assert result["partial"] is False
    assert result["status"] == "rebuild_required"
    domains = cast("dict[str, dict[str, object]]", result["domains"])
    document = domains[PublicSourceType.DOCUMENT.value]
    assert document["ok"] is False
    assert document["status"] == "rebuild_required"
    assert document["error_kind"] == error_kind
    remediation = cast("list[str]", document["remediation"])
    assert len(remediation) == 1
    assert "--rebuild" in remediation[0]


def _seed_document_proof(
    root_dir: Path,
    *,
    generation_collection: str = store_schema.DOCUMENT_COLLECTION,
    proof_collection: str = store_schema.DOCUMENT_COLLECTION,
    proof_storage_schema: int = store_schema.STORAGE_SCHEMA_VERSION,
) -> tuple[RunLedger, ProofCompatibilityKey, RunGeneration]:
    from ..indexer._publication_proof import ProofCompatibilityKey, ProofProvenance

    backend_identity = configured_backend_identity(root_dir)
    ledger = RunLedger(_audit_ledger_path(root_dir))
    generation = ledger.start_generation(
        RunSignature(
            root_identity=str(root_dir.resolve()),
            collection_identity=generation_collection,
            source_type=ContentKind.DOCUMENT,
            operation=RunOperation.FULL,
            clean=True,
            model_identity="audit-model",
            backend_identity=backend_identity,
            dense_dimensions=8,
            embedding_schema=DOCUMENT_EMBED_SCHEMA,
            payload_schema=store_schema.STORAGE_SCHEMA_VERSION,
            content_epoch=_fingerprint("audit-content"),
            membership_epoch=_fingerprint("audit-membership"),
            preprocessing_identity=_fingerprint("audit-preprocessing"),
            configuration_fingerprint=_fingerprint("audit-configuration"),
            policy_fingerprint=_fingerprint("audit-policy"),
        )
    )
    key = ProofCompatibilityKey(
        source_type=PublicSourceType.DOCUMENT,
        root_identity=str(root_dir.resolve()),
        backend_identity=backend_identity,
        collection_identity=proof_collection,
        storage_schema=proof_storage_schema,
        payload_schema=store_schema.STORAGE_SCHEMA_VERSION,
        embedding_schema_identity=(f"audit-model:8:{DOCUMENT_EMBED_SCHEMA}"),
        chunking_schema_identity=_fingerprint("audit-preprocessing"),
        membership_identity=_fingerprint("audit-membership"),
        content_identity=_fingerprint("audit-content"),
        policy_identity=_fingerprint("audit-policy"),
    )
    with sqlite3.connect(ledger.path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            INSERT INTO publication_proofs (
                source_type, root_identity, backend_identity,
                collection_identity, storage_schema, payload_schema,
                embedding_schema_identity, chunking_schema_identity,
                membership_identity, content_identity, policy_identity,
                generation_id, revision, reservation_sequence,
                indexed_identities, retained_points, provenance,
                committed_at, verified_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 3, 5, 0, 0, ?, 1.0, 1.0)
            """,
            (
                key.source_type.value,
                key.root_identity,
                key.backend_identity,
                key.collection_identity,
                key.storage_schema,
                key.payload_schema,
                key.embedding_schema_identity,
                key.chunking_schema_identity,
                key.membership_identity,
                key.content_identity,
                key.policy_identity,
                generation.generation_id,
                ProofProvenance.VERIFIED.value,
            ),
        )
    return ledger, key, generation


def _insert_open_receipt(
    ledger: RunLedger,
    key: ProofCompatibilityKey,
    generation: RunGeneration,
    *,
    receipt_id: str,
    parent_revision: int,
) -> None:
    with sqlite3.connect(ledger.path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            INSERT INTO publication_receipts (
                receipt_id, reservation_sequence, source_type, root_identity,
                backend_identity, collection_identity, storage_schema,
                payload_schema, embedding_schema_identity,
                chunking_schema_identity, membership_identity,
                content_identity, policy_identity, generation_id,
                parent_revision, target_revision, next_mutation_ordinal,
                state, reserved_at, sealed_at, rollback_started_at,
                committed_at, rolled_back_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0,
                      'reserved', 2.0, NULL, NULL, NULL, NULL)
            """,
            (
                receipt_id,
                5,
                key.source_type.value,
                key.root_identity,
                key.backend_identity,
                key.collection_identity,
                key.storage_schema,
                key.payload_schema,
                key.embedding_schema_identity,
                key.chunking_schema_identity,
                key.membership_identity,
                key.content_identity,
                key.policy_identity,
                generation.generation_id,
                parent_revision,
                parent_revision + 1,
            ),
        )


def _fingerprint(value: str) -> str:
    return hashlib.blake2b(value.encode("utf-8")).hexdigest()


def _store_document_points(store: VaultStore, count: int) -> tuple[str, ...]:
    """Upsert real document points so the manifest's claim is fully backed."""
    dimension = store_schema.effective_dense_dim()
    chunks = [
        DocumentChunk(
            id=f"{_DELETED_SOURCE}::{ordinal}",
            payload=DocumentPayload(
                source_path=_DELETED_SOURCE,
                unit_ordinal=ordinal,
                content_fingerprint=_fingerprint(_DELETED_SOURCE),
                content=f"paragraph {ordinal}\n",
            ),
            vector=[0.1] * dimension,
        )
        for ordinal in range(count)
    ]
    store.upsert_document_content_chunks(chunks, write_policy=None)
    return tuple(chunk.id for chunk in chunks)


def _publish_manifest(
    meta_path: Path,
    policy: ResolvedIndexPolicy,
    point_ids: tuple[str, ...],
) -> None:
    """Publish a complete, current manifest citing an unresolvable generation."""
    fingerprints = policy.fingerprints_for(ContentKind.DOCUMENT)
    write_document_meta(
        meta_path,
        DocumentIndexMetadata(
            fingerprints.membership,
            fingerprints.content,
            policy.fingerprints.snapshot,
            (
                DocumentFileMetadata(
                    _DELETED_SOURCE,
                    _fingerprint(_DELETED_SOURCE),
                    point_ids,
                ),
            ),
            generation_id=_DANGLING_GENERATION,
        ),
    )


def _retire_the_only_document_generation(root_dir: Path, data_root: Path) -> RunLedger:
    """Leave the ledger holding one document generation that cannot parent.

    A parent must have succeeded, so an attempt that died before publication
    is unusable however recent it is. Together with the sidecar's unresolvable
    evidence id, this is a ledger that answers every question and can still
    parent nothing.
    """
    ledger = RunLedger(index_run_ledger_path(data_root))
    generation = ledger.start_generation(
        RunSignature(
            root_identity=str(root_dir.resolve()),
            collection_identity=store_schema.DOCUMENT_COLLECTION,
            source_type=ContentKind.DOCUMENT,
            operation=RunOperation.FULL,
            clean=False,
            model_identity="retired-model",
            backend_identity="test-backend:document-escalation",
            dense_dimensions=8,
            embedding_schema=DOCUMENT_EMBED_SCHEMA,
            payload_schema=store_schema.STORAGE_SCHEMA_VERSION,
            content_epoch=_fingerprint("content"),
            membership_epoch=_fingerprint("membership"),
            preprocessing_identity=_fingerprint("execution"),
            configuration_fingerprint=_fingerprint("configuration"),
            policy_fingerprint=_fingerprint("snapshot"),
        )
    )
    ledger.finish_generation(
        generation.generation_id,
        RunTerminalState.FAILED,
        detail="attempt died before publication",
    )
    return ledger


def test_audit_missing_ledger_requires_rebuild_without_creating_state(
    tmp_path: Path,
) -> None:
    """Creating a ledger before refusing leaves observable forbidden state."""
    before = set(tmp_path.rglob("*"))

    result = _audit_without_storage(tmp_path)

    _assert_document_rebuild_required(result, error_kind="missing")
    assert set(tmp_path.rglob("*")) == before


def test_audit_missing_proof_requires_rebuild_without_seeding(
    tmp_path: Path,
) -> None:
    """A non-seeding audit leaves both the ledger bytes and proof count exact."""
    ledger = RunLedger(_audit_ledger_path(tmp_path))
    before = ledger.path.read_bytes()

    result = _audit_without_storage(tmp_path)

    _assert_document_rebuild_required(result, error_kind="missing")
    assert ledger.path.read_bytes() == before
    with sqlite3.connect(ledger.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM publication_proofs"
        ).fetchone() == (0,)


def test_audit_old_ledger_requires_rebuild_without_migration(
    tmp_path: Path,
) -> None:
    """Reclassifying or opening an old schema breaks the typed refusal guard."""
    path = _audit_ledger_path(tmp_path)
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE old_runs (value TEXT NOT NULL)")
        connection.execute("INSERT INTO old_runs VALUES ('preserve-me')")
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION - 1}")
    before = path.read_bytes()

    result = _audit_without_storage(tmp_path)

    _assert_document_rebuild_required(
        result,
        error_kind="RunLedgerRebuildRequiredError",
    )
    assert path.read_bytes() == before
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT value FROM old_runs").fetchone() == (
            "preserve-me",
        )


def test_audit_receipt_schema_drift_requires_rebuild_without_repair(
    tmp_path: Path,
) -> None:
    """A missing required receipt index is refused and never reinstalled."""
    ledger = RunLedger(_audit_ledger_path(tmp_path))
    with sqlite3.connect(ledger.path) as connection:
        connection.execute("DROP INDEX publication_receipts_open")
    before = ledger.path.read_bytes()

    result = _audit_without_storage(tmp_path)

    _assert_document_rebuild_required(
        result,
        error_kind="RunLedgerRebuildRequiredError",
    )
    assert ledger.path.read_bytes() == before


@pytest.mark.parametrize(
    ("proof_collection", "proof_storage_schema"),
    [
        ("foreign_document_collection", store_schema.STORAGE_SCHEMA_VERSION),
        (
            store_schema.DOCUMENT_COLLECTION,
            store_schema.STORAGE_SCHEMA_VERSION + 1,
        ),
    ],
    ids=["collection", "storage-schema"],
)
def test_audit_incompatible_proof_requires_rebuild_before_storage(
    tmp_path: Path,
    proof_collection: str,
    proof_storage_schema: int,
) -> None:
    """Collection and storage-schema drift cannot reach a backend read."""
    ledger, _key, _generation = _seed_document_proof(
        tmp_path,
        proof_collection=proof_collection,
        proof_storage_schema=proof_storage_schema,
    )
    before = ledger.path.read_bytes()

    result = _audit_without_storage(tmp_path)

    _assert_document_rebuild_required(result, error_kind="incompatible")
    assert ledger.path.read_bytes() == before


def test_audit_incompatible_proof_ancestry_requires_rebuild(
    tmp_path: Path,
) -> None:
    """Skipping the proof-generation comparison opens storage and fails here."""
    ledger, _key, _generation = _seed_document_proof(
        tmp_path,
        generation_collection="foreign_document_collection",
    )
    before = ledger.path.read_bytes()

    result = _audit_without_storage(tmp_path)

    _assert_document_rebuild_required(result, error_kind="incompatible")
    assert ledger.path.read_bytes() == before


def test_audit_corrupt_open_receipt_requires_rebuild_instead_of_retry(
    tmp_path: Path,
) -> None:
    """Treating a mismatched receipt as ordinary contention fails this guard."""
    ledger, key, generation = _seed_document_proof(tmp_path)
    _insert_open_receipt(
        ledger,
        key,
        generation,
        receipt_id="corrupt-audit-receipt",
        parent_revision=4,
    )
    before = ledger.path.read_bytes()

    result = _audit_without_storage(tmp_path)

    _assert_document_rebuild_required(result, error_kind="corrupt_receipt")
    assert ledger.path.read_bytes() == before


def test_audit_malformed_open_receipt_requires_typed_corrupt_refusal(
    tmp_path: Path,
) -> None:
    """Leaking the ledger decoder's generic corruption kind fails this guard."""
    ledger, key, generation = _seed_document_proof(tmp_path)
    receipt_id = "malformed-audit-receipt"
    _insert_open_receipt(
        ledger,
        key,
        generation,
        receipt_id=receipt_id,
        parent_revision=3,
    )
    with sqlite3.connect(ledger.path) as connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            "UPDATE publication_receipts SET parent_revision = ? WHERE receipt_id = ?",
            ("not-an-integer", receipt_id),
        )
    before = ledger.path.read_bytes()

    result = _audit_without_storage(tmp_path)

    _assert_document_rebuild_required(result, error_kind="corrupt_receipt")
    assert ledger.path.read_bytes() == before


@pytest.mark.parametrize("scoped", [False, True])
def test_an_unparentable_ledger_requires_an_explicit_full_reconciliation(
    tmp_path: Path,
    scoped: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No compatible parent may broaden either incremental entry shape."""
    with managed_env(**{EnvVar.SPARSE_ENABLED.value: "false"}):
        store = VaultStore(tmp_path)
        try:
            store.ensure_document_table()
            indexer = DocumentIndexer(tmp_path, cast("Any", None), store)
            policy = indexer.resolve_policy_snapshot()
            point_ids = _store_document_points(store, 2)
            meta_path = document_metadata_path(tmp_path)
            _publish_manifest(meta_path, policy, point_ids)
            # The sidecar sits in the data root, which is also where the run
            # ledger the indexer opens lives.
            _retire_the_only_document_generation(tmp_path, meta_path.parent)

            def _forbidden_full(*_args: object, **_kwargs: object) -> None:
                pytest.fail("incremental indexing invoked full_index")

            monkeypatch.setattr(DocumentIndexer, "full_index", _forbidden_full)

            with pytest.raises(JobError) as raised:
                indexer.incremental_index(
                    reporter=NullProgressReporter(),
                    changed_paths=(tmp_path / _DELETED_SOURCE,) if scoped else None,
                )

            assert raised.value.error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
            assert store.count_document() == len(point_ids)
            assert read_document_meta(meta_path) is not None
        finally:
            store.close()
