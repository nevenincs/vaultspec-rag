"""Stand-in download sources served over real loopback HTTPS.

The provisioner refuses a source that is not HTTPS and verifies the server's
certificate, so a stand-in has to speak TLS with a certificate the client
trusts or the shipped download path never reaches it. This mints a throwaway
certificate for the loopback address, points the interpreter's default trust
at it for the duration of a block, and serves whatever a test's responder
writes. Nothing in the code under test is replaced: the request, the redirect
handling and the TLS handshake are the ones production performs.

It is also the one place a degraded source is built. Each fault here is a
real server doing the thing - holding a connection open and saying nothing,
resetting it mid-body, sending fewer or more bytes than it promised - so a
client under test meets it on a real socket. A caller that needs no TLS takes
the same starter from :func:`plain_loopback_sources`.
"""

from __future__ import annotations

import datetime
import ipaddress
import socket
import ssl
import struct
import sys
import threading
import time
from contextlib import contextmanager, suppress
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from typing import TYPE_CHECKING, cast

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from ._http_stubs import QuietHandler
from ._ports import free_loopback_port
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

__all__ = [
    "LOOPBACK_HOST",
    "LoopbackSources",
    "SilentListener",
    "StandInSource",
    "plain_loopback_sources",
    "send_bytes",
    "send_endless",
    "send_redirect",
    "send_then_reset",
    "send_trickle",
    "send_truncated",
    "stay_silent",
    "trickle_headers",
    "trusted_loopback_sources",
]

#: The one address every stand-in listens on and is certified for.
LOOPBACK_HOST = "127.0.0.1"

#: The longest a deliberately stuck responder holds its connection when the
#: test never tears its source down. A backstop only: closing the source
#: releases every held connection at once.
_HOLD_BACKSTOP_SECONDS = 120.0

type Responder = Callable[[QuietHandler], None]


class _SourceServer(ThreadingHTTPServer):
    """Carry the responder and the request log the handler reaches through."""

    # A responder may hold a request open on purpose; teardown must not wait
    # for it.
    daemon_threads = True

    def __init__(self, respond: Responder) -> None:
        super().__init__((LOOPBACK_HOST, 0), _SourceHandler)
        self.respond = respond
        self.requests: list[str] = []
        self.heads: list[str] = []
        #: Set at teardown, so a responder that is holding a connection open
        #: on purpose lets go of it.
        self.closing = threading.Event()


class _SourceHandler(QuietHandler):
    """Log the request path, then hand the exchange to the test's responder."""

    def do_GET(self) -> None:
        server = cast("_SourceServer", self.server)
        server.requests.append(self.path)
        server.respond(self)

    def do_HEAD(self) -> None:
        # The responder reads ``command`` to tell the two apart, and writes no
        # body for this one.
        server = cast("_SourceServer", self.server)
        server.heads.append(self.path)
        server.respond(self)

    def handle(self) -> None:
        # A client that abandons the transfer mid-body is a case under test,
        # not a server fault worth a traceback in the captured output. Over
        # TLS the abandoned write surfaces as one of several socket errors.
        try:
            super().handle()
        except OSError:
            return


class StandInSource:
    """One running loopback server and the requests it has answered."""

    def __init__(self, server: _SourceServer, scheme: str) -> None:
        self._server = server
        self._scheme = scheme
        # The default half-second poll would be paid at every teardown.
        self._thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.02},
            daemon=True,
        )
        self._thread.start()

    @property
    def requests(self) -> list[str]:
        """The path of every ``GET`` received, in arrival order."""
        return self._server.requests

    @property
    def heads(self) -> list[str]:
        """The path of every ``HEAD`` received, in arrival order."""
        return self._server.heads

    def url(self, path: str = "") -> str:
        """Return the address of *path* on this source."""
        port = self._server.server_address[1]
        return f"{self._scheme}://{LOOPBACK_HOST}:{port}{path}"

    def close(self) -> None:
        """Stop serving, release held connections, and release the port."""
        self._server.closing.set()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5.0)


