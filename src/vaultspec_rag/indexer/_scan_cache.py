"""Bounded-staleness cache for discovery walk results.

An unscoped pass walks the whole tree even when it immediately follows
another walk of the same tree under the same policy - a preflight followed by
its run, or back-to-back reconciles. This cache collapses those repeats: a
result is served only while its policy fingerprint still matches and a short
TTL has not elapsed, and any caller that observes a membership-changing event
invalidates it explicitly. Scoped runs never consult it - they carry exact
paths and bypass discovery entirely.

Staleness is bounded, never permanent: a create or delete that no caller
reported can be hidden for at most the TTL, after which the next walk sees
it. Deliberately short - the win is collapsing adjacent passes, not
eliminating walks.
"""

from __future__ import annotations

import threading
import time
from typing import Final

__all__ = [
    "MembershipScanCache",
]

#: How long a cached walk may answer for its fingerprint. Long enough to span
#: a preflight and the run it authorizes plus immediate retries; short enough
#: that an unreported membership change is deferred by seconds, not minutes.
_SCAN_CACHE_TTL_SECONDS: Final = 30.0


class MembershipScanCache[T]:
    """One-slot fingerprint-keyed cache of a discovery walk result.

    One slot suffices because a root resolves one policy at a time; a
    fingerprint change (any config or membership input) replaces the slot.
    Values must be immutable or treated as such by every consumer - the same
    object is returned to every hit. Thread-safe: discovery is called from
    service paths outside the writer lock.
    """

    __slots__ = ("_deadline", "_fingerprint", "_lock", "_ttl", "_value")

    def __init__(self, ttl_seconds: float = _SCAN_CACHE_TTL_SECONDS) -> None:
        self._lock = threading.Lock()
        self._ttl = ttl_seconds
        self._fingerprint: str | None = None
        self._value: T | None = None
        self._deadline = 0.0

    def get(self, fingerprint: str) -> T | None:
        """Return the cached value for *fingerprint*, or ``None``."""
        with self._lock:
            if (
                self._value is not None
                and self._fingerprint == fingerprint
                and time.monotonic() < self._deadline
            ):
                return self._value
            return None

    def put(self, fingerprint: str, value: T) -> None:
        """Cache *value* for *fingerprint* until the TTL elapses."""
        with self._lock:
            self._fingerprint = fingerprint
            self._value = value
            self._deadline = time.monotonic() + self._ttl

    def invalidate(self) -> None:
        """Drop the slot; the next walk re-establishes membership truth."""
        with self._lock:
            self._fingerprint = None
            self._value = None
            self._deadline = 0.0
