"""One ephemeral-loopback-port helper for the whole test suite.

Every test that needs "a port nothing is listening on" - a closed port for a
negative probe, a free port for a daemon to bind - asks here, so the suite has
one definition of what that means instead of one per module.
"""

from __future__ import annotations

import socket
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator


def free_loopback_port() -> int:
    """Return a loopback port number that nothing is currently listening on.

    Binds an ephemeral port, reads the number the kernel assigned, and closes
    the socket, so the port is unbound by the time the caller sees it. That
    makes the answer a best-effort observation rather than a reservation:
    another process can claim the port before the caller binds it, which is
    inherent to asking the kernel for a free port at all.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def refused_loopback_port() -> Generator[int]:
    """Yield a loopback port that refuses every connection while it is held.

    A socket bound to an ephemeral port but never put into ``listen()`` rejects
    every connect with ECONNREFUSED for as long as it is held - so there is no
    bind/close/reuse window, which a released port number leaves open to any
    listener another test starts in that moment. A connect that reaches such
    a listener is accepted and never answered, and the caller waits out its
    own timeout where the test expected an immediate refusal.

    macOS is the exception: it answers a connect to such a socket with
    silence, so the caller times out instead of being refused. There the port
    is released before it is handed over, which that system refuses at once,
    and the reuse window is accepted as the smaller error.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    if sys.platform == "darwin":
        sock.close()
    try:
        yield port
    finally:
        sock.close()


def bind_released_loopback_port(port: int) -> None:
    """Bind *port* on loopback, raising ``OSError`` while anything listens there.

    A server that closed a test's request first leaves that connection in
    TIME_WAIT on its port, and POSIX refuses a plain bind to it for about a
    minute after the listener is gone. ``SO_REUSEADDR`` admits that case and
    still refuses a live listener. Windows' ``SO_REUSEADDR`` would admit a live
    listener too, so it binds exclusively instead, which also refuses a
    listener that itself opted into address sharing.

    A listener held on the port failed this bind on Linux (errno 98) and in the
    Windows monitor allocation test (WinError 10048); closing it passed, and on
    Linux a server-side TIME_WAIT left behind no longer failed it.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sys.platform == "win32":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
