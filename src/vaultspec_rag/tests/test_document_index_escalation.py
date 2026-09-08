"""A document ledger that cannot parent an incremental fails closed.

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
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, cast

import pytest

from .. import store_schema
from .._job_errors import JobError, JobErrorKind
from .._store_models import DocumentChunk, DocumentPayload
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
    RunOperation,
    RunSignature,
    RunTerminalState,
    index_run_ledger_path,
)
from ..indexer._run_ledger_runtime import RunLedger
from ..progress import NullProgressReporter
from ..store_runtime import VaultStore
from .conftest import managed_env

if TYPE_CHECKING:
    from pathlib import Path

    from ..indexer._resolved_policy import ResolvedIndexPolicy

pytestmark = [pytest.mark.unit]

#: A source the manifest still names and the working tree no longer holds, so
#: the escalated reconciliation has real work to do without encoding anything.
_DELETED_SOURCE = "guide.md"

#: An evidence generation the ledger does not hold. The sidecar cites it, and
#: nothing resolves it - the dangling reference this escalation exists for.
_DANGLING_GENERATION = "0" * 32


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
