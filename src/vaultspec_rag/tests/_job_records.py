"""One live-activity-record editor for the whole test suite.

Every test that needs an activity record no verb can produce - a progress stamp
older than the five-minute stall threshold, a start stamp older than a `since`
window - reaches the record through here, so the suite has one definition of
that edit instead of one per module.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator


@contextmanager
def activity_record(record_id: str) -> Generator[dict[str, object]]:
    """Yield one live activity record for in-place edit, under the jobs lock.

    The records these tests need cannot be produced by waiting: the stall
    threshold is five minutes, and no verb backdates a timestamp or writes a
    stamp the daemon did not produce. Only the edited field moves - the record
    is the one ``record_start``/``record_progress`` built, and every code path
    that reads it stays real.
    """
    from .. import jobs

    with jobs._lock:
        for record in jobs._records:
            if record["id"] == record_id:
                yield record
                return
    raise AssertionError(f"no activity record with id {record_id}")
