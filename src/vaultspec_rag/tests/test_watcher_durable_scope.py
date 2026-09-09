"""Atomic durability tests for exact watcher scope."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from ..watcher_durability import (
    WatcherAttemptOutcome,
    WatcherSettlement,
    admit_scoped_watcher_attempt,
    persist_watcher_observations,
    settle_watcher_attempt,
)
from ..watcher_retry import (
    WatcherPathEvent,
    WatcherPathObservation,
    WatcherRetryPolicy,
    WatcherSource,
    _WatcherRetryOptions,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _policy(path: Path, root: Path) -> WatcherRetryPolicy:
    return WatcherRetryPolicy(
        path,
        _WatcherRetryOptions(
            canonical_root=os.path.normcase(str(root.resolve())),
            source=WatcherSource.CODE,
            base_seconds=1.0,
            max_seconds=2.0,
            jitter_fraction=0.0,
            failure_threshold=3,
            now=0.0,
        ),
    )


def _observation(path: str, generation: int = 1) -> WatcherPathObservation:
    return WatcherPathObservation(
        relative_path=path,
        source=WatcherSource.CODE,
        first_observed_at=1.0,
        latest_observed_at=2.0,
        event_kinds=frozenset({WatcherPathEvent.MODIFIED}),
        generation=generation,
    )


@pytest.mark.asyncio
async def test_observation_and_admission_commit_exact_scope_and_job_fence(
    tmp_path: Path,
) -> None:
    policy = _policy(tmp_path / "state" / "code.json", tmp_path)
    observation = _observation("src/a.py")

    cancelled = await persist_watcher_observations(
        policy,
        (observation,),
        source=WatcherSource.CODE,
        root_dir=tmp_path,
    )
    decision = await admit_scoped_watcher_attempt(
        policy,
        "job-1",
        source=WatcherSource.CODE,
        root_dir=tmp_path,
    )

    assert not cancelled
    assert decision.admitted
    assert policy.state.pending_paths == ()
    assert policy.state.captured_paths == (observation,)
    assert policy.state.attempt_job_id == "job-1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome", [WatcherAttemptOutcome.INTERRUPTED, WatcherAttemptOutcome.FAILED]
)
async def test_non_success_settlement_restores_captured_scope(
    tmp_path: Path,
    outcome: WatcherAttemptOutcome,
) -> None:
    policy = _policy(tmp_path / "state" / "code.json", tmp_path)
    observation = _observation("src/a.py")
    await persist_watcher_observations(
        policy, (observation,), source=WatcherSource.CODE, root_dir=tmp_path
    )
    decision = await admit_scoped_watcher_attempt(
        policy, "job-1", source=WatcherSource.CODE, root_dir=tmp_path
    )
    assert decision.attempt_generation is not None

    settled = await settle_watcher_attempt(
        policy,
        decision.attempt_generation,
        WatcherSettlement(
            outcome,
            RuntimeError("temporary")
            if outcome is WatcherAttemptOutcome.FAILED
            else None,
        ),
        source=WatcherSource.CODE,
        root_dir=tmp_path,
    )

    assert settled.pending_paths == (observation,)
    assert settled.captured_paths == ()
    assert settled.attempt_job_id is None


@pytest.mark.asyncio
async def test_success_consumes_only_captured_generation(tmp_path: Path) -> None:
    policy = _policy(tmp_path / "state" / "code.json", tmp_path)
    first = _observation("src/a.py")
    await persist_watcher_observations(
        policy, (first,), source=WatcherSource.CODE, root_dir=tmp_path
    )
    decision = await admit_scoped_watcher_attempt(
        policy, "job-1", source=WatcherSource.CODE, root_dir=tmp_path
    )
    assert decision.attempt_generation is not None
    later = _observation("src/b.py", generation=2)
    await persist_watcher_observations(
        policy, (later,), source=WatcherSource.CODE, root_dir=tmp_path
    )

    settled = await settle_watcher_attempt(
        policy,
        decision.attempt_generation,
        WatcherSettlement(WatcherAttemptOutcome.SUCCEEDED),
        source=WatcherSource.CODE,
        root_dir=tmp_path,
    )

    assert settled.pending_paths == (later,)
    assert settled.captured_paths == ()
    assert settled.convergence_pending
