"""Logging configuration for vaultspec-rag.

Thin wrapper over :mod:`vaultspec_core.logging_config`. RAG previously held a
near-verbatim copy of core's implementation; it now delegates so the two
packages cannot silently diverge. The only RAG-specific behavior preserved
here is the env-var override (``VAULTSPEC_RAG_LOG_LEVEL``) and RAG's
``WARNING`` default when no explicit level is supplied.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING, override

from vaultspec_core.logging_config import configure_logging as _core_configure_logging
from vaultspec_core.logging_config import get_console, reset_logging

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "DaemonRotatingFileHandler",
    "configure_logging",
    "get_console",
    "install_daemon_log_rotation",
    "reset_logging",
]

logger = logging.getLogger(__name__)


def configure_logging(
    level: str | int | None = None,
    debug: bool = False,
    quiet: bool = False,
) -> None:
    """Configure the root logger via core's RichHandler setup.

    Honors the RAG-specific ``VAULTSPEC_RAG_LOG_LEVEL`` env var with a
    ``WARNING`` default when no explicit ``level``/``debug``/``quiet`` is
    provided, then delegates to :func:`vaultspec_core.logging_config.configure_logging`.

    Args:
        level: Explicit log level (e.g. ``logging.INFO`` or ``"DEBUG"``).
        debug: When ``True``, forces level to ``DEBUG`` and enables rich
            tracebacks with local variables.
        quiet: When ``True``, forces level to ``WARNING``.
    """
    if level is None and not debug and not quiet:
        from .config import EnvVar

        env_level = os.environ.get(EnvVar.LOG_LEVEL, "WARNING").upper()
        level = getattr(logging, env_level, logging.INFO)

    _core_configure_logging(level=level, debug=debug, quiet=quiet)


class DaemonRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that re-``dup2``s stdout/stderr after rollover.

    The daemon is spawned with its ``stdout``/``stderr`` already ``dup2``'d
    onto the open ``service.log`` FD by the parent CLI.  On first rotation,
    :class:`RotatingFileHandler` renames the log file and opens a fresh
    stream — but fds 1/2 still reference the *original* kernel inode,
    which ``os.rename`` has just moved to ``service.log.1``.  Without a
    re-``dup2``, stdout/stderr get stuck writing to the rotated file
    forever and the backup-count accounting silently goes wrong.

    This subclass overrides :meth:`doRollover` to ``os.dup2`` the
    freshly-opened stream's FD onto both 1 and 2 immediately after
    :meth:`RotatingFileHandler.doRollover` swaps the stream.  Python's
    :class:`logging.Handler` acquires a reentrant lock
    (``threading.RLock``) around every :meth:`emit` call, so the
    acquire/release inside :meth:`doRollover` is a defensive no-op in
    the common path and safe against reentrant calls.
    """

    @override
    def shouldRollover(self, record: logging.LogRecord) -> int:
        """Decide rollover from on-disk file size, not the handler's own writes.

        :class:`RotatingFileHandler.shouldRollover` measures
        ``self.stream.tell()`` which only reflects bytes the handler itself
        wrote.  In the daemon, ``print()``, uvicorn access logs, and core's
        :class:`rich.RichHandler` (which we re-route by ``dup2``-ing fds 1
        and 2 onto the same file) all bypass the handler's stream and grow
        the file directly.  Without this override, the handler under-counts
        the file size and never triggers rollover even after the on-disk
        log balloons past ``maxBytes``.
        """
        if self.stream is None:
            self.stream = self._open()
        if self.maxBytes > 0:
            size = self._safe_stream_size()
            msg = f"{self.format(record)}\n"
            if size + len(msg) >= self.maxBytes:
                return 1
        return 0

    def _safe_stream_size(self) -> int:
        """Best-effort current size of the active log file.

        ``shouldRollover`` is called from inside ``emit`` and must never
        propagate an exception, otherwise the handler's error path
        triggers and the rollover never fires.  Both ``fileno()`` and
        ``tell()`` raise ``ValueError`` on a closed stream, and ``fstat``
        can fail with ``OSError`` on some platforms — fall back through
        all three to ``0`` rather than letting any of them escape.
        """
        if self.stream is None:
            return 0
        try:
            return os.fstat(self.stream.fileno()).st_size
        except (OSError, ValueError):
            pass
        try:
            return self.stream.tell()
        except (OSError, ValueError):
            return 0

    @override
    def doRollover(self) -> None:
        """Rotate the log file, then re-``dup2`` fds 1 and 2 onto the stream.

        On Windows, any open handle to the active log file blocks the
        rename inside :meth:`RotatingFileHandler.doRollover`.  Because
        the daemon has ``dup2``'d fds 1 and 2 onto the log file during
        :func:`install_daemon_log_rotation`, those fds would otherwise
        pin the file open.  The fix is to redirect fds 1 and 2 to
        ``os.devnull`` for the duration of the rename, then re-``dup2``
        them onto the freshly-opened stream once the parent class has
        swapped files.

        If anything in the rollover sequence raises (e.g. transient
        Windows file-lock conflict, or ``self.stream is None`` because
        the handler is in ``delay=True`` mode), fds 1 and 2 are
        restored to *whatever ``self.baseFilename`` currently points
        at* by opening it fresh and ``dup2``-ing the new fd onto 1 and
        2.  This prevents the silent-log-loss failure mode where a
        partial rollover leaves stdout/stderr permanently pinned to
        ``/dev/null``.  Note that we do **not** save the original fds
        1 / 2 before redirecting to ``/dev/null`` because those fds
        point at the active log file and would themselves block the
        Windows rename inside ``super().doRollover()``.
        """
        # logging.Handler.acquire() returns a reentrant RLock so it is
        # safe even when emit() already holds it on our behalf.
        self.acquire()
        try:
            devnull_fd = os.open(os.devnull, os.O_WRONLY)
            try:
                os.dup2(devnull_fd, 1)
                os.dup2(devnull_fd, 2)
            finally:
                os.close(devnull_fd)
            try:
                super().doRollover()
            except PermissionError:
                if os.name != "nt":
                    self._rebind_fds_to_basefile()
                    raise
                self._copytruncate_rollover()
            except Exception:
                self._rebind_fds_to_basefile()
                raise
            # ``self.stream is None`` is the expected state when
            # ``delay=True`` is configured: the parent class defers the
            # next ``_open()`` until the following emit().  Treat it as
            # a valid no-op and rebind fds 1/2 to the (newly empty)
            # ``baseFilename`` so subsequent stdout/stderr writes still
            # land in the active log file rather than ``/dev/null``.
            if self.stream is None:
                self._rebind_fds_to_basefile()
                return
            fd = self.stream.fileno()
            os.dup2(fd, 1)
            os.dup2(fd, 2)
        finally:
            self.release()

    def _copytruncate_rollover(self) -> None:
        """Rotate by copying and truncating when Windows blocks rename.

        Some Windows handles inherited by the detached service can keep
        the active log path non-renamable even after fds 1 and 2 are
        redirected.  In that case, preserve the normal bounded-backup
        contract by shifting existing backups, copying the active file
        into ``.1``, and truncating the active file in place.
        """
        if self.stream is not None:
            self.stream.close()
            self.stream = None

        if self.backupCount > 0:
            for i in range(self.backupCount - 1, 0, -1):
                src = self.rotation_filename(f"{self.baseFilename}.{i}")
                dst = self.rotation_filename(f"{self.baseFilename}.{i + 1}")
                if os.path.exists(src):
                    if os.path.exists(dst):
                        os.remove(dst)
                    os.replace(src, dst)

            first_backup = self.rotation_filename(f"{self.baseFilename}.1")
            if os.path.exists(first_backup):
                os.remove(first_backup)
            if os.path.exists(self.baseFilename):
                shutil.copyfile(self.baseFilename, first_backup)

        with open(self.baseFilename, "w", encoding=self.encoding):
            pass

        if not self.delay:
            self.stream = self._open()

    def _rebind_fds_to_basefile(self) -> None:
        """Best-effort: re-``dup2`` fds 1 and 2 onto ``self.baseFilename``.

        Used by :meth:`doRollover`'s recovery path and the ``delay=True``
        no-op path.  Failures are swallowed because the caller is
        already mid-recovery — the original error (if any) still
        propagates with its traceback intact.
        """
        try:
            recovery_fd = os.open(
                self.baseFilename,
                os.O_WRONLY | os.O_APPEND | os.O_CREAT,
                0o644,
            )
        except OSError:
            return
        try:
            with contextlib.suppress(OSError):
                os.dup2(recovery_fd, 1)
                os.dup2(recovery_fd, 2)
        finally:
            with contextlib.suppress(OSError):
                os.close(recovery_fd)


