"""Small exclusive-lease HTTP pool; admission is owned by the transport."""

from __future__ import annotations

import ssl
import threading
import time
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import urlsplit


@dataclass
class ConnectionLease:
    connection: HTTPConnection
    target: str
    identity: tuple[bytes, str]
    generation: int
    reused: bool


class ConnectionPool:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._context: ssl.SSLContext | None = None
        self._idle: list[tuple[ConnectionLease, float]] = []
        self._identity: tuple[bytes, str] | None = None
        self._generation = 0

    def close(self) -> None:
        with self._lock:
            self._clear()

    def _clear(self) -> None:
        self._generation += 1
        for lease, _ in self._idle:
            lease.connection.close()
        self._idle.clear()

    def acquire(self, identity: tuple[bytes, str], timeout: float) -> ConnectionLease:
        with self._lock:
            if self._identity != identity:
                self._clear()
                self._identity = identity
            while self._idle:
                lease, returned = self._idle.pop()
                if time.monotonic() - returned < 15.0:
                    lease.reused = True
                    lease.connection.timeout = timeout
                    if lease.connection.sock is not None:
                        lease.connection.sock.settimeout(timeout)
                    return lease
                lease.connection.close()
            endpoint = urlsplit(identity[1])
            if endpoint.scheme == "https":
                if self._context is None:
                    self._context = ssl.create_default_context()
                    self._context.set_alpn_protocols(["http/1.1"])
                connection = HTTPSConnection(
                    endpoint.netloc, timeout=timeout, context=self._context
                )
            elif endpoint.scheme == "http" and endpoint.hostname == "127.0.0.1":
                connection = HTTPConnection(endpoint.netloc, timeout=timeout)
            else:
                raise ValueError("unsupported_endpoint")
            target = endpoint.path or "/"
            if endpoint.query:
                target += "?" + endpoint.query
            return ConnectionLease(
                connection, target, identity, self._generation, False
            )

    def release(self, lease: ConnectionLease, *, reusable: bool) -> None:
        with self._lock:
            if (
                reusable
                and lease.identity == self._identity
                and lease.generation == self._generation
                and len(self._idle) < 2
            ):
                self._idle.append((lease, time.monotonic()))
            else:
                lease.connection.close()
