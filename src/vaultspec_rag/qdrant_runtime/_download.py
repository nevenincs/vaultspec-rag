"""Fetch one file over HTTPS, with every way that can go wrong bounded and named.

The transport half of provisioning, and the downloader the build tools use
for their own pinned artifacts. It decides nothing about what the bytes are:
callers verify them against a committed digest afterwards. What it owns is
the conversation with the source:

- **Where the request may go.** The source must be HTTPS. Its own host is
  contacted because the caller chose it; every redirect is checked before it
  is followed and must stay HTTPS and inside the hosts the caller allowed.
- **How long it may take.** One deadline covers the whole transfer, every
  attempt included, and it is enforced from outside the transfer: when it
  passes, the connection is hung up, so a source that trickles its response
  head, its TLS handshake or its body cannot hold a caller past it. A source
  that goes silent is cut sooner, by the stall limit on each socket read.
  Name resolution is the one step left to the operating system's own limit.
- **How much it may send.** A response that declares more than the cap is
  refused before its first byte is read, and one that sends more is cut off.
- **What is worth another attempt.** A failure of the transport, or a status
  that says "not now", is tried again a bounded number of times, each attempt
  starting the file over. A refusal this module makes itself, a status that
  will not change, a certificate that does not verify, and a failure to write
  what arrived are never retried. A body that only the close of the
  connection ends cannot be told from one cut short by anything in the
  transfer, so the caller is asked, and a body it does not recognise is
  tried again as a cut transfer.

Every failure leaves as one :class:`DownloadError` carrying which of those it
was, so a caller can tell an operator what to do about it.
"""

from __future__ import annotations

import http.client
import logging
import random
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from http import HTTPStatus
from typing import IO, TYPE_CHECKING, Self, cast, override

from .._backoff import jittered_backoff
from .._units import human_bytes

if TYPE_CHECKING:
    import io
    from collections.abc import Callable
    from http.client import HTTPMessage, HTTPResponse
    from types import TracebackType

logger = logging.getLogger(__name__)

__all__ = [
    "DownloadError",
    "DownloadFailure",
    "DownloadLimits",
    "download_https",
    "no_progress",
]

_DOWNLOAD_CHUNK_BYTES = 1 << 20
# The release archives are ~30 MB; cap the stream well above that so a
# host-pinned-but-defective response cannot fill the disk before the
# SHA256 check would reject it (defense in depth behind the host pin).
_MAX_DOWNLOAD_BYTES = 256 << 20
# Report every few chunks rather than every chunk: the reporter prints a plain
# line per distinct activity off a terminal, so a per-megabyte tick would fill
# a piped install log with a hundred near-identical lines.
_DOWNLOAD_REPORT_BYTES = 4 << 20
_RETRY_JITTER_FRACTION = 0.25
# Statuses that say "not now" rather than "no": a timeout, a rate limit, or a
# fault on the far side.
_TRANSIENT_HTTP_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
_GONE_HTTP_STATUS = frozenset({404, 410})


def no_progress(_line: str) -> None:
    """Drop a progress line, for callers that asked for no reporting.

    A no-op sink rather than a ``None`` check at each call site. Provisioning
    always runs in a foreground command and never in the daemon, which only
    resolves and verifies the binary; the commands that have a console pass a
    sink of their own, and a caller with nothing to show passes none.
    """


def _admit_any(_declared_bytes: int) -> None:
    """Admit a response of any declared size."""


def _whole_unless_told(_received: IO[bytes]) -> bool:
    """Take a body nothing delimits as complete, for a caller that cannot say."""
    return True


