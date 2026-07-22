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
    first = _chunk(path, "first")
    second = _chunk(path, "second")
    return (
        CodeFileSegment(path, 0, (first,), 128, False),
        CodeFileSegment(path, 1, (second,), 128, True),
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

    assert (
        checkpoint.record_confirmed_segment(segments[0], digest)
        is True
    )
    checkpoint.ledger.finish_generation(
        checkpoint.generation_id,
        RunTerminalState.CANCELLED,
        detail="interrupted after one storage-confirmed segment",
    )

    resumed = _open(tmp_path)
    assert resumed.generation_id == checkpoint.generation_id
    assert tuple(resumed.pending_segments(segments, digest)) == (segments[1],)
    assert (
        resumed.record_confirmed_segment(segments[1], digest)
        is True
    )
    assert tuple(resumed.pending_segments(segments, digest)) == ()

    meta_path = tmp_path / ".state" / "code_meta.json"
    assert resumed.publish_metadata(meta_path) == 1
    published = resumed.publish_generation()
    assert published.complete
    assert meta_path.exists()


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
        checkpoint.publish_metadata(meta_path)
    assert not meta_path.exists()
    generation = checkpoint.ledger.generation(checkpoint.generation_id)
    assert generation.finalization_phase is FinalizationPhase.INGESTING


def test_first_incremental_requires_a_published_manifest(tmp_path: Path) -> None:
    with pytest.raises(RunLedgerCompatibilityError, match="full reconciliation"):
        _open(tmp_path, operation=RunOperation.INCREMENTAL)
