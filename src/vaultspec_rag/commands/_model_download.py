"""Run one model download as a child process that can always be stopped.

The hub client has no bound on a transfer that keeps moving: a hub that sends
a few bytes at a time never trips its read timeout, and the native transport
it uses for the default weights cannot be interrupted from Python at all. A
command that waits on such a download waits for as long as the hub cares to
keep it waiting, and a command started by a broker has nobody to press
Ctrl-C.

So the download runs in a child, and this module watches what the child
reports. Too little for too long, and the child and everything it started are
killed and the caller gets one failed outcome. Killing a process is the one
stop that does not depend on which transport was moving the bytes. An
interrupt of the caller takes the same path.

Every request to the hub is the child's, the first one included: the child
asks how large the repository is and waits, and only when the caller has
judged that size does it fetch anything. This process never opens a
connection to the hub, so there is no request of its own that a hub could
hold it on.

Nothing is decided in the child. It reports bytes, counts, the declared size,
and how it ended; what that means is settled here and by the caller.
"""

from __future__ import annotations

import contextlib
import json
import logging
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TYPE_CHECKING, cast

from .._python_child import module_command
from .._units import human_bytes
from ._hub_failure import HubFailure
from ._model_download_child import (
    GO_AHEAD,
    RECORD_DECLARED,
    RECORD_DONE,
    RECORD_FAILED,
    RECORD_PROGRESS,
)
from ._snapshot_progress import SnapshotCounts

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_LIMITS",
    "DownloadCaller",
    "DownloadOutcome",
    "FetchLimits",
    "download_snapshot",
    "exclusive_fetch",
]

_CHILD_MODULE = "vaultspec_rag.commands._model_download_child"

#: How often the child's reports are looked at when the window is long.
_POLL_SECONDS = 0.5

#: How long a killed process is given to be gone before it is reported as
#: still there. A kill is asynchronous; it is not slow.
_KILL_CONFIRM_SECONDS = 10.0

#: How much of the child's standard error is kept for a failure's detail.
_STDERR_TAIL_LINES = 8

#: Where the one-fetch-at-a-time claim lives inside a hub cache. The hub
#: client keeps its own lock files in this directory and its cache scan skips
#: it, so nothing here is mistaken for a repository.
_LOCK_NAME = ".locks/vaultspec-rag-fetch.lock"
_LOCK_POLL_SECONDS = 0.5


@dataclass(frozen=True, slots=True)
class FetchLimits:
    """How little progress, and how long a wait, a model fetch tolerates.

    Constants with their reasoning, not settings. The floor of one mebibyte in
    ten minutes is about 14 kbit/s; at that rate the default weights would
    take weeks, so no link anyone would wait on is slow enough to be caught by
    it, and a hub that trickles to hold a client open is. Ten minutes is long
    enough to ride out an access point restarting.

    The window is not counted from the moment the download process is
    started. A process takes time to start and to reach the hub - half a
    second measured on an idle machine, a quarter of a minute on one with six
    busy processes to every core - and that is not time in which the hub sent
    too little. So the first window opens when the first byte arrives. It
    opens a minute after the start whatever has happened, so a download that
    never receives anything at all is judged like any other, one window
    later. A minute is four times the slowest start measured, and it costs
    nothing to be generous with: reaching it stops nothing, it only starts
    the clock that can.

    So the longest a download that will never finish is waited on is the
    window plus the wait for a first byte: eleven minutes when nothing ever
    arrives, and ten minutes from its first byte when a hub trickles. The
    look every half second and the ten seconds allowed to confirm the kill
    come on top of either.

    An hour waiting for another process is longer than a first fetch of the
    default models takes on a 10 Mbit/s link; past that, saying who holds the
    cache is more use than waiting in silence.

    They are parameters so a test can run the same code in seconds.
    """

    window_seconds: float = 600.0
    min_bytes: int = 1 << 20
    first_byte_seconds: float = 60.0
    contention_seconds: float = 3600.0


DEFAULT_LIMITS = FetchLimits()


@dataclass(frozen=True, slots=True)
class DownloadOutcome:
    """How one download ended.

    Attributes:
        failure: ``None`` when the repository was downloaded; otherwise why
            it was not.
        message: The detail of a failure, ready to follow the repository id.
            For a refusal it is the caller's own reason, unchanged.
    """

    failure: HubFailure | None = None
    message: str = ""