@dataclass(frozen=True)
class DownloadLimits:
    """How long, how large and how persistent one download may be.

    Attributes:
        deadline_seconds: The whole transfer, every attempt and every wait
            between attempts included. Generous for a ~30 MB archive on a
            slow link, and finite so a slow source ends as a reported failure
            rather than a command that never returns.
        stall_seconds: The longest the source may send nothing at all before
            the attempt is abandoned. It bounds one socket operation, so a
            source that keeps trickling never trips it; the deadline is what
            bounds that. Any byte that arrives starts the wait over, so a
            slow link is not what this limit is tuned for: it only has to
            outlast a pause no working source makes, and a source silent for
            this long through every attempt costs the operator about a minute
            and a half.
        max_bytes: The most a response may declare or send.
        attempts: How many times a transient failure is tried in all.
        retry_base_seconds: The wait before the second attempt; it doubles
            before each later one, with jitter.
        retry_cap_seconds: The longest wait between two attempts.
        admit: The caller's own limit on what it has room for. Called with
            the size each response declares (0 when it declares none) before
            the first body byte is read. Whatever it raises ends the download
            and is passed on unchanged, so it must not raise an ``OSError``,
            which reads as a failed transfer, or a ``ValueError``, which
            reads as a URL that cannot be fetched.
        whole: The caller's answer to a question the transfer cannot settle.
            A response that declares no length and is not chunked ends when
            the connection closes, so a transfer cut short looks exactly like
            one that finished. For such a body, and no other, this is called
            with the file as received; ``False`` makes the attempt a cut
            transfer, tried again like any other. A caller holding a digest
            can tell; one that cannot leaves the default, which accepts it.
    """

    deadline_seconds: float = 900.0
    stall_seconds: float = 30.0
    max_bytes: int = _MAX_DOWNLOAD_BYTES
    attempts: int = 3
    retry_base_seconds: float = 0.5
    retry_cap_seconds: float = 4.0
    admit: Callable[[int], None] = _admit_any
    whole: Callable[[IO[bytes]], bool] = _whole_unless_told


_DEFAULT_LIMITS = DownloadLimits()


class DownloadFailure(StrEnum):
    """Why a download failed, by what an operator can do about it."""

    #: The URL is not one this module will fetch: not HTTPS, or malformed.
    BAD_SOURCE = "bad_source"
    #: A redirect left HTTPS or the hosts the caller allowed.
    REDIRECT_REFUSED = "redirect_refused"
    #: The source's redirects loop, run too long, or name no target.
    BAD_REDIRECT = "bad_redirect"
    #: The source's certificate does not verify against this host's trust.
    UNTRUSTED_CERTIFICATE = "untrusted_certificate"
    #: The source answered that it has no such file.
    NOT_FOUND = "not_found"
    #: The source answered with a refusal that asking again will not change.
    REFUSED = "refused"
    #: The source kept answering "not now" until the attempts ran out.
    UNAVAILABLE = "unavailable"
    #: The source could not be reached, or kept dropping the connection,
    #: until the attempts ran out.
    UNREACHABLE = "unreachable"
    #: The transfer did not finish within its deadline.
    TOO_SLOW = "too_slow"
    #: The source declared or sent more than the cap.
    TOO_LARGE = "too_large"
    #: What arrived could not be written to the caller's file.
    WRITE_FAILED = "write_failed"


#: The failures another attempt at the same request could plausibly cure.
_TRANSIENT = frozenset({DownloadFailure.UNAVAILABLE, DownloadFailure.UNREACHABLE})


class DownloadError(urllib.error.URLError):
    """A download that failed, with the reason sorted into one kind.

    Attributes:
        kind: Which failure this was.
        status: The HTTP status the source answered with, when it answered.
        attempts: How many attempts had been made when it was given up.
    """

    def __init__(
        self,
        kind: DownloadFailure,
        detail: str,
        *,
        status: int | None = None,
        attempts: int = 1,
    ) -> None:
        super().__init__(detail)
        self.kind = kind
        self.status = status
        self.attempts = attempts

    def __str__(self) -> str:
        return str(self.reason)


def _hang_up(sock: socket.socket | None) -> None:
    """End *sock* from another thread, waking whatever is reading it.

    The operating system's shutdown is called on the socket directly. A TLS
    socket's own ``shutdown`` first discards its session state, which the
    thread still reading through it would then trip over.
    """
    if sock is not None:
        with suppress(OSError):
            socket.socket.shutdown(sock, socket.SHUT_RDWR)


