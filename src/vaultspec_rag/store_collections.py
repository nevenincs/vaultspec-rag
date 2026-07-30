"""Collection schema, identity, and manifest operations for the vault store."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, TypedDict, cast

from . import store_schema

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable, Sequence
    from contextlib import AbstractContextManager

    from qdrant_client import QdrantClient
    from qdrant_client.http.models import (
        OptimizersConfigDiff,
        QuantizationConfig,
        WalConfigDiff,
    )

    from ._store_locks import ReentrantLock


logger = logging.getLogger(__name__)

from .store_runtime import (  # noqa: E402
    StorageGeometryError,
    suppress_local_qdrant_warnings,
)

__all__ = ["_VaultCollectionMixin"]


class _CreateCollectionExtras(TypedDict, total=False):
    """The optional ``create_collection`` keyword arguments this store sets."""

    quantization_config: QuantizationConfig
    wal_config: WalConfigDiff
    optimizers_config: OptimizersConfigDiff


class _VaultCollectionMixin:
    """Collection behaviour supplied to :class:`VaultStore`.

    The concrete store owns the client, locks, and lifecycle state. These
    type-checker-only declarations make that dependency explicit without
    introducing runtime shadow implementations in the mixin.
    """

    if TYPE_CHECKING:
        TABLE_NAME: str
        CODE_TABLE_NAME: str
        DOCUMENT_TABLE_NAME: str
        root_dir: pathlib.Path
        db_path: pathlib.Path | str
        _server_mode: bool
        _embedding_dim: int
        _ensured: dict[str, bool]
        _conformance: dict[str, store_schema.ConformanceVerdict]
        _manifest_recorded: bool
        _lifecycle_lock: ReentrantLock

        @property
        def client(self) -> QdrantClient: ...

        def _collection_exists(self, name: str) -> bool: ...

        def _create_payload_index(
            self,
            collection_name: str,
            field_name: str,
            field_schema: Any,
        ) -> None: ...

        def _point_lock(self, collection: str) -> AbstractContextManager[object]: ...

    def _ensure_collection(self, name: str) -> None:
        """Create a collection with dense + sparse vectors if it doesn't exist.

        Args:
            name: Qdrant collection name to create.
        """
        from qdrant_client import models

        from .config._settings import get_config

        cfg = get_config()
        quantization_val = cfg.qdrant_quantization

        quantization_config = None
        if quantization_val:
            val = str(quantization_val).lower().strip()
            if val in ("scalar", "int8", "scalar_int8"):
                quantization_config = models.ScalarQuantization(
                    scalar=models.ScalarQuantizationConfig(
                        type=models.ScalarType.INT8,
                        always_ram=True,
                    )
                )
            elif val in ("turbo", "turboquant"):
                quantization_config = models.TurboQuantization(
                    turbo=models.TurboQuantQuantizationConfig(
                        always_ram=True,
                    )
                )
            elif val in ("product", "pq"):
                quantization_config = models.ProductQuantization(
                    product=models.ProductQuantizationConfig(
                        compression=models.CompressionRatio.X16,
                        always_ram=True,
                    )
                )

        with self._lifecycle_lock:
            if self._collection_exists(name):
                return

            kwargs: _CreateCollectionExtras = {}
            if quantization_config is not None:
                kwargs["quantization_config"] = quantization_config
            if self._server_mode:
                # Bound per-collection preallocation. The geometry itself is
                # declared in store_schema because the storage domain
                # reconciles pre-existing collections toward the same target;
                # local mode has no WAL/segment preallocation to bound.
                kwargs["wal_config"] = models.WalConfigDiff(
                    wal_capacity_mb=store_schema.SERVER_WAL_CAPACITY_MB
                )
                kwargs["optimizers_config"] = models.OptimizersConfigDiff(
                    default_segment_number=store_schema.SERVER_SEGMENT_NUMBER
                )

            self.client.create_collection(
                collection_name=name,
                vectors_config={
                    store_schema.DENSE_VECTOR_NAME: models.VectorParams(
                        size=self._embedding_dim,
                        distance=models.Distance(store_schema.DENSE_DISTANCE),
                    ),
                },
                sparse_vectors_config={
                    store_schema.SPARSE_VECTOR_NAME: models.SparseVectorParams(),
                },
                **kwargs,
            )
            # Stamped here, inside the create, because this is the only moment
            # the process writing the vectors and the record of what wrote them
            # are guaranteed to agree. Anywhere later and the configuration may
            # already have moved.
            self._stamp_identity(name)
        logger.info("Created collection '%s' at %s", name, self.db_path)

    def _stamp_identity(self, collection: str) -> None:
        """Record what this process used to build ``collection``.

        The width comes from ``self._embedding_dim`` - the value the collection
        was actually created with - rather than from config, which the store may
        have been constructed to override. A stamp that recorded the config
        instead would describe a collection nobody built.
        """
        import dataclasses

        from .storage_identity import record_identity

        record_identity(
            self.root_dir,
            backend="server" if self._server_mode else "local",
            collection=collection,
            identity=dataclasses.replace(
                store_schema.current_identity(), dense_dim=self._embedding_dim
            ),
            local_dir=None if self._server_mode else self.db_path,
        )

    def _delete_collection_hard(self, name: str) -> None:
        """Delete a collection so a same-name recreate cannot resurrect points.

        In local mode qdrant-client's ``delete_collection`` pops the in-memory
        collection and calls ``shutil.rmtree(..., ignore_errors=True)`` but never
        closes the collection's sqlite handle first. On Windows the still-open
        handle makes ``rmtree`` fail silently (WinError 32): ``storage.sqlite``
        survives, and a same-name ``create_collection`` re-reads it and brings
        the deleted points back. The public client exposes no close-before-delete
        path, so we reach the private ``QdrantLocal.collections`` map to close the
        handle before deleting, then assert the on-disk directory is gone so any
        future regression fails loudly instead of resurrecting data. Server mode
        is a remote HTTP delete and needs none of this.
        """
        with suppress_local_qdrant_warnings():
            if not self._server_mode:
                local = getattr(self.client, "_client", None)
                collection = getattr(local, "collections", {}).get(name)
                if collection is not None:
                    collection.close()
            self.client.delete_collection(name)
        if not self._server_mode:
            import pathlib as _pathlib

            collection_dir = _pathlib.Path(self.db_path) / "collection" / name
            if collection_dir.exists():
                raise RuntimeError(
                    f"local collection directory survived delete_collection: "
                    f"{collection_dir}; same-name recreate would resurrect points"
                )

    def _drop_collection(self, collection: str) -> None:
        """Drop one collection if it exists and clear its ensured latch.

        The latch is cleared inside the lifecycle lock, alongside the drop: a
        latch that stayed set past the drop would let the next caller skip
        re-creation and address a collection that no longer exists.
        """
        with self._lifecycle_lock, self._point_lock(collection):
            if self._collection_exists(collection):
                self._delete_collection_hard(collection)
                logger.info("Dropped collection '%s'", collection)
            self._ensured[collection] = False

    def drop_table(self) -> None:
        """Drop the vault_docs collection if it exists."""
        self._drop_collection(self.TABLE_NAME)

    def _code_collection(self, collection: str | None) -> str:
        """Return the code collection a call targets.

        Defaults to the served name, so every existing caller keeps reading
        and writing exactly where it did. A rebuild passes its generation
        collection instead, which is what lets it populate a replacement while
        the served one keeps answering searches.

        The target is a per-call argument rather than instance state because
        one store is shared between search and indexing: rebinding it on the
        instance would drag concurrent readers onto the half-built generation.
        """
        return collection or self.CODE_TABLE_NAME

    def drop_code_table(self, collection: str | None = None) -> None:
        """Drop a code collection if it exists, defaulting to the served one."""
        self._drop_collection(self._code_collection(collection))

    def drop_document_table(self) -> None:
        """Drop only the independently owned document collection."""
        self._drop_collection(self.DOCUMENT_TABLE_NAME)

    def _record_manifest(self) -> None:
        """Record this root in the storage manifest (server mode only).

        Populates the prefix-to-root attribution the storage survey/prune
        surface needs to classify a namespace as live or orphaned. Runs at
        most once per store instance (guarded by ``_manifest_recorded``), so
        it never adds a per-operation manifest read to the search/index hot
        path. A manifest failure is logged, never raised - this best-effort
        attribution must not break indexing.
        """
        if self._manifest_recorded or not self._server_mode:
            return
        # Mark before attempting so a failure is not retried on every store
        # operation; attribution is best-effort and recovers on the next open.
        self._manifest_recorded = True
        try:
            from .storage_manifest import record_root

            record_root(self.root_dir, backend="server")
        except Exception:  # best-effort attribution hook; must never break indexing
            logger.debug(
                "could not record storage manifest for %s",
                self.root_dir,
                exc_info=True,
            )

    def touch_manifest_last_indexed(self) -> None:
        """Refresh this root's persisted ``last_indexed`` stamp (server mode).

        The ephemeral idle-TTL reclaim tier treats a temp-rooted
        namespace as dangling once this stamp is old enough, so every
        successful index run must refresh it - the stamp is the persisted
        activity clock that keeps an actively-used temp root protected.
        Best-effort like :meth:`_record_manifest`: a manifest failure must
        never fail the index run.
        """
        if not self._server_mode:
            return
        import datetime as _dt

        try:
            from .storage_manifest import record_root

            stamp = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
            record_root(self.root_dir, backend="server", last_indexed=stamp)
        except Exception:  # best-effort stamp; must never break indexing
            logger.debug(
                "could not stamp last_indexed for %s",
                self.root_dir,
                exc_info=True,
            )

    def _ensure_payload_indexes(
        self,
        collection: str,
        keyword_fields: Sequence[str],
        integer_fields: Sequence[str],
    ) -> None:
        """Create every declared payload index for one collection.

        ``create_payload_index`` is a no-op when the index already exists, so
        this is safe to call against a pre-existing collection to backfill a
        newly declared index. The field sets themselves are declared once in
        ``store_schema``; this is the single loop that applies them.
        """
        from qdrant_client import models

        for fname in keyword_fields:
            self._create_payload_index(
                collection,
                fname,
                models.PayloadSchemaType.KEYWORD,
            )
        for fname in integer_fields:
            self._create_payload_index(
                collection,
                fname,
                models.PayloadSchemaType.INTEGER,
            )

    def _ensure_table(
        self,
        collection: str,
        keyword_fields: Sequence[str],
        integer_fields: Sequence[str],
    ) -> None:
        """Create one collection and its declared payload indexes, at most once.

        An existing collection still has its declared indexes applied, which is
        what lets a newly declared index reach a collection created before the
        declaration. Every collection is treated the same way, because an
        exception for one of them is how a filter ends up doing a linear scan on
        that collection alone, for the life of the collection, with nothing to
        report it. The vault collection was such an exception, and never by
        decision: the skip-if-present shape was originally shared by all three,
        and only the other two were ever revisited - each at the moment a newly
        declared index had to reach data that already existed.

        The cost was measured against a real server holding 50k points.
        Re-declaring an index that is already present costs roughly 19ms per
        field; that is the steady-state price, paid once per collection per
        store open, and local mode ignores payload indexes altogether so it
        costs nothing there. The one open that finds a genuinely new field
        builds it in roughly a second per 50k points while continuing to serve
        searches at unchanged latency - a concurrent query stream held its p50
        near 5ms across the build, against the same figure before it, with no
        failed queries - so this neither gates readiness nor stalls a live
        collection.
        """
        self._record_manifest()
        with self._lifecycle_lock:
            if self._ensured.get(collection):
                return
            if not self._collection_exists(collection):
                self._ensure_collection(collection)
            self._ensure_payload_indexes(collection, keyword_fields, integer_fields)
            # Verified here, behind the same once-per-collection marker the
            # index reconcile sits behind, so the live geometry read never
            # reaches the query path. Ordered after the reconcile because a
            # collection this process just created must be judged against the
            # stamp that creation wrote, not against a half-built state.
            self._verify_conformance(collection)
            self._ensured[collection] = True

    def _reconcile_for_read(self, collection: str, ensure: Callable[[], None]) -> bool:
        """Return whether *collection* is there, reconciling it, creating nothing.

        The contract every read that pushes a filter down through a declared
        payload index is held to.

        A read never creates the collection it failed to find. An absent
        collection has nothing to answer with, and materialising one as a side
        effect of a read would put a second owner on it: the handle a read runs
        through need not be the handle an index run writes through, and two
        handles carry their own lifecycle lock and their own ensure latch, so
        neither serialises against the other and both would issue the create.
        Creation belongs to the index path, the only caller that must have the
        collection before it can proceed. It also keeps the answer honest - a
        fabricated empty collection reads downstream as an index that exists
        and holds nothing, rather than as no index at all.

        A collection that IS there still goes through *ensure*, because that is
        what applies a newly declared payload index to data indexed before the
        declaration. Dropping it would leave the filter this read is about to
        push down doing a linear scan for the life of the collection, with
        nothing to report it. The ensure latch gates the existence probe, so the
        extra round trip is paid once per store open per collection rather than
        once per call.

        Args:
            collection: The collection about to be read.
            ensure: The entry point that reconciles *collection* to its
                declared schema.

        Returns:
            Whether the collection exists and has been reconciled.
        """
        if not self._ensured.get(collection) and not self._collection_exists(
            collection
        ):
            return False
        ensure()
        return True

    def _live_dense_dim(self, collection: str) -> int | None:
        """Return the live collection's dense width, or ``None`` if unreadable.

        Unreadable is a real answer, not a failure: it yields an
        ``unverifiable`` verdict rather than an exception, because a backend
        that cannot answer a config question must not take down a store open.
        """
        try:
            info = self.client.get_collection(collection)
            vectors = info.config.params.vectors
        except Exception:  # an unanswerable probe is unverifiable, not fatal
            logger.debug("could not read geometry for %s", collection, exc_info=True)
            return None
        if not isinstance(vectors, dict):
            # Every collection this code creates uses named vectors; an
            # unnamed one is a shape we did not write and cannot judge.
            return None
        dense = cast("dict[str, Any]", vectors).get(store_schema.DENSE_VECTOR_NAME)
        size = getattr(dense, "size", None)
        return int(size) if isinstance(size, int) else None

    def _expected_identity(self) -> store_schema.CollectionIdentity:
        """Return the identity this store would stamp on a fresh collection."""
        import dataclasses

        return dataclasses.replace(
            store_schema.current_identity(), dense_dim=self._embedding_dim
        )

    def _verify_conformance(self, collection: str) -> None:
        """Judge one collection against what this process expects, and record it.

        Raises on a geometry disagreement and only on a geometry disagreement.
        A model disagreement is recorded and logged so the health surface can
        report it with a rebuild command; the collection stays readable because
        a rebuild is the remedy and refusing would remove search for its
        duration.
        """
        from .storage_identity import load_identity

        backend = "server" if self._server_mode else "local"
        stamped = load_identity(
            self.root_dir,
            backend=backend,
            collection=collection,
            local_dir=None if self._server_mode else self.db_path,
        )
        verdict = store_schema.evaluate_conformance(
            stamped,
            expected=self._expected_identity(),
            live_dense_dim=self._live_dense_dim(collection),
        )
        self._conformance[collection] = verdict
        if verdict.geometry_fatal:
            raise StorageGeometryError(
                f"collection {collection!r} cannot hold this configuration's "
                f"vectors: {verdict.reason}"
            )
        if verdict.verdict == store_schema.NONCONFORMING:
            logger.warning(
                "collection %s is nonconforming: %s", collection, verdict.reason
            )

    def conformance_verdicts(self) -> dict[str, store_schema.ConformanceVerdict]:
        """Return the verdict recorded for every collection ensured so far.

        Read by the health surface, which must report a nonconforming namespace
        without re-probing the backend on every health poll.
        """
        with self._lifecycle_lock:
            return dict(self._conformance)

    def ensure_table(self) -> None:
        """Create the vault_docs collection and its declared payload indexes.

        ``doc_id`` backs delete-by-document and chunk grouping; ``chunk_ordinal``
        backs the doc-level listing filter; ``doc_type``, ``feature``, and
        ``tags`` back the vault search filters.
        """
        self._ensure_table(
            self.TABLE_NAME,
            store_schema.VAULT_KEYWORD_INDEXES,
            store_schema.VAULT_INTEGER_INDEXES,
        )

    def code_collection_exists(self, collection: str | None = None) -> bool:
        """Return whether the code collection currently exists in storage.

        Read-only existence probe for callers that must distinguish an
        externally destroyed collection (e.g. a storage delete dropped the
        namespace) from an empty one before trusting prior-run evidence
        that claims storage-confirmed writes.
        """
        _target = self._code_collection(collection)
        return self._collection_exists(_target)

    def ensure_code_table(self, collection: str | None = None) -> None:
        """Create the codebase_docs collection and its declared payload indexes.

        ``node_type`` is in the KEYWORD set so the MCP
        ``search_codebase(node_type=...)`` filter does not fall back to a linear
        scan on remote Qdrant deployments, and ``domain`` backs the noise
        exclude/only pushdown - the index that first made reaching an existing
        collection matter.
        """
        _target = self._code_collection(collection)
        self._ensure_table(
            _target,
            store_schema.CODE_KEYWORD_INDEXES,
            store_schema.CODE_INTEGER_INDEXES,
        )

    def ensure_document_table(self) -> None:
        """Create the document collection and its declared payload indexes."""
        self._ensure_table(
            self.DOCUMENT_TABLE_NAME,
            store_schema.DOCUMENT_KEYWORD_INDEXES,
            store_schema.DOCUMENT_INTEGER_INDEXES,
        )
