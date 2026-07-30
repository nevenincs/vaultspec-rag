"""Catalog, inventory, and content-reading operations for the vault store."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from contextlib import AbstractContextManager
    from uuid import UUID

    from qdrant_client import QdrantClient
    from qdrant_client.http.models.models import Condition, Filter, Record

logger = logging.getLogger(__name__)

__all__ = ["_VaultCatalogMixin"]


@dataclass(frozen=True)
class _ContentScrollRequest:
    collection: str
    path_key: str
    noun: str
    ensure: Callable[[], None]
    limit: int
    offset: Any
    source_paths: set[str] | None
    with_vectors: bool


class _VaultCatalogMixin:
    """Catalog-side behaviour supplied to :class:`VaultStore`.

    The concrete store owns the client, collection lifecycle, locking, and
    retry helpers. These type-checking declarations express that host contract
    without adding runtime implementations to the mixin.
    """

    if TYPE_CHECKING:
        TABLE_NAME: str
        CODE_TABLE_NAME: str
        DOCUMENT_TABLE_NAME: str

        @property
        def client(self) -> QdrantClient: ...

        def ensure_table(self) -> None: ...

        def ensure_code_table(self, collection: str | None = None) -> None: ...

        def ensure_document_table(self) -> None: ...

        def _code_collection(self, collection: str | None) -> str: ...

        def _collection_exists(self, name: str) -> bool: ...

        def _point_lock(self, collection: str) -> AbstractContextManager[object]: ...

        def _scroll(self, **kwargs: Any) -> tuple[list[Record], Any]: ...

        def _retrieve(self, **kwargs: Any) -> list[Record]: ...

        def _delete_points(self, **kwargs: Any) -> None: ...

        def _id_scan_page_limit(self, collection: str) -> int: ...

        def _retried[T](self, description: str, op: Callable[[int], T]) -> T: ...

    def get_all_ids(self) -> set[str]:
        """Return the set of all document ``id`` values in the store.

        Returns:
            Set of document stem IDs from the vault_docs collection, empty
            when it does not exist. Creates nothing, for the same reason
            :meth:`count` does not.
        """
        if not self._collection_exists(self.TABLE_NAME):
            return set()
        with self._point_lock(self.TABLE_NAME):
            return self._scroll_all_ids(self.TABLE_NAME, "doc_id")

    def _scan_chunk_ordinals(
        self,
        doc_ids: set[str] | None,
    ) -> dict[str, set[int | None]]:
        """Scan the ordinals each vault document has points stored under.

        The one scan behind both public answers below. ``None`` stands for a
        point written before chunking, which carries no ordinal at all - kept
        as a member rather than dropped, because a document represented only
        by such points is a different fact from one with no points, and both
        callers need to tell them apart.

        Args:
            doc_ids: When given, restrict the scan to these documents.

        Returns:
            Mapping of document stem ID to the ordinals it has points under.
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

        ordinals: dict[str, set[int | None]] = {}
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
                ordinals.setdefault(str(doc_id), set()).add(
                    ordinal if isinstance(ordinal, int) else None
                )
            if next_offset is None:
                break
            offset = next_offset
        return ordinals

    def get_chunk_counts(
        self,
        doc_ids: set[str] | None = None,
    ) -> dict[str, int]:
        """Return the stored chunk count per vault document.

        Points written before chunking carry no ordinal and count as a
        single chunk. Used to detect documents that shrank between
        index runs so their stale tail chunks can be purged.

        This is the highest ordinal plus one, not a census of the points that
        exist. That is what the tail purge wants - it deletes an ordinal range
        and needs to know where the range ends - but it means a document
        missing an ordinal in the middle reports the same count as a whole one.
        A caller that needs to know which points actually exist must ask
        :meth:`get_stored_chunk_ordinals` instead.

        Args:
            doc_ids: When given, restrict the scan to these documents.

        Returns:
            Mapping of document stem ID to its stored chunk count.
        """
        return {
            doc_id: max(
                (ordinal + 1 if ordinal is not None else 1) for ordinal in ordinals
            )
            for doc_id, ordinals in self._scan_chunk_ordinals(doc_ids).items()
        }

    def get_stored_chunk_ordinals(
        self,
        doc_ids: set[str],
    ) -> dict[str, set[int]]:
        """Return the exact chunk ordinals each named document has points under.

        Answers "which points exist", where :meth:`get_chunk_counts` answers
        "how far do they reach". A caller about to write to specific point ids
        needs the former: the two disagree precisely when a document's ordinal
        range has a hole in it, and that is the case where writing by assumed
        ordinal silently reaches nothing.

        Points from the pre-chunking layout are excluded rather than mapped to
        an ordinal. They are stored under the bare document id, so no
        ordinal-keyed write addresses them at all, and reporting them as
        ordinal 0 would claim a point exists where the writer cannot reach one.

        Args:
            doc_ids: Documents to scan. An empty set scans nothing.

        Returns:
            Mapping of document stem ID to the ordinals it stores points under.
        """
        return {
            doc_id: {ordinal for ordinal in ordinals if ordinal is not None}
            for doc_id, ordinals in self._scan_chunk_ordinals(doc_ids).items()
        }

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

    def delete_prechunk_vault_points(self) -> int:
        """Delete every vault point written before heading-aware chunking.

        Points from the one-point-per-document layout carry no
        ``chunk_ordinal``, so they are invisible to both replacement paths:
        an upsert writes chunk-keyed points beside them, and the tail purge
        matches only ordinal ranges. After an in-place clean rebuild they
        would therefore survive as duplicate content, which is exactly the
        debris the old drop-first rebuild existed to remove - this deletes
        them by the payload shape only that layout produces, so a clean
        rebuild can replace in place without destroying anything first.

        Returns:
            The number of pre-chunking points that were present and removed.
        """
        from qdrant_client import models

        # ``IsEmpty`` matches points where the key is absent as well as null,
        # and absent is precisely how the pre-chunking layout looks.
        prechunk_filter = models.Filter(
            must=[
                models.IsEmptyCondition(
                    is_empty=models.PayloadField(key="chunk_ordinal"),
                ),
            ],
        )
        self.ensure_table()
        with self._point_lock(self.TABLE_NAME):
            stale = self.client.count(
                collection_name=self.TABLE_NAME,
                count_filter=prechunk_filter,
                exact=True,
            ).count
            if stale:
                self._delete_points(
                    collection_name=self.TABLE_NAME,
                    points_selector=models.FilterSelector(filter=prechunk_filter),
                )
        if stale:
            logger.info("Deleted %d pre-chunking vault point(s)", stale)
        return int(stale)

    def get_all_code_ids(self, collection: str | None = None) -> set[str]:
        """Return the set of all code chunk ``id`` values in the store.

        Returns:
            Set of chunk IDs from the targeted code collection, empty when it
            does not exist. Creates nothing, for the same reason
            :meth:`count_code` does not.
        """
        _target = self._code_collection(collection)
        if not self._collection_exists(_target):
            return set()
        with self._point_lock(_target):
            return self._scroll_all_ids(_target, "chunk_id")

    def _scroll_content(
        self, request: _ContentScrollRequest
    ) -> tuple[list[dict[str, Any]], Any]:
        """Return one bounded page from *collection*.

        The code and document pages differed only by the collection, the
        payload key holding the source path, and the noun in the two limit
        errors. ``ensure`` is passed rather than called by the public methods
        so the limit is still validated BEFORE anything creates a collection -
        a bad limit must not have a side effect.
        """
        from qdrant_client import models

        (
            collection,
            path_key,
            noun,
            ensure,
            limit,
            offset,
            source_paths,
            with_vectors,
        ) = (
            request.collection,
            request.path_key,
            request.noun,
            request.ensure,
            request.limit,
            request.offset,
            request.source_paths,
            request.with_vectors,
        )

        raw_limit = cast("object", limit)
        if (
            isinstance(raw_limit, bool)
            or not isinstance(raw_limit, int)
            or raw_limit <= 0
        ):
            raise ValueError(f"{noun} scroll limit must be a positive integer")
        if raw_limit > 1000:
            raise ValueError(f"{noun} scroll limit must not exceed 1000")
        limit = raw_limit
        scroll_filter = None
        if source_paths is not None:
            if not source_paths:
                return [], None
            scroll_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key=path_key,
                        match=models.MatchAny(any=sorted(source_paths)),
                    )
                ]
            )
        ensure()
        with self._point_lock(collection):
            records, next_offset = self._scroll(
                collection_name=collection,
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

    def scroll_code_content(
        self,
        *,
        limit: int = 100,
        offset: Any = None,
        source_paths: set[str] | None = None,
        with_vectors: bool = False,
    ) -> tuple[list[dict[str, Any]], Any]:
        """Return one bounded page from the code collection."""
        return self._scroll_content(
            _ContentScrollRequest(
                self.CODE_TABLE_NAME,
                "path",
                "code",
                self.ensure_code_table,
                limit,
                offset,
                source_paths,
                with_vectors,
            )
        )

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
        return self._scroll_content(
            _ContentScrollRequest(
                self.DOCUMENT_TABLE_NAME,
                "source_path",
                "document",
                self.ensure_document_table,
                limit,
                offset,
                source_paths,
                with_vectors,
            )
        )

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

        if not self._collection_exists(_target):
            return []

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
        """Return *collection*'s point count, creating nothing.

        The one counting reader behind every public count. An absent
        collection counts zero and stays absent, for two reasons.

        It keeps the answer honest. A read that created the name it failed to
        find would convert "this index does not exist" into "this index is
        empty", and every downstream guard compares counts, so the fabricated
        empty collection then reads as a healthy small one.

        It also keeps creation to one owner. A count runs on whatever handle
        its caller holds, and a root can be counted through a transient store
        opened while its project slot is still being constructed - a different
        instance from the one the index job writes through, with its own
        lifecycle lock and its own ensure latch, so neither serialises against
        the other. Both would find the collection absent and both would issue
        the create; the loser took a conflict from the backend, and when the
        loser was the index job that conflict failed the run. Creation belongs
        to the index path, which is the only caller that must have the
        collection before it can proceed.

        Returns:
            Point count in *collection*, or ``0`` when it does not exist.
        """
        if not self._collection_exists(collection):
            return 0
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
            Point count in the vault_docs collection, or ``0`` when it does
            not exist.
        """
        return self._count_collection(self.TABLE_NAME)

    def count_code(self, collection: str | None = None) -> int:
        """Return total number of indexed codebase chunks.

        Returns:
            Point count in the targeted code collection, or ``0`` when it does
            not exist.
        """
        return self._count_collection(self._code_collection(collection))

    def count_code_files(self, collection: str | None = None) -> int:
        """Return how many distinct files the code collection holds points for.

        Counted from the collection rather than read from the sidecar, so it
        describes what is actually being served. A publication claiming more
        files than this is claiming breadth the collection does not hold - the
        shape a destroyed-and-partially-repopulated collection takes, where the
        point count alone still looks self-consistent.

        Scans the collection, so it belongs on a publication path and not on a
        query path. Creates nothing, for the same reason :meth:`count_code`
        does not.
        """
        _target = self._code_collection(collection)
        if not self._collection_exists(_target):
            return 0
        return len(self._scroll_all_ids(_target, "path"))

    def count_document(self) -> int:
        """Return the point count in the document collection.

        Returns:
            Point count in the document collection, or ``0`` when it does not
            exist.
        """
        return self._count_collection(self.DOCUMENT_TABLE_NAME)

    def get_by_id(self, doc_id: str) -> dict[str, Any] | None:
        """Retrieve a single document by ID, or ``None`` if not found.

        Args:
            doc_id: Document stem to look up.

        Returns:
            Document payload dict (vectors stripped), or ``None`` if no
            matching point exists - including when the collection holding
            them does not. Creates nothing, for the same reason :meth:`count`
            does not.
        """
        if not self._collection_exists(self.TABLE_NAME):
            return None
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
