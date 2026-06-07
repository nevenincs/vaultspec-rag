"""Qdrant vector store layer for vault semantic search.

Manages a persistent Qdrant local database with hybrid search (dense + SPLADE sparse).
All heavy imports are guarded so core vault tools work without RAG deps.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import warnings
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pathlib
    from uuid import UUID

    from qdrant_client import QdrantClient
    from qdrant_client.http.models import Filter

    from .embeddings import SparseResult

logger = logging.getLogger(__name__)

__all__ = ["CodeChunk", "VaultDocument", "VaultStore", "VaultStoreLockedError"]


class VaultStoreLockedError(RuntimeError):
    """Raised when the Qdrant storage folder is already opened by another process.

    Attributes:
        db_path: Absolute path to the locked Qdrant storage folder.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        super().__init__(
            "Qdrant storage at "
            f"{db_path} is already in use by another process. "
            "Local-file-backed RAG storage is not parallel-safe across "
            "multiple vaultspec-rag processes; route concurrent searches "
            "through one resident service or retry after the holder exits.",
        )


class FileLock:
    """Cross-platform non-blocking file lock."""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        self.fd = None

    def acquire(self) -> bool:
        import os
        import sys

        try:
            self.fd = os.open(str(self.path), os.O_CREAT | os.O_WRONLY)
        except OSError:
            return False

        if sys.platform == "win32":
            import msvcrt

            try:
                msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                self.close()
                return False
        else:
            import fcntl

            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                self.close()
                return False

    def release(self) -> None:
        import os
        import sys

        if self.fd is not None:
            if sys.platform == "win32":
                import msvcrt

                try:
                    os.lseek(self.fd, 0, os.SEEK_SET)
                    msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl

                with suppress(OSError):
                    fcntl.flock(self.fd, fcntl.LOCK_UN)
            self.close()

    def close(self) -> None:
        import os

        if self.fd is not None:
            with suppress(OSError):
                os.close(self.fd)
            self.fd = None


EMBEDDING_DIM = 1024  # Qwen3-Embedding-0.6B default


@contextmanager
def _suppress_local_qdrant_warnings():
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


def _check_rag_deps() -> None:
    """Raise ImportError if qdrant-client is not installed.

    Raises:
        ImportError: If ``qdrant-client`` is not available.
    """
    try:
        import qdrant_client

        _ = qdrant_client
    except ImportError:
        raise ImportError("RAG dependencies not installed. Run: uv sync") from None


@dataclass
class VaultDocument:
    """Schema for a single vault document in the vector store.

    Attributes:
        id: Document stem used as the primary key.
        path: Relative path within the docs directory.
        doc_type: Document type string.
        feature: Feature tag without the leading #.
        date: ISO date string parsed from the document frontmatter.
        tags: List of frontmatter tags.
        related: List of related wiki-link strings.
        title: H1 heading extracted from the document body.
        content: Full markdown body text.
        vector: Dense embedding vector.
        sparse_indices: Sparse vector indices (SPLADE).
        sparse_values: Sparse vector values (SPLADE).
    """

    id: str
    path: str
    doc_type: str
    feature: str
    date: str
    tags: list[str]
    related: list[str]
    title: str
    content: str
    vector: list[float] = field(default_factory=list)
    sparse_indices: list[int] = field(default_factory=list)
    sparse_values: list[float] = field(default_factory=list)


@dataclass
class CodeChunk:
    """Schema for a source code chunk in the vector store.

    Attributes:
        id: Unique chunk ID.
        path: File path relative to project root.
        language: Programming language string.
        content: The actual source code text of the chunk.
        line_start: Starting line number in the source file.
        line_end: Ending line number in the source file.
        node_type: AST node type of the primary node (e.g. "function_definition").
        function_name: Name of the function/method this chunk belongs to, if any.
        class_name: Name of the enclosing class/struct/impl, if any.
        vector: Dense embedding vector.
        sparse_indices: Sparse vector indices (SPLADE).
        sparse_values: Sparse vector values (SPLADE).
    """

    id: str
    path: str
    language: str
    content: str
    line_start: int
    line_end: int
    node_type: str | None = None
    function_name: str | None = None
    class_name: str | None = None
    vector: list[float] = field(default_factory=list)
    sparse_indices: list[int] = field(default_factory=list)
    sparse_values: list[float] = field(default_factory=list)


