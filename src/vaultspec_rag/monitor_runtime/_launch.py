"""Everything between a resolved monitor and a process running it.

Resolution says which file would run and what it is held to. This module is
the only place that file is checked before a process is created from it, and
it checks it while holding it, so the file that was hashed is the file that
runs. A digest that is missing or empty is a mismatch like any other, because
no file hashes to it: there is no branch on which a monitor runs unhashed.

The hold is what ties the two together, as tightly as each platform allows;
``vaultspec_rag.native_binary._hold`` states how tightly that is. Once the
process exists it is asked again whether the file it was created from is
still the verified one, and a process created from anything else is killed
before it can serve a page.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from ..native_binary._hold import held_executable
from ._resolve import (
    MONITOR_BINARY_BUSY,
    MONITOR_BINARY_UNVERIFIED,
    MonitorBinaryError,
    MonitorSource,
    operator_monitor_fault,
)

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Generator

    from ..native_binary._hold import HeldExecutable
    from ._resolve import ResolvedMonitor

__all__ = ["confirm_launch", "verified_monitor", "verify_monitor"]


def _refused(monitor: ResolvedMonitor, problem: str) -> MonitorBinaryError:
    """Build the refusal for a monitor that failed its check.

    An operator monitor's refusal names the settings that chose it, because
    an operator set them. This release's own monitor carries no instruction:
    the next start obtains and verifies it again.
    """
    if monitor.source is MonitorSource.OPERATOR_SETTING:
        # Function-local: this module is reached by the daemon, which has no
        # reason to load the settings vocabulary until a refusal needs it.
        from ..config._types import EnvVar

        remedy = (
            f"Correct {EnvVar.MONITOR_BINARY.value} or "
            f"{EnvVar.MONITOR_BINARY_SHA256.value}, or unset both to use the "
            "monitor this release provides."
        )
    else:
        remedy = "The next start obtains and verifies it again."
    return MonitorBinaryError(
        MONITOR_BINARY_UNVERIFIED,
        f"The monitor at {monitor.path} {problem}; refusing to run it. {remedy}",
    )


@contextmanager
def verified_monitor(monitor: ResolvedMonitor) -> Generator[HeldExecutable]:
    """Hold *monitor* open, proven to be what its source holds it to.

    The file stays held for the whole block, so a process created inside it
    is created from the file that was checked.

    Raises:
        MonitorError: When the monitor may not run.
    """
    if monitor.source is MonitorSource.OPERATOR_SETTING:
        fault = operator_monitor_fault(monitor.path)
        if fault is not None:
            raise _refused(monitor, fault)
    try:
        with held_executable(monitor.path) as held:
            if held.sha256() != monitor.sha256:
                raise _refused(
                    monitor, "does not match the digest it is admitted under"
                )
            yield held
    except OSError as exc:
        raise MonitorBinaryError(
            MONITOR_BINARY_BUSY,
            f"The monitor at {monitor.path} cannot be read ({exc}), so it "
            "cannot be checked. Another program may be holding it open, or "
            "this user may not be permitted to read it.",
        ) from exc


def verify_monitor(monitor: ResolvedMonitor) -> None:
    """Check *monitor* against what its source holds it to, or refuse it.

    The same check a launch makes, for a caller that wants the answer without
    a process. Passing it does not authorise a later launch; every launch
    checks again.

    Raises:
        MonitorError: When the monitor may not run.
    """
    with verified_monitor(monitor):
        pass


def confirm_launch(
    monitor: ResolvedMonitor,
    held: HeldExecutable,
    process: subprocess.Popen[str],
) -> None:
    """Say the process just created from *held* ran the verified file, or kill it.

    Called inside the block that holds the file, immediately after the
    process exists. Where the platform cannot hold a file still, this is what
    catches a replacement made in the window between the hash and the
    process; the process is killed before it can serve anything.

    Raises:
        MonitorError: When the file changed. The process is already gone.
    """
    if held.unchanged(monitor.sha256):
        return
    process.kill()
    process.wait()
    for stream in (process.stdin, process.stdout):
        if stream is not None:
            stream.close()
    raise _refused(monitor, "changed while it was being started")
