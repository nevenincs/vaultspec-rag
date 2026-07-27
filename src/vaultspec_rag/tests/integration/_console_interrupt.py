"""Delivering a real Windows console interrupt to a spawned CLI process.

``threading.interrupt_main`` cannot stand in for this. It trips the
interpreter's flag directly and skips the console handler the CRT runs on its
own thread, so it exercises none of the delivery path an operator's Ctrl+C
takes - a guard built on it reports success against a process that never
receives the signal.

Delivery has two Windows properties the helpers here are built around, both of
which silently produce a passing test if got wrong:

- ``CTRL_C_EVENT`` reaches processes by CONSOLE, not by pid, so a process under
  test is given its own console and the event is generated for everyone on it;
- the "ignore Ctrl+C" attribute is INHERITED by child processes. A test process
  that set it - to survive the event it generates - would hand every CLI it
  spawns a deafness indistinguishable from a working guard. So the generating
  process is a separate short-lived one that spawns nothing and is free to make
  itself deaf.

Underscore prefix keeps pytest from collecting this as a test module.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

__all__ = [
    "_CREATE_NEW_CONSOLE",
    "_clear_inherited_console_interrupt_deafness",
    "_hidden_console_startupinfo",
    "_interrupt_console_of",
]

# Spelled out rather than taken from ``subprocess``, which only defines the
# console creation flags on Windows; this module is imported on every platform
# by tests that skip themselves.
_CREATE_NEW_CONSOLE = 0x00000010
_STARTF_USESHOWWINDOW = 0x00000001
_SW_HIDE = 0

_INTERRUPT_DELIVERY_TIMEOUT = 60.0

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


def _clear_inherited_console_interrupt_deafness() -> None:
    """Make children of this process able to receive a console interrupt.

    The ignore attribute is inherited, and this process may well have been
    started by a launcher that set it - shells and task runners commonly do. A
    CLI spawned under an inherited ignore runs straight through the interrupt,
    so the guard would be measured against a process that never received the
    signal and would pass no matter what the code under test did. Clearing it
    restores the ordinary console default rather than imposing anything, and it
    cannot expose this process to an event generated on a child's own console.
    """
    ctypes.WinDLL("kernel32", use_last_error=True).SetConsoleCtrlHandler(None, False)


def _hidden_console_startupinfo() -> Any:
    """Start a child on a console it owns, without flashing a window.

    The console is required - an interrupt is delivered through one, and a
    child created without it can never receive the event. It is hidden because
    a test suite should not put windows on an operator's screen.
    """
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= _STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = _SW_HIDE
    return startupinfo


def _interrupt_console_of(pid: int) -> None:
    """Generate a genuine ``CTRL_C_EVENT`` on the console *pid* owns."""
    sent = subprocess.run(
        [sys.executable, "-c", _GENERATE_CONSOLE_INTERRUPT, str(pid)],
        capture_output=True,
        text=True,
        check=False,
        timeout=_INTERRUPT_DELIVERY_TIMEOUT,
    )
    assert sent.returncode == 0, (
        f"could not deliver a console interrupt: rc={sent.returncode} {sent.stderr}"
    )
