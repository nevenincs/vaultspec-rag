"""Stand-in release archives, and install requests pinned to them.

The committed pins vouch only for the real release, so a test cannot install
anything through them without downloading it. The install takes its pins as
arguments of the request, though, so a stand-in archive can be held to its
own digests exactly as a release is held to the committed ones: every check
runs, on different expected values.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
import zipfile
from typing import TYPE_CHECKING

from ..qdrant_runtime._constants import MANIFEST_FILENAME
from ..qdrant_runtime._provision import _InstallRequest
from ..qdrant_runtime._resolve import binary_filename
from ._loopback_tls import LOOPBACK_HOST

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "ARCHIVE_SHAPES",
    "NEW_EXECUTABLE",
    "build_archive",
    "install_request",
    "release_archive",
    "sha256_hex",
    "working_files",
]

#: The two archive shapes upstream publishes, exercised on every platform.
ARCHIVE_SHAPES = ("stand-in-asset.zip", "stand-in-asset.tar.gz")

#: The executable a stand-in release holds unless a test says otherwise.
NEW_EXECUTABLE = b"\x7fnew stand-in server\x00" * 512


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_archive(asset: str, members: dict[str, bytes]) -> bytes:
    """Build a release-shaped archive holding *members*, in *asset*'s format."""
    buffer = io.BytesIO()
    if asset.endswith(".zip"):
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, payload in members.items():
                zf.writestr(name, payload)
    else:
        with tarfile.open(fileobj=buffer, mode="w:gz") as tf:
            for name, payload in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                info.mode = 0o755
                tf.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def release_archive(asset: str, executable: bytes = NEW_EXECUTABLE) -> bytes:
    """An archive laid out as a release is: the executable under a directory."""
    return build_archive(asset, {f"release/{binary_filename()}": executable})


def install_request(
    url: str,
    version_dir: Path,
    *,
    asset: str,
    pinned_archive: bytes,
) -> _InstallRequest:
    """A first-install request pinned to *pinned_archive* and the new executable.

    A test that needs another pin, other limits, or a request that replaces an
    install derives it from this one, so the difference it is about stays
    visible.
    """
    return _InstallRequest(
        url=url,
        redirect_hosts=frozenset({LOOPBACK_HOST}),
        asset=asset,
        archive_sha256=sha256_hex(pinned_archive),
        executable_sha256=sha256_hex(NEW_EXECUTABLE),
        version_dir=version_dir,
        previously="absent",
    )


def working_files(version_dir: Path) -> list[str]:
    """Every file in *version_dir* other than an install's own two."""
    keep = {binary_filename(), MANIFEST_FILENAME}
    return sorted(p.name for p in version_dir.iterdir() if p.name not in keep)
