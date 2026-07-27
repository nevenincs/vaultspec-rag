"""Shared setup for tests that restore jobs a dead daemon left behind."""

from __future__ import annotations

import subprocess
import sys

_RECORD_JOB_AND_EXIT = """
import sys

from ..job_models import JobSource
from ..jobs import record_finish, record_start

job_id = record_start(JobSource.CODE, "tool", command="reindex_codebase")
if "finish" in sys.argv:
    record_finish(job_id, result="ok")
print(job_id)
"""


def job_recorded_by_a_now_dead_process(*, finished: bool = False) -> str:
    """Record a job in a real process, let it die, and return the job id.

    The persisted running-jobs snapshot is one machine-wide path, and each
    entry records the pid that owns the run, so restore adopts an entry only
    once its owner is gone: a job this test process started is not abandoned
    work, it is work still running here. Losing the in-memory ring therefore
    simulates nothing on its own - only a process that recorded a job and
    then exited leaves behind the state a restart has to recover.

    ``finished`` runs the job to completion before the process exits, which is
    what makes a zero restore count meaningful: with the owning process still
    alive, nothing is adoptable whether or not the finish cleared the entry.

    The child inherits the isolated status dir from the environment, so
    production code writes the snapshot the caller then restores from.
    """
    argv = [sys.executable, "-c", _RECORD_JOB_AND_EXIT]
    if finished:
        argv.append("finish")
    completed = subprocess.run(argv, capture_output=True, text=True, check=True)
    # Anything the import chain logs lands on stderr; the id is the last thing
    # written to stdout.
    return completed.stdout.strip().splitlines()[-1].strip()
