"""A cancelled Textual timer leaves no executor thread behind.

Textual stops a timer by cancelling its task and awaiting it; when that
awaiter is cancelled as well, as app and loop teardown do, the timer's sleep
is cancelled twice. On Windows Textual's own sleep then strands a thread in
an unbounded wait, and closing the event loop blocks for the five-minute
default-executor shutdown timeout.

The scenario runs in a fresh interpreter: a stranded pool thread is joined at
interpreter exit, so hosting it in the test runner would hang the session
instead of failing this test. The child reports and leaves with ``os._exit``.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

pytestmark = [pytest.mark.unit]

_CHILD_TIMEOUT_SECONDS = 120.0

_DOUBLE_CANCEL_SRC = """
import asyncio
import os
import threading

import vaultspec_rag.cli._jobs_tui  # noqa: F401  # absolute-import-ok
from textual.timer import Timer

JOIN_SECONDS = 10.0


class Target:
    pass


async def main() -> None:
    target = Target()
    for _ in range(20):
        # An interval no test outlives: only a cancelled sleep can return.
        timer = Timer(target, 3600.0, callback=lambda: None)
        timer._start()
        await asyncio.sleep(0.05)
        stopper = asyncio.create_task(Timer._stop_all([timer]))
        await asyncio.sleep(0)
        stopper.cancel()
        try:
            await stopper
        except asyncio.CancelledError:
            pass
    executor = asyncio.get_running_loop()._default_executor
    joined = True
    if executor is not None:
        joiner = threading.Thread(target=executor.shutdown, daemon=True)
        joiner.start()
        joiner.join(JOIN_SECONDS)
        joined = not joiner.is_alive()
    print("joined" if joined else "stranded", flush=True)
    os._exit(0)


asyncio.run(main())
"""


def test_a_doubly_cancelled_timer_strands_no_executor_thread() -> None:
    """Teardown of a stopped timer never waits on a parked sleep thread.

    Mutation: removing the palette's ``install_cancel_safe_timer_sleep()``
    call restores Textual's executor sleep, and on Windows the child reports
    ``stranded``. Other platforms already sleep on the event loop, so there
    the test pins only that the jobs interface keeps them that way.
    """
    completed = subprocess.run(
        [sys.executable, "-c", _DOUBLE_CANCEL_SRC],
        capture_output=True,
        text=True,
        timeout=_CHILD_TIMEOUT_SECONDS,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "joined", (
        "a cancelled timer left its sleep thread parked in the default executor"
    )
