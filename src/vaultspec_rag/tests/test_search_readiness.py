"""Deterministic unit proofs for publication-readiness convergence."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest

from ..indexer._content_policy import RootContentPolicy, SourceProfileVersion
from ..indexer._document_indexer import DocumentIndexer
from ..indexer._generation_lifecycle import (
    CodeGenerationBindings,
    CodeGenerationLifecycle,
    CodeGenerationOpenRequest,
)
from ..indexer._resolved_policy import (
    IndexPolicyResolutionOptions,
    resolve_index_policy,
)
from ..indexer._run_checkpoint import CodeRunConfiguration
from ..indexer._run_ledger_models import RunOperation
from ..job_control import NO_RUN_CONTROL
from ..job_manager.manager import JobManager
from ..job_models import (
    DesiredJobState,
    JobInitiator,
    JobMode,
    JobOperation,
    JobSource,
    JobSpec,
)
from ..progress import NullProgressReporter
from ..server._search_readiness import (
    PublicationTarget,
    ReadinessRegistryClosedError,
    ReadinessRevisionRegistry,
    ReadinessSourceKey,
)
from ..service import ServiceRegistry
from ..service_quiesce import ServiceQuiesceController
from ..store_runtime import VaultStore

if TYPE_CHECKING:
    from pathlib import Path

    from .._source_types import IndexSource
    from ..indexer._document_checkpoint import DocumentRunCheckpoint

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


@dataclass(slots=True)
class VirtualReadinessDeadlineScheduler:
    """One manually advanced clock and wake authority for readiness tests."""

    current: float = 0.0
    wait_calls: int = 0
    deadlines: list[float] = field(default_factory=list)
    _clock_waiters: list[asyncio.Future[None]] = field(default_factory=list)

    def now(self, loop: asyncio.AbstractEventLoop) -> float:
        del loop
        return self.current

    async def wait(
        self,
        future: asyncio.Future[None],
        *,
        deadline: float,
        loop: asyncio.AbstractEventLoop,
    ) -> bool:
        self.wait_calls += 1
        self.deadlines.append(deadline)
        clock_wake = loop.create_future()
        self._clock_waiters.append(clock_wake)
        try:
            done, _ = await asyncio.wait(
                (future, clock_wake),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if future in done:
                await future
                return True
            return self.current < deadline
        finally:
            self._clock_waiters.remove(clock_wake)
            if not clock_wake.done():
                clock_wake.cancel()

    def wake(self) -> None:
        """Deliver a clock/spurious wake without advancing time."""
        for waiter in tuple(self._clock_waiters):
            if not waiter.done():
                waiter.set_result(None)

    def advance(self, seconds: float) -> None:
        """Advance virtual monotonic time and wake every deadline observer."""
        self.current += seconds
        self.wake()


def _registry(
    scheduler: VirtualReadinessDeadlineScheduler,
) -> ReadinessRevisionRegistry:
    registry = ReadinessRevisionRegistry(deadline_scheduler=scheduler)
    registry.start()
    return registry


def _target(
    root: Path, source: IndexSource, revision: int, generation: str | None = None
) -> PublicationTarget:
    return PublicationTarget(
        key=ReadinessSourceKey.from_root(root, source),
        revision=revision,
        generation=generation,
    )


def test_publication_target_rejects_an_absent_revision(tmp_path: Path) -> None:
    """A target with no revision would be satisfied by any publication.

    Deleting the explicit ``is None`` branch in ``PublicationTarget`` admitted
    the value and failed here with DID NOT RAISE; restoring it passed. The
    shared ``_revision`` helper cannot carry this check because the snapshot
    fields it also validates are legitimately optional.
    """
    with pytest.raises(ValueError, match="revision must be a non-negative integer"):
        PublicationTarget(
            key=ReadinessSourceKey.from_root(tmp_path, "code"),
            revision=cast("int", None),
        )


async def _wait_until_registered(
    registry: ReadinessRevisionRegistry,
    *,
    count: int = 1,
) -> None:
    for _ in range(10):
        if len(registry._observers) == count:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"expected {count} registered readiness observer(s)")


async def _wait_until_calls(
    scheduler: VirtualReadinessDeadlineScheduler,
    expected: int,
) -> None:
    for _ in range(10):
        if scheduler.wait_calls == expected:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"expected {expected} virtual scheduler wait call(s)")


async def test_zero_timeout_bypasses_observer_registration(tmp_path: Path) -> None:
    scheduler = VirtualReadinessDeadlineScheduler()
    registry = _registry(scheduler)

    satisfied = await registry.published_at_least(
        (_target(tmp_path, "code", 1),),
        timeout_seconds=0,
    )

    assert not satisfied
    assert scheduler.wait_calls == 0
    assert registry._observers == {}


async def test_already_satisfied_target_returns_without_waiting(tmp_path: Path) -> None:
    scheduler = VirtualReadinessDeadlineScheduler()
    registry = _registry(scheduler)
    published = registry.publish_next(tmp_path, "code", generation="code-1")

    satisfied = await registry.published_at_least(
        (_target(tmp_path, "code", published.publication_revision or 0, "code-1"),),
        timeout_seconds=5,
    )

    assert satisfied
    assert scheduler.wait_calls == 0


async def test_controller_notification_before_registration_does_not_satisfy(
    tmp_path: Path,
) -> None:
    scheduler = VirtualReadinessDeadlineScheduler()
    registry = _registry(scheduler)
    controller = registry.notify_controller(tmp_path, "code", generation="wanted")
    target = _target(tmp_path, "code", controller.controller_revision or 0, "wanted")

    waiting = asyncio.create_task(
        registry.published_at_least((target,), timeout_seconds=5)
    )
    await _wait_until_registered(registry)
    assert not waiting.done()

    registry.publish_next(tmp_path, "code", generation="wanted")
    assert await waiting


async def test_notification_after_registration_rechecks_and_satisfies(
    tmp_path: Path,
) -> None:
    scheduler = VirtualReadinessDeadlineScheduler()
    registry = _registry(scheduler)
    waiting = asyncio.create_task(
        registry.published_at_least(
            (_target(tmp_path, "document", 1, "docs-1"),),
            timeout_seconds=5,
        )
    )
    await _wait_until_registered(registry)

    registry.publish_next(tmp_path, "document", generation="docs-1")

    assert await waiting
    assert registry._observers == {}


async def test_spurious_and_controller_wakes_only_recheck(tmp_path: Path) -> None:
    scheduler = VirtualReadinessDeadlineScheduler()
    registry = _registry(scheduler)
    waiting = asyncio.create_task(
        registry.published_at_least(
            (_target(tmp_path, "code", 2, "served"),), timeout_seconds=5
        )
    )
    await _wait_until_registered(registry)

    scheduler.wake()
    await _wait_until_calls(scheduler, 2)
    await _wait_until_registered(registry)
    assert not waiting.done()
    registry.notify_controller(tmp_path, "code", generation="served")
    await _wait_until_calls(scheduler, 3)
    await _wait_until_registered(registry)
    assert not waiting.done()

    registry.publish_next(tmp_path, "code", generation="served")
    assert await waiting


async def test_virtual_deadline_expires_exactly_at_bound(tmp_path: Path) -> None:
    scheduler = VirtualReadinessDeadlineScheduler(current=10)
    registry = _registry(scheduler)
    waiting = asyncio.create_task(
        registry.published_at_least((_target(tmp_path, "code", 1),), timeout_seconds=3)
    )
    await _wait_until_registered(registry)
    assert scheduler.deadlines == [13]

    scheduler.advance(2.999)
    await asyncio.sleep(0)
    await _wait_until_registered(registry)
    assert not waiting.done()
    scheduler.advance(0.001)

    assert not await waiting
    assert registry._observers == {}


async def test_publication_committed_at_deadline_wins_over_timeout(
    tmp_path: Path,
) -> None:
    scheduler = VirtualReadinessDeadlineScheduler()
    registry = _registry(scheduler)
    waiting = asyncio.create_task(
        registry.published_at_least(
            (_target(tmp_path, "code", 1, "boundary"),), timeout_seconds=4
        )
    )
    await _wait_until_registered(registry)

    scheduler.advance(4)
    registry.publish_next(tmp_path, "code", generation="boundary")

    assert await waiting


async def test_task_cancellation_promptly_unregisters_observer(tmp_path: Path) -> None:
    # Removing the shared finally-pop (also used by timeout) leaves observer 0
    # behind and makes the final empty-registry assertion fail.
    scheduler = VirtualReadinessDeadlineScheduler()
    registry = _registry(scheduler)
    waiting = asyncio.create_task(
        registry.published_at_least((_target(tmp_path, "code", 1),), timeout_seconds=5)
    )
    await _wait_until_registered(registry)

    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting

    assert registry._observers == {}


async def test_close_cleans_waiters_and_rejects_new_waits(tmp_path: Path) -> None:
    scheduler = VirtualReadinessDeadlineScheduler()
    registry = _registry(scheduler)
    target = _target(tmp_path, "code", 1)
    waiting = asyncio.create_task(
        registry.published_at_least((target,), timeout_seconds=5)
    )
    await _wait_until_registered(registry)

    registry.close()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert registry._observers == {}
    with pytest.raises(
        ReadinessRegistryClosedError, match="readiness registry is closed"
    ):
        await registry.published_at_least((target,), timeout_seconds=5)


async def test_two_source_target_waits_for_both_publications(tmp_path: Path) -> None:
    scheduler = VirtualReadinessDeadlineScheduler()
    registry = _registry(scheduler)
    waiting = asyncio.create_task(
        registry.published_at_least(
            (
                _target(tmp_path, "code", 1, "code-1"),
                _target(tmp_path, "document", 1, "docs-1"),
            ),
            timeout_seconds=5,
        )
    )
    await _wait_until_registered(registry)

    registry.publish_next(tmp_path, "code", generation="code-1")
    await asyncio.sleep(0)
    await _wait_until_registered(registry)
    assert not waiting.done()
    registry.publish_next(tmp_path, "document", generation="docs-1")

    assert await waiting


async def test_unrelated_root_and_source_never_satisfy_target(tmp_path: Path) -> None:
    scheduler = VirtualReadinessDeadlineScheduler()
    registry = _registry(scheduler)
    waiting = asyncio.create_task(
        registry.published_at_least(
            (_target(tmp_path / "wanted", "code", 1),), timeout_seconds=2
        )
    )
    await _wait_until_registered(registry)

    registry.publish_next(tmp_path / "other", "code", generation="other-root")
    registry.publish_next(tmp_path / "wanted", "document", generation="other-source")
    await asyncio.sleep(0)
    assert not waiting.done()
    scheduler.advance(2)

    assert not await waiting


async def test_revision_is_monotonic_and_equal_revision_checks_generation(
    tmp_path: Path,
) -> None:
    scheduler = VirtualReadinessDeadlineScheduler()
    registry = _registry(scheduler)
    first = registry.publish_next(tmp_path, "code", generation="first")
    controller = registry.notify_controller(tmp_path, "code", generation="wanted")
    second = registry.publish_next(tmp_path, "code", generation="second")
    assert first.publication_revision == 1
    assert controller.controller_revision == 2
    assert second.publication_revision == 3

    conflict = await registry.published_at_least(
        (_target(tmp_path, "code", 3, "not-second"),), timeout_seconds=0
    )
    older_conflict = await registry.published_at_least(
        (_target(tmp_path, "code", 2, "not-second"),), timeout_seconds=0
    )
    matching = registry.publish_next(tmp_path, "code", generation="not-second")
    older_matching = await registry.published_at_least(
        (_target(tmp_path, "code", 2, "not-second"),), timeout_seconds=0
    )

    assert not conflict
    assert not older_conflict
    assert matching.publication_revision == 4
    assert older_matching


async def test_terminal_job_transition_cannot_satisfy_publication(
    tmp_path: Path,
) -> None:
    # Allowing terminal callbacks and routing the service callback through
    # publish_next makes the exact unsatisfied-publication assertion fail.
    scheduler = VirtualReadinessDeadlineScheduler()
    registry = _registry(scheduler)
    target = _target(tmp_path, "code", 1)
    manager = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        max_nonterminal=1,
        state_path=tmp_path / "jobs.json",
        on_controller_target=lambda snapshot: ServiceRegistry._notify_controller_target(
            registry,
            snapshot,
        ),
    )
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            str(tmp_path),
            JobMode.INCREMENTAL,
        ),
        JobInitiator("test", "terminal-does-not-publish", str(tmp_path)),
    )
    assert created.job is not None

    cancelled = manager.set_desired_state(
        created.job.id,
        DesiredJobState.CANCELLED,
    )

    assert cancelled.job is not None
    assert cancelled.job.state.is_terminal
    assert not await registry.published_at_least((target,), timeout_seconds=0)
    snapshot = registry.snapshot(tmp_path, "code")
    assert snapshot.controller_revision is None
    assert snapshot.publication_revision is None
    assert snapshot.published_generation is None


@dataclass(slots=True)
class _PublishedGeneration:
    generation_id: str


@dataclass(slots=True)
class _DocumentCheckpointCollaborator:
    generation_id: str
    events: list[str]
    publish_calls: int = 0

    def publish_generation(self) -> _PublishedGeneration:
        self.publish_calls += 1
        self.events.append("durable-publish")
        return _PublishedGeneration(self.generation_id)


async def test_document_publish_boundary_notifies_exactly_once(tmp_path: Path) -> None:
    events: list[str] = []
    notifications: list[tuple[Path, str]] = []
    indexer = DocumentIndexer.__new__(DocumentIndexer)
    indexer.root_dir = tmp_path

    def notify(root: Path, generation: str) -> None:
        events.append("readiness-notify")
        notifications.append((root, generation))

    indexer._publish_readiness = notify
    checkpoint = _DocumentCheckpointCollaborator("documents-published", events)

    indexer._publish_generation(cast("DocumentRunCheckpoint", checkpoint))

    assert checkpoint.publish_calls == 1
    assert events == ["durable-publish", "readiness-notify"]
    assert notifications == [(tmp_path, "documents-published")]


@dataclass(slots=True)
class _FailingDocumentCheckpointCollaborator:
    publish_calls: int = 0

    def publish_generation(self) -> _PublishedGeneration:
        self.publish_calls += 1
        raise OSError("durable checkpoint publication failed")


async def test_document_publish_failure_propagates_without_notification(
    tmp_path: Path,
) -> None:
    notifications: list[tuple[Path, str]] = []
    indexer = DocumentIndexer.__new__(DocumentIndexer)
    indexer.root_dir = tmp_path

    def notify(root: Path, generation: str) -> None:
        notifications.append((root, generation))

    indexer._publish_readiness = notify
    checkpoint = _FailingDocumentCheckpointCollaborator()

    with pytest.raises(OSError, match="durable checkpoint publication failed"):
        indexer._publish_generation(cast("DocumentRunCheckpoint", checkpoint))

    assert checkpoint.publish_calls == 1
    assert notifications == []


def _code_open_request(tmp_path: Path) -> CodeGenerationOpenRequest:
    policy = resolve_index_policy(
        tmp_path,
        IndexPolicyResolutionOptions(
            content_policy=RootContentPolicy(SourceProfileVersion.CONVENTIONAL_V1)
        ),
    )
    return CodeGenerationOpenRequest(
        policy=policy,
        operation=RunOperation.FULL,
        clean=False,
        configuration=CodeRunConfiguration(
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
        ),
        dense_dimensions=8,
        sparse_enabled=False,
        run_control=NO_RUN_CONTROL,
    )


async def test_code_ordinary_and_resumed_publication_notify_once_after_durable(
    tmp_path: Path,
    isolated_singleton_dirs: Path,
) -> None:
    del isolated_singleton_dirs
    events: list[tuple[str, Path, str]] = []
    readiness = _registry(VirtualReadinessDeadlineScheduler())
    store = VaultStore(tmp_path / "store", embedding_dim=8)
    meta_path = tmp_path / "code_meta.json"
    checkpoint = None

    def notify(root: Path, generation: str) -> None:
        assert checkpoint is not None
        assert checkpoint.generation.complete
        readiness.publish_next(root, "code", generation=generation)
        events.append(("notify", root, generation))

    lifecycle = CodeGenerationLifecycle(
        CodeGenerationBindings(
            root_dir=tmp_path,
            data_root=tmp_path / ".state",
            meta_path=meta_path,
            store=store,
            load_meta=dict,
            read_meta_raw=dict,
            publish_readiness=notify,
        )
    )
    reporter = NullProgressReporter()
    try:
        checkpoint = lifecycle.open_checkpoint(_code_open_request(tmp_path))
        lifecycle.publish(
            checkpoint,
            build_target=None,
            reporter=reporter,
            phase_label="ordinary publication",
        )
        ordinary_generation = checkpoint.generation_id

        checkpoint = lifecycle.open_checkpoint(_code_open_request(tmp_path))
        checkpoint.publish_metadata(meta_path, published_points=0, published_files=0)
        assert lifecycle.publish_pending_finalization(checkpoint, reporter=reporter)
        resumed_generation = checkpoint.generation_id
    finally:
        store.close()

    assert events == [
        ("notify", tmp_path, ordinary_generation),
        ("notify", tmp_path, resumed_generation),
    ]
    exact = readiness.snapshot(tmp_path, "code")
    assert exact.publication_revision == 2
    assert exact.published_generation == resumed_generation
    assert readiness.snapshot(tmp_path, "document").publication_revision is None
    assert readiness.snapshot(tmp_path / "other", "code").publication_revision is None
