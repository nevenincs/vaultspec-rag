"""Download one model repository into the hub cache, as a process of its own.

Run as ``python -m vaultspec_rag.commands._model_download_child <repo>`` by
the model fetch, never imported by it for the download itself. The hub client
moves the default weights with a native transport that nothing in the same
process can interrupt, so a download that must be stoppable has to be a
process: stopping it is then the operating system's job, whatever is moving
the bytes.

This process talks to the hub and reports, and decides nothing. What to fetch,
whether there is room for it, whether what arrived can be trusted, and what a
failure means to the operator all stay with the process that started it. Every
request to the hub is made here, including the one that asks how large the
repository is: a request made by the starting process could not be stopped
either, and a hub that answers it a few bytes at a time would hold that
process for as long as it liked.

Standard output carries one JSON record per line and nothing else:

- ``progress`` - the bytes received so far and the file and byte counts, sent
  whenever they change;
- ``declared`` - the size the hub declares for the revision, sent once, before
  any file is asked for;
- ``done`` - the download completed;
- ``failed`` - it did not, with the failure's class and the hub client's own
  first line.

After ``declared`` nothing is fetched until the reader answers with one line
on standard input saying to go. The reader is the one that knows whether the
download fits, so a download that cannot fit is refused before its first byte.

A process that ends without a ``done`` or ``failed`` record has died, and the
reader treats that as its own kind of failure.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from typing import IO, TYPE_CHECKING, Protocol, cast

from ._hub_failure import classify_hub_failure, first_line
from ._snapshot_progress import SnapshotBars

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = [
    "GO_AHEAD",
    "RECORD_DECLARED",
    "RECORD_DONE",
    "RECORD_FAILED",
    "RECORD_PROGRESS",
    "main",
]

RECORD_PROGRESS = "progress"
RECORD_DECLARED = "declared"
RECORD_DONE = "done"
RECORD_FAILED = "failed"

#: The line the reader sends on standard input to let the download begin.
GO_AHEAD = "go"

#: How often the counts are looked at. Fast enough that the reader's progress
#: line moves, slow enough that a download of an hour is a few thousand lines.
_REPORT_INTERVAL_SECONDS = 0.25

#: Exit status when nobody is waiting for a result any more: the reader went
#: away, or answered the declared size with anything but the go-ahead.
_EXIT_UNREAD = 3


class _Records:
    """Write records to the reader, one JSON document per line."""

    def __init__(self, stream: IO[str]) -> None:
        self._stream = stream
        self._lock = threading.Lock()

    def write(self, record: dict[str, object]) -> None:
        """Send one record, or stop the process when nobody can read it.

        A reader that has gone away - killed, or finished with this download -
        leaves a download nobody is watching, which is exactly what this
        process exists to make impossible. The exit is immediate rather than
        orderly because the native transport's threads would outlive an
        orderly one.
        """
        line = json.dumps(record)
        try:
            with self._lock:
                self._stream.write(line + "\n")
                self._stream.flush()
        except (OSError, ValueError):
            os._exit(_EXIT_UNREAD)


class _Wire:
    """Count the bytes the hub's HTTP session reads off the network.

    The hub client hands a download to its caller in ten-mebibyte pieces, so
    its own counters stand still for as long as a slow transfer takes to fill
    one. The HTTP library underneath counts every response's bytes as they
    arrive; watching the responses themselves is what tells a transfer that
    is slow from one that has stopped.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._open: list[object] = []
        self._settled = 0

    def watch(self, response: object) -> None:
        """Start counting *response*. Installed as a response event hook."""
        with self._lock:
            self._open.append(response)

    def received(self) -> int:
        """Return every byte read so far, across all responses."""
        with self._lock:
            still_open: list[object] = []
            arriving = 0
            for response in self._open:
                # Closed is read first: a response that closes between the two
                # reads is then counted at its final size on the next call
                # rather than dropped short of it on this one.
                closed = bool(getattr(response, "is_closed", True))
                count = getattr(response, "num_bytes_downloaded", 0)
                read = count if isinstance(count, int) else 0
                if closed:
                    self._settled += read
                else:
                    still_open.append(response)
                    arriving += read
            self._open = still_open
            return self._settled + arriving


