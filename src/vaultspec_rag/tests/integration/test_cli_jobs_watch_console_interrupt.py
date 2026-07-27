"""Ctrl+C out of ``server jobs --watch`` with a real console interrupt.

``--watch`` hands the screen to a full-screen interface, so an interrupt has to
travel further than it did through a reprint loop: the application owns the
alternate screen buffer, the cursor and mouse reporting, and it has to give all
three back on the way out. Raising ``KeyboardInterrupt`` from a substituted
sleep asserts that a handler formats an exception the test constructed; it
cannot show that the signal a terminal actually sends reaches a running event
loop, nor that the terminal survives it. So the CLI runs as a real child on its
own console and is interrupted the way an operator interrupts it.

An interrupt that ends the process without unwinding the application leaves the
operator's shell inside the alternate screen with a hidden cursor - a working
shell that renders as a dead one. That teardown is what the byte-level
assertions below are reading.
"""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

from .._cli_helpers import _jobs_empty_contract_server
from ._console_interrupt import (
    _CREATE_NEW_CONSOLE,
    _clear_inherited_console_interrupt_deafness,
    _hidden_console_startupinfo,
    _interrupt_console_of,
)

pytestmark = [pytest.mark.integration]

# Leaving the live view is how an operator finishes with it, by Ctrl+C exactly
# as by `q`. Nothing was asked for that was not delivered, so there is no
# failure for a non-zero status to report.
_OPERATOR_LEFT_EXIT_CODE = 0

_RENDER_TIMEOUT = 90.0
_CLI_EXIT_TIMEOUT = 60.0

# The terminal state the application takes and must hand back.
_ENTER_ALTERNATE_SCREEN = b"\x1b[?1049h"
_LEAVE_ALTERNATE_SCREEN = b"\x1b[?1049l"
_SHOW_CURSOR = b"\x1b[?25h"


def _await_the_first_refresh(
    proc: subprocess.Popen[bytes], requests: list[str]
) -> None:
    """Wait until the view has rendered a real refresh.

    The interrupt has to land in the running event loop rather than during
    startup; a process interrupted before its terminal setup completes would
    have nothing to hand back and would pass the teardown assertions trivially.
    """
    deadline = time.monotonic() + _RENDER_TIMEOUT
    while time.monotonic() < deadline and not requests:
        if proc.poll() is not None:
            msg = f"the watch exited (rc={proc.returncode}) before refreshing"
            raise AssertionError(msg)
        time.sleep(0.05)
    assert requests, "the watch never issued a refresh"


@pytest.mark.skipif(sys.platform != "win32", reason="console control events")
def test_a_console_interrupt_ends_the_watch_and_hands_back_the_terminal() -> None:
    """Ctrl+C leaves the view cleanly and restores the screen and cursor.

    The refresh the interface renders first is a real request to a real
    server, and the interrupt is the event a terminal generates rather than an
    exception the test raised into a patched sleep.

    Proven able to fail, in both directions this test claims:

    - the exit status: parking the watch adapter in a bare sleep after one
      refresh, instead of handing the screen to the interface, fails on the
      status assertion with 130 - the entry point's own interrupt guard
      catching a ``KeyboardInterrupt`` the interface would have absorbed;
    - the teardown: hard-exiting from a ``SIGINT`` handler inside the
      interface, so it exits 0 with no traceback but never unwinds, fails on
      the alternate-screen assertion by name against a stream that enters the
      screen and never leaves it.
    """
    _clear_inherited_console_interrupt_deafness()

    server, thread, requests = _jobs_empty_contract_server()
    # Bytes, not text: the interface paints escape sequences and box-drawing
    # characters that the console's ANSI codepage cannot decode, and a decode
    # error in the reader thread yields a ``None`` stream rather than a failure
    # anyone can read.
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "vaultspec_rag",
            "server",
            "jobs",
            "--watch",
            "--port",
            str(server.server_address[1]),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=_CREATE_NEW_CONSOLE,
        startupinfo=_hidden_console_startupinfo(),
    )
    try:
        _await_the_first_refresh(proc, requests)
        _interrupt_console_of(proc.pid)
        # A view that swallowed the interrupt would hold the terminal until
        # this timeout expires, which is the operator-facing failure itself.
        stdout, stderr = proc.communicate(timeout=_CLI_EXIT_TIMEOUT)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=30)
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert proc.returncode == _OPERATOR_LEFT_EXIT_CODE, (
        f"exit {proc.returncode} (0x{proc.returncode & 0xFFFFFFFF:x}), "
        f"stderr: {stderr.decode('utf-8', 'replace')}"
    )

    # Ordering, not presence: an application that emitted the leave sequence
    # before it ever entered would satisfy a containment check while leaving
    # the operator on the alternate screen.
    assert _ENTER_ALTERNATE_SCREEN in stdout, "the interface never took the screen"
    assert _LEAVE_ALTERNATE_SCREEN in stdout, (
        "the interrupt left the alternate screen up"
    )
    left = stdout.rindex(_LEAVE_ALTERNATE_SCREEN)
    assert left > stdout.index(_ENTER_ALTERNATE_SCREEN)
    # The cursor is hidden for the duration and has to come back after the
    # screen does, or the restored shell has no visible prompt.
    assert _SHOW_CURSOR in stdout[left:], "the interrupt left the cursor hidden"

    assert b"Traceback" not in stdout
    assert b"Traceback" not in stderr
    assert b"KeyboardInterrupt" not in stderr
