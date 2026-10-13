"""Digests, staging files and single-member extraction, for any native binary.

The steps every pinned native install goes through, with nothing in them that
says which program is being installed. A caller supplies the digests, the
member name, the directory and the words an operator reads; this module
supplies the order, and the order is the point:

- An archive is hashed before anything is read out of it, through the handle
  it was hashed from, so what is extracted is what the digest covered.
- A member is matched by its basename alone, so a path embedded in an archive
  never decides where anything is written.
- A staging file is created exclusively under a name nothing reads as an
  install, so a run killed mid-write strands no executable and cannot be
  made to follow a planted link.
- An executable is hashed after its last byte is written and before it
  replaces anything.

Stdlib-only and free of service configuration: the release tooling installs
its own pinned artifacts through these same functions.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import sys
import tarfile
import zipfile
from contextlib import contextmanager
from typing import IO, TYPE_CHECKING, Final

from ._download import SILENT, Progress

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

__all__ = [
    "STAGING_SUFFIX",
    "ChecksumMismatchError",
    "archive_member",
    "extract_verified_archive",
    "file_sha256",
    "mark_executable",
    "open_destination",
    "open_staging",
    "stream_sha256",
    "verify_native_binary",
]

_COPY_CHUNK_BYTES = 1 << 20

#: Ends the name of every working file an install creates in a version
#: directory. Nothing reads a file carrying it as an install, so a run killed
#: before it could clean up strands no executable.
STAGING_SUFFIX: Final[str] = ".staging"


class ChecksumMismatchError(RuntimeError):
    """Raised when an artifact does not hash to its committed SHA256 digest.

    Nothing from the artifact is kept or installed once this is raised.
    """

    def __init__(self, name: str, expected: str, actual: str) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"SHA256 mismatch for {name}: expected {expected}, got {actual}. "
            "Nothing from it was kept or installed. The upstream asset may "
            "have been replaced, or the committed pin is stale."
        )


def stream_sha256(handle: IO[bytes]) -> str:
    """Return the hex SHA256 of everything in *handle*, read from its start."""
    handle.seek(0)
    digest = hashlib.sha256()
    while chunk := handle.read(_COPY_CHUNK_BYTES):
        digest.update(chunk)
    return digest.hexdigest()


def file_sha256(path: Path) -> str:
    """Return the hex SHA256 digest of *path*'s content."""
    with path.open("rb") as handle:
        return stream_sha256(handle)


def verify_native_binary(binary: Path, expected_sha256: str) -> None:
    """Rehash a regular executable immediately before a supervised launch."""
    if (
        binary.is_symlink()
        or not binary.is_file()
        or file_sha256(binary) != expected_sha256
    ):
        raise RuntimeError(f"Native executable pin mismatch: {binary}")


def open_destination(path: Path) -> IO[bytes]:
    """Open *path* for writing without following a pre-planted symlink.

    A local attacker who can pre-create a symlink at the destination could
    otherwise redirect the write outside the directory the caller chose. We
    unlink any existing symlink and open with ``O_NOFOLLOW`` where available,
    owner-only.
    """
    if path.is_symlink():
        path.unlink()
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    return os.fdopen(os.open(path, flags, 0o600), "wb")


def open_staging(directory: Path, label: str) -> tuple[Path, IO[bytes]]:
    """Create a uniquely named staging file in *directory*, open read-write.

    The name carries the pid and a random token and the file is created
    exclusively, so the open fails rather than following or truncating
    anything already planted at that name. Staging beside the destination
    keeps the final move a rename within one volume, which is what makes it
    atomic.
    """
    path = directory / f".{label}.{os.getpid()}.{os.urandom(6).hex()}{STAGING_SUFFIX}"
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    return path, os.fdopen(os.open(path, flags, 0o600), "w+b")


def mark_executable(path: Path) -> None:
    """Make *path* runnable by its owner, and by nobody else."""
    if sys.platform != "win32":
        # Owner-only rwx: the service runs as one user; a world-executable
        # managed binary needlessly widens who can run it on a shared host.
        path.chmod(0o700)


def _zip_member(zf: zipfile.ZipFile, target_name: str) -> zipfile.ZipInfo | None:
    """Return the one regular *target_name* entry of *zf*, or ``None``."""
    matches = [
        info for info in zf.infolist() if _basename(info.filename) == target_name
    ]
    if len(matches) != 1:
        return None
    info = matches[0]
    if info.is_dir() or stat.S_IFMT(info.external_attr >> 16) not in (
        0,
        stat.S_IFREG,
    ):
        return None
    return info


