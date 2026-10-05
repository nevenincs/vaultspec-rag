"""Find a helper program by name without consulting the working directory.

This package runs a handful of programs it does not ship: the monitor, the
graphics driver's query tool, the package manager, and a few operating-system
tools. Naming one and leaving the rest to the operating system is not safe.
On Windows a bare program name is looked for in the working directory before
anywhere else, both by the process-creation call and by the standard
library's lookup, which adds the working directory even to a search path it
is handed. Elsewhere an empty or relative entry in ``PATH`` means the same
thing. Commands here are run from inside project checkouts, so either lets a
checkout supply the program.

A program is therefore always run by an absolute path, found here, in the
places its caller says it belongs:

* beside this installation's own programs, for what ships with it;
* the operating system's own directory, for operating-system tools, which
  must not be answered by a same-named port earlier on ``PATH``;
* the absolute entries of ``PATH``, for a tool the operator installed.

The working directory is never among them, and an entry of ``PATH`` that is
empty or relative is skipped. An absolute entry that happens to be the
working directory is honoured: the operator put it there.

Imports nothing beyond the variable names and the Windows bindings, so the
service client and the command line can reach it without loading the
inference stack.
"""

from __future__ import annotations

import os
import sys
import sysconfig
from enum import Enum
from typing import TYPE_CHECKING

from .config._types import EnvVar

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

__all__ = ["Where", "find_program"]

#: The extensions a program may carry on Windows when ``PATHEXT`` says nothing.
_DEFAULT_PATHEXT = ".COM;.EXE;.BAT;.CMD"


class Where(Enum):
    """A place a program is legitimately found."""

    #: The directories this installation's own programs are installed into:
    #: the environment's scripts directory and the running program's own.
    INSTALLATION = "beside this installation's programs"
    #: Where the operating system keeps its own programs.
    SYSTEM = "the operating system's program directory"
    #: The absolute entries of ``PATH``, in order.
    SEARCH_PATH = "an absolute entry of PATH"


def find_program(name: str, *where: Where) -> str | None:
    """Return the absolute path of the program *name*, or ``None``.

    Args:
        name: The program's bare name. On Windows an extension is supplied
            from ``PATHEXT`` when the name carries none of them.
        *where: The places to look, in order. At least one.

    Returns:
        The first match as an absolute path, or ``None`` when no place given
        holds a runnable file of that name.

    Raises:
        ValueError: If *name* is not a bare name, or no place is given. A
            name with a directory part would be a path, and a path is the
            caller's to check, not something to search for.
    """
    if not where:
        raise ValueError("at least one place to look is required")
    if not name or name in {os.curdir, os.pardir} or os.path.basename(name) != name:
        raise ValueError(f"not a bare program name: {name!r}")
    candidates = _spellings(name)
    seen: set[str] = set()
    for directory in _directories(where):
        key = os.path.normcase(os.path.normpath(directory))
        if key in seen:
            continue
        seen.add(key)
        for candidate in candidates:
            path = os.path.join(directory, candidate)
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
    return None


def _spellings(name: str) -> tuple[str, ...]:
    """Return the file names *name* may be found under on this platform."""
    if sys.platform != "win32":
        return (name,)
    extensions = [
        extension
        for extension in os.environ.get(EnvVar.PATHEXT, _DEFAULT_PATHEXT).split(
            os.pathsep
        )
        if extension
    ]
    if any(name.upper().endswith(extension.upper()) for extension in extensions):
        return (name,)
    return tuple(name + extension for extension in extensions)


def _directories(where: tuple[Where, ...]) -> Iterator[str]:
    """Yield every absolute directory the given places name, in order."""
    for place in where:
        candidates: Sequence[str]
        if place is Where.INSTALLATION:
            candidates = [
                sysconfig.get_path("scripts"),
                os.path.dirname(sys.executable),
            ]
        elif place is Where.SYSTEM:
            candidates = _system_directories()
        else:
            candidates = os.environ.get(EnvVar.PATH, os.defpath).split(os.pathsep)
        for candidate in candidates:
            # An empty or relative entry is a place relative to wherever this
            # process happens to be, which is exactly what must not be searched.
            if candidate and os.path.isabs(candidate):
                yield candidate


def _system_directories() -> Sequence[str]:
    if sys.platform == "win32":
        from ._win32 import system_directory

        return [system_directory()]
    return os.defpath.split(os.pathsep)
