"""Win32 process-creation flags, as plain integers.

These are values from the Windows API (``processthreadsapi.h``), not project
policy. ``subprocess`` defines the same numbers, but only on Windows: importing
them at module scope would break every POSIX import of the modules that need
them, so they are restated here once as ordinary ints that any platform can
import and that the win32-only branches then use.

Restated *once*. Two spawn sites - the detached daemon and the supervised
Qdrant child - previously carried their own copies of the same two flags, which
is a transcription risk with no upside: a Win32 flag is a single wrong hex digit
away from meaning something else entirely, and a wrong `creationflags` value
fails as strange process behaviour rather than as an error anyone can read.

The flags a call site combines remain that call site's decision, and the two
differ deliberately: the daemon breaks away from the launching shell's Job
Object so it survives the shell, while the Qdrant child must stay inside the
daemon's Job Object because that membership is the no-orphan guarantee.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "WIN_CREATE_BREAKAWAY_FROM_JOB",
    "WIN_CREATE_NEW_PROCESS_GROUP",
    "WIN_CREATE_NO_WINDOW",
    "WIN_DETACHED_PROCESS",
]

#: New process group: the child does not receive the parent console's CTRL_C.
WIN_CREATE_NEW_PROCESS_GROUP: Final = 0x00000200

#: No console window is allocated for the child.
WIN_CREATE_NO_WINDOW: Final = 0x08000000

#: Detach from the launching shell's Job Object so the child outlives the
#: shell. Restricted Job Objects may deny this, which callers must handle.
WIN_CREATE_BREAKAWAY_FROM_JOB: Final = 0x01000000

#: Sever the child's console association entirely.
WIN_DETACHED_PROCESS: Final = 0x00000008
