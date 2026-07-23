"""Bounding tests for preprocess-hook-emitted document units.

Hook-emitted units were the one chunk class the pipeline never size-bounded:
the units branch emitted one chunk per unit verbatim, so a unit above the
encoder's sequence window was silently truncated at embed time and its tail
was never retrievable. These tests lock down the repaired contract:

- every chunk built from a unit respects the shared splitter's bound;
- fragments inherit the parent unit's provenance (title, section, anchor,
  locator, metadata);
- point ids stay unique when one unit becomes many fragments - including for
  locator-bearing units, whose identity ignores the unit ordinal - and stay
  byte-identical to the pre-split construction for units that do not split,
  so unchanged files replay idempotently.
"""

from __future__ import annotations

from .._store_models import DocumentLocator
from ..indexer._chunk_worker import _document_chunks_from_output
from ..indexer._chunking import TextSplitter
from ..indexer._document_identity import document_point_id
from ..indexer._preprocess_schema import Locator, PreprocOutput, PreprocUnit

_BOUND = TextSplitter().chunk_size
_HASH = "f" * 40


def _output(units: list[PreprocUnit]) -> PreprocOutput:
    return PreprocOutput(
        schema_version=1,
        preprocessor_id="test-extractor",
        preprocessor_version="1.0",
        source_path="doc.pdf",
        units=units,
    )


def test_oversized_unit_is_split_into_bounded_fragments() -> None:
    words = " ".join(f"word{i}" for i in range(2000))
    unit = PreprocUnit(
        text=words,
        title="Page 3",
        section="Results",
        anchor="p3",
        locator=Locator(kind="page", value=3),
        metadata={"table": True},
    )
    chunks = _document_chunks_from_output(
        _output([unit]),
        rel_path="doc.pdf",
        content_hash=_HASH,
    )
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.payload.content) <= _BOUND
        assert chunk.payload.title == "Page 3"
        assert chunk.payload.section == "Results"
        assert chunk.payload.anchor == "p3"
        assert chunk.payload.locator == DocumentLocator("page", 3, None)
        assert chunk.payload.unit_ordinal == 0
    reassembled = " ".join(chunk.payload.content for chunk in chunks)
    assert reassembled.split() == words.split()


def test_locator_bearing_fragments_have_unique_ids() -> None:
    # A locator-bearing unit's point identity ignores the unit ordinal, so
    # only the fragment discriminator separates two fragments of one page.
    # This asserts id-set uniqueness specifically to catch a construction
    # that drops the fragment ordinal from the locator identity branch.
    unit = PreprocUnit(
        text="x" * (_BOUND * 3),
        locator=Locator(kind="page", value=7),
    )
    chunks = _document_chunks_from_output(
        _output([unit]),
        rel_path="doc.pdf",
        content_hash=_HASH,
    )
    assert len(chunks) >= 3
    ids = [chunk.id for chunk in chunks]
    assert len(set(ids)) == len(ids)


def test_unsplit_unit_keeps_pre_split_point_identity() -> None:
    ordinal_unit = PreprocUnit(text="short ordinal unit")
    locator_unit = PreprocUnit(
        text="short page unit",
        locator=Locator(kind="page", value=1),
    )
    chunks = _document_chunks_from_output(
        _output([ordinal_unit, locator_unit]),
        rel_path="doc.pdf",
        content_hash=_HASH,
    )
    assert len(chunks) == 2
    assert chunks[0].id == document_point_id(
        source_path="doc.pdf",
        unit_ordinal=0,
        content_fingerprint=_HASH,
    )
    assert chunks[1].id == document_point_id(
        source_path="doc.pdf",
        unit_ordinal=1,
        content_fingerprint=_HASH,
        locator=DocumentLocator("page", 1, None),
    )


def test_whitespace_only_unit_emits_no_chunk() -> None:
    chunks = _document_chunks_from_output(
        _output([PreprocUnit(text="   "), PreprocUnit(text="kept")]),
        rel_path="doc.pdf",
        content_hash=_HASH,
    )
    assert [chunk.payload.content for chunk in chunks] == ["kept"]
    assert chunks[0].payload.unit_ordinal == 1
