"""Qdrant vector store layer for vault semantic search.

Manages a persistent Qdrant local database with hybrid search (dense + SPLADE sparse).
All heavy imports are guarded so core vault tools work without RAG deps.
"""

from __future__ import annotations

import logging
import math
import threading
import time
import warnings
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Literal

from . import store_schema
from ._store_locks import (
    FileLock,
    ReentrantLock,
    VaultStoreLockedError,
    acquire_collection_locks,
    acquire_collection_locks_bounded,
)
from ._store_models import (
    resolve_served_code_collection,
    root_collection_prefix,
)
from ._store_search import _VaultSearchMixin
from ._store_writes import (
    StoreWritePolicy,
    remaining_write_seconds,
    run_store_operation_with_retry,
)

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable, Generator, Sequence
    from contextlib import AbstractContextManager

    from qdrant_client import QdrantClient
    from qdrant_client.http.models.models import (
        Record,
    )

logger = logging.getLogger(__name__)

__all__ = [
    "DonorPoint",
    "IngestVerificationError",
    "VaultStore",
]


_WRITE_LOCK_POLL_SECONDS = 0.1
# Donor reads page ids in bounded batches: large enough to amortize the
# round-trip, small enough that one response stays cheap to parse and hold.
DONOR_RETRIEVE_BATCH_SIZE = 256


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
INGEST_FENCE_POINT_ID = "00000000-0000-4000-8000-000000000000"


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
def suppress_local_qdrant_warnings() -> Generator[None]:
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


# The interpreter range this stack is built and tested against, and the single
# source of truth for the guard below. Keep in step with ``requires-python`` in
# pyproject.toml: the guard is the runtime half of that declaration, and the two
# disagreeing means an interpreter installs cleanly and then refuses to run.
#
# The floor is the oldest syntax and stdlib the code uses. The exclusive ceiling
# is the first interpreter nobody has run the suite on — it is a statement about
# what was tested, NOT about a known defect, so raising it is a matter of adding
# the version to the CI matrix and moving this tuple.
MIN_PYTHON: Final[tuple[int, int]] = (3, 13)
MAX_PYTHON_EXCLUSIVE: Final[tuple[int, int]] = (3, 15)


def _format_version_range() -> str:
    """Render the supported range the way ``requires-python`` spells it."""
    return (
        f">={MIN_PYTHON[0]}.{MIN_PYTHON[1]},"
        f"<{MAX_PYTHON_EXCLUSIVE[0]}.{MAX_PYTHON_EXCLUSIVE[1]}"
    )


def _interpreter_is_supported(version_info: Sequence[int | str]) -> bool:
    """Return True when *version_info* falls in the supported range.

    Args:
        version_info: A ``(major, minor, ...)`` tuple — pass ``sys.version_info`` or a
            plain ``(major, minor, micro)`` tuple in tests.

    Returns:
        ``True`` for any interpreter in ``[MIN_PYTHON, MAX_PYTHON_EXCLUSIVE)``.
    """
    version = (int(version_info[0]), int(version_info[1]))
    return MIN_PYTHON <= version < MAX_PYTHON_EXCLUSIVE


def _check_rag_deps() -> None:
    """Raise if the interpreter is unsupported or qdrant-client is not installed.

    The guard runs *before* importing ``qdrant_client`` so that an out-of-range
    interpreter names itself, rather than surfacing as whichever native extension
    happens to lack a wheel for that ABI.

    Raises:
        RuntimeError: If the running interpreter is outside the supported range.
        ImportError: If ``qdrant-client`` is not available.
    """
    import sys

    if not _interpreter_is_supported(sys.version_info):
        running = f"{sys.version_info[0]}.{sys.version_info[1]}"
        raise RuntimeError(
            f"vaultspec-rag supports CPython {_format_version_range()}; the running "
            f"interpreter is {running} ({sys.version.split()[0]}).  "
            "Install under a supported interpreter — 'uv tool install --python "
            f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]} vaultspec-rag[mcp]' for a tool "
            "install, or run via 'uv run vaultspec-rag ...' inside a project so uv "
            "selects the interpreter from its virtual environment."
        )
    try:
        import qdrant_client

        _ = qdrant_client
    except ImportError:
        raise ImportError("RAG dependencies not installed. Run: uv sync") from None


from .store_catalog import _VaultCatalogMixin  # noqa: E402
from .store_collections import _VaultCollectionMixin  # noqa: E402
from .store_donors import _VaultDonorMixin  # noqa: E402
from .store_ingest import _VaultIngestMixin  # noqa: E402


class VaultStore(
    _VaultSearchMixin,
    _VaultCollectionMixin,
    _VaultIngestMixin,
    _VaultCatalogMixin,
    _VaultDonorMixin,
):
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
                Defaults to store_schema.DEFAULT_DENSE_DIM (1024).

        Raises:
            ImportError: If qdrant-client is not installed.
            VaultStoreLockedError: If the Qdrant storage folder is already opened
                by another process.
        """
        _check_rag_deps()
        import pathlib as _pathlib

        from qdrant_client import QdrantClient as _QdrantClient

        from .config._settings import get_config

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
        self._collection_locks: dict[str, ReentrantLock] = {
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
            local_db_path = self.root_dir / cfg.data_dir / cfg.qdrant_dir
            local_db_path.mkdir(parents=True, exist_ok=True)
            self.db_path = local_db_path
            self._storage_probe_path = local_db_path
            self._lock_helper = FileLock(local_db_path / "exclusive.lock")
            if not self._lock_helper.acquire():
                raise VaultStoreLockedError(str(self.db_path))
            try:
                with suppress_local_qdrant_warnings():
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
        from .config._settings import get_config

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
            with suppress_local_qdrant_warnings():
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

    def _lock_for(self, collection: str) -> ReentrantLock:
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
