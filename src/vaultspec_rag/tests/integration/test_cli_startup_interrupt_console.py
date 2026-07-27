"""A real console Ctrl+C at a real CLI process, inside its startup window.

This is the guard for the defect as an operator meets it, and it is
deliberately expensive: a spawned CLI, its own console, and a genuine
``CTRL_C_EVENT``. Why nothing cheaper stands in, and the two Windows delivery
properties the arrangement is built around, are documented at the helpers that
carry them in ``_console_interrupt``.

The child holds itself inside the window rather than the test firing on a
timer. The window is real but its width is not fixed: the same command takes
around 2.5s with cold file caches and under 0.8s once warm, so a fixed delay
either fires before the guard is live or after the command has already
finished, and the second of those passes while measuring nothing. Holding the
import open and firing on the child's own signal makes the test measure the
case it names every time. Everything else stays real - the process, the
console, the event, the entry point, and the import the interrupt lands in.
"""

from __future__ import annotations

import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

from ...__main__ import _INTERRUPTED_NOTICE
from ._console_interrupt import (
    _CREATE_NEW_CONSOLE,
    _clear_inherited_console_interrupt_deafness,
    _hidden_console_startupinfo,
    _interrupt_console_of,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.integration]

# Conventional interrupted status, 128 + SIGINT. Written out rather than read
# from the entry point: the contract under test is this number, and the defect
# was that the process reported the console's 0xC000013A instead.
_INTERRUPTED_EXIT_CODE = 130

#: How long the child holds the command-surface import open. Only an upper
#: bound on a wedged run - the interrupt normally ends it in milliseconds.
_HOLD_WINDOW_OPEN_SECONDS = 30.0

#: How long to wait for the child to report that it reached the window.
_REACHED_WINDOW_TIMEOUT = 90.0

_CLI_EXIT_TIMEOUT = 60.0

# Announces that the child is inside the guarded import and then keeps it
# there. The announcement goes to a file rather than to a stream, so both of
# the child's streams stay pristine for the assertions about what the operator
# is shown. argv is restored to a real invocation, so a run that somehow missed
# the interrupt goes on to print help and fails loudly instead of erroring on
# the harness's own arguments.
_HOLD_INSIDE_THE_STARTUP_WINDOW = """
import sys
import time
from importlib.abc import MetaPathFinder
from pathlib import Path

marker = Path(sys.argv[1])
hold = float(sys.argv[2])
sys.argv = ["vaultspec-rag", "--help"]


class _HoldInsideTheImport(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "vaultspec_rag.cli":
            marker.write_text("reached", encoding="utf-8")
            time.sleep(hold)
        return None


sys.meta_path.insert(0, _HoldInsideTheImport())

from vaultspec_rag.__main__ import main  # absolute-import-ok

main()
"""

if sys.platform == "win32":

    def _spawn_cli_holding_the_window_open(marker: Path) -> subprocess.Popen[str]:
        """Start the CLI on its own console, parked inside the guarded import.

        Both streams stay on pipes so the console never sees the output.
        """
        _clear_inherited_console_interrupt_deafness()
        return subprocess.Popen(
            [
                sys.executable,
                "-c",
                _HOLD_INSIDE_THE_STARTUP_WINDOW,
                str(marker),
                str(_HOLD_WINDOW_OPEN_SECONDS),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            creationflags=_CREATE_NEW_CONSOLE,
            startupinfo=_hidden_console_startupinfo(),
            text=True,
        )

    def _await_the_startup_window(proc: subprocess.Popen[str], marker: Path) -> None:
        deadline = time.monotonic() + _REACHED_WINDOW_TIMEOUT
        while time.monotonic() < deadline:
            if marker.is_file():
                return
            if proc.poll() is not None:
                raise AssertionError(
                    f"the CLI exited (rc={proc.returncode}) before reaching the "
                    f"startup window"
                )
            time.sleep(0.02)
        raise AssertionError("the CLI never reached the startup window")

    def test_a_console_interrupt_during_startup_exits_on_the_interrupted_status(
        tmp_path: Path,
    ) -> None:
        """Ctrl+C before the command exists ends on 130 with one plain line.

        Every assertion here failed before the guard: the process reported the
        console's own termination status, said nothing an operator could act
        on, and spilled the frames of whichever import happened to be running.
        """
        marker = tmp_path / "reached-the-startup-window"
        proc = _spawn_cli_holding_the_window_open(marker)
        try:
            _await_the_startup_window(proc, marker)
            _interrupt_console_of(proc.pid)
            stdout, stderr = proc.communicate(timeout=_CLI_EXIT_TIMEOUT)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()

        assert proc.returncode == _INTERRUPTED_EXIT_CODE, (
            f"exit {proc.returncode} (0x{proc.returncode & 0xFFFFFFFF:x}), "
            f"stderr: {stderr}"
        )
        assert _INTERRUPTED_NOTICE in stderr
        assert "Traceback" not in stderr
        assert "KeyboardInterrupt" not in stderr
        # Both halves matter: the command never ran, and the notice went to the
        # stream a --json consumer is not parsing.
        assert "Usage:" not in stdout
        assert stdout == ""