class _Deadline:
    """A whole-transfer time limit that hangs up when it passes.

    Checking a clock between reads bounds only the reads that return. This
    also holds what the transfer reads from, and a timer ends it at the
    deadline, so a read that is still waiting - for a header line, a
    handshake record, the next body byte - fails at once instead of at its
    own timeout.

    Two things are held, because a connection lets go of its socket partway
    through. While a connection is being made, its socket is whatever the
    connection currently has, so the connection is held and asked. Once the
    response head is read the connection drops the socket and the response
    reads on from it alone, so the socket itself is held as well.
    """

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self._expires_at = time.monotonic() + seconds
        self._guard = threading.Lock()
        self._connections: list[http.client.HTTPConnection] = []
        self._sockets: list[socket.socket] = []
        self._cut = False
        self._timer = threading.Timer(seconds, self._cut_connections)
        self._timer.daemon = True

    def __enter__(self) -> Self:
        self._timer.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._timer.cancel()

    @property
    def cut(self) -> bool:
        """Whether the deadline passed and the connections were hung up."""
        return self._cut

    def remaining(self) -> float:
        return self._expires_at - time.monotonic()

    def watch(self, connection: http.client.HTTPConnection) -> None:
        """Hold *connection* so the deadline can end it while it is being made."""
        with self._guard:
            self._connections.append(connection)

    def hold(self, sock: socket.socket) -> None:
        """Hold the connected *sock* so the deadline can end reads from it."""
        with self._guard:
            self._sockets.append(sock)
            cut = self._cut
        if cut:
            _hang_up(sock)

    def _cut_connections(self) -> None:
        with self._guard:
            self._cut = True
            sockets = [*self._sockets, *(held.sock for held in self._connections)]
        for sock in sockets:
            _hang_up(sock)

    def breach(self) -> DownloadError:
        return DownloadError(
            DownloadFailure.TOO_SLOW,
            f"The download did not finish within its {self.seconds:g} second limit",
        )


class _WatchedConnection(http.client.HTTPSConnection):
    """An HTTPS connection its transfer's deadline can end."""

    #: Set by the factory that makes the connection, before it is used.
    held_by: _Deadline

    @override
    def connect(self) -> None:
        self.held_by.watch(self)
        super().connect()
        # Hung up at once if the deadline passed while the address was still
        # being resolved or dialled, before there was a socket to end.
        self.held_by.hold(self.sock)


class _WatchedConnections:
    """Make one transfer's connections, each held by that transfer's deadline.

    Shaped as the connection factory the standard opener calls, so proxies
    and tunnels are set up on these connections exactly as on its own.
    """

    def __init__(self, deadline: _Deadline) -> None:
        self._deadline = deadline
        # The interpreter's default verification, built once so the same
        # context reaches every connection: system trust, plus whatever
        # ``SSL_CERT_FILE`` names. Nothing about it is relaxed.
        self._tls = ssl.create_default_context()
        self._tls.set_alpn_protocols(["http/1.1"])

    def __call__(
        self,
        host: str,
        /,
        *,
        port: int | None = None,
        timeout: float = _DEFAULT_LIMITS.stall_seconds,
        source_address: tuple[str, int] | None = None,
        blocksize: int = 8192,
    ) -> http.client.HTTPConnection:
        connection = _WatchedConnection(
            host,
            port,
            timeout=timeout,
            source_address=source_address,
            context=self._tls,
            blocksize=blocksize,
        )
        connection.held_by = self._deadline
        return connection


class _WatchedHTTPS(urllib.request.HTTPSHandler):
    """Open HTTPS connections that the transfer's deadline holds."""

    def __init__(self, deadline: _Deadline) -> None:
        super().__init__()
        self._connections = _WatchedConnections(deadline)

    @override
    def https_open(self, req: urllib.request.Request) -> HTTPResponse:
        return self.do_open(self._connections, req)


