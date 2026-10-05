"""Stand-in download sources served over real loopback HTTPS.

The provisioner refuses a source that is not HTTPS and verifies the server's
certificate, so a stand-in has to speak TLS with a certificate the client
trusts or the shipped download path never reaches it. This mints a throwaway
certificate for the loopback address, points the interpreter's default trust
at it for the duration of a block, and serves whatever a test's responder
writes. Nothing in the code under test is replaced: the request, the redirect
handling and the TLS handshake are the ones production performs.
"""

from __future__ import annotations

import datetime
import ipaddress
import ssl
import threading
from contextlib import contextmanager
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from typing import TYPE_CHECKING, cast

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from ._http_stubs import QuietHandler
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

__all__ = [
    "LOOPBACK_HOST",
    "LoopbackSources",
    "StandInSource",
    "send_bytes",
    "send_redirect",
    "send_truncated",
    "trusted_loopback_sources",
]

#: The one address every stand-in listens on and is certified for.
LOOPBACK_HOST = "127.0.0.1"

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


class _SourceHandler(QuietHandler):
    """Log the request path, then hand the exchange to the test's responder."""

    def do_GET(self) -> None:
        server = cast("_SourceServer", self.server)
        server.requests.append(self.path)
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
        """The path of every request received, in arrival order."""
        return self._server.requests

    def url(self, path: str = "") -> str:
        """Return the address of *path* on this source."""
        port = self._server.server_address[1]
        return f"{self._scheme}://{LOOPBACK_HOST}:{port}{path}"

    def close(self) -> None:
        """Stop serving and release the port."""
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5.0)


class LoopbackSources:
    """Start stand-in sources that share one trusted loopback certificate."""

    def __init__(self, context: ssl.SSLContext) -> None:
        self._context = context
        self._sources: list[StandInSource] = []

    def serve(self, respond: Responder, *, tls: bool = True) -> StandInSource:
        """Serve *respond* over HTTPS, or over plain HTTP when *tls* is off."""
        server = _SourceServer(respond)
        if tls:
            server.socket = self._context.wrap_socket(server.socket, server_side=True)
        source = StandInSource(server, "https" if tls else "http")
        self._sources.append(source)
        return source

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
    handler.wfile.write(body)


def send_truncated(handler: QuietHandler, body: bytes, *, declared: int) -> None:
    """Promise *declared* bytes, send only *body*, then hang up."""
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Length", str(declared))
    handler.end_headers()
    handler.wfile.write(body)
    handler.wfile.flush()
    handler.close_connection = True


def send_redirect(handler: QuietHandler, location: str) -> None:
    """Answer *handler*'s request with a redirect to *location*."""
    handler.send_response(HTTPStatus.FOUND)
    handler.send_header("Location", location)
    handler.send_header("Content-Length", "0")
    handler.end_headers()


def _mint_loopback_certificate(directory: Path) -> tuple[Path, Path]:
    """Write a short-lived self-signed certificate for the loopback address."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "loopback stand-in")])
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
    certificate_path = directory / "loopback-cert.pem"
    key_path = directory / "loopback-key.pem"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return certificate_path, key_path


@contextmanager
def trusted_loopback_sources(directory: Path) -> Generator[LoopbackSources]:
    """Yield a starter for stand-in sources the default TLS client trusts.

    Trust is granted the way an operator grants it to a private mirror: the
    certificate file is named in ``SSL_CERT_FILE``, which the interpreter's
    default verification reads. The client under test builds no context of
    its own for this, so a failure to verify a real certificate would still
    fail. Loopback is also excluded from any configured proxy, because a
    proxy would be asked to reach an address that only exists on this host.
    """
    certificate_path, key_path = _mint_loopback_certificate(directory)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate_path, key_path)
    sources = LoopbackSources(context)
    try:
        with managed_env(
            SSL_CERT_FILE=str(certificate_path),
            NO_PROXY=LOOPBACK_HOST,
            no_proxy=LOOPBACK_HOST,
        ):
            yield sources
    finally:
        sources.close()
