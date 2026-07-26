"""Qdrant vector store layer for vault semantic search.

Manages a persistent Qdrant local database with hybrid search (dense + SPLADE sparse).
All heavy imports are guarded so core vault tools work without RAG deps.
"""

from __future__ import annotations

import hashlib
import logging
import math
import threading
import time
import warnings
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, cast

from . import store_schema
from ._store_locks import (
    FileLock,
    VaultStoreLockedError,
    acquire_collection_locks,
    acquire_collection_locks_bounded,
)
from ._store_models import (
    CodeChunk,
    VaultChunk,
    VaultDocument,
    _code_chunk_payload,
    _vault_chunk_payload,
    _vault_doc_payload,
    resolve_served_code_collection,
    root_collection_prefix,
)
from ._store_models import (
    DocumentChunk as _DocumentChunk,
)
from ._store_search import _VaultSearchMixin
from ._store_writes import (
    StoreWritePolicy,
    ensure_disk_headroom,
    remaining_write_seconds,
    run_store_operation_with_retry,
)

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable, Generator, Sequence
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
    "DonorPoint",
    "IngestVerificationError",
    "VaultDocument",
    "VaultStore",
    "VaultStoreLockedError",
    "root_collection_prefix",
]


EMBEDDING_DIM = store_schema.DEFAULT_DENSE_DIM  # Qwen3-Embedding-0.6B default
_WRITE_LOCK_POLL_SECONDS = 0.1
# Donor reads page ids in bounded batches: large enough to amortize the
# round-trip, small enough that one response stays cheap to parse and hold.
_DONOR_RETRIEVE_BATCH_SIZE = 256


@dataclass(frozen=True, slots=True)
class DonorPoint:
    """One point read back from a donor collection by string id.

    Carries exactly what a reuse caller needs to adopt stored vectors
    without re-encoding: the named dense vector, the named sparse vector
    (``None``/``None`` when the point was written without one), and the
    stored payload for content verification. Read-only data; the store
    never mutates a donor.
    """

    dense: list[float]
    sparse_indices: list[int] | None
    sparse_values: list[float] | None
    payload: dict[str, Any] = field(default_factory=dict)


#: Reserved fence point identity for the ingest barrier. ``_stable_id``
#: only ever produces integers, so a UUID point id can never collide with
#: a real chunk; deleting it is always an idempotent no-op the server
#: applies in WAL order behind every previously acknowledged update.
_INGEST_FENCE_POINT_ID = "00000000-0000-4000-8000-000000000000"


class IngestVerificationError(RuntimeError):
    """Acknowledged writes did not all apply to the collection.

    Raised by the ingest barrier when the exact post-fence point count
    disagrees with the caller's expectation. This is the silent-loss
    class a non-blocking upsert can hide: the server can acknowledge a
    batch (for example one naming an unknown vector) and never apply
    it, without ever reporting an error. A job that sees this must
    fail rather than publish terminal metadata over missing points.
    """


