"""Job-manager values, attempt context, and private runtime records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncio

    from ..job_control import RunControlToken
    from ..job_models import (
        IndexResilienceSnapshot,
        JobOutcome,
        ProcessResourceSnapshot,
    )
    from .manager import JobManager


MAX_RECORDS = 256


@dataclass(frozen=True, slots=True)
class JobExecutionResult:
    """Result returned by one synchronous managed execution attempt."""

    summary: str
    preprocess_ok: int = 0
    preprocess_skipped: int = 0
    preprocess_failures: tuple[str, ...] = ()
    reuse: dict[str, object] | None = None
    drift: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class JobShutdownResult:
    """Bounded manager-drain result consumed by service shutdown."""

    resources_released: bool
    persistence_ok: bool
    requested_job_ids: tuple[str, ...]
    surviving_job_ids: tuple[str, ...]
    persistence_code: str

    @property
    def clean(self) -> bool:
        """Return whether shutdown was both resource-safe and durable."""
        return self.resources_released and self.persistence_ok


@dataclass(frozen=True, slots=True)
class ProgressUpdate:
    """One exact-attempt progress publication request."""

    attempt: int
    task: asyncio.Task[Any]
    step: str
    completed: int = 0
    total: int | None = None


@dataclass(frozen=True, slots=True)
class ResourceUpdate:
    """One partial update to exact-attempt resource ownership."""

    started: ProcessResourceSnapshot | object | None = ...
    finished: ProcessResourceSnapshot | object | None = ...
    index_capacity_held: bool | None = None
    project_lease_held: bool | None = None
    writer_lock_held: bool | None = None
    pipeline_active: bool | None = None
    admission_acquired_at: float | None = None
    gpu_lock_wait_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class JobAttemptContext:
    """Exact manager-owned resources passed to a synchronous attempt runner."""

    manager: JobManager
    job_id: str
    attempt: int
    task: asyncio.Task[Any]
    control: RunControlToken

    def update_progress(
        self, step: str, completed: int = 0, total: int | None = None
    ) -> JobOutcome:
        """Publish progress only if this context still owns the attempt."""
        return self.manager.update_progress(
            self.job_id,
            ProgressUpdate(
                attempt=self.attempt,
                task=self.task,
                step=step,
                completed=completed,
                total=total,
            ),
        )

    def set_resources(self, update: ResourceUpdate) -> bool:
        """Update this attempt's resource ownership without stale-task writes."""
        return self.manager.update_execution_resources(
            self.job_id,
            task=self.task,
            update=update,
        )

    def set_resilience(self, resilience: IndexResilienceSnapshot) -> bool:
        """Publish canonical resilience state for this exact attempt."""
        return self.manager.update_resilience(
            self.job_id, task=self.task, resilience=resilience
        )
