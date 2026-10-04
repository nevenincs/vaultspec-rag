"""One ephemeral-loopback-port helper for the whole test suite.

Every test that needs "a port nothing is listening on" - a closed port for a
negative probe, a free port for a daemon to bind - asks here, so the suite has
one definition of what that means instead of one per module.
"""

from __future__ import annotations

import socket
import sys


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