class StorageGeometryError(RuntimeError):
    """A collection's vector geometry cannot carry this process's vectors.

    Raised when the width, distance, or dense vector name of an existing
    collection disagrees with what the running configuration would produce.
    Such vectors cannot be scored at all, so this refuses at the ensure step
    rather than letting the disagreement surface later as a rejected upsert
    that burns the whole retry budget under a "transient" label, or as a
    hybrid-search fallback that blames the wrong subsystem.

    Deliberately NOT raised for a model disagreement at matching geometry:
    that collection is readable, and refusing would remove search for exactly
    the duration of the rebuild that is the remedy.
    """


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
    """Qdrant-backed vector store for vault, code, and document content.

    Storage lives at ``{root_dir}/{data_dir}/{qdrant_dir}/`` (by default
    ``.vault/data/search-data/qdrant/``).  The collection ``vault_docs``
    holds vault chunks, ``codebase_docs`` holds source chunks, and
    ``document_docs`` holds independently owned document chunks.

    In server mode (``cfg.qdrant_url`` set) one shared qdrant server
    hosts every root, so the instance-level collection names gain a
    stable per-root prefix (see :func:`root_collection_prefix`); the
    class attributes below remain the bare local-mode names and the
    suffix of the namespaced names.
    """

    TABLE_NAME = store_schema.VAULT_COLLECTION
    CODE_TABLE_NAME = store_schema.CODE_COLLECTION
    DOCUMENT_TABLE_NAME = store_schema.DOCUMENT_COLLECTION

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
        # Code reads resolve through the per-root served pointer rather than
        # the derived name, so a replacement generation takes effect for
        # readers when the pointer moves and not before. Absent a pointer this
        # is exactly the derived name, which is the state of every root that
        # has never published a replacement.
        self.CODE_TABLE_NAME: str = resolve_served_code_collection(  # pyright: ignore[reportConstantRedefinition]
            self.root_dir, _prefix + VaultStore.CODE_TABLE_NAME
        )
        self.DOCUMENT_TABLE_NAME: str = _prefix + VaultStore.DOCUMENT_TABLE_NAME  # pyright: ignore[reportConstantRedefinition]
        # Locking is backend-aware and split per concern. The lifecycle
        # lock guards client open/close, collection create/drop, and the
        # ensure flags. Point operations take their collection's own
        # lock: QdrantLocal is not thread-safe within a collection, but
        # each collection owns independent state (its own in-memory
        # structures and sqlite connection), so vault, code, and document
        # traffic never serialize against each other. A remote Qdrant server
        # handles its own concurrency, so server-mode point operations
        # take no lock at all. The lock dict is keyed by the resolved
        # (possibly prefixed) collection names assigned above.
        self._lifecycle_lock = threading.RLock()
        self._collection_locks: dict[str, threading.RLock] = {
            self.TABLE_NAME: threading.RLock(),
            self.CODE_TABLE_NAME: threading.RLock(),
            self.DOCUMENT_TABLE_NAME: threading.RLock(),
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
                    timeout=math.ceil(cfg.store_operation_timeout_seconds),
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
        # One latch per collection rather than a field per collection: the
        # create-once fast path is identical for all three, and three parallel
        # booleans invite a drop that clears the wrong one.
        self._ensured: dict[str, bool] = {}
        # Verdict per collection, populated by the ensure path and read by the
        # health surface so a health poll never re-probes the backend.
        self._conformance: dict[str, store_schema.ConformanceVerdict] = {}
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

    def _retried[T](self, description: str, op: Callable[[int], T]) -> T:
        """Run one replay-safe store operation under the bounded retry.

        Server mode only. A refused connection is a remote-backend
        condition - the managed server can be restarting, cycling a
        quarantined collection, or simply gone while a runner outlives it -
        and an index job reaches ensure and read operations before its
        first write, so leaving those single-shot turned a momentary
        refusal into a failed job. The embedded local engine has no socket
        to refuse, so local mode runs the operation exactly once and a
        genuine local fault surfaces immediately instead of being retried.

        Only operations safe to replay are routed here: existence checks,
        reads, and idempotent deletes. Storage exhaustion still raises on
        the first attempt.
        """
        from .config import get_config

        operation_timeout = get_config().store_operation_timeout_seconds
        if not self._server_mode:
            return op(math.ceil(operation_timeout))
        # One operation may not outlast the single-attempt timeout however
        # many attempts it takes. Without that ceiling a backend that
        # accepts the connection and then stalls would cost the full
        # timeout per attempt, and the ensure path runs a dozen operations
        # back to back under the lifecycle lock - so the retry would
        # multiply the worst-case hold rather than bound it.
        return run_store_operation_with_retry(
            op,
            description=description,
            policy=None,
            max_elapsed_seconds=operation_timeout,
        )

    def _collection_exists(self, name: str) -> bool:
        """Return whether *name* exists, tolerating a transient backend blip.

        This is the first backend contact an index job makes, so it is the
        operation a refused connection kills first. Purely a query, so it
        is safe to replay.
        """
        return self._retried(
            f"collection exists {name}",
            lambda _timeout: self.client.collection_exists(name),
        )

    def _create_payload_index(
        self,
        collection_name: str,
        field_name: str,
        field_schema: Any,
    ) -> None:
        """Create one payload index idempotently under the bounded retry.

        Creating an index that already exists is a no-op in Qdrant, so the
        operation is safe to replay.
        """

        def attempt(timeout: int) -> object:
            # The suppression mutates process-global warning filters and is
            # not thread-safe, so it stays inside one attempt rather than
            # spanning the retry's backoff sleeps.
            with _suppress_local_qdrant_warnings():
                return self.client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field_name,
                    field_schema=field_schema,
                    timeout=timeout,
                )

        self._retried(
            f"create payload index {collection_name}.{field_name}",
            attempt,
        )

    def _scroll(self, **kwargs: Any) -> tuple[list[Record], Any]:
        """Page a collection under the bounded retry.

        A scroll is a pure query, so replaying an attempt that never
        reached the backend is safe.
        """
        return self._retried(
            f"scroll {kwargs.get('collection_name')}",
            lambda timeout: self.client.scroll(timeout=timeout, **kwargs),
        )

    def _retrieve(self, **kwargs: Any) -> list[Record]:
        """Fetch points by id under the bounded retry (a query, replay-safe)."""
        return self._retried(
            f"retrieve {kwargs.get('collection_name')}",
            lambda timeout: self.client.retrieve(timeout=timeout, **kwargs),
        )

    def _delete_points(self, **kwargs: Any) -> None:
        """Remove points under the bounded retry.

        Deletion by id list or by payload filter is idempotent - replaying
        an attempt that already landed removes nothing further - so a
        refused connection costs a retry rather than a failed job. Dropping
        a whole collection is not routed here: it is lifecycle-destructive
        rather than replay-safe.
        """
        self._retried(
            f"delete points {kwargs.get('collection_name')}",
            lambda timeout: self.client.delete(timeout=timeout, **kwargs),
        )

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

    def _lock_for(self, collection: str) -> threading.RLock:
        """Return *collection*'s reentrant lock, minting one on first use.

        The three collections a root is opened with are seeded at
        construction. A generation collection is created during a rebuild and
        needs the same guarantee, so its lock is minted on demand rather than
        raising for a name the constructor could not have known.

        ``setdefault`` is atomic, so concurrent first-callers agree on one
        lock object. It is deliberately not taken under the lifecycle lock:
        this runs on paths that already hold a collection lock, and acquiring
        the lifecycle lock beneath one would invert the documented order.
        """
        return self._collection_locks.setdefault(collection, threading.RLock())

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
        return self._lock_for(collection)

    @contextmanager
    def _point_write_lock(
        self,
        collection: str,
        policy: StoreWritePolicy | None,
    ) -> Generator[None]:
        """Acquire a local write lock within the caller's liveness budget."""
        if self._server_mode or policy is None:
            with self._point_lock(collection):
                yield
            return

        lock = self._lock_for(collection)
        acquired = False
        try:
            while not acquired:
                policy.wait(0.0)
                remaining = remaining_write_seconds(
                    policy,
                    description=f"{collection} write lock",
                )
                if remaining is None:
                    raise RuntimeError("managed write policy lost its deadline")
                acquired = lock.acquire(
                    timeout=min(_WRITE_LOCK_POLL_SECONDS, remaining)
                )
            policy.wait(0.0)
            yield
        finally:
            if acquired:
                lock.release()

    def close(self, *, force_after_seconds: float | None = None) -> None:
        """Release the Qdrant client and set it to ``None``.

        Takes the lifecycle lock and then every collection lock in a
        fixed order so no point operation is in flight when the client
        goes away.

        Normal callers pass nothing and get that fully-ordered, unbounded
        acquisition, so a legitimate slow point operation is always awaited
        rather than abandoned.

        A shutdown or rollback caller may pass ``force_after_seconds`` to bound
        the WHOLE acquisition end-to-end: the lifecycle lock and then the
        collection locks are still taken in the same fixed order, but the
        lifecycle-lock wait and each collection-lock wait are bounded against
        one shared deadline, and any lock still held past it is abandoned so the
        client is closed anyway - aborting a wedged consumer's in-flight write,
        or an in-flight open/create/drop holding the lifecycle lock, so a
        bounded daemon shutdown can complete instead of blocking forever. That
        abort is safe only because the caller is discarding state, which is why
        the bound is opt-in.
        """
        if force_after_seconds is None:
            with self._lifecycle_lock, acquire_collection_locks(self._collection_locks):
                self._release_client_locked()
            return
        self._force_close(force_after_seconds)

    def _force_close(self, deadline_seconds: float) -> None:
        """Close under a single shared deadline, abandoning any wedged lock.

        The lifecycle lock is acquired first (preserving the fixed order), but
        bounded: if an open/create/drop still holds it past the deadline it is
        abandoned rather than awaited, and the collection locks then get only
        the time that remains. A store-wide mutex is never introduced; each
        collection lock is still its own guard taken in name order.
        """
        deadline = time.monotonic() + max(0.0, deadline_seconds)
        lifecycle_held = self._lifecycle_lock.acquire(
            timeout=max(0.0, deadline - time.monotonic())
        )
        if not lifecycle_held:
            logger.warning(
                "Force-closing store %s without the lifecycle lock (held past "
                "the deadline); an in-flight open/create/drop is abandoned so "
                "shutdown can complete",
                self.db_path,
            )
        try:
            with acquire_collection_locks_bounded(
                self._collection_locks,
                deadline_seconds=max(0.0, deadline - time.monotonic()),
            ) as all_held:
                if not all_held:
                    logger.warning(
                        "Force-closing store %s past a held collection lock; a "
                        "wedged consumer's in-flight write is aborted so "
                        "shutdown can complete",
                        self.db_path,
                    )
                self._release_client_locked()
        finally:
            if lifecycle_held:
                self._lifecycle_lock.release()

    def _release_client_locked(self) -> None:
        """Close the Qdrant client and lock helper (caller holds the locks)."""
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
    ) -> Literal[False]:
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
            if self._collection_exists(name):
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
            self._guarded_upsert(
                self.TABLE_NAME,
                points,
                "vault chunks",
                write_policy=write_policy,
                wait=wait,
            )
        logger.info("Upserted %d vault chunk(s)", len(chunks))

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
            vector: dict[str, Any] = {"dense": chunk.vector}
            if chunk.sparse_indices:
                vector["sparse"] = models.SparseVector(
                    indices=chunk.sparse_indices,
                    values=chunk.sparse_values,
                )
            points.append(
                models.PointStruct(
                    id=self._stable_id(chunk.id),
                    vector=vector,
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
                    points=[_INGEST_FENCE_POINT_ID],
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
            self._delete_points(
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
        from qdrant_client import models

        self.ensure_document_table()
        with self._point_lock(self.DOCUMENT_TABLE_NAME):
            self._delete_points(
                collection_name=self.DOCUMENT_TABLE_NAME,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="source_path",
                                match=models.MatchAny(any=sorted(source_paths)),
                            )
                        ]
                    )
                ),
            )
        logger.info("Deleted document chunks for %d source(s)", len(source_paths))

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
                records, next_offset = self._scroll(
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
            self._delete_points(
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

    def get_all_code_ids(self, collection: str | None = None) -> set[str]:
        """Return the set of all code chunk ``id`` values in the store.

        Returns:
            Set of chunk IDs from the codebase_docs collection.
        """
        _target = self._code_collection(collection)
        self.ensure_code_table()
        with self._point_lock(_target):
            return self._scroll_all_ids(_target, "chunk_id")

    def scroll_code_content(
        self,
        *,
        limit: int = 100,
        offset: Any = None,
        source_paths: set[str] | None = None,
        with_vectors: bool = False,
    ) -> tuple[list[dict[str, Any]], Any]:
        """Return one bounded page from the code collection."""
        from qdrant_client import models

        raw_limit = cast("object", limit)
        if (
            isinstance(raw_limit, bool)
            or not isinstance(raw_limit, int)
            or raw_limit <= 0
        ):
            raise ValueError("code scroll limit must be a positive integer")
        if raw_limit > 1000:
            raise ValueError("code scroll limit must not exceed 1000")
        limit = raw_limit
        scroll_filter = None
        if source_paths is not None:
            if not source_paths:
                return [], None
            scroll_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="path",
                        match=models.MatchAny(any=sorted(source_paths)),
                    )
                ]
            )
        self.ensure_code_table()
        with self._point_lock(self.CODE_TABLE_NAME):
            records, next_offset = self._scroll(
                collection_name=self.CODE_TABLE_NAME,
                scroll_filter=scroll_filter,
                limit=limit,
                offset=offset,
                with_payload=True,
                with_vectors=with_vectors,
            )
        rows = [
            {
                "id": str(record.id),
                "payload": dict(record.payload or {}),
                "vector": record.vector if with_vectors else None,
            }
            for record in records
        ]
        return rows, next_offset

    def code_content_ids_exist(
        self, ids: Sequence[str], collection: str | None = None
    ) -> bool:
        """Return whether every requested code identity is currently stored."""
        _target = self._code_collection(collection)
        if not ids:
            return False
        self.ensure_code_table()
        return self._content_ids_exist(_target, ids)

    def get_all_document_content_ids(self) -> set[str]:
        """Return every deterministic ID in the document collection."""
        self.ensure_document_table()
        with self._point_lock(self.DOCUMENT_TABLE_NAME):
            return self._scroll_all_ids(self.DOCUMENT_TABLE_NAME, "document_id")

    def scroll_document_content(
        self,
        *,
        limit: int = 100,
        offset: Any = None,
        source_paths: set[str] | None = None,
        with_vectors: bool = False,
    ) -> tuple[list[dict[str, Any]], Any]:
        """Return one bounded page from the document collection."""
        from qdrant_client import models

        raw_limit = cast("object", limit)
        if (
            isinstance(raw_limit, bool)
            or not isinstance(raw_limit, int)
            or raw_limit <= 0
        ):
            raise ValueError("document scroll limit must be a positive integer")
        if raw_limit > 1000:
            raise ValueError("document scroll limit must not exceed 1000")
        limit = raw_limit
        scroll_filter = None
        if source_paths is not None:
            if not source_paths:
                return [], None
            scroll_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="source_path",
                        match=models.MatchAny(any=sorted(source_paths)),
                    )
                ]
            )
        self.ensure_document_table()
        with self._point_lock(self.DOCUMENT_TABLE_NAME):
            records, next_offset = self._scroll(
                collection_name=self.DOCUMENT_TABLE_NAME,
                scroll_filter=scroll_filter,
                limit=limit,
                offset=offset,
                with_payload=True,
                with_vectors=with_vectors,
            )
        rows = [
            {
                "id": str(record.id),
                "payload": dict(record.payload or {}),
                "vector": record.vector if with_vectors else None,
            }
            for record in records
        ]
        return rows, next_offset

    def document_content_ids_exist(self, ids: Sequence[str]) -> bool:
        """Return whether every requested document identity is currently stored."""
        if not ids:
            return False
        self.ensure_document_table()
        return self._content_ids_exist(self.DOCUMENT_TABLE_NAME, ids)

    def _content_ids_exist(
        self,
        collection: str,
        ids: Sequence[str],
    ) -> bool:
        """Check one bounded identity batch without scanning a collection."""
        point_ids = [self._stable_id(value) for value in ids]
        expected = {str(point_id) for point_id in point_ids}
        with self._point_lock(collection):
            records = self._retrieve(
                collection_name=collection,
                ids=point_ids,
                with_payload=False,
                with_vectors=False,
            )
        return {str(record.id) for record in records} == expected

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
                records, next_offset = self._scroll(
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

    def get_code_ids_by_paths(
        self, rel_paths: set[str], collection: str | None = None
    ) -> list[str]:
        """Return chunk IDs for code chunks belonging to the given file paths.

        Uses a Qdrant MatchAny filter on the ``path`` payload field
        instead of scanning all chunks.

        Args:
            rel_paths: Set of relative file paths to match against.

        Returns:
            List of chunk ID strings for matching code chunks.
        """
        _target = self._code_collection(collection)
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
        page_limit = self._id_scan_page_limit(_target)
        while True:
            with self._point_lock(_target):
                records, next_offset = self._scroll(
                    collection_name=_target,
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

    def _count_collection(self, collection: str) -> int:
        """Return the point count for one already-ensured collection."""
        with self._point_lock(collection):
            return self._retried(
                f"count {collection}",
                lambda timeout: (
                    self.client.count(collection_name=collection, timeout=timeout).count
                ),
            )

    def count(self) -> int:
        """Return total number of indexed documents in vault_docs.

        Returns:
            Point count in the vault_docs collection.
        """
        self.ensure_table()
        return self._count_collection(self.TABLE_NAME)

    def count_code(self, collection: str | None = None) -> int:
        """Return total number of indexed codebase chunks.

        Returns:
            Point count in the codebase_docs collection.
        """
        _target = self._code_collection(collection)
        self.ensure_code_table()
        return self._count_collection(_target)

    def count_code_files(self, collection: str | None = None) -> int:
        """Return how many distinct files the code collection holds points for.

        Counted from the collection rather than read from the sidecar, so it
        describes what is actually being served. A publication claiming more
        files than this is claiming breadth the collection does not hold - the
        shape a destroyed-and-partially-repopulated collection takes, where the
        point count alone still looks self-consistent.

        Scans the collection, so it belongs on a publication path and not on a
        query path.
        """
        _target = self._code_collection(collection)
        self.ensure_code_table()
        return len(self._scroll_all_ids(_target, "path"))

    def count_document(self) -> int:
        """Return the point count in the document collection."""
        self.ensure_document_table()
        return self._count_collection(self.DOCUMENT_TABLE_NAME)

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
            records: list[Record] = self._retrieve(
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
                records, next_offset = self._scroll(
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

    # ------------------------------------------------------------------
    # Donor reads: read-only, backend-aware retrieval from a sibling
    # collection so callers can adopt already-stored vectors instead of
    # re-encoding identical content. Nothing here writes, creates, drops,
    # or takes any lifecycle action against the donor.
    # ------------------------------------------------------------------

    def supports_donor_reads(self, donor_collection: str) -> bool:
        """Return whether this handle can read from *donor_collection*.

        Server mode: yes for any collection name - every root's namespaced
        collections live on the one shared server, so a cross-namespace
        read is just a read against another collection name. Local mode:
        only the collections this store instance already has open (its own
        three); the embedded engine is single-process and opening a foreign
        root's storage directory from here is not supported, so the
        capability is reported honestly instead of half-working.
        """
        if self._server_mode:
            return True
        return donor_collection in self._collection_locks

    def retrieve_donor_points(
        self,
        donor_collection: str,
        chunk_ids: Sequence[str],
    ) -> dict[str, DonorPoint]:
        """Fetch donor points by string chunk/point id, with vectors.

        Ids are hashed through the same stable point-id scheme the store
        writes with, so a caller passes the plain string ids it would have
        upserted under. Retrieval pages in bounded batches. Point-lock
        discipline is backend-aware: each batch takes the donor
        collection's own lock in local mode and no lock at all in server
        mode; no store-wide mutex is involved.

        Absence is normal, never an error: an unsupported donor (local
        mode, foreign collection), a donor collection that does not exist,
        ids with no stored point, and points missing a dense vector are
        all silently omitted from the result. Genuine transport failures
        still raise through the store's bounded-retry read path.

        Vectors come back exactly as the backend stores them. Note the
        embedded local engine persists cosine dense vectors in
        unit-normalized form, so a local read may return the normalized
        image of what was upserted - equivalent under cosine scoring.

        Args:
            donor_collection: Full (possibly root-prefixed) collection name.
            chunk_ids: String ids to look up.

        Returns:
            Mapping of found string id -> :class:`DonorPoint`; misses are
            simply absent.
        """
        if not chunk_ids or not self.supports_donor_reads(donor_collection):
            return {}
        if not self._collection_exists(donor_collection):
            return {}
        hits: dict[str, DonorPoint] = {}
        for start in range(0, len(chunk_ids), _DONOR_RETRIEVE_BATCH_SIZE):
            batch = chunk_ids[start : start + _DONOR_RETRIEVE_BATCH_SIZE]
            by_point_id = {self._stable_id(cid): cid for cid in batch}
            records = self._retrieve_donor_batch(donor_collection, list(by_point_id))
            for record in records:
                string_id = (
                    by_point_id.get(record.id) if isinstance(record.id, int) else None
                )
                if string_id is None:
                    continue
                donor_point = self._donor_point_from_record(record)
                if donor_point is not None:
                    hits[string_id] = donor_point
        return hits

    def _retrieve_donor_batch(
        self,
        donor_collection: str,
        point_ids: list[int],
    ) -> list[Record]:
        """Retrieve one id batch from a donor, treating not-found as empty.

        The donor can legitimately vanish between the existence pre-check
        and the retrieve (e.g. its root was pruned); that is a normal miss
        for every id in the batch, not a failure. Any other backend error
        propagates from the retried read path.
        """
        from qdrant_client.http.exceptions import UnexpectedResponse

        try:
            with self._point_lock(donor_collection):
                return self._retrieve(
                    collection_name=donor_collection,
                    ids=cast("list[int | str | UUID]", point_ids),
                    with_payload=True,
                    with_vectors=True,
                )
        except UnexpectedResponse as exc:
            if exc.status_code == 404:
                logger.debug(
                    "Donor collection %s disappeared mid-read; treating as miss",
                    donor_collection,
                )
                return []
            raise
        except ValueError as exc:
            # The embedded engine reports a missing collection as a
            # ValueError; anything else is a genuine fault.
            if "not found" in str(exc).lower():
                logger.debug(
                    "Donor collection %s not present locally; treating as miss",
                    donor_collection,
                )
                return []
            raise

    @staticmethod
    def _donor_point_from_record(record: Record) -> DonorPoint | None:
        """Convert one retrieved record into a :class:`DonorPoint`.

        Requires the named dense vector; a point without one is useless
        for vector adoption and reads as a miss (``None``). The named
        sparse vector is optional - points are written without one when
        sparse encoding is disabled - and is accepted in both the client
        model form (``.indices``/``.values``) and the plain dict form.
        """
        vectors = record.vector
        if not isinstance(vectors, dict):
            return None
        dense_raw = cast("Any", vectors.get(store_schema.DENSE_VECTOR_NAME))
        if not isinstance(dense_raw, list) or not dense_raw:
            return None
        dense_items = cast("list[Any]", dense_raw)
        if not all(isinstance(value, (int, float)) for value in dense_items):
            return None
        dense = [float(value) for value in cast("list[float]", dense_raw)]
        sparse_raw = cast("Any", vectors.get(store_schema.SPARSE_VECTOR_NAME))
        indices: Any = None
        values: Any = None
        if isinstance(sparse_raw, dict):
            sparse_map = cast("dict[str, Any]", sparse_raw)
            indices = sparse_map.get("indices")
            values = sparse_map.get("values")
        else:
            indices = getattr(sparse_raw, "indices", None)
            values = getattr(sparse_raw, "values", None)
        sparse_indices: list[int] | None = None
        sparse_values: list[float] | None = None
        if isinstance(indices, list) and isinstance(values, list):
            sparse_indices = [int(index) for index in cast("list[int]", indices)]
            sparse_values = [float(value) for value in cast("list[float]", values)]
        payload: dict[str, Any] = dict(record.payload) if record.payload else {}
        return DonorPoint(
            dense=dense,
            sparse_indices=sparse_indices,
            sparse_values=sparse_values,
            payload=payload,
        )
