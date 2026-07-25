"""Package execution shim for ``python -m vaultspec_rag``.

This module delegates directly to the root Typer application defined in
``vaultspec_rag.cli`` so package execution and the installed CLI entrypoint
share the same command surface.

The delegation is deferred to call time rather than done at module scope, and
that is load-bearing. Building the command surface costs seconds of import
work, and until it finishes there is no command handler to receive an
interrupt: an operator's Ctrl+C in that window reaches the top level as an
unhandled ``KeyboardInterrupt``, which CPython on Windows reports by
terminating the process with the console's own status code, behind a traceback
of whichever import happened to be in flight. Importing under the guard below
turns that into the same conventional interrupted status the running commands
already report.

The guard ends the moment the command surface exists. Interrupt handling from
there on belongs to the command that is running, and is deliberately untouched.
"""

from __future__ import annotations

import os
import sys
from typing import NoReturn

#: Conventional exit status for a run ended by an operator interrupt
#: (128 + SIGINT), matching what the already-running commands report.
_INTERRUPTED_EXIT_CODE = 130

#: Says the one thing the operator cannot otherwise know: the interrupt landed
#: early enough that no command began, so nothing was left half-done.
_INTERRUPTED_NOTICE = "Interrupted before the command started; nothing ran."


def _exit_startup_interrupted() -> NoReturn:
    """Report an interrupt taken during startup and exit on 130.

    Written to stderr with the interpreter's own primitives, for two reasons.
    Stream: a ``--json`` consumer parses stdout, and a human line placed there
    would corrupt the document it is reading. Primitives: the CLI's console is
    part of the import that was still in flight, so reaching for it here could
    fail on exactly the runs this exists to handle.

    The exit is immediate rather than a raised ``SystemExit``. Unwinding
    normally leaves the interpreter finalizing hundreds of half-imported
    modules while the console's own interrupt disposition is still in play, and
    that race was measured to reclaim the exit status on roughly one run in
    eight - the operator saw the notice and still got the console's status
    code. Exiting here is safe precisely because no command ran: nothing is
    open to unwind, so the only thing normal shutdown could still do is take
    the status away.
    """
    # Leading newline so the line does not run on from the console's own ``^C``
    # echo, matching how the running commands announce the same event.
    print(f"\n{_INTERRUPTED_NOTICE}", file=sys.stderr)
    # Explicit, because the immediate exit runs no buffer flushing of its own.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            stream.flush()
    os._exit(_INTERRUPTED_EXIT_CODE)


def main() -> None:
    """Entry point for ``python -m vaultspec_rag`` and the console script.

    Loads the root Typer CLI application, then delegates to it.
    """
    try:
        from .cli import run_cli
    except KeyboardInterrupt:
        _exit_startup_interrupted()
    else:
        run_cli()


if __name__ == "__main__":
    main()
