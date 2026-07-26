"""Replacing one file with another, atomically and without losing the race.

Twenty-odd modules publish state by writing a temp file and calling
``os.replace``. One of them - the job persistence layer - learned the hard way
that a bare ``os.replace`` is not enough on Windows, and grew a retry ladder
and a write-through move. The other twenty did not, so every one of them could
still fail on the condition that layer was hardened against.

The two things it learned are separable, and separating them is what lets
every caller take the part it needs:

- **The sharing race is universal and free to defend against.** Windows
  Defender and the Search indexer open a freshly published file, and a
  ``os.replace`` landing in that window fails with ``ACCESS_DENIED`` or
  ``SHARING_VIOLATION``. The defence is a short retry ladder, and it costs
  nothing when uncontended: the loop returns on its first attempt. Every
  caller uses :func:`replace_atomically`.
- **Durability costs real I/O and is a per-caller decision.** Forcing the
  rename to disk means a write-through move on Windows or an ``fsync`` of the
  parent directory on POSIX. A record that must survive a crash wants it; a
  cache entry rewritten on the next run does not, and paying for it on a
  per-file indexing path would be a real cost for nothing. Those callers use
  :func:`replace_durably`.

The retry is bounded so the whole ladder stays under about a second, because
callers hold locks across it.
"""

from __future__ import annotations

import contextlib
import os
import random
import sys
import time
from typing import TYPE_CHECKING

from ._backoff import jittered_backoff

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = ["NotDurableError", "replace_atomically", "replace_durably"]

#: Attempts and the jittered ladder between them. Exponential growth escapes a
#: busy scan window quickly; the jitter decorrelates this writer's retries from
#: the scanner's periodic open so repeated collisions do not lock-step.
_ATTEMPTS = 10
_BASE_SECONDS = 0.005
_MAX_SLEEP_SECONDS = 0.15
_JITTER_FRACTION = 0.25

#: ``MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH``.
_MOVEFILE_REPLACE_EXISTING = 0x1
_MOVEFILE_WRITE_THROUGH = 0x8

#: Windows ``ERROR_ACCESS_DENIED`` and ``ERROR_SHARING_VIOLATION``.
_SHARING_WINERRORS = frozenset({5, 32})


class NotDurableError(OSError):
    """The replace LANDED but could not be forced to disk.

    Distinct from a failed replace because the data is already visible to
    every reader: the caller has published, and only the crash-durability of
    that publication is in doubt. A caller that reports this as a write
    failure would be telling its operator the opposite of what happened.
    """


def _is_sharing_violation(exc: OSError) -> bool:
    """Whether a failed replace is the transient scanner race, not a real fault."""
    return isinstance(exc, PermissionError) or (
        sys.platform == "win32" and getattr(exc, "winerror", None) in _SHARING_WINERRORS
    )


def _retrying(replace: Callable[[], None]) -> None:
    """Run *replace* through the bounded sharing-violation ladder."""
    for attempt in range(_ATTEMPTS):
        try:
            replace()
        except OSError as exc:
            last = attempt + 1 >= _ATTEMPTS
            if _is_sharing_violation(exc) and not last:
                # The ladder numbers attempts from zero, so the attempt index
                # is the exponent with no offset.
                time.sleep(
                    jittered_backoff(
                        attempt,
                        base=_BASE_SECONDS,
                        cap=_MAX_SLEEP_SECONDS,
                        fraction=_JITTER_FRACTION,
                        random_unit=random.random(),
                    )
                )
                continue
            raise
        else:
            return


def replace_atomically(source: Path | str, destination: Path | str) -> None:
    """Replace *destination* with *source*, retrying the Windows sharing race.

    Does NOT force the rename to disk - see :func:`replace_durably` for that.
    Use this wherever a bare ``os.replace`` would otherwise appear: it is the
    same operation with the one defence that costs nothing when uncontended.

    Raises:
        OSError: The replace failed for a reason retrying cannot fix, or the
            sharing window did not clear within the ladder.

    """
    _retrying(lambda: os.replace(source, destination))


def replace_durably(source: Path | str, destination: Path | str) -> None:
    """Replace *destination* with *source* and force the rename to disk.

    Windows uses a write-through move, which is atomic and durable in one
    call. POSIX has no such flag, so the rename is followed by an ``fsync`` of
    the containing directory - and a failure THERE is reported as
    :class:`NotDurableError`, because by then the replace has already landed.

    Raises:
        NotDurableError: The replace landed but could not be synced.
        OSError: The replace itself failed.

    """
    if sys.platform == "win32":
        _retrying(lambda: _move_file_write_through(source, destination))
        return
    _retrying(lambda: os.replace(source, destination))
    parent = os.path.dirname(os.path.abspath(str(destination)))
    try:
        descriptor = os.open(parent, os.O_RDONLY)
    except OSError as exc:
        raise NotDurableError(str(exc)) from exc
    try:
        os.fsync(descriptor)
    except OSError as exc:
        raise NotDurableError(str(exc)) from exc
    finally:
        with contextlib.suppress(OSError):
            os.close(descriptor)


def _move_file_write_through(source: Path | str, destination: Path | str) -> None:
    """Atomically replace *destination*, forcing the change through to disk."""
    import ctypes
    from ctypes import wintypes

    move_file_ex = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
    move_file_ex.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    move_file_ex.restype = wintypes.BOOL
    if not move_file_ex(
        str(source),
        str(destination),
        _MOVEFILE_REPLACE_EXISTING | _MOVEFILE_WRITE_THROUGH,
    ):
        raise ctypes.WinError(ctypes.get_last_error())
