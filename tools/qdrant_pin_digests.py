"""Derive the SHA256 pin tables for a Qdrant server release.

Moving the pin means replacing every digest in ``QDRANT_ASSET_SHA256`` and
``QDRANT_EXECUTABLE_SHA256``, and a digest taken alongside the artifact it
describes attests to nothing but itself. What makes the new tables trustworthy
is the step before them: re-deriving the digests already committed for the
OUTGOING version and watching them reproduce exactly. That shows this method,
this host set, and this transport still return what the reviewed constants say
they returned, so the same run against the new version is evidence rather than
assertion.

    python tools/qdrant_pin_digests.py 1.18.2   # must reproduce the committed tables
    python tools/qdrant_pin_digests.py 1.19.0   # the tables to commit

Each asset is staged in a temporary directory that is removed before the next
one is fetched. The executable digest is the hash of what the provisioner's own
extraction produces from that archive, so the pin and the install cannot
disagree about which member is the server. No downloaded file is ever run.

Nothing here writes to the source tree. The digests are printed for a human to
paste and review, because the pin is the boundary that decides whether a
downloaded binary is allowed to execute.
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from http.client import HTTPMessage
    from typing import IO

from vaultspec_rag.qdrant_runtime._constants import (
    ALLOWED_DOWNLOAD_HOSTS,
    ASSET_WINDOWS_X86,
    QDRANT_ASSET_SHA256,
    QDRANT_EXECUTABLE_SHA256,
    QDRANT_RELEASE_BASE_URL,
)
from vaultspec_rag.qdrant_runtime._provision import extract_verified_archive
from vaultspec_rag.qdrant_runtime._resolve import binary_filename

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


def asset_digests(version: str, asset: str) -> tuple[str, str]:
    """Stream one release asset; return its archive and executable SHA256.

    The archive is hashed as it arrives. The extraction then re-hashes the
    staged file against that digest before unpacking, which proves the bytes
    unpacked are the bytes that were hashed off the wire.
    """
    opener = urllib.request.build_opener(_AllowedHostsOnly())
    digest = hashlib.sha256()
    # Named for the asset's platform, never the one this tool happens to run on:
    # every asset is derived from one machine.
    executable_name = binary_filename(
        "win32" if asset == ASSET_WINDOWS_X86 else "linux"
    )
    with tempfile.TemporaryDirectory() as staging:
        archive = Path(staging) / asset
        with (
            opener.open(
                f"{QDRANT_RELEASE_BASE_URL}/v{version}/{asset}", timeout=300
            ) as response,
            archive.open("wb") as staged,
        ):
            while chunk := response.read(_CHUNK):
                digest.update(chunk)
                staged.write(chunk)
        _, executable = extract_verified_archive(
            archive,
            digest.hexdigest(),
            Path(staging),
            binary_name=executable_name,
        )
    return digest.hexdigest(), executable


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    version = argv[1]
    reproduced = True
    for asset, committed_archive in QDRANT_ASSET_SHA256.items():
        archive, executable = asset_digests(version, asset)
        print(asset, flush=True)
        for label, derived, committed in (
            ("archive", archive, committed_archive),
            ("executable", executable, QDRANT_EXECUTABLE_SHA256.get(asset)),
        ):
            matches = derived == committed
            reproduced = reproduced and matches
            marker = "  (matches committed)" if matches else ""
            print(f"    {label:<10} {derived}{marker}", flush=True)
    print()
    if reproduced:
        print(f"every digest for v{version} matches the committed pin tables")
    else:
        print(
            f"digests for v{version} differ from the committed tables; this is "
            "expected when deriving a new pin, and a finding when re-deriving "
            "the version already pinned"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
