"""Write, ingest-barrier, and destructive content operations for the vault store."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from . import store_schema
from ._store_models import (
    CodeChunk,
    VaultChunk,
    VaultDocument,
    _code_chunk_payload,
    _vault_chunk_payload,
    _vault_doc_payload,
)
from ._store_models import DocumentChunk as _DocumentChunk
from ._store_writes import (
    StoreWritePolicy,
    ensure_disk_headroom,
    run_store_operation_with_retry,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from contextlib import AbstractContextManager
    from pathlib import Path
    from uuid import UUID

    from qdrant_client import QdrantClient


logger = logging.getLogger(__name__)

from .store_runtime import INGEST_FENCE_POINT_ID, IngestVerificationError  # noqa: E402

__all__ = ["_VaultIngestMixin"]


def _point_vector(
    vector: list[float],
    sparse_indices: list[int],
    sparse_values: list[float],
) -> dict[str, Any]:
    """Build a point's vector payload: a dense vector plus an optional sparse one."""
    from qdrant_client import models

    payload: dict[str, Any] = {store_schema.DENSE_VECTOR_NAME: vector}
    if sparse_indices:
        payload[store_schema.SPARSE_VECTOR_NAME] = models.SparseVector(
            indices=sparse_indices,
            values=sparse_values,
        )
    return payload


