"""Memory-only exact-response LRU with absolute age and byte bounds.

The transport owns synchronization. Keys are digests, never request content.
"""

from __future__ import annotations

from collections import OrderedDict


class ResponseCache:
    def __init__(
        self,
        *,
        ttl: float = 60.0,
        entries: int = 128,
        byte_limit: int = 4 * 1024 * 1024,
    ) -> None:
        self.ttl = ttl
        self.entries = entries
        self.byte_limit = byte_limit
        self.size = 0
        self.values: OrderedDict[bytes, tuple[float, bytes]] = OrderedDict()

    def clear(self) -> None:
        self.values.clear()
        self.size = 0

    def get(self, key: bytes, now: float) -> bytes | None:
        entry = self.values.pop(key, None)
        if entry is None:
            return None
        expires, body = entry
        if now >= expires:
            self.size -= len(body)
            return None
        self.values[key] = entry
        return body

    def put(self, key: bytes, body: bytes, now: float) -> None:
        old = self.values.pop(key, None)
        if old is not None:
            self.size -= len(old[1])
        if len(body) > self.byte_limit or self.entries <= 0 or self.ttl <= 0:
            return
        self.values[key] = (now + self.ttl, body)
        self.size += len(body)
        while len(self.values) > self.entries or self.size > self.byte_limit:
            _, (_, evicted) = self.values.popitem(last=False)
            self.size -= len(evicted)
