"""Donor-vector reuse operations for the vault store."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from . import store_schema

if TYPE_CHECKING:
    from collections.abc import Sequence
    from contextlib import AbstractContextManager

    from qdrant_client.conversions.common_types import PointId
    from qdrant_client.http.models.models import Record

    from ._store_locks import ReentrantLock

logger = logging.getLogger(__name__)

from .store_runtime import DONOR_RETRIEVE_BATCH_SIZE, DonorPoint  # noqa: E402

__all__ = ["_VaultDonorMixin"]


def _numeric_list(raw: Any) -> list[float] | None:
    """Return *raw* as floats when it is a list of numbers, else ``None``.

    Every vector half a donor record can carry - dense entries, sparse
    indices, sparse values - is a list of numbers, so one check covers all
    three. Entry types are verified before conversion because a stored
    vector is untrusted input: converting first turns a malformed entry
    into an exception escaping the read path instead of the miss this
    module promises. An empty list is a list of numbers and is returned as
    one; only the dense caller additionally requires it to be non-empty.
    """
    if not isinstance(raw, list):
        return None
    numbers: list[float] = []
    for value in cast("list[Any]", raw):
        if not isinstance(value, (int, float)):
            return None
        numbers.append(float(value))
    return numbers


class _VaultDonorMixin:
    """Read-only donor-vector reuse behaviour supplied to :class:`VaultStore`."""

    if TYPE_CHECKING:
        _server_mode: bool
        _collection_locks: dict[str, ReentrantLock]

        def _collection_exists(self, name: str) -> bool: ...

        @staticmethod
        def _stable_id(string_id: str) -> int: ...

        def _point_lock(self, collection: str) -> AbstractContextManager[object]: ...

        def _retrieve(
            self,
            *,
            collection_name: str,
            ids: Sequence[PointId],
            with_payload: bool | Sequence[str] = ...,
            with_vectors: bool | Sequence[str] = ...,
        ) -> list[Record]: ...

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
        for start in range(0, len(chunk_ids), DONOR_RETRIEVE_BATCH_SIZE):
            batch = chunk_ids[start : start + DONOR_RETRIEVE_BATCH_SIZE]
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
                    ids=point_ids,
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

        Requires the named dense vector; a point without one - or one whose
        stored entries are not numbers - is useless for vector adoption and
        reads as a miss (``None``). The named sparse vector is optional -
        points are written without one when sparse encoding is disabled -
        and is accepted in both the client model form (``.indices``/
        ``.values``) and the plain dict form. A sparse vector that is
        malformed in any way, in its shape or in its entries, is dropped
        exactly like an absent one: the point still reads as a hit carrying
        its usable dense vector, and adoption declines it downstream when
        the run needs sparse vectors.
        """
        vectors = record.vector
        if not isinstance(vectors, dict):
            return None
        dense = _numeric_list(cast("Any", vectors.get(store_schema.DENSE_VECTOR_NAME)))
        if not dense:
            return None
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
        raw_indices = _numeric_list(indices)
        sparse_values = _numeric_list(values)
        sparse_indices: list[int] | None = None
        if raw_indices is None or sparse_values is None:
            sparse_values = None
        else:
            sparse_indices = [int(index) for index in raw_indices]
        payload: dict[str, object] = dict(record.payload) if record.payload else {}
        return DonorPoint(
            dense=dense,
            sparse_indices=sparse_indices,
            sparse_values=sparse_values,
            payload=payload,
        )