class _VaultIngestMixin:
    """Write-side behaviour supplied to :class:`VaultStore`.

    The concrete store owns connection lifecycle, collection creation, and
    point-lock coordination. These type-checker-only declarations document
    that dependency boundary without changing the mixin's runtime behaviour.
    """

    if TYPE_CHECKING:
        TABLE_NAME: str
        DOCUMENT_TABLE_NAME: str
        _server_mode: bool
        _storage_probe_path: Path

        @property
        def client(self) -> QdrantClient: ...

        @staticmethod
        def _stable_id(string_id: str) -> int: ...

        def _code_collection(self, collection: str | None) -> str: ...

        def ensure_table(self) -> None: ...

        def ensure_code_table(self, collection: str | None = None) -> None: ...

        def ensure_document_table(self) -> None: ...

        def _point_lock(self, collection: str) -> AbstractContextManager[object]: ...

        def _point_write_lock(
            self,
            collection: str,
            policy: StoreWritePolicy | None,
        ) -> AbstractContextManager[None]: ...

        def _delete_points(self, **kwargs: Any) -> None: ...

    @staticmethod
    def _document_chunk_payload(
        chunk: _DocumentChunk,
    ) -> store_schema.DocumentChunkPayload:
        """Build the canonical document collection payload."""
        locator = chunk.payload.locator
        value = locator.value if locator is not None else None
        end = locator.end if locator is not None else None
        return {
            "document_id": chunk.id,
            "source_path": chunk.payload.source_path,
            "unit_ordinal": chunk.payload.unit_ordinal,
            "content_fingerprint": chunk.payload.content_fingerprint,
            "content": chunk.payload.content,
            "title": chunk.payload.title,
            "section": chunk.payload.section,
            "anchor": chunk.payload.anchor,
            "locator_kind": locator.kind if locator is not None else None,
            "locator_value_int": value if isinstance(value, int) else None,
            "locator_value_str": value if isinstance(value, str) else None,
            "locator_end_int": end if isinstance(end, int) else None,
            "locator_end_str": end if isinstance(end, str) else None,
            "document_metadata": chunk.payload.document_metadata.materialize(),
            "unit_metadata": chunk.payload.unit_metadata.materialize(),
            "extractor_id": chunk.payload.extractor_id,
            "extractor_version": chunk.payload.extractor_version,
        }

    def upsert_documents(
        self,
        docs: list[VaultDocument],
        *,
        write_policy: StoreWritePolicy | None,
    ) -> None:
        """Insert or update documents by ``id``.

        Args:
            docs: Documents to insert or replace.
            write_policy: Caller-owned retry/deadline policy for managed runs;
                direct store callers pass ``None``.
        """
        if not docs:
            return

        from qdrant_client import models

        points: list[Any] = []
        for doc in docs:
            points.append(
                models.PointStruct(
                    id=self._stable_id(doc.id),
                    vector=_point_vector(
                        doc.vector, doc.sparse_indices, doc.sparse_values
                    ),
                    payload=cast("dict[str, Any]", _vault_doc_payload(doc)),
                ),
            )

        self.ensure_table()
        with self._point_lock(self.TABLE_NAME):
            self._guarded_upsert(
                self.TABLE_NAME,
                points,
                "vault documents",
                write_policy=write_policy,
            )
        logger.info("Upserted %d document(s)", len(docs))

    def upsert_document_chunks(
        self,
        chunks: list[VaultChunk],
        *,
        write_policy: StoreWritePolicy | None,
        wait: bool = True,
    ) -> None:
        """Insert or update vault chunks keyed by ``doc_id#c{ordinal}``.

        The full document body travels only on the ordinal-0 chunk
        (``doc_content``) so retrieval-by-id stays exact while the
        per-chunk payload carries just its own text.

        Args:
            chunks: Vault chunks to insert or replace.
            write_policy: Caller-owned retry/deadline policy for managed runs;
                direct store callers pass ``None``.
            wait: Server-mode durability handshake. Rebuild-path callers
                pass ``False`` to acknowledge on the WAL write and must
                run :meth:`apply_ingest_barrier` before any stale purge
                or terminal metadata publish. Ignored by the embedded
                backend, which applies synchronously.
        """
        if not chunks:
            return

        from qdrant_client import models

        points: list[Any] = []
        for chunk in chunks:
            points.append(
                models.PointStruct(
                    id=self._stable_id(chunk.point_key),
                    vector=_point_vector(
                        chunk.vector, chunk.sparse_indices, chunk.sparse_values
                    ),
                    payload=cast("dict[str, Any]", _vault_chunk_payload(chunk)),
                ),
            )

        self.ensure_table()
        with self._point_lock(self.TABLE_NAME):
            self._guarded_upsert(
                self.TABLE_NAME,
                points,
                "vault chunks",
                write_policy=write_policy,
                wait=wait,
            )
        logger.info("Upserted %d vault chunk(s)", len(chunks))

    def overwrite_vault_chunk_payloads(
        self,
        chunks: list[VaultChunk],
        *,
        write_policy: StoreWritePolicy | None,
    ) -> None:
        """Replace the payloads of existing vault chunk points, keeping vectors.

        The write path for a document whose indexed metadata changed while its
        body did not. Its stored vectors still describe its body exactly, so
        re-encoding them would buy nothing; only what the payload says about
        the document is stale.

        Payloads are overwritten rather than merged. A merge would leave a
        field that has since been removed from the payload shape sitting in the
        store forever, invisible to every later write - the payload has to end
        up as though it had just been built, because that is the claim
        indexing makes about it. The payloads themselves come from the same
        builder the upsert uses, so a payload written this way and one written
        by a re-embed cannot disagree.

        Args:
            chunks: Vault chunks whose point ids already exist in the store.
                Vectors on these chunks are ignored - only payloads are sent.
            write_policy: Caller-owned retry/deadline policy for managed runs;
                direct store callers pass ``None``.
        """
        if not chunks:
            return

        ensure_disk_headroom(self._storage_probe_path)
        self.ensure_table()
        description = f"overwrite vault chunk payload in {self.TABLE_NAME}"
        with self._point_lock(self.TABLE_NAME):
            for chunk in chunks:
                payload = cast("dict[str, Any]", _vault_chunk_payload(chunk))
                point_id = self._stable_id(chunk.point_key)
                run_store_operation_with_retry(
                    lambda attempt_timeout, payload=payload, point_id=point_id: (
                        self.client.overwrite_payload(
                            collection_name=self.TABLE_NAME,
                            payload=payload,
                            points=[point_id],
                            timeout=attempt_timeout,
                        )
                    ),
                    description=description,
                    policy=write_policy,
                )
        logger.info("Rebuilt payloads for %d vault chunk(s)", len(chunks))

    def upsert_code_chunks(
        self,
        chunks: list[CodeChunk],
        *,
        write_policy: StoreWritePolicy | None,
        wait: bool = True,
        collection: str | None = None,
    ) -> None:
        """Insert or update codebase chunks by ``id``.

        Args:
            chunks: Code chunks to insert or replace.
            write_policy: Caller-owned retry/deadline policy for managed runs;
                direct store callers pass ``None``.
            wait: Server-mode durability handshake. Rebuild-path callers
                pass ``False`` to acknowledge on the WAL write and must
                run :meth:`apply_ingest_barrier` before any stale purge
                or terminal metadata publish. Ignored by the embedded
                backend, which applies synchronously.
        """
        _target = self._code_collection(collection)
        if not chunks:
            return

        from qdrant_client import models

        points: list[Any] = []
        for chunk in chunks:
            points.append(
                models.PointStruct(
                    id=self._stable_id(chunk.id),
                    vector=_point_vector(
                        chunk.vector, chunk.sparse_indices, chunk.sparse_values
                    ),
                    payload=cast("dict[str, Any]", _code_chunk_payload(chunk)),
                ),
            )

        self.ensure_code_table()
        with self._point_write_lock(_target, write_policy):
            self._guarded_upsert(
                _target,
                points,
                "code chunks",
                write_policy=write_policy,
                wait=wait,
            )
        logger.info("Upserted %d codebase chunk(s)", len(chunks))

    def upsert_document_content_chunks(
        self,
        chunks: list[_DocumentChunk],
        *,
        write_policy: StoreWritePolicy | None,
    ) -> None:
        """Insert or replace document-native chunks by deterministic ID."""
        if not chunks:
            return

        from qdrant_client import models

        points: list[Any] = []
        for chunk in chunks:
            points.append(
                models.PointStruct(
                    id=self._stable_id(chunk.id),
                    vector=_point_vector(
                        chunk.vector, chunk.sparse_indices, chunk.sparse_values
                    ),
                    payload=cast(
                        "dict[str, Any]",
                        self._document_chunk_payload(chunk),
                    ),
                )
            )

        self.ensure_document_table()
        with self._point_write_lock(self.DOCUMENT_TABLE_NAME, write_policy):
            self._guarded_upsert(
                self.DOCUMENT_TABLE_NAME,
                points,
                "document chunks",
                write_policy=write_policy,
            )
        logger.info("Upserted %d document chunk(s)", len(chunks))

    def _guarded_upsert(
        self,
        collection_name: str,
        points: list[Any],
        description: str,
        *,
        write_policy: StoreWritePolicy | None,
        wait: bool = True,
    ) -> None:
        """Upsert under the write-failure guards.

        A cheap free-disk floor check refuses the write while the store
        volume is exhausted (before Qdrant can wedge on it), then the upsert
        runs under the bounded retry: transient failures back off and retry,
        storage exhaustion raises immediately so the embedder upstream stops
        burning GPU on vectors that cannot be persisted. That distinction
        survives ``wait=False``: acknowledgement includes the WAL write, so
        exhaustion, wrong dimensions, and a missing collection still raise
        synchronously - only the apply step becomes deferred, and the ingest
        barrier is what verifies it.
        """
        ensure_disk_headroom(self._storage_probe_path)
        deferred = self._server_mode and not wait

        def attempt(attempt_timeout: int) -> object:
            if deferred:
                return self.client.upsert(
                    collection_name=collection_name,
                    points=points,
                    timeout=attempt_timeout,
                    wait=False,
                )
            return self.client.upsert(
                collection_name=collection_name,
                points=points,
                timeout=attempt_timeout,
            )

        run_store_operation_with_retry(
            attempt,
            description=f"upsert {description} into {collection_name}",
            policy=write_policy,
        )

    def apply_ingest_barrier(
        self,
        collection_name: str,
        *,
        expected_points: int,
        write_policy: StoreWritePolicy | None = None,
    ) -> None:
        """Prove every acknowledged write applied before terminal steps run.

        Server mode only; the embedded backend applies synchronously and
        returns immediately. The barrier is writer-agnostic: it fences the
        collection, not a particular caller, so any thread that upserted
        with ``wait=False`` (including a future writer-side upsert queue)
        is covered by one barrier call.

        Two steps, each replay-safe under the bounded retry:

        1. Fence: delete the reserved sentinel point id with ``wait=True``.
           Updates apply in WAL order per shard, so when this no-op returns
           every previously acknowledged update has been applied.
        2. Verify: an exact count must equal ``expected_points``. Applied
           order alone cannot catch the silent-drop class where the server
           acknowledges a batch and never applies it (no error is ever
           reported); the count does.

        Raises:
            IngestVerificationError: When the applied point count disagrees
                with the expectation - the caller's job must fail instead
                of purging stale points or publishing terminal metadata.
        """
        if not self._server_mode:
            return
        from qdrant_client import models

        run_store_operation_with_retry(
            lambda attempt_timeout: self.client.delete(
                collection_name=collection_name,
                points_selector=models.PointIdsList(
                    points=[INGEST_FENCE_POINT_ID],
                ),
                wait=True,
                timeout=attempt_timeout,
            ),
            description=f"ingest fence for {collection_name}",
            policy=write_policy,
        )
        applied = int(
            run_store_operation_with_retry(
                lambda attempt_timeout: self.client.count(
                    collection_name=collection_name,
                    exact=True,
                    timeout=attempt_timeout,
                ),
                description=f"ingest verification count for {collection_name}",
                policy=write_policy,
            ).count
        )
        if applied != expected_points:
            raise IngestVerificationError(
                f"ingest verification failed for {collection_name}: expected "
                f"{expected_points} applied point(s), found {applied}. One or "
                "more acknowledged batches did not apply; failing the run "
                "before stale-purge or metadata publish. If this collection "
                "predates the current storage schema, rebuild it with a "
                "clean re-index."
            )

    def disk_headroom_preflight(self, new_points: int) -> None:
        """Bulk-index pre-flight: fail fast when the run cannot fit on disk.

        Raises:
            InsufficientDiskSpaceError: When the estimated footprint of
                ``new_points`` plus the write floor exceeds the free space
                on the store volume.
        """
        ensure_disk_headroom(self._storage_probe_path, new_points=new_points)

    def _delete_by_payload_any(
        self,
        *,
        collection: str,
        ensure: Callable[[], None],
        key: str,
        values: Sequence[str],
    ) -> None:
        """Delete every point in *collection* whose *key* is one of *values*.

        Deleting by payload filter rather than by point id is what makes this
        shared: both callers need every point carrying the value gone, not a
        known set of ids, so neither can use an id selector.
        """
        from qdrant_client import models

        ensure()
        with self._point_lock(collection):
            self._delete_points(
                collection_name=collection,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key=key,
                                match=models.MatchAny(any=list(values)),
                            ),
                        ],
                    ),
                ),
            )

    def delete_documents(self, ids: list[str]) -> None:
        """Remove documents (every chunk) by their ``doc_id`` values.

        Deletes by payload filter rather than point id so all chunks of
        a document go together, and points written before chunking
        (whose payload also carries ``doc_id``) are removed too.

        Args:
            ids: List of document stem IDs to delete.
        """
        if not ids:
            return
        self._delete_by_payload_any(
            collection=self.TABLE_NAME,
            ensure=self.ensure_table,
            key="doc_id",
            values=ids,
        )
        logger.info("Deleted %d document(s)", len(ids))

    def delete_code_chunks(self, ids: list[str], collection: str | None = None) -> None:
        """Remove code chunks by their ``id`` values.

        Args:
            ids: List of chunk IDs to delete.
        """
        _target = self._code_collection(collection)
        if not ids:
            return
        from qdrant_client import models

        self.ensure_code_table()
        with self._point_lock(_target):
            point_ids: list[int | str | UUID] = [self._stable_id(i) for i in ids]
            self._delete_points(
                collection_name=_target,
                points_selector=models.PointIdsList(points=point_ids),
            )
        logger.info("Deleted %d code chunk(s)", len(ids))

    def delete_document_content_chunks(self, ids: list[str]) -> None:
        """Remove document-native chunks by their deterministic IDs."""
        if not ids:
            return
        from qdrant_client import models

        self.ensure_document_table()
        point_ids: list[int | str | UUID] = [self._stable_id(value) for value in ids]
        with self._point_lock(self.DOCUMENT_TABLE_NAME):
            self._delete_points(
                collection_name=self.DOCUMENT_TABLE_NAME,
                points_selector=models.PointIdsList(points=point_ids),
            )
        logger.info("Deleted %d document chunk(s)", len(ids))

    def delete_document_sources(self, source_paths: set[str]) -> None:
        """Remove every document chunk belonging to the selected sources."""
        if not source_paths:
            return
        self._delete_by_payload_any(
            collection=self.DOCUMENT_TABLE_NAME,
            ensure=self.ensure_document_table,
            key="source_path",
            values=sorted(source_paths),
        )
        logger.info("Deleted document chunks for %d source(s)", len(source_paths))
