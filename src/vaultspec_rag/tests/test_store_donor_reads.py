"""Unit tests for the read-only donor retrieval path on VaultStore.

Exercises the real embedded backend in a tmp store: points are upserted
with synthetic vectors into one collection and read back by string id
through the donor path, asserting exact vector round-trips and honest
miss behavior. No mocks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ..store import CodeChunk, VaultStore

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_DENSE_DIM = 1024


def _dense(seed: int) -> list[float]:
    """A deterministic dense vector with exactly unit norm.

    Four 0.5 entries (norm exactly 1.0, every value float32-exact) so the
    embedded engine's cosine unit-normalization is an exact no-op and the
    round-trip can be asserted bit-for-bit.
    """
    vector = [0.0] * _DENSE_DIM
    for offset in range(4):
        vector[(seed * 7 + offset * 31) % _DENSE_DIM] = 0.5
    return vector


def _chunk(
    chunk_id: str,
    seed: int,
    *,
    with_sparse: bool = True,
) -> CodeChunk:
    sparse_indices = [seed, seed + 3, seed + 11] if with_sparse else []
    sparse_values = [0.5, 1.25, 2.75] if with_sparse else []
    return CodeChunk(
        id=chunk_id,
        path=f"src/{chunk_id.split(':', 1)[0]}",
        language="python",
        content=f"def fn_{seed}():\n    return {seed}",
        line_start=1,
        line_end=2,
        vector=_dense(seed),
        sparse_indices=sparse_indices,
        sparse_values=sparse_values,
    )


@pytest.fixture
def donor_store(tmp_path: Path) -> Generator[VaultStore]:
    """A real local-mode store in a tmp directory."""
    store = VaultStore(tmp_path)
    yield store
    store.close()


class TestDonorReadsLocalMode:
    """Donor retrieval against the embedded backend."""

    def test_round_trips_dense_sparse_and_payload_exactly(
        self, donor_store: VaultStore
    ) -> None:
        chunks = [_chunk("a.py:1-2", 1), _chunk("b.py:1-2", 2)]
        donor_store.upsert_code_chunks(chunks, write_policy=None)

        hits = donor_store.retrieve_donor_points(
            donor_store.CODE_TABLE_NAME, [c.id for c in chunks]
        )

        assert set(hits) == {"a.py:1-2", "b.py:1-2"}
        for chunk in chunks:
            point = hits[chunk.id]
            assert point.dense == chunk.vector
            assert point.sparse_indices == chunk.sparse_indices
            assert point.sparse_values == chunk.sparse_values
            assert point.payload["chunk_id"] == chunk.id
            assert point.payload["content"] == chunk.content

    def test_absent_ids_are_misses_not_errors(self, donor_store: VaultStore) -> None:
        donor_store.upsert_code_chunks([_chunk("a.py:1-2", 1)], write_policy=None)

        hits = donor_store.retrieve_donor_points(
            donor_store.CODE_TABLE_NAME,
            ["a.py:1-2", "never-indexed.py:1-2", "also-missing.py:9-9"],
        )

        assert set(hits) == {"a.py:1-2"}

    def test_point_without_sparse_vector_reports_none_sparse(
        self, donor_store: VaultStore
    ) -> None:
        donor_store.upsert_code_chunks(
            [_chunk("dense-only.py:1-2", 5, with_sparse=False)], write_policy=None
        )

        hits = donor_store.retrieve_donor_points(
            donor_store.CODE_TABLE_NAME, ["dense-only.py:1-2"]
        )

        point = hits["dense-only.py:1-2"]
        assert point.dense == _dense(5)
        assert point.sparse_indices is None
        assert point.sparse_values is None

    def test_missing_donor_collection_returns_empty(
        self, donor_store: VaultStore
    ) -> None:
        # The store's own vault collection has never been created here.
        hits = donor_store.retrieve_donor_points(
            donor_store.TABLE_NAME, ["some-doc#c0"]
        )
        assert hits == {}

    def test_foreign_collection_unsupported_in_local_mode(
        self, donor_store: VaultStore
    ) -> None:
        # Local mode cannot open another root's storage; capability is
        # reported honestly and the read returns empty instead of raising.
        assert donor_store.supports_donor_reads("r0123abcd_codebase_docs") is False
        hits = donor_store.retrieve_donor_points(
            "r0123abcd_codebase_docs", ["a.py:1-2"]
        )
        assert hits == {}

    def test_own_collections_supported_in_local_mode(
        self, donor_store: VaultStore
    ) -> None:
        assert donor_store.supports_donor_reads(donor_store.TABLE_NAME) is True
        assert donor_store.supports_donor_reads(donor_store.CODE_TABLE_NAME) is True
        assert donor_store.supports_donor_reads(donor_store.DOCUMENT_TABLE_NAME) is True

    def test_empty_id_batch_returns_empty(self, donor_store: VaultStore) -> None:
        assert donor_store.retrieve_donor_points(donor_store.CODE_TABLE_NAME, []) == {}

    def test_batches_larger_than_page_size_are_fully_retrieved(
        self, donor_store: VaultStore
    ) -> None:
        # Spans two retrieve batches (page size 256) plus interleaved misses.
        chunks = [_chunk(f"m{i}.py:1-2", i) for i in range(300)]
        donor_store.upsert_code_chunks(chunks, write_policy=None)

        requested = [c.id for c in chunks] + [f"gone{i}.py:1-2" for i in range(10)]
        hits = donor_store.retrieve_donor_points(donor_store.CODE_TABLE_NAME, requested)

        assert set(hits) == {c.id for c in chunks}
        assert hits["m0.py:1-2"].dense == _dense(0)
        assert hits["m299.py:1-2"].dense == _dense(299)