class VaultStore:
    """Qdrant-backed vector store for vault documents and codebase chunks.

    Storage lives at ``{root_dir}/{data_dir}/{qdrant_dir}/`` (by default
    ``.vault/data/search-data/qdrant/``).  The collection ``vault_docs``
    holds one point per indexed document, and ``codebase_docs`` holds
    points per source code chunk.
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
        self._client_lock = threading.RLock()

        if cfg.qdrant_url:
            self.db_path = cfg.qdrant_url
            self._lock_helper = None
            try:
                self._client: QdrantClient | None = _QdrantClient(
                    url=cfg.qdrant_url,
                    api_key=cfg.qdrant_api_key,
                )
            except Exception as exc:
                logger.error(
                    "Failed to connect to Qdrant server at %s: %s", cfg.qdrant_url, exc
                )
                raise
        else:
            self.db_path = self.root_dir / cfg.data_dir / cfg.qdrant_dir
            self.db_path.mkdir(parents=True, exist_ok=True)
            self._lock_helper = FileLock(self.db_path / "exclusive.lock")
            if not self._lock_helper.acquire():
                raise VaultStoreLockedError(str(self.db_path))
            try:
                with _suppress_local_qdrant_warnings():
                    self._client: QdrantClient | None = _QdrantClient(
                        path=str(self.db_path),
                    )
            except RuntimeError as exc:
                self._lock_helper.release()
                if "already accessed by another instance" in str(exc):
                    raise VaultStoreLockedError(str(self.db_path)) from exc
                raise

        self._embedding_dim = embedding_dim or EMBEDDING_DIM
        self._vault_ensured = False
        self._code_ensured = False

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

    def close(self) -> None:
        """Release the Qdrant client and set it to ``None``."""
        with self._client_lock:
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

        with self._client_lock:
            if self.client.collection_exists(name):
                return

            from typing import Any

            kwargs: dict[str, Any] = {}
            if quantization_config is not None:
                kwargs["quantization_config"] = quantization_config

            self.client.create_collection(
                collection_name=name,
                vectors_config={
                    "dense": models.VectorParams(
                        size=self._embedding_dim,
                        distance=models.Distance.COSINE,
                    ),
                },
                sparse_vectors_config={
                    "sparse": models.SparseVectorParams(),
                },
                **kwargs,
            )
        logger.info("Created collection '%s' at %s", name, self.db_path)

    def drop_table(self) -> None:
        """Drop the vault_docs collection if it exists."""
        from qdrant_client import models

        with self._client_lock:
            if self.client.collection_exists(self.TABLE_NAME):
                with _suppress_local_qdrant_warnings():
                    self.client.delete(
                        collection_name=self.TABLE_NAME,
                        points_selector=models.Filter(),
                    )
                self.client.delete_collection(self.TABLE_NAME)
                logger.info("Dropped collection '%s'", self.TABLE_NAME)
            self._vault_ensured = False

    def drop_code_table(self) -> None:
        """Drop the codebase_docs collection if it exists."""
        from qdrant_client import models

        with self._client_lock:
            if self.client.collection_exists(self.CODE_TABLE_NAME):
                with _suppress_local_qdrant_warnings():
                    self.client.delete(
                        collection_name=self.CODE_TABLE_NAME,
                        points_selector=models.Filter(),
                    )
                self.client.delete_collection(self.CODE_TABLE_NAME)
                logger.info("Dropped collection '%s'", self.CODE_TABLE_NAME)
            self._code_ensured = False

    def ensure_table(self) -> None:
        """Create the vault_docs collection if it doesn't exist."""
        from qdrant_client import models

        with self._client_lock:
            if self._vault_ensured:
                return

            if self.client.collection_exists(self.TABLE_NAME):
                self._vault_ensured = True
                return

            self._ensure_collection(self.TABLE_NAME)

            for fname in ("doc_type", "feature", "date", "tags"):
                with _suppress_local_qdrant_warnings():
                    self.client.create_payload_index(
                        collection_name=self.TABLE_NAME,
                        field_name=fname,
                        field_schema=models.PayloadSchemaType.KEYWORD,
                    )
            self._vault_ensured = True

    def ensure_code_table(self) -> None:
        """Create the codebase_docs collection if it doesn't exist."""
        from qdrant_client import models

        with self._client_lock:
            if self._code_ensured:
                return

            if self.client.collection_exists(self.CODE_TABLE_NAME):
                self._code_ensured = True
                return

            self._ensure_collection(self.CODE_TABLE_NAME)

            # ``node_type`` is added to the KEYWORD index set so the
            # MCP `search_codebase(node_type=...)` filter does not fall
            # back to a linear scan on remote Qdrant deployments. Local
            # mode already returned correct results without the index;
            # this is purely a perf-on-remote completeness fix.
            for fname in (
                "path",
                "language",
                "function_name",
                "class_name",
                "node_type",
            ):
                with _suppress_local_qdrant_warnings():
                    self.client.create_payload_index(
                        collection_name=self.CODE_TABLE_NAME,
                        field_name=fname,
                        field_schema=models.PayloadSchemaType.KEYWORD,
                    )
            with _suppress_local_qdrant_warnings():
                self.client.create_payload_index(
                    collection_name=self.CODE_TABLE_NAME,
                    field_name="line_start",
                    field_schema=models.PayloadSchemaType.INTEGER,
                )
            self._code_ensured = True

    def upsert_documents(self, docs: list[VaultDocument]) -> None:
        """Insert or update documents by ``id``.

        Args:
            docs: Documents to insert or replace.
        """
        if not docs:
            return

        from qdrant_client import models

        points = []
        for doc in docs:
            vector: dict = {
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
                    payload={
                        "doc_id": doc.id,
                        "path": doc.path,
                        "doc_type": doc.doc_type,
                        "feature": doc.feature,
                        "date": doc.date,
                        "tags": doc.tags,
                        "related": doc.related,
                        "title": doc.title,
                        "content": doc.content,
                    },
                ),
            )

        with self._client_lock:
            self.ensure_table()
            self.client.upsert(
                collection_name=self.TABLE_NAME,
                points=points,
            )
        logger.info("Upserted %d document(s)", len(docs))

    def upsert_code_chunks(self, chunks: list[CodeChunk]) -> None:
        """Insert or update codebase chunks by ``id``.

        Args:
            chunks: Code chunks to insert or replace.
        """
        if not chunks:
            return

        from qdrant_client import models

        points = []
        for chunk in chunks:
            vector: dict = {
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
                    payload={
                        "chunk_id": chunk.id,
                        "path": chunk.path,
                        "language": chunk.language,
                        "content": chunk.content,
                        "line_start": chunk.line_start,
                        "line_end": chunk.line_end,
                        "node_type": chunk.node_type,
                        "function_name": chunk.function_name,
                        "class_name": chunk.class_name,
                    },
                ),
            )

        with self._client_lock:
            self.ensure_code_table()
            self.client.upsert(
                collection_name=self.CODE_TABLE_NAME,
                points=points,
            )
        logger.info("Upserted %d codebase chunk(s)", len(chunks))

    def delete_documents(self, ids: list[str]) -> None:
        """Remove documents by their ``id`` values.

        Args:
            ids: List of document stem IDs to delete.
        """
        if not ids:
            return
        from qdrant_client import models

        with self._client_lock:
            self.ensure_table()
            point_ids: list[int | str | UUID] = [self._stable_id(i) for i in ids]
            self.client.delete(
                collection_name=self.TABLE_NAME,
                points_selector=models.PointIdsList(points=point_ids),
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

        with self._client_lock:
            self.ensure_code_table()
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
        with self._client_lock:
            self.ensure_table()
            return self._scroll_all_ids(self.TABLE_NAME, "doc_id")

    def get_all_code_ids(self) -> set[str]:
        """Return the set of all code chunk ``id`` values in the store.

        Returns:
            Set of chunk IDs from the codebase_docs collection.
        """
        with self._client_lock:
            self.ensure_code_table()
            return self._scroll_all_ids(self.CODE_TABLE_NAME, "chunk_id")

    def _scroll_all_ids(self, collection: str, id_field: str) -> set[str]:
        """Scroll through all points and collect the id field from payloads.

        Args:
            collection: Qdrant collection name to scroll.
            id_field: Payload key that holds the string ID.

        Returns:
            Set of string IDs extracted from point payloads.
        """
        with self._client_lock:
            ids: set[str] = set()
            offset = None
            while True:
                points, next_offset = self.client.scroll(
                    collection_name=collection,
                    limit=1000,
                    offset=offset,
                    with_payload=[id_field],
                    with_vectors=False,
                )
                for point in points:
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

        with self._client_lock:
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
            offset = None
            while True:
                points, next_offset = self.client.scroll(
                    collection_name=self.CODE_TABLE_NAME,
                    scroll_filter=scroll_filter,
                    limit=1000,
                    offset=offset,
                    with_payload=["chunk_id"],
                    with_vectors=False,
                )
                for point in points:
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
        with self._client_lock:
            self.ensure_table()
            return self.client.count(collection_name=self.TABLE_NAME).count

    def count_code(self) -> int:
        """Return total number of indexed codebase chunks.

        Returns:
            Point count in the codebase_docs collection.
        """
        with self._client_lock:
            self.ensure_code_table()
            return self.client.count(collection_name=self.CODE_TABLE_NAME).count

    def get_by_id(self, doc_id: str) -> dict | None:
        """Retrieve a single document by ID, or ``None`` if not found.

        Args:
            doc_id: Document stem to look up.

        Returns:
            Document payload dict (vectors stripped), or ``None``
            if no matching point exists.
        """
        with self._client_lock:
            self.ensure_table()
            point_id = self._stable_id(doc_id)
            points = self.client.retrieve(
                collection_name=self.TABLE_NAME,
                ids=[point_id],
                with_payload=True,
                with_vectors=False,
            )
            if not points:
                return None
            payload = dict(points[0].payload) if points[0].payload else {}
            payload["id"] = payload.pop("doc_id", doc_id)
            return payload

    def list_all_documents(
        self,
        doc_type: str | None = None,
    ) -> list[dict]:
        """Return all vault documents via scroll, optionally filtered.

        Args:
            doc_type: If provided, only return documents of this type.

        Returns:
            List of document dicts (id, path, doc_type, title, etc.).
        """
        from qdrant_client import models

        with self._client_lock:
            self.ensure_table()
            scroll_filter = None
            if doc_type:
                scroll_filter = models.Filter(
                    must=[
                        models.FieldCondition(
                            key="doc_type",
                            match=models.MatchValue(value=doc_type),
                        ),
                    ],
                )

            docs: list[dict] = []
            offset = None
            while True:
                points, next_offset = self.client.scroll(
                    collection_name=self.TABLE_NAME,
                    scroll_filter=scroll_filter,
                    limit=1000,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for point in points:
                    payload = dict(point.payload) if point.payload else {}
                    payload["id"] = payload.pop("doc_id", str(point.id))
                    docs.append(payload)
                if next_offset is None:
                    break
                offset = next_offset
            return docs

    def hybrid_search(
        self,
        query_vector: list[float],
        _query_text: str,
        filters: dict[str, str] | None = None,
        limit: int = 5,
        *,
        sparse_vector: SparseResult | None = None,
        like_ids: list[str | int] | None = None,
        unlike_ids: list[str | int] | None = None,
    ) -> list[dict]:
        """Execute hybrid dense + sparse search with RRF on vault_docs.

        Args:
            query_vector: Dense query embedding.
            query_text: Kept for interface compat (search uses
                sparse_vector).
            filters: Metadata filters (doc_type, feature, date).
            limit: Max results to return.
            sparse_vector: Pre-computed SPLADE sparse embedding
                with ``.indices`` and ``.values`` attributes.
            like_ids: Optional list of document IDs or point IDs to guide
                search (positive feedback).
            unlike_ids: Optional list of document IDs or point IDs to push
                search away (negative feedback).

        Returns:
            List of result dicts with payload fields and
            ``_relevance_score``.

        Raises:
            UnexpectedResponse: Logged and caught internally;
                triggers dense-only fallback.
        """
        from qdrant_client import models

        query_filter = self._build_filter(filters)
        dense_vec = (
            query_vector if isinstance(query_vector, list) else query_vector.tolist()
        )
        dense_query = self._build_dense_query(dense_vec, like_ids, unlike_ids, models)
        prefetch = self._build_prefetch(
            dense_query, sparse_vector, query_filter, limit, models
        )
        scored_points = self._execute_hybrid_query(
            self.TABLE_NAME, False, prefetch, dense_query, query_filter, limit, models
        )

        return self._points_to_dicts(scored_points, "doc_id")

    def hybrid_search_codebase(
        self,
        query_vector: list[float],
        _query_text: str,
        filters: dict[str, str] | None = None,
        limit: int = 5,
        *,
        sparse_vector: SparseResult | None = None,
        like_ids: list[str | int] | None = None,
        unlike_ids: list[str | int] | None = None,
    ) -> list[dict]:
        """Execute hybrid dense + sparse search with RRF on codebase_docs.

        Args:
            query_vector: Dense query embedding.
            query_text: Kept for interface compat (search uses
                sparse_vector).
            filters: Codebase filters (language, path, etc.).
            limit: Max results to return.
            sparse_vector: Pre-computed SPLADE sparse embedding
                with ``.indices`` and ``.values`` attributes.
            like_ids: Optional list of chunk IDs or point IDs to guide
                search (positive feedback).
            unlike_ids: Optional list of chunk IDs or point IDs to push
                search away (negative feedback).

        Returns:
            List of result dicts with payload fields and
            ``_relevance_score``.

        Raises:
            UnexpectedResponse: Logged and caught internally;
                triggers dense-only fallback.
        """
        from qdrant_client import models

        query_filter = self._build_code_filter(filters)
        dense_vec = (
            query_vector if isinstance(query_vector, list) else query_vector.tolist()
        )
        dense_query = self._build_dense_query(dense_vec, like_ids, unlike_ids, models)
        prefetch = self._build_prefetch(
            dense_query, sparse_vector, query_filter, limit, models
        )
        scored_points = self._execute_hybrid_query(
            self.CODE_TABLE_NAME,
            True,
            prefetch,
            dense_query,
            query_filter,
            limit,
            models,
        )

        return self._points_to_dicts(scored_points, "chunk_id")

    def _build_dense_query(
        self,
        dense_vec: list[float],
        like_ids: list[str | int] | None,
        unlike_ids: list[str | int] | None,
        models,
    ):
        if not like_ids and not unlike_ids:
            return dense_vec

        from typing import Any

        pos: list[Any] = [dense_vec]
        if like_ids:
            pos.extend(
                self._stable_id(i) if isinstance(i, str) else i for i in like_ids
            )
        neg: list[Any] = (
            [self._stable_id(i) if isinstance(i, str) else i for i in unlike_ids]
            if unlike_ids
            else []
        )
        return models.RecommendQuery(
            recommend=models.RecommendInput(
                positive=pos,
                negative=neg,
            )
        )

    def _build_prefetch(
        self,
        dense_query,
        sparse_vector,
        query_filter,
        limit: int,
        models,
    ):
        prefetch = [
            models.Prefetch(
                query=dense_query,
                using="dense",
                limit=limit * 4,
                filter=query_filter,
            ),
        ]

        if sparse_vector is not None:
            prefetch.append(
                models.Prefetch(
                    query=models.SparseVector(
                        indices=list(sparse_vector.indices),
                        values=list(sparse_vector.values),
                    ),
                    using="sparse",
                    limit=limit * 4,
                    filter=query_filter,
                ),
            )
        return prefetch

    def _execute_hybrid_query(
        self,
        collection_name: str,
        is_codebase: bool,
        prefetch,
        dense_query,
        query_filter,
        limit: int,
        models,
    ):
        from qdrant_client.http.exceptions import (
            ResponseHandlingException,
            UnexpectedResponse,
        )

        with self._client_lock:
            if is_codebase:
                self.ensure_code_table()
            else:
                self.ensure_table()
            try:
                results = self.client.query_points(
                    collection_name=collection_name,
                    prefetch=prefetch,
                    query=models.RrfQuery(rrf=models.Rrf(k=60)),
                    limit=limit,
                )
                return results.points
            except (
                UnexpectedResponse,
                ResponseHandlingException,
                ValueError,
            ) as exc:
                logger.warning(
                    "Hybrid search failed (%s), falling back to dense-only",
                    exc,
                )
                fallback = self.client.query_points(
                    collection_name=collection_name,
                    query=dense_query,
                    using="dense",
                    limit=limit,
                    query_filter=query_filter,
                )
                return fallback.points

    @staticmethod
    def _points_to_dicts(scored_points: list, id_field: str) -> list[dict]:
        """Convert Qdrant ScoredPoint list to result dicts.

        Args:
            scored_points: List of Qdrant ``ScoredPoint`` objects.
            id_field: Payload key that holds the string ID
                (e.g. ``"doc_id"`` or ``"chunk_id"``).

        Returns:
            List of dicts with payload fields, ``id``, and
            ``_relevance_score``.
        """
        results = []
        for point in scored_points:
            row = dict(point.payload) if point.payload else {}
            if id_field not in row:
                logger.warning(
                    "Point %s missing id field '%s'",
                    point.id,
                    id_field,
                )
            row["id"] = row.pop(id_field, str(point.id))
            row["_relevance_score"] = point.score
            results.append(row)
        return results

    @staticmethod
    def _build_filter(
        filters: dict[str, str] | None,
    ) -> Filter | None:
        """Convert a filters dict into a Qdrant ``Filter``.

        Args:
            filters: Mapping of filter keys (``doc_type``,
                ``feature``, ``date``, ``tag``) to values.

        Returns:
            A ``qdrant_client.models.Filter`` instance, or ``None``
            if no valid conditions were produced.
        """
        if not filters:
            return None
        from qdrant_client import models

        conditions: list = []
        for key, value in filters.items():
            if not value:
                continue
            if key == "date":
                conditions.append(
                    models.FieldCondition(
                        key="date",
                        match=models.MatchValue(value=value),
                    ),
                )
            elif key == "tag":
                conditions.append(
                    models.FieldCondition(
                        key="tags",
                        match=models.MatchAny(any=[value]),
                    ),
                )
            elif key in ("doc_type", "feature"):
                conditions.append(
                    models.FieldCondition(
                        key=key,
                        match=models.MatchValue(value=value),
                    ),
                )
            else:
                logger.warning("Unknown filter key: %s", key)
        if not conditions:
            return None
        return models.Filter(must=conditions)

    @staticmethod
    def _build_code_filter(
        filters: dict[str, str] | None,
    ) -> Filter | None:
        """Convert codebase filters into a Qdrant ``Filter``.

        Args:
            filters: Mapping of codebase filter keys (``language``,
                ``path``, ``node_type``, ``function_name``,
                ``class_name``) to values.

        Returns:
            A ``qdrant_client.models.Filter`` instance, or ``None``
            if no valid conditions were produced.
        """
        if not filters:
            return None
        from qdrant_client import models

        conditions: list = []
        for key, value in filters.items():
            if key in (
                "language",
                "path",
                "node_type",
                "function_name",
                "class_name",
            ):
                conditions.append(
                    models.FieldCondition(
                        key=key,
                        match=models.MatchValue(value=value),
                    ),
                )
            else:
                logger.warning("Unknown filter key: %s", key)
        if not conditions:
            return None
        return models.Filter(must=conditions)

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