def _count_wire_bytes(wire: _Wire) -> None:
    """Have every response of the hub's HTTP session reported to *wire*.

    Through the hub client's own factory seam rather than by editing the
    session it has now: the client discards its session after a connection
    error and builds another, and a hook hung on the first would silently
    stop counting on the very links most likely to need it. The replacement
    is built from the session the client built for itself, so it carries the
    same request hooks, redirect policy and timeout.
    """
    from huggingface_hub import get_session, set_client_factory

    template = get_session()
    client_type = type(template)
    request_hooks = list(template.event_hooks["request"])
    response_hooks = [*template.event_hooks["response"], wire.watch]
    follow_redirects = template.follow_redirects
    timeout = template.timeout

    set_client_factory(
        lambda: client_type(
            event_hooks={"request": request_hooks, "response": response_hooks},
            follow_redirects=follow_redirects,
            timeout=timeout,
        )
    )


class _Reporter:
    """Send a ``progress`` record whenever the counts have moved."""

    def __init__(self, records: _Records, wire: _Wire, bars: SnapshotBars) -> None:
        self._records = records
        self._wire = wire
        self._bars = bars
        self._stop = threading.Event()
        self._sent: dict[str, object] | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> _Reporter:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join()
        self._report()

    def _run(self) -> None:
        while not self._stop.wait(_REPORT_INTERVAL_SECONDS):
            self._report()

    def _report(self) -> None:
        counts = self._bars.counts()
        record: dict[str, object] = {
            "record": RECORD_PROGRESS,
            # What the wire carried plus what the client reports moved. The
            # native transport is seen only by the second and a slow plain
            # transfer only by the first, so neither alone tells movement
            # from none; a plain transfer's payload is seen by both, which
            # makes this an activity measure and not a size.
            "received": self._wire.received() + counts.bytes_done,
            "files_done": counts.files_done,
            "files_total": counts.files_total,
            "bytes_done": counts.bytes_done,
            "bytes_total": counts.bytes_total,
        }
        if record != self._sent:
            self._sent = record
            self._records.write(record)


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="vaultspec-rag model download")
    parser.add_argument("repo")
    parser.add_argument("--revision")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


class _SizedApi(Protocol):
    """The one hub call that asks how large a revision is, as used here."""

    def model_info(self, repo_id: str, **kwargs: object) -> object: ...


def _declared_bytes(
    api: _SizedApi, repo: str, revision: str | None, *, timeout: float
) -> int:
    """Return the size the hub declares for *revision*, or 0 when it declares none.

    The request is given the timeout the hub client gives its own request
    for a repository's files. Left unset, the client waits on this one
    without limit, and a hub that accepted it and said nothing would be
    waited on until the progress floor stopped the whole process.

    Raises:
        Exception: Whatever the hub client raises when it cannot answer.
    """
    info = api.model_info(
        repo, revision=revision, files_metadata=True, token=False, timeout=timeout
    )
    siblings = cast("list[object]", getattr(info, "siblings", None) or [])
    declared = [getattr(sibling, "size", None) for sibling in siblings]
    return sum(size for size in declared if isinstance(size, int))


def main(argv: Sequence[str] | None = None) -> int:
    """Download one repository and report how it went."""
    args = _arguments(argv)
    records = _Records(sys.stdout)
    try:
        from huggingface_hub import (
            HfApi,
            constants,
            snapshot_download,  # pyright: ignore[reportUnknownVariableType]  # huggingface_hub stubs partially unknown
        )

        wire = _Wire()
        _count_wire_bytes(wire)
        # The hub ships partial stubs, so the imported symbols are only
        # partially typed; naming the shapes this call site actually uses is
        # what keeps the strict gate honest.
        api = cast("_SizedApi", HfApi())
        download = cast("Callable[..., object]", snapshot_download)
        with SnapshotBars() as bars, _Reporter(records, wire, bars):
            declared = _declared_bytes(
                api,
                args.repo,
                args.revision,
                timeout=constants.HF_HUB_ETAG_TIMEOUT,
            )
            records.write({"record": RECORD_DECLARED, "bytes": declared})
            # Read as bytes and decoded here: a text read would use whatever
            # encoding the parent's environment happened to set.
            answer = sys.stdin.buffer.readline().decode("utf-8", errors="replace")
            if answer.strip() != GO_AHEAD:
                # The reader refused the download or is gone; either way it
                # is not waiting for a result, and nothing was fetched.
                return _EXIT_UNREAD
            download(
                args.repo,
                revision=args.revision,
                token=False,
                force_download=args.force,
                tqdm_class=bars.tqdm_class,
            )
    except Exception as exc:
        records.write(
            {
                "record": RECORD_FAILED,
                "failure": classify_hub_failure(exc).value,
                "message": first_line(exc),
            }
        )
        return 1
    records.write({"record": RECORD_DONE})
    return 0


if __name__ == "__main__":
    sys.exit(main())
