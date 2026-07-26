"""The one opener for talking to a loopback HTTP server.

Two packages built this independently - the service client and the qdrant
runtime - each with a multi-paragraph comment explaining the same threat, and
``serviceclient/_transport.py`` even noted that "the qdrant runtime's loopback
openers are built the same way". They then diverged on the control that
matters: only one refused redirects. That is the shape duplication always
takes here, and the copy that never got the fix is the one that shipped the
gap.

Both defences answer the same question - can a responder other than the
intended service decide what this process believes?

- **Proxy map emptied.** The standard library does not bypass loopback
  automatically, so an operator's ``http_proxy`` would route a 127.0.0.1
  request off the host. The proxy could then answer in the service's place,
  and a bearer credential on the request would travel with it.
- **Redirects refused.** These callers address 127.0.0.1 at a known port and
  no route on either service emits a 3xx, so a redirect means something else
  answered. Following one hands that responder the destination: the standard
  library copies request headers onto the redirect target without comparing
  hosts or stripping credentials, and the target's 200 would be adopted as the
  service's own answer - a spoofed "ready" deciding whether a caller attaches
  to a server that is not there.

This is NOT the opener for fetching anything off-host. Provisioning downloads
the pinned qdrant binary over public HTTPS and needs redirects to happen while
re-checking scheme and host across each hop, so it builds its own host-pinning
opener. Merging that one in would delete a security control, not duplicate it.
"""

from __future__ import annotations

import urllib.request
from typing import Final

__all__ = ["LOOPBACK_OPENER", "NoRedirect"]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse HTTP redirects on every request made through this opener.

    Returning ``None`` declines the redirect, which leaves the 3xx to surface
    as an ordinary ``HTTPError``. That is a subclass of ``URLError`` and so of
    ``OSError``, so every existing caller's error handling already catches it
    and fails closed - a redirecting responder reads as unavailable rather
    than as ready.
    """

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        _ = req, fp, code, msg, headers, newurl
        return None


#: Built once so neither defence can be applied on one probe path and quietly
#: forgotten on another - which is exactly what happened while there were two.
LOOPBACK_OPENER: Final = urllib.request.build_opener(
    NoRedirect, urllib.request.ProxyHandler({})
)
