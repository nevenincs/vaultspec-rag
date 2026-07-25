"""Guard tests for the CLI's startup interrupt window.

These are guard tests, not positive coverage. Their subject is an interrupt
that arrives BEFORE any command handler exists - during the seconds the
entry point spends building the command surface. Left unguarded it escapes as
an unhandled ``KeyboardInterrupt``, which CPython on Windows reports by
terminating the process with the console's own status code, behind a traceback
of whichever import was in flight.

Two properties hold the fix up, and each is asserted here:

- the entry point must not import the command surface at module scope, because
  the guard can only cover work it wraps - an import hoisted back out of
  ``main`` would leave the guard in place and covering nothing;
- an interrupt raised out of that import must leave on the conventional
  interrupted status, with the notice on stderr and stdout untouched.

The interrupt here is injected at a real landing site inside the import
machinery, which makes these runnable on every platform. That is a statement
about the handler, not about console signal delivery - the Windows console
path that produced the defect is proven separately against a real
``CTRL_C_EVENT`` and a real spawned CLI.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from ..__main__ import _INTERRUPTED_NOTICE
from ._import_probe import assert_fresh_import_excludes, import_probe_source

pytestmark = [pytest.mark.unit]

# Conventional interrupted status, 128 + SIGINT. Written out rather than read
# from the entry point: the contract under test is this number, and sourcing it
# from the code under test would let a changed constant pass unnoticed.
_INTERRUPTED_EXIT_CODE = 130

# Raises the interrupt from inside the import machinery, where a real console
# interrupt is converted, rather than around it - a KeyboardInterrupt raised at
# the call site would pass even if the import had been hoisted to module scope.
_INTERRUPT_DURING_COMMAND_SURFACE_IMPORT = """
import sys
from importlib.abc import MetaPathFinder


class _InterruptWhileImporting(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "vaultspec_rag.cli":
            raise KeyboardInterrupt
        return None


sys.meta_path.insert(0, _InterruptWhileImporting())

from vaultspec_rag.__main__ import main  # absolute-import-ok

main()
print("the entry point returned instead of exiting", file=sys.stderr)
"""


def test_the_entry_point_defers_the_command_surface_import() -> None:
    """``__main__`` must not build the command surface at module scope.

    The console script reaches ``main`` by importing this module, so anything
    imported at its module scope runs before the guard exists and is therefore
    outside it. Hoisting the import back out of ``main`` is the regression this
    catches: the guard would still be there, wrapping nothing.

    Typer, Click and Rich are named alongside the CLI package because they are
    the bulk of that import, so a re-entangled entry point trips this even if
    it reaches them by some other route.
    """
    assert_fresh_import_excludes(
        import_probe_source(
            "vaultspec_rag.__main__",
            forbidden=("vaultspec_rag.cli", "typer", "click", "rich"),
        )
    )


def test_an_interrupt_during_startup_exits_on_the_interrupted_status() -> None:
    """The interrupt leaves on 130, saying so on stderr and not on stdout.

    Exit 0 would tell a script the command completed; a traceback would hand
    the operator interpreter internals instead of an answer. The notice belongs
    on stderr because a ``--json`` consumer parses stdout, and a human line
    placed there would corrupt the document it is reading.
    """
    proc = subprocess.run(
        [sys.executable, "-c", _INTERRUPT_DURING_COMMAND_SURFACE_IMPORT],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert proc.returncode == _INTERRUPTED_EXIT_CODE, (
        f"exit {proc.returncode}, stderr: {proc.stderr}"
    )
    assert _INTERRUPTED_NOTICE in proc.stderr
    assert "Traceback" not in proc.stderr
    assert "KeyboardInterrupt" not in proc.stderr
    assert proc.stdout == "", "the notice must not reach a --json consumer"
