"""Production segment-to-ledger checkpoint behavior."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from .._store_models import CodeChunk
from ..indexer._content_policy import RootContentPolicy, SourceProfileVersion
from ..indexer._resolved_policy import resolve_index_policy
from ..indexer._run_checkpoint import CodeRunCheckpoint
from ..indexer._run_ledger import RunOperation, RunTerminalState
from ..indexer._run_policy import RunPolicy
from ..indexer._streaming import CodeFileSegment

if TYPE_CHECKING:
    from collections.abc import Mapping
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
    configuration: Mapping[str, object] | None = None,
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
        operation=RunOperation.FULL,
        clean=False,
        model_identity="model-v1",
        dense_dimensions=8,
        configuration=configuration or {"segment_chunks": 1, "queue_chunks": 2},
    )


def test_checkpoint_resumes_only_unconfirmed_segments(tmp_path: Path) -> None:
    checkpoint = _open(tmp_path)
    segments = _segments("src/example.py")
    digest = _digest("example")
    assert checkpoint.pending_segments(segments, digest) == segments

    assert (
        checkpoint.record_confirmed_segments(
            (segments[0],),
            {segments[0].path: digest},
        )
        == 1
    )
    checkpoint.ledger.finish_generation(
        checkpoint.generation_id,
        RunTerminalState.CANCELLED,
        detail="interrupted after one storage-confirmed segment",
    )

    resumed = _open(tmp_path)
    assert resumed.generation_id == checkpoint.generation_id
    assert resumed.pending_segments(segments, digest) == (segments[1],)
    assert (
        resumed.record_confirmed_segments(
            (segments[1],),
            {segments[1].path: digest},
        )
        == 1
    )
    assert resumed.pending_segments(segments, digest) == ()

    meta_path = tmp_path / ".state" / "code_meta.json"
    assert resumed.publish_metadata(meta_path) == 1
    published = resumed.publish_generation()
    assert published.complete
    assert meta_path.exists()


def test_checkpoint_signature_drift_starts_a_new_generation(tmp_path: Path) -> None:
    first = _open(tmp_path)
    first_segment = _segments("src/example.py")[0]
    digest = _digest("example")
    first.record_confirmed_segments((first_segment,), {first_segment.path: digest})

    changed = _open(tmp_path, configuration={"segment_chunks": 2, "queue_chunks": 2})
    assert changed.generation_id != first.generation_id
    invalidated = changed.ledger.generation(first.generation_id)
    assert invalidated.terminal_state is RunTerminalState.INVALIDATED
