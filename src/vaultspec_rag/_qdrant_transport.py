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

That same send path signals a server that DID answer, and answered with a
refusal, as different types again: every non-2xx status becomes
``UnexpectedResponse``, and a 429 carrying a ``Retry-After`` header becomes
``ResourceExhaustedResponse``. Neither is a ``ResponseHandlingException``, so
naming that wrapper alone covered a server too slow to reply and missed one
replying 500 or 503 - to a maintenance cycle the same failure, on the same
call, with the same consequence: the drop loop is already destroying by the
time it can fail, and an escape carries a half-deleted namespace out of the
cycle with no outcome recorded anywhere.

The client's two exception roots are named rather than the individual leaves
under them. Every leaf either root carries is a statement about a request that
produced no usable answer, and neither root is raised for a caller's own
mistake - those arrive as builtins. Naming the roots is what makes this a
class instead of an enumeration, and an enumeration is precisely what let the
answered-with-an-error leaves through after the unanswered one was handled.

``OSError`` and ``RuntimeError`` stay in the tuple: the local backend calls
into the same client API without a socket in the path, and the store's own
guards raise ``RuntimeError``.

Deliberately narrow. This is not ``Exception``: a programming error in a
callback and a bad argument still escape and are seen, rather than being
recorded as a namespace the server was too slow to reach. ``TypeError`` and
``ValueError`` are what that narrowness is made of - neither is one of the
builtins named above, and neither descends from a client root.

A malformed response is NOT in that set, and saying it was overstated the
boundary. The client parses a 2xx body itself and re-raises the validation
failure as ``ResponseHandlingException``, so a schema mismatch is absorbed at
every site naming this tuple and deferred as a namespace that could not be
read. That outcome is right - a body this client cannot parse is an answer
this code cannot use - but it is an absorbed failure, not an escaping one,
and a boundary claimed in the wrong place is worse than one left unclaimed.
"""

from __future__ import annotations

from qdrant_client.common.client_exceptions import (
    QdrantException,
    ResourceExhaustedResponse,
)
from qdrant_client.http.exceptions import ApiException, UnexpectedResponse

__all__ = ["SERVER_REFUSALS", "TRANSPORT_FAILURES"]

#: Catch-tuple for any qdrant call whose failure must defer one namespace
#: rather than abort the caller.
TRANSPORT_FAILURES: tuple[type[BaseException], ...] = (
    OSError,
    RuntimeError,
    ApiException,
    QdrantException,
)

#: The subset of :data:`TRANSPORT_FAILURES` where a response did arrive and
#: carried the refusal. For the surfaces whose remediation differs and only
#: those: sending an operator to start a service that answered is worse than
#: saying nothing, so such a caller catches this first and the whole class
#: second. Every other site wants the class, because a namespace deferred for
#: a refusal and one deferred for a silence are deferred alike.
SERVER_REFUSALS: tuple[type[BaseException], ...] = (
    UnexpectedResponse,
    ResourceExhaustedResponse,
)
