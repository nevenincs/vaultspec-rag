"""Process-level locking primitives for the local-file Qdrant store.

Split out of ``store.py`` to keep the store module focused on collection and
point operations. These helpers are stdlib-only (no qdrant, torch, or other
heavy imports) so they stay cheap to import from anywhere that needs the lock
or its error type.
"""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pathlib


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

    def acquire(self) -> bool:
        import os
        import sys

        try:
            self.fd = os.open(str(self.path), os.O_CREAT | os.O_WRONLY)
        except OSError:
            return False

        if sys.platform == "win32":
            import msvcrt

            try:
                msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                self.close()
                return False
        else:
            import fcntl

            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                self.close()
                return False

    def release(self) -> None:
        import os
        import sys

        if self.fd is not None:
            if sys.platform == "win32":
                import msvcrt

                try:
                    os.lseek(self.fd, 0, os.SEEK_SET)
                    msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl

                with suppress(OSError):
                    fcntl.flock(self.fd, fcntl.LOCK_UN)
            self.close()

    def close(self) -> None:
        import os

        if self.fd is not None:
            with suppress(OSError):
                os.close(self.fd)
            self.fd = None
