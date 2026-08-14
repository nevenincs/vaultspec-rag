"""The in-memory activity ring, its lock, and the snapshot that outlives it.

The registry's state has its own module because several modules mutate it -
progress sampling, finish accounting, the registry surface itself - and a
shared mutable structure reached from three places belongs below all of them
rather than inside whichever one happens to be largest.

Nothing here decides policy. It owns the ring, the lock taken around it, and
the best-effort snapshot that lets a restart report interrupted jobs instead
of losing them.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import TYPE_CHECKING, cast

from .config._settings import managed_status_dir
from .job_manager.models import MAX_RECORDS

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "_active_snapshot_path",
    "_lock",
    "_persist_active_snapshot",
    "_records",
    "logger",
]

#: Named for the registry surface rather than for this module. The logger
#: name is what an operator greps and what log filters are written against,
#: so it names the subject - job activity - and does not follow a file
#: split that subject was never party to.
logger = logging.getLogger("vaultspec_rag.jobs")

_ACTIVE_SNAPSHOT_FILENAME = "jobs-active.json"

_lock = threading.Lock()
_records: deque[dict[str, object]] = deque(maxlen=MAX_RECORDS)


def _active_snapshot_path() -> Path:
    """Resolve the active-jobs snapshot path from the managed status dir."""

    return managed_status_dir() / _ACTIVE_SNAPSHOT_FILENAME


def _persist_active_snapshot() -> None:
    """Write the currently-running jobs to the status dir, atomically.

    Best-effort durability for the in-memory ring: if this daemon dies,
    the next startup reads the file and surfaces the jobs as
    ``interrupted`` instead of letting them vanish. Never raises - jobs
    bookkeeping must not fail a job.
    """

    from ._atomic_write import JsonWriteOptions, write_json_atomically

    with _lock:
        active = [
            {
                "id": record.get("id"),
                "source": record.get("source"),
                "trigger": record.get("trigger"),
                "started_at": record.get("started_at"),
                # Which process owns the run. The snapshot path is shared by
                # every process on the machine, so the reader needs this to
                # tell a job its own prior life abandoned from one still
                # running under somebody else.
                "pid": cast("dict[str, object]", runtime).get("pid")
                if isinstance(runtime := record.get("runtime"), dict)
                else None,
                "progress": dict(cast("dict[str, object]", progress))
                if isinstance(progress := record.get("progress"), dict)
                else None,
                "initiator": dict(cast("dict[str, object]", initiator))
                if isinstance(initiator := record.get("initiator"), dict)
                else None,
            }
            for record in _records
            if record.get("phase") == "running"
        ]
    try:
        write_json_atomically(
            _active_snapshot_path(),
            {"active": active},
            JsonWriteOptions(durable=True),
        )
    except OSError:
        logger.debug("could not persist active-jobs snapshot", exc_info=True)
