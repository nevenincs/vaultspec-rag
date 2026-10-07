"""The Qdrant download and install against sources and disks that fail.

Every network condition here is a real server doing the thing on a real
loopback socket: refusing, accepting and then saying nothing, trickling,
resetting, sending less or more than it promised, answering with an error
status, redirecting where it may not or in a loop, presenting a certificate
the client was never told about. Nothing in the code under test is replaced.

Each condition is held to the same four outcomes at the install: one failed
report that says what to do, no working file left behind, the previous
install still verifying, and the next attempt succeeding with no cleanup in
between.

Disk exhaustion is reproduced as far as an unprivileged test can:

- **Not enough room before the first byte.** The measurement is the operating
  system's own reading of the volume. What makes it insufficient is the
  request, which asks for a reserve larger than the volume has free. No free
  space figure is invented.
- **A write that fails after the check passed.** A full volume cannot be
  staged without privileges, so this one is simulated, at the narrowest point
  there is: the staging file the install opens is real and on disk, and it is
  wrapped so that its ``write`` raises ``OSError(ENOSPC)`` once a set number
  of bytes are down. The error is constructed by the test; the kernel did not
  return it. Everything after the raise - what the install reports, removes
  and leaves alone - is the shipped code running for real.
"""

from __future__ import annotations

import errno
import io
import re
import threading
import time
from dataclasses import dataclass, replace
from http import HTTPStatus
from typing import IO, TYPE_CHECKING, cast

import pytest

