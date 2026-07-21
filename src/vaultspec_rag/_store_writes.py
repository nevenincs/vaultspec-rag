"""Write-path hardening for the vector store.

The 2026-07-21 incident: a full disk made the managed Qdrant server refuse
(or stall) every upsert while the indexer kept encoding batches at 100% GPU
with the job frozen at ``completed=0`` and no error ever recorded. The write
path had no error classification, no retry ceiling, no disk headroom check,
and the server-mode client had no request timeout, so a stalled socket
blocked forever.

This module owns the store-domain pieces: classifying a write failure as
unrecoverable (storage exhaustion - retrying cannot help) versus transient,
running a write under a bounded retry with backoff, and checking free-disk
headroom so a bulk index fails fast before burning GPU on vectors that can
never be persisted. Torch-free and CLI-free by design (the maintenance
import graph reaches the store).
"""

from __future__ import annotations

import errno
import logging
import time
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable

logger = logging.getLogger(__name__)

__all__ = [
    "BYTES_PER_POINT_ESTIMATE",
    "DISK_FLOOR_BYTES",
    "InsufficientDiskSpaceError",
    "classify_write_error",
    "ensure_disk_headroom",
    "run_write_with_retry",
]

#: Failure-text markers of storage exhaustion. Matched case-insensitively
#: against the exception chain: the managed server surfaces disk-full as an
#: HTTP 500 whose body carries "No space left on device: WAL buffer size
#: exceeds available disk space" (observed verbatim in the incident log).
_UNRECOVERABLE_MARKERS = (
    "no space left on device",
    "wal buffer size exceeds",
)

_WRITE_ATTEMPTS = 5
_BASE_DELAY_S = 0.5
_MAX_DELAY_S = 8.0

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


def run_write_with_retry[T](
    op: Callable[[], T],
    *,
    description: str,
    attempts: int = _WRITE_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run a store write under a bounded retry with exponential backoff.

    An unrecoverable failure (storage exhaustion) raises immediately - a
    full disk does not drain, and every retried batch only burns more GPU
    time upstream. A transient failure is retried up to ``attempts`` times
    with capped exponential backoff, then raised, so a dead server can
    never wedge a job silently. The original exception always propagates
    unchanged, preserving the server's error text for the job record and
    the CLI's friendly disk-full mapping.
    """
    delay = _BASE_DELAY_S
    for attempt in range(1, attempts + 1):
        try:
            return op()
        except Exception as exc:
            if classify_write_error(exc) == "unrecoverable":
                logger.error(
                    "unrecoverable store write failure in %s: %s", description, exc
                )
                raise
            if attempt == attempts:
                logger.error(
                    "store write %s failed after %d attempts: %s",
                    description,
                    attempts,
                    exc,
                )
                raise
            logger.warning(
                "transient store write failure in %s (attempt %d/%d), "
                "retrying in %.1fs: %s",
                description,
                attempt,
                attempts,
                delay,
                exc,
            )
            sleep(delay)
            delay = min(delay * 2.0, _MAX_DELAY_S)
    msg = "unreachable: retry loop must return or raise"  # pragma: no cover
    raise AssertionError(msg)  # pragma: no cover


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
