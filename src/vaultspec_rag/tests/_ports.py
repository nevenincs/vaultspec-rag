"""One ephemeral-loopback-port helper for the whole test suite.

Every test that needs "a port nothing is listening on" - a closed port for a
negative probe, a free port for a daemon to bind - asks here, so the suite has
one definition of what that means instead of one per module.
"""

from __future__ import annotations

import socket


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
