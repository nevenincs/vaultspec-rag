"""A real child process holding the machine lock with an unreadable record.

The lock's own writer publishes its owner pid with a read-back verification,
so a healthy build never leaves the record unreadable. The state still exists
in the field - an interrupted foreign writer, a body scrubbed on disk - and it
is the one observation where the OS lock answers held while no pid can be
named. This helper constructs that state for real: a separate interpreter
claims the configured machine lock and publishes a body that is not JSON,
holding both until told to stop.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_STARTUP_TIMEOUT_SECONDS = 10.0

_UNNAMED_HOLDER_SRC = """
import os
import sys
import time
from pathlib import Path

from vaultspec_rag._anchor_claim import claim_anchor
from vaultspec_rag._machine_lock import machine_lock_path

ready = Path(sys.argv[1])
stop = Path(sys.argv[2])
claim = claim_anchor(machine_lock_path(), pid_record=True, create_parent=True)
assert claim.descriptor is not None, claim
# A body no writer will ever turn into an owner record.
os.lseek(claim.descriptor, 0, os.SEEK_SET)
os.write(claim.descriptor, b"retired anchor")
os.fsync(claim.descriptor)
ready.write_text(str(os.getpid()), encoding="ascii")
while not stop.exists():
    time.sleep(0.01)
"""


@contextlib.contextmanager
def unnamed_machine_lock_holder(control_dir: Path) -> Generator[int]:
    """Hold the configured machine lock with an unreadable owner record.

    The child inherits this process's environment, so the configured (and in
    tests, isolated) machine lock path is the one it claims. Yields the
    child's pid; the OS lock stays held until the context exits.
    """
    ready = control_dir / "unnamed-holder-ready"
    stop = control_dir / "unnamed-holder-stop"
    process = subprocess.Popen(
        [sys.executable, "-c", _UNNAMED_HOLDER_SRC, str(ready), str(stop)],
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        # The readiness file appears before its contents land, so poll for a
        # parseable pid rather than for the path.
        holder_pid = 0
        deadline = time.monotonic() + _STARTUP_TIMEOUT_SECONDS
        while holder_pid == 0 and process.poll() is None:
            assert time.monotonic() < deadline, "unnamed lock holder did not start"
            with contextlib.suppress(OSError, ValueError):
                holder_pid = int(ready.read_text(encoding="ascii"))
            if holder_pid == 0:
                time.sleep(0.01)
        assert holder_pid > 0, "unnamed lock holder exited before readiness"
        yield holder_pid
    finally:
        if process.poll() is None:
            stop.write_text("stop", encoding="ascii")
        try:
            process.wait(timeout=_STARTUP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=_STARTUP_TIMEOUT_SECONDS)
        assert process.stderr is not None
        stderr = process.stderr.read()
        process.stderr.close()
        assert process.returncode == 0, stderr
