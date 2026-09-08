"""Lifecycle-owned publication revisions and event-driven readiness waits."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, replace
from math import isfinite
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Final, Protocol, cast

from .._source_types import INDEX_SOURCES, IndexSource

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

__all__ = [
    "MAX_READINESS_OBSERVERS",
    "PublicationTarget",
    "ReadinessDeadlineScheduler",
    "ReadinessObserverCapacityError",
    "ReadinessRegistryClosedError",
    "ReadinessRegistryNotStartedError",
    "ReadinessRevisionRegistry",
    "ReadinessRevisionSnapshot",
    "ReadinessSourceKey",
]

MAX_READINESS_OBSERVERS: Final = 1_024
_MAX_IDENTITY_LENGTH: Final = 256


class ReadinessRegistryNotStartedError(RuntimeError):
    """Raised when a registry operation has no owning event loop."""


class ReadinessRegistryClosedError(RuntimeError):
    """Raised when an operation reaches a closed registry."""


class ReadinessObserverCapacityError(RuntimeError):
    """Raised when the bounded observer set is full."""


class ReadinessDeadlineScheduler(Protocol):
    """One clock and wait authority for a monotonic readiness deadline."""

    def now(self, loop: asyncio.AbstractEventLoop) -> float:
        """Return the current monotonic time for ``loop``."""
        ...

    async def wait(
        self,
        future: asyncio.Future[None],
        *,
        deadline: float,
        loop: asyncio.AbstractEventLoop,
    ) -> bool:
        """Return true for a notification or false when ``deadline`` expires."""
        ...


class _AsyncioDeadlineScheduler:
    def now(self, loop: asyncio.AbstractEventLoop) -> float:
        return loop.time()

    async def wait(
        self,
        future: asyncio.Future[None],
        *,
        deadline: float,
        loop: asyncio.AbstractEventLoop,
    ) -> bool:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return False
        try:
            await asyncio.wait_for(asyncio.shield(future), timeout=remaining)
        except TimeoutError:
            return False
        return True


def _canonical_root(value: str | Path) -> str:
    if not isinstance(value, (str, Path)) or (
        isinstance(value, str) and not value.strip()
    ):
        raise ValueError("root must be a non-empty path")
    try:
        resolved = Path(value).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as error:
        raise ValueError("root must be a valid path") from error
    return os.path.normcase(str(resolved))


def _concrete_source(value: object) -> IndexSource:
    if not isinstance(value, str) or value not in INDEX_SOURCES:
        raise ValueError("source must be a concrete index source")
    return cast("IndexSource", value)


def _identity(value: str | None, *, field: str) -> None:
    if value is not None and (
        not isinstance(value, str) or not value or len(value) > _MAX_IDENTITY_LENGTH
    ):
        raise ValueError(f"{field} must contain 1 to {_MAX_IDENTITY_LENGTH} characters")


def _revision(value: int | None, *, field: str) -> None:
    if value is not None and (
        not isinstance(value, int) or isinstance(value, bool) or value < 0
    ):
        raise ValueError(f"{field} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class ReadinessSourceKey:
    """Exact canonical project-root and concrete-source identity."""

    canonical_root: str
    source: IndexSource

    def __post_init__(self) -> None:
        if not isinstance(self.canonical_root, str) or not self.canonical_root:
            raise ValueError("canonical_root must be a non-empty string")
        if _canonical_root(self.canonical_root) != self.canonical_root:
            raise ValueError("canonical_root must be an absolute normalized path")
        object.__setattr__(self, "source", _concrete_source(self.source))

    @classmethod
    def from_root(cls, root: str | Path, source: IndexSource) -> ReadinessSourceKey:
        """Build the exact registry key from a caller-facing root."""
        return cls(canonical_root=_canonical_root(root), source=source)


@dataclass(frozen=True, slots=True)
class ReadinessRevisionSnapshot:
    """Immutable publication and controller evidence for one source."""

    key: ReadinessSourceKey
    published_generation: str | None = None
    publication_revision: int | None = None
    desired_generation: str | None = None
    controller_revision: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.key, ReadinessSourceKey):
            raise ValueError("key must be a ReadinessSourceKey")
        _identity(self.published_generation, field="published_generation")
        _identity(self.desired_generation, field="desired_generation")
        _revision(self.publication_revision, field="publication_revision")
        _revision(self.controller_revision, field="controller_revision")


@dataclass(frozen=True, slots=True)
class PublicationTarget:
    """Publication condition captured for one concrete source at admission."""

    key: ReadinessSourceKey
    revision: int
    generation: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.key, ReadinessSourceKey):
            raise ValueError("key must be a ReadinessSourceKey")
        _identity(self.generation, field="generation")
        _revision(self.revision, field="revision")
        if self.revision is None:
            raise ValueError("revision must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class _Observer:
    keys: frozenset[ReadinessSourceKey]
    future: asyncio.Future[None]


class ReadinessRevisionRegistry:
    """Own publication evidence and bounded waiters for one service lifetime."""

    def __init__(
        self,
        *,
        max_observers: int = MAX_READINESS_OBSERVERS,
        deadline_scheduler: ReadinessDeadlineScheduler | None = None,
    ) -> None:
        if (
            not isinstance(max_observers, int)
            or isinstance(max_observers, bool)
            or max_observers <= 0
        ):
            raise ValueError("max_observers must be a positive integer")
        self._max_observers = max_observers
        self._deadline_scheduler = deadline_scheduler or _AsyncioDeadlineScheduler()
        self._lock = RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closed = False
        self._snapshots: dict[ReadinessSourceKey, ReadinessRevisionSnapshot] = {}
        self._observers: dict[int, _Observer] = {}
        self._next_observer_id = 0

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Bind the registry to its service event loop exactly once."""
        owner = asyncio.get_running_loop() if loop is None else loop
        with self._lock:
            if self._closed:
                raise ReadinessRegistryClosedError("readiness registry is closed")
            if self._loop is not None and self._loop is not owner:
                raise RuntimeError(
                    "readiness registry already has a different owner loop"
                )
            self._loop = owner

    def close(self) -> None:
        """Close the lifetime and cancel every registered waiter."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            loop = self._loop
            futures = tuple(observer.future for observer in self._observers.values())
            self._observers.clear()
        if loop is None:
            return
        for future in futures:
            _schedule_on_owner(loop, _cancel_future, future)

    def snapshot(
        self, root: str | Path, source: IndexSource
    ) -> ReadinessRevisionSnapshot:
        """Return current immutable evidence without performing external work."""
        key = ReadinessSourceKey.from_root(root, source)
        with self._lock:
            self._require_live_locked()
            return self._snapshots.get(key, ReadinessRevisionSnapshot(key=key))

    def publish_next(
        self,
        root: str | Path,
        source: IndexSource,
        *,
        generation: str | None = None,
    ) -> ReadinessRevisionSnapshot:
        """Allocate and publish the next monotonic revision for one source."""
        _identity(generation, field="generation")
        key = ReadinessSourceKey.from_root(root, source)
        with self._lock:
            loop = self._require_live_locked()
            current = self._snapshots.get(key, ReadinessRevisionSnapshot(key=key))
            revision = (
                max(
                    current.publication_revision or 0,
                    current.controller_revision or 0,
                )
                + 1
            )
            updated = replace(
                current,
                published_generation=generation,
                publication_revision=revision,
            )
            self._snapshots[key] = updated
            futures = self._observer_futures_locked(key)
        self._wake_observers(loop, futures)
        return updated

    def notify_controller(
        self,
        root: str | Path,
        source: IndexSource,
        *,
        generation: str | None = None,
    ) -> ReadinessRevisionSnapshot:
        """Allocate a target revision and wake without claiming publication."""
        _identity(generation, field="generation")
        key = ReadinessSourceKey.from_root(root, source)
        with self._lock:
            loop = self._require_live_locked()
            current = self._snapshots.get(key, ReadinessRevisionSnapshot(key=key))
            revision = (
                max(
                    current.publication_revision or 0,
                    current.controller_revision or 0,
                )
                + 1
            )
            updated = replace(
                current,
                desired_generation=generation,
                controller_revision=revision,
            )
            self._snapshots[key] = updated
            futures = self._observer_futures_locked(key)
        self._wake_observers(loop, futures)
        return updated

    async def published_at_least(
        self,
        targets: Iterable[PublicationTarget],
        *,
        timeout_seconds: float,
    ) -> bool:
        """Wait until every target is published, returning false at the deadline."""
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not isfinite(timeout_seconds)
            or timeout_seconds < 0
        ):
            raise ValueError("timeout_seconds must be a finite non-negative number")
        target_tuple = tuple(targets)
        if not target_tuple:
            raise ValueError("targets must contain at least one publication target")
        keys = frozenset(target.key for target in target_tuple)
        if len(keys) != len(target_tuple):
            raise ValueError("targets must contain each source key at most once")

        loop = asyncio.get_running_loop()
        deadline = self._deadline_scheduler.now(loop) + timeout_seconds
        while True:
            observer_id: int | None = None
            future: asyncio.Future[None] | None = None
            with self._lock:
                self._require_owner_locked(loop)
                if self._targets_satisfied_locked(target_tuple):
                    return True
                if self._deadline_scheduler.now(loop) >= deadline:
                    return False
                if len(self._observers) >= self._max_observers:
                    raise ReadinessObserverCapacityError(
                        "readiness observer capacity is exhausted"
                    )
                future = loop.create_future()
                observer_id = self._next_observer_id
                self._next_observer_id += 1
                self._observers[observer_id] = _Observer(keys=keys, future=future)
            try:
                await self._deadline_scheduler.wait(
                    future,
                    deadline=deadline,
                    loop=loop,
                )
            finally:
                with self._lock:
                    self._observers.pop(observer_id, None)

    def _observer_futures_locked(
        self, key: ReadinessSourceKey
    ) -> tuple[asyncio.Future[None], ...]:
        return tuple(
            observer.future
            for observer in self._observers.values()
            if key in observer.keys
        )

    @staticmethod
    def _wake_observers(
        loop: asyncio.AbstractEventLoop,
        futures: tuple[asyncio.Future[None], ...],
    ) -> None:
        for future in futures:
            _schedule_on_owner(loop, _resolve_future, future)

    def _require_live_locked(self) -> asyncio.AbstractEventLoop:
        if self._closed:
            raise ReadinessRegistryClosedError("readiness registry is closed")
        if self._loop is None:
            raise ReadinessRegistryNotStartedError("readiness registry is not started")
        return self._loop

    def _require_owner_locked(
        self, loop: asyncio.AbstractEventLoop
    ) -> asyncio.AbstractEventLoop:
        owner = self._require_live_locked()
        if loop is not owner:
            raise RuntimeError("readiness waits must run on the owner loop")
        return owner

    def _targets_satisfied_locked(self, targets: tuple[PublicationTarget, ...]) -> bool:
        for target in targets:
            snapshot = self._snapshots.get(target.key)
            if snapshot is None:
                return False
            if snapshot.publication_revision is None:
                return False
            if snapshot.publication_revision < target.revision:
                return False
            if (
                target.generation is not None
                and snapshot.published_generation != target.generation
            ):
                return False
        return True


def _resolve_future(future: asyncio.Future[None]) -> None:
    if not future.done():
        future.set_result(None)


def _cancel_future(future: asyncio.Future[None]) -> None:
    if not future.done():
        future.cancel()


def _schedule_on_owner(
    loop: asyncio.AbstractEventLoop,
    callback: Callable[[asyncio.Future[None]], None],
    future: asyncio.Future[None],
) -> None:
    try:
        loop.call_soon_threadsafe(callback, future)
    except RuntimeError:
        if not loop.is_closed():
            raise
