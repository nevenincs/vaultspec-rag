"""Find a helper program by name without consulting the working directory.

This package runs a handful of programs it does not build in Python: the
monitor, the graphics driver's query tool, the package manager, and a few
operating-system tools. Naming one and leaving the rest to the operating
system is not safe.
On Windows a bare program name is looked for in the working directory before
anywhere else, both by the process-creation call and by the standard
library's lookup, which adds the working directory even to a search path it
is handed. Elsewhere an empty or relative entry in ``PATH`` means the same
thing. Commands here are run from inside project checkouts, so either lets a
checkout supply the program.

A program is therefore always run by an absolute path, found here, in the
places its caller says it belongs:

* beside this installation's own programs, for what ships with it. That is
  the environment's scripts directory, the running interpreter's own
  directory, and - for an installation started by a single-file launcher -
  the launcher's own directory, because a launcher installs this package
  into a cache environment of its own and the executables it shipped with
  sit beside the launcher instead. The monitor is looked for in those
  places and nowhere else, and only its content decides whether what is
  found may run;
* the operating system's own directories, for operating-system tools, which
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

__all__ = ["Where", "find_program", "find_programs", "installation_programs"]

#: The extensions a program may carry on Windows when ``PATHEXT`` says nothing.
_DEFAULT_PATHEXT = ".COM;.EXE;.BAT;.CMD"


class Where(Enum):
    """A place a program is legitimately found."""

    #: The directories this installation's own programs are installed into:
    #: the environment's scripts directory and the running program's own.
    INSTALLATION = "beside this installation's programs"
    #: Where the operating system keeps its own programs. On Windows that is
    #: the system directory and the PowerShell directory beneath it.
    SYSTEM = "the operating system's program directories"
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
    return next(find_programs(name, *where), None)


def find_programs(name: str, *where: Where) -> Iterator[str]:
    """Yield every absolute path the program *name* is found at, in order.

    For a caller that decides which match may run by the file's content
    rather than by its place: the first file of the right name is not
    necessarily the right file, and stopping at it hides the others. One
    installation can hold several - a launcher's own directory beside the
    scripts directory of the environment it installed - and only one of them
    is this release's.

    Each directory is visited once, however many of the places given name it.

    Args:
        name: The program's bare name, as :func:`find_program` takes it.
        *where: The places to look, in order. At least one.

    Raises:
        ValueError: As :func:`find_program` does, before anything is looked
            for.
    """
    if not where:
        raise ValueError("at least one place to look is required")
    if not name or name in {os.curdir, os.pardir} or os.path.basename(name) != name:
        raise ValueError(f"not a bare program name: {name!r}")
    return _matches(_spellings(name), where)


def _matches(candidates: tuple[str, ...], where: tuple[Where, ...]) -> Iterator[str]:
    """Yield each runnable file among *candidates*, in the places given."""
    seen: set[str] = set()
    for directory in _directories(where):
        key = os.path.normcase(os.path.normpath(directory))
        if key in seen:
            continue
        seen.add(key)
        for candidate in candidates:
            path = os.path.join(directory, candidate)
            if os.path.isfile(path) and os.access(path, os.X_OK):
                yield path


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


def installation_programs() -> tuple[str, ...]:
    """Return the directories this installation's own programs are in, in order.

    The first is where an installer puts a program of this installation's; the
    second is where the running interpreter is, which is the same directory in
    an ordinary environment and a different one in a relocated or embedded
    layout. The third, when there is one, is the directory of the launcher
    this installation was started by. Stated here because whoever installs a
    program of ours has to agree with where :func:`find_program` will look
    for it.
    """
    launcher = _launcher_directory()
    directories = (sysconfig.get_path("scripts"), os.path.dirname(sys.executable))
    return directories if launcher is None else (*directories, launcher)


def _launcher_directory() -> str | None:
    """Return the directory of the launcher that started this, or ``None``.

    A single-file launcher carries this package as a wheel, installs it into
    a cache environment of its own on first run, and runs the interpreter of
    that environment. Neither directory above is then where the executables
    the launcher shipped with sit: those are beside the launcher itself,
    inside the archive an installation of that shape was extracted from.

    The launcher states its own path in the environment it hands the
    interpreter. The same variable carries a bare marker when the launcher
    was built without that option, so a value that does not name an existing
    absolute file is not read as a path.
    """
    stated = os.environ.get(EnvVar.PYAPP, "")
    if not stated or not os.path.isabs(stated) or not os.path.isfile(stated):
        return None
    return os.path.dirname(stated)


def _directories(where: tuple[Where, ...]) -> Iterator[str]:
    """Yield every absolute directory the given places name, in order."""
    for place in where:
        candidates: Sequence[str]
        if place is Where.INSTALLATION:
            candidates = installation_programs()
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

        system = system_directory()
        # Windows keeps PowerShell in a directory of its own beneath the
        # system directory, so that one alone would send a caller wanting it
        # back to PATH, where a same-named program can answer first.
        return [system, os.path.join(system, "WindowsPowerShell", "v1.0")]
    return os.defpath.split(os.pathsep)