def _tar_member(tf: tarfile.TarFile, target_name: str) -> tarfile.TarInfo | None:
    """Return the one regular *target_name* entry of *tf*, or ``None``."""
    matches = [
        member for member in tf.getmembers() if _basename(member.name) == target_name
    ]
    if len(matches) != 1 or not matches[0].isfile():
        return None
    return matches[0]


def _basename(embedded: str) -> str:
    """Return the final component of a name an archive carries.

    Both separators are treated as separators whatever platform this runs on:
    an archive is written elsewhere, and its entry names are data.
    """
    return embedded.replace("\\", "/").rsplit("/", 1)[-1]


@contextmanager
def archive_member(
    archive: IO[bytes], archive_name: str, target_name: str
) -> Generator[tuple[IO[bytes], int]]:
    """Yield a reader over the one regular *target_name* member of *archive*.

    The reader comes with the member's uncompressed size, as the archive
    records it, so a caller can know what extraction will write before it
    writes any of it.

    Handles both the ``.zip`` and the ``.tar.gz`` shapes, chosen by
    *archive_name*'s extension. Only the named member is read - any other
    entry is ignored - and it is matched by basename, so a path embedded in
    the archive never decides where anything is written.

    The archive is read through the caller's open handle rather than reopened
    by path, so the bytes extracted are the bytes that handle was hashed from.
    The member is validated before the reader is yielded, so a caller that
    opens its destination inside the block never creates one for an archive
    that is refused.

    Raises:
        ValueError: When *target_name* is not a bare filename.
        RuntimeError: When the archive does not hold exactly one regular
            member of that name.
    """
    if (
        not target_name
        or target_name in {".", ".."}
        or _basename(target_name) != target_name
    ):
        raise ValueError("The executable name must be a basename")
    invalid_member = RuntimeError(
        f"Archive {archive_name} requires one regular {target_name} member"
    )
    archive.seek(0)
    if archive_name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            info = _zip_member(zf, target_name)
            if info is None:
                raise invalid_member
            with zf.open(info) as source:
                yield source, info.file_size
        return
    with tarfile.open(fileobj=archive, mode="r:gz") as tf:
        member = _tar_member(tf, target_name)
        source = tf.extractfile(member) if member is not None else None
        if member is None or source is None:
            raise invalid_member
        with source:
            yield source, member.size


def extract_verified_archive(
    archive: Path,
    expected_sha256: str,
    dest_dir: Path,
    *,
    binary_name: str,
    progress: Progress = SILENT,
) -> tuple[Path, str]:
    """Verify *archive* against *expected_sha256*, then extract.

    Verification strictly precedes extraction; on mismatch the archive
    is deleted and :class:`ChecksumMismatchError` raised, so a
    tampered artifact is never unpacked. The archive is opened once and both
    hashed and extracted through that handle, so the file cannot be swapped
    between the two.

    Args:
        archive: The downloaded release archive.
        expected_sha256: The committed digest to verify against.
        dest_dir: Directory to place the extracted binary in.
        binary_name: The executable member to extract, by basename.
        progress: Where each stage is announced and what it calls the
            artifact. Reporting only: the verify-then-extract order it
            describes is the order enforced below.

    Returns:
        ``(binary_path, binary_sha256)`` for the extracted executable.

    Raises:
        ChecksumMismatchError: On digest mismatch (archive deleted).
    """
    binary = dest_dir / binary_name
    with archive.open("rb") as handle:
        progress.say(f"Verifying the {progress.subject} download checksum...")
        actual = stream_sha256(handle)
        verified = actual.lower() == expected_sha256.lower()
        if verified:
            progress.say(f"Extracting the {progress.subject}...")
            with (
                archive_member(handle, archive.name, binary_name) as (source, _),
                open_destination(binary) as out,
            ):
                shutil.copyfileobj(source, out, _COPY_CHUNK_BYTES)
    if not verified:
        # Removed only once the handle above is closed: an open file cannot
        # be unlinked on Windows.
        archive.unlink(missing_ok=True)
        raise ChecksumMismatchError(archive.name, expected_sha256, actual)
    mark_executable(binary)
    progress.say(f"Verifying the extracted {progress.subject}...")
    return binary, file_sha256(binary)
