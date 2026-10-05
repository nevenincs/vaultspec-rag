"""Stand-in release archives, and the one way a test makes one the pinned release.

The committed pins vouch only for the real release, which no test can hold
without downloading it. Two things here let the shipped code be driven
against a stand-in instead, with every check still running.

An install request carries its own digests, so the install step can be handed
a request pinned to a stand-in archive of either format: :func:`install_request`.

Everything above the install step reads the committed pin tables: what a
provisioning call plans, what the classifier calls healthy, what the resolver
and the spawn check accept, and so every command. For those,
:func:`pinned_stand_in` writes a stand-in's two digests into the tables for
the length of a block. It is a substitution of a trust constant, and it is
the only one: nothing else in the tests may write either table, a guard
fails on any other writer, and every use of this one is counted.

What a test under it shows is that the shipped code holds a file to the
table. What it does not show is that the table describes the real release.
That is shown where the real release is: by the tool that derives the digests
from the official source, and by runs against the real archive.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import tarfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..config._types import EnvVar
from ..qdrant_runtime._constants import (
    MANIFEST_FILENAME,
    QDRANT_ASSET_SHA256,
    QDRANT_EXECUTABLE_SHA256,
)
from ..qdrant_runtime._provision import _InstallRequest
from ..qdrant_runtime._resolve import (
    asset_for_platform,
    binary_filename,
    qdrant_bin_dir,
)
from ._loopback_tls import LOOPBACK_HOST, send_bytes
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ._loopback_tls import LoopbackSources, StandInSource

__all__ = [
    "ARCHIVE_SHAPES",
    "NEW_EXECUTABLE",
    "ServedRelease",
    "abandon_a_working_file",
    "build_archive",
    "install_request",
    "pinned_stand_in",
    "place_stand_in",
    "release_archive",
    "served_stand_in",
    "sha256_hex",
    "working_files",
]

#: The two archive shapes upstream publishes, exercised on every platform.
ARCHIVE_SHAPES = ("stand-in-asset.zip", "stand-in-asset.tar.gz")

#: The executable a stand-in release holds unless a test says otherwise.
NEW_EXECUTABLE = b"\x7fnew stand-in server\x00" * 512

#: The timestamp every member of a stand-in archive carries: the earliest a
#: zip can record. A fixed one makes the same members build the same bytes.
_MEMBER_DATE = (1980, 1, 1, 0, 0, 0)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_archive(asset: str, members: dict[str, bytes]) -> bytes:
    """Build a release-shaped archive holding *members*, in *asset*'s format.

    The same members always build the same bytes, in any process: no clock is
    read. Two processes that build the same stand-in therefore agree on its
    digest, which a test that runs an install in a child depends on.
    """
    buffer = io.BytesIO()
    if asset.endswith(".zip"):
        with zipfile.ZipFile(buffer, "w") as zf:
            for name, payload in members.items():
                info = zipfile.ZipInfo(name, date_time=_MEMBER_DATE)
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, payload)
        return buffer.getvalue()
    with (
        gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w") as tf,
    ):
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


@contextmanager
def pinned_stand_in(executable: bytes = NEW_EXECUTABLE) -> Generator[bytes]:
    """Make a stand-in the pinned release of this platform's asset, for the block.

    Inside the block a file whose content is *executable* is the pinned
    release executable to everything that reads the committed tables, and the
    archive yielded is the pinned release archive. Nothing is passed to the
    code under test and nothing in it is replaced: only the two digests it
    holds a file to are different.

    The committed digests are put back when the block ends, whatever ends it:
    a return, a failed assertion, an interrupt. Blocks may nest; each puts
    back what it found.

    Yields:
        The stand-in release archive, in this platform's own format, for a
        test that serves it from a source or passes it as a local archive.
    """
    asset = asset_for_platform()
    archive = release_archive(asset, executable)
    found = (QDRANT_ASSET_SHA256[asset], QDRANT_EXECUTABLE_SHA256[asset])
    QDRANT_ASSET_SHA256[asset] = sha256_hex(archive)
    QDRANT_EXECUTABLE_SHA256[asset] = sha256_hex(executable)
    try:
        yield archive
    finally:
        QDRANT_ASSET_SHA256[asset], QDRANT_EXECUTABLE_SHA256[asset] = found


@dataclass(frozen=True)
class ServedRelease:
    """A pinned stand-in release: its archive, and the source serving it."""

    archive: bytes
    source: StandInSource


@contextmanager
def served_stand_in(sources: LoopbackSources) -> Generator[ServedRelease]:
    """Pin a stand-in release and serve it as the configured release source.

    For the block, the stand-in is the pinned release of this platform's
    asset to everything that reads the committed tables, and the release
    source setting names a real loopback server that answers every request
    with its archive. The source logs each request, so a run that reached for
    the network when it had no need to shows up in the log, and one that
    should have downloaded shows that it did.
    """
    with pinned_stand_in() as archive:
        source = sources.serve(lambda handler: send_bytes(handler, archive))
        with managed_env(
            **{EnvVar.QDRANT_RELEASE_BASE_URL.value: source.url("/mirror")}
        ):
            yield ServedRelease(archive, source)


def abandon_a_working_file(version_dir: Path) -> Path:
    """Leave a file exactly as a killed run's download would be left."""
    version_dir.mkdir(parents=True, exist_ok=True)
    abandoned = version_dir / f".{asset_for_platform()}.4242.0123456789ab.staging"
    abandoned.write_bytes(b"half a download from a run that was killed")
    return abandoned


def place_stand_in(executable: bytes = NEW_EXECUTABLE) -> Path:
    """Write *executable* at the managed install's name, with no manifest.

    Substitutes nothing. What it leaves is what a run killed between moving
    the executable into place and recording it leaves.
    """
    version_dir = qdrant_bin_dir()
    version_dir.mkdir(parents=True, exist_ok=True)
    binary = version_dir / binary_filename()
    binary.write_bytes(executable)
    return binary


def working_files(version_dir: Path) -> list[str]:
    """Every file in *version_dir* other than an install's own two."""
    keep = {binary_filename(), MANIFEST_FILENAME}
    return sorted(p.name for p in version_dir.iterdir() if p.name not in keep)
