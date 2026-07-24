"""Shared base for the stub HTTP servers the test suite stands up.

Tests that need a service to answer them spin up a real ``http.server`` with a
hand-written handler. Every one of those handlers wants the same thing from the
base class - silence - so that request logging does not interleave with the
output under assertion. That override lives here once.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler


class QuietHandler(BaseHTTPRequestHandler):
    """A request handler that logs nothing to stderr.

    ``BaseHTTPRequestHandler.log_message`` writes one line per request to
    stderr. In a test that is noise at best, and at worst it lands in the middle
    of captured output an assertion is reading.
    """

    def log_message(self, format: str, *args: object) -> None:
        _ = format, args
