"""Bounding tests for preprocess-hook-emitted document units.

Hook-emitted units were the one chunk class the pipeline never size-bounded:
the units branch emitted one chunk per unit verbatim, so a unit above the
encoder's sequence window was silently truncated at embed time and its tail
was never retrievable. These tests lock down the repaired contract:

- every chunk built from a unit respects the shared document split budget;
- fragments inherit the parent unit's provenance (title, section, anchor,
  locator, metadata) and cover the unit's content without gaps;
- point ids stay unique when one unit becomes many fragments - including for
  locator-bearing units, whose identity ignores the unit ordinal - and stay
  byte-identical across repeated runs of an unchanged unit, so ledger replay
  stays idempotent.
"""

from __future__ import annotations

import pytest

from .._store_models import DocumentLocator
from ..indexer._chunk_worker import (
    ChunkExecutionPolicy,
    _document_chunks_from_output,
)
from ..indexer._document_identity import document_point_id
from ..indexer._preprocess_schema import Locator, PreprocOutput, PreprocUnit

pytestmark = [pytest.mark.unit]

_POLICY = ChunkExecutionPolicy()
_BOUND = _POLICY.document_chunk_chars
_OVERLAP = _POLICY.document_chunk_overlap
_HASH = "f" * 40


def _output(units: list[PreprocUnit]) -> PreprocOutput:
    return PreprocOutput(
        schema_version=1,
        preprocessor_id="test-extractor",
        preprocessor_version="1.0",
        source_path="doc.pdf",
        units=units,
    )


def _assert_gapless_coverage(original: str, fragments: list[str]) -> None:
    """Assert in-order fragments cover the original text without a gap."""
    covered = 0
    for fragment in fragments:
        index = original.find(fragment)
        assert index != -1, "fragment is not a substring of the original text"
        assert index <= covered, "gap between consecutive fragments"
        covered = max(covered, index + len(fragment))
    assert covered == len(original), "fragments do not reach the end of the text"


def test_oversized_unit_is_split_into_bounded_fragments() -> None:
    words = " ".join(f"word{i}" for i in range(2000))
    assert len(words) > _BOUND
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
    _assert_gapless_coverage(words, [chunk.payload.content for chunk in chunks])


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


def test_fragment_ids_are_stable_across_repeated_runs() -> None:
    units = [
        PreprocUnit(text="short ordinal unit"),
        PreprocUnit(
            text="y" * (_BOUND + 100),
            locator=Locator(kind="page", value=1),
        ),
    ]
    first = _document_chunks_from_output(
        _output(units),
        rel_path="doc.pdf",
        content_hash=_HASH,
    )
    second = _document_chunks_from_output(
        _output(units),
        rel_path="doc.pdf",
        content_hash=_HASH,
    )
    assert [chunk.id for chunk in first] == [chunk.id for chunk in second]
    assert len(first) >= 3
    # The identity derivation is reproducible from its declared inputs.
    assert first[0].id == document_point_id(
        source_path="doc.pdf",
        unit_ordinal=0,
        content_fingerprint=_HASH,
        fragment_ordinal=0,
    )
    assert first[1].id == document_point_id(
        source_path="doc.pdf",
        unit_ordinal=1,
        content_fingerprint=_HASH,
        locator=DocumentLocator("page", 1, None),
        fragment_ordinal=0,
    )


def test_whitespace_only_unit_emits_no_chunk() -> None:
    chunks = _document_chunks_from_output(
        _output([PreprocUnit(text="   "), PreprocUnit(text="kept")]),
        rel_path="doc.pdf",
        content_hash=_HASH,
    )
    assert [chunk.payload.content for chunk in chunks] == ["kept"]
    assert chunks[0].payload.unit_ordinal == 1