class _Floor:
    """Judge whether enough has arrived in the window that just passed.

    Nothing is judged until the first window opens: at the first byte, or
    ``first_byte_seconds`` after the download process was started when no
    byte has arrived by then.
    """

    def __init__(self, limits: FetchLimits, started: float) -> None:
        self._limits = limits
        self._opens_by = started + limits.first_byte_seconds
        self._samples: deque[tuple[float, int]] = deque()

    def breached(self, now: float, received: int) -> bool:
        """Record *received* at *now*; say whether the last window fell short.

        The comparison is against the newest sample that is at least a whole
        window old, so the judgement is over a sliding window and a burst at
        the start of the download buys no more than one window of silence.
        """
        if not self._samples and received <= 0 and now < self._opens_by:
            return False
        self._samples.append((now, received))
        horizon = now - self._limits.window_seconds
        while len(self._samples) > 1 and self._samples[1][0] <= horizon:
            self._samples.popleft()
        since, baseline = self._samples[0]
        return since <= horizon and received - baseline < self._limits.min_bytes


class _ChildFeed:
    """Read the child's records, keep the latest of each kind, and answer one.

    The child's ``declared`` record is answered from the reading thread, the
    moment it is read: the child fetches nothing until it is, so answering on
    the watcher's next look would add that wait to every download.
    """

    def __init__(
        self, process: subprocess.Popen[str], admit: Callable[[int], str | None] | None
    ) -> None:
        self._lock = threading.Lock()
        self._received = 0
        self._counts = SnapshotCounts()
        self._terminal: dict[str, object] | None = None
        self._refusal: str | None = None
        self._admit = admit
        self._answers = process.stdin
        self._stderr: deque[str] = deque(maxlen=_STDERR_TAIL_LINES)
        self._threads = (
            threading.Thread(target=self._read_records, args=(process.stdout,)),
            threading.Thread(target=self._read_stderr, args=(process.stderr,)),
        )
        for thread in self._threads:
            thread.daemon = True
            thread.start()

    def _read_records(self, stream: IO[str] | None) -> None:
        for line in stream or ():
            try:
                parsed: object = json.loads(line)
            except ValueError:
                # Only records are expected here; anything else is a library
                # that printed where it should not have, and is not a result.
                continue
            if isinstance(parsed, dict):
                self._take(cast("dict[str, object]", parsed))

    def _take(self, record: dict[str, object]) -> None:
        kind = record.get("record")
        if kind == RECORD_DECLARED:
            self._answer(_int(record.get("bytes")))
            return
        with self._lock:
            if kind == RECORD_PROGRESS:
                self._received = max(self._received, _int(record.get("received")))
                self._counts = SnapshotCounts(
                    _int(record.get("files_done")),
                    _int(record.get("files_total")),
                    _int(record.get("bytes_done")),
                    _int(record.get("bytes_total")),
                )
            elif kind in {RECORD_DONE, RECORD_FAILED}:
                self._terminal = record

    def _answer(self, declared: int) -> None:
        """Let the child download *declared* bytes, or keep it waiting.

        A refusal sends nothing: the child stays where it is, having fetched
        no file, until the watcher sees the refusal and stops it.
        """
        reason = None if self._admit is None else self._admit(declared)
        if reason is not None:
            with self._lock:
                self._refusal = reason
            return
        # A child that died before it could be answered is found by the
        # watcher; there is nobody left to tell.
        with contextlib.suppress(OSError, ValueError):
            if self._answers is not None:
                self._answers.write(GO_AHEAD + "\n")
                self._answers.flush()

    def _read_stderr(self, stream: IO[str] | None) -> None:
        for line in stream or ():
            if line.strip():
                with self._lock:
                    self._stderr.append(line.rstrip())

    def latest(self) -> tuple[int, SnapshotCounts]:
        """Return the bytes received and the counts last reported."""
        with self._lock:
            return self._received, self._counts

    def refusal(self) -> str | None:
        """Return why the caller refused the declared size, if it did."""
        with self._lock:
            return self._refusal

    def finish(self) -> tuple[dict[str, object] | None, str]:
        """Wait for both pipes to end; return the terminal record and stderr."""
        for thread in self._threads:
            thread.join(timeout=_KILL_CONFIRM_SECONDS)
        with self._lock:
            return self._terminal, " | ".join(self._stderr)


