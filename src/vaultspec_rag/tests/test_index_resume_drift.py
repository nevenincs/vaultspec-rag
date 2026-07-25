"""Recording code units for a path the tree rewrote under the running index.

Every test runs the genuine store, the genuine run ledger, and the genuine
indexer against a real temporary root. Nothing on the path under test is
mocked: the collision is raised by the real ledger guard, the remedy deletes
real points, and the assertions read real durable state back. The embedding
model is never constructed because this seam never encodes - it records what
an encode already stored.
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Any, cast

import pytest

from ..config import reset_config
from ..indexer._codebase_indexer import CodebaseIndexer
from ..indexer._content_policy import RootContentPolicy, SourceProfileVersion
from ..indexer._path_drift import CodePathDriftOwner
from ..indexer._resolved_policy import resolve_index_policy
from ..indexer._run_checkpoint import CodeRunCheckpoint, CodeRunConfiguration
from ..indexer._run_ledger import (
    RunLedgerIndexedPathCollisionError,
    RunOperation,
)
from ..indexer._run_policy import RunPolicy
from ..indexer._streaming import CodeFileSegment
from ..store import CodeChunk, VaultStore

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_DENSE_DIM = 1024
_MOVING = "src/moving.py"
_BEFORE = "def before():\n    return 1\n"
_AFTER = "def after():\n    return 2\n"


@pytest.fixture(autouse=True)
def _isolated_env(  # pyright: ignore[reportUnusedFunction]
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None]:
    """Isolate config-backed machine paths and force local mode."""
    monkeypatch.setenv("VAULTSPEC_RAG_STATUS_DIR", str(tmp_path / "status"))
    monkeypatch.setenv(
        "VAULTSPEC_RAG_QDRANT_STORAGE_DIR",
        str(tmp_path / "qs" / "storage"),
    )
    monkeypatch.delenv("VAULTSPEC_RAG_QDRANT_URL", raising=False)
    reset_config()
    yield
    reset_config()


def _digest(value: str) -> str:
    return hashlib.blake2b(value.encode("utf-8")).hexdigest()


def _dense(seed: int) -> list[float]:
    vector = [0.0] * _DENSE_DIM
    vector[seed % _DENSE_DIM] = 1.0
    return vector


def _chunk(rel_path: str, content: str, seed: int) -> CodeChunk:
    chunk = CodeChunk(
        id=f"{rel_path}:1-2@{_digest(content)[:12]}",
        path=rel_path,
        language="python",
        content=content,
        line_start=1,
        line_end=2,
    )
    chunk.vector = _dense(seed)
    return chunk


def _segment(rel_path: str, content: str, seed: int) -> CodeFileSegment:
    return CodeFileSegment(rel_path, 0, (_chunk(rel_path, content, seed),), 128, True)


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


def _checkpoint(root: Path) -> CodeRunCheckpoint:
    policy = resolve_index_policy(
        root,
        content_policy=RootContentPolicy(SourceProfileVersion.CONVENTIONAL_V1),
    )
    return CodeRunCheckpoint.open(
        data_root=root / ".state",
        root_dir=root,
        policy=policy,
        run_policy=RunPolicy(no_progress_timeout_seconds=30.0),
        operation=RunOperation.FULL,
        clean=False,
        model_identity="model-v1",
        dense_dimensions=_DENSE_DIM,
        configuration=_configuration(),
    )


class _Fixture:
    """One real root carrying a store, a generation, and an indexer."""

    def __init__(self, root: Path, *, supersede_budget: int | None = None) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.store = VaultStore(root)
        self.checkpoint = _checkpoint(root)
        self.indexer = CodebaseIndexer(root, cast("Any", None), self.store)
        self.indexer._last_checkpoint = self.checkpoint
        self.drift = (
            CodePathDriftOwner(self.store, self.checkpoint)
            if supersede_budget is None
            else CodePathDriftOwner(
                self.store,
                self.checkpoint,
                supersede_budget=supersede_budget,
            )
        )
        self.indexer._drift = self.drift

    def publish(self, segment: CodeFileSegment) -> None:
        """Store the points an encode would have written for one segment."""
        self.store.upsert_code_chunks(list(segment.chunks), write_policy=None)

    def indexed_digest(self, rel_path: str) -> str | None:
        states = self.checkpoint.ledger.file_states_for_paths(
            self.checkpoint.generation_id,
            (rel_path,),
        )
        state = states.get(rel_path)
        return state.content_hash if state is not None else None

    def close(self) -> None:
        self.store.close()


@pytest.fixture
def indexed_before(tmp_path: Path) -> Generator[_Fixture]:
    """A generation that already indexed the moving path at its old content."""
    fixture = _Fixture(tmp_path / "root")
    old = _segment(_MOVING, _BEFORE, seed=1)
    fixture.publish(old)
    fixture.checkpoint.record_confirmed_segments((old,), {_MOVING: _digest(_BEFORE)})
    yield fixture
    fixture.close()


def test_recording_a_rewritten_path_supersedes_it_instead_of_failing_the_run(
    indexed_before: _Fixture,
) -> None:
    """The reported failure: a resumed run submits new content for an
    indexed path and the whole job dies on the ledger guard.
    """
    fresh = _segment(_MOVING, _AFTER, seed=2)
    indexed_before.publish(fresh)

    indexed_before.indexer._record_confirmed_slice(
        indexed_before.checkpoint,
        (fresh,),
        {_MOVING: _digest(_AFTER)},
    )

    assert indexed_before.indexed_digest(_MOVING) == _digest(_AFTER)
    # The superseded points are gone rather than sitting beside the new ones:
    # chunk identity embeds a content digest, so keeping both duplicates the
    # file instead of replacing it.
    assert set(indexed_before.store.get_code_ids_by_paths({_MOVING})) == {
        fresh.chunks[0].id
    }
    tally = indexed_before.drift.tally()
    assert (tally.supersede_operations, tally.deferred_paths) == (1, 0)


def test_a_collision_raised_by_the_ledger_is_repaired_and_re_recorded(
    indexed_before: _Fixture,
) -> None:
    """The residual window: the path moves after the pre-record check.

    The collision handed to the handler is the genuine one the ledger guard
    raises, obtained by driving the guard directly, so the repair is proved
    against the real signal rather than a constructed stand-in.
    """
    fresh = _segment(_MOVING, _AFTER, seed=2)
    indexed_before.publish(fresh)
    digests = {_MOVING: _digest(_AFTER)}

    with pytest.raises(RunLedgerIndexedPathCollisionError) as raised:
        indexed_before.checkpoint.record_confirmed_segments((fresh,), digests)
    assert raised.value.is_drift

    remaining = indexed_before.indexer._settle_slice_collision(
        indexed_before.drift,
        raised.value,
        (fresh,),
    )

    assert remaining == (fresh,)
    assert indexed_before.checkpoint.record_confirmed_segments(remaining, digests) == 1
    assert indexed_before.indexed_digest(_MOVING) == _digest(_AFTER)
    assert set(indexed_before.store.get_code_ids_by_paths({_MOVING})) == {
        fresh.chunks[0].id
    }


def test_a_path_that_keeps_moving_is_deferred_once_its_budget_is_spent(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fixture = _Fixture(tmp_path / "root", supersede_budget=1)
    try:
        old = _segment(_MOVING, _BEFORE, seed=1)
        fixture.publish(old)
        fixture.checkpoint.record_confirmed_segments(
            (old,), {_MOVING: _digest(_BEFORE)}
        )

        # First rewrite: within budget, so it is superseded and recorded.
        first = _segment(_MOVING, _AFTER, seed=2)
        fixture.publish(first)
        fixture.indexer._record_confirmed_slice(
            fixture.checkpoint, (first,), {_MOVING: _digest(_AFTER)}
        )

        # Second rewrite: the budget is spent, so the run gives the path up
        # rather than spending itself on one file.
        third_content = "def third():\n    return 3\n"
        second = _segment(_MOVING, third_content, seed=3)
        fixture.publish(second)
        with caplog.at_level(logging.WARNING):
            fixture.indexer._record_confirmed_slice(
                fixture.checkpoint, (second,), {_MOVING: _digest(third_content)}
            )

        assert fixture.drift.deferred_paths == frozenset({_MOVING})
        # Deferral leaves the path exactly as its surviving evidence claims:
        # the abandoned points are removed, so the next run sees an ordinary
        # changed file rather than two generations of content at once.
        assert set(fixture.store.get_code_ids_by_paths({_MOVING})) == {
            first.chunks[0].id
        }
        assert fixture.indexed_digest(_MOVING) == _digest(_AFTER)
        warning = "".join(
            record.getMessage()
            for record in caplog.records
            if record.levelno >= logging.WARNING
        )
        assert _MOVING in warning
        assert "budget of 1" in warning
    finally:
        fixture.close()


def test_later_segments_of_a_deferred_path_are_dropped_rather_than_recorded(
    tmp_path: Path,
) -> None:
    fixture = _Fixture(tmp_path / "root", supersede_budget=1)
    try:
        stable = "src/stable.py"
        stable_content = "def stable():\n    return 0\n"
        fixture.drift.defer(_MOVING, ())

        abandoned = _segment(_MOVING, _AFTER, seed=2)
        kept = _segment(stable, stable_content, seed=4)
        fixture.publish(abandoned)
        fixture.publish(kept)

        fixture.indexer._record_confirmed_slice(
            fixture.checkpoint,
            (abandoned, kept),
            {_MOVING: _digest(_AFTER), stable: _digest(stable_content)},
        )

        assert fixture.store.get_code_ids_by_paths({_MOVING}) == []
        assert fixture.indexed_digest(_MOVING) is None
        assert fixture.indexed_digest(stable) == _digest(stable_content)
    finally:
        fixture.close()


def test_resubmitted_identical_content_is_not_treated_as_drift(
    indexed_before: _Fixture,
) -> None:
    """The guard must still fail closed for a caller defect.

    Equal digests mean the caller re-submitted content this generation
    already committed under a different unit identity. That is not a moving
    tree, and repairing it would silently republish the same file forever, so
    the collision has to escape. The assertion names the drift predicate
    rather than the message, because every branch of the guard shares one
    message and a message match would pass whichever fired.
    """
    # Same path, ordinal and source digest as the committed unit, but new
    # point identities, so the unit is not recognised as an exact replay and
    # reaches the guard. Keeping the ordinal at zero matters: it means a
    # repair would succeed, so a guard that stopped rejecting this would show
    # up as no exception at all rather than as a later ledger complaint.
    replayed = CodeFileSegment(
        _MOVING,
        0,
        (_chunk(_MOVING, _BEFORE + "# re-submitted under new identities\n", 5),),
        128,
        True,
    )
    indexed_before.publish(replayed)

    with pytest.raises(RunLedgerIndexedPathCollisionError) as raised:
        indexed_before.indexer._record_confirmed_slice(
            indexed_before.checkpoint,
            (replayed,),
            {_MOVING: _digest(_BEFORE)},
        )

    assert not raised.value.is_drift
    assert raised.value.rel_path == _MOVING
    assert indexed_before.drift.tally().supersede_operations == 0


def test_superseding_preserves_the_identities_the_incoming_content_claims(
    indexed_before: _Fixture,
) -> None:
    """The remedy must not delete the points it is making room for.

    Storage holds the new content before the ledger accepts it, so a remedy
    that dropped everything the store reports for the path would erase the
    incoming units' own points and leave the ledger claiming identities that
    no longer exist.
    """
    fresh = _segment(_MOVING, _AFTER, seed=2)
    indexed_before.publish(fresh)
    protected = frozenset({fresh.chunks[0].id})

    removed = indexed_before.drift.supersede(
        _MOVING,
        _digest(_BEFORE),
        protected_ids=protected,
    )

    assert removed == 1
    assert set(indexed_before.store.get_code_ids_by_paths({_MOVING})) == protected
