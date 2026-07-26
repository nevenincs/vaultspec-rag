"""Operation-path hardening for the vector store.

The 2026-07-21 incident: a full disk made the managed Qdrant server refuse
(or stall) every upsert while the indexer kept encoding batches at 100% GPU
with the job frozen at ``completed=0`` and no error ever recorded. The write
path had no error classification, no retry ceiling, no disk headroom check,
and the server-mode client had no request timeout, so a stalled socket
blocked forever.

This module owns the store-domain pieces: classifying a store failure as
unrecoverable (storage exhaustion - retrying cannot help) versus transient,
running a store operation under a bounded retry with backoff, and checking
free-disk headroom so a bulk index fails fast before burning GPU on vectors
that can never be persisted. Torch-free and CLI-free by design (the
maintenance import graph reaches the store).

The bounded retry covers every store operation, not only the write. A
managed vector-store backend can refuse connections for a window (a
restart, a corrupt-collection quarantine cycle, a runner outliving its
backend), and an index job reaches collection-ensure and read operations
before its first write. Leaving those single-shot turned a momentary
refusal into a hard job failure, so any operation safe to replay -
ensure, read, and idempotent delete - runs under the same bounded retry.
"""

from __future__ import annotations

import errno
import logging
import math
import pathlib
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

__all__ = [
    "BYTES_PER_POINT_ESTIMATE",
    "DISK_FLOOR_BYTES",
    "InsufficientDiskSpaceError",
    "StoreWritePolicy",
    "VolumeReading",
    "classify_write_error",
    "ensure_disk_headroom",
    "probe_store_volume",
    "probe_workspace_volume",
    "remaining_write_seconds",
    "run_store_operation_with_retry",
    "store_volume_path",
    "workspace_volume_path",
]

#: Failure-text markers of storage exhaustion. Matched case-insensitively
#: against the exception chain: the managed server surfaces disk-full as an
#: HTTP 500 whose body carries "No space left on device: WAL buffer size
#: exceeds available disk space" (observed verbatim in the incident log).
#: Conservative per-point on-disk budget for the bulk-index estimate: a
#: 1024-dim float32 dense vector (4 KiB) plus the sparse vector, payload,
#: HNSW index, and WAL overhead.
BYTES_PER_POINT_ESTIMATE = 16 * 1024

#: Minimum free bytes any index-time write target must retain. Qdrant needs
#: WAL and optimizer headroom (the incident showed optimizer failures
#: needing ~360 MiB with 0 B available); below this floor a write is refused
#: before Qdrant can wedge on it. The project data dir shares the number
#: rather than forking a second one: its run ledger and metadata are bounded
#: metadata, so this floor is generous there and the store's own
#: profile-scoped headroom would be absurd.
DISK_FLOOR_BYTES = 1 * 1024 * 1024 * 1024


class InsufficientDiskSpaceError(RuntimeError):
    """The store volume lacks headroom for the requested write or index."""


@dataclass(frozen=True, slots=True)
class StoreWritePolicy:
    """Limited capabilities supplied by the indexing run policy.

    The caller-owned indexing run policy owns the clock, durable-progress
    resets, and interruptible waiting. This value binds only the two
    capabilities the store may consume, keeping retry code independent of
    indexer lifecycle state and preventing it from advancing the clock.
    """

    remaining_seconds: Callable[[], float]
    wait: Callable[[float], None]


def classify_write_error(err: BaseException) -> Literal["unrecoverable", "transient"]:
    """Classify a store write failure; unrecoverable means retrying is futile.

    Walks the exception chain so a wrapped ``OSError`` (``ENOSPC``) or an
    HTTP-layer exception carrying the server's disk-full text is recognised
    at any depth. Everything else is transient (network blip, restart
    window, timeout) and eligible for a bounded retry.
    """
    from ._job_errors import DISK_FULL_MARKERS

    seen: set[int] = set()
    current: BaseException | None = err
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, OSError) and current.errno == errno.ENOSPC:
            return "unrecoverable"
        text = str(current).lower()
        # A full disk is the unrecoverable class for a write: retrying
        # cannot free space. The vocabulary is shared with the job
        # record's error_kind so both agree on what "full" looks like.
        if any(marker in text for marker in DISK_FULL_MARKERS):
            return "unrecoverable"
        current = current.__cause__ or current.__context__
    return "transient"


