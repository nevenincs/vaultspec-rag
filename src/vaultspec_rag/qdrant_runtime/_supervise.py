"""Supervision of the qdrant server child process.

The resident daemon spawns exactly one loopback-bound qdrant child,
configured entirely through ``QDRANT__*`` environment variables, polls
its readiness endpoint with exponential backoff, and terminates it
last among data components on shutdown. On Windows the child is
assigned to a kill-on-close Job Object so a hard daemon death (kill,
OOM, crash before atexit) can never orphan a qdrant process - the OS
closes the job handle with the daemon and tears the child down with
it.
"""

from __future__ import annotations

import codecs
import contextlib
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .._managed_log_sink import RawRotatingLogSink
from .._win32 import WIN_CREATE_NEW_PROCESS_GROUP, WIN_CREATE_NO_WINDOW
from ._constants import (
    LOOPBACK_OPENER,
    QDRANT_SERVER_VERSION,
    QdrantRuntimeState,
)

if TYPE_CHECKING:
    from typing import Any, BinaryIO

    from ._resolve import QdrantIdentity

logger = logging.getLogger(__name__)

__all__ = [
    "QdrantSupervisor",
    "active_supervisor",
    "runtime_state",
    "set_active_supervisor",
    "start_supervised_from_config",
]

# Whole-operation budget for the pre-spawn orphan reap: five witness
# inspections plus the reap itself. Generous enough that a healthy host never
# reaches it, small enough that a wedged local inspection (a blocked Windows
# ``tasklist``, a hung psutil probe) fails startup with a named cause instead
# of holding the machine singleton lock indefinitely.
_REAP_BUDGET_DEFAULT_SECONDS = 30.0
_READY_TIMEOUT_DEFAULT_SECONDS = 300.0
_READY_TIMEOUT_ENV = "VAULTSPEC_RAG_QDRANT_READY_TIMEOUT"
_STOP_TIMEOUT_SECONDS = 10.0
# How many of the child's most-recent output lines to retain in memory so a
# non-ready exit can be reported with its cause (a Rust panic, a bind error, a
# storage-lock error) instead of an opaque timeout.
_RECENT_OUTPUT_LINES = 50
_RECENT_OUTPUT_LINE_CHARS = 16 * 1024
_QDRANT_DRAIN_CHUNK_BYTES = 64 * 1024
_DRAIN_JOIN_TIMEOUT_SECONDS = 3.0
_MANAGED_LOG_MAX_BYTES_DEFAULT = 10 * 1024 * 1024
_MANAGED_LOG_BACKUP_COUNT_DEFAULT = 5

# Recovery bound: how many collections may be quarantined within one supervised
# start before the start fails loudly instead of quarantining further. A
# pathological store (many corrupt collections, or a non-load panic the parser
# misreads) must degrade to a clear failure, not loop the whole store into
# quarantine, bounded by a per-start retry count, then fail loudly.
_MAX_QUARANTINES_PER_START = 3

# Lowercased substrings that mark a collection *load* failure in the captured
# qdrant output. These are failure-specific - broad operational words that also
# appear in healthy load/recovery logging (``segment``, ``wal``, ``snapshot``,
# ``recover``) are deliberately excluded so normal output never reads as a
# failure. Detection only quarantines when one of these co-occurs with a real
# on-disk collection name *on the same line*.
_LOAD_FAILURE_MARKERS = (
    "panic",
    "corrupt",
    "failed to load",
    "cannot load",
    "unable to load",
    "could not load",
    "error loading",
)


def _qdrant_child_path(path: Path) -> str:
    """Render a storage path for the qdrant child's environment.

    On Windows the path is converted to extended-length form
    (``\\\\?\\C:\\...``, or ``\\\\?\\UNC\\server\\share\\...`` for UNC): the
    engine's on-disk ``collections/<name>/segments/<uuid>/...`` layout
    otherwise crosses the classic 260-character MAX_PATH once the storage
    root exceeds ~105 characters, and every collection create fails with
    "os error 3" - the ``LongPathsEnabled`` registry setting does not help.
    Extended-length paths bypass that limit entirely (verified against the
    pinned binary: plain paths fail at 140/200 characters, verbatim paths
    succeed). Verbatim form disables Win32 normalization, so the path is
    absolute-resolved first. Non-Windows platforms and already-prefixed
    paths pass through unchanged. Python-side bookkeeping keeps using the
    plain path; only the child's env sees this form.
    """
    if sys.platform != "win32":
        return str(path)
    resolved = os.path.abspath(str(path))
    if resolved.startswith("\\\\?\\"):
        return resolved
    if resolved.startswith("\\\\"):
        return "\\\\?\\UNC\\" + resolved[2:]
    return "\\\\?\\" + resolved


def _list_on_disk_collections(storage_dir: Path) -> set[str]:
    """Return the names of the collection directories in *storage_dir*.

    Names starting with ``.`` (and the ``quarantine`` sibling) are not
    collections Qdrant loads, so they are excluded.
    """
    collections_dir = storage_dir / "collections"
    try:
        return {
            entry.name
            for entry in collections_dir.iterdir()
            if entry.is_dir() and not entry.name.startswith(".")
        }
    except OSError:
        return set()