from .._store_writes import free_bytes
from .._sync_vocabulary import ProvisionAction
from ..config._types import EnvVar
from ..qdrant_runtime._constants import MANIFEST_FILENAME
from ..qdrant_runtime._download import (
    DownloadError,
    DownloadFailure,
    DownloadLimits,
    download_https,
)
from ..qdrant_runtime._provision import (
    _install,
    _open_staging,
    verify_native_binary,
)
from ..qdrant_runtime._resolve import binary_filename, qdrant_bin_dir
from ._loopback_tls import (
    LOOPBACK_HOST,
    LoopbackSources,
    send_bytes,
    send_endless,
    send_redirect,
    send_then_reset,
    send_trickle,
    send_truncated,
    send_undelimited,
    stay_silent,
    trickle_headers,
    trusted_loopback_sources,
)
from ._stand_in_release import (
    ARCHIVE_SHAPES,
    NEW_EXECUTABLE,
    build_archive,
    install_request,
    release_archive,
    sha256_hex,
    working_files,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

    from ..qdrant_runtime._provision import _InstallRequest
    from ._http_stubs import QuietHandler

pytestmark = [pytest.mark.unit]

_ALLOWED = frozenset({LOOPBACK_HOST})
_BODY = b"a stand-in body, sent in more than one write. " * 512

#: Limits small enough that every bound is reached in well under a second,
#: with the production number of attempts.
_QUICK = DownloadLimits(
    deadline_seconds=20.0, stall_seconds=0.4, retry_base_seconds=0.02
)

_BASE_URL_SETTING = EnvVar.QDRANT_RELEASE_BASE_URL.value
#: The whole command that repeats an install over an existing one.
_UPGRADE_COMMAND = "`vaultspec-rag server qdrant install --upgrade`"
_HOSTS_SETTING = EnvVar.QDRANT_DOWNLOAD_HOSTS.value


@pytest.fixture
def sources(tmp_path: Path) -> Generator[LoopbackSources]:
    with trusted_loopback_sources(tmp_path / "tls") as started:
        yield started


@pytest.fixture
def version_dir(isolated_singleton_dirs: Path) -> Path:
    """The managed version dir, relocated under the test's temp dir."""
    del isolated_singleton_dirs
    return qdrant_bin_dir()


class _InOrder:
    """Answer successive requests with successive responders, then the last."""

    def __init__(self, *responders: Callable[[QuietHandler], None]) -> None:
        self._responders = responders
        self._guard = threading.Lock()
        self._served = 0

    def __call__(self, handler: QuietHandler) -> None:
        with self._guard:
            index = min(self._served, len(self._responders) - 1)
            self._served += 1
        self._responders[index](handler)


def _status(code: HTTPStatus) -> Callable[[QuietHandler], None]:
    return lambda handler: send_bytes(handler, b"stand-in refusal", status=code)


def _fetch(url: str, limits: DownloadLimits = _QUICK) -> DownloadError:
    """Download *url* into memory and return the failure it must end in."""
    with pytest.raises(DownloadError) as failed:
        download_https(url, io.BytesIO(), redirect_hosts=_ALLOWED, limits=limits)
    return failed.value


class TestRetry:
    """Only a failure of the transport earns another attempt, and only a few."""

    def test_transient_failures_are_retried_and_each_attempt_starts_over(
        self, sources: LoopbackSources
    ) -> None:
        """A dropped transfer and a busy source are both tried again.

        The first answer promises the whole body and hangs up partway, having
        sent bytes the real body does not contain. Were an attempt to keep
        what the one before it wrote, they would survive in the result.

        Mutation: removed the rewind and truncate at the start of
        ``_fetch_once``. Observed the content assertion fail: the result
        began with the dropped attempt's bytes. Then removed the short-body
        check in ``_stream_capped``. Observed the request-count assertion
        fail (``1 == 3``): the dropped transfer was accepted as complete.
        Restored after each; passes.
        """
        dropped = b"\xff" * 4096
        source = sources.serve(
            _InOrder(
                lambda handler: send_truncated(handler, dropped, declared=len(_BODY)),
                _status(HTTPStatus.SERVICE_UNAVAILABLE),
                lambda handler: send_bytes(handler, _BODY),
            )
        )
        out = io.BytesIO()
        lines: list[str] = []

        download_https(
            source.url("/asset.bin"),
            out,
            redirect_hosts=_ALLOWED,
            on_progress=lines.append,
            limits=_QUICK,
        )

        assert len(source.requests) == 3
        assert out.getvalue() == _BODY
        # Each retry is announced, so a slow first attempt does not read as a
        # hung command.
        retries = [line for line in lines if "retrying" in line]
        assert len(retries) == 2
        assert "attempt 2 of 3" in retries[0]
        assert "attempt 3 of 3" in retries[1]

    def test_retries_stop_at_the_bound(self, sources: LoopbackSources) -> None:
        """A source that stays busy is given up on after three attempts.

        The deadline is long enough for many more attempts to start, so only
        the attempt bound can be what stops at three.

        Mutation: made ``_retry_delay`` ignore the attempt count. Observed the
        attempts assertion fail (``7 == 3``), the deadline being what finally
        ended the run. Restored; passes.
        """
        source = sources.serve(_status(HTTPStatus.SERVICE_UNAVAILABLE))

        failure = _fetch(
            source.url("/asset.bin"), replace(_QUICK, deadline_seconds=2.0)
        )

        assert failure.kind is DownloadFailure.UNAVAILABLE
        assert failure.status == HTTPStatus.SERVICE_UNAVAILABLE
        assert failure.attempts == 3
        assert len(source.requests) == 3

    def test_a_refusal_is_not_retried(self, sources: LoopbackSources) -> None:
        """An answer that will not change is asked for once.

        Mutation: added the not-found kind to the transient set. Observed the
        attempts assertion fail (``3 == 1``). Restored; passes.
        """
        source = sources.serve(_status(HTTPStatus.NOT_FOUND))

        failure = _fetch(source.url("/asset.bin"))

        assert failure.kind is DownloadFailure.NOT_FOUND
        assert failure.attempts == 1
        assert len(source.requests) == 1


def _trickle_body(handler: QuietHandler) -> None:
    """Send a body one small piece at a time, five seconds end to end."""
    send_trickle(handler, pieces=100, piece=b"\0" * 512, interval=0.05)


def _trickle_head(handler: QuietHandler) -> None:
    """Send a response head one line at a time, for over four seconds."""
    trickle_headers(handler, lines=90, interval=0.05)


class TestDeadline:
    """The whole download is bounded, wherever in it the source dawdles."""

    @pytest.mark.parametrize(
        "dawdle",
        [
            pytest.param(_trickle_body, id="body"),
            pytest.param(_trickle_head, id="response head"),
        ],
    )
    def test_a_trickling_source_is_cut_at_the_deadline(
        self, sources: LoopbackSources, dawdle: Callable[[QuietHandler], None]
    ) -> None:
        """A source that never goes quiet long enough to stall is still bounded.

        Each source keeps sending for more than four seconds, a piece at a
        time, so no single read ever waits out the stall limit. Only the
        deadline can end the transfer, and it has to end it wherever the
        trickle is: in the body, where the reads return and a clock could be
        checked between them, and in the response head, where the client is
        inside one library call until the head is complete.

        The body is bounded twice over, by the clock checked between reads
        and by the timer that hangs the socket up; the response head only by
        the timer. All three combinations were run.

        Mutation: stopped the deadline's timer from hanging anything up.
        Observed the response-head case fail on the elapsed assertion, the
        call returning only when the source had finished after 4.6 seconds;
        the body case passed, on the check between reads. Then removed that
        check too. Observed both cases fail on the elapsed assertion. Then
        restored the timer alone. Observed both pass, the body now cut by the
        timer. Restored the check; passes.

        The third run first failed for the body, which is how a defect was
        found: the timer held each connection, and a connection lets go of
        its socket once the response head is read, so the body was never
        hung up. The deadline now holds the socket itself.
        """
        source = sources.serve(dawdle)
        started = time.monotonic()

        failure = _fetch(
            source.url("/asset.bin"),
            DownloadLimits(deadline_seconds=0.5, stall_seconds=30.0),
        )

        assert failure.kind is DownloadFailure.TOO_SLOW
        assert "did not finish within its 0.5 second limit" in str(failure)
        assert time.monotonic() - started < 2.0
        # Running out of time is not a fault another attempt would cure.
        assert len(source.requests) == 1

    def test_a_read_the_deadline_hung_up_on_is_reported_as_the_deadline(
        self, sources: LoopbackSources
    ) -> None:
        """What the hung-up read raises is the deadline's doing, and says so.

        The source promises no length and sends a piece every fifth of a
        second, so when the deadline hangs the connection up the client is
        inside a read with most of its own timeout still to run. That read
        fails with a connection error: an aborted connection on Windows, a
        broken pipe on Linux. Taken at face value either is a transport fault
        worth another attempt, which a transfer that has run out of time must
        not get.

        Mutation: removed the test in ``download_https`` for whether the
        deadline had passed when an attempt failed. Observed the kind
        assertion fail, the failure sorted as an unreachable source.
        Restored; passes. Run on Windows and on Linux.
        """
        source = sources.serve(
            lambda handler: send_trickle(
                handler, pieces=25, piece=b"\0" * 512, interval=0.2, declare=False
            )
        )

        failure = _fetch(
            source.url("/asset.bin"),
            DownloadLimits(deadline_seconds=0.5, stall_seconds=30.0),
        )

        assert failure.kind is DownloadFailure.TOO_SLOW

    def test_a_retry_that_cannot_start_before_the_deadline_is_not_made(
        self, sources: LoopbackSources
    ) -> None:
        """The refusal is reported as it stands when no retry can fit.

        Mutation: made ``_retry_delay`` return the wait whether or not it fits
        before the deadline. Observed the kind assertion fail as too slow,
        after the wait had been slept through. Restored; passes.
        """
        source = sources.serve(_status(HTTPStatus.SERVICE_UNAVAILABLE))

        failure = _fetch(
            source.url("/asset.bin"),
            # The wait before a second attempt is longer than the time left,
            # however the jitter falls: at least three quarters of the base.
            # The deadline is seconds, not a fraction of one, because it also
            # covers the handshake and the refusal, and a first attempt that
            # overruns it ends as too slow before any retry is weighed.
            DownloadLimits(
                deadline_seconds=5.0,
                retry_base_seconds=20.0,
                retry_cap_seconds=20.0,
            ),
        )

        assert failure.kind is DownloadFailure.UNAVAILABLE
        assert len(source.requests) == 1


class TestSizeCap:
    def test_a_response_declaring_more_than_the_cap_is_refused_unread(
        self, sources: LoopbackSources
    ) -> None:
        """The declared size is judged before any of the body is taken.

        The source would send eight megabytes. The caller's file must stay
        empty, which it cannot if the cap is only noticed as the bytes pile
        up.

        Mutation: removed the declared-size check in ``_fetch_once``. Observed
        the empty-file assertion fail, with the bytes up to the cap written.
        Restored; passes.
        """
        total = 8 << 20
        source = sources.serve(
            lambda handler: send_endless(handler, total=total, declared=total)
        )
        out = io.BytesIO()

        with pytest.raises(DownloadError) as failed:
            download_https(
                source.url("/asset.bin"),
                out,
                redirect_hosts=_ALLOWED,
                limits=DownloadLimits(max_bytes=1 << 20),
            )

        assert failed.value.kind is DownloadFailure.TOO_LARGE
        assert out.getvalue() == b""
        assert "refusing to start" in str(failed.value)
        assert len(source.requests) == 1

    def test_a_body_that_outgrows_the_cap_undeclared_is_cut_off(
        self, sources: LoopbackSources
    ) -> None:
        source = sources.serve(lambda handler: send_endless(handler, total=8 << 20))
        out = io.BytesIO()

        with pytest.raises(DownloadError) as failed:
            download_https(
                source.url("/asset.bin"),
                out,
                redirect_hosts=_ALLOWED,
                limits=DownloadLimits(max_bytes=1 << 20),
            )

        assert failed.value.kind is DownloadFailure.TOO_LARGE
        assert len(out.getvalue()) <= 1 << 20
        assert len(source.requests) == 1


class _FailingWrites:
    """A real open file whose ``write`` raises once enough bytes are down.

    Stands in for a volume that fills partway through a write. The file is
    real and so is everything written before the limit; the error raised at
    the limit is built here, not returned by the operating system.
    """

    def __init__(self, handle: IO[bytes], *, fail_after: int) -> None:
        self._handle = handle
        self._room = fail_after

    def write(self, data: bytes) -> int:
        if len(data) > self._room:
            self._handle.write(data[: self._room])
            self._room = 0
            raise OSError(errno.ENOSPC, "No space left on device")
        self._room -= len(data)
        return self._handle.write(data)

    def __getattr__(self, name: str) -> object:
        return getattr(self._handle, name)

    def __enter__(self) -> IO[bytes]:
        return cast("IO[bytes]", self)

    def __exit__(self, *exc_info: object) -> None:
        self._handle.close()


def _fills_up(
    label_part: str, *, fail_after: int
) -> Callable[[Path, str], tuple[Path, IO[bytes]]]:
    """Open staging files for real, failing writes to the one *label_part* names."""

    def open_staging(directory: Path, label: str) -> tuple[Path, IO[bytes]]:
        path, handle = _open_staging(directory, label)
        if label_part not in label:
            return path, handle
        return path, cast("IO[bytes]", _FailingWrites(handle, fail_after=fail_after))

    return open_staging


class TestLocalWrite:
    def test_a_failed_write_is_the_disk_s_failure_and_is_not_retried(
        self, sources: LoopbackSources, tmp_path: Path
    ) -> None:
        """Asking the source again cannot cure a write that failed here.

        Mutation: let the failed write leave ``_stream_capped`` as the bare
        ``OSError``. Observed the kind assertion fail: the error was sorted
        as an unreachable source, which is retried. Restored; passes.
        """
        source = sources.serve(lambda handler: send_bytes(handler, _BODY))
        with (tmp_path / "out.bin").open("w+b") as real:
            out = cast("IO[bytes]", _FailingWrites(real, fail_after=1000))

            with pytest.raises(DownloadError) as failed:
                download_https(
                    source.url("/asset.bin"),
                    out,
                    redirect_hosts=_ALLOWED,
                    limits=_QUICK,
                )

        assert failed.value.kind is DownloadFailure.WRITE_FAILED
        assert isinstance(failed.value.__cause__, OSError)
        assert failed.value.__cause__.errno == errno.ENOSPC
        assert len(source.requests) == 1

    def test_a_file_that_cannot_be_written_at_all_is_refused_before_any_request(
        self, sources: LoopbackSources, tmp_path: Path
    ) -> None:
        """A real refusal from a real file: one opened for reading only."""
        source = sources.serve(lambda handler: send_bytes(handler, _BODY))
        target = tmp_path / "read-only.bin"
        target.write_bytes(b"left as it was")

        with target.open("rb") as out, pytest.raises(DownloadError) as failed:
            download_https(
                source.url("/asset.bin"), out, redirect_hosts=_ALLOWED, limits=_QUICK
            )

        assert failed.value.kind is DownloadFailure.WRITE_FAILED
        assert source.requests == []
        assert target.read_bytes() == b"left as it was"


@dataclass(frozen=True)
class _Degraded:
    """One way a source can fail, and what the install must make of it.

    Attributes:
        start: Starts the failing source and returns the URL to install from
            and a count of the requests or connections it has seen.
        says: Text the report must carry: what happened, then what to do.
        attempts: How many times the source must have been asked, or ``None``
            where there is no server to count them.
        limits: The bounds the attempt runs under.
        within: The longest the attempt may take.
    """

    start: Callable[[LoopbackSources], tuple[str, Callable[[], int]]]
    says: tuple[str, ...]
    attempts: int | None
    limits: DownloadLimits = _QUICK
    within: float = 5.0


def _serving(
    respond: Callable[[QuietHandler], None], *, trusted: bool = True
) -> Callable[[LoopbackSources], tuple[str, Callable[[], int]]]:
    def start(sources: LoopbackSources) -> tuple[str, Callable[[], int]]:
        source = sources.serve(respond, trusted=trusted)
        return source.url("/asset"), lambda: len(source.requests)

    return start


def _silent(sources: LoopbackSources) -> tuple[str, Callable[[], int]]:
    listener = sources.serve_silence()
    return listener.url("/asset"), lambda: listener.connections


def _redirecting_off_the_hosts(
    sources: LoopbackSources,
) -> tuple[str, Callable[[], int]]:
    # The same address under a name the request does not allow.
    elsewhere = sources.serve(lambda handler: send_bytes(handler, _BODY))
    target = elsewhere.url("/blob").replace(LOOPBACK_HOST, "localhost")
    source = sources.serve(lambda handler: send_redirect(handler, target))
    return source.url("/asset"), lambda: len(source.requests) + len(elsewhere.requests)


def _unresolvable(sources: LoopbackSources) -> tuple[str, Callable[[], int]]:
    """Name a source under the reserved domain no resolver answers for."""
    del sources
    return "https://qdrant-mirror.invalid/asset", lambda: 0


_DEGRADED: dict[str, _Degraded] = {
    "connection refused": _Degraded(
        start=lambda sources: (sources.refused_url("/asset"), lambda: 0),
        says=("after 3 attempts", "network connection", _BASE_URL_SETTING),
        attempts=None,
        # A refused loopback connection takes a second or more to be reported
        # on Windows, so the stall limit must not get there first.
        limits=replace(_QUICK, stall_seconds=10.0),
        within=20.0,
    ),
    "accepted, then silent": _Degraded(
        start=_silent,
        says=("stopped responding", "0.4 second stall limit", "after 3 attempts"),
        attempts=3,
    ),
    "request read, then silent": _Degraded(
        start=_serving(stay_silent),
        says=("stopped responding", "after 3 attempts"),
        attempts=3,
    ),
    "trickle slower than the deadline": _Degraded(
        start=_serving(_trickle_body),
        says=("did not finish within its 0.5 second limit", "faster connection"),
        attempts=1,
        limits=DownloadLimits(deadline_seconds=0.5, stall_seconds=30.0),
    ),
    "reset mid-body": _Degraded(
        start=_serving(lambda h: send_then_reset(h, _BODY[:4096], declared=len(_BODY))),
        says=("connection to the source failed", "after 3 attempts"),
        attempts=3,
    ),
    "body shorter than declared": _Degraded(
        start=_serving(lambda h: send_truncated(h, _BODY[:4096], declared=len(_BODY))),
        says=(f"ended after 4096 of {len(_BODY)} bytes", "after 3 attempts"),
        attempts=3,
    ),
    "body longer than the cap": _Degraded(
        start=_serving(lambda h: send_endless(h, total=4 << 20)),
        says=("byte cap", "not serving the release asset", _BASE_URL_SETTING),
        attempts=1,
        limits=replace(_QUICK, max_bytes=1 << 20),
    ),
    "HTTP 404": _Degraded(
        start=_serving(_status(HTTPStatus.NOT_FOUND)),
        says=("HTTP 404 Not Found", _BASE_URL_SETTING, "publishes stand-in-asset.zip"),
        attempts=1,
    ),
    "HTTP 429": _Degraded(
        start=_serving(_status(HTTPStatus.TOO_MANY_REQUESTS)),
        says=("HTTP 429 Too Many Requests", "after 3 attempts", "Wait"),
        attempts=3,
    ),
    "HTTP 503": _Degraded(
        start=_serving(_status(HTTPStatus.SERVICE_UNAVAILABLE)),
        says=("HTTP 503 Service Unavailable", "after 3 attempts", "Wait"),
        attempts=3,
    ),
    "redirect to a host outside the set": _Degraded(
        start=_redirecting_off_the_hosts,
        says=("disallowed host 'localhost'", _HOSTS_SETTING),
        attempts=1,
    ),
    "redirect loop": _Degraded(
        start=_serving(lambda h: send_redirect(h, h.path)),
        says=("redirect that cannot be followed", _BASE_URL_SETTING),
        # The standard opener follows a repeated redirect four times before
        # it calls it a loop.
        attempts=5,
    ),
    "untrusted certificate": _Degraded(
        start=_serving(lambda h: send_bytes(h, _BODY), trusted=False),
        says=("certificate could not be verified", "SSL_CERT_FILE", "never skipped"),
        # The handshake is refused, so no request is ever made.
        attempts=0,
    ),
    "unresolvable host": _Degraded(
        start=_unresolvable,
        says=("host name could not be resolved", "after 3 attempts", _BASE_URL_SETTING),
        attempts=None,
        within=30.0,
    ),
}


def _install_healthy(
    sources: LoopbackSources, version_dir: Path, executable: bytes
) -> _InstallRequest:
    """Install *executable* from a healthy source and return the request used."""
    asset = ARCHIVE_SHAPES[0]
    archive = release_archive(asset, executable)
    source = sources.serve(lambda handler: send_bytes(handler, archive))
    request = replace(
        install_request(
            source.url(f"/{asset}"), version_dir, asset=asset, pinned_archive=archive
        ),
        executable_sha256=sha256_hex(executable),
    )
    report = _install(request)
    assert report.action in {ProvisionAction.CREATED, ProvisionAction.UPDATED}, (
        report.message
    )
    assert (version_dir / binary_filename()).read_bytes() == executable
    return request


_PRIOR_EXECUTABLE = b"the executable installed before anything went wrong\x00" * 64


def _assert_failed_cleanly(
    version_dir: Path, prior: _InstallRequest, prior_manifest: bytes
) -> None:
    """Nothing is left behind and the previous install still verifies."""
    assert working_files(version_dir) == []
    # The shipped verifier, against the digest the previous install was held to.
    verify_native_binary(version_dir / binary_filename(), prior.executable_sha256)
    assert (version_dir / MANIFEST_FILENAME).read_bytes() == prior_manifest


class TestDegradedSource:
    @pytest.mark.parametrize("condition", _DEGRADED.values(), ids=_DEGRADED)
    def test_the_install_fails_once_and_cleanly_and_the_next_attempt_succeeds(
        self, sources: LoopbackSources, version_dir: Path, condition: _Degraded
    ) -> None:
        """One failed outcome with a remedy, nothing left over, nothing lost.

        Mutation: moved the staging cleanup in ``_install`` out
        of ``finally`` and onto the success path. Observed every condition
        fail on the working-file assertion, each listing the staging archive
        it had left. Then, with that restored, reworded the remedy for an
        unreachable source to end "then run the command again". Observed
        the six conditions that carry it fail on the command assertion.
        Restored after each; passes.
        """
        prior = _install_healthy(sources, version_dir, _PRIOR_EXECUTABLE)
        prior_manifest = (version_dir / MANIFEST_FILENAME).read_bytes()
        url, seen = condition.start(sources)
        asset = ARCHIVE_SHAPES[0]
        request = replace(
            install_request(
                url, version_dir, asset=asset, pinned_archive=release_archive(asset)
            ),
            previously="healthy",
            limits=condition.limits,
        )

        started = time.monotonic()
        report = _install(request)
        elapsed = time.monotonic() - started

        assert report.action == ProvisionAction.FAILED
        for text in condition.says:
            assert text in report.message
        if condition.attempts is not None:
            assert seen() == condition.attempts
        assert elapsed < condition.within
        # Whatever went wrong, the remedy names a whole command. This text
        # is also read by someone who ran a start, where "the command" is
        # not the install and "--upgrade" is not a flag.
        assert _UPGRADE_COMMAND in report.message
        assert "command again" not in report.message
        _assert_failed_cleanly(version_dir, prior, prior_manifest)

        _install_healthy(sources, version_dir, NEW_EXECUTABLE)
        assert working_files(version_dir) == []


def _a_volume_this_short(version_dir: Path, shortfall: int, needs: int) -> int:
    """Return the reserve that leaves the real volume *shortfall* bytes short.

    The free space is whatever the operating system reports for the volume
    holding *version_dir* at this moment; *needs* is what the step under test
    writes besides the reserve.
    """
    version_dir.mkdir(parents=True, exist_ok=True)
    free = free_bytes(version_dir)
    assert free is not None, "the test volume cannot be measured"
    return free - needs + shortfall


_UNIT_BYTES = {"B": 1, "KiB": 1 << 10, "MiB": 1 << 20, "GiB": 1 << 30, "TiB": 1 << 40}


def _named_shortfall(message: str) -> float:
    """Return, in bytes, how much more space *message* asks the operator for."""
    asked = re.search(
        r"Free ([0-9.]+) (B|KiB|MiB|GiB|TiB) more on that volume", message
    )
    assert asked is not None, message
    return float(asked.group(1)) * _UNIT_BYTES[asked.group(2)]


class TestFreeSpace:
    """Room is checked before it is spent, and a full disk is one outcome."""

    def test_a_download_that_cannot_fit_is_refused_before_its_first_byte(
        self, sources: LoopbackSources, version_dir: Path
    ) -> None:
        """The response's declared size decides, before any of it is read.

        The volume is measured for real. The request asks for more reserve
        than it has free, by a gigabyte, so the shortfall the report names is
        real arithmetic on a real reading. The source holds its body back
        until it is told the client has stopped listening, so a client that
        read even one byte of it would hang here instead of failing.

        Mutation: removed the space check made when the response arrives.
        Observed the message assertion fail: with no refusal the install
        waited for a body the source never sends, three times over, and
        reported a source that had stopped responding. Restored; passes.
        """
        prior = _install_healthy(sources, version_dir, _PRIOR_EXECUTABLE)
        prior_manifest = (version_dir / MANIFEST_FILENAME).read_bytes()
        asset = ARCHIVE_SHAPES[0]
        archive = release_archive(asset)

        def head_only(handler: QuietHandler) -> None:
            handler.send_response(HTTPStatus.OK)
            handler.send_header("Content-Length", str(len(archive)))
            handler.end_headers()
            stay_silent(handler)

        source = sources.serve(head_only)
        # Five times the archive: the archive, and four more for the
        # executable it is assumed to hold.
        reserve = _a_volume_this_short(version_dir, 1 << 30, needs=5 * len(archive))
        request = replace(
            install_request(
                source.url(f"/{asset}"),
                version_dir,
                asset=asset,
                pinned_archive=archive,
            ),
            previously="healthy",
            limits=_QUICK,
            reserve_bytes=reserve,
        )

        report = _install(request)

        assert report.action == ProvisionAction.FAILED
        assert "Not enough free space" in report.message
        assert str(version_dir) in report.message
        # The shortfall is named: the gigabyte asked for, give or take what
        # else wrote to the volume between this test's reading and the
        # install's.
        assert abs(_named_shortfall(report.message) - (1 << 30)) < 256 << 20
        assert f"then run {_UPGRADE_COMMAND}" in report.message
        assert len(source.requests) == 1
        _assert_failed_cleanly(version_dir, prior, prior_manifest)

    def test_an_extraction_that_cannot_fit_is_refused_before_its_first_byte(
        self, sources: LoopbackSources, version_dir: Path
    ) -> None:
        """The verified archive says exactly what extraction will write.

        The stand-in executable is 256 MiB of zeros, which compress to a few
        hundred kilobytes, so the estimate made when the response arrives is
        far too low and passes. The exact size is what refuses, and it must
        do so before a staging file for the executable exists.

        Mutation: removed the space check made before extraction. Observed
        the action assertion fail (``updated`` where ``failed`` was
        required): the 256 MiB were written. Restored; passes.
        """
        prior = _install_healthy(sources, version_dir, _PRIOR_EXECUTABLE)
        prior_manifest = (version_dir / MANIFEST_FILENAME).read_bytes()
        asset = ARCHIVE_SHAPES[0]
        executable = bytes(256 << 20)
        archive = build_archive(asset, {binary_filename(): executable})
        assert len(archive) < 1 << 20
        source = sources.serve(lambda handler: send_bytes(handler, archive))
        # Short by half the executable: far more than the estimate needs, far
        # less than the extraction does.
        reserve = _a_volume_this_short(version_dir, 128 << 20, needs=len(executable))
        staged: list[str] = []

        def recording(directory: Path, label: str) -> tuple[Path, IO[bytes]]:
            staged.append(label)
            return _open_staging(directory, label)

        request = replace(
            install_request(
                source.url(f"/{asset}"),
                version_dir,
                asset=asset,
                pinned_archive=archive,
            ),
            executable_sha256=sha256_hex(executable),
            previously="healthy",
            reserve_bytes=reserve,
            open_staging=recording,
        )

        report = _install(request)

        assert report.action == ProvisionAction.FAILED, report.message
        assert "Not enough free space" in report.message
        assert "256.0 MiB for the executable it holds" in report.message
        # Only the archive was ever staged.
        assert staged == [asset]
        _assert_failed_cleanly(version_dir, prior, prior_manifest)

    @pytest.mark.parametrize(
        ("stage", "fail_after"),
        [
            # The stand-in archive compresses to a few hundred bytes, so its
            # write has to fail early to fail at all.
            pytest.param("stand-in-asset", 64, id="while the archive arrives"),
            pytest.param(
                binary_filename(), 1000, id="while the executable is extracted"
            ),
        ],
    )
    def test_a_write_that_fails_after_the_check_passed_is_one_clean_failure(
        self, sources: LoopbackSources, version_dir: Path, stage: str, fail_after: int
    ) -> None:
        """A volume that fills mid-write costs the operator nothing installed.

        Simulated, as the module docstring says: the staging file is real,
        and its ``write`` raises a constructed ``OSError(ENOSPC)`` once
        *fail_after* bytes are down. Those bytes are really on disk when it
        does.

        Mutation: dropped the disk-full branch of ``_failure_message``.
        Observed the message assertion fail: the report carried the bare
        error text and no remedy. Restored; passes.
        """
        prior = _install_healthy(sources, version_dir, _PRIOR_EXECUTABLE)
        prior_manifest = (version_dir / MANIFEST_FILENAME).read_bytes()
        asset = ARCHIVE_SHAPES[0]
        archive = release_archive(asset)
        source = sources.serve(lambda handler: send_bytes(handler, archive))
        request = replace(
            install_request(
                source.url(f"/{asset}"),
                version_dir,
                asset=asset,
                pinned_archive=archive,
            ),
            previously="healthy",
            limits=_QUICK,
            open_staging=_fills_up(stage, fail_after=fail_after),
        )

        report = _install(request)

        assert report.action == ProvisionAction.FAILED
        assert "ran out of space" in report.message
        assert str(version_dir) in report.message
        assert "Free space on that volume" in report.message
        # A full disk is not the source's fault; it is asked once.
        assert len(source.requests) == 1
        _assert_failed_cleanly(version_dir, prior, prior_manifest)

        _install_healthy(sources, version_dir, NEW_EXECUTABLE)
        assert working_files(version_dir) == []


class TestABodyNothingDelimits:
    """A body with no length and no framing ends when the connection does."""

    def test_a_cut_transfer_is_tried_again_and_the_whole_body_installed(
        self, sources: LoopbackSources, version_dir: Path
    ) -> None:
        """A short body with no declared length is a cut transfer, not a verdict.

        The source closes the connection in order after half the archive, and
        declares no length, so nothing in the transfer says the body is
        short. Only the digest can, and what it finds is retried as any cut
        transfer is. The second answer is the whole archive.

        Mutation: removed the question ``_fetch_once`` asks of an undelimited
        body. Observed the action assertion fail (``failed`` where
        ``created`` was required), on one request: the half archive went to
        the digest check and was reported as a replaced upstream asset.
        Restored; passes.
        """
        asset = ARCHIVE_SHAPES[0]
        archive = release_archive(asset)
        source = sources.serve(
            _InOrder(
                lambda handler: send_undelimited(handler, archive[: len(archive) // 2]),
                lambda handler: send_undelimited(handler, archive),
            )
        )
        lines: list[str] = []
        request = replace(
            install_request(
                source.url(f"/{asset}"),
                version_dir,
                asset=asset,
                pinned_archive=archive,
            ),
            limits=_QUICK,
            on_progress=lines.append,
        )

        report = _install(request)

        assert report.action == ProvisionAction.CREATED, report.message
        assert len(source.requests) == 2
        assert (version_dir / binary_filename()).read_bytes() == NEW_EXECUTABLE
        assert sum("retrying" in line for line in lines) == 1
        assert working_files(version_dir) == []

    def test_a_source_that_never_sends_the_expected_file_is_not_called_a_replaced_asset(
        self, sources: LoopbackSources, version_dir: Path
    ) -> None:
        """What cannot be told apart is reported as both things it could be.

        Every answer is the same bytes, complete, and they are not the
        archive. Without a length the client cannot know they were complete,
        so the report says so instead of asserting that upstream changed.
        """
        asset = ARCHIVE_SHAPES[0]
        source = sources.serve(
            lambda handler: send_undelimited(handler, b"some other file entirely")
        )
        request = replace(
            install_request(
                source.url(f"/{asset}"),
                version_dir,
                asset=asset,
                pinned_archive=release_archive(asset),
            ),
            limits=_QUICK,
        )

        report = _install(request)

        assert report.action == ProvisionAction.FAILED
        assert len(source.requests) == 3
        assert "after 3 attempts" in report.message
        assert "without having said how many to expect" in report.message
        assert "cut short or the source is serving a different file" in report.message
        assert "may have been replaced" not in report.message
        assert "`vaultspec-rag server qdrant install`" in report.message
        assert not (version_dir / binary_filename()).exists()
        assert working_files(version_dir) == []

    def test_a_caller_with_no_way_to_tell_is_handed_the_body_as_it_came(
        self, sources: LoopbackSources
    ) -> None:
        """The transport decides nothing about content it was not asked about."""
        source = sources.serve(lambda handler: send_undelimited(handler, _BODY))
        out = io.BytesIO()

        download_https(
            source.url("/asset.bin"), out, redirect_hosts=_ALLOWED, limits=_QUICK
        )

        assert out.getvalue() == _BODY
        assert len(source.requests) == 1


class TestAHostNoNameCanBeMadeOf:
    @pytest.mark.parametrize(
        "host",
        ["mirror..example", f"{'a' * 64}.example"],
        ids=["an empty label", "a label over 63 characters"],
    )
    def test_it_is_a_bad_source_and_not_an_error_from_the_encoder(
        self, host: str
    ) -> None:
        """A host that cannot be encoded is the URL's fault, said as such.

        Nothing is contacted: the name fails before it is resolved.

        Mutation: removed the handling of the encoder's refusal in
        ``download_https``. Observed ``UnicodeError`` escape the call in both
        cases. Restored; passes.
        """
        failure = _fetch(f"https://{host}/asset.bin")

        assert failure.kind is DownloadFailure.BAD_SOURCE
        assert failure.attempts == 1
        assert host in str(failure)