def run_store_operation_with_retry[T](
    op: Callable[[int], T],
    *,
    description: str,
    policy: StoreWritePolicy | None,
    max_elapsed_seconds: float | None = None,
) -> T:
    """Run a store operation under configured retry and a caller-owned budget.

    Any operation safe to replay may run under this: the upsert write, the
    collection-ensure existence check and index creation, the reads, and the
    idempotent point deletes. A backend that refuses connections for a
    window therefore costs a bounded wait rather than a failed job.

    An unrecoverable failure (storage exhaustion) raises immediately - a
    full disk does not drain, and every retried batch only burns more GPU
    time upstream. This holds for a read exactly as for a write. A transient
    failure consumes the configured attempt and capped exponential-backoff
    policy. ``policy`` is supplied by the run-policy layer: this
    store-domain helper neither starts nor resets the durable no-progress
    clock. It checks that budget before admitting every attempt and clamps
    every policy wait to the reported remainder. Direct callers outside a
    managed index run explicitly pass ``None``.

    The original operation exception propagates unchanged when storage is
    unrecoverable or the configured attempt count is exhausted. Exhausting
    the caller's durable no-progress budget instead raises the shared typed
    ``no_progress_timeout`` outcome, so a genuinely unreachable backend
    still terminates on the liveness contract rather than waiting forever.

    Args:
        op: One synchronous store operation attempt. The argument is the
            positive whole-second timeout admitted for that attempt;
            operations whose client call takes no timeout ignore it.
        description: Bounded operator context for diagnostics.
        policy: Caller-owned durable no-progress policy, or ``None`` for a
            direct store call outside a managed indexing run.
        max_elapsed_seconds: Optional ceiling on this operation's total wall
            clock across every attempt. Without it the attempt count is the
            only bound, so a backend that accepts the connection and then
            stalls costs the full per-attempt timeout once per attempt -
            multiplying, not capping, the pre-retry worst case. Callers that
            run many operations back to back under one lock supply this so a
            stalled backend cannot extend the hold proportionally.
    """
    from .config import get_config

    cfg = get_config()
    attempts = cfg.store_write_retry_attempts
    operation_timeout = cfg.store_operation_timeout_seconds
    delay = cfg.store_write_retry_base_seconds
    max_delay = cfg.store_write_retry_max_seconds
    started = time.monotonic()

    for attempt in range(1, attempts + 1):
        elapsed_left = _elapsed_left(max_elapsed_seconds, started)
        attempt_timeout = _attempt_timeout_seconds(
            operation_timeout,
            _tighter(
                remaining_write_seconds(policy, description=description),
                elapsed_left,
            ),
            description=description,
        )
        try:
            return op(attempt_timeout)
        except Exception as exc:
            if classify_write_error(exc) == "unrecoverable":
                logger.error(
                    "unrecoverable store operation failure in %s: %s", description, exc
                )
                raise

            remaining = remaining_write_seconds(policy, description=description)
            elapsed_left = _elapsed_left(max_elapsed_seconds, started)
            if (
                _terminal_reason(
                    attempt=attempt, attempts=attempts, elapsed_left=elapsed_left
                )
                is not None
            ):
                _log_give_up(
                    exc,
                    description=description,
                    attempt=attempt,
                    attempts=attempts,
                    elapsed_left=elapsed_left,
                    max_elapsed_seconds=max_elapsed_seconds,
                )
                raise

            wait_seconds = _retry_wait_seconds(delay, remaining, elapsed_left)
            logger.warning(
                "transient store operation failure in %s (attempt %d/%d), "
                "retrying in %.1fs: %s",
                description,
                attempt,
                attempts,
                wait_seconds,
                exc,
            )
            _wait_before_retry(
                wait_seconds=wait_seconds,
                policy=policy,
                failure=exc,
                description=description,
            )
            delay = min(delay * 2.0, max_delay)
    msg = "unreachable: retry loop must return or raise"  # pragma: no cover
    raise AssertionError(msg)  # pragma: no cover


