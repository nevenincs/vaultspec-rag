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
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable

logger = logging.getLogger(__name__)

__all__ = [
    "BYTES_PER_POINT_ESTIMATE",
    "DISK_FLOOR_BYTES",
    "InsufficientDiskSpaceError",
    "StoreWritePolicy",
    "classify_write_error",
    "ensure_disk_headroom",
    "remaining_write_seconds",
    "run_store_operation_with_retry",
]

#: Failure-text markers of storage exhaustion. Matched case-insensitively
#: against the exception chain: the managed server surfaces disk-full as an
#: HTTP 500 whose body carries "No space left on device: WAL buffer size
#: exceeds available disk space" (observed verbatim in the incident log).
_UNRECOVERABLE_MARKERS = (
    "no space left on device",
    "wal buffer size exceeds",
)

#: Conservative per-point on-disk budget for the bulk-index estimate: a
#: 1024-dim float32 dense vector (4 KiB) plus the sparse vector, payload,
#: HNSW index, and WAL overhead.
BYTES_PER_POINT_ESTIMATE = 16 * 1024

#: Minimum free bytes the store volume must retain for a write to proceed.
#: Qdrant needs WAL and optimizer headroom (the incident showed optimizer
#: failures needing ~360 MiB with 0 B available); below this floor a write
#: is refused before Qdrant can wedge on it.
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
    seen: set[int] = set()
    current: BaseException | None = err
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, OSError) and current.errno == errno.ENOSPC:
            return "unrecoverable"
        text = str(current).lower()
        if any(marker in text for marker in _UNRECOVERABLE_MARKERS):
            return "unrecoverable"
        current = current.__cause__ or current.__context__
    return "transient"


def run_store_operation_with_retry[T](
    op: Callable[[int], T],
    *,
    description: str,
    policy: StoreWritePolicy | None,
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
    """
    from .config import get_config

    cfg = get_config()
    attempts = cfg.store_write_retry_attempts
    operation_timeout = cfg.store_operation_timeout_seconds
    delay = cfg.store_write_retry_base_seconds
    max_delay = cfg.store_write_retry_max_seconds

    for attempt in range(1, attempts + 1):
        remaining = remaining_write_seconds(policy, description=description)
        attempt_timeout = _attempt_timeout_seconds(
            operation_timeout,
            remaining,
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

            remaining = remaining_write_seconds(
                policy,
                description=description,
            )
            if attempt == attempts:
                logger.error(
                    "store operation %s failed after %d attempts: %s",
                    description,
                    attempts,
                    exc,
                )
                raise
            wait_seconds = delay if remaining is None else min(delay, remaining)
            logger.warning(
                "transient store operation failure in %s (attempt %d/%d), "
                "retrying in %.1fs: %s",
                description,
                attempt,
                attempts,
                wait_seconds,
                exc,
            )
            if policy is None:
                time.sleep(wait_seconds)
            else:
                policy.wait(wait_seconds)
            delay = min(delay * 2.0, max_delay)
    msg = "unreachable: retry loop must return or raise"  # pragma: no cover
    raise AssertionError(msg)  # pragma: no cover


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
            The message carries the canonical "No space left on device"
            phrasing so job records hit the CLI's friendly disk mapping.
    """
    free = _free_bytes(storage_path)
    if free is None:
        return
    needed = floor_bytes + new_points * BYTES_PER_POINT_ESTIMATE
    if free >= needed:
        return
    gib = 1024.0**3
    msg = (
        f"not enough free disk space for the vector store (No space left on "
        f"device imminent): need ~{needed / gib:.1f} GiB "
        f"({new_points} points), have {free / gib:.1f} GiB free at "
        f"{storage_path}. Free disk space (see: vaultspec-rag server storage "
        f"survey) and retry."
    )
    raise InsufficientDiskSpaceError(msg)
