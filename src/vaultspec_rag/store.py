"""Qdrant vector store layer for vault semantic search.

Manages a persistent Qdrant local database with hybrid search (dense + SPLADE sparse).
All heavy imports are guarded so core vault tools work without RAG deps.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pathlib

    from qdrant_client import QdrantClient

    from .embeddings import SparseResult

logger = logging.getLogger(__name__)

__all__ = ["CodeChunk", "VaultDocument", "VaultStore"]

EMBEDDING_DIM = 1024  # Qwen3-Embedding-0.6B default


def _check_rag_deps() -> None:
    """Raise ImportError if qdrant-client is not installed."""
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
    vector: list[float] = field(default_factory=list)
    sparse_indices: list[int] = field(default_factory=list)
    sparse_values: list[float] = field(default_factory=list)


class VaultStore:
    """Qdrant-backed vector store for vault documents and codebase chunks.

    Storage lives at ``{root_dir}/.qdrant/``. The collection ``vault_docs``
    holds one point per indexed document, and ``codebase_docs`` holds
    points per source code chunk.
    """

    TABLE_NAME = "vault_docs"
    CODE_TABLE_NAME = "codebase_docs"

    def __init__(
        self, root_dir: pathlib.Path | str, embedding_dim: int | None = None
    ) -> None:
        """Connect to (or create) the Qdrant store at ``{root_dir}/.qdrant/``.

        Args:
            root_dir: Workspace root directory.
            embedding_dim: Dimensionality of the dense embedding vectors.
                Defaults to EMBEDDING_DIM (1024).

        Raises:
            ImportError: If qdrant-client is not installed.
        """
        _check_rag_deps()
        import pathlib as _pathlib

        from qdrant_client import QdrantClient as _QdrantClient

        from .config import get_config

        cfg = get_config()

        self.root_dir = _pathlib.Path(root_dir)
        self.db_path = self.root_dir / cfg.qdrant_dir
        self.db_path.mkdir(parents=True, exist_ok=True)
        self._client: QdrantClient = _QdrantClient(path=str(self.db_path))
        self._embedding_dim = embedding_dim or EMBEDDING_DIM

    def close(self) -> None:
        """Release the Qdrant client."""
        if self._client is not None:
            self._client.close()
            self._client = None  # type: ignore[assignment]

    def __enter__(self) -> VaultStore:
        """Return *self* to support use as a context manager."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> bool:
        """Close the store on context-manager exit."""
        self.close()
        return False

    def _ensure_collection(self, name: str) -> None:
        """Create a collection with dense + sparse vectors if it doesn't exist."""
        from qdrant_client import models

        if self._client.collection_exists(name):
            return

        self._client.create_collection(
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
        )
        logger.info("Created collection '%s' at %s", name, self.db_path)

    def ensure_table(self) -> None:
        """Create the vault_docs collection if it doesn't exist."""
        self._ensure_collection(self.TABLE_NAME)

    def ensure_code_table(self) -> None:
        """Create the codebase_docs collection if it doesn't exist."""
        self._ensure_collection(self.CODE_TABLE_NAME)

    def upsert_documents(self, docs: list[VaultDocument]) -> None:
        """Insert or update documents by ``id``.

        Args:
            docs: Documents to insert or replace.
        """
        if not docs:
            return

        from qdrant_client import models

        self.ensure_table()

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
                )
            )

        self._client.upsert(
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

        self.ensure_code_table()

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
                    },
                )
            )

        self._client.upsert(
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

        self.ensure_table()
        point_ids = [self._stable_id(i) for i in ids]
        self._client.delete(
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

        self.ensure_code_table()
        point_ids = [self._stable_id(i) for i in ids]
        self._client.delete(
            collection_name=self.CODE_TABLE_NAME,
            points_selector=models.PointIdsList(points=point_ids),
        )
        logger.info("Deleted %d code chunk(s)", len(ids))

    def get_all_ids(self) -> set[str]:
        """Return the set of all document ``id`` values in the store."""
        self.ensure_table()
        return self._scroll_all_ids(self.TABLE_NAME, "doc_id")

    def get_all_code_ids(self) -> set[str]:
        """Return the set of all code chunk ``id`` values in the store."""
        self.ensure_code_table()
        return self._scroll_all_ids(self.CODE_TABLE_NAME, "chunk_id")

    def _scroll_all_ids(self, collection: str, id_field: str) -> set[str]:
        """Scroll through all points and collect the id field from payloads."""
        ids: set[str] = set()
        offset = None
        while True:
            points, next_offset = self._client.scroll(
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

    def count(self) -> int:
        """Return total number of indexed documents in vault_docs."""
        self.ensure_table()
        return self._client.count(collection_name=self.TABLE_NAME).count

    def count_code(self) -> int:
        """Return total number of indexed codebase chunks."""
        self.ensure_code_table()
        return self._client.count(collection_name=self.CODE_TABLE_NAME).count

    def get_by_id(self, doc_id: str) -> dict | None:
        """Retrieve a single document by ID, or None if not found.

        Args:
            doc_id: Document stem to look up.

        Returns:
            Document dict with vector stripped, or None if not found.
        """
        self.ensure_table()
        point_id = self._stable_id(doc_id)
        points = self._client.retrieve(
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

    def hybrid_search(
        self,
        query_vector: list[float],
        query_text: str,  # noqa: ARG002
        filters: dict[str, str] | None = None,
        limit: int = 5,
        *,
        sparse_vector: SparseResult | None = None,
    ) -> list[dict]:
        """Execute hybrid dense + sparse search with RRF on vault_docs.

        Args:
            query_vector: Dense query embedding.
            query_text: Kept for interface compat (search uses sparse_vector).
            filters: Metadata filters (doc_type, feature, date).
            limit: Max results to return.
            sparse_vector: Optional sparse embedding with .indices and .values.

        Returns:
            List of result dicts with payload fields and ``_relevance_score``.
        """
        from qdrant_client import models

        self.ensure_table()
        if self.count() == 0:
            return []

        query_filter = self._build_filter(filters)
        dense_vec = (
            query_vector if isinstance(query_vector, list) else query_vector.tolist()
        )

        prefetch = [
            models.Prefetch(
                query=dense_vec,
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

        try:
            results = self._client.query_points(
                collection_name=self.TABLE_NAME,
                prefetch=prefetch,
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=limit,
            )
            scored_points = results.points
        except Exception as exc:
            logger.warning("Hybrid search failed (%s), falling back to dense-only", exc)
            fallback = self._client.query_points(
                collection_name=self.TABLE_NAME,
                query=dense_vec,
                using="dense",
                limit=limit,
                query_filter=query_filter,
            )
            scored_points = fallback.points

        return self._points_to_dicts(scored_points, "doc_id")

    def hybrid_search_codebase(
        self,
        query_vector: list[float],
        query_text: str,  # noqa: ARG002
        filters: dict[str, str] | None = None,
        limit: int = 5,
        *,
        sparse_vector: SparseResult | None = None,
    ) -> list[dict]:
        """Execute hybrid search on codebase_docs."""
        from qdrant_client import models

        self.ensure_code_table()
        if self.count_code() == 0:
            return []

        query_filter = self._build_code_filter(filters)
        dense_vec = (
            query_vector if isinstance(query_vector, list) else query_vector.tolist()
        )

        prefetch = [
            models.Prefetch(
                query=dense_vec,
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

        try:
            results = self._client.query_points(
                collection_name=self.CODE_TABLE_NAME,
                prefetch=prefetch,
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=limit,
            )
            scored_points = results.points
        except Exception as exc:
            logger.warning(
                "Codebase hybrid search failed (%s), falling back to dense-only",
                exc,
            )
            fallback = self._client.query_points(
                collection_name=self.CODE_TABLE_NAME,
                query=dense_vec,
                using="dense",
                limit=limit,
                query_filter=query_filter,
            )
            scored_points = fallback.points

        return self._points_to_dicts(scored_points, "chunk_id")

    @staticmethod
    def _points_to_dicts(scored_points: list, id_field: str) -> list[dict]:
        """Convert Qdrant ScoredPoint list to result dicts."""
        results = []
        for point in scored_points:
            row = dict(point.payload) if point.payload else {}
            row["id"] = row.pop(id_field, str(point.id))
            row["_relevance_score"] = point.score
            results.append(row)
        return results

    @staticmethod
    def _build_filter(
        filters: dict[str, str] | None,
    ):  # -> models.Filter | None
        """Convert a filters dict into a Qdrant Filter."""
        if not filters:
            return None
        from qdrant_client import models

        conditions: list = []
        for key, value in filters.items():
            if key == "date":
                conditions.append(
                    models.FieldCondition(
                        key="date",
                        match=models.MatchText(text=value),
                    )
                )
            elif key in ("doc_type", "feature"):
                conditions.append(
                    models.FieldCondition(
                        key=key,
                        match=models.MatchValue(value=value),
                    )
                )
        if not conditions:
            return None
        return models.Filter(must=conditions)

    @staticmethod
    def _build_code_filter(
        filters: dict[str, str] | None,
    ):  # -> models.Filter | None
        """Convert codebase filters into a Qdrant Filter."""
        if not filters:
            return None
        from qdrant_client import models

        conditions: list = []
        for key, value in filters.items():
            if key in ("language", "path"):
                conditions.append(
                    models.FieldCondition(
                        key=key,
                        match=models.MatchValue(value=value),
                    )
                )
        if not conditions:
            return None
        return models.Filter(must=conditions)

    @staticmethod
    def _stable_id(string_id: str) -> int:
        """Convert a string ID to a stable integer for Qdrant point ID.

        Qdrant local mode requires integer or UUID point IDs. We use a
        deterministic hash to map string document stems to integers.
        """
        import hashlib

        h = hashlib.sha256(string_id.encode("utf-8")).digest()
        return int.from_bytes(h[:8], byteorder="big") & 0x7FFFFFFFFFFFFFFF