def _wait_before_retry(
    *,
    wait_seconds: float,
    policy: StoreWritePolicy | None,
    failure: BaseException,
    description: str,
) -> None:
    """Back off before the next attempt, letting the failure outrank a cancel.

    The run policy's wait doubles as the cooperative control channel, so an
    operator pause or cancel that arrives while backing off is raised from
    inside it. Those signals derive from ``BaseException``, so they escape
    the retry's ``except Exception`` and would otherwise replace the store
    failure that caused the backoff - the attempt would be recorded as
    cancelled even though it genuinely failed. The failure is re-raised
    instead: the request stays pending and unacknowledged, and the worker
    observes it at its next checkpoint.

    A shutdown is deliberately NOT absorbed. It is not a verdict on the
    work but the process going away, and the attempt is classified as
    interrupted (and so resumable) rather than failed.
    """
    from .job_control import CancelRequested, PauseRequested

    try:
        if policy is None:
            time.sleep(wait_seconds)
        else:
            policy.wait(wait_seconds)
    except (PauseRequested, CancelRequested) as signal:
        logger.warning(
            "store operation %s already failed when %s arrived during "
            "backoff; reporting the failure and leaving the request "
            "pending: %s",
            description,
            type(signal).__name__,
            failure,
        )
        raise failure from signal


def _elapsed_left(max_elapsed_seconds: float | None, started: float) -> float | None:
    """Return the wall clock an operation has left, or ``None`` if uncapped."""
    if max_elapsed_seconds is None:
        return None
    return max_elapsed_seconds - (time.monotonic() - started)


def _tighter(value: float | None, ceiling: float | None) -> float | None:
    """Return the stricter of two optional budgets."""
    if ceiling is None:
        return value
    return ceiling if value is None else min(value, ceiling)


def _terminal_reason(
    *,
    attempt: int,
    attempts: int,
    elapsed_left: float | None,
) -> Literal["attempts", "budget"] | None:
    """Return why this failure ends the operation, or ``None`` to retry.

    A wall-clock ceiling ends the operation on the original error rather
    than a liveness outcome: an unmanaged read that spent its own
    allowance has not stalled a managed run.
    """
    if attempt >= attempts:
        return "attempts"
    if elapsed_left is not None and elapsed_left <= 0.0:
        return "budget"
    return None


def _log_give_up(
    exc: BaseException,
    *,
    description: str,
    attempt: int,
    attempts: int,
    elapsed_left: float | None,
    max_elapsed_seconds: float | None,
) -> None:
    """Record why a transient failure was not retried again."""
    if (
        _terminal_reason(attempt=attempt, attempts=attempts, elapsed_left=elapsed_left)
        == "attempts"
    ):
        logger.error(
            "store operation %s failed after %d attempts: %s",
            description,
            attempts,
            exc,
        )
        return
    logger.error(
        "store operation %s exhausted its %.1fs budget after %d attempt(s): %s",
        description,
        max_elapsed_seconds,
        attempt,
        exc,
    )


def _retry_wait_seconds(
    delay: float,
    remaining: float | None,
    elapsed_left: float | None,
) -> float:
    """Return the backoff wait clamped to whichever budgets are finite."""
    wait_seconds = delay if remaining is None else min(delay, remaining)
    if elapsed_left is not None:
        wait_seconds = min(wait_seconds, elapsed_left)
    return wait_seconds


