"""One provisioning run in a process of its own, for a parent that kills it.

What a hard kill leaves on disk can only be learned by killing a process: an
exception raised in the test's own process still runs every ``finally`` on
its way out, and a killed process runs none. So the run happens here, in a
child, and the parent ends it from outside.

The run is the shipped ``provision()``, start to finish. It reads its managed
directory and its release source from the environment as any run does. It is
held to a stand-in release, pinned here as the parent pinned it, because a
pin lives in one process's memory and the parent's does not reach this one.
The only other thing added is where the run stops: when it reports the stage
named on the command line, the progress sink says so on standard output and
then waits, so the parent can end the process at exactly that point.

Run as ``python -P -m vaultspec_rag.tests._provisioning_child <stage>``.
"""

from __future__ import annotations

import os
import sys
import threading

from ..qdrant_runtime._provision import provision
from ._stand_in_release import pinned_stand_in

#: What the child prints, followed by its own process id, once the run has
#: reached the stage it stops at. The id is the interpreter's: where the
#: interpreter is started through a launcher, the parent knows only the
#: launcher's.
REACHED = "reached the stage"


def main(stop_at: str) -> None:
    def stop_at_the_stage(line: str) -> None:
        if line.startswith(stop_at):
            print(REACHED, os.getpid(), flush=True)
            # Until the parent ends this process. Nothing wakes it.
            threading.Event().wait()

    with pinned_stand_in():
        report = provision(on_progress=stop_at_the_stage)
    # Reached only when the stage was never reported; the parent reads this
    # as the run having finished instead of stopping.
    print(f"finished: {report.action} {report.message}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
