"""Process-level locking primitives for the local-file Qdrant store.

Split out of ``store.py`` to keep the store module focused on collection and
point operations. These helpers are stdlib-only (no qdrant, torch, or other
heavy imports) so they stay cheap to import from anywhere that needs the lock
or its error type.
"""

from __future__ import annotations

import time
from contextlib import ExitStack, contextmanager, suppress
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Generator, Mapping


@contextmanager
def acquire_collection_locks(
    locks: Mapping[str, Any],
) -> Generator[None]:
    """Acquire collection guards in deterministic name order."""
    with ExitStack() as stack:
        for name in sorted(locks):
            stack.enter_context(locks[name])
        yield


@contextmanager
def acquire_collection_locks_bounded(
    locks: Mapping[str, Any],
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
    acquired: list[Any] = []
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
    """Raised when the Qdrant storage folder is already opened by another process.

    Attributes:
        db_path: Absolute path to the locked Qdrant storage folder.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        super().__init__(
            "Qdrant storage at "
            f"{db_path} is already in use by another process. "
            "Local-file-backed RAG storage is not parallel-safe across "
            "multiple vaultspec-rag processes; route concurrent searches "
            "through one resident service or retry after the holder exits.",
        )


class FileLock:
    """Cross-platform non-blocking file lock."""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        self.fd = None
        self.last_error: OSError | None = None
        self.last_error_stage: str | None = None

    def acquire(self) -> bool:
        import os

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
        return True

    def release(self) -> None:
        from ._fd_lock import unlock_fd

        if self.fd is not None:
            unlock_fd(self.fd)
            self.close()

    def close(self) -> None:
        import os

        if self.fd is not None:
            with suppress(OSError):
                os.close(self.fd)
            self.fd = None
