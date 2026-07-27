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
from ..indexer._drift_owner import CodeDriftOwner
from ..indexer._file_state import FileState, FileStateKind
from ..indexer._resolved_policy import IndexPolicyResolutionOptions, resolve_index_policy
from ..indexer._run_checkpoint import CodeRunCheckpoint, CodeRunConfiguration
from ..indexer._run_ledger import (
    FinalizationPhase,
    RunLedgerCompatibilityError,
    RunLedgerIndexedPathCollisionError,
    RunLedgerStateError,
    RunOperation,
    RunTerminalState,
)
from ..indexer._run_policy import RunPolicy
from ..indexer._streaming import CodeFileSegment

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ..store_runtime import VaultStore

pytestmark = [pytest.mark.unit]


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


def _segments(path: str, *, marker: str = "") -> tuple[CodeFileSegment, ...]:
    # Point identities are unique per generation, so scope them to the path to
    # keep segments for two paths from claiming the same points. ``marker``
    # stands in for rewritten content: chunk identity embeds a content hash, so
    # a real edit mints fresh point identities rather than reusing the old ones.
    stem = path.rpartition("/")[2].partition(".")[0]
    first = _chunk(path, f"{stem}{marker}_first")
    second = _chunk(path, f"{stem}{marker}_second")
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
        IndexPolicyResolutionOptions(
            content_policy=RootContentPolicy(SourceProfileVersion.CONVENTIONAL_V1)
        ),
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


# ---------------------------------------------------------------------------
# Drift ownership: a path whose source moves while the run records it.
# ---------------------------------------------------------------------------

#: Narrow enough to keep the real collection cheap, wide enough to be a vector.
_DENSE_DIM = 8


@pytest.fixture
def drift_store(
    isolated_singleton_dirs: Path,
    tmp_path: Path,
) -> Iterator[VaultStore]:
    """A real on-disk store the drift owner drops superseded points from.

    Nothing here is stubbed. A supersede has to actually remove the superseded
    points and actually leave the replacements behind, and only a real
    collection can tell those two outcomes apart.
    """
    del isolated_singleton_dirs
    from ..config import reset_config
    from ..store_runtime import VaultStore

    reset_config()
    store = VaultStore(tmp_path / "store", embedding_dim=_DENSE_DIM)
    try:
        yield store
    finally:
        store.close()
        reset_config()


def _publish(store: VaultStore, segments: tuple[CodeFileSegment, ...]) -> None:
    """Put a path's chunks in the store the way a confirmed slice would."""
    store.upsert_code_chunks(
        [
            replace(chunk, vector=[0.125] * _DENSE_DIM)
            for segment in segments
            for chunk in segment.chunks
        ],
        write_policy=None,
    )


def _stored(store: VaultStore, rel_path: str) -> set[str]:
    return set(store.get_code_ids_by_paths({rel_path}))


def _identities(segments: tuple[CodeFileSegment, ...]) -> set[str]:
    return {chunk.id for segment in segments for chunk in segment.chunks}


def test_a_path_rewritten_mid_run_is_superseded_not_fatal(
    tmp_path: Path,
    drift_store: VaultStore,
) -> None:
    """The record-time collision is repaired instead of failing the run.

    This is the defect itself: a resumed generation over a tree that keeps
    moving reaches the indexed-path upsert guard and, with nothing owning the
    repair, loses the entire run to one racing file.
    """
    checkpoint = _open(tmp_path)
    indexed_digest = _digest("before the edit")
    original = _segments("src/racing.py")
    _index_path(checkpoint, "src/racing.py", indexed_digest)
    _publish(drift_store, original)
    _interrupt(checkpoint, "interrupted after one path was indexed")

    resumed = _open(tmp_path)
    owner = CodeDriftOwner(resumed, drift_store)

    # The pre-dispatch snapshot observed this path unchanged, so nothing
    # re-opened it. The source is rewritten while the run encodes, and the
    # fresh content reaches storage before the ledger is told about it.
    moved_digest = _digest("after the edit")
    moved = _segments("src/racing.py", marker="_moved")
    _publish(drift_store, moved)

    assert owner.record_segments(moved, {"src/racing.py": moved_digest}) == 2

    assert owner.superseded_paths == ("src/racing.py",)
    assert owner.deferred_paths == ()
    assert owner.remediated is True
    # The generation now claims the replacement units and no longer claims the
    # superseded ones.
    assert all(
        resumed.ledger.unit_committed(
            resumed.generation_id,
            resumed.unit_for(segment, moved_digest),
        )
        for segment in moved
    )
    assert not resumed.ledger.unit_committed(
        resumed.generation_id,
        resumed.unit_for(original[1], indexed_digest),
    )
    # Storage holds the replacement content alone. Dropping every point the
    # path owns - the union of both digests - would have deleted exactly what
    # the re-record just claimed.
    assert _stored(drift_store, "src/racing.py") == _identities(moved)