def _corrupt_collection_from_output(tail: str, storage_dir: Path) -> str | None:
    """Identify the corrupt collection named in a startup-failure *tail*.

    Keys on the real on-disk collection set rather than Qdrant's (version-
    dependent) message format: returns the longest on-disk collection name that
    appears on a *single line* together with a load-failure marker, else
    ``None``. Requiring the name and the marker on the same line avoids fingering
    a collection merely logged (healthily) earlier in the buffer while an
    unrelated, collection-less fault (corrupt ``raft_state.json``, disk-full,
    OOM) panics later. Abstaining on no match is deliberate - guessing would risk
    quarantining a healthy index.
    """
    on_disk = _list_on_disk_collections(storage_dir)
    if not on_disk:
        return None
    # Longest-first so a short collection name that is a substring of a longer
    # one does not shadow the real, longer culprit.
    names = sorted(on_disk, key=len, reverse=True)
    for line in tail.splitlines():
        lowered = line.lower()
        if not any(marker in lowered for marker in _LOAD_FAILURE_MARKERS):
            continue
        for name in names:
            if name in line:
                return name
    return None


def _quarantine_collection(storage_dir: Path, name: str) -> Path:
    """Move collection *name* aside to ``{storage_dir}/quarantine/{name}.{ts}``.

    The quarantine directory is a sibling of ``collections/`` (never under it,
    or Qdrant would try to load it), so the move removes the collection from the
    set Qdrant loads. The move is reversible and preserves the corrupt files for
    forensics; the root re-creates its collection on demand on its next touch.
    Returns the quarantine destination.
    """
    src = storage_dir / "collections" / name
    quarantine_dir = storage_dir / "quarantine"
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = quarantine_dir / f"{name}.{stamp}"
    src.rename(dest)
    return dest


def _ready_timeout_seconds() -> float:
    """Resolve the qdrant readiness timeout, env-overridable.

    A large managed store cold-loads every collection before answering
    ``/readyz``; a multi-hundred-GB store with ~170 collections was
    measured at ~131s, well over the original fixed 60s, so the default is
    generous and operators with even larger stores can raise it via
    ``VAULTSPEC_RAG_QDRANT_READY_TIMEOUT`` (seconds). A missing, malformed,
    or non-positive value falls back to the default rather than failing
    startup.
    """
    raw = os.environ.get(_READY_TIMEOUT_ENV)
    if raw is None:
        return _READY_TIMEOUT_DEFAULT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return _READY_TIMEOUT_DEFAULT_SECONDS
    return value if value > 0 else _READY_TIMEOUT_DEFAULT_SECONDS


# Environment variables the qdrant child inherits. Least privilege: only
# OS-operation variables (so the binary runs correctly on every platform),
# never the daemon's full environment, so daemon secrets are not exposed.
_CHILD_ENV_PASSTHROUGH = frozenset(
    {
        "PATH",
        "SystemRoot",
        "SYSTEMROOT",
        "windir",
        "ComSpec",
        "COMSPEC",
        "PATHEXT",
        "ProgramData",
        "ProgramFiles",
        "ProgramFiles(x86)",
        "TEMP",
        "TMP",
        "TMPDIR",
        "HOME",
        "USERPROFILE",
        "NUMBER_OF_PROCESSORS",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        # Diagnostics for the Rust child: operator-set crash backtraces and log
        # tuning. Diagnostic-only, no secrets - kept so curating the env does not
        # silently swallow an operator's RUST_BACKTRACE=1 / RUST_LOG=...
        "RUST_BACKTRACE",
        "RUST_LOG",
    }
)

# Unlike the daemon spawn, the qdrant child must NOT break away from the
# daemon's Job Object - that membership is exactly the no-orphan guarantee,
# so no breakaway flag appears here.
_WIN_CREATE_NEW_PROCESS_GROUP = WIN_CREATE_NEW_PROCESS_GROUP
_WIN_CREATE_NO_WINDOW = WIN_CREATE_NO_WINDOW

# Job Object constants (WinBase.h / winnt.h).
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9


