"""Qdrant vector store layer for vault semantic search.

Manages a persistent Qdrant local database with hybrid search (dense + SPLADE sparse).
All heavy imports are guarded so core vault tools work without RAG deps.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import warnings
from contextlib import contextmanager, nullcontext
from typing import TYPE_CHECKING, Any, cast

from . import store_schema
from ._store_locks import FileLock, VaultStoreLockedError
from ._store_models import (
    CodeChunk,
    VaultChunk,
    VaultDocument,
    _code_chunk_payload,
    _vault_chunk_payload,
    _vault_doc_payload,
    root_collection_prefix,
)
from ._store_search import _VaultSearchMixin
from ._store_writes import ensure_disk_headroom, run_write_with_retry

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Generator, Sequence
    from contextlib import AbstractContextManager
    from uuid import UUID

    from qdrant_client import QdrantClient
    from qdrant_client.http.models.models import (
        Condition,
        Filter,
        Record,
    )

logger = logging.getLogger(__name__)

__all__ = [
    "CodeChunk",
    "VaultDocument",
    "VaultStore",
    "VaultStoreLockedError",
    "root_collection_prefix",
]


EMBEDDING_DIM = store_schema.DEFAULT_DENSE_DIM  # Qwen3-Embedding-0.6B default

#: Server-mode request timeout. Bounded so a Qdrant server wedged on a
#: full-disk WAL raises instead of blocking an upsert socket forever;
#: generous enough for large batch upserts and slow scans.
_SERVER_REQUEST_TIMEOUT_S = 120


@contextmanager
def _suppress_local_qdrant_warnings() -> Generator[None]:
    """Suppress Qdrant local-mode warnings that are not actionable per call."""
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=".*Payload indexes have no effect in the local Qdrant.*",
            category=UserWarning,
        )
        warnings.filterwarnings(
            "ignore",
            message=".*Local mode is not recommended for collections with more than.*",
            category=UserWarning,
        )
        yield


def _interpreter_is_supported(version_info: Sequence[int | str]) -> bool:
    """Return True when *version_info* is compatible with the pinned stack.

    The pinned stack requires CPython 3.13.x (``requires-python = ">=3.13"`` in
    ``pyproject.toml``).  CPython 3.14+ breaks ``qdrant_client`` at import time via a
    ``protobuf`` metaclass incompatibility; the guard in ``_check_rag_deps`` converts
    that opaque ``TypeError`` into an actionable ``RuntimeError`` before the import is
    ever attempted.

    Args:
        version_info: A ``(major, minor, ...)`` tuple — pass ``sys.version_info`` or a
            plain ``(major, minor, micro)`` tuple in tests.

    Returns:
        ``True`` for 3.13.x, ``False`` for anything < 3.13 or >= 3.14.
    """
    major, minor = int(version_info[0]), int(version_info[1])
    return major == 3 and minor == 13


def _check_rag_deps() -> None:
    """Raise if the interpreter is unsupported or qdrant-client is not installed.

    The guard runs *before* importing ``qdrant_client`` so that a CPython 3.14+
    interpreter produces an actionable ``RuntimeError`` rather than the opaque
    ``TypeError: Metaclasses with custom tp_new are not supported`` that protobuf
    raises on import.

    Raises:
        RuntimeError: If the running interpreter is not CPython 3.13.x.
        ImportError: If ``qdrant-client`` is not available.
    """
    import sys

    if not _interpreter_is_supported(sys.version_info):
        raise RuntimeError(
            "vaultspec-rag requires CPython 3.13.x (>=3.13,<3.14); CPython 3.14+ "
            "breaks qdrant-client at import.  The running interpreter is "
            f"{sys.version!r}.  "
            "Run the service via 'uv run vaultspec-rag ...' so that uv selects the "
            "pinned interpreter from the project's virtual environment."
        )
    try:
        import qdrant_client

        _ = qdrant_client
    except ImportError:
        raise ImportError("RAG dependencies not installed. Run: uv sync") from None


class VaultStore(_VaultSearchMixin):
    """Qdrant-backed vector store for vault documents and codebase chunks.

    Storage lives at ``{root_dir}/{data_dir}/{qdrant_dir}/`` (by default
    ``.vault/data/search-data/qdrant/``).  The collection ``vault_docs``
    holds one point per indexed document, and ``codebase_docs`` holds
    points per source code chunk.

    In server mode (``cfg.qdrant_url`` set) one shared qdrant server
    hosts every root, so the instance-level collection names gain a
    stable per-root prefix (see :func:`root_collection_prefix`); the
    class attributes below remain the bare local-mode names and the
    suffix of the namespaced names.
    """

    TABLE_NAME = "vault_docs"
    CODE_TABLE_NAME = "codebase_docs"

    def __init__(
        self,
        root_dir: pathlib.Path | str,
        embedding_dim: int | None = None,
    ) -> None:
        """Connect to (or create) the Qdrant store.

        Path: ``{root_dir}/{data_dir}/{qdrant_dir}/``.

        Args:
            root_dir: Workspace root directory.
            embedding_dim: Dimensionality of the dense embedding vectors.
                Defaults to EMBEDDING_DIM (1024).

        Raises:
            ImportError: If qdrant-client is not installed.
            VaultStoreLockedError: If the Qdrant storage folder is already opened
                by another process.
        """
        _check_rag_deps()
        import pathlib as _pathlib

        from qdrant_client import QdrantClient as _QdrantClient

        from .config import get_config

        cfg = get_config()

        self.root_dir = _pathlib.Path(root_dir)
        self._server_mode = bool(cfg.qdrant_url)
        # One shared qdrant server hosts every root's data, so server
        # mode namespaces this root's collections with a stable
        # per-root prefix; the bare names stay the suffix. Local mode
        # keeps the bare names (one store per project data dir).
        _prefix = root_collection_prefix(self.root_dir) if self._server_mode else ""
        # Per-instance namespaced names intentionally shadow the bare class
        # constants; basedpyright's uppercase-is-constant rule does not model
        # the class-constant / instance-override split this class relies on.
        self.TABLE_NAME: str = _prefix + VaultStore.TABLE_NAME  # pyright: ignore[reportConstantRedefinition]
        self.CODE_TABLE_NAME: str = _prefix + VaultStore.CODE_TABLE_NAME  # pyright: ignore[reportConstantRedefinition]
        # Locking is backend-aware and split per concern. The lifecycle
        # lock guards client open/close, collection create/drop, and the
        # ensure flags. Point operations take their collection's own
        # lock: QdrantLocal is not thread-safe within a collection, but
        # each collection owns independent state (its own in-memory
        # structures and sqlite connection), so vault and code traffic
        # never serialize against each other. A remote Qdrant server
        # handles its own concurrency, so server-mode point operations
        # take no lock at all. The lock dict is keyed by the resolved
        # (possibly prefixed) collection names assigned above.
        self._lifecycle_lock = threading.RLock()
        self._collection_locks: dict[str, threading.RLock] = {
            self.TABLE_NAME: threading.RLock(),
            self.CODE_TABLE_NAME: threading.RLock(),
        }
        self._client: QdrantClient | None = None

        if cfg.qdrant_url:
            self.db_path = cfg.qdrant_url
            self._lock_helper = None
            # The managed server's storage volume, for write headroom
            # checks; a remote server's dir won't exist locally and the
            # probe then skips itself.
            self._storage_probe_path = _pathlib.Path(
                cfg.qdrant_storage_dir
            ).expanduser()
            try:
                # An explicit request timeout: without one, a server
                # stalling on a full-disk WAL blocks the upsert socket
                # forever, freezing the job at completed=0 with no error
                # ever raised while the GPU keeps burning upstream.
                self._client = _QdrantClient(
                    url=cfg.qdrant_url,
                    api_key=cfg.qdrant_api_key,
                    timeout=_SERVER_REQUEST_TIMEOUT_S,
                )
            except Exception as exc:
                logger.error(
                    "Failed to connect to Qdrant server at %s: %s", cfg.qdrant_url, exc
                )
                raise
        else:
            self.db_path = self.root_dir / cfg.data_dir / cfg.qdrant_dir
            self.db_path.mkdir(parents=True, exist_ok=True)
            self._storage_probe_path = self.db_path
            self._lock_helper = FileLock(self.db_path / "exclusive.lock")
            if not self._lock_helper.acquire():
                raise VaultStoreLockedError(str(self.db_path))
            try:
                with _suppress_local_qdrant_warnings():
                    self._client = _QdrantClient(
                        path=str(self.db_path),
                    )
            except RuntimeError as exc:
                self._lock_helper.release()
                if "already accessed by another instance" in str(exc):
                    raise VaultStoreLockedError(str(self.db_path)) from exc
                raise

        # Default the collection's dense dimension from the same source the wire
        # descriptor advertises, so the advertised dimension always equals what
        # the live collection is built with - even under a config override.
        self._embedding_dim = embedding_dim or store_schema.effective_dense_dim()
        self._vault_ensured = False
        self._code_ensured = False
        # Best-effort storage-manifest attribution is recorded at most once per
        # store instance (server mode only) so it never re-enters the hot path.
        self._manifest_recorded = False

    @property
    def client(self) -> QdrantClient:
        """Return the Qdrant client, raising if the store has been closed.

        Raises:
            RuntimeError: If the store has already been closed.
        """
        if self._client is None:
            msg = "VaultStore has been closed"
            raise RuntimeError(msg)
        return self._client

    def _id_scan_page_limit(self, collection: str) -> int:
        """Return the scroll page size for payload-light full-collection scans.

        QdrantLocal's ``scroll`` re-sorts every point id and linearly
        skips to the offset on *each* page, so paging a large local
        collection costs O(N^2) of GIL-holding CPU - measured at 10+
        minutes on a few hundred thousand points while starving every
        other thread in the process. Local mode therefore fetches the
        whole id set as a single page (one sort, one pass); server mode
        keeps bounded pages since large HTTP responses are the cost
        there.
        """
        if self._server_mode:
            return 1000
        try:
            with self._point_lock(collection):
                total = int(self.client.count(collection_name=collection).count)
        except (OSError, RuntimeError):
            logger.warning(
                "Could not size the id scan for %s; falling back to paging",
                collection,
                exc_info=True,
            )
            return 1000
        return max(1, total)

    def _point_lock(self, collection: str) -> AbstractContextManager[object]:
        """Return the point-operation guard for *collection*.

        Local mode returns the collection's own reentrant lock; server
        mode returns a no-op context because the remote Qdrant server
        is concurrency-safe and client-side locking would only cap
        throughput. Reentrancy is load-bearing: scan helpers size their
        page limit (which takes this lock) while callers already hold
        it - switching to a non-reentrant lock would deadlock there.
        """
        if self._server_mode:
            return nullcontext()
        return self._collection_locks[collection]

    def close(self) -> None:
        """Release the Qdrant client and set it to ``None``.

        Takes the lifecycle lock and then every collection lock in a
        fixed order so no point operation is in flight when the client
        goes away.
        """
        with (
            self._lifecycle_lock,
            self._collection_locks[self.TABLE_NAME],
            self._collection_locks[self.CODE_TABLE_NAME],
        ):
            if self._client is not None:
                self._client.close()
                self._client = None
            if hasattr(self, "_lock_helper") and self._lock_helper is not None:
                self._lock_helper.release()

    def __enter__(self) -> VaultStore:
        """Return *self* to support use as a context manager.

        Returns:
            This store instance.
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> bool:
        """Close the store on context-manager exit.

        Returns:
            Always ``False``; exceptions are never suppressed.
        """
        self.close()
        return False

    def _ensure_collection(self, name: str) -> None:
        """Create a collection with dense + sparse vectors if it doesn't exist.

        Args:
            name: Qdrant collection name to create.
        """
        from qdrant_client import models

        from .config import get_config

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
            if self.client.collection_exists(name):
                return

            kwargs: dict[str, Any] = {}
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
        logger.info("Created collection '%s' at %s", name, self.db_path)

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
        with _suppress_local_qdrant_warnings():
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

    def drop_table(self) -> None:
        """Drop the vault_docs collection if it exists."""
        with self._lifecycle_lock, self._point_lock(self.TABLE_NAME):
            if self.client.collection_exists(self.TABLE_NAME):
                self._delete_collection_hard(self.TABLE_NAME)
                logger.info("Dropped collection '%s'", self.TABLE_NAME)
            self._vault_ensured = False

    def drop_code_table(self) -> None:
        """Drop the codebase_docs collection if it exists."""
        with self._lifecycle_lock, self._point_lock(self.CODE_TABLE_NAME):
            if self.client.collection_exists(self.CODE_TABLE_NAME):
                self._delete_collection_hard(self.CODE_TABLE_NAME)
                logger.info("Dropped collection '%s'", self.CODE_TABLE_NAME)
            self._code_ensured = False

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

    def ensure_table(self) -> None:
        """Create the vault_docs collection if it doesn't exist."""
        from qdrant_client import models

        self._record_manifest()
        with self._lifecycle_lock:
            if self._vault_ensured:
                return

            if self.client.collection_exists(self.TABLE_NAME):
                self._vault_ensured = True
                return

            self._ensure_collection(self.TABLE_NAME)

            # ``doc_id`` backs delete-by-document and chunk grouping;
            # ``chunk_ordinal`` backs the doc-level listing filter. The field
            # sets are declared once in ``store_schema``.
            for fname in store_schema.VAULT_KEYWORD_INDEXES:
                with _suppress_local_qdrant_warnings():
                    self.client.create_payload_index(
                        collection_name=self.TABLE_NAME,
                        field_name=fname,
                        field_schema=models.PayloadSchemaType.KEYWORD,
                    )
            for fname in store_schema.VAULT_INTEGER_INDEXES:
                with _suppress_local_qdrant_warnings():
                    self.client.create_payload_index(
                        collection_name=self.TABLE_NAME,
                        field_name=fname,
                        field_schema=models.PayloadSchemaType.INTEGER,
                    )
            self._vault_ensured = True

    def _ensure_code_indexes(self) -> None:
        """Create every declared code payload index (idempotent).

        ``node_type`` is in the KEYWORD set so the MCP
        ``search_codebase(node_type=...)`` filter does not fall back to a linear
        scan on remote Qdrant deployments, ``domain`` backs the noise
        exclude/only pushdown, and the document-preprocessing hook locators
        (#185) keep a typed index per value kind. The field sets are declared
        once in ``store_schema``. ``create_payload_index`` is a no-op when the
        index already exists, so this is safe to call on a pre-existing
        collection to backfill a newly added index (e.g. ``domain``).
        """
        from qdrant_client import models

        for fname in store_schema.CODE_KEYWORD_INDEXES:
            with _suppress_local_qdrant_warnings():
                self.client.create_payload_index(
                    collection_name=self.CODE_TABLE_NAME,
                    field_name=fname,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
        for fname in store_schema.CODE_INTEGER_INDEXES:
            with _suppress_local_qdrant_warnings():
                self.client.create_payload_index(
                    collection_name=self.CODE_TABLE_NAME,
                    field_name=fname,
                    field_schema=models.PayloadSchemaType.INTEGER,
                )

    def ensure_code_table(self) -> None:
        """Create the codebase_docs collection if it doesn't exist.

        On an existing collection the declared indexes are still ensured so a
        newly added KEYWORD index (e.g. ``domain``) is backfilled on the next
        open rather than requiring a full drop-and-reindex.
        """
        self._record_manifest()
        with self._lifecycle_lock:
            if self._code_ensured:
                return

            if not self.client.collection_exists(self.CODE_TABLE_NAME):
                self._ensure_collection(self.CODE_TABLE_NAME)

            self._ensure_code_indexes()
            self._code_ensured = True

    def upsert_documents(self, docs: list[VaultDocument]) -> None:
        """Insert or update documents by ``id``.

        Args:
            docs: Documents to insert or replace.
        """
        if not docs:
            return

        from qdrant_client import models

        points: list[Any] = []
        for doc in docs:
            vector: dict[str, Any] = {
                "dense": doc.vector,
            }
            if doc.sparse_indices:
                vector["sparse"] = models.SparseVector(
                    indices=doc.sparse_indices,
                    values=doc.sparse_values,
                )
            points.append(
                models.PointStruct(
                    id=self._stable_id(doc.id),
                    vector=vector,
                    payload=cast("dict[str, Any]", _vault_doc_payload(doc)),
                ),
            )

        self.ensure_table()
        with self._point_lock(self.TABLE_NAME):
            self._guarded_upsert(self.TABLE_NAME, points, "vault documents")
        logger.info("Upserted %d document(s)", len(docs))

    def upsert_document_chunks(self, chunks: list[VaultChunk]) -> None:
        """Insert or update vault chunks keyed by ``doc_id#c{ordinal}``.

        The full document body travels only on the ordinal-0 chunk
        (``doc_content``) so retrieval-by-id stays exact while the
        per-chunk payload carries just its own text.

        Args:
            chunks: Vault chunks to insert or replace.
        """
        if not chunks:
            return

        from qdrant_client import models

        points: list[Any] = []
        for chunk in chunks:
            vector: dict[str, Any] = {
                "dense": chunk.vector,
            }
            if chunk.sparse_indices:
                vector["sparse"] = models.SparseVector(
                    indices=chunk.sparse_indices,
                    values=chunk.sparse_values,
                )
            points.append(
                models.PointStruct(
                    id=self._stable_id(chunk.point_key),
                    vector=vector,
                    payload=cast("dict[str, Any]", _vault_chunk_payload(chunk)),
                ),
            )

        self.ensure_table()
        with self._point_lock(self.TABLE_NAME):
            self._guarded_upsert(self.TABLE_NAME, points, "vault chunks")
        logger.info("Upserted %d vault chunk(s)", len(chunks))

    def upsert_code_chunks(self, chunks: list[CodeChunk]) -> None:
        """Insert or update codebase chunks by ``id``.

        Args:
            chunks: Code chunks to insert or replace.
        """
        if not chunks:
            return

        from qdrant_client import models

        points: list[Any] = []
        for chunk in chunks:
            vector: dict[str, Any] = {
                "dense": chunk.vector,
            }
            if chunk.sparse_indices:
                vector["sparse"] = models.SparseVector(
                    indices=chunk.sparse_indices,
                    values=chunk.sparse_values,
                )
            points.append(
                models.PointStruct(
                    id=self._stable_id(chunk.id),
                    vector=vector,
                    payload=cast("dict[str, Any]", _code_chunk_payload(chunk)),
                ),
            )

        self.ensure_code_table()
        with self._point_lock(self.CODE_TABLE_NAME):
            self._guarded_upsert(self.CODE_TABLE_NAME, points, "code chunks")
        logger.info("Upserted %d codebase chunk(s)", len(chunks))

    def _guarded_upsert(
        self, collection_name: str, points: list[Any], description: str
    ) -> None:
        """Upsert under the write-failure guards.

        A cheap free-disk floor check refuses the write while the store
        volume is exhausted (before Qdrant can wedge on it), then the upsert
        runs under the bounded retry: transient failures back off and retry,
        storage exhaustion raises immediately so the embedder upstream stops
        burning GPU on vectors that cannot be persisted.
        """
        ensure_disk_headroom(self._storage_probe_path)
        run_write_with_retry(
            lambda: self.client.upsert(
                collection_name=collection_name,
                points=points,
            ),
            description=f"upsert {description} into {collection_name}",
        )

    def disk_headroom_preflight(self, new_points: int) -> None:
        """Bulk-index pre-flight: fail fast when the run cannot fit on disk.

        Raises:
            InsufficientDiskSpaceError: When the estimated footprint of
                ``new_points`` plus the write floor exceeds the free space
                on the store volume.
        """
        ensure_disk_headroom(self._storage_probe_path, new_points=new_points)

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
        from qdrant_client import models

        self.ensure_table()
        with self._point_lock(self.TABLE_NAME):
            self.client.delete(
                collection_name=self.TABLE_NAME,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="doc_id",
                                match=models.MatchAny(any=list(ids)),
                            ),
                        ],
                    ),
                ),
            )
        logger.info("Deleted %d document(s)", len(ids))

    def delete_code_chunks(self, ids: list[str]) -> None:
        """Remove code chunks by their ``id`` values.

        Args:
            ids: List of chunk IDs to delete.
        """
        if not ids:
            return
        from qdrant_client import models

        self.ensure_code_table()
        with self._point_lock(self.CODE_TABLE_NAME):
            point_ids: list[int | str | UUID] = [self._stable_id(i) for i in ids]
            self.client.delete(
                collection_name=self.CODE_TABLE_NAME,
                points_selector=models.PointIdsList(points=point_ids),
            )
        logger.info("Deleted %d code chunk(s)", len(ids))

    def get_all_ids(self) -> set[str]:
        """Return the set of all document ``id`` values in the store.

        Returns:
            Set of document stem IDs from the vault_docs collection.
        """
        self.ensure_table()
        with self._point_lock(self.TABLE_NAME):
            return self._scroll_all_ids(self.TABLE_NAME, "doc_id")

    def get_chunk_counts(
        self,
        doc_ids: set[str] | None = None,
    ) -> dict[str, int]:
        """Return the stored chunk count per vault document.

        Points written before chunking carry no ordinal and count as a
        single chunk. Used to detect documents that shrank between
        index runs so their stale tail chunks can be purged.

        Args:
            doc_ids: When given, restrict the scan to these documents.

        Returns:
            Mapping of document stem ID to its stored chunk count.
        """
        from qdrant_client import models

        scroll_filter: Filter | None = None
        if doc_ids is not None:
            if not doc_ids:
                return {}
            scroll_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="doc_id",
                        match=models.MatchAny(any=sorted(doc_ids)),
                    ),
                ],
            )

        counts: dict[str, int] = {}
        offset: Any = None  # qdrant scroll offset is int|str|UUID|PointId|None
        self.ensure_table()
        page_limit = self._id_scan_page_limit(self.TABLE_NAME)
        while True:
            with self._point_lock(self.TABLE_NAME):
                records, next_offset = self.client.scroll(
                    collection_name=self.TABLE_NAME,
                    scroll_filter=scroll_filter,
                    limit=page_limit,
                    offset=offset,
                    with_payload=["doc_id", "chunk_ordinal"],
                    with_vectors=False,
                )
            point: Record
            for point in records:
                payload = point.payload or {}
                doc_id = payload.get("doc_id")
                if doc_id is None:
                    continue
                ordinal = payload.get("chunk_ordinal")
                chunk_no = (ordinal + 1) if isinstance(ordinal, int) else 1
                key = str(doc_id)
                counts[key] = max(counts.get(key, 0), chunk_no)
            if next_offset is None:
                break
            offset = next_offset
        return counts

    def delete_document_chunk_tail(self, doc_id: str, from_ordinal: int) -> None:
        """Delete a document's chunks at or beyond *from_ordinal*.

        Called after re-indexing a document that shrank: the upsert
        overwrote ordinals below the new count, and this removes the
        now-orphaned tail.

        Args:
            doc_id: Document stem whose tail chunks to remove.
            from_ordinal: First ordinal to delete (the new chunk count).
        """
        from qdrant_client import models

        self.ensure_table()
        with self._point_lock(self.TABLE_NAME):
            self.client.delete(
                collection_name=self.TABLE_NAME,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="doc_id",
                                match=models.MatchValue(value=doc_id),
                            ),
                            models.FieldCondition(
                                key="chunk_ordinal",
                                range=models.Range(gte=from_ordinal),
                            ),
                        ],
                    ),
                ),
            )
        logger.info("Deleted chunk tail of %s from ordinal %d", doc_id, from_ordinal)

    def get_all_code_ids(self) -> set[str]:
        """Return the set of all code chunk ``id`` values in the store.

        Returns:
            Set of chunk IDs from the codebase_docs collection.
        """
        self.ensure_code_table()
        with self._point_lock(self.CODE_TABLE_NAME):
            return self._scroll_all_ids(self.CODE_TABLE_NAME, "chunk_id")

    def _scroll_all_ids(self, collection: str, id_field: str) -> set[str]:
        """Scroll through all points and collect the id field from payloads.

        Args:
            collection: Qdrant collection name to scroll.
            id_field: Payload key that holds the string ID.

        Returns:
            Set of string IDs extracted from point payloads.
        """
        ids: set[str] = set()
        offset: Any = None  # qdrant scroll offset is int|str|UUID|PointId|None
        page_limit = self._id_scan_page_limit(collection)
        while True:
            with self._point_lock(collection):
                records, next_offset = self.client.scroll(
                    collection_name=collection,
                    limit=page_limit,
                    offset=offset,
                    with_payload=[id_field],
                    with_vectors=False,
                )
            point: Record
            for point in records:
                if point.payload and id_field in point.payload:
                    ids.add(str(point.payload[id_field]))
            if next_offset is None:
                break
            offset = next_offset
        return ids

    def get_code_ids_by_paths(self, rel_paths: set[str]) -> list[str]:
        """Return chunk IDs for code chunks belonging to the given file paths.

        Uses a Qdrant MatchAny filter on the ``path`` payload field
        instead of scanning all chunks.

        Args:
            rel_paths: Set of relative file paths to match against.

        Returns:
            List of chunk ID strings for matching code chunks.
        """
        from qdrant_client import models

        if not rel_paths:
            return []

        self.ensure_code_table()

        scroll_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="path",
                    match=models.MatchAny(any=list(rel_paths)),
                ),
            ],
        )

        ids: list[str] = []
        offset: Any = None  # qdrant scroll offset is int|str|UUID|PointId|None
        page_limit = self._id_scan_page_limit(self.CODE_TABLE_NAME)
        while True:
            with self._point_lock(self.CODE_TABLE_NAME):
                records, next_offset = self.client.scroll(
                    collection_name=self.CODE_TABLE_NAME,
                    scroll_filter=scroll_filter,
                    limit=page_limit,
                    offset=offset,
                    with_payload=["chunk_id"],
                    with_vectors=False,
                )
            point: Record
            for point in records:
                if point.payload and "chunk_id" in point.payload:
                    ids.append(str(point.payload["chunk_id"]))
            if next_offset is None:
                break
            offset = next_offset
        return ids

    def count(self) -> int:
        """Return total number of indexed documents in vault_docs.

        Returns:
            Point count in the vault_docs collection.
        """
        self.ensure_table()
        with self._point_lock(self.TABLE_NAME):
            return self.client.count(collection_name=self.TABLE_NAME).count

    def count_code(self) -> int:
        """Return total number of indexed codebase chunks.

        Returns:
            Point count in the codebase_docs collection.
        """
        self.ensure_code_table()
        with self._point_lock(self.CODE_TABLE_NAME):
            return self.client.count(collection_name=self.CODE_TABLE_NAME).count

    def get_by_id(self, doc_id: str) -> dict[str, Any] | None:
        """Retrieve a single document by ID, or ``None`` if not found.

        Args:
            doc_id: Document stem to look up.

        Returns:
            Document payload dict (vectors stripped), or ``None``
            if no matching point exists.
        """
        self.ensure_table()
        with self._point_lock(self.TABLE_NAME):
            # The head chunk (ordinal 0) carries the full body as
            # ``doc_content``; fall back to the pre-chunking point id
            # so stores written before chunking still resolve.
            point_ids: list[int | str | UUID] = [
                self._stable_id(f"{doc_id}#c0"),
                self._stable_id(doc_id),
            ]
            records: list[Record] = self.client.retrieve(
                collection_name=self.TABLE_NAME,
                ids=point_ids,
                with_payload=True,
                with_vectors=False,
            )
            if not records:
                return None
            raw = records[0].payload
            payload: dict[str, Any] = dict(raw) if raw else {}
            payload["id"] = payload.pop("doc_id", doc_id)
            doc_content = payload.pop("doc_content", None)
            if isinstance(doc_content, str):
                payload["content"] = doc_content
            payload.pop("chunk_ordinal", None)
            payload.pop("chunk_count", None)
            return payload

    def list_all_documents(
        self,
        doc_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return all vault documents via scroll, optionally filtered.

        Args:
            doc_type: If provided, only return documents of this type.

        Returns:
            List of document dicts (id, path, doc_type, title, etc.).
        """
        from qdrant_client import models

        self.ensure_table()

        # One row per document: match only head chunks (ordinal 0) or
        # points written before chunking (no ordinal field at all).
        head_or_legacy = models.Filter(
            should=[
                models.FieldCondition(
                    key="chunk_ordinal",
                    match=models.MatchValue(value=0),
                ),
                models.IsEmptyCondition(
                    is_empty=models.PayloadField(key="chunk_ordinal"),
                ),
            ],
        )
        conditions: list[Condition] = [head_or_legacy]
        if doc_type:
            conditions.append(
                models.FieldCondition(
                    key="doc_type",
                    match=models.MatchValue(value=doc_type),
                ),
            )
        scroll_filter = models.Filter(must=conditions)

        docs: list[dict[str, Any]] = []
        offset: Any = None  # qdrant scroll offset is int|str|UUID|PointId|None
        while True:
            with self._point_lock(self.TABLE_NAME):
                records, next_offset = self.client.scroll(
                    collection_name=self.TABLE_NAME,
                    scroll_filter=scroll_filter,
                    limit=1000,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
            point: Record
            for point in records:
                payload: dict[str, Any] = dict(point.payload) if point.payload else {}
                payload["id"] = payload.pop("doc_id", str(point.id))
                doc_content = payload.pop("doc_content", None)
                if isinstance(doc_content, str):
                    payload["content"] = doc_content
                payload.pop("chunk_ordinal", None)
                payload.pop("chunk_count", None)
                docs.append(payload)
            if next_offset is None:
                break
            offset = next_offset
        return docs

    @staticmethod
    def _stable_id(string_id: str) -> int:
        """Convert a string ID to a stable integer for Qdrant point ID.

        Qdrant local mode requires integer or UUID point IDs. We use a
        deterministic hash to map string document stems to integers.

        Args:
            string_id: The string document or chunk ID to hash.

        Returns:
            Positive 63-bit integer derived from SHA-256 of the ID.
        """
        h = hashlib.sha256(string_id.encode("utf-8")).digest()
        return int.from_bytes(h[:8], byteorder="big") & 0x7FFFFFFFFFFFFFFF