class _HostPinnedRedirect(urllib.request.HTTPRedirectHandler):
    """Allow redirects only over HTTPS and only onto the hosts it was given.

    The request that starts a download goes to a source its caller chose. A
    redirect is chosen by whoever answered that request, so each hop is
    checked here before it is followed.
    """

    def __init__(self, allowed_hosts: frozenset[str]) -> None:
        self._allowed_hosts = allowed_hosts

    @override
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        """Reject redirect targets outside the pinned HTTPS host set."""
        parsed = urllib.parse.urlparse(newurl)
        # A redirect must stay HTTPS: a downgrade to http on an allowed
        # host would still strip TLS, so reject it as firmly as a
        # cross-host redirect.
        if parsed.scheme != "https":
            raise DownloadError(
                DownloadFailure.REDIRECT_REFUSED,
                f"Redirect to non-HTTPS URL {newurl!r} rejected",
            )
        host = (parsed.hostname or "").lower()
        if host not in self._allowed_hosts:
            raise DownloadError(
                DownloadFailure.REDIRECT_REFUSED,
                f"Redirect to disallowed host {host!r} rejected "
                f"(allowed: {sorted(self._allowed_hosts)})",
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _declared_length(headers: object) -> int:
    """Read a response's ``Content-Length``, or 0 when it declares none."""
    getter = getattr(headers, "get", None)
    if getter is None:
        return 0
    try:
        return max(0, int(getter("Content-Length") or 0))
    except (TypeError, ValueError):
        return 0


def _download_line(written: int, declared: int) -> str:
    """Render one line of download progress, with a total when one was declared."""
    if declared:
        return (
            f"Downloading the Qdrant server: "
            f"{human_bytes(written)} of {human_bytes(declared)}"
        )
    return f"Downloading the Qdrant server: {human_bytes(written)}"


@dataclass(frozen=True)
class _StreamBounds:
    """How much one stream may hold, and when it must be over."""

    max_bytes: int = _MAX_DOWNLOAD_BYTES
    deadline: _Deadline | None = None


_CAPPED_ONLY = _StreamBounds()


def _stream_capped(
    source: io.BufferedIOBase,
    out: IO[bytes],
    *,
    declared: int,
    on_progress: Callable[[str], None],
    bounds: _StreamBounds = _CAPPED_ONLY,
) -> int:
    """Copy *source* into *out* under the size cap, reporting as it goes.

    Split from the request handling so the cap and the reporting cadence can
    be exercised over an ordinary binary stream rather than only over a live
    HTTPS response.

    Each read takes whatever one read of the underlying stream returns
    instead of waiting for a full chunk. A full-chunk read keeps blocking for
    as long as bytes keep arriving, however slowly, so nothing could be
    reported or checked until a megabyte had trickled in.

    Args:
        source: The readable stream to drain.
        out: The file to write into.
        declared: The size the response claimed, or 0 when it claimed none.
        on_progress: Sink for byte-progress lines.
        bounds: The most the stream may hold, and when the whole download
            must be over if it is bounded in time.

    Returns:
        The number of bytes written.

    Raises:
        DownloadError: When the stream exceeds the cap or runs past its
            deadline, or *out* refuses a write.
        ConnectionError: When the stream ends short of the size it declared.
    """
    deadline = bounds.deadline
    written = 0
    reported = 0
    while chunk := source.read1(_DOWNLOAD_CHUNK_BYTES):
        if deadline is not None and deadline.remaining() <= 0:
            raise deadline.breach()
        written += len(chunk)
        if written > bounds.max_bytes:
            raise DownloadError(
                DownloadFailure.TOO_LARGE,
                f"Download exceeded the {bounds.max_bytes} byte cap; "
                "refusing to continue",
            )
        try:
            out.write(chunk)
        except OSError as exc:
            # Told apart from a failed read here, where the two are still
            # distinguishable: a write that failed is the local disk's doing
            # and asking the source again cannot help.
            raise DownloadError(
                DownloadFailure.WRITE_FAILED,
                f"Writing the download failed after {written - len(chunk)} bytes: "
                f"{exc}",
            ) from exc
        if written - reported >= _DOWNLOAD_REPORT_BYTES:
            reported = written
            on_progress(_download_line(written, declared))
    # A source that hangs up early ends the stream exactly as a complete body
    # does. Named here, it is a transport failure worth another attempt; left
    # to the digest check it would read as a replaced asset.
    if declared and written < declared:
        raise ConnectionError(f"The transfer ended after {written} of {declared} bytes")
    # The final tick lands on the true size, so the last thing an operator
    # reads is the transfer completing rather than stalling near the end.
    if written != reported:
        on_progress(_download_line(written, declared))
    return written


def _http_failure(exc: urllib.error.HTTPError) -> DownloadError:
    """Sort an HTTP error status into what an operator can do about it."""
    status = exc.code
    # The error is also the open response; nothing more is read from it.
    exc.close()
    try:
        answer = f"HTTP {status} {HTTPStatus(status).phrase}"
    except ValueError:
        answer = f"HTTP {status}"
    if HTTPStatus.MULTIPLE_CHOICES <= status < HTTPStatus.BAD_REQUEST:
        return DownloadError(
            DownloadFailure.BAD_REDIRECT,
            f"The source answered {answer} with a redirect that cannot be "
            "followed: it loops, runs through too many hops, or names no target",
            status=status,
        )
    if status in _GONE_HTTP_STATUS:
        kind = DownloadFailure.NOT_FOUND
    elif status in _TRANSIENT_HTTP_STATUS:
        kind = DownloadFailure.UNAVAILABLE
    else:
        kind = DownloadFailure.REFUSED
    return DownloadError(kind, f"The source answered {answer}", status=status)


def _transport_failure(cause: BaseException, limits: DownloadLimits) -> DownloadError:
    """Sort a failure below HTTP into what an operator can do about it."""
    if isinstance(cause, ssl.SSLCertVerificationError):
        return DownloadError(
            DownloadFailure.UNTRUSTED_CERTIFICATE,
            f"The source's certificate could not be verified: {cause.verify_message}",
        )
    if isinstance(cause, socket.gaierror):
        detail = f"The source's host name could not be resolved ({cause})"
    elif isinstance(cause, ConnectionRefusedError):
        detail = f"The source refused the connection ({cause})"
    elif isinstance(cause, TimeoutError):
        detail = (
            "The source stopped responding: nothing arrived within the "
            f"{limits.stall_seconds:g} second stall limit"
        )
    else:
        detail = f"The connection to the source failed ({cause})"
    return DownloadError(DownloadFailure.UNREACHABLE, detail)


def _failure(exc: Exception, limits: DownloadLimits) -> DownloadError:
    """Return the one failure *exc* amounts to."""
    if isinstance(exc, urllib.error.HTTPError):
        return _http_failure(exc)
    if isinstance(exc, urllib.error.URLError):
        if isinstance(exc.reason, BaseException):
            return _transport_failure(exc.reason, limits)
        # A reason with no underlying error is urllib refusing the URL itself.
        return DownloadError(
            DownloadFailure.BAD_SOURCE,
            f"The source URL cannot be fetched: {exc.reason}",
        )
    return _transport_failure(exc, limits)


@dataclass(frozen=True)
class _Transfer:
    """One download's fixed inputs, shared by every attempt at it."""

    url: str
    out: IO[bytes]
    limits: DownloadLimits
    deadline: _Deadline
    on_progress: Callable[[str], None]


def _fetch_once(opener: urllib.request.OpenerDirector, transfer: _Transfer) -> None:
    """Make one attempt at streaming the URL into the file, from its first byte."""
    deadline, limits, out = transfer.deadline, transfer.limits, transfer.out
    remaining = deadline.remaining()
    if remaining <= 0:
        raise deadline.breach()
    try:
        # Nothing of an earlier attempt is kept: the transfer starts the file
        # over.
        out.seek(0)
        out.truncate()
    except OSError as exc:
        raise DownloadError(
            DownloadFailure.WRITE_FAILED, f"The download file could not be reset: {exc}"
        ) from exc
    # ``OpenerDirector.open`` is typed ``Any`` in typeshed (it dispatches
    # across registered handlers); an HTTPS download always resolves to an
    # ``HTTPResponse`` at runtime.
    with cast(
        "HTTPResponse",
        opener.open(transfer.url, timeout=min(limits.stall_seconds, remaining)),
    ) as resp:
        declared = _declared_length(resp.headers)
        if declared > limits.max_bytes:
            raise DownloadError(
                DownloadFailure.TOO_LARGE,
                f"The source declares {declared} bytes, more than the "
                f"{limits.max_bytes} byte cap; refusing to start",
            )
        # The caller's last word before the first body byte is read.
        limits.admit(declared)
        # Neither a length nor chunk framing: only the close of the
        # connection ends this body, whether or not all of it was sent.
        undelimited = not declared and not resp.chunked
        received = _stream_capped(
            resp,
            out,
            declared=declared,
            on_progress=transfer.on_progress,
            bounds=_StreamBounds(limits.max_bytes, deadline),
        )
    if undelimited and not deadline.cut and not limits.whole(out):
        # Left to the caller's digest check, a cut transfer would read as a
        # replaced asset and never be tried again.
        raise ConnectionError(
            f"the source closed the connection after {received} bytes without "
            "having said how many to expect, and what arrived is not the "
            "expected file: either the transfer was cut short or the source "
            "is serving a different file"
        )
    if deadline.cut:
        # A body with no declared length ends when the connection does, so
        # one the deadline hung up on could pass for complete if the hung-up
        # read reported an end of stream. On Windows and Linux that read
        # raises instead and the caller's handler names the deadline; this
        # covers a platform where it does not.
        raise deadline.breach()


def _retry_delay(
    failure: DownloadError, attempt: int, limits: DownloadLimits, deadline: _Deadline
) -> float | None:
    """Return how long to wait before another attempt, or ``None`` to stop."""
    if failure.kind not in _TRANSIENT or attempt >= limits.attempts:
        return None
    delay = jittered_backoff(
        attempt - 1,
        base=limits.retry_base_seconds,
        cap=limits.retry_cap_seconds,
        fraction=_RETRY_JITTER_FRACTION,
        random_unit=random.random(),
    )
    # An attempt that could not start before the deadline is not worth the
    # wait for it.
    return delay if delay < deadline.remaining() else None


def download_https(
    url: str,
    out: IO[bytes],
    *,
    redirect_hosts: frozenset[str],
    on_progress: Callable[[str], None] = no_progress,
    limits: DownloadLimits = _DEFAULT_LIMITS,
) -> None:
    """Stream *url* into the open file *out* over HTTPS with pinned redirects.

    The host *url* names is contacted whatever *redirect_hosts* says: it is
    the source the caller chose. *redirect_hosts* bounds where that source may
    redirect to, and every hop must stay HTTPS.

    The caller opens *out* and owns what happens to it afterwards, because
    that differs: the managed install streams into a staging file it created
    exclusively and discards on any failure, while a build tool streams into
    a file in a directory of its own.

    Args:
        url: The pinned release asset to fetch.
        out: The open, seekable binary file to stream into.
        redirect_hosts: Lower-cased host names a redirect may land on. It is
            a required argument so each caller states the hosts it trusts
            rather than inheriting another caller's.
        on_progress: Sink for byte-progress lines, emitted every few
            megabytes and once more on the final byte, and for a line per
            retry.
        limits: How long, how large and how persistent the transfer may be.

    Raises:
        DownloadError: However the download failed; ``kind`` says which way.
    """
    if urllib.parse.urlparse(url).scheme != "https":
        raise DownloadError(
            DownloadFailure.BAD_SOURCE, f"Refusing non-HTTPS download URL {url!r}"
        )
    with _Deadline(limits.deadline_seconds) as deadline:
        opener = urllib.request.build_opener(
            _HostPinnedRedirect(redirect_hosts), _WatchedHTTPS(deadline)
        )
        transfer = _Transfer(url, out, limits, deadline, on_progress)
        attempt = 1
        # The loop has no bound of its own. The only way out besides success
        # is the failure being raised, so no branch can fall through and
        # return as if a failed final attempt had filled the file.
        while True:
            try:
                _fetch_once(opener, transfer)
            except DownloadError:
                raise
            except (ValueError, http.client.InvalidURL) as exc:
                # A host no name can be made of - an empty or over-long
                # label, a control character - is refused where the name is
                # encoded, below anything that sorts failures. It is the URL
                # that is wrong, and asking again cannot change it.
                raise DownloadError(
                    DownloadFailure.BAD_SOURCE,
                    f"The source URL {url!r} cannot be fetched: {exc}",
                ) from exc
            except (OSError, http.client.HTTPException) as exc:
                if deadline.cut or deadline.remaining() <= 0:
                    # Whatever the hung-up read raised, the deadline is why.
                    raise deadline.breach() from exc
                failure = _failure(exc, limits)
                delay = _retry_delay(failure, attempt, limits, deadline)
                if delay is None:
                    failure.attempts = attempt
                    raise failure from exc
                logger.warning(
                    "download attempt %d of %s failed: %s", attempt, url, exc
                )
                attempt += 1
                on_progress(
                    f"The download was interrupted ({failure}); "
                    f"retrying, attempt {attempt} of {limits.attempts}..."
                )
                time.sleep(delay)
            else:
                return
