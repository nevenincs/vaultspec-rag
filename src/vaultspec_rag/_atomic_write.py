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
import json
import os
import pathlib
import random
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ._backoff import jittered_backoff

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = [
    "JsonWriteOptions",
    "NotDurableError",
    "fsync_directory",
    "replace_atomically",
    "replace_durably",
    "write_json_atomically",
]

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


@dataclass(frozen=True)
class JsonWriteOptions:
    """Serialization and durability choices for an atomic JSON publication."""

    indent: int | None = None
    sort_keys: bool = False
    compact: bool = False
    durable: bool = False


_DEFAULT_JSON_WRITE_OPTIONS = JsonWriteOptions()


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
    try:
        fsync_directory(os.path.dirname(os.path.abspath(str(destination))))
    except OSError as exc:
        raise NotDurableError(str(exc)) from exc


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


def write_json_atomically(
    path: Path | str,
    payload: Any,
    options: JsonWriteOptions = _DEFAULT_JSON_WRITE_OPTIONS,
) -> None:
    """Publish *payload* as JSON at *path*, atomically, leaving no temp behind.

    Thirteen sites grew this: serialize, write a temp sibling, replace. Two of
    them - the machine pointer and the streaming code sidecar - had learned
    what the other eleven had not, and the difference is visible on disk:

    - **The temp file must be cleaned up.** A failed write or a replace that
      outlasts the sharing ladder leaves the temp behind forever. The careful
      copies unlink theirs in a ``finally``; the naive ones simply leaked. The
      suite already asserts no temp survives in several places, which is how
      the two versions could sit side by side without the gap being obvious.
    - **The temp name must not collide.** ``path.with_suffix(".tmp")`` gives
      two writers of one file the same temp path, and gives an attacker a
      predictable name to pre-plant a symlink at. The name here carries the
      target, the pid and a random suffix, and is dot-prefixed so it does not
      look like product data to anything listing the directory.

    ``options.durable`` forces the bytes and the rename to disk, for a record
    that has to survive a crash rather than merely a concurrent reader. It does both:
    forcing only the rename, as one caller did, durably publishes contents the
    kernel was never told to flush.

    Raises:
        OSError: The payload could not be written or the replace failed.
        NotDurableError: Only under ``durable``, and only once the replace has
            already landed - the data is published, its persistence is not.

    """
    target = pathlib.Path(path)
    encoded = json.dumps(
        payload,
        indent=options.indent,
        sort_keys=options.sort_keys,
        separators=(",", ":") if options.compact else None,
        # NaN and Infinity are not JSON. Python emits them anyway and reads
        # them back, so a document carrying one round-trips here and is
        # rejected by every stricter reader. One caller already refused them;
        # refusing at the single writer means the bug surfaces where it is
        # made rather than wherever the file is next parsed.
        allow_nan=False,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(
        f".{target.name}.{os.getpid()}.{os.urandom(6).hex()}.tmp"
    )
    try:
        # newline="" so the bytes do not depend on the platform: with an
        # indent, the default translation would emit CRLF on Windows and LF
        # elsewhere for the same payload.
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            handle.write(encoded)
            if options.durable:
                handle.flush()
                os.fsync(handle.fileno())
        if options.durable:
            replace_durably(temporary, target)
        else:
            replace_atomically(temporary, target)
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)


def fsync_directory(directory: Path | str) -> None:
    """Force *directory*'s own entry to disk.

    A rename is not durable until the directory holding it is synced, and
    neither is a freshly created directory. POSIX only: on Windows a directory
    handle cannot be opened this way, and the write-through move covers the
    rename case instead.

    Raises:
        OSError: The directory could not be opened or synced. Callers decide
            what that means - a failed rename sync is reported as
            :class:`NotDurableError`, while a failed mkdir sync is fatal.

    """
    if sys.platform == "win32":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        with contextlib.suppress(OSError):
            os.close(descriptor)
