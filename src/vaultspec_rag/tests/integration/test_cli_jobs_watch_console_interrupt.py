"""Ctrl+C out of ``server jobs --watch`` with a real console interrupt.

The watch loop parks in a sleep between refreshes, and a terminal ends it by
delivering a console control event into that sleep. Raising ``KeyboardInterrupt``
from a substituted sleep asserts that the handler formats an exception the test
constructed; it cannot show that the signal a terminal actually sends reaches
the loop and is handled. So the CLI runs as a real child on its own console and
is interrupted the way an operator interrupts it.
"""

from __future__ import annotations

import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

from .._cli_helpers import _jobs_empty_contract_server

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.integration]

# Conventional interrupted status, 128 + SIGINT.
_INTERRUPTED_EXIT_CODE = 130

_STARTF_USESHOWWINDOW = 0x00000001
_SW_HIDE = 0
_RENDER_TIMEOUT = 90.0
_CLI_EXIT_TIMEOUT = 60.0

_GENERATE_CONSOLE_INTERRUPT = """
import ctypes
import sys

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
# Safe here and nowhere else: this process spawns nothing, so the inherited
# ignore attribute cannot reach the process under test.
kernel32.SetConsoleCtrlHandler(None, True)
kernel32.FreeConsole()
if not kernel32.AttachConsole(int(sys.argv[1])):
    raise SystemExit(2)
raise SystemExit(0 if kernel32.GenerateConsoleCtrlEvent(0, 0) else 3)
"""


@pytest.mark.skipif(sys.platform != "win32", reason="console control events")
def test_a_console_interrupt_ends_the_watch_on_the_interrupted_status(
    tmp_path: Path,
) -> None:
    """Ctrl+C ends the view on 130 with the stop line and no traceback.

    Reporting 0 would tell a script the watch completed normally. The refresh
    the loop renders first is a real request to a real server, and the
    interrupt is the event a terminal generates rather than an exception the
    test raised into a patched sleep.

    Proven able to fail: removing the KeyboardInterrupt handler from the watch
    verb makes the child report the console's own termination status instead of
    130, and print a traceback rather than the stop line.
    """
    import ctypes

    del tmp_path
    # The ignore attribute is inherited, and a launcher may have set it. A CLI
    # spawned under an inherited ignore runs straight through the interrupt, so
    # the guard would be measured against a process that never received it.
    ctypes.WinDLL("kernel32", use_last_error=True).SetConsoleCtrlHandler(None, False)

    server, thread, requests = _jobs_empty_contract_server()
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= _STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = _SW_HIDE
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
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        startupinfo=startupinfo,
        text=True,
    )
    try:
        # Wait for the loop to have rendered a real refresh, so the interrupt
        # lands in the wait rather than during startup.
        deadline = time.monotonic() + _RENDER_TIMEOUT
        while time.monotonic() < deadline and not requests:
            if proc.poll() is not None:
                msg = f"the watch exited (rc={proc.returncode}) before refreshing"
                raise AssertionError(msg)
            time.sleep(0.05)
        assert requests, "the watch never issued a refresh"

        sent = subprocess.run(
            [sys.executable, "-c", _GENERATE_CONSOLE_INTERRUPT, str(proc.pid)],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert sent.returncode == 0, f"could not deliver an interrupt: {sent.stderr}"
        stdout, stderr = proc.communicate(timeout=_CLI_EXIT_TIMEOUT)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=30)
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert proc.returncode == _INTERRUPTED_EXIT_CODE
    assert "Stopped watching jobs." in stdout
    assert "Traceback" not in stdout
    assert "Traceback" not in stderr