def test_the_pre_record_check_keeps_visible_drift_off_the_signal_path(
    tmp_path: Path,
    drift_store: VaultStore,
) -> None:
    """Drift the ledger can already see never reaches the collision branch."""
    checkpoint = _open(tmp_path)
    _index_path(checkpoint, "src/known.py", _digest("before the edit"))
    _publish(drift_store, _segments("src/known.py"))
    _interrupt(checkpoint, "interrupted after one path was indexed")

    resumed = _open(tmp_path)
    owner = CodeDriftOwner(resumed, drift_store)
    moved = _segments("src/known.py", marker="_moved")
    _publish(drift_store, moved)

    assert owner.record_segments(moved, {"src/known.py": _digest("after")}) == 2

    assert owner.superseded_paths == ("src/known.py",)
    # The point of the cheap re-check: the ledger never had to refuse a write.
    assert owner.collisions_observed == 0


def test_a_resubmission_under_the_same_digest_stays_fatal(
    tmp_path: Path,
    drift_store: VaultStore,
) -> None:
    """Equal digests are a caller defect, not a moving tree, and must not heal.

    Superseding here would drop published content to cover for a caller that
    submitted content the generation already committed under fresh identities.
    """
    checkpoint = _open(tmp_path)
    digest = _digest("committed content")
    _index_path(checkpoint, "src/settled.py", digest)
    owner = CodeDriftOwner(checkpoint, drift_store)

    resubmitted = _segments("src/settled.py", marker="_again")
    with pytest.raises(RunLedgerIndexedPathCollisionError) as caught:
        owner.record_segments(resubmitted, {"src/settled.py": digest})

    assert caught.value.is_drift is False
    assert owner.superseded_paths == ()
    assert owner.collisions_observed == 1


def test_a_path_that_keeps_moving_is_deferred_and_says_so(
    tmp_path: Path,
    drift_store: VaultStore,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An exhausted path leaves the mutation; its siblings still record."""
    checkpoint = _open(tmp_path)
    hot = "src/hot.py"
    calm = "src/calm.py"
    _index_path(checkpoint, hot, _digest("first content"))
    _interrupt(checkpoint, "interrupted after one path was indexed")

    resumed = _open(tmp_path)
    owner = CodeDriftOwner(resumed, drift_store, retry_budget=1)

    # One supersede is all this path gets, and it spends it here.
    second = _segments(hot, marker="_second")
    assert owner.record_segments(second, {hot: _digest("second content")}) == 2
    assert owner.superseded_paths == (hot,)
    assert owner.deferred_paths == ()

    # It moves again with the budget spent, so it is deferred. The calm path
    # travelling in the same mutation is still recorded.
    third = _segments(hot, marker="_third")
    calm_segments = _segments(calm)
    calm_digest = _digest("calm content")
    caplog.set_level("WARNING")
    inserted = owner.record_segments(
        (*third, *calm_segments),
        {hot: _digest("third content"), calm: calm_digest},
    )

    assert inserted == 2
    assert owner.deferred_paths == (hot,)
    assert all(
        resumed.ledger.unit_committed(
            resumed.generation_id,
            resumed.unit_for(segment, calm_digest),
        )
        for segment in calm_segments
    )
    # Silent deferral is not acceptable: the warning names the path and the
    # budget it exhausted.
    assert any(
        hot in record.getMessage() and "budget of 1" in record.getMessage()
        for record in caplog.records
        if record.levelname == "WARNING"
    )


def test_the_retry_budget_must_be_positive(
    tmp_path: Path,
    drift_store: VaultStore,
) -> None:
    """A zero budget defers every drifted path without ever repairing one."""
    with pytest.raises(ValueError, match="retry_budget must be a positive integer"):
        CodeDriftOwner(_open(tmp_path), drift_store, retry_budget=0)


def test_drift_telemetry_reports_volume_the_breaker_cannot_see(
    tmp_path: Path,
    drift_store: VaultStore,
) -> None:
    """A remediated run succeeds, so this block is the only drift signal.

    The breaker counts faults, and remediated drift is not one, so it never
    increments. That makes the telemetry block the sole place drift volume
    surfaces, and a deferred path has to be nameable rather than merely
    counted, because it is stale index content someone has to find.
    """
    checkpoint = _open(tmp_path)
    _index_path(checkpoint, "src/moving.py", _digest("first content"))
    _interrupt(checkpoint, "interrupted after one path was indexed")

    resumed = _open(tmp_path)
    owner = CodeDriftOwner(resumed, drift_store, retry_budget=1)
    assert owner.snapshot() == {
        "superseded_paths": 0,
        "deferred_paths": [],
        "collisions_observed": 0,
        "retry_budget": 1,
    }

    owner.record_segments(
        _segments("src/moving.py", marker="_second"),
        {"src/moving.py": _digest("second content")},
    )
    owner.record_segments(
        _segments("src/moving.py", marker="_third"),
        {"src/moving.py": _digest("third content")},
    )

    assert owner.snapshot() == {
        "superseded_paths": 1,
        "deferred_paths": ["src/moving.py"],
        "collisions_observed": 0,
        "retry_budget": 1,
    }
