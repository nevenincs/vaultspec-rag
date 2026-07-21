"""Logging configuration for vaultspec-rag.

Thin wrapper over :mod:`vaultspec_core.logging_config`. RAG previously held a
near-verbatim copy of core's implementation; it now delegates so the two
packages cannot silently diverge. The only RAG-specific behavior preserved
here is the env-var override (``VAULTSPEC_RAG_LOG_LEVEL``) and RAG's
``WARNING`` default when no explicit level is supplied.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypedDict, override

from vaultspec_core.logging_config import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
    configure_logging as _core_configure_logging,
)
from vaultspec_core.logging_config import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
    get_console,
    reset_logging,
)

__all__ = [
    "DaemonRotatingFileHandler",
    "InvalidManagedLogSourceError",
    "ManagedLogGroup",
    "ManagedLogSource",
    "configure_logging",
    "get_console",
    "install_daemon_log_rotation",
    "log_event",
    "read_managed_logs",
    "reset_logging",
]

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Mapping

_EVENT_TOKEN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
_FIELD_TOKEN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_BARE_VALUE_RE = re.compile(r"^[A-Za-z0-9_./:@\\-]+$")

type ManagedLogSource = Literal["service", "qdrant", "all"]
type ManagedLogGroupSource = Literal["service", "qdrant"]


class ManagedLogGroup(TypedDict):
    """One source's raw records, ordered only within that source."""

    source: ManagedLogGroupSource
    lines: list[str]


class InvalidManagedLogSourceError(ValueError):
    """Raised when a managed-log source selector is not supported."""


_MANAGED_LOG_SOURCES: tuple[ManagedLogGroupSource, ...] = ("service", "qdrant")
_QDRANT_LOG_NAME = "qdrant.log"
_TAIL_READ_BLOCK_BYTES = 64 * 1024


def _format_event_value(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, Path):
        value = str(value)

    rendered = str(value)
    if _BARE_VALUE_RE.fullmatch(rendered):
        return rendered
    return json.dumps(rendered, ensure_ascii=True)


def log_event(
    target_logger: logging.Logger,
    namespace: str,
    event: str,
    *,
    severity: int = logging.INFO,
    exc_info: Any = None,
    fields: Mapping[str, object] | None = None,
    **extra_fields: object,
) -> None:
    """Emit a parseable service event through the configured logger.

    Events use a stable ``namespace event=name key=value`` message shape
    so CLI log filtering, MCP adapters, and external collectors can
    consume the same stream without depending on human-facing formatting.
    Values containing whitespace or shell-significant punctuation are
    JSON-quoted; common identifiers and paths remain bare for greppability.
    """
    if not _EVENT_TOKEN_RE.fullmatch(namespace):
        msg = f"invalid log event namespace: {namespace!r}"
        raise ValueError(msg)
    if not _EVENT_TOKEN_RE.fullmatch(event):
        msg = f"invalid log event name: {event!r}"
        raise ValueError(msg)

    combined_fields: dict[str, object] = {}
    if fields is not None:
        combined_fields.update(fields)
    combined_fields.update(extra_fields)

    parts = [namespace, f"event={event}"]
    for key, value in combined_fields.items():
        if not _FIELD_TOKEN_RE.fullmatch(key):
            msg = f"invalid log event field: {key!r}"
            raise ValueError(msg)
        parts.append(f"{key}={_format_event_value(value)}")

    target_logger.log(
        severity,
        "%s",
        " ".join(parts),
        exc_info=exc_info,
        extra={
            "vaultspec_event_namespace": namespace,
            "vaultspec_event": event,
            "vaultspec_event_fields": dict(combined_fields),
        },
    )


def _resolve_status_dir(status_dir: Path | None) -> Path:
    """Resolve the service status directory for the log reader.

    Mirrors the CLI's ``_status_dir`` / the daemon's
    ``_resolve_log_path`` resolution (``cfg.status_dir`` with env-var
    and CLI overrides) so the reader walks the same directory the
    daemon rotates into. An explicit *status_dir* (used by tests)
    short-circuits config resolution.
    """
    if status_dir is not None:
        return status_dir
    from .config import get_config

    cfg = get_config()
    return Path(cfg.status_dir).expanduser()


def _managed_log_source(raw: str) -> ManagedLogSource:
    if raw == "service":
        return "service"
    if raw == "qdrant":
        return "qdrant"
    if raw == "all":
        return "all"
    msg = "source must be one of service, qdrant, all."
    raise InvalidManagedLogSourceError(msg)


def _managed_log_name(source: ManagedLogGroupSource) -> str:
    if source == "qdrant":
        return _QDRANT_LOG_NAME
    from .config import get_config

    return str(get_config().log_file)


def _rotated_log_paths(status_dir: Path, log_name: str) -> list[Path]:
    """Return sparse generations oldest-first, followed by the active file."""
    suffix_re = re.compile(rf"^{re.escape(log_name)}\.(\d+)$")
    generations: list[tuple[int, Path]] = []
    try:
        entries = status_dir.iterdir()
        for entry in entries:
            match = suffix_re.fullmatch(entry.name)
            if match is None:
                continue
            generation = int(match.group(1))
            if generation > 0:
                generations.append((generation, entry))
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.debug("managed log directory %s unreadable: %s", status_dir, exc)

    generations.sort(key=lambda item: item[0], reverse=True)
    return [*(path for _generation, path in generations), status_dir / log_name]


