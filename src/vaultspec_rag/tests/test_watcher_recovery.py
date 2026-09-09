"""Restart reconciliation for durably fenced watcher generations."""

from __future__ import annotations

import os
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

import pytest

from ..job_models import (
    DesiredJobState,
    JobAttempt,
    JobCapabilities,
    JobInitiator,
    JobMode,
    JobOperation,
    JobResourceSnapshot,
    JobRuntimeSnapshot,
    JobSnapshot,
    JobSource,
    JobSpec,
    JobState,
    JobTimestamps,
)
from ..service import ServiceRegistry
from ..watcher_retry import (
    _ADMISSION_RESERVATIONS,
    WatcherCircuitState,
    WatcherPathEvent,
    WatcherPathObservation,
    WatcherRetryPolicy,
    WatcherScopeRefusal,
    WatcherSource,
    _WatcherRetryOptions,
)
from ..watcher_runtime import WatcherConvergenceSlot, reconcile_restarted_slot

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

pytestmark = pytest.mark.unit


class _History:
    def __init__(self, snapshot: JobSnapshot | None) -> None:
        self.snapshot = snapshot

    def get(self, job_id: str) -> JobSnapshot | None:
        assert job_id == "job-1"
        return self.snapshot


def _options(root: Path) -> _WatcherRetryOptions:
    return _WatcherRetryOptions(
        canonical_root=os.path.normcase(str(root.resolve())),
        source=WatcherSource.CODE,
        base_seconds=1.0,
        max_seconds=2.0,
        jitter_fraction=0.0,
        failure_threshold=3,
        now=1.0,
    )


def _fenced_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> WatcherRetryPolicy:
    state_path = tmp_path / "state" / "code.json"
    policy = WatcherRetryPolicy(state_path, _options(tmp_path))
    policy.mark_scope_pending(
        (
            WatcherPathObservation(
                relative_path="src/a.py",
                source=WatcherSource.CODE,
                first_observed_at=1.0,
                latest_observed_at=1.0,
                event_kinds=frozenset({WatcherPathEvent.MODIFIED}),
                generation=1,
            ),
        ),
        now=1.0,
    )
    decision = policy.admit_reserved(
        policy.reserve_admission(), now=2.0, job_id="job-1"
    )
    assert decision.admitted
    _ADMISSION_RESERVATIONS.clear()
    monkeypatch.setattr(
        "vaultspec_rag.watcher_retry._attempt_owner_is_live", lambda _state: False
    )
    return WatcherRetryPolicy(state_path, _options(tmp_path))


def _snapshot(root: Path, state: JobState) -> JobSnapshot:
    return JobSnapshot(
        id="job-1",
        revision=1,
        spec=JobSpec(
            operation=JobOperation.INDEX,
            source=JobSource.CODE,
            project_root=str(root),
            mode=JobMode.INCREMENTAL,
        ),
        state=state,
        desired_state=DesiredJobState.RUNNING,
        capabilities=JobCapabilities(
            pausable=False,
            resumable=False,
            cancellable=False,
            retryable=False,
            deletable=False,
        ),
        attempt=JobAttempt(number=1),
        timestamps=JobTimestamps(created_at=1.0, state_changed_at=2.0),
        progress=None,
        result=None,
        error_kind=None,
        initiator=JobInitiator(
            kind="watcher",
            command="watcher_code_index",
            project_root=str(root),
        ),
        runtime=JobRuntimeSnapshot(
            pid=1,
            parent_pid=0,
            user="u",
            executable="python",
            prefix="p",
            base_prefix="p",
            virtual_env=None,
        ),
        resources=JobResourceSnapshot(started=None, finished=None),
    )


def _slot(root: Path, policy: WatcherRetryPolicy) -> WatcherConvergenceSlot:
    return WatcherConvergenceSlot(
        JobSource.CODE, root.resolve(), ServiceRegistry(), policy
    )


@pytest.mark.asyncio
async def test_restart_recognizes_already_succeeded_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = _fenced_policy(tmp_path, monkeypatch)
    slot = _slot(tmp_path, policy)

    await reconcile_restarted_slot(
        slot, cast("Any", _History(_snapshot(tmp_path, JobState.SUCCEEDED)))
    )

    assert not policy.state.convergence_pending
    assert policy.state.captured_paths == ()
    assert policy.state.attempt_job_id is None
    assert not slot.has_work()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state", [JobState.CANCELLED, JobState.INTERRUPTED, JobState.FAILED]
)
async def test_restart_restores_exact_scope_after_unsuccessful_terminal_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: JobState
) -> None:
    policy = _fenced_policy(tmp_path, monkeypatch)
    slot = _slot(tmp_path, policy)

    await reconcile_restarted_slot(
        slot, cast("Any", _History(_snapshot(tmp_path, state)))
    )

    assert [item.relative_path for item in policy.state.pending_paths] == ["src/a.py"]
    assert slot.dirty_paths() == frozenset({tmp_path.resolve() / "src/a.py"})
    assert policy.state.attempt_job_id is None


@pytest.mark.asyncio
async def test_restart_reattaches_live_job_and_blocks_duplicate_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = _fenced_policy(tmp_path, monkeypatch)
    slot = _slot(tmp_path, policy)

    await reconcile_restarted_slot(
        slot, cast("Any", _History(_snapshot(tmp_path, JobState.RUNNING)))
    )

    assert slot.job_id == "job-1"
    assert slot.captured_attempt(1) == frozenset({tmp_path.resolve() / "src/a.py"})
    assert policy.reserve_admission() is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "history",
    [
        lambda _root: None,
        lambda root: replace(
            _snapshot(root, JobState.SUCCEEDED),
            spec=replace(
                _snapshot(root, JobState.SUCCEEDED).spec, mode=JobMode.REBUILD
            ),
        ),
        lambda root: replace(
            _snapshot(root, JobState.SUCCEEDED),
            spec=replace(
                _snapshot(root, JobState.SUCCEEDED).spec,
                project_root=str(root / "foreign"),
            ),
        ),
    ],
)
async def test_unsafe_restart_recovery_is_terminal_and_retry_cannot_clear_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    history: Callable[[Path], JobSnapshot | None],
) -> None:
    policy = _fenced_policy(tmp_path, monkeypatch)
    slot = _slot(tmp_path, policy)

    await reconcile_restarted_slot(slot, cast("Any", _History(history(tmp_path))))
    refused = policy.state
    policy.mark_convergence_pending(now=3.0)

    assert refused.scope_refusal is WatcherScopeRefusal.FULL_REINDEX_REQUIRED
    assert refused.circuit_state is WatcherCircuitState.OPEN
    assert refused.pending_paths == ()
    assert policy.state.scope_refusal is WatcherScopeRefusal.FULL_REINDEX_REQUIRED
    assert not policy.admit(now=4.0).admitted