def _win_kill_on_close_job() -> object | None:
    """Create a Windows Job Object configured to kill members on close.

    Returns:
        The job handle (kept alive by the caller for the daemon's
        lifetime), or ``None`` off-Windows or when creation fails.
    """
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimits),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        logger.warning("CreateJobObjectW failed; qdrant orphan guard disabled")
        return None
    info = _ExtendedLimits()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = kernel32.SetInformationJobObject(
        job,
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        logger.warning("SetInformationJobObject failed; qdrant orphan guard disabled")
        kernel32.CloseHandle(job)
        return None
    return job


def _win_assign_to_job(job: object, proc: subprocess.Popen[bytes]) -> bool:
    """Assign *proc* to *job*; True on success (logged otherwise)."""
    if sys.platform != "win32" or job is None:
        return False
    import ctypes

    kernel32 = ctypes.windll.kernel32
    # Popen exposes the raw Windows process handle as ``_handle``;
    # typeshed does not declare it, hence the Any cast.
    handle = int(cast("Any", proc)._handle)
    if kernel32.AssignProcessToJobObject(job, handle):
        return True
    logger.error(
        "AssignProcessToJobObject failed for qdrant pid %d; kill-on-close "
        "orphan guard is DISABLED for this child - a hard daemon death may "
        "orphan it",
        proc.pid,
    )
    return False


class QdrantSupervisor:
    """Owns one loopback-bound qdrant child process.

    Attributes:
        binary: The executable to spawn.
        http_port: REST listener port (loopback).
        grpc_port: gRPC listener port (loopback); defaults to one
            below ``http_port`` so the pair never collides with the
            RAG service's own port one above.
        storage_dir: Shared multi-root storage directory.
        log_path: File qdrant stdout/stderr is appended to.
        restart_count: Heartbeat-initiated restarts performed so far.
    """

    def __init__(
        self,
        binary: Path,
        *,
        http_port: int,
        storage_dir: Path,
        grpc_port: int | None = None,
        log_path: Path | None = None,
        log_max_bytes: int = _MANAGED_LOG_MAX_BYTES_DEFAULT,
        log_backup_count: int = _MANAGED_LOG_BACKUP_COUNT_DEFAULT,
    ) -> None:
        self.binary = binary
        self.http_port = int(http_port)
        self.grpc_port = int(grpc_port) if grpc_port is not None else self.http_port - 1
        self.storage_dir = storage_dir
        self.log_path = log_path
        self.log_max_bytes = int(log_max_bytes)
        self.log_backup_count = int(log_backup_count)
        if self.log_max_bytes <= 0:
            raise ValueError("log_max_bytes must be positive")
        if self.log_backup_count < 0:
            raise ValueError("log_backup_count must be non-negative")
        self.restart_count = 0
        self._proc: subprocess.Popen[bytes] | None = None
        # Most-recent child output lines, filled by the drain thread, so a
        # non-ready exit reports its cause instead of an opaque timeout.
        self._recent_output: deque[str] = deque(maxlen=_RECENT_OUTPUT_LINES)
        self._drain_thread: threading.Thread | None = None
        # Attached mode: this supervisor points at an already-running managed
        # Qdrant it did NOT spawn, so it must never terminate it on stop().
        self._attached = False
        # The Windows kill-on-close job handle is deliberately held for
        # the supervisor's whole lifetime and never explicitly closed:
        # the OS kills the child exactly when the last handle closes
        # (on process exit), which IS the orphan guard. One job is
        # created once and reused across restart(); a supervisor must
        # therefore never be dropped-and-recreated while its child runs.
        self._job_handle: object | None = None

    @property
    def url(self) -> str:
        """The REST URL stores connect to."""
        return f"http://127.0.0.1:{self.http_port}"

    @property
    def pid(self) -> int | None:
        """PID of the running child, or ``None``."""
        return self._proc.pid if self._proc is not None else None

    def _child_env(self) -> dict[str, str]:
        # Least privilege: pass only OS-operation variables plus the QDRANT__*
        # knobs, never the daemon's full environment, so any secrets the daemon
        # holds (cloud creds, tokens) are not exposed to the qdrant child.
        env = {
            key: value
            for key, value in os.environ.items()
            if key in _CHILD_ENV_PASSTHROUGH
        }
        env.update(
            {
                "QDRANT__SERVICE__HOST": "127.0.0.1",
                "QDRANT__SERVICE__HTTP_PORT": str(self.http_port),
                "QDRANT__SERVICE__GRPC_PORT": str(self.grpc_port),
                "QDRANT__STORAGE__STORAGE_PATH": _qdrant_child_path(self.storage_dir),
                "QDRANT__STORAGE__SNAPSHOTS_PATH": _qdrant_child_path(
                    self.storage_dir.parent / "snapshots"
                ),
                "QDRANT__TELEMETRY_DISABLED": "true",
            }
        )
        return env

    def spawn(self) -> None:
        """Start the qdrant child (without waiting for readiness).

        Raises:
            RuntimeError: If a child is already running.
                Also raised while a previous child's output drain still owns
                the rotating log sink.
            OSError: If the spawn itself fails.
        """
        from .._test_isolation import enforce_pytest_managed_singleton_containment

        snapshots_dir = self.storage_dir.parent / "snapshots"
        containment_targets = [self.storage_dir, snapshots_dir]
        if self.log_path is not None:
            containment_targets.append(self.log_path)
        enforce_pytest_managed_singleton_containment(
            operation="create supervised managed Qdrant storage",
            targets=containment_targets,
        )

        if self.is_alive():
            raise RuntimeError(f"qdrant child pid={self.pid} is already running")
        if not self._join_output_drain(timeout=0.0):
            raise RuntimeError(
                "previous qdrant output drain is still active; refusing to spawn "
                "a second log writer"
            )
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._recent_output.clear()

        # Capture the child's combined stdout/stderr through a pipe drained by a
        # thread, rather than redirecting straight to a file: an abnormal exit
        # (a Rust panic, a port-bind failure, a storage-lock error) is then
        # retained in memory and reported as the cause, never lost behind an
        # opaque readiness timeout. The drain thread appends to the log file
        # with the same owner-only, no-symlink-follow protection as before.
        if sys.platform == "win32":
            self._proc = subprocess.Popen(
                [str(self.binary)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=self._child_env(),
                # Pin the child's working directory to the managed qdrant dir:
                # the binary writes runtime markers (.qdrant-initialized) into
                # its cwd, which must never be the service's start directory.
                cwd=str(self.storage_dir.parent),
                text=False,
                bufsize=0,
                creationflags=(_WIN_CREATE_NEW_PROCESS_GROUP | _WIN_CREATE_NO_WINDOW),
            )
            if self._job_handle is None:
                self._job_handle = _win_kill_on_close_job()
            if self._job_handle is not None:
                _win_assign_to_job(self._job_handle, self._proc)
        else:
            self._proc = subprocess.Popen(
                [str(self.binary)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=self._child_env(),
                # Same managed-cwd pin as the Windows branch above.
                cwd=str(self.storage_dir.parent),
                text=False,
                bufsize=0,
                start_new_session=True,
            )
        self._start_output_drain()
        logger.info(
            "qdrant child spawned: pid=%d http=%d grpc=%d storage=%s",
            self._proc.pid,
            self.http_port,
            self.grpc_port,
            self.storage_dir,
        )

    def _start_output_drain(self) -> None:
        """Start the daemon thread that drains the child's output pipe."""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        thread = threading.Thread(
            target=self._drain_output,
            args=(proc.stdout,),
            name=f"qdrant-log-drain-{proc.pid}",
            daemon=True,
        )
        self._drain_thread = thread
        thread.start()

    def _append_recent_text(self, text: str, pending: str) -> str:
        """Retain complete lines and a bounded tail of one incomplete line."""
        parts = f"{pending}{text}".split("\n")
        incomplete = parts.pop()
        for line in parts:
            self._recent_output.append(f"{line[-_RECENT_OUTPUT_LINE_CHARS:]}\n")
        return incomplete[-_RECENT_OUTPUT_LINE_CHARS:]

    def _drain_output(self, stream: BinaryIO) -> None:
        """Drain fixed-size child output chunks to the log and diagnostic ring.

        Runs until the child closes the pipe (EOF on death). Opens the log with
        owner-only permission and ``O_NOFOLLOW`` (where available) so a planted
        symlink at the log path cannot redirect the appended output. Persistence
        errors disable the file sink for that child but never stop pipe draining
        or recent-output capture.
        """
        sink = (
            RawRotatingLogSink(
                self.log_path,
                max_bytes=self.log_max_bytes,
                backup_count=self.log_backup_count,
            )
            if self.log_path is not None
            else None
        )
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        pending = ""
        try:
            while True:
                payload = os.read(stream.fileno(), _QDRANT_DRAIN_CHUNK_BYTES)
                if not payload:
                    break
                pending = self._append_recent_text(decoder.decode(payload), pending)
                if sink is not None:
                    try:
                        sink.write(payload)
                    except (OSError, ValueError) as exc:
                        failed_sink = sink
                        sink = None
                        # Persistence is already degraded. A secondary close
                        # failure must not end pipe draining and lose the
                        # diagnostic ring that explains the child failure.
                        with contextlib.suppress(OSError, ValueError):
                            failed_sink.close()
                        logger.warning(
                            "qdrant log persistence disabled for this child: %s",
                            exc,
                        )
            pending = self._append_recent_text(decoder.decode(b"", final=True), pending)
            if pending:
                self._recent_output.append(pending)
        except (OSError, ValueError) as exc:
            logger.debug("qdrant output drain ended: %s", exc)
        finally:
            if sink is not None:
                with contextlib.suppress(OSError, ValueError):
                    sink.close()
            with contextlib.suppress(OSError):
                stream.close()

    def _join_output_drain(self, *, timeout: float) -> bool:
        """Join and clear a completed drain without forgetting a live writer."""
        thread = self._drain_thread
        if thread is None:
            return True
        thread.join(timeout=max(0.0, timeout))
        if thread.is_alive():
            return False
        self._drain_thread = None
        return True

    def recent_output_tail(self, max_lines: int = 20) -> str:
        """Return the most-recent captured child output lines, joined."""
        lines = list(self._recent_output)
        return "".join(lines[-max_lines:])

    def _ready_probe(self) -> bool:
        url = f"{self.url}/readyz"
        try:
            with LOOPBACK_OPENER.open(url, timeout=2.0) as resp:
                return int(resp.status) == 200
        except (urllib.error.URLError, OSError, ValueError) as exc:
            logger.debug("qdrant readyz probe failed: %s", exc)
            return False

    def wait_ready(self, timeout: float | None = None) -> bool:
        """Poll ``/readyz`` with backoff until ready or *timeout*.

        Args:
            timeout: Seconds to wait; ``None`` resolves the env-overridable
                default via :func:`_ready_timeout_seconds`.

        Returns:
            True once the server answers ready; False on timeout or
            child death (both logged).
        """
        if timeout is None:
            timeout = _ready_timeout_seconds()
        deadline = time.monotonic() + timeout
        delay = 0.1
        while time.monotonic() < deadline:
            if not self.is_alive():
                logger.error("qdrant child died during startup; see %s", self.log_path)
                return False
            if self._ready_probe():
                return True
            time.sleep(delay)
            delay = min(delay * 2, 2.0)
        logger.error("qdrant child pid=%s not ready after %.0fs", self.pid, timeout)
        return False

    def start(
        self, timeout: float | None = None, *, auto_quarantine: bool = True
    ) -> None:
        """Spawn the child and wait for readiness, recovering a corrupt collection.

        On a readiness failure whose captured output names a real on-disk
        collection alongside a load-failure marker, that collection is
        quarantined and the start is retried, so one corrupt collection degrades
        to one stale root instead of bricking the whole shared store. Recovery is
        bounded by :data:`_MAX_QUARANTINES_PER_START`; when no culprit can be
        identified (or the bound is reached) the start fails loudly with the
        captured panic rather than guessing.

        Args:
            timeout: Seconds to wait for readiness; ``None`` resolves the
                env-overridable default via :func:`_ready_timeout_seconds`.
            auto_quarantine: When ``True`` (default), quarantine an identified
                corrupt collection and retry; when ``False``, fail on the first
                non-ready exit without touching the store.

        Raises:
            RuntimeError: If the server does not become ready and no corrupt
                collection can be recovered (the child is terminated first).
        """
        if timeout is None:
            timeout = _ready_timeout_seconds()
        quarantined = 0
        while True:
            self.spawn()
            if self.wait_ready(timeout):
                return
            # Distinguish a dead child (a real load abort) from a still-alive one
            # (a readiness timeout on a healthy-but-slow store). Only a dead child
            # is evidence of a corrupt collection; quarantining on a timeout would
            # kill a healthily-loading child and drop a healthy index; a
            # timeout is never evidence of corruption. Capture liveness before
            # stop().
            child_died = not self.is_alive()
            # Stop joins the output-drain thread, so the panic tail is fully
            # captured here; reading it before stop() can race the final line.
            if not self.stop():
                raise RuntimeError(
                    "qdrant failed to stop after an unsuccessful readiness probe; "
                    "refusing recovery while the prior child or log writer survives"
                )
            tail = self.recent_output_tail()
            culprit = (
                _corrupt_collection_from_output(tail, self.storage_dir)
                if (
                    auto_quarantine
                    and child_died
                    and quarantined < _MAX_QUARANTINES_PER_START
                )
                else None
            )
            if culprit is None:
                cause = (
                    f" Last child output:\n{tail}"
                    if tail.strip()
                    else " The child produced no output before exiting."
                )
                raise RuntimeError(
                    f"qdrant server on port {self.http_port} failed to become "
                    f"ready within {timeout:.0f}s; see {self.log_path}.{cause}"
                )
            try:
                dest = _quarantine_collection(self.storage_dir, culprit)
            except OSError as exc:
                raise RuntimeError(
                    f"qdrant could not load collection {culprit!r} and quarantining "
                    f"it failed ({exc}); see {self.log_path}. Stop the server and "
                    f"run `vaultspec-rag server qdrant quarantine {culprit}`."
                ) from exc
            quarantined += 1
            logger.warning(
                "qdrant failed to load collection %r; quarantined it to %s and "
                "retrying start (%d/%d). That root re-indexes on its next touch.",
                culprit,
                dest,
                quarantined,
                _MAX_QUARANTINES_PER_START,
            )

    def restart(self, timeout: float | None = None) -> bool:
        """One supervised restart attempt; increments the counter.

        Args:
            timeout: Seconds to wait for readiness; ``None`` resolves the
                env-overridable default via :func:`_ready_timeout_seconds`.

        Returns:
            True when the restarted child reports ready.
        """
        if timeout is None:
            timeout = _ready_timeout_seconds()
        self.restart_count += 1
        if not self.stop():
            logger.error(
                "qdrant restart refused: prior child or output drain did not converge"
            )
            return False
        try:
            self.spawn()
        except (OSError, RuntimeError):
            logger.exception("qdrant restart spawn failed")
            return False
        ready = self.wait_ready(timeout)
        if ready:
            from ._constants import QDRANT_SERVER_VERSION
            from ._resolve import write_qdrant_identity

            try:
                write_qdrant_identity(
                    storage_path=str(self.storage_dir),
                    version=self.server_version() or QDRANT_SERVER_VERSION,
                    owner_pid=os.getpid(),
                    http_port=self.http_port,
                    qdrant_pid=self.pid or 0,
                )
            except Exception:
                logger.exception("qdrant restart identity publication failed")
                if not self.stop():
                    logger.error(
                        "qdrant identity publication failed and child teardown "
                        "did not converge"
                    )
                return False
        return ready

    def mark_attached(self) -> None:
        """Mark this supervisor as attached to an externally-owned managed server.

        Used when a healthy managed Qdrant is already serving the port: this
        supervisor reuses it without spawning a child and must not terminate it.
        """
        self._attached = True

    def is_alive(self) -> bool:
        """True while the managed server is running.

        In attached mode there is no owned child, so liveness is the readiness
        of the server this supervisor points at.
        """
        if self._attached:
            return self._ready_probe()
        return self._proc is not None and self._proc.poll() is None

    def stop(self, timeout: float = _STOP_TIMEOUT_SECONDS) -> bool:
        """Terminate the child and report confirmed child and drain convergence.

        Idempotent; safe to call with no child running. A drain that does not
        reach EOF within the bounded join remains referenced so no replacement
        child can acquire a second rotating-log sink concurrently.
        """
        proc = self._proc
        child_stopped = proc is None or proc.poll() is not None
        if proc is not None and proc.poll() is None:
            from .._test_isolation import (
                enforce_pytest_managed_singleton_containment,
            )

            enforce_pytest_managed_singleton_containment(
                operation="stop a supervised managed Qdrant process",
                targets=(self.storage_dir,),
            )
            try:
                if sys.platform == "win32":
                    proc.terminate()
                else:
                    proc.send_signal(signal.SIGTERM)
            except OSError as exc:
                logger.debug("qdrant terminate signal failed: %s", exc)
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                logger.warning(
                    "qdrant pid=%d did not exit in %.0fs; killing",
                    proc.pid,
                    timeout,
                )
                proc.kill()
                try:
                    proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    logger.error("qdrant pid=%d survived kill", proc.pid)
            child_stopped = proc.poll() is not None
        # The child's exit closes the output pipe, so the drain thread sees EOF
        # and finishes; join it (bounded) so the log handle is flushed/closed.
        drain_stopped = self._join_output_drain(timeout=_DRAIN_JOIN_TIMEOUT_SECONDS)
        if not drain_stopped:
            logger.warning(
                "qdrant output drain did not exit within %.0fs; retaining its "
                "single-writer guard",
                _DRAIN_JOIN_TIMEOUT_SECONDS,
            )
        if not child_stopped or not drain_stopped:
            return False
        if proc is not None:
            logger.info("qdrant child pid=%d stopped", proc.pid)
        self._proc = None
        return True

    def state(self) -> QdrantRuntimeState:
        """Service-domain snapshot for operability surfaces."""
        return QdrantRuntimeState(
            mode="server",
            url=self.url,
            pid=self.pid,
            alive=self.is_alive(),
            port=self.http_port,
            version=QDRANT_SERVER_VERSION,
            restarts=self.restart_count,
        )

    def server_version(self) -> str:
        """Read the running server's reported version from its root route.

        Returns:
            The version string, or ``""`` when unreachable.
        """
        try:
            with LOOPBACK_OPENER.open(self.url, timeout=2.0) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            return str(payload.get("version", ""))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            logger.debug("qdrant version probe failed: %s", exc)
            return ""


_PORT_RELEASE_TIMEOUT_SECONDS = 10.0
_PORT_RELEASE_SETTLE_SECONDS = 0.25


def _port_is_listening(http_port: int, *, timeout: float = 0.25) -> bool:
    """Return whether something accepts a loopback TCP connection on *http_port*.

    A connection refused (or any connect error) means nothing is listening - the
    port is free. Used after an orphan reap to wait for the prior child's
    listening socket to be fully released before a fresh bind.
    """
    import socket

    try:
        with socket.create_connection(("127.0.0.1", http_port), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_for_port_release(
    http_port: int,
    *,
    timeout: float = _PORT_RELEASE_TIMEOUT_SECONDS,
) -> bool:
    """Poll until *http_port* stops listening, then settle; report success.

    Closes the reap-to-spawn bind race: a just-reaped child's socket lingers in
    a closing state for a moment, and spawning into that window loses the bind.
    Returns ``True`` once the port is observed free (with a short settle so the
    storage lock handle is released too), or ``False`` on timeout so the caller
    fails with a named cause rather than spawning a doomed child.
    """
    deadline = time.monotonic() + timeout
    delay = 0.05
    while time.monotonic() < deadline:
        if not _port_is_listening(http_port):
            # The port is free; settle briefly so the OS also releases the
            # storage-lock handle the prior child held before we open it.
            time.sleep(_PORT_RELEASE_SETTLE_SECONDS)
            return not _port_is_listening(http_port)
        time.sleep(delay)
        delay = min(delay * 2, 1.0)
    return False


def _reap_orphan_before_spawn(
    qport: int,
    identity: QdrantIdentity | None,
    reason: str,
    *,
    budget: float = _REAP_BUDGET_DEFAULT_SECONDS,
) -> None:
    """Reap a provably-dead managed qdrant orphan, then wait for port release.

    Called only when the decision layer classified a managed orphan (recorded
    owner dead, child still holding the port). Confirms the recorded child pid
    is still a qdrant process before the hard kill (a recycled pid must never be
    killed), reaps it, then polls for the port to free so the fresh child cannot
    lose a reap-to-spawn bind race. Raises with a named, actionable cause at each
    failure rather than spawning a doomed competitor.

    Every witness inspection is bounded by ``budget`` as one whole-operation
    deadline rather than a per-call timeout. These inspections are local but not
    instantaneous - on Windows the image check shells out to ``tasklist``, which
    can block for a long time on a loaded or filter-driver-wedged host - and
    this runs inside daemon startup while the machine singleton lock is held, so
    an unbounded inspection wedges the daemon in ``warming`` with no way out.
    """
    from ._resolve import (
        pid_image_is_qdrant,
        pid_listens_on_loopback_port,
        pid_matches_start_time,
        probe_qdrant_endpoint,
        reap_qdrant_orphan,
    )

    if identity is None:
        raise RuntimeError(
            f"qdrant orphan on port {qport} has no managed identity; refusing to signal"
        )
    target = identity.qdrant_pid
    child_start_time = identity.qdrant_start_time
    logger.warning("Reaping managed qdrant orphan on port %d: %s", qport, reason)
    from ._resolve import owner_pid_witness_state

    deadline = time.monotonic() + max(0.0, budget)

    def remaining(stage: str) -> float:
        """Time left for ``stage``, or a named failure when the budget is spent."""
        left = deadline - time.monotonic()
        if left <= 0.0:
            raise RuntimeError(
                f"qdrant orphan on port {qport}: the {budget:.1f}s reap budget "
                f"expired during {stage}; refusing to signal the managed child "
                "on unproven witnesses. Stop the holder manually, then retry; "
                "or run local-only: vaultspec-rag server start --local-only"
            )
        return left

    owner_state = owner_pid_witness_state(
        identity, timeout=remaining("the owner-death witness")
    )
    if owner_state not in {"dead", "replaced"}:
        raise RuntimeError(
            f"qdrant orphan on port {qport}: recorded owner pid "
            f"{identity.owner_pid} is {owner_state}; refusing to signal the "
            "managed child until owner death is proven"
        )
    if child_start_time <= 0.0 or not pid_matches_start_time(
        target,
        child_start_time,
        timeout=remaining("the child process-start witness"),
    ):
        raise RuntimeError(
            f"qdrant orphan on port {qport}: recorded child pid {target} has "
            "no matching process-start witness; refusing to signal a reusable "
            "pid. Stop the holder manually, then retry; or run local-only: "
            "vaultspec-rag server start --local-only"
        )
    from ..config import get_config

    expected_storage = Path(str(get_config().qdrant_storage_dir)).expanduser().resolve()
    recorded_storage = Path(identity.storage_path).expanduser().resolve()
    live_probe = probe_qdrant_endpoint(qport, timeout=remaining("the endpoint probe"))
    if (
        recorded_storage != expected_storage
        or identity.version != QDRANT_SERVER_VERSION
        or identity.http_port != qport
        or not pid_listens_on_loopback_port(
            target, qport, timeout=remaining("the loopback listener witness")
        )
        or not live_probe.ready
        or live_probe.version != QDRANT_SERVER_VERSION
    ):
        raise RuntimeError(
            f"qdrant orphan on port {qport} failed the complete managed "
            "storage/version/listener witness; refusing to signal it"
        )
    # Confirm the recorded child pid is still a qdrant process before the hard
    # kill: the pid came from a dead owner's record and may have been recycled by
    # an unrelated process, which must never be killed.
    if target <= 0 or not pid_image_is_qdrant(
        target, timeout=remaining("the child image witness")
    ):
        raise RuntimeError(
            f"qdrant orphan on port {qport}: recorded child pid {target} is "
            "not a live qdrant process (likely a dead/recycled pid); refusing "
            "to kill it. Stop the holder manually, then retry; or run "
            "local-only: vaultspec-rag server start --local-only"
        )
    if not reap_qdrant_orphan(
        target,
        expected_start_time=child_start_time,
        wait_seconds=remaining("the child reap"),
    ):
        raise RuntimeError(
            f"qdrant orphan holding port {qport} could not be reaped "
            f"(child pid {target}); stop it manually, then retry; or run "
            "local-only: vaultspec-rag server start --local-only"
        )
    # A reaped process can outlive its own exit by a moment at the OS level: its
    # listening socket lingers in TIME_WAIT/CLOSING and its storage lock handle
    # is released asynchronously. Spawning into that window loses a bind race -
    # the fresh child fails to bind the port or open the single-writer storage
    # and dies. Poll for the port to go quiet before spawning so the
    # reap-to-spawn handoff is deterministic, not racy.
    if not _wait_for_port_release(qport):
        raise RuntimeError(
            f"qdrant orphan on port {qport} was reaped but the port did not "
            "free in time; the prior child's socket or storage handle is "
            "still held. Retry shortly; or run local-only: "
            "vaultspec-rag server start --local-only"
        )
    logger.info("Reaped qdrant orphan pid %d; proceeding to spawn", target)


def start_supervised_from_config() -> QdrantSupervisor:
    """Resolve, verify, spawn, and ready-wait the qdrant child per config.

    Resolution follows the env-var > provisioned > PATH order. A
    provisioned binary is re-hashed against its manifest digest before
    execution so a tampered managed dir never runs. The started
    supervisor is installed as the process-wide active supervisor.

    Returns:
        The running, ready supervisor.

    Raises:
        RuntimeError: When no binary is resolvable (the message names
            the exact install command), when the provisioned binary
            fails its pre-execution hash check, or when the server
            does not become ready.
    """
    from pathlib import Path

    from ..config import get_config
    from ._provision import file_sha256
    from ._resolve import (
        decide_qdrant_action,
        probe_qdrant_endpoint,
        read_qdrant_identity,
        resolve_binary,
        write_qdrant_identity,
    )

    cfg = get_config()
    qport = int(cfg.qdrant_port)
    storage_dir = Path(str(cfg.qdrant_storage_dir)).expanduser()
    log_path = Path(str(cfg.status_dir)).expanduser() / "qdrant.log"
    log_max_bytes = int(cfg.managed_log_max_bytes)
    log_backup_count = int(cfg.managed_log_backup_count)

    # Decide before spawning. A healthy, owned, capable managed server is
    # attached (never re-spawned onto its single-writer storage); a foreign or
    # unverifiable holder, or a managed orphan, is refused fast with a named
    # cause instead of a competing child and an opaque timeout.
    probe = probe_qdrant_endpoint(qport)
    identity = read_qdrant_identity()
    action, reason = decide_qdrant_action(
        probe,
        identity,
        expected_port=qport,
        expected_version=QDRANT_SERVER_VERSION,
        expected_storage=str(storage_dir),
    )
    if action == "attach":
        logger.info(
            "Attaching to the running managed qdrant on port %d: %s", qport, reason
        )
        supervisor = QdrantSupervisor(
            Path("attached-qdrant"),
            http_port=qport,
            storage_dir=storage_dir,
            log_path=log_path,
            log_max_bytes=log_max_bytes,
            log_backup_count=log_backup_count,
        )
        supervisor.mark_attached()
        set_active_supervisor(supervisor)
        return supervisor
    if action == "refuse":
        raise RuntimeError(
            f"refusing to start qdrant on port {qport}: {reason}. Stop or fix "
            "the process holding the port, then retry; or run local-only: "
            "vaultspec-rag server start --local-only"
        )
    if action == "reap_then_spawn":
        _reap_orphan_before_spawn(qport, identity, reason)
        # fall through to the spawn path below.

    # action in ("spawn", "reap_then_spawn" after a successful reap): resolve
    # the binary and start a fresh managed child.
    resolved = resolve_binary()
    if resolved is None:
        raise RuntimeError(
            "qdrant server mode is enabled but no server binary is "
            "available. Run: vaultspec-rag server qdrant install. "
            "Local-only option: vaultspec-rag server start --local-only"
        )
    if resolved.source == "provisioned" and resolved.sha256:
        actual = file_sha256(resolved.path)
        if actual.lower() != resolved.sha256.lower():
            raise RuntimeError(
                f"Provisioned qdrant binary at {resolved.path} does not "
                "match its manifest digest; refusing to execute. Re-run: "
                "vaultspec-rag server qdrant install --upgrade"
            )
    elif resolved.source in ("env", "path"):
        # An env-var or PATH binary carries no pinned digest, so it runs
        # UNVERIFIED. Make the bypass loud (it is otherwise silent), and call
        # out when it is shadowing a verified provisioned install - the case a
        # PATH/env plant would exploit.
        from ..config import EnvVar
        from ._resolve import has_provisioned_binary

        shadowed = has_provisioned_binary(QDRANT_SERVER_VERSION)
        remedy = (
            f"It is SHADOWING a verified provisioned install; unset "
            f"{EnvVar.QDRANT_BINARY.value} or remove qdrant from PATH to run the "
            "pinned binary."
            if shadowed
            else "Provision a pinned binary with: vaultspec-rag server qdrant install."
        )
        logger.warning(
            "qdrant binary resolved from %s (%s) runs UNVERIFIED - no "
            "pinned-digest check applies to this source. %s",
            resolved.source,
            resolved.path,
            remedy,
        )

    supervisor = QdrantSupervisor(
        resolved.path,
        http_port=qport,
        storage_dir=storage_dir,
        log_path=log_path,
        log_max_bytes=log_max_bytes,
        log_backup_count=log_backup_count,
    )
    logger.info("Starting qdrant server (%s binary %s)", resolved.source, resolved.path)
    try:
        supervisor.start()
    except RuntimeError as exc:
        raise RuntimeError(
            f"{exc}. The qdrant server backing the default server mode "
            "could not start; inspect the log above, then re-run, or fall "
            "back to local mode: vaultspec-rag server start --local-only"
        ) from exc
    set_active_supervisor(supervisor)
    # Record the managed-Qdrant identity now that it is ready, so a later start
    # can verify ownership and learn this owner pid to classify orphans.
    write_qdrant_identity(
        storage_path=str(storage_dir),
        version=supervisor.server_version() or QDRANT_SERVER_VERSION,
        owner_pid=os.getpid(),
        http_port=qport,
        qdrant_pid=supervisor.pid or 0,
    )
    return supervisor


# The daemon's active supervisor. Reassigned by the service lifespan;
# read by the health handler, the heartbeat loop, and the
# service-state surface so every adapter reports the same qdrant
# state (service domain owns operability).
_active_supervisor: QdrantSupervisor | None = None


def set_active_supervisor(supervisor: QdrantSupervisor | None) -> None:
    """Install (or clear) the process-wide active supervisor."""
    global _active_supervisor
    _active_supervisor = supervisor


def active_supervisor() -> QdrantSupervisor | None:
    """Return the process-wide active supervisor, if any."""
    return _active_supervisor


def runtime_state() -> QdrantRuntimeState:
    """Snapshot the qdrant runtime for the current process.

    A process supervising a child reports ``server`` mode with live
    child telemetry; a process pointed at an external server via the
    URL knob reports ``remote``; everything else is ``local``.
    """
    supervisor = _active_supervisor
    if supervisor is not None:
        return supervisor.state()

    from ..config import get_config

    cfg = get_config()
    url = str(cfg.qdrant_url or "")
    if url:
        return QdrantRuntimeState(mode="remote", url=url)
    return QdrantRuntimeState(mode="local")
