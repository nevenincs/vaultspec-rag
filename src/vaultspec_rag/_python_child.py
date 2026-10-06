"""Build the command line for every Python child this package starts.

An interpreter started to run a module or an inline program puts the working
directory first on its import path, and one started on a script file puts that
file's directory there. This package's commands are run from inside project
checkouts, so a child started either way imports whatever the checkout ships
under the name of this package, or of anything the child imports, and runs it
as the operator.

Every child therefore runs in the interpreter's safe-path mode, which adds
neither directory. Installed packages are still found: they are reached
through the environment's site directories, which the mode leaves alone, and
an editable install is reached the same way through its path file.

The flag is used rather than the equivalent environment variable because a
variable is inherited by everything the child goes on to start, including
tools that are not this package's to configure, and is ignored by a child
that asks for an isolated environment. The one place that cannot pass a flag
is a worker pool, whose command line the standard library builds; that site
alone uses the variable, and says so where it does.

Stdlib-only and free of package imports, so a process-pool worker, the service
client and the command line can all reach it without loading anything else.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["inline_command", "module_command", "script_command"]

#: Keeps the working directory and the script directory off the import path.
SAFE_PATH_FLAG: Final = "-P"


def module_command(interpreter: str, module: str, *arguments: str) -> list[str]:
    """Return the command that runs *module* as a program under *interpreter*."""
    return [interpreter, SAFE_PATH_FLAG, "-m", module, *arguments]


def inline_command(interpreter: str, program: str, *arguments: str) -> list[str]:
    """Return the command that runs the source text *program* under *interpreter*."""
    return [interpreter, SAFE_PATH_FLAG, "-c", program, *arguments]


def script_command(interpreter: str, script: Path, *arguments: str) -> list[str]:
    """Return the command that runs the file *script* under *interpreter*.

    Naming the file is what a caller uses when the import path of the child
    is not its own to trust: the file run is the one named, whatever a module
    of the same name resolves to there.
    """
    return [interpreter, SAFE_PATH_FLAG, str(script), *arguments]