def _attempt_timeout_seconds(
    configured_timeout: float,
    remaining: float | None,
    *,
    description: str,
) -> int:
    """Return a whole-second attempt timeout that cannot exceed the budget."""
    if remaining is None:
        return math.ceil(configured_timeout)

    timeout = math.floor(min(configured_timeout, remaining))
    if timeout >= 1:
        return timeout

    from ._job_errors import JobError, JobErrorKind

    raise JobError(
        JobErrorKind.NO_PROGRESS_TIMEOUT,
        "store write has less than one whole second of durable no-progress "
        f"budget remaining: {description}",
    )


def remaining_write_seconds(
    policy: StoreWritePolicy | None,
    *,
    description: str,
) -> float | None:
    """Return a finite remaining budget or raise its typed expiry outcome."""
    if policy is None:
        return None

    remaining = policy.remaining_seconds()
    if isinstance(remaining, bool) or not math.isfinite(remaining):
        msg = (
            "remaining durable no-progress budget must be a finite number, "
            f"got {remaining!r}"
        )
        raise ValueError(msg)
    if remaining > 0.0:
        return remaining

    from ._job_errors import JobError, JobErrorKind

    raise JobError(
        JobErrorKind.NO_PROGRESS_TIMEOUT,
        f"store write made no durable progress before its deadline: {description}",
    )


def _free_bytes(storage_path: pathlib.Path) -> int | None:
    """Best-effort free-space probe of the store volume, ``None`` if unknown.

    A missing path (e.g. a remote Qdrant server with no local managed
    storage dir) yields ``None`` so the caller skips the check rather than
    misjudging a volume this process cannot see.
    """
    import shutil

    try:
        return shutil.disk_usage(storage_path).free
    except OSError:
        return None


@dataclass(frozen=True, slots=True)
class VolumeReading:
    """One measured free-space observation of one write target's volume.

    An index writes to two independent locations that are routinely on
    different volumes: the vector store, and the project's own data dir
    (the run ledger and the index metadata). Each is measured separately so
    a refusal can name which one is short instead of collapsing both into a
    single figure.

    ``free_bytes`` is ``None`` when this process cannot see the volume - a
    remote Qdrant server, or a path whose whole ancestry is absent. Callers
    must treat that as "unknown" and skip their check rather than
    substitute another volume's number.
    """

    role: str
    path: pathlib.Path
    measured_path: pathlib.Path | None
    free_bytes: int | None
    #: Filesystem device id of ``measured_path`` - the volume serial on
    #: Windows, ``st_dev`` elsewhere. Captured at probe time so the record
    #: needs no further filesystem access, and so identity is decided by the
    #: device rather than by a rendered path: every POSIX absolute path
    #: shares the anchor ``/``, which would make unrelated volumes compare
    #: equal.
    device_id: int | None = None

    @property
    def volume(self) -> str:
        """The drive or mount root of the measured path, empty if unnamed."""
        target = self.measured_path or self.path
        drive = pathlib.Path(target).drive
        return drive or pathlib.Path(target).anchor

    def describe(self) -> str:
        """Render what was measured and where, for an operator-facing refusal.

        The role is named alongside the path because the operator's
        complaint is almost always about a DIFFERENT volume than the one
        that was short; without the role, a correct figure still reads as
        the tool contradicting what their file manager shows.
        """
        volume = self.volume
        suffix = f", volume {volume}" if volume else ""
        return f"{self.path} ({self.role}{suffix})"

    def same_volume_as(self, other: VolumeReading) -> bool:
        """Whether both readings landed on the same volume.

        Two unmeasured readings are never treated as the same volume:
        "unknown" is not an identity, and answering yes would silently
        collapse two independent checks into one.
        """
        return (
            self.device_id is not None
            and other.device_id is not None
            and self.device_id == other.device_id
        )


def store_volume_path(root: pathlib.Path) -> pathlib.Path:
    """Return the directory the vector store writes its data into.

    Mirrors the backend selection the store itself makes: the managed
    server's storage dir when the supervised backend is in effect, the
    per-project on-disk store otherwise. Resolving it without opening a
    store is what lets an admission preflight name the right volume before
    any mutable resource exists.
    """
    from .config import get_config

    cfg = get_config()
    if cfg.effective_server_mode():
        return pathlib.Path(str(cfg.qdrant_storage_dir)).expanduser()
    return pathlib.Path(root) / cfg.data_dir / cfg.qdrant_dir


