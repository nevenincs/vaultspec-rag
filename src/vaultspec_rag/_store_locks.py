"""Process-level locking primitives for the local-file Qdrant store.

Split out of ``store_runtime.py`` to keep the store runtime focused on collection and
point operations. These helpers are stdlib-only (no qdrant, torch, or other
heavy imports) so they stay cheap to import from anywhere that needs the lock
or its error type.
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import ExitStack, contextmanager, suppress
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Generator, Mapping
    from types import TracebackType

# Storage paths this process currently holds an exclusive handle on, keyed by
# normalised path and counted so nested holders are tracked exactly. The OS
# primitive is per open handle rather than per process, so a second handle
# taken inside one process is refused exactly as a foreign holder's is - and a
# refusal that blames "another process" then sends the reader hunting for a
# process that does not exist. This is the one fact the refusing process can
# establish about itself, so it is recorded where the lock is taken.
_process_held_paths: dict[str, int] = {}
_process_held_paths_lock = threading.Lock()


class ReentrantLock(Protocol):
    """Minimal lock contract shared by local collection guards."""

    def __enter__(self, blocking: bool = True, timeout: float = -1.0) -> bool: ...

    def __exit__(
        self,
        t: type[BaseException] | None,
        v: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    def acquire(self, blocking: bool = True, timeout: float = -1.0) -> bool: ...

    def release(self) -> None: ...


@contextmanager
def acquire_collection_locks(
    locks: Mapping[str, ReentrantLock],
) -> Generator[None]:
    """Acquire collection guards in deterministic name order."""
    with ExitStack() as stack:
        for name in sorted(locks):
            stack.enter_context(locks[name])
        yield


@contextmanager
def acquire_collection_locks_bounded(
    locks: Mapping[str, ReentrantLock],
    *,
    deadline_seconds: float,
) -> Generator[bool]:
    """Acquire collection guards in name order under a finite deadline.

    Acquires in the same deterministic name order as
    :func:`acquire_collection_locks`, but bounds each wait by the time
    remaining until ``deadline_seconds`` from entry. A lock that cannot be
    acquired before the deadline is abandoned - never reordered, never
    force-broken - and acquisition proceeds to the next. Yields whether every
    lock was held.

    Only a shutdown or rollback teardown should use this: abandoning a lock
    means tearing the store down while a holder still owns it, which aborts
    that holder's in-flight write. That is intended when the caller is
    discarding state and completing a bounded shutdown, and unsafe on a
    healthy store - which is why the ordinary lock acquisition stays unbounded.
    """
    deadline = time.monotonic() + deadline_seconds
    acquired: list[ReentrantLock] = []
    all_held = True
    try:
        for name in sorted(locks):
            remaining = deadline - time.monotonic()
            if remaining <= 0.0 or not locks[name].acquire(timeout=remaining):
                all_held = False
                continue
            acquired.append(locks[name])
        yield all_held
    finally:
        for lock in reversed(acquired):
            lock.release()


class VaultStoreLockedError(RuntimeError):
    """Raised when a local Qdrant storage folder could not be locked exclusively.

    Attributes:
        db_path: Absolute path to the Qdrant storage folder that stayed locked.
        held_in_process: Whether a store *this* process opened is the holder.
            The two cases have opposite remedies - stop opening a second store
            here, versus wait for a holder this process cannot see - and only
            this one is verifiable, so the other names no holder at all rather
            than asserting one.
    """

    def __init__(self, db_path: str, *, held_in_process: bool = False) -> None:
        self.db_path = db_path
        self.held_in_process = held_in_process
        if held_in_process:
            detail = (
                "is already open in this process. Local-file storage is locked "
                "per open handle, so a second store on the same root is refused "
                "exactly as a foreign holder would be; reuse the store this "
                "process already has open rather than opening another."
            )
        else:
            detail = (
                "could not be locked, and no store opened by this process holds "
                "it, so the holder is unidentified. Local-file-backed RAG "
                "storage is not parallel-safe across vaultspec-rag processes; "
                "route concurrent searches through one resident service, or "
                "retry after the holder releases it."
            )
        super().__init__(f"Qdrant storage at {db_path} {detail}")


class FileLock:
    """Cross-platform non-blocking file lock.

    Records every path it holds in a process-wide table, so a refused
    acquisition can report whether this process is its own holder. Nothing
    about the lock's exclusivity depends on that table: it is diagnostic only,
    and the OS primitive remains the sole arbiter.
    """

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        self.fd = None
        self.last_error: OSError | None = None
        self.last_error_stage: str | None = None
        self._registered = False

    @property
    def _key(self) -> str:
        """Return the process-table key for this lock's path."""
        return os.path.normcase(os.path.abspath(os.fspath(self.path)))

    def held_elsewhere_in_this_process(self) -> bool:
        """Return whether a *different* live lock in this process holds this path.

        Excludes this instance's own registration, so a caller that already
        holds the lock does not read itself back as the contending holder.
        """
        with _process_held_paths_lock:
            held = _process_held_paths.get(self._key, 0)
        return held > (1 if self._registered else 0)

    def acquire(self) -> bool:
        self.last_error = None
        self.last_error_stage = None
        try:
            self.fd = os.open(str(self.path), os.O_CREAT | os.O_WRONLY)
        except OSError as exc:
            self.last_error = exc
            self.last_error_stage = "open"
            return False

        from ._fd_lock import lock_fd_exclusive

        try:
            lock_fd_exclusive(self.fd)
        except OSError as exc:
            self.last_error = exc
            self.last_error_stage = "lock"
            self.close()
            return False
        with _process_held_paths_lock:
            _process_held_paths[self._key] = _process_held_paths.get(self._key, 0) + 1
        self._registered = True
        return True

    def release(self) -> None:
        from ._fd_lock import unlock_fd

        if self.fd is not None:
            unlock_fd(self.fd)
            self.close()
        self._unregister()

    def close(self) -> None:
        if self.fd is not None:
            with suppress(OSError):
                os.close(self.fd)
            self.fd = None

    def _unregister(self) -> None:
        """Drop this instance's process-table entry, at most once."""
        if not self._registered:
            return
        self._registered = False
        with _process_held_paths_lock:
            remaining = _process_held_paths.get(self._key, 0) - 1
            if remaining > 0:
                _process_held_paths[self._key] = remaining
            else:
                _process_held_paths.pop(self._key, None)
