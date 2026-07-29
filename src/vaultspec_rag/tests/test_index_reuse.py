"""Encode-seam donor vector reuse against the real embedded backend.

Every test runs the genuine store in a tmp directory: donor points are
upserted with synthetic vectors, and the seam under test
(``encode_and_upsert_code_slice`` -> ``_encode_slice_vector_fields``) is
exercised end to end. No behavior under test is mocked. The only doubles
are embedding-model stand-ins at the encoder boundary:

* ``_ExplodingModel`` raises on ANY forward call. It is used exclusively
  for the all-hits scenario, whose subject is precisely that zero forward
  passes occur - the double does not replace the behavior being verified,
  it is the tripwire that makes a violation fail loudly.
* ``_RecordingModel`` returns deterministic one-hot vectors per text and
  records exactly which texts it encoded, so miss-encode coverage and
  vector-to-chunk alignment are asserted against exact values.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from .._store_models import CodeChunk, VaultChunk
from ..config._settings import reset_config
from ..indexer._donor_candidates import CollectionKind
from ..indexer._reuse import (
    FALLBACK_ENCODE_SECONDS_PER_CHUNK,
    DonorReuseContext,
    ReuseStats,
    resolve_donor_reuse,
)
from ..indexer._streaming import (
    CodeSliceRequest,
    _code_embed_text,
    encode_and_upsert_code_slice,
)
from ..store_runtime import DonorPoint, VaultStore

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence
    from pathlib import Path

    from ..embeddings import EmbeddingModel

pytestmark = [pytest.mark.unit]

_DENSE_DIM = 1024


@pytest.fixture(autouse=True)
def _isolated_env(  # pyright: ignore[reportUnusedFunction]
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None]:
    """Isolate config-backed machine paths and force local mode."""
    monkeypatch.setenv("VAULTSPEC_RAG_STATUS_DIR", str(tmp_path / "status"))
    monkeypatch.setenv(
        "VAULTSPEC_RAG_QDRANT_STORAGE_DIR",
        str(tmp_path / "qdrant-server" / "storage"),
    )
    monkeypatch.delenv("VAULTSPEC_RAG_QDRANT_URL", raising=False)
    monkeypatch.delenv("VAULTSPEC_RAG_INDEX_REUSE", raising=False)
    reset_config()
    yield
    reset_config()


def _donor_dense(seed: int) -> list[float]:
    """Deterministic exactly-unit-norm donor vector (four 0.5 entries).

    Unit norm makes the embedded engine's cosine normalization an exact
    no-op, so donor adoption round-trips bit-for-bit. The four-hot shape
    is disjoint from the one-hot shape ``_encoded_dense`` produces, so a
    donor vector can never be mistaken for an encoded one.
    """
    vector = [0.0] * _DENSE_DIM
    for offset in range(4):
        vector[(seed * 7 + offset * 31) % _DENSE_DIM] = 0.5
    return vector


def _text_slot(text: str) -> int:
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=4).digest()
    return int.from_bytes(digest, "big") % _DENSE_DIM


def _encoded_dense(text: str) -> list[float]:
    """The exact one-hot unit vector ``_RecordingModel`` emits for a text."""
    vector = [0.0] * _DENSE_DIM
    vector[_text_slot(text)] = 1.0
    return vector


@dataclass
class _SparseRow:
    indices: list[int]
    values: list[float]


class _ExplodingModel:
    """Encoder tripwire for the all-hits case: any forward call fails.

    The assertion message names the property under test so a regression
    that routes an adopted point back through the GPU fails on the exact
    guarantee (zero forward passes for verified hits), not incidentally.
    """

    device = "cpu"

    def encode_documents_on_device(
        self,
        texts: list[str],
        batch_size: int | None = None,  # noqa: ARG002  # seam-imposed signature
        gpu_lock: object | None = None,  # noqa: ARG002  # seam-imposed signature
        on_bucket: object | None = None,  # noqa: ARG002  # seam-imposed signature
    ) -> object:
        raise AssertionError(f"dense forward ran for a fully adopted slice: {texts!r}")

    def encode_documents_sparse(
        self,
        texts: list[str],
        batch_size: int | None = None,  # noqa: ARG002  # seam-imposed signature
        gpu_lock: object | None = None,  # noqa: ARG002  # seam-imposed signature
    ) -> object:
        raise AssertionError(f"sparse forward ran for a fully adopted slice: {texts!r}")


class _RecordingModel:
    """Deterministic encoder double recording exactly what it encoded."""

    device = "cpu"

    def __init__(self) -> None:
        self.encoded_texts: list[str] = []

    def encode_documents_on_device(
        self,
        texts: list[str],
        batch_size: int | None = None,  # noqa: ARG002  # seam-imposed signature
        gpu_lock: object | None = None,  # noqa: ARG002  # seam-imposed signature
        on_bucket: object | None = None,  # noqa: ARG002  # seam-imposed signature
    ) -> list[list[float]]:
        self.encoded_texts.extend(texts)
        return [_encoded_dense(text) for text in texts]

    def encode_documents_sparse(
        self,
        texts: list[str],
        batch_size: int | None = None,  # noqa: ARG002  # seam-imposed signature
        gpu_lock: object | None = None,  # noqa: ARG002  # seam-imposed signature
    ) -> list[_SparseRow]:
        return [_SparseRow([_text_slot(text)], [1.0]) for text in texts]


def _as_model(double: object) -> EmbeddingModel:
    return cast("EmbeddingModel", double)


def _code_chunk(chunk_id: str, content: str) -> CodeChunk:
    return CodeChunk(
        id=chunk_id,
        path=f"src/{chunk_id.split(':', 1)[0]}",
        language="python",
        content=content,
        line_start=1,
        line_end=3,
    )


def _donor_chunk(chunk_id: str, seed: int, content: str) -> CodeChunk:
    chunk = _code_chunk(chunk_id, content)
    chunk.vector = _donor_dense(seed)
    chunk.sparse_indices = [seed, seed + 3]
    chunk.sparse_values = [0.5, 1.25]
    return chunk


@pytest.fixture
def store(tmp_path: Path) -> Generator[VaultStore]:
    real_store = VaultStore(tmp_path / "root")
    yield real_store
    real_store.close()


def _context(store: VaultStore, *collections: str) -> DonorReuseContext:
    names = collections or (store.CODE_TABLE_NAME,)
    return DonorReuseContext(
        store=store,
        donor_collections=tuple(names),
        stats=ReuseStats(donor_collections=tuple(names)),
    )


class TestAllHitsAdoptWithoutEncoding:
    def test_verified_hits_produce_zero_forward_passes(self, store: VaultStore) -> None:
        donors = [
            _donor_chunk("a.py:1-3", 1, "def a():\n    return 1"),
            _donor_chunk("b.py:1-3", 2, "def b():\n    return 2"),
            _donor_chunk("c.py:1-3", 3, "def c():\n    return 3"),
        ]
        store.upsert_code_chunks(donors, write_policy=None)
        fresh = [_code_chunk(donor.id, donor.content) for donor in donors]
        context = _context(store)

        # _ExplodingModel raises on any forward, so completing this call IS
        # the zero-encode proof; no interaction bookkeeping can pass vacuously.
        encode_and_upsert_code_slice(
            CodeSliceRequest(
                chunks=fresh,
                model=_as_model(_ExplodingModel()),
                store=store,
                gpu_lock=None,
                reuse=context,
            )
        )

        stored = store.retrieve_donor_points(
            store.CODE_TABLE_NAME, [chunk.id for chunk in fresh]
        )
        for seed, donor in enumerate(donors, start=1):
            point = stored[donor.id]
            assert point.dense == _donor_dense(seed)
            assert point.sparse_indices == [seed, seed + 3]
            assert point.sparse_values == [0.5, 1.25]
            # Payloads are rebuilt locally on every run, never copied.
            assert point.payload["content"] == donor.content
        assert context.stats.reuse_hits == 3
        assert context.stats.reuse_misses == 0
        assert context.stats.hit_rate == 1.0
        # No miss encode ran, so the estimate uses the documented fallback.
        assert context.stats.gpu_seconds_saved == pytest.approx(
            3 * FALLBACK_ENCODE_SECONDS_PER_CHUNK
        )


class TestContentVerification:
    def test_content_mismatch_at_same_point_id_is_a_miss_and_encodes(
        self, store: VaultStore
    ) -> None:
        donor = _donor_chunk("x.py:1-3", 7, "def x():\n    return 'old'")
        store.upsert_code_chunks([donor], write_policy=None)
        changed = _code_chunk(donor.id, "def x():\n    return 'new'")
        context = _context(store)
        model = _RecordingModel()

        encode_and_upsert_code_slice(
            CodeSliceRequest(
                chunks=[changed],
                model=_as_model(model),
                store=store,
                gpu_lock=None,
                reuse=context,
            )
        )

        # The specific rejection: the donor stores DIFFERENT bytes under the
        # identical point id, so the point must be counted as a miss and be
        # freshly encoded - never adopt the stale donor vector.
        assert context.stats.reuse_hits == 0
        assert context.stats.reuse_misses == 1
        assert model.encoded_texts == [_code_embed_text(changed)]
        stored = store.retrieve_donor_points(store.CODE_TABLE_NAME, [donor.id])
        assert stored[donor.id].dense == _encoded_dense(_code_embed_text(changed))
        assert stored[donor.id].dense != _donor_dense(7)

    def test_identical_content_at_same_point_id_is_adopted(
        self, store: VaultStore
    ) -> None:
        # Contrast pin for the mismatch test above: with byte-identical
        # content the SAME setup adopts, so the mismatch outcome can only
        # come from the content compare, not from some unrelated gate.
        donor = _donor_chunk("x.py:1-3", 7, "def x():\n    return 'old'")
        store.upsert_code_chunks([donor], write_policy=None)
        same = _code_chunk(donor.id, donor.content)
        context = _context(store)
        model = _RecordingModel()

        encode_and_upsert_code_slice(
            CodeSliceRequest(
                chunks=[same],
                model=_as_model(model),
                store=store,
                gpu_lock=None,
                reuse=context,
            )
        )

        assert context.stats.reuse_hits == 1
        assert context.stats.reuse_misses == 0
        assert model.encoded_texts == []
        stored = store.retrieve_donor_points(store.CODE_TABLE_NAME, [donor.id])
        assert stored[donor.id].dense == _donor_dense(7)


class _TripwireStore(VaultStore):
    """Real store whose donor-read path fails the test if ever reached."""

    def retrieve_donor_points(
        self,
        donor_collection: str,  # noqa: ARG002  # base-imposed signature
        chunk_ids: Sequence[str],  # noqa: ARG002  # base-imposed signature
    ) -> dict[str, DonorPoint]:
        raise AssertionError("donor read was consulted although reuse is disabled")


class TestFlagOffBaseline:
    def test_flag_off_resolves_to_no_context(
        self,
        store: VaultStore,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VAULTSPEC_RAG_INDEX_REUSE", "0")
        reset_config()
        stats, context = resolve_donor_reuse(
            tmp_path / "root",
            CollectionKind.CODE,
            store,
            expected_content_epoch="epoch",
        )
        assert stats is None
        assert context is None

    def test_reuse_none_never_consults_donors_and_encodes_everything(
        self, tmp_path: Path
    ) -> None:
        tripwire = _TripwireStore(tmp_path / "root")
        try:
            chunks = [
                _code_chunk("a.py:1-3", "def a():\n    return 1"),
                _code_chunk("b.py:1-3", "def b():\n    return 2"),
            ]
            model = _RecordingModel()

            # reuse=None is exactly what indexers pass when the knob is off;
            # the overridden donor read is the tripwire proving the baseline
            # path never reaches it.
            encode_and_upsert_code_slice(
                CodeSliceRequest(
                    chunks=chunks,
                    model=_as_model(model),
                    store=tripwire,
                    gpu_lock=None,
                    reuse=None,
                )
            )

            assert model.encoded_texts == [_code_embed_text(chunk) for chunk in chunks]
        finally:
            tripwire.close()


class TestMixedSliceAlignment:
    def test_hit_and_miss_vectors_land_on_the_right_chunks(
        self, store: VaultStore
    ) -> None:
        contents = [
            "def f0():\n    return 'zero'",
            "def f1():\n    return 'one and some longer body'",
            "def f2():\n    return 'two'",
            "def f3():\n    return 'three, longest body of them all here'",
            "def f4():\n    return 'four'",
        ]
        chunks = [
            _code_chunk(f"m{i}.py:1-3", content) for i, content in enumerate(contents)
        ]
        # Donors exist only for the interleaved positions 0, 2, and 4.
        donor_seeds = {chunks[i].id: i + 10 for i in (0, 2, 4)}
        store.upsert_code_chunks(
            [_donor_chunk(chunks[i].id, i + 10, chunks[i].content) for i in (0, 2, 4)],
            write_policy=None,
        )
        context = _context(store)
        model = _RecordingModel()

        encode_and_upsert_code_slice(
            CodeSliceRequest(
                chunks=list(chunks),
                model=_as_model(model),
                store=store,
                gpu_lock=None,
                reuse=context,
            )
        )

        # Only the misses reach the encoder, in their original slice order.
        assert model.encoded_texts == [
            _code_embed_text(chunks[1]),
            _code_embed_text(chunks[3]),
        ]
        stored = store.retrieve_donor_points(
            store.CODE_TABLE_NAME, [chunk.id for chunk in chunks]
        )
        for index, chunk in enumerate(chunks):
            point = stored[chunk.id]
            if chunk.id in donor_seeds:
                # Hit positions carry EXACTLY their own donor's vector.
                assert point.dense == _donor_dense(donor_seeds[chunk.id]), (
                    f"chunk {index} lost its donor vector"
                )
                assert point.sparse_indices == [index + 10, index + 13]
            else:
                # Miss positions carry EXACTLY their own encoded vector.
                assert point.dense == _encoded_dense(_code_embed_text(chunk)), (
                    f"chunk {index} was mis-aligned with another row"
                )
                assert point.sparse_indices == [_text_slot(_code_embed_text(chunk))]
        assert context.stats.reuse_hits == 3
        assert context.stats.reuse_misses == 2
        assert context.stats.hit_rate == pytest.approx(0.6)
        # Misses were encoded, so the estimate derives from measured timing.
        assert context.stats.encoded_chunks == 2
        assert context.stats.gpu_seconds_saved >= 0.0


class _FailingDonorStore(VaultStore):
    """Real store whose donor reads always raise a transport-class error."""

    def retrieve_donor_points(
        self,
        donor_collection: str,  # noqa: ARG002  # base-imposed signature
        chunk_ids: Sequence[str],  # noqa: ARG002  # base-imposed signature
    ) -> dict[str, DonorPoint]:
        raise RuntimeError("donor backend unreachable")


class TestDonorFailureDegradesToEncode:
    def test_donor_read_exception_encodes_all_and_never_fails_the_job(
        self, tmp_path: Path
    ) -> None:
        failing = _FailingDonorStore(tmp_path / "root")
        try:
            chunks = [
                _code_chunk("a.py:1-3", "def a():\n    return 1"),
                _code_chunk("b.py:1-3", "def b():\n    return 2"),
            ]
            context = _context(failing)
            model = _RecordingModel()

            encode_and_upsert_code_slice(
                CodeSliceRequest(
                    chunks=chunks,
                    model=_as_model(model),
                    store=failing,
                    gpu_lock=None,
                    reuse=context,
                )
            )

            assert model.encoded_texts == [_code_embed_text(chunk) for chunk in chunks]
            assert context.stats.reuse_hits == 0
            assert context.stats.reuse_misses == 2
        finally:
            failing.close()


class TestVaultChunkIdentity:
    def test_vault_chunk_adopts_by_point_key_and_text(self, store: VaultStore) -> None:
        # Binds the vault identity mapping (point_key -> stored ``content``
        # payload field carrying ``text``) against the real writer, so an id
        # or payload drift surfaces here rather than as silent misses.
        donor = VaultChunk(
            doc_id="adr/2026-01-01-x-adr",
            ordinal=0,
            chunk_count=1,
            text="## Decision\n\nchunked body",
            path="adr/2026-01-01-x-adr.md",
            doc_type="adr",
            feature="x",
            date="2026-01-01",
            tags=["#adr", "#x"],
            related=[],
            title="x adr",
            vector=_donor_dense(21),
            sparse_indices=[21],
            sparse_values=[1.0],
        )
        store.upsert_document_chunks([donor], write_policy=None)
        fresh = VaultChunk(
            doc_id=donor.doc_id,
            ordinal=0,
            chunk_count=1,
            text=donor.text,
            path=donor.path,
            doc_type=donor.doc_type,
            feature=donor.feature,
            date=donor.date,
            tags=list(donor.tags),
            related=[],
            title=donor.title,
        )
        context = _context(store, store.TABLE_NAME)

        adopted = context.adopt_verified_vectors([fresh], sparse_required=True)

        assert adopted == [True]
        assert fresh.vector == _donor_dense(21)
        assert fresh.sparse_indices == [21]
        assert context.stats.reuse_hits == 1

    def test_vault_chunk_text_mismatch_is_a_miss(self, store: VaultStore) -> None:
        donor = VaultChunk(
            doc_id="adr/2026-01-01-x-adr",
            ordinal=0,
            chunk_count=1,
            text="original text",
            path="adr/2026-01-01-x-adr.md",
            doc_type="adr",
            feature="x",
            date="2026-01-01",
            tags=["#adr", "#x"],
            related=[],
            title="x adr",
            vector=_donor_dense(22),
            sparse_indices=[22],
            sparse_values=[1.0],
        )
        store.upsert_document_chunks([donor], write_policy=None)
        fresh = VaultChunk(
            doc_id=donor.doc_id,
            ordinal=0,
            chunk_count=1,
            text="edited text",
            path=donor.path,
            doc_type=donor.doc_type,
            feature=donor.feature,
            date=donor.date,
            tags=list(donor.tags),
            related=[],
            title=donor.title,
        )
        context = _context(store, store.TABLE_NAME)

        adopted = context.adopt_verified_vectors([fresh], sparse_required=True)

        assert adopted == [False]
        assert fresh.vector == []
        assert context.stats.reuse_misses == 1


class TestResolveTelemetry:
    def test_knob_on_with_no_donors_records_donor_absent(
        self, store: VaultStore, tmp_path: Path
    ) -> None:
        stats, context = resolve_donor_reuse(
            tmp_path / "root",
            CollectionKind.CODE,
            store,
            expected_content_epoch="epoch",
        )
        assert context is None
        assert stats is not None
        assert stats.donor_absent is True
        snapshot = stats.snapshot()
        assert snapshot == {
            "reuse_hits": 0,
            "reuse_misses": 0,
            "hit_rate": 0.0,
            "gpu_seconds_saved": 0.0,
            "donor_absent": True,
            "donor_collections": [],
        }

    def test_sparse_required_rejects_dense_only_donor_points(
        self, store: VaultStore
    ) -> None:
        donor = _code_chunk("s.py:1-3", "def s():\n    return 5")
        donor.vector = _donor_dense(5)
        store.upsert_code_chunks([donor], write_policy=None)
        fresh = _code_chunk(donor.id, donor.content)
        context = _context(store)

        adopted = context.adopt_verified_vectors([fresh], sparse_required=True)

        # A run that writes sparse vectors must not adopt a donor point
        # lacking one - the point would silently lose sparse recall.
        assert adopted == [False]
        assert fresh.vector == []