def workspace_volume_path(root: pathlib.Path) -> pathlib.Path:
    """Return the project data dir an index writes its own bookkeeping into.

    The run ledger and the per-domain index metadata land here, on the
    volume holding the indexed tree. They are bounded metadata rather than
    vectors, so this target's requirement is the small shared write floor,
    never the store's profile-scoped headroom.
    """
    from .config import get_config

    return pathlib.Path(root) / get_config().data_dir


def _is_remote_store() -> bool:
    """Whether an operator pointed the store at a Qdrant this host cannot see."""
    from urllib.parse import urlsplit

    from .config import get_config

    url = str(get_config().qdrant_url or "")
    if not url:
        return False
    host = (urlsplit(url).hostname or "").lower()
    return host not in {"", "localhost", "127.0.0.1", "::1"}


def _read_volume(role: str, path: pathlib.Path) -> VolumeReading:
    """Measure *path*'s volume, walking up to its nearest existing ancestor.

    The target need not exist yet (a first index on a fresh install); an
    existing ancestor is on the same volume and answers the same question,
    where reporting "unknown" would disable the check needlessly.
    """
    for candidate in (path, *path.parents):
        if not candidate.exists():
            continue
        free = _free_bytes(candidate)
        if free is None:
            continue
        try:
            device_id = candidate.stat().st_dev
        except OSError:
            logger.debug("device probe failed for %s", candidate, exc_info=True)
            device_id = None
        return VolumeReading(
            role=role,
            path=path,
            measured_path=candidate,
            free_bytes=free,
            device_id=device_id,
        )
    return VolumeReading(role=role, path=path, measured_path=None, free_bytes=None)


def probe_store_volume(root: pathlib.Path) -> VolumeReading:
    """Measure free space on the volume the vector store actually writes to.

    A remote store is reported as unknown rather than measured against an
    unrelated local dir this host happens to be able to see.
    """
    path = store_volume_path(root)
    if _is_remote_store():
        return VolumeReading(
            role="vector store", path=path, measured_path=None, free_bytes=None
        )
    return _read_volume("vector store", path)


def probe_workspace_volume(root: pathlib.Path) -> VolumeReading:
    """Measure free space on the volume holding the project's own data dir."""
    return _read_volume("project data dir", workspace_volume_path(root))


def ensure_disk_headroom(
    storage_path: pathlib.Path,
    *,
    new_points: int = 0,
    floor_bytes: int = DISK_FLOOR_BYTES,
) -> None:
    """Refuse a write or bulk index the store volume cannot absorb.

    With ``new_points`` this is the bulk-index pre-flight: the estimated
    footprint plus the floor must fit in free space, so an impossible run
    fails in milliseconds instead of wedging at 1-2%% hours later. With the
    default ``new_points=0`` it is the cheap per-write floor check that
    converts gradual mid-run disk exhaustion into a loud, classified abort.

    Raises:
        InsufficientDiskSpaceError: When free space is below the requirement.
            The message is built from ``_job_errors.DISK_FULL_PHRASE`` so job
            records hit the CLI's friendly disk mapping; re-typing the
            phrasing here is what let the two drift apart before.
    """
    free = _free_bytes(storage_path)
    if free is None:
        return
    needed = floor_bytes + new_points * BYTES_PER_POINT_ESTIMATE
    if free >= needed:
        return
    from ._job_errors import DISK_FULL_PHRASE
    from ._units import human_bytes

    msg = (
        f"not enough free disk space for the vector store "
        f"({DISK_FULL_PHRASE} imminent): need ~{human_bytes(needed)} "
        f"({new_points} points), have {human_bytes(free)} free at "
        f"{storage_path}. Free disk space (see: vaultspec-rag server storage "
        f"survey) and retry."
    )
    raise InsufficientDiskSpaceError(msg)