class SilentListener:
    """A port that accepts every connection and then never says a word.

    The peer a stalled source looks like before any protocol is spoken: the
    TCP handshake completes, so the client is not refused, and nothing ever
    arrives, so a TLS client waits in its own handshake.
    """

    def __init__(self) -> None:
        self._listener = socket.create_server((LOOPBACK_HOST, 0))
        self._held: list[socket.socket] = []
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()

    @property
    def connections(self) -> int:
        """How many connections have been accepted so far."""
        return len(self._held)

    def url(self, path: str = "") -> str:
        """Return an HTTPS address on this port."""
        return f"https://{LOOPBACK_HOST}:{self._listener.getsockname()[1]}{path}"

    def _accept(self) -> None:
        while True:
            try:
                connection, _ = self._listener.accept()
            except OSError:
                return
            self._held.append(connection)

    def close(self) -> None:
        """Hang up on everyone and release the port."""
        self._listener.close()
        for connection in self._held:
            with suppress(OSError):
                connection.close()
        self._thread.join(timeout=5.0)


class LoopbackSources:
    """Start stand-in sources on the loopback address.

    Sources started with TLS share one certificate the client trusts. One
    started with ``trusted=False`` presents a second certificate the client
    has never been told about, which is what an unknown mirror looks like.
    """

    def __init__(
        self,
        trusted: ssl.SSLContext | None = None,
        untrusted: ssl.SSLContext | None = None,
    ) -> None:
        self._trusted = trusted
        self._untrusted = untrusted
        self._sources: list[StandInSource | SilentListener] = []

    def serve(
        self, respond: Responder, *, tls: bool = True, trusted: bool = True
    ) -> StandInSource:
        """Serve *respond* over HTTPS, or over plain HTTP when *tls* is off."""
        server = _SourceServer(respond)
        if tls:
            context = self._trusted if trusted else self._untrusted
            if context is None:
                server.server_close()
                raise RuntimeError("this starter was built without a certificate")
            server.socket = context.wrap_socket(server.socket, server_side=True)
        source = StandInSource(server, "https" if tls else "http")
        self._sources.append(source)
        return source

    def serve_silence(self) -> SilentListener:
        """Start a port that accepts connections and never speaks."""
        listener = SilentListener()
        self._sources.append(listener)
        return listener

    def refused_url(self, path: str = "") -> str:
        """Return an HTTPS address on a loopback port nothing listens on."""
        return f"https://{LOOPBACK_HOST}:{free_loopback_port()}{path}"

    def close(self) -> None:
        """Stop every source this started."""
        for source in self._sources:
            source.close()


def send_bytes(
    handler: QuietHandler,
    body: bytes,
    *,
    status: HTTPStatus = HTTPStatus.OK,
) -> None:
    """Answer *handler*'s request with *body* and a truthful length."""
    handler.send_response(status)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    if handler.command != "HEAD":
        handler.wfile.write(body)


def send_truncated(handler: QuietHandler, body: bytes, *, declared: int) -> None:
    """Promise *declared* bytes, send only *body*, then hang up."""
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Length", str(declared))
    handler.end_headers()
    handler.wfile.write(body)
    handler.wfile.flush()
    handler.close_connection = True


def send_then_reset(handler: QuietHandler, body: bytes, *, declared: int) -> None:
    """Promise *declared* bytes, send *body*, then reset the connection.

    Unlike :func:`send_truncated`, the connection is not closed in order: the
    socket is told to discard what it holds and abort, so the peer receives a
    reset rather than an end of stream.
    """
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Length", str(declared))
    handler.end_headers()
    handler.wfile.write(body)
    handler.wfile.flush()
    # A zero linger time makes the close an abort. The option takes two
    # 16-bit fields on Windows and two C ints elsewhere.
    linger = struct.pack("HH" if sys.platform == "win32" else "ii", 1, 0)
    handler.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger)
    handler.connection.close()
    handler.close_connection = True


def stay_silent(handler: QuietHandler) -> None:
    """Read the request, then send nothing until the source is torn down."""
    server = cast("_SourceServer", handler.server)
    server.closing.wait(timeout=_HOLD_BACKSTOP_SECONDS)
    handler.close_connection = True