def install_daemon_log_rotation(
    log_path: Path,
    *,
    max_bytes: int,
    backup_count: int,
) -> DaemonRotatingFileHandler:
    """Attach a :class:`DaemonRotatingFileHandler` to the root logger.

    Idempotent: if a :class:`DaemonRotatingFileHandler` is already
    attached to the root logger, the existing handler is returned
    unchanged.  On first install, opens the handler against
    *log_path*, attaches it to the root logger, and performs an
    initial ``os.dup2`` of the stream's FD onto fds 1 and 2 so
    ``print()`` and third-party raw stdout writes land in the
    rotated file alongside formatted log records.

    Args:
        log_path: Absolute path to the active ``service.log`` file.
            The parent directory is created if missing.
        max_bytes: Rollover threshold in bytes.  ``0`` disables
            rotation (handler still installs but never rolls).
        backup_count: Number of rotated backups to keep.  ``0`` rolls
            and truncates without keeping history.

    Returns:
        The installed (or pre-existing)
        :class:`DaemonRotatingFileHandler` instance.
    """
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, DaemonRotatingFileHandler):
            return handler

    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = DaemonRotatingFileHandler(
        str(log_path),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)

    if handler.stream is not None:
        fd = handler.stream.fileno()
        os.dup2(fd, 1)
        os.dup2(fd, 2)

    return handler
