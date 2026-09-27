"""Canonical job snapshots for watcher recovery and transition tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..indexer._run_ledger_models import RunAuthority
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

if TYPE_CHECKING:
    from pathlib import Path


def watcher_job_snapshot(
    root: Path,
    state: JobState,
    *,
    created_at: float = 0.0,
    state_changed_at: float = 0.0,
) -> JobSnapshot:
    return JobSnapshot(
        id="job-1",
        revision=1,
        spec=JobSpec(
            operation=JobOperation.INDEX,
            source=JobSource.CODE,
            project_root=str(root),
            mode=JobMode.INCREMENTAL,
            authority=RunAuthority.PUBLICATION,
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
        timestamps=JobTimestamps(
            created_at=created_at,
            state_changed_at=state_changed_at,
        ),
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
