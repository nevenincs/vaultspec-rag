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

Every asset is fetched from the shipped default source through the
provisioner's own downloader, never from a source an operator configured: a
pin derived from a mirror would attest to the mirror. Each asset is staged in a
temporary directory that is removed before the next one is fetched. The
executable digest is the hash of what the provisioner's own extraction produces
from that archive, so the pin and the install cannot disagree about which
member is the server. No downloaded file is ever run.

Nothing here writes to the source tree. The digests are printed for a human to
paste and review, because the pin is the boundary that decides whether a
downloaded binary is allowed to execute.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from vaultspec_rag.config._schema import comma_separated
from vaultspec_rag.config._settings import rag_default
from vaultspec_rag.qdrant_runtime._constants import (
    ASSET_WINDOWS_X86,
    QDRANT_ASSET_SHA256,
    QDRANT_EXECUTABLE_SHA256,
)
from vaultspec_rag.qdrant_runtime._download import download_https
from vaultspec_rag.qdrant_runtime._provision import (
    extract_verified_archive,
    file_sha256,
)
from vaultspec_rag.qdrant_runtime._resolve import binary_filename


def asset_digests(version: str, asset: str) -> tuple[str, str]:
    """Fetch one release asset; return its archive and executable SHA256.

    The staged archive is hashed, and the extraction re-hashes that same file
    against the result before unpacking, so the executable digest belongs to
    the archive digest reported beside it.
    """
    base_url = str(rag_default("qdrant_release_base_url"))
    redirect_hosts = frozenset(
        comma_separated(str(rag_default("qdrant_download_hosts")))
    )
    # Named for the asset's platform, never the one this tool happens to run on:
    # every asset is derived from one machine.
    executable_name = binary_filename(
        "win32" if asset == ASSET_WINDOWS_X86 else "linux"
    )
    with tempfile.TemporaryDirectory() as staging:
        archive = Path(staging) / asset
        with archive.open("wb") as staged:
            download_https(
                f"{base_url}/v{version}/{asset}",
                staged,
                redirect_hosts=redirect_hosts,
            )
        digest = file_sha256(archive)
        _, executable = extract_verified_archive(
            archive,
            digest,
            Path(staging),
            binary_name=executable_name,
        )
    return digest, executable


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
