"""Lifecycle-owned publication revisions and event-driven readiness waits."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from math import isfinite
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Final, cast

from .._root_identity import canonical_root_key
from .._source_types import INDEX_SOURCES, IndexSource, PublicSourceType

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

__all__ = [
    "MAX_READINESS_OBSERVERS",
    "PublicationTarget",
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


async def _wait_until_notified(
    future: asyncio.Future[None],
    *,
    deadline: float,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Return on a notification, or when the monotonic ``deadline`` expires."""
    remaining = deadline - loop.time()
    if remaining <= 0:
        return
    try:
        await asyncio.wait_for(asyncio.shield(future), timeout=remaining)
    except TimeoutError:
        return


def _canonical_root(value: object) -> str:
    if not isinstance(value, (str, Path)) or (
        isinstance(value, str) and not value.strip()
    ):
        raise ValueError("root must be a non-empty path")
    try:
        return canonical_root_key(Path(value).expanduser())
    except (OSError, RuntimeError, ValueError) as error:
        raise ValueError("root must be a valid path") from error


def _concrete_source(value: object) -> IndexSource:
    if not isinstance(value, str) or value not in INDEX_SOURCES:
        raise ValueError("source must be a concrete index source")
    return value


def _identity(value: object, *, field: str) -> None:
    if value is not None and (
        not isinstance(value, str) or not value or len(value) > _MAX_IDENTITY_LENGTH
    ):
        raise ValueError(f"{field} must contain 1 to {_MAX_IDENTITY_LENGTH} characters")


def _revision(value: object, *, field: str) -> None:
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
        if (
            not isinstance(cast("object", self.canonical_root), str)
            or not self.canonical_root
        ):
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
        if not isinstance(cast("object", self.key), ReadinessSourceKey):
            raise ValueError("key must be a ReadinessSourceKey")
        _identity(self.published_generation, field="published_generation")
        _identity(self.desired_generation, field="desired_generation")
        _revision(self.publication_revision, field="publication_revision")
        _revision(self.controller_revision, field="controller_revision")

    def publication_target(self) -> PublicationTarget | None:
        """Capture the controller target, or the publication already served."""
        if self.controller_revision is not None:
            return PublicationTarget(
                self.key, self.controller_revision, self.desired_generation
            )
        if self.publication_revision is not None:
            return PublicationTarget(
                self.key, self.publication_revision, self.published_generation
            )
        return None


@dataclass(frozen=True, slots=True)
class PublicationTarget:
    """Publication condition captured for one concrete source at admission."""

    key: ReadinessSourceKey
    revision: int
    generation: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.key), ReadinessSourceKey):
            raise ValueError("key must be a ReadinessSourceKey")
        _identity(self.generation, field="generation")
        _revision(self.revision, field="revision")
        # ``_revision`` tolerates None because the snapshot fields it also
        # validates are genuinely optional. A target's revision is not: it is
        # the condition the wait is admitted against, and a None reaching here
        # through an untyped path would make every publication satisfy it.
        if cast("object", self.revision) is None:
            raise ValueError("revision must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class _Observer:
    keys: frozenset[ReadinessSourceKey]
    future: asyncio.Future[None]


class ReadinessRevisionRegistry:
    """Own publication evidence and bounded waiters for one service lifetime."""

    def __init__(self) -> None:
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
        """Restore missing publication evidence from its receipt-free authority."""
        from .._publication_state import (
            UNREADABLE_PUBLICATION_ERRORS,
            acquire_publication_snapshot,
        )

        key = ReadinessSourceKey.from_root(root, source)
        with self._lock:
            self._require_live_locked()
            current = self._snapshots.get(key, ReadinessRevisionSnapshot(key=key))
            if current.publication_revision is not None:
                return current
        generation = None
        try:
            publication = acquire_publication_snapshot(
                Path(root).expanduser(), PublicSourceType(source)
            )
            publication.validate()
            generation = publication.proof.generation_id
        except UNREADABLE_PUBLICATION_ERRORS:
            pass
        with self._lock:
            self._require_live_locked()
            current = self._snapshots.get(key, ReadinessRevisionSnapshot(key=key))
            if current.publication_revision is None and generation is not None:
                # This predates every controller notification in this lifetime.
                # Durable proof revisions belong to a different sequence.
                current = replace(
                    current, published_generation=generation, publication_revision=0
                )
                self._snapshots[key] = current
            return current

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
            isinstance(cast("object", timeout_seconds), bool)
            or not isinstance(cast("object", timeout_seconds), (int, float))
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
        deadline = loop.time() + timeout_seconds
        while True:
            observer_id: int | None = None
            future: asyncio.Future[None] | None = None
            with self._lock:
                self._require_owner_locked(loop)
                if self._targets_satisfied_locked(target_tuple):
                    return True
                if loop.time() >= deadline:
                    return False
                if len(self._observers) >= MAX_READINESS_OBSERVERS:
                    raise ReadinessObserverCapacityError(
                        "readiness observer capacity is exhausted"
                    )
                future = loop.create_future()
                observer_id = self._next_observer_id
                self._next_observer_id += 1
                self._observers[observer_id] = _Observer(keys=keys, future=future)
            try:
                await _wait_until_notified(future, deadline=deadline, loop=loop)
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