def _tail_file_lines(path: Path, lines: int) -> list[str]:
    """Read at most the final *lines* records without loading the whole file."""
    if lines <= 0:
        return []
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            position = stream.tell()
            chunks: list[bytes] = []
            newline_count = 0
            # Read one delimiter beyond the requested record count when possible,
            # so an initial partial record from the first block is discarded by
            # the final tail rather than surfaced as a fabricated log line.
            while position > 0 and newline_count <= lines:
                block_size = min(position, _TAIL_READ_BLOCK_BYTES)
                position -= block_size
                stream.seek(position)
                chunk = stream.read(block_size)
                chunks.append(chunk)
                newline_count += chunk.count(b"\n")
    except FileNotFoundError as exc:
        logger.debug("managed log %s vanished mid-read: %s", path, exc)
        return []
    except OSError as exc:
        logger.debug("managed log %s unreadable: %s", path, exc)
        return []

    text = b"".join(reversed(chunks)).decode("utf-8", errors="replace")
    return text.splitlines()[-lines:]


def _read_managed_source(
    status_dir: Path,
    source: ManagedLogGroupSource,
    lines: int,
) -> ManagedLogGroup:
    remaining = max(0, lines)
    newest_chunks: list[list[str]] = []
    # Paths are chronological; read them newest-first so older generations are
    # never touched after the requested per-source record bound is satisfied.
    for path in reversed(_rotated_log_paths(status_dir, _managed_log_name(source))):
        if remaining <= 0:
            break
        chunk = _tail_file_lines(path, remaining)
        if not chunk:
            continue
        newest_chunks.append(chunk)
        remaining -= len(chunk)

    source_lines = [line for chunk in reversed(newest_chunks) for line in chunk]
    return {"source": source, "lines": source_lines}


def read_managed_logs(
    lines: int,
    *,
    source: str = "all",
    status_dir: Path | None = None,
) -> list[ManagedLogGroup]:
    """Return bounded raw records grouped by managed producer.

    ``all`` returns the service group followed by the Qdrant group. That is a
    stable display order only: no chronology is inferred across producers.
    Within each group, records are oldest-first and span any sparse numeric
    backup generations plus the active file. Missing or concurrently rotated
    files are skipped without failing the whole operator view.

    Args:
        lines: Maximum records returned for each selected source. Non-positive
            values retain the selected empty group or groups.
        source: ``service``, ``qdrant``, or ``all`` (the default).
        status_dir: Explicit managed-log directory, primarily for offline use
            and tests. Defaults to the configured status directory.

    Raises:
        InvalidManagedLogSourceError: When *source* is not supported.
    """
    selected = _managed_log_source(source)
    selected_sources = _MANAGED_LOG_SOURCES if selected == "all" else (selected,)
    base = _resolve_status_dir(status_dir)
    return [
        _read_managed_source(base, managed_source, lines)
        for managed_source in selected_sources
    ]


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
    stream - but fds 1/2 still reference the *original* kernel inode,
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
        can fail with ``OSError`` on some platforms - fall back through
        all three to ``0`` rather than letting any of them escape.
        """
        if self.stream is None:
            return 0
        try:
            return os.fstat(self.stream.fileno()).st_size
        except (OSError, ValueError) as exc:
            logger.debug("log fstat fell through to tell(): %s", exc)
        try:
            return self.stream.tell()
        except (OSError, ValueError) as exc:
            logger.debug("log tell() fell through to 0: %s", exc)
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
            self._shift_backups()
            self._copy_base_to_first_backup()

        with open(self.baseFilename, "w", encoding=self.encoding):
            pass

        if not self.delay:
            self.stream = self._open()

    def _shift_backups(self) -> None:
        for i in range(self.backupCount - 1, 0, -1):
            src = self.rotation_filename(f"{self.baseFilename}.{i}")
            dst = self.rotation_filename(f"{self.baseFilename}.{i + 1}")
            if os.path.exists(src):
                if os.path.exists(dst):
                    os.remove(dst)
                os.replace(src, dst)

    def _copy_base_to_first_backup(self) -> None:
        first_backup = self.rotation_filename(f"{self.baseFilename}.1")
        if os.path.exists(first_backup):
            os.remove(first_backup)
        if os.path.exists(self.baseFilename):
            shutil.copyfile(self.baseFilename, first_backup)

    def _rebind_fds_to_basefile(self) -> None:
        """Best-effort: re-``dup2`` fds 1 and 2 onto ``self.baseFilename``.

        Used by :meth:`doRollover`'s recovery path and the ``delay=True``
        no-op path.  Failures are swallowed because the caller is
        already mid-recovery - the original error (if any) still
        propagates with its traceback intact.
        """
        try:
            recovery_fd = os.open(
                self.baseFilename,
                os.O_WRONLY | os.O_APPEND | os.O_CREAT,
                0o644,
            )
        except OSError as exc:
            logger.debug(
                "fd rebind: log open(%s) failed: %s",
                self.baseFilename,
                exc,
            )
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
