"""Production segment-to-ledger checkpoint behavior."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from .._store_models import CodeChunk
from ..indexer._content_policy import (
    ContentKind,
    RootContentPolicy,
    SourceProfileVersion,
)
from ..indexer._file_state import FileState, FileStateKind
from ..indexer._resolved_policy import resolve_index_policy
from ..indexer._run_checkpoint import CodeRunCheckpoint, CodeRunConfiguration
from ..indexer._run_ledger import (
    FinalizationPhase,
    RunLedgerCompatibilityError,
    RunLedgerStateError,
    RunOperation,
    RunTerminalState,
)
from ..indexer._run_policy import RunPolicy
from ..indexer._streaming import CodeFileSegment

if TYPE_CHECKING:
    from pathlib import Path


def _digest(value: str) -> str:
    return hashlib.blake2b(value.encode("utf-8")).hexdigest()


def _chunk(path: str, identity: str) -> CodeChunk:
    return CodeChunk(
        id=identity,
        path=path,
        language="python",
        content=f"def {identity}():\n    return 1\n",
        line_start=1,
        line_end=2,
    )


def _segments(path: str) -> tuple[CodeFileSegment, CodeFileSegment]:
    # Point identities are unique per generation, so scope them to the path to
    # keep segments for two paths from claiming the same points.
    stem = path.rpartition("/")[2].partition(".")[0]
    first = _chunk(path, f"{stem}_first")
    second = _chunk(path, f"{stem}_second")
    return (
        CodeFileSegment(path, 0, (first,), 128, False),
        CodeFileSegment(path, 1, (second,), 128, True),
    )


def _index_path(checkpoint: CodeRunCheckpoint, path: str, digest: str) -> None:
    for segment in _segments(path):
        checkpoint.record_confirmed_segment(segment, digest)


def _interrupt(checkpoint: CodeRunCheckpoint, detail: str) -> None:
    checkpoint.ledger.finish_generation(
        checkpoint.generation_id,
        RunTerminalState.CANCELLED,
        detail=detail,
    )


def _open(
    tmp_path: Path,
    *,
    configuration: CodeRunConfiguration | None = None,
    operation: RunOperation = RunOperation.FULL,
) -> CodeRunCheckpoint:
    policy = resolve_index_policy(
        tmp_path,
        content_policy=RootContentPolicy(SourceProfileVersion.CONVENTIONAL_V1),
    )
    return CodeRunCheckpoint.open(
        data_root=tmp_path / ".state",
        root_dir=tmp_path,
        policy=policy,
        run_policy=RunPolicy(no_progress_timeout_seconds=30.0),
        operation=operation,
        clean=False,
        model_identity="model-v1",
        dense_dimensions=8,
        configuration=configuration or _configuration(),
    )


def _configuration() -> CodeRunConfiguration:
    return CodeRunConfiguration(
        segment_max_chunks=1,
        segment_max_bytes=1024,
        queue_max_chunks=2,
        queue_max_bytes=2048,
        slice_max_chunks=2,
        slice_max_bytes=2048,
        sparse_enabled=False,
        sparse_dimension=1,
        encode_batch_size=2,
        flush_slices=4,
    )


def test_checkpoint_resumes_only_unconfirmed_segments(tmp_path: Path) -> None:
    checkpoint = _open(tmp_path)
    segments = _segments("src/example.py")
    digest = _digest("example")
    assert tuple(checkpoint.pending_segments(segments, digest)) == segments

    assert checkpoint.record_confirmed_segment(segments[0], digest) is True
    checkpoint.ledger.finish_generation(
        checkpoint.generation_id,
        RunTerminalState.CANCELLED,
        detail="interrupted after one storage-confirmed segment",
    )

    resumed = _open(tmp_path)
    assert resumed.generation_id == checkpoint.generation_id
    assert tuple(resumed.pending_segments(segments, digest)) == (segments[1],)
    assert resumed.record_confirmed_segment(segments[1], digest) is True
    assert tuple(resumed.pending_segments(segments, digest)) == ()

    meta_path = tmp_path / ".state" / "code_meta.json"
    assert resumed.publish_metadata(meta_path, published_points=1) == 1
    published = resumed.publish_generation()
    assert published.complete
    assert meta_path.exists()


def test_confirmed_weighted_slice_records_all_segments_atomically(
    tmp_path: Path,
) -> None:
    checkpoint = _open(tmp_path)
    first = CodeFileSegment(
        "src/first.py",
        0,
        (_chunk("src/first.py", "first_file"),),
        128,
        True,
    )
    invalid_second = CodeFileSegment(
        "src/second.py",
        1,
        (_chunk("src/second.py", "second_file"),),
        128,
        True,
    )
    digests = {
        "src/first.py": _digest("first source"),
        "src/second.py": _digest("second source"),
    }

    with pytest.raises(RunLedgerStateError, match="ordinals must be contiguous"):
        checkpoint.record_confirmed_segments(
            (first, invalid_second),
            digests,
        )

    assert tuple(checkpoint.pending_segments((first,), digests[first.path])) == (first,)
    second = CodeFileSegment(
        "src/second.py",
        0,
        invalid_second.chunks,
        invalid_second.estimated_bytes,
        True,
    )
    assert checkpoint.record_confirmed_segments((first, second), digests) == 2
    assert tuple(checkpoint.pending_segments((first,), digests[first.path])) == ()
    assert tuple(checkpoint.pending_segments((second,), digests[second.path])) == ()
    assert checkpoint.run_policy.snapshot().durable_progress_count == 1


def test_drifted_path_maps_to_the_digest_recorded_when_it_was_indexed(
    tmp_path: Path,
) -> None:
    checkpoint = _open(tmp_path)
    indexed_digest = _digest("before the edit")
    _index_path(checkpoint, "src/drifted.py", indexed_digest)
    _interrupt(checkpoint, "interrupted after one path was indexed")

    resumed = _open(tmp_path)
    assert resumed.generation_id == checkpoint.generation_id

    # The mapped value is the superseded evidence, not the freshly observed
    # digest: the caller needs the recorded digest to clear the stale units
    # that claim the published points. Returning the observed digest instead
    # would leave the old evidence in place and duplicate the content.
    assert resumed.drifted_indexed_paths(
        {"src/drifted.py": _digest("after the edit")}
    ) == {"src/drifted.py": indexed_digest}


def test_unchanged_indexed_path_is_not_reported_as_drifted(tmp_path: Path) -> None:
    checkpoint = _open(tmp_path)
    digest = _digest("stable source")
    _index_path(checkpoint, "src/stable.py", digest)
    _interrupt(checkpoint, "interrupted after one path was indexed")

    resumed = _open(tmp_path)
    assert resumed.drifted_indexed_paths({"src/stable.py": digest}) == {}


def test_paths_without_indexed_evidence_are_never_reported_as_drifted(
    tmp_path: Path,
) -> None:
    checkpoint = _open(tmp_path)
    rejected_digest = _digest("an empty source")
    checkpoint.record_empty_source("src/empty.py", content_hash=rejected_digest)
    # A path whose first segment was confirmed but never reached its file end
    # carries committed units without an indexed state.
    checkpoint.record_confirmed_segment(
        _segments("src/partial.py")[0],
        _digest("a partially ingested source"),
    )
    _interrupt(checkpoint, "interrupted before any path was indexed")

    resumed = _open(tmp_path)
    # Only an indexed state is evidence a caller must supersede; a converged
    # rejection, a half-ingested path, and an unknown path carry none, so a
    # differing digest for any of them is an ordinary first ingestion.
    assert (
        resumed.drifted_indexed_paths(
            {
                "src/empty.py": _digest("no longer empty"),
                "src/partial.py": _digest("a changed partial source"),
                "src/unknown.py": _digest("never seen before"),
            }
        )
        == {}
    )


def test_fresh_generation_reports_no_drifted_paths(tmp_path: Path) -> None:
    checkpoint = _open(tmp_path)

    assert (
        checkpoint.drifted_indexed_paths(
            {
                "src/first.py": _digest("first source"),
                "src/second.py": _digest("second source"),
            }
        )
        == {}
    )


def test_indexed_path_outside_the_observed_digests_is_not_reported(
    tmp_path: Path,
) -> None:
    checkpoint = _open(tmp_path)
    _index_path(checkpoint, "src/carried.py", _digest("carried source"))
    _index_path(checkpoint, "src/reingested.py", _digest("before the edit"))
    _interrupt(checkpoint, "interrupted after two paths were indexed")

    resumed = _open(tmp_path)
    # The lookup is scoped to the supplied observation, so a carried indexed
    # path the caller did not observe is left alone. Reporting it would
    # re-open a path this run never re-ingests, dropping its published points
    # with nothing to replace them.
    assert resumed.drifted_indexed_paths(
        {"src/reingested.py": _digest("after the edit")}
    ) == {"src/reingested.py": _digest("before the edit")}


def test_checkpoint_signature_drift_starts_a_new_generation(tmp_path: Path) -> None:
    first = _open(tmp_path)
    first_segment = _segments("src/example.py")[0]
    digest = _digest("example")
    first.record_confirmed_segment(first_segment, digest)

    changed = _open(
        tmp_path,
        configuration=replace(_configuration(), segment_max_chunks=2),
    )
    assert changed.generation_id != first.generation_id
    invalidated = changed.ledger.generation(first.generation_id)
    assert invalidated.terminal_state is RunTerminalState.INVALIDATED


def test_checkpoint_metadata_refuses_unresolved_file_state(tmp_path: Path) -> None:
    checkpoint = _open(tmp_path)
    checkpoint.ledger.record_file_state(
        checkpoint.generation_id,
        FileState.failed(
            "src/unresolved.py",
            FileStateKind.CHUNK_FAILED,
            ContentKind.CODE,
            "chunking failed",
            content_hash=_digest("unresolved"),
        ),
    )

    meta_path = tmp_path / ".state" / "code_meta.json"
    with pytest.raises(RunLedgerStateError, match="unresolved"):
        checkpoint.publish_metadata(meta_path, published_points=1)
    assert not meta_path.exists()
    generation = checkpoint.ledger.generation(checkpoint.generation_id)
    assert generation.finalization_phase is FinalizationPhase.INGESTING


def test_first_incremental_requires_a_published_manifest(tmp_path: Path) -> None:
    with pytest.raises(RunLedgerCompatibilityError, match="full reconciliation"):
        _open(tmp_path, operation=RunOperation.INCREMENTAL)


@pytest.mark.parametrize(
    "interrupted_phase",
    [
        FinalizationPhase.STALE_RECONCILED,
        FinalizationPhase.METADATA_PUBLISHED,
        FinalizationPhase.GENERATION_PUBLISHED,
    ],
)
def test_checkpoint_resumes_each_publication_phase(
    tmp_path: Path,
    interrupted_phase: FinalizationPhase,
) -> None:
    checkpoint = _open(tmp_path)
    segment = _segments("src/finalize.py")[1]
    digest = _digest("finalize")
    for pending in _segments("src/finalize.py"):
        checkpoint.record_confirmed_segment(pending, digest)

    meta_path = tmp_path / ".state" / "code_meta.json"
    checkpoint.ledger.advance_finalization(
        checkpoint.generation_id,
        FinalizationPhase.STALE_RECONCILED,
    )
    if interrupted_phase in (
        FinalizationPhase.METADATA_PUBLISHED,
        FinalizationPhase.GENERATION_PUBLISHED,
    ):
        checkpoint.publish_metadata(meta_path, published_points=1)
    if interrupted_phase is FinalizationPhase.GENERATION_PUBLISHED:
        checkpoint.ledger.advance_finalization(
            checkpoint.generation_id,
            FinalizationPhase.GENERATION_PUBLISHED,
        )
    checkpoint.ledger.finish_generation(
        checkpoint.generation_id,
        RunTerminalState.CANCELLED,
        detail=f"interrupted at {interrupted_phase.value}",
    )

    resumed = _open(tmp_path)
    assert resumed.ingestion_complete
    resumed.publish_metadata(meta_path, published_points=1)
    published = resumed.publish_generation()

    assert published.complete
    assert published.finalization_phase is FinalizationPhase.COMPACTED
    assert meta_path.exists()
    assert resumed.ledger.unit_committed(
        resumed.generation_id,
        resumed.unit_for(segment, digest),
    )
