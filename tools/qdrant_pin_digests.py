"""Derive the SHA256 pin table for a Qdrant server release.

Moving the pin means replacing every digest in ``QDRANT_ASSET_SHA256``, and a
digest taken alongside the artifact it describes attests to nothing but itself.
What makes the new table trustworthy is the step before it: re-deriving the
digests already committed for the OUTGOING version and watching them reproduce
exactly. That shows this method, this host set, and this transport still return
what the reviewed constants say they returned, so the same run against the new
version is evidence rather than assertion.

    python tools/qdrant_pin_digests.py 1.18.2   # must reproduce the committed table
    python tools/qdrant_pin_digests.py 1.19.0   # the table to commit

Nothing here writes to the source tree. The digests are printed for a human to
paste and review, because the pin is the boundary that decides whether a
downloaded binary is allowed to execute.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from http.client import HTTPMessage
    from typing import IO

from vaultspec_rag.qdrant_runtime._constants import (
    ALLOWED_DOWNLOAD_HOSTS,
    QDRANT_ASSET_SHA256,
    QDRANT_RELEASE_BASE_URL,
)

_CHUNK = 1 << 20


class _AllowedHostsOnly(urllib.request.HTTPRedirectHandler):
    """Refuse a redirect leaving the allowed host set or downgrading from TLS.

    The release host redirects to an object store, so redirects cannot simply
    be disabled. They are followed only within the same set the provisioner
    itself allows.
    """

    def redirect_request(  # noqa: PLR0913 - signature fixed by urllib
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        parts = urlsplit(newurl)
        if parts.scheme != "https" or parts.hostname not in ALLOWED_DOWNLOAD_HOSTS:
            raise RuntimeError(f"refused redirect outside the allowed hosts: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def asset_digest(version: str, asset: str) -> str:
    """Stream one release asset and return its SHA256, keeping nothing."""
    opener = urllib.request.build_opener(_AllowedHostsOnly())
    digest = hashlib.sha256()
    with opener.open(
        f"{QDRANT_RELEASE_BASE_URL}/v{version}/{asset}", timeout=300
    ) as response:
        while chunk := response.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    version = argv[1]
    reproduced = True
    for asset, committed in QDRANT_ASSET_SHA256.items():
        derived = asset_digest(version, asset)
        matches = derived == committed
        reproduced = reproduced and matches
        marker = "  (matches committed)" if matches else ""
        print(f"{asset}\n    {derived}{marker}", flush=True)
    print()
    if reproduced:
        print(f"every digest for v{version} matches the committed pin table")
    else:
        print(
            f"digests for v{version} differ from the committed table; this is "
            "expected when deriving a new pin, and a finding when re-deriving "
            "the version already pinned"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
