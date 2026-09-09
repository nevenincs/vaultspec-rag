"""The failure class a qdrant call raises when the server cannot answer.

One name for one class, because the class - not any individual call site - is
what a guard has to cover. Widening handlers one call at a time is how a
maintenance cycle ends up isolated on the paths someone happened to look at
and unwound on the paths they did not, and a tuple repeated at ten sites gives
a reader no way to tell a site that was considered from a site that was
missed.

The client is the reason the builtins alone are not enough. Every REST call
goes through its own send path, which catches whatever ``httpx`` raised and
re-raises it wrapped in ``ResponseHandlingException`` - a plain ``Exception``,
subclass of neither ``OSError`` nor ``RuntimeError``. A read timeout, a
refused connection and a dropped socket all arrive as that one type, so a
handler naming only the builtins sees none of them. No raw ``httpx`` type
escapes the client here, because nothing in this codebase enables the gRPC
transport.

``OSError`` and ``RuntimeError`` stay in the tuple: the local backend calls
into the same client API without a socket in the path, and the store's own
guards raise ``RuntimeError``.

Deliberately narrow. This is not ``Exception``: a malformed response, a
programming error in a callback or a bad argument must still escape and be
seen, rather than being recorded as a namespace the server was too slow to
reach.
"""

from __future__ import annotations

from qdrant_client.http.exceptions import ResponseHandlingException

__all__ = ["TRANSPORT_FAILURES"]

#: Catch-tuple for any qdrant call whose failure must defer one namespace
#: rather than abort the caller.
TRANSPORT_FAILURES: tuple[type[BaseException], ...] = (
    OSError,
    RuntimeError,
    ResponseHandlingException,
)
