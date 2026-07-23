"""Hybrid search and query-builder helpers for the Qdrant vault store.

Split out of ``store.py`` as a mixin that :class:`~vaultspec_rag.store.VaultStore`
inherits. The methods here own dense/sparse query assembly, the RRF hybrid
execution with its dense-only fallback, filter construction, and result
mapping. They acquire the store's point locks exactly as before via the
``_point_lock`` guard the concrete store provides; the lifecycle/point-lock
design and its ordering stay in ``store.py``. Qdrant is imported function-local
so importing this module stays torch- and qdrant-free at module scope, matching
the rest of the local-mode store layer.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

    from qdrant_client import QdrantClient
    from qdrant_client.http.models.models import (
        Condition,
        Filter,
        ScoredPoint,
    )

    from .embeddings import SparseResult

logger = logging.getLogger(__name__)

__all__ = ["_VaultSearchMixin"]


class _VaultSearchMixin:
    """Search-side behaviour for ``VaultStore``.

    Depends on collection names, the Qdrant client, the ensure-collection
    entry points, the point-lock guard, and the stable-id hash - all provided
    by the concrete ``VaultStore`` this mixes into. The declarations below are
    type-checker-only shadows of those members; the runtime implementations
    live on ``VaultStore``.
    """

    if TYPE_CHECKING:
        TABLE_NAME: str
        CODE_TABLE_NAME: str
        DOCUMENT_TABLE_NAME: str

        @property
        def client(self) -> QdrantClient: ...

        def ensure_table(self) -> None: ...

        def ensure_code_table(self) -> None: ...

        def ensure_document_table(self) -> None: ...

        def _point_lock(self, collection: str) -> AbstractContextManager[object]: ...

        @staticmethod
        def _stable_id(string_id: str) -> int: ...

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
    ) -> list[dict[str, Any]]:
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
        query_filter = self._build_filter(filters)
        dense_vec: list[float] = query_vector
        dense_query: Any = self._build_dense_query(
            dense_vec,
            like_ids,
            unlike_ids,
            id_resolver=self._resolve_vault_feedback_id,
        )
        prefetch: list[Any] = self._build_prefetch(
            dense_query, sparse_vector, query_filter, limit
        )
        scored_points = self._execute_hybrid_query(
            self.TABLE_NAME, "vault", prefetch, dense_query, query_filter, limit
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
        exclude_domains: list[str] | None = None,
        only_domains: list[str] | None = None,
    ) -> list[dict[str, Any]]:
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
        query_filter = self._build_code_filter(
            filters, exclude_domains=exclude_domains, only_domains=only_domains
        )
        dense_vec: list[float] = query_vector
        dense_query: Any = self._build_dense_query(dense_vec, like_ids, unlike_ids)
        prefetch: list[Any] = self._build_prefetch(
            dense_query, sparse_vector, query_filter, limit
        )
        scored_points = self._execute_hybrid_query(
            self.CODE_TABLE_NAME,
            "code",
            prefetch,
            dense_query,
            query_filter,
            limit,
        )

        return self._points_to_dicts(scored_points, "chunk_id")

    def hybrid_search_document(
        self,
        query_vector: list[float],
        _query_text: str,
        filters: dict[str, str] | None = None,
        limit: int = 5,
        *,
        sparse_vector: SparseResult | None = None,
    ) -> list[dict[str, Any]]:
        """Execute hybrid search against the independent document collection."""
        query_filter = self._build_document_filter(filters)
        dense_query: Any = query_vector
        prefetch = self._build_prefetch(
            dense_query,
            sparse_vector,
            query_filter,
            limit,
        )
        scored_points = self._execute_hybrid_query(
            self.DOCUMENT_TABLE_NAME,
            "document",
            prefetch,
            dense_query,
            query_filter,
            limit,
        )
        return self._points_to_dicts(scored_points, "document_id")

    def _resolve_vault_feedback_id(self, doc_id: str) -> int:
        """Map a vault document id to an existing feedback point id.

        Vault documents are stored one point per chunk, so the natural
        feedback anchor is the head chunk. Stores written before
        chunking keep their point under the bare document id; probe
        both and use whichever exists so feedback works across layouts.

        Args:
            doc_id: Document stem from a prior search result.

        Returns:
            The integer point id to feed into the recommend query.
        """
        head_id = self._stable_id(f"{doc_id}#c0")
        bare_id = self._stable_id(doc_id)
        try:
            self.ensure_table()
            with self._point_lock(self.TABLE_NAME):
                # Interactive search reads deliberately stay single-shot
                # rather than routing through the store's bounded retry:
                # a user-facing query should fail fast and fall back, not
                # spend seconds of backoff waiting for a backend to return.
                # Background index operations make the opposite trade.
                records = self.client.retrieve(
                    collection_name=self.TABLE_NAME,
                    ids=[head_id, bare_id],
                    with_payload=False,
                    with_vectors=False,
                )
        except (OSError, RuntimeError):
            logger.warning(
                "Could not resolve feedback id for %s; assuming the chunked head point",
                doc_id,
                exc_info=True,
            )
            return head_id
        existing = {record.id for record in records}
        return head_id if head_id in existing or bare_id not in existing else bare_id

    def _build_dense_query(
        self,
        dense_vec: list[float],
        like_ids: list[str | int] | None,
        unlike_ids: list[str | int] | None,
        id_resolver: Callable[[str], int] | None = None,
    ) -> Any:
        if not like_ids and not unlike_ids:
            return dense_vec

        from qdrant_client import models

        resolve = id_resolver or self._stable_id
        pos: list[Any] = [dense_vec]
        if like_ids:
            pos.extend(resolve(i) if isinstance(i, str) else i for i in like_ids)
        neg: list[Any] = (
            [resolve(i) if isinstance(i, str) else i for i in unlike_ids]
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
        dense_query: Any,
        sparse_vector: SparseResult | None,
        query_filter: Filter | None,
        limit: int,
    ) -> list[Any]:
        from qdrant_client import models

        prefetch: list[Any] = [
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
        source: Literal["vault", "code", "document"],
        prefetch: list[Any],
        dense_query: Any,
        query_filter: Filter | None,
        limit: int,
    ) -> list[ScoredPoint]:
        from qdrant_client import models
        from qdrant_client.http.exceptions import (
            ResponseHandlingException,
            UnexpectedResponse,
        )

        if source == "code":
            self.ensure_code_table()
        elif source == "document":
            self.ensure_document_table()
        else:
            self.ensure_table()

        with self._point_lock(collection_name):
            if len(prefetch) < 2:
                results = self.client.query_points(
                    collection_name=collection_name,
                    query=dense_query,
                    using="dense",
                    limit=limit,
                    query_filter=query_filter,
                )
                return results.points  # pyright: ignore[reportUnknownVariableType,reportUnknownMemberType]  # qdrant QueryResponse.points is untyped in stubs

            try:
                results = self.client.query_points(
                    collection_name=collection_name,
                    prefetch=prefetch,
                    query=models.RrfQuery(rrf=models.Rrf(k=60)),
                    limit=limit,
                )
                return results.points  # pyright: ignore[reportUnknownVariableType,reportUnknownMemberType]  # qdrant QueryResponse.points is untyped in stubs
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
                return fallback.points  # pyright: ignore[reportUnknownVariableType,reportUnknownMemberType]  # qdrant QueryResponse.points is untyped in stubs

    @staticmethod
    def _points_to_dicts(
        scored_points: list[ScoredPoint], id_field: str
    ) -> list[dict[str, Any]]:
        """Convert Qdrant ScoredPoint list to result dicts.

        Args:
            scored_points: List of Qdrant ``ScoredPoint`` objects.
            id_field: Payload key that holds the string ID
                (e.g. ``"doc_id"`` or ``"chunk_id"``).

        Returns:
            List of dicts with payload fields, ``id``, and
            ``_relevance_score``.
        """
        results: list[dict[str, Any]] = []
        for point in scored_points:
            row: dict[str, Any] = dict(point.payload) if point.payload else {}
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

        conditions: list[Condition] = []
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
            elif key == "doc_type":
                # A comma-separated doc_type selects a union of pipeline kinds
                # (e.g. "adr,plan"); a single value stays an exact match.
                values = [v.strip() for v in value.split(",") if v.strip()]
                if len(values) == 1:
                    conditions.append(
                        models.FieldCondition(
                            key="doc_type",
                            match=models.MatchValue(value=values[0]),
                        ),
                    )
                elif values:
                    conditions.append(
                        models.FieldCondition(
                            key="doc_type",
                            match=models.MatchAny(any=values),
                        ),
                    )
            elif key == "feature":
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
        *,
        exclude_domains: list[str] | None = None,
        only_domains: list[str] | None = None,
    ) -> Filter | None:
        """Convert codebase filters into a Qdrant ``Filter``.

        Args:
            filters: Mapping of codebase filter keys (``language``,
                ``path``, ``node_type``, ``function_name``,
                ``class_name``) to exact-match values.
            exclude_domains: Noise domains to drop via a ``must_not``
                ``MatchAny`` on the ``domain`` payload field (pushdown).
            only_domains: When set, keep only chunks whose ``domain`` is
                in this set via a ``must`` ``MatchAny`` (pushdown).

        Returns:
            A ``qdrant_client.models.Filter`` instance, or ``None``
            if no valid conditions were produced.
        """
        from qdrant_client import models

        conditions: list[Condition] = []
        for key, value in (filters or {}).items():
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
        if only_domains:
            conditions.append(
                models.FieldCondition(
                    key="domain",
                    match=models.MatchAny(any=list(only_domains)),
                ),
            )
        must_not: list[Condition] = []
        if exclude_domains:
            must_not.append(
                models.FieldCondition(
                    key="domain",
                    match=models.MatchAny(any=list(exclude_domains)),
                ),
            )
        if not conditions and not must_not:
            return None
        return models.Filter(must=conditions or None, must_not=must_not or None)

    @staticmethod
    def _build_document_filter(
        filters: dict[str, str] | None,
    ) -> Filter | None:
        """Build exact filters only for declared document payload indexes."""
        if not filters:
            return None
        from qdrant_client import models

        indexed = {
            "source_path",
            "content_fingerprint",
            "extractor_id",
            "extractor_version",
            "locator_kind",
            "locator_value_str",
        }
        conditions: list[Condition] = []
        for key, value in filters.items():
            if key not in indexed:
                logger.warning("Unknown document filter key: %s", key)
                continue
            conditions.append(
                models.FieldCondition(
                    key=key,
                    match=models.MatchValue(value=value),
                )
            )
        if not conditions:
            return None
        return models.Filter(must=conditions)
