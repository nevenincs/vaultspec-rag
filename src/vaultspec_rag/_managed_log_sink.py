"""Single-writer byte sink shared by managed service and Qdrant logs."""

from __future__ import annotations

import contextlib
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import BinaryIO

__all__ = ["RawRotatingLogSink"]


class RawRotatingLogSink:
    """Secure size-rotating sink for one managed raw byte stream.

    Exactly one drain thread owns each instance. The active handle is closed
    before numbered files move, which is required for Windows. Opens use append
    mode, owner-only permissions, and ``O_NOFOLLOW`` where available.
    """

    def __init__(self, path: Path, *, max_bytes: int, backup_count: int) -> None:
        self.path = path
        self.max_bytes = int(max_bytes)
        self.backup_count = int(backup_count)
        if self.max_bytes <= 0:
            raise ValueError("managed log max_bytes must be positive")
        if self.backup_count < 0:
            raise ValueError("managed log backup_count must be non-negative")
        self._stream: BinaryIO | None = None
        self._retention_checked = False

    @staticmethod
    def _enforce_containment(path: Path, *, operation: str) -> None:
        """Fail before a managed-log filesystem effect escapes pytest isolation."""
        from ._test_isolation import enforce_pytest_singleton_containment

        enforce_pytest_singleton_containment(path, operation=operation)

    def _open(self, *, truncate: bool = False) -> BinaryIO:
        self._enforce_containment(self.path, operation="open managed log sink")
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        flags |= os.O_TRUNC if truncate else os.O_APPEND
        fd = os.open(self.path, flags, 0o600)
        try:
            if os.name != "nt":
                os.fchmod(fd, 0o600)
            return os.fdopen(fd, "wb" if truncate else "ab", buffering=0)
        except Exception:
            os.close(fd)
            raise

    def _ensure_open(self) -> BinaryIO:
        if self._stream is None:
            self._stream = self._open()
        return self._stream

    def close(self) -> None:
        """Close the active stream; safe after an earlier close."""
        stream = self._stream
        self._stream = None
        if stream is not None:
            stream.close()

    def _backup_path(self, generation: int) -> Path:
        return self.path.with_name(f"{self.path.name}.{generation}")

    def _trim_to_tail(self, candidate: Path) -> None:
        """Bound a retained file immediately, preserving its newest bytes."""
        self._enforce_containment(
            candidate,
            operation="bound oversized managed log generation",
        )
        flags = os.O_RDWR | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(candidate, flags)
        except FileNotFoundError:
            return
        try:
            size = os.fstat(fd).st_size
            if size <= self.max_bytes:
                return
            os.lseek(fd, size - self.max_bytes, os.SEEK_SET)
            tail = bytearray()
            while len(tail) < self.max_bytes:
                block = os.read(fd, self.max_bytes - len(tail))
                if not block:
                    break
                tail.extend(block)
            os.lseek(fd, 0, os.SEEK_SET)
            view = memoryview(tail)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("managed log migration made no write progress")
                view = view[written:]
            os.ftruncate(fd, len(tail))
        finally:
            os.close(fd)

    def _enforce_backup_count(self) -> None:
        """Remove stale numeric generations outside the configured set."""
        prefix = f"{self.path.name}."
        self._enforce_containment(
            self.path.parent,
            operation="scan managed log generations",
        )
        with os.scandir(self.path.parent) as entries:
            for entry in entries:
                if not entry.name.startswith(prefix):
                    continue
                suffix = entry.name[len(prefix) :]
                if not suffix.isascii() or not suffix.isdigit():
                    continue
                generation = int(suffix)
                if (
                    generation < 1
                    or generation > self.backup_count
                    or suffix != str(generation)
                ):
                    candidate = Path(entry.path)
                    self._enforce_containment(
                        candidate,
                        operation="remove stale managed log generation",
                    )
                    try:
                        os.unlink(candidate)
                    except FileNotFoundError:
                        continue
                else:
                    self._trim_to_tail(Path(entry.path))

    def _shift_backups(self) -> None:
        oldest = self._backup_path(self.backup_count)
        self._enforce_containment(
            oldest,
            operation="remove oldest managed log generation",
        )
        with contextlib.suppress(FileNotFoundError):
            os.unlink(oldest)
        for generation in range(self.backup_count - 1, 0, -1):
            source = self._backup_path(generation)
            destination = self._backup_path(generation + 1)
            self._enforce_containment(
                source,
                operation="shift managed log generation source",
            )
            self._enforce_containment(
                destination,
                operation="shift managed log generation destination",
            )
            try:
                os.replace(source, destination)
            except FileNotFoundError:
                # Sparse generations are valid after interrupted/manual cleanup.
                continue

    def _copy_active_to_first_backup(self) -> None:
        """Copy active bytes securely for the Windows rename fallback."""
        self._enforce_containment(
            self.path,
            operation="copy managed log rollover source",
        )
        source_flags = (
            os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        source_fd = os.open(self.path, source_flags)
        try:
            destination = self._backup_path(1)
            self._enforce_containment(
                destination,
                operation="copy managed log rollover destination",
            )
            destination_flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_TRUNC
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            destination_fd = os.open(destination, destination_flags, 0o600)
            try:
                if os.name != "nt":
                    os.fchmod(destination_fd, 0o600)
                with (
                    os.fdopen(source_fd, "rb", closefd=False) as source,
                    os.fdopen(
                        destination_fd,
                        "wb",
                        buffering=0,
                        closefd=False,
                    ) as target,
                ):
                    shutil.copyfileobj(source, target)
            finally:
                os.close(destination_fd)
        finally:
            os.close(source_fd)

    def _truncate_active(self) -> None:
        stream = self._open(truncate=True)
        stream.close()

    def _rollover(self) -> None:
        self.close()
        if self.backup_count == 0:
            self._truncate_active()
            self._stream = self._open()
            return

        self._shift_backups()
        first_backup = self._backup_path(1)
        self._enforce_containment(
            self.path,
            operation="rotate managed log source",
        )
        self._enforce_containment(
            first_backup,
            operation="rotate managed log destination",
        )
        try:
            os.replace(self.path, first_backup)
        except PermissionError:
            if os.name != "nt":
                raise
            # A foreign Windows read handle can retain the active path. Copy
            # then truncate preserves the bounded contract without growing it.
            self._copy_active_to_first_backup()
            self._truncate_active()
        self._stream = self._open()

    def write(self, payload: bytes) -> None:
        """Persist arbitrary bytes without allowing a generation past its cap."""
        if not payload:
            return
        if not self._retention_checked:
            self._enforce_backup_count()
            self._trim_to_tail(self.path)
            self._retention_checked = True

        remaining = memoryview(payload)
        while remaining:
            stream = self._ensure_open()
            size = os.fstat(stream.fileno()).st_size
            if size >= self.max_bytes:
                self._rollover()
                continue

            capacity = self.max_bytes - size
            chunk = remaining[:capacity]
            written = stream.write(chunk)
            if written <= 0:
                raise OSError("managed log sink made no write progress")
            remaining = remaining[written:]
            if remaining and size + written >= self.max_bytes:
                self._rollover()
