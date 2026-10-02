"""Shared backend and monitor bind probes."""

from __future__ import annotations

import logging
import socket

logger = logging.getLogger(__name__)


def port_is_available(port: int) -> bool:
    """Check whether the loopback TCP port can be bound without address reuse."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        try:
            listener.bind(("127.0.0.1", port))
        except OSError as exc:
            logger.debug("port %d not bindable: %s", port, exc)
            return False
    return True


def next_available_port(start: int) -> int:
    """Scan upward without wrapping the valid TCP port range."""
    if not 1 <= start <= 65535:
        raise RuntimeError("No monitor port exists above the backend port.")
    for port in range(start, 65536):
        if port_is_available(port):
            return port
    raise RuntimeError(f"No available monitor port in {start}..65535.")