def _int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _kill_tree(process: subprocess.Popen[str]) -> list[int]:
    """Kill *process* and everything it started; return the pids still alive.

    The tree, not the process: on Windows the interpreter a virtual
    environment names is a launcher that starts the real one as its child, so
    killing the launcher alone would leave the download running. Descendants
    are witnessed before the parent dies, because afterwards the ancestry can
    no longer be established.

    Only the process's own creation time is read to pin it. Walking its
    ancestry to learn the same thing cost most of a second on an idle machine
    and a quarter of a minute on a loaded one, and the download kept running
    for all of it.
    """
    from .._process_probe import (
        LineageEntry,
        kill_process_descendants,
        pid_start_time,
        wait_for_exit,
    )

    descendants: tuple[LineageEntry, ...] = ()
    if process.poll() is None:
        created = pid_start_time(process.pid)
        if created > 0.0:
            with contextlib.suppress(OSError, ValueError):
                descendants = kill_process_descendants(
                    LineageEntry(process.pid, created)
                )
        with contextlib.suppress(OSError):
            process.kill()
    deadline = time.monotonic() + _KILL_CONFIRM_SECONDS
    survivors: list[int] = []
    try:
        process.wait(timeout=_KILL_CONFIRM_SECONDS)
    except subprocess.TimeoutExpired:
        survivors.append(process.pid)
    survivors.extend(
        descendant.pid
        for descendant in descendants
        if not wait_for_exit(
            descendant.pid, timeout=max(0.0, deadline - time.monotonic())
        )
    )
    return survivors


def _partial_files(blobs: Path) -> set[Path]:
    """Return the unfinished download files the hub client has in *blobs*."""
    if not blobs.is_dir():
        return set()
    return set(blobs.glob("*.incomplete"))


def _stalled(
    process: subprocess.Popen[str], limits: FetchLimits, received: int
) -> DownloadOutcome:
    survivors = _kill_tree(process)
    message = (
        f"stalled: fewer than {human_bytes(limits.min_bytes)} arrived in "
        f"{limits.window_seconds:g} seconds ({human_bytes(received)} in all), "
        "so the download was stopped"
    )
    if survivors:
        message += f"; processes {survivors} could not be confirmed stopped"
    return DownloadOutcome(HubFailure.STALLED, message)


def _refused(process: subprocess.Popen[str], reason: str) -> DownloadOutcome:
    """Stop a child the caller would not let download, which fetched no file."""
    survivors = _kill_tree(process)
    if survivors:
        reason += f"; processes {survivors} could not be confirmed stopped"
    return DownloadOutcome(HubFailure.REFUSED, reason)


def _ended(process: subprocess.Popen[str], feed: _ChildFeed) -> DownloadOutcome:
    """Turn a child that exited on its own into an outcome."""
    terminal, stderr = feed.finish()
    if terminal is not None and terminal.get("record") == RECORD_DONE:
        if process.returncode == 0:
            return DownloadOutcome()
    elif terminal is not None:
        try:
            failure = HubFailure(str(terminal.get("failure")))
        except ValueError:
            failure = HubFailure.UNREACHABLE
        return DownloadOutcome(failure, str(terminal.get("message") or failure.value))
    detail = (
        f"the download process ended with exit code {process.returncode} "
        "and reported no result"
    )
    if stderr:
        detail += f": {stderr}"
    return DownloadOutcome(HubFailure.DIED, detail)


@dataclass(frozen=True, slots=True)
class DownloadCaller:
    """What the caller of a download is told, and what it is asked.

    Attributes:
        on_progress: Called with the counts whenever they change.
        admit: The caller's judgement of the size the hub declares for the
            revision, in bytes (0 when it declares none). Called once, before
            any file is fetched, on a thread of this module's; it returns
            ``None`` to let the download go ahead or the reason it may not.
            It must not raise: the download process is waiting on the answer.
            Omitted, every size is let through.
    """

    on_progress: Callable[[SnapshotCounts], None] | None = None
    admit: Callable[[int], str | None] | None = None


@dataclass(frozen=True, slots=True)
class _Request:
    repo: str
    revision: str | None
    force: bool
    blobs: Path
    limits: FetchLimits
    caller: DownloadCaller


def download_snapshot(
    repo: str,
    *,
    revision: str | None,
    force: bool = False,
    limits: FetchLimits = DEFAULT_LIMITS,
    caller: DownloadCaller | None = None,
) -> DownloadOutcome:
    """Download *repo* into the hub cache in a child process, under the floor.

    Never raises for a download that failed: every way it can end is an
    outcome. An interrupt of the caller is the one exception that passes
    through, after the child has been killed.

    Args:
        repo: The repository id.
        revision: The revision to fetch, or ``None`` for the default branch.
        force: Fetch every file again, replacing what the cache holds.
        limits: The progress floor.
        caller: Where progress is reported and who judges the declared size;
            omitted, nothing is reported and every size is let through.

    Returns:
        How the download ended.
    """
    from huggingface_hub import constants
    from huggingface_hub.file_download import repo_folder_name

    # Where the hub client keeps a file it has not finished. A killed child
    # cannot remove its own, so the ones that appear during this call are
    # removed once it is dead.
    blobs = (
        Path(constants.HF_HUB_CACHE)
        / repo_folder_name(repo_id=repo, repo_type="model")
        / "blobs"
    )
    return _run(
        _Request(repo, revision, force, blobs, limits, caller or DownloadCaller())
    )


