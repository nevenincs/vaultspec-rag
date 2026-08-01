"""How this suite talks to the real child processes its tests spawn.

Two mechanics, both of which every such test needs and each of which was
previously re-derived per call site with a different amount of care.

**Readiness markers.** A child reports "I have taken the lock / bound the
port / published the pointer" by writing a small file the parent polls for.
``Path.write_text`` creates the file and then writes into it, so a parent that
treats mere existence as the readiness condition can - and on Windows almost
always does - open it in the window between the two and read nothing. Measured
on this suite's own marker shape, an existence-triggered read landed in the
empty window 39 times out of 40. What that empty read then becomes depends
only on how the value is used: an empty borrower capability that the route
rejects as ``invalid_borrower_capability``, a ``Path("")`` that is not
absolute, an ``int("")`` that raises. Publishing through
:func:`publish_marker` makes appearance imply complete content, so existence
becomes a sound readiness condition again and :func:`await_marker` can wait on
the value rather than on a duration.

**Stderr.** A child spawned with ``stderr=subprocess.PIPE`` whose parent reads
that pipe only after ``wait()`` deadlocks as soon as the child emits more than
the pipe buffer holds - the child blocks in ``write``, the parent blocks in
``wait``. This is not hypothetical here: one route host deliberately provokes
an unhandled ASGI exception, and uvicorn's multi-kilobyte traceback fills the
buffer. The child then blocks inside the request, so the response is never
sent, the caller times out, and the server's graceful shutdown waits forever
for a request that can never finish - a hang that reads as an unreachable or
non-answering service rather than as the pipe it is. :func:`child_stderr`
gives the child a file it can always write to, and the parent the text
afterwards.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from .._atomic_write import replace_atomically

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Generator
    from os import PathLike

__all__ = ["ChildStderr", "await_marker", "child_stderr", "publish_marker"]


def publish_marker(path: str | PathLike[str], text: str) -> None:
    """Publish *text* at *path* so the file's appearance implies its content.

    Writes a uniquely named sibling and renames it into place, which is the
    only way a reader that merely observes the destination cannot see a
    partial value. The rename goes through the shared replace helper, so the
    Windows sharing window a scanner opens on a freshly written file is
    retried rather than raised at the child.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(
        f".{target.name}.{os.getpid()}.{os.urandom(6).hex()}.tmp"
    )
    try:
        staging.write_text(text, encoding="utf-8")
        replace_atomically(staging, target)
    finally:
        staging.unlink(missing_ok=True)


def await_marker(
    path: str | PathLike[str],
    process: subprocess.Popen[str] | subprocess.Popen[bytes],
    *,
    timeout: float,
) -> str | None:
    """Return the marker a live child published at *path*, or ``None``.

    ``None`` means the child exited without publishing, or the deadline
    passed. The caller owns the diagnosis, because the same wait failing means
    something different at each site.

    A read that raises ``OSError`` is retried rather than propagated: the
    marker is published by rename, so the only way an existing marker fails to
    open is a scanner holding it for the moment after it appears.
    """
    marker = Path(path)
    deadline = time.monotonic() + timeout
    while True:
        exited = process.poll() is not None
        with contextlib.suppress(OSError):
            published = marker.read_text(encoding="utf-8")
            if published:
                return published
        if exited or time.monotonic() >= deadline:
            return None
        time.sleep(0.01)


class ChildStderr:
    """A child's stderr, captured where the child can never block writing it."""

    def __init__(self, sink: BinaryIO, path: Path) -> None:
        self._sink = sink
        self._path = path

    @property
    def sink(self) -> BinaryIO:
        """The open file to hand to ``subprocess`` as ``stderr``."""
        return self._sink

    def read(self) -> str:
        """Return everything the child has written to stderr so far."""
        self._sink.flush()
        return self._path.read_text(encoding="utf-8", errors="replace")


#: How long to keep retrying the sink's removal. A signalled process on
#: Windows releases its inherited handles some time after ``wait`` returns, so
#: the first unlink can lose to a child that has already exited. The window is
#: milliseconds; this is generous, and removal is best-effort regardless
#: because a few kilobytes of scratch in the system temp dir is not worth
#: failing a test over.
_SINK_REMOVAL_WINDOW_SECONDS = 5.0


@contextlib.contextmanager
def child_stderr() -> Generator[ChildStderr]:
    """Provide a drained stderr channel for one spawned child.

    Yields a handle whose ``sink`` is passed to ``subprocess`` in place of
    ``subprocess.PIPE`` and whose ``read`` returns the child's diagnostics
    whether it exited, hung, or was killed - a pipe loses them in the last two
    cases, which is exactly when they are worth having.
    """
    handle, raw_path = tempfile.mkstemp(prefix="vaultspec-rag-child-stderr-")
    os.close(handle)
    path = Path(raw_path)
    with path.open("wb") as sink:
        try:
            yield ChildStderr(sink, path)
        finally:
            sink.flush()
    _remove_sink(path)


def _remove_sink(path: Path) -> None:
    """Remove the sink once every inherited handle on it has been released."""
    deadline = time.monotonic() + _SINK_REMOVAL_WINDOW_SECONDS
    while True:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            if time.monotonic() >= deadline:
                return
            time.sleep(0.05)
        else:
            return