def send_trickle(
    handler: QuietHandler,
    *,
    pieces: int,
    piece: bytes,
    interval: float,
    declare: bool = True,
) -> None:
    """Send a body of *pieces* copies of *piece*, one every *interval* seconds.

    With *declare* off no length is promised, so the body ends only when the
    connection does.
    """
    server = cast("_SourceServer", handler.server)
    handler.send_response(HTTPStatus.OK)
    if declare:
        handler.send_header("Content-Length", str(pieces * len(piece)))
    handler.end_headers()
    for _ in range(pieces):
        if server.closing.is_set():
            break
        handler.wfile.write(piece)
        handler.wfile.flush()
        time.sleep(interval)
    handler.close_connection = True


def trickle_headers(handler: QuietHandler, *, lines: int, interval: float) -> None:
    """Send a status line, then one header line every *interval* seconds.

    The response head never ends within the lines sent, so a client that
    bounds only each read, or only the body, waits here for as long as the
    lines keep coming.
    """
    server = cast("_SourceServer", handler.server)
    handler.wfile.write(b"HTTP/1.1 200 OK\r\n")
    handler.wfile.flush()
    for index in range(lines):
        if server.closing.is_set():
            break
        handler.wfile.write(f"X-Filler-{index}: still coming\r\n".encode("ascii"))
        handler.wfile.flush()
        time.sleep(interval)
    handler.close_connection = True


def send_endless(
    handler: QuietHandler, *, total: int, declared: int | None = None
) -> None:
    """Send *total* bytes, declaring *declared* of them or no length at all.

    With no declared length the body is delimited by the close of the
    connection, so a client learns how large it is only by reading it.
    """
    chunk = b"\0" * 65536
    handler.send_response(HTTPStatus.OK)
    if declared is not None:
        handler.send_header("Content-Length", str(declared))
    handler.end_headers()
    sent = 0
    while sent < total:
        handler.wfile.write(chunk[: total - sent])
        sent += len(chunk)
    handler.close_connection = True


def send_redirect(handler: QuietHandler, location: str) -> None:
    """Answer *handler*'s request with a redirect to *location*."""
    handler.send_response(HTTPStatus.FOUND)
    handler.send_header("Location", location)
    handler.send_header("Content-Length", "0")
    handler.end_headers()


def _mint_loopback_certificate(directory: Path, label: str) -> tuple[Path, Path]:
    """Write a short-lived self-signed certificate for the loopback address."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"loopback {label}")])
    now = datetime.datetime.now(datetime.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address(LOOPBACK_HOST))]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    directory.mkdir(parents=True, exist_ok=True)
    certificate_path = directory / f"loopback-{label}-cert.pem"
    key_path = directory / f"loopback-{label}-key.pem"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return certificate_path, key_path


def _server_context(certificate_path: Path, key_path: Path) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate_path, key_path)
    return context


@contextmanager
def trusted_loopback_sources(directory: Path) -> Generator[LoopbackSources]:
    """Yield a starter for stand-in sources the default TLS client trusts.

    Trust is granted the way an operator grants it to a private mirror: the
    certificate file is named in ``SSL_CERT_FILE``, which the interpreter's
    default verification reads. The client under test builds no context of
    its own for this, so a failure to verify a real certificate would still
    fail - and does, for a source started with ``trusted=False``, whose
    certificate that file does not hold. Loopback is also excluded from any
    configured proxy, because a proxy would be asked to reach an address that
    only exists on this host.
    """
    trusted_certificate, trusted_key = _mint_loopback_certificate(directory, "trusted")
    sources = LoopbackSources(
        _server_context(trusted_certificate, trusted_key),
        _server_context(*_mint_loopback_certificate(directory, "unknown")),
    )
    try:
        with managed_env(
            SSL_CERT_FILE=str(trusted_certificate),
            NO_PROXY=LOOPBACK_HOST,
            no_proxy=LOOPBACK_HOST,
        ):
            yield sources
    finally:
        sources.close()


@contextmanager
def plain_loopback_sources() -> Generator[LoopbackSources]:
    """Yield a starter for plain-HTTP stand-in sources, with no certificate.

    For a client that is pointed at an ``http`` endpoint. Every source must be
    started with ``tls=False``; the fault responders work the same way over
    either transport.
    """
    sources = LoopbackSources()
    try:
        with managed_env(NO_PROXY=LOOPBACK_HOST, no_proxy=LOOPBACK_HOST):
            yield sources
    finally:
        sources.close()