def _run(request: _Request) -> DownloadOutcome:
    command = module_command(sys.executable, _CHILD_MODULE, request.repo)
    if request.revision is not None:
        command += ["--revision", request.revision]
    if request.force:
        command.append("--force")
    before = _partial_files(request.blobs)
    # The environment is this process's own: the hub endpoint and the offline
    # switch were settled before any command body ran, and the child must see
    # exactly what this process would have used.
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    feed = _ChildFeed(process, request.caller.admit)
    # A child that ends on its own removes the file it could not finish. One
    # that was stopped, or died, did not get the chance.
    unfinished = True
    try:
        outcome = _watch(process, feed, request)
        unfinished = outcome.failure in {HubFailure.STALLED, HubFailure.DIED}
        return outcome
    finally:
        if process.poll() is None:
            _kill_tree(process)
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe is not None:
                # Closing the answering pipe of a dead child can report the
                # line it never read; there is nothing to do about that.
                with contextlib.suppress(OSError):
                    pipe.close()
        if unfinished:
            # Only what appeared during this call. Under the fetch claim no
            # other fetch of this package is writing here; a file another tool
            # was writing at the same moment would be taken too.
            for leftover in _partial_files(request.blobs) - before:
                with contextlib.suppress(OSError):
                    leftover.unlink()


def _watch(
    process: subprocess.Popen[str], feed: _ChildFeed, request: _Request
) -> DownloadOutcome:
    limits = request.limits
    floor = _Floor(limits, time.monotonic())
    poll = min(_POLL_SECONDS, limits.window_seconds / 4)
    shown = SnapshotCounts()
    while True:
        try:
            process.wait(timeout=poll)
            exited = True
        except subprocess.TimeoutExpired:
            exited = False
        received, counts = feed.latest()
        if request.caller.on_progress is not None and counts != shown:
            shown = counts
            request.caller.on_progress(counts)
        if exited:
            return _ended(process, feed)
        refusal = feed.refusal()
        if refusal is not None:
            return _refused(process, refusal)
        if floor.breached(time.monotonic(), received):
            return _stalled(process, limits, received)


@contextlib.contextmanager
def exclusive_fetch(
    cache: Path,
    *,
    limits: FetchLimits = DEFAULT_LIMITS,
    on_wait: Callable[[str], None] | None = None,
) -> Generator[str | None]:
    """Hold this cache's one-fetch-at-a-time claim for the block.

    Two commands fetching the same repository would otherwise meet inside the
    hub client, where the second waits on the first's file lock and receives
    nothing while it does - which the progress floor would read as a stalled
    download and stop. The claim makes the second wait here instead, where
    waiting is not mistaken for failing, and then look at the cache again.

    It is an operating-system claim on a file, so it is released when its
    holder ends however it ends.

    Yields:
        ``None`` when the block may fetch, or a sentence saying who still
        held the cache after the wait ran out. A cache in which the claim
        cannot be taken at all yields ``None``: the fetch goes ahead and
        reports whatever is wrong with the directory itself.
    """
    from .._anchor_claim import claim_anchor, record_claim_owner, release_anchor_claim

    lock_path = cache / _LOCK_NAME
    started = time.monotonic()
    announced = False
    while True:
        claim = claim_anchor(lock_path, pid_record=True, create_parent=True)
        if claim.descriptor is not None or claim.fault is not None:
            break
        holder = (
            f"process {claim.holder_pid}" if claim.holder_pid else "another process"
        )
        remaining = limits.contention_seconds - (time.monotonic() - started)
        if remaining <= 0:
            yield (
                f"{holder} was still downloading models into {cache} after "
                f"{limits.contention_seconds:g} seconds"
            )
            return
        if not announced:
            announced = True
            if on_wait is not None:
                on_wait(f"Waiting for {holder} to finish downloading models...")
        time.sleep(min(_LOCK_POLL_SECONDS, remaining))
    if claim.descriptor is None:
        logger.debug("no fetch claim could be taken in %s: %s", cache, claim.fault)
        yield None
        return
    try:
        # The record only lets a waiter name this process. The claim itself is
        # what excludes, so a record that cannot be written costs a waiter a
        # name and nothing else.
        with contextlib.suppress(OSError):
            record_claim_owner(claim.descriptor)
        yield None
    finally:
        release_anchor_claim(claim.descriptor, pid_record=True)
