"""In-flight activity registry for index/reindex jobs (#142, plan P01).

Delegates to the backend jobs module to avoid duplicate state and layering issues.
"""

from __future__ import annotations

from ..jobs import (
    MAX_RECORDS,
    JobProgressReporter,
    record_finish,
    record_progress,
    record_start,
    reset,
    snapshot,
)

__all__ = [
    "MAX_RECORDS",
    "JobProgressReporter",
    "record_finish",
    "record_progress",
    "record_start",
    "reset",
    "snapshot",
]
