"""Download-on-first-use provisioning of the pinned Qdrant server binary.

The flow: resolve the release asset for the running platform and download it
over HTTPS from the configured release base, with every redirect held to HTTPS
and to the configured download hosts. The archive lands in a uniquely named
staging file and is hashed against its committed digest BEFORE anything is
extracted. The single executable member is extracted to a second staging
file, hashed against the committed executable digest for the asset, and only
then moved onto the installed name in one atomic replace; the manifest is
written last. A failure or an interrupt at any stage removes this run's
staging files and leaves a previous install exactly as it was. A digest
mismatch is a hard failure.

What is installed is judged by hashing the executable, never by reading the
manifest. A run that finds the pinned executable already in place downloads
nothing, whatever its manifest says or lacks, and writes the manifest again
if it is missing or wrong; that is all a run killed between the replace and
the manifest leaves to do. An executable that is anything else is neither
run nor overwritten until the upgrade form asks for it.

A host with no route to a release source installs the same archive from a
local copy. That changes where the archive is read from and nothing else:
the same two digests, the same staging, the same replace. The managed
directory holds the pinned release only. A binary of the operator's own is
never copied into it; it is named through the operator binary settings.

Working files a killed run left behind are removed by the next run of any
kind that can show no run is still using them, whether or not it installs.

Space is checked before it is spent. A download whose archive and extracted
executable cannot both fit on the managed directory's volume is refused
before its first byte is read, and an extraction that cannot fit is refused
before its first byte is written. A write that fails anyway, because the
volume filled in between, is one failed outcome like any other.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import shutil
import stat
import sys
import tarfile
import time
import zipfile
import zlib
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, TYPE_CHECKING

from .._atomic_write import (
    JsonWriteOptions,
    replace_atomically,
    write_json_atomically,
)
from .._rmtree import remove_tree
from .._store_writes import classify_write_error, free_bytes
from .._sync_vocabulary import ProvisionAction
from .._units import human_bytes
from ._constants import (
    MANIFEST_FILENAME,
    MANIFEST_SOURCE_ARCHIVE,
    MANIFEST_SOURCE_DOWNLOAD,
    MANIFEST_SOURCE_UNRECORDED,
    QDRANT_ASSET_SHA256,
    QDRANT_EXECUTABLE_SHA256,
    QDRANT_SERVER_VERSION,
    ProvisionReport,
)
from ._download import (
    DownloadError,
    DownloadFailure,
    DownloadLimits,
    download_https,
    no_progress,
)
from ._managed_install import InstallState, ManagedInstall, classify_managed_binary

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterable

logger = logging.getLogger(__name__)

__all__ = [
    "ChecksumMismatchError",
    "clean_provisioned",
    "extract_verified_archive",
    "file_sha256",
    "provision",
    "provisioned_versions",
]

_COPY_CHUNK_BYTES = 1 << 20
_DOWNLOAD_LIMITS = DownloadLimits()
# Marks a file as one run's working copy. Nothing reads a file carrying it as
# an install, so a run killed before it could clean up strands no executable.
_STAGING_SUFFIX = ".staging"
# One file for every version dir, beside them, so two runs cannot write the
# same install at once whichever version each is after.
_LOCK_FILENAME = "provision.lock"
# A waiter outlasts the longest a holder can legitimately take: one whole
# download plus its verification and extraction. A holder that dies releases
# the lock with its process, so this is never spent waiting on a dead one.
_LOCK_WAIT_SECONDS = _DOWNLOAD_LIMITS.deadline_seconds + 60.0
_LOCK_POLL_SECONDS = 0.2
# Kept free beyond what the install itself writes: the manifest, the
# filesystem's own bookkeeping, and whatever else is writing to the volume
# while this runs.
_FREE_SPACE_RESERVE_BYTES = 32 << 20
# How much larger than its archive the executable is assumed to be before the
# archive is in hand to say exactly. The pinned Windows executable is 2.9
# times its archive; a wrong guess here costs nothing but an early refusal,
# because the exact size is checked again before extraction.
_EXECUTABLE_BYTES_PER_ARCHIVE_BYTE = 4

# Everything that can go wrong between creating the first staging file and the
# manifest landing, and is an outcome to report rather than a defect to raise.
# An interrupt is deliberately absent: it propagates once staging is removed.
_INSTALL_FAILURES = (
    OSError,
    RuntimeError,
    EOFError,
    tarfile.TarError,
    zipfile.BadZipFile,
    zlib.error,
)


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


class _InsufficientSpaceError(RuntimeError):
    """The managed directory's volume cannot hold what an install would write.

    Raised before the bytes in question are transferred or extracted, so
    nothing has been written on its account.
    """


def _stream_sha256(handle: IO[bytes]) -> str:
    """Return the hex SHA256 of everything in *handle*, read from its start."""
    handle.seek(0)
    digest = hashlib.sha256()
    while chunk := handle.read(_COPY_CHUNK_BYTES):
        digest.update(chunk)
    return digest.hexdigest()


def file_sha256(path: Path) -> str:
    """Return the hex SHA256 digest of *path*'s content."""
    with path.open("rb") as handle:
        return _stream_sha256(handle)


def verify_native_binary(binary: Path, expected_sha256: str) -> None:
    """Rehash a regular executable immediately before a supervised launch."""
    if (
        binary.is_symlink()
        or not binary.is_file()
        or file_sha256(binary) != expected_sha256
    ):
        raise RuntimeError(f"Native executable pin mismatch: {binary}")


def _open_destination(path: Path) -> IO[bytes]:
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


def _open_staging(directory: Path, label: str) -> tuple[Path, IO[bytes]]:
    """Create a uniquely named staging file in *directory*, open read-write.

    The name carries the pid and a random token and the file is created
    exclusively, so the open fails rather than following or truncating
    anything already planted at that name. Staging beside the destination
    keeps the final move a rename within one volume, which is what makes it
    atomic.
    """
    path = directory / (
        f".{label}.{os.getpid()}.{os.urandom(6).hex()}{_STAGING_SUFFIX}"
    )
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    return path, os.fdopen(os.open(path, flags, 0o600), "w+b")


@dataclass(frozen=True)
class _InstallRequest:
    """One staged install: its source, its pins, and what bounds it.

    Attributes:
        url: Where the release asset is published. Downloaded from unless
            ``local_archive`` is set; then it is only named, in a message
            telling the operator where the right file comes from.
        local_archive: The operator's own copy of the release archive, to
            install from without a request. Held to ``archive_sha256`` like a
            download.
        limits: How long, how large and how persistent the download may be.
        reserve_bytes: Free space the volume must keep beyond what the
            install writes.
        open_staging: Creates each staging file. The one point at which the
            install opens a file it will write a transfer or an extraction
            into.
    """

    url: str
    redirect_hosts: frozenset[str]
    asset: str
    archive_sha256: str
    executable_sha256: str
    version_dir: Path
    previously: str
    on_progress: Callable[[str], None] = no_progress
    local_archive: Path | None = None
    limits: DownloadLimits = _DOWNLOAD_LIMITS
    reserve_bytes: int = _FREE_SPACE_RESERVE_BYTES
    open_staging: Callable[[Path, str], tuple[Path, IO[bytes]]] = _open_staging


_INSTALL_COMMAND = "vaultspec-rag server qdrant install"


def _install_command(request: _InstallRequest) -> str:
    """Name the whole command that performs *request*.

    A failure of this install is read by someone who may have run a
    different command to get here: a start provisions on the way. So a remedy
    names the command that does this install, in full, and never says to
    repeat a command or add a flag to one.
    """
    command = _INSTALL_COMMAND
    if request.previously != InstallState.ABSENT:
        command += " --upgrade"
    if request.local_archive is not None:
        command += f' --archive "{request.local_archive}"'
    return f"`{command}`"


def _managed_directory_remedy(version_dir: Path, rerun: str) -> str:
    """Say what to do when the managed directory itself cannot be written."""
    # Function-local: the build tools import this module in an interpreter
    # that has no service configuration to import.
    from ..config._types import EnvVar

    return (
        f"Check that {version_dir} is a directory this user can create and "
        "write, with no file standing where a directory belongs on the way "
        f"to it, or point {EnvVar.STATUS_DIR.value} at a directory that is. "
        f"Then run {rerun}."
    )


def _require_free_space(
    request: _InstallRequest, *, archive_bytes: int, executable_bytes: int
) -> None:
    """Refuse an install step the managed directory's volume cannot hold.

    The requirement is what the step is about to write plus the reserve. A
    replaced install does not count towards it: the executable being replaced
    stays where it is until the new one has been verified, so both exist at
    once.

    Raises:
        _InsufficientSpaceError: When less is free than the step needs. The
            message carries the shortfall.
    """
    free = free_bytes(request.version_dir)
    if free is None:
        # A volume that cannot be measured is not judged; a write that does
        # not fit still fails as one outcome.
        return
    needed = archive_bytes + executable_bytes + request.reserve_bytes
    if free >= needed:
        return
    parts = [
        f"{human_bytes(size)} for {what}"
        for size, what in (
            (archive_bytes, "the archive"),
            (executable_bytes, "the executable it holds"),
            (request.reserve_bytes, "working room"),
        )
        if size
    ]
    raise _InsufficientSpaceError(
        "Not enough free space to install the Qdrant server: the volume "
        f"holding {request.version_dir} has {human_bytes(free)} free and the "
        f"install needs {human_bytes(needed)} ({', '.join(parts)}). Free "
        f"{human_bytes(needed - free)} more on that volume, then run "
        f"{_install_command(request)}."
    )


def _discard(paths: Iterable[Path]) -> None:
    """Remove this run's staging files, tolerating ones already moved away."""
    for path in paths:
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)


def _zip_member(zf: zipfile.ZipFile, target_name: str) -> zipfile.ZipInfo | None:
    """Return the one regular *target_name* entry of *zf*, or ``None``."""
    matches = [
        info
        for info in zf.infolist()
        if Path(info.filename.replace("\\", "/")).name == target_name
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
        member
        for member in tf.getmembers()
        if Path(member.name.replace("\\", "/")).name == target_name
    ]
    if len(matches) != 1 or not matches[0].isfile():
        return None
    return matches[0]


@contextmanager
def _binary_member(
    archive: IO[bytes], archive_name: str, target_name: str
) -> Generator[tuple[IO[bytes], int]]:
    """Yield a reader over the one regular executable member of *archive*.

    The reader comes with the member's uncompressed size, as the archive
    records it, so a caller can know what extraction will write before it
    writes any of it.

    Handles both the Windows ``.zip`` (single ``qdrant.exe`` entry)
    and the Unix ``.tar.gz`` (single ``qdrant`` entry) shapes. Only
    the executable member is read - any other entry is ignored - and the
    member is matched by basename, so a path embedded in the archive never
    decides where anything is written.

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
        or Path(target_name).name != target_name
        or "\\" in target_name
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


def _mark_executable(path: Path) -> None:
    """Make *path* runnable by its owner, and by nobody else."""
    if sys.platform != "win32":
        # Owner-only rwx: the service runs as one user; a world-executable
        # managed binary needlessly widens who can run it on a shared host.
        path.chmod(0o700)


def extract_verified_archive(
    archive: Path,
    expected_sha256: str,
    dest_dir: Path,
    *,
    on_progress: Callable[[str], None] = no_progress,
    binary_name: str | None = None,
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
        on_progress: Sink announcing each stage; reporting only, and the
            verify-then-extract order it describes is the order enforced
            below.
        binary_name: The executable member to extract; the qdrant
            executable for this platform when omitted.

    Returns:
        ``(binary_path, binary_sha256)`` for the extracted executable.

    Raises:
        ChecksumMismatchError: On digest mismatch (archive deleted).
    """
    if binary_name is None:
        from ._resolve import binary_filename

        binary_name = binary_filename()
    binary = dest_dir / binary_name
    with archive.open("rb") as handle:
        on_progress("Verifying the Qdrant download checksum...")
        actual = _stream_sha256(handle)
        verified = actual.lower() == expected_sha256.lower()
        if verified:
            on_progress("Extracting the Qdrant server...")
            with (
                _binary_member(handle, archive.name, binary_name) as (source, _),
                _open_destination(binary) as out,
            ):
                shutil.copyfileobj(source, out, _COPY_CHUNK_BYTES)
    if not verified:
        # Removed only once the handle above is closed: an open file cannot
        # be unlinked on Windows.
        archive.unlink(missing_ok=True)
        raise ChecksumMismatchError(archive.name, expected_sha256, actual)
    _mark_executable(binary)
    on_progress("Verifying the extracted Qdrant server...")
    return binary, file_sha256(binary)


def _replace_executable(staged: Path, target: Path, *, rerun: str) -> None:
    """Move a verified staging file onto the installed name in one step.

    Args:
        rerun: The whole command that repeats this install, for the remedy.

    Raises:
        RuntimeError: On Windows, when another process holds *target* open.
        OSError: When the replace fails for any other reason.
    """
    _mark_executable(staged)
    try:
        replace_atomically(staged, target)
    except PermissionError as exc:
        # Only a file can be held open. A refusal over anything else - a
        # directory at the installed name, a directory this user cannot write
        # - is a fault of the managed directory and is reported as one.
        if sys.platform != "win32" or not target.is_file():
            raise
        # Windows refuses to replace a file another process holds open, which
        # a running server does to its own executable. That is the cause in
        # every ordinary case, so say what to do about it instead of
        # surfacing an access-denied error.
        raise RuntimeError(
            f"{target} is held open by another process and cannot be "
            "replaced. A running Qdrant server holds its executable this "
            "way: stop the service with `vaultspec-rag server stop`. Any "
            f"other program reading the file must close it. Then run {rerun}."
        ) from exc


@contextmanager
def _verified_archive(
    request: _InstallRequest, staged: list[Path]
) -> Generator[IO[bytes]]:
    """Yield the release archive, open and already matched to its committed digest.

    The archive comes from one of two places and is held to the same digest
    from either. A download lands in a staging file this run created, which
    is recorded in *staged* for the caller to remove. A local copy is the
    operator's own file: it is opened for reading where it lies, and is never
    copied, moved, renamed or removed, and no request is made for it.

    The handle that was hashed is the one yielded, so whatever is extracted
    from it afterwards is what the digest covered.

    Raises:
        ChecksumMismatchError: When a downloaded archive does not hash to the
            committed digest.
        _WrongArchiveError: When a local file does not.
        _InsufficientSpaceError: When the volume cannot hold the download.
    """
    on_progress = request.on_progress
    if request.local_archive is not None:
        try:
            opened = request.local_archive.open("rb")
        except OSError as exc:
            # Named apart from a fault of the managed directory: this file is
            # the operator's, and the remedy is theirs to apply to it.
            raise RuntimeError(
                f"The archive {request.local_archive} could not be opened "
                f"({exc}). Check that it exists and that this user can read "
                f"it, then run {_install_command(request)}."
            ) from exc
        with opened as archive:
            on_progress(
                f"Verifying {request.local_archive} against the pinned checksum..."
            )
            actual = _stream_sha256(archive)
            if actual.lower() != request.archive_sha256.lower():
                raise _WrongArchiveError(request, actual)
            yield archive
        return

    def admit(declared_bytes: int) -> None:
        _require_free_space(
            request,
            archive_bytes=declared_bytes,
            executable_bytes=declared_bytes * _EXECUTABLE_BYTES_PER_ARCHIVE_BYTE,
        )

    def whole(received: IO[bytes]) -> bool:
        # Asked only of a body nothing in the transfer says is complete. The
        # digest is the one thing here that can tell a cut transfer from a
        # finished one, so it is what answers.
        return _stream_sha256(received).lower() == request.archive_sha256.lower()

    archive_path, archive = request.open_staging(request.version_dir, request.asset)
    staged.append(archive_path)
    with archive:
        logger.info("Downloading %s", request.url)
        on_progress(f"Downloading the Qdrant server ({request.asset})...")
        download_https(
            request.url,
            archive,
            redirect_hosts=request.redirect_hosts,
            on_progress=on_progress,
            limits=replace(request.limits, admit=admit, whole=whole),
        )
        on_progress("Verifying the Qdrant download checksum...")
        actual = _stream_sha256(archive)
        if actual.lower() != request.archive_sha256.lower():
            raise ChecksumMismatchError(request.asset, request.archive_sha256, actual)
        yield archive


def _stage_verified_executable(request: _InstallRequest, staged: list[Path]) -> Path:
    """Obtain and verify the archive, then stage its verified executable.

    Each staging file is recorded in *staged* as it is created, so the caller
    can remove them whatever happens next. The archive handle stays open from
    the hash through the extraction, so both see the same file. The
    executable digest is the check that decides what may be installed: it is
    taken from the staged file itself, after the last byte was written to it.

    Space is asked for before the bytes it covers. Before the first byte of a
    transfer, from the size the response declares and an estimate of the
    executable inside it. Before the first byte of the extraction, from the
    size the verified archive records for its member, which is exact.

    Raises:
        ChecksumMismatchError: When a downloaded archive or the staged
            executable does not hash to its committed digest.
        _WrongArchiveError: When a local archive is not the pinned one.
        _InsufficientSpaceError: When the volume cannot hold the transfer or
            the extraction.
    """
    from ._resolve import binary_filename

    name = binary_filename()
    with _verified_archive(request, staged) as archive:
        request.on_progress("Extracting the Qdrant server...")
        with _binary_member(archive, request.asset, name) as (source, size):
            _require_free_space(request, archive_bytes=0, executable_bytes=size)
            executable_path, executable = request.open_staging(
                request.version_dir, name
            )
            staged.append(executable_path)
            with executable:
                shutil.copyfileobj(source, executable, _COPY_CHUNK_BYTES)
                request.on_progress("Verifying the extracted Qdrant server...")
                actual = _stream_sha256(executable)
    if actual.lower() != request.executable_sha256.lower():
        raise ChecksumMismatchError(
            f"the {name} member of {request.asset}", request.executable_sha256, actual
        )
    return executable_path


def _write_manifest(
    version_dir: Path,
    *,
    asset: str,
    asset_sha256: str,
    binary_sha256: str,
    source: str,
) -> None:
    """Atomically write the provisioning manifest into *version_dir*."""
    manifest: dict[str, str] = {
        "version": QDRANT_SERVER_VERSION,
        "asset": asset,
        "asset_sha256": asset_sha256,
        "binary_sha256": binary_sha256,
        "source": source,
        "provisioned_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    write_json_atomically(
        version_dir / MANIFEST_FILENAME, manifest, JsonWriteOptions(indent=2)
    )


#: What a manifest may say of how a healthy install arrived. The last is what
#: is written for one whose arrival nobody recorded.
_RECORDED_SOURCES = frozenset(
    {MANIFEST_SOURCE_DOWNLOAD, MANIFEST_SOURCE_ARCHIVE, MANIFEST_SOURCE_UNRECORDED}
)


def _recorded_source(healthy: ManagedInstall) -> str | None:
    """Return how *healthy*'s manifest says it arrived, or ``None``.

    ``None`` means no manifest describes the install: there is none, or it
    disagrees with the executable beside it about the version, the asset or
    either digest, or it names a way of arriving that nothing writes. Such a
    manifest changes nothing about whether the install is healthy - the
    executable decided that - and is simply written again.
    """
    from ._resolve import read_manifest

    manifest = read_manifest(healthy.binary.parent)
    if manifest is None:
        return None
    described = {
        "version": QDRANT_SERVER_VERSION,
        "asset": healthy.asset,
        "asset_sha256": QDRANT_ASSET_SHA256.get(healthy.asset, ""),
        "binary_sha256": healthy.sha256,
    }
    if any(manifest.get(field) != value for field, value in described.items()):
        return None
    source = manifest.get("source")
    return source if isinstance(source, str) and source in _RECORDED_SOURCES else None


def _asset_url(release_base_url: str, asset: str) -> str:
    """Return where *asset* of the pinned release lives under the base."""
    return f"{release_base_url}/v{QDRANT_SERVER_VERSION}/{asset}"


def _healthy_report(
    healthy: ManagedInstall, request: _ProvisionRequest, release_base_url: str
) -> ProvisionReport:
    """Report a healthy install as one this run downloads nothing for."""
    # An upgrade finds nothing to do here either: the executable already is
    # the pinned one, and a version bump installs to a new directory.
    return ProvisionReport(
        action=ProvisionAction.UNCHANGED,
        asset=healthy.asset,
        url=_asset_url(release_base_url, healthy.asset),
        binary=healthy.binary,
        sha256=QDRANT_ASSET_SHA256.get(healthy.asset, ""),
        message=(
            "Install already matches the pin; nothing to upgrade."
            if request.upgrade
            else "Verified install already present; nothing to do."
        ),
    )


@dataclass(frozen=True)
class _ManifestRepair:
    """A healthy install whose manifest does not describe it.

    What a run killed between the replace and the manifest leaves behind, and
    what an install made under any older record looks like. Nothing is
    downloaded for it: the executable is already the pinned one.

    Attributes:
        healthy: The install as it was judged.
        settled: The report for this install had its manifest been in order.
    """

    healthy: ManagedInstall
    settled: ProvisionReport


def _repair_manifest(repair: _ManifestRepair) -> ProvisionReport:
    """Write the manifest of a healthy install again, and report what was done.

    Called only while holding the provisioning lock. How the executable
    arrived is recorded as unrecorded, because nobody witnessed it.
    """
    healthy = repair.healthy
    version_dir = healthy.binary.parent
    try:
        _write_manifest(
            version_dir,
            asset=healthy.asset,
            asset_sha256=repair.settled.sha256,
            binary_sha256=healthy.sha256,
            source=MANIFEST_SOURCE_UNRECORDED,
        )
    except OSError as exc:
        logger.error("qdrant manifest could not be rewritten: %s", exc)
        return replace(
            repair.settled,
            action=ProvisionAction.FAILED,
            url="",
            message=(
                f"The Qdrant server at {healthy.binary} is the pinned release "
                "and needs no download, but its manifest could not be written "
                f"({exc}). "
                + _managed_directory_remedy(version_dir, f"`{_INSTALL_COMMAND}`")
            ),
        )
    return replace(
        repair.settled,
        action=ProvisionAction.UPDATED,
        url="",
        message=(
            "The installed Qdrant server already is the pinned release, so "
            "nothing was downloaded. Its manifest was missing or did not "
            "describe it, and has been written again."
        ),
    )


class _WrongArchiveError(RuntimeError):
    """A local file is not the pinned release archive for this platform.

    Nothing was extracted from it, and the file was left as it was found.
    """

    def __init__(self, request: _InstallRequest, actual: str) -> None:
        upgrade = "" if request.previously == InstallState.ABSENT else "--upgrade "
        super().__init__(
            f"{request.local_archive} is not the pinned Qdrant release archive "
            f"for this platform. Expected {request.asset} for version "
            f"{QDRANT_SERVER_VERSION}, SHA256 {request.archive_sha256}; this "
            f"file hashes to {actual}. Nothing was extracted from it. Fetch "
            f"that asset from {request.url} on a host that can reach it, and "
            f"run `{_INSTALL_COMMAND} {upgrade}--archive <file>` with the copy."
        )


def _offline_route(request: _InstallRequest) -> str:
    """Say how to install without reaching a release source at all."""
    upgrade = "" if request.previously == InstallState.ABSENT else "--upgrade "
    return (
        f" On a host with no route to a release source, copy {request.asset} "
        f"to it from one that has, and run `{_INSTALL_COMMAND} "
        f"{upgrade}--archive <file>`."
    )


#: What an operator does about each way a download fails. ``{base}`` and
#: ``{hosts}`` are the names of the two source settings, ``{asset}`` the
#: release asset, ``{version}`` the pinned version and ``{rerun}`` the whole
#: command that repeats the install.
_DOWNLOAD_REMEDIES: dict[DownloadFailure, str] = {
    DownloadFailure.BAD_SOURCE: (
        "Set {base} to the https URL of a release source, then run {rerun}."
    ),
    DownloadFailure.REDIRECT_REFUSED: (
        "A mirror that redirects to its own storage host needs that host "
        "listed in {hosts}. Then run {rerun}."
    ),
    DownloadFailure.BAD_REDIRECT: (
        "Check that {base} names a release source whose redirects end at the "
        "file, then run {rerun}."
    ),
    DownloadFailure.UNTRUSTED_CERTIFICATE: (
        "This host does not trust the certificate the source presented. For a "
        "private mirror, add its certificate authority to the system trust "
        "store or name its bundle in SSL_CERT_FILE, then run {rerun}. "
        "Verification is never skipped."
    ),
    DownloadFailure.NOT_FOUND: (
        "Check that {base} names a release source that publishes {asset} for "
        "version {version}, then run {rerun}."
    ),
    DownloadFailure.REFUSED: (
        "Check {base}, and any proxy or credentials between this host and the "
        "source it names, then run {rerun}."
    ),
    DownloadFailure.UNAVAILABLE: (
        "The source is failing or rate-limiting requests. Wait, then run "
        "{rerun}; if it keeps happening, point {base} at another mirror of "
        "the release."
    ),
    DownloadFailure.UNREACHABLE: (
        "Check this host's network connection and proxy settings, and that "
        "{base} names a source it can reach, then run {rerun}."
    ),
    DownloadFailure.TOO_SLOW: (
        "Run {rerun} on a faster connection, or point {base} at a nearer "
        "mirror of the release."
    ),
    DownloadFailure.TOO_LARGE: (
        "The pinned archive is far smaller than that, so the source is not "
        "serving the release asset. Check {base}, then run {rerun}."
    ),
}

#: The failures a host that simply cannot reach a release source runs into,
#: and so the ones whose remedy also names the route that needs no network.
_OFFLINE_ROUTE_APPLIES = frozenset(
    {
        DownloadFailure.UNREACHABLE,
        DownloadFailure.UNAVAILABLE,
        DownloadFailure.TOO_SLOW,
        DownloadFailure.UNTRUSTED_CERTIFICATE,
    }
)


def _download_failure_message(exc: DownloadError, request: _InstallRequest) -> str:
    """Describe a failed download and say what the operator can do about it."""
    rerun = _install_command(request)
    if exc.kind is DownloadFailure.WRITE_FAILED:
        return f"{exc}. {_managed_directory_remedy(request.version_dir, rerun)}"
    # Function-local: the build tools import this module in an interpreter
    # that has no service configuration to import.
    from ..config._types import EnvVar

    remedy = _DOWNLOAD_REMEDIES[exc.kind].format(
        base=EnvVar.QDRANT_RELEASE_BASE_URL.value,
        hosts=EnvVar.QDRANT_DOWNLOAD_HOSTS.value,
        asset=request.asset,
        version=QDRANT_SERVER_VERSION,
        rerun=rerun,
    )
    if exc.kind in _OFFLINE_ROUTE_APPLIES:
        remedy += _offline_route(request)
    tried = f" after {exc.attempts} attempts" if exc.attempts > 1 else ""
    return f"Downloading the Qdrant server failed{tried}: {exc}. {remedy}"


def _failure_message(exc: Exception, request: _InstallRequest) -> str:
    """Describe a failed install and say what the operator can do about it."""
    rerun = _install_command(request)
    if classify_write_error(exc) == "unrecoverable":
        return (
            f"The volume holding {request.version_dir} ran out of space while "
            f"the Qdrant server was being written ({exc}). Nothing was left "
            f"behind. Free space on that volume, then run {rerun}."
        )
    if isinstance(exc, DownloadError):
        return _download_failure_message(exc, request)
    if isinstance(exc, ChecksumMismatchError) and request.local_archive is None:
        from ..config._types import EnvVar

        return (
            f"{exc} Check that {EnvVar.QDRANT_RELEASE_BASE_URL.value} names "
            f"an official source of the release, then run {rerun}. The "
            "digests ship with vaultspec-rag and cannot be configured: a "
            "source that keeps failing them is not serving this release."
        )
    if isinstance(exc, OSError):
        # Whatever else the filesystem refused happened under the managed
        # directory: the archive is the only file read from anywhere else,
        # and a failure to open it is reported by name where it is opened.
        return (
            f"The Qdrant server could not be installed to {request.version_dir} "
            f"({exc}). {_managed_directory_remedy(request.version_dir, rerun)}"
        )
    return str(exc)


def _install(request: _InstallRequest) -> ProvisionReport:
    """Stage, verify, and atomically install the pinned binary.

    The one install path, whichever way the archive arrives. Nothing is
    written at the installed name until the staged executable has matched its
    committed digest, and the manifest is written only after the executable
    is in place. A failure before the replace therefore leaves a previous
    install untouched. A run that dies after it leaves the pinned executable
    in place with no manifest, or with its predecessor's. That install is
    healthy, because its executable is what is judged, and the next run of
    any kind writes the manifest again without downloading anything.
    """
    from ._resolve import binary_filename

    target = request.version_dir / binary_filename()
    local = request.local_archive is not None
    # A local install contacts nothing, so its report names no URL.
    url = "" if local else request.url
    staged: list[Path] = []
    try:
        request.version_dir.mkdir(parents=True, exist_ok=True)
        executable = _stage_verified_executable(request, staged)
        _replace_executable(executable, target, rerun=_install_command(request))
        request.on_progress("Recording the installed Qdrant server...")
        _write_manifest(
            request.version_dir,
            asset=request.asset,
            asset_sha256=request.archive_sha256,
            binary_sha256=request.executable_sha256,
            source=MANIFEST_SOURCE_ARCHIVE if local else MANIFEST_SOURCE_DOWNLOAD,
        )
    except _INSTALL_FAILURES as exc:
        logger.error("qdrant provisioning failed: %s", exc)
        return ProvisionReport(
            action=ProvisionAction.FAILED,
            asset=request.asset,
            url=url,
            sha256=request.archive_sha256,
            message=_failure_message(exc, request),
        )
    finally:
        # Reached by an interrupt as well as by a failure, so a run stopped
        # at the keyboard strands no working file either.
        _discard(staged)
    action = (
        ProvisionAction.UPDATED
        if request.previously != InstallState.ABSENT
        else ProvisionAction.CREATED
    )
    return ProvisionReport(
        action=action,
        asset=request.asset,
        url=url,
        sha256=request.archive_sha256,
        binary=target,
    )


@dataclass(frozen=True)
class _ProvisionRequest:
    """One provisioning call's arguments, and the platform it is judged for.

    Attributes:
        archive: A local copy of the release archive to install from instead
            of downloading it.
        platform: ``sys.platform`` value to resolve the asset for; the running
            platform when ``None``, as the resolver itself defaults.
        machine: ``platform.machine()`` value, likewise.
    """

    version_dir: Path
    upgrade: bool = False
    archive: Path | None = None
    on_progress: Callable[[str], None] = no_progress
    platform: str | None = None
    machine: str | None = None


def _unusable_archive(archive: Path, version_dir: Path) -> str | None:
    """Say why *archive* cannot be installed from, or ``None`` when it can.

    Judged before anything is planned, so a preview and a real run agree. A
    file inside the managed directory is refused because that directory is
    the install's own: a later cleanup of it removes everything it holds, and
    the operator's copy must never be something an install can delete.
    """
    if not archive.is_file():
        return (
            f"{archive} is not an existing file. Pass the path of a local "
            f"copy of the release archive to `{_INSTALL_COMMAND} --archive "
            "<file>`."
        )
    managed = version_dir.parent.resolve()
    if archive.resolve().is_relative_to(managed):
        return (
            f"{archive} is inside the managed directory {managed}, which "
            "installs and cleanups write to. Keep the archive somewhere else "
            f"and pass that path to `{_INSTALL_COMMAND} --archive <file>`."
        )
    return None


def _plan(
    request: _ProvisionRequest,
) -> ProvisionReport | _ManifestRepair | _InstallRequest:
    """Decide what a run must do, without doing any of it.

    Returns:
        The report for a run with nothing to write - a healthy install, one
        that is refused or unreadable with no upgrade asked for, an installed
        name nothing can be written over, a platform with no release asset, a
        local archive that cannot be used. Or the manifest a healthy install
        still needs. Or the install the run must perform.
    """
    # Function-local, like the resolver: the build tools import this module in
    # an interpreter that has no service configuration to import.
    from ..config._settings import get_config
    from ._resolve import (
        UnsupportedPlatformError,
        asset_for_platform,
        binary_filename,
    )

    if request.archive is not None:
        unusable = _unusable_archive(request.archive, request.version_dir)
        if unusable is not None:
            return ProvisionReport(action=ProvisionAction.FAILED, message=unusable)
    existing = classify_managed_binary(request.version_dir / binary_filename())
    source = get_config()
    if existing.state is InstallState.HEALTHY:
        settled = _healthy_report(existing, request, source.qdrant_release_base_url)
        if _recorded_source(existing) is None:
            return _ManifestRepair(existing, settled)
        return settled
    # The upgrade form replaces a file that is not the pinned release, and
    # one that cannot be read to find out. Nothing replaces something that is
    # not a file, and nothing is replaced unasked.
    replaceable = existing.state in (InstallState.REFUSED, InstallState.UNREADABLE)
    if existing.state is InstallState.OBSTRUCTED or (
        replaceable and not request.upgrade
    ):
        return ProvisionReport(
            action=ProvisionAction.FAILED,
            binary=existing.binary,
            message=existing.refusal,
        )
    try:
        asset = asset_for_platform(request.platform, request.machine)
    except UnsupportedPlatformError as exc:
        # An outcome, not a crash: every caller is owed a report, and this
        # host is never handed another architecture's build.
        return ProvisionReport(action=ProvisionAction.FAILED, message=str(exc))
    return _InstallRequest(
        url=_asset_url(source.qdrant_release_base_url, asset),
        redirect_hosts=source.qdrant_download_hosts,
        asset=asset,
        archive_sha256=QDRANT_ASSET_SHA256[asset],
        executable_sha256=QDRANT_EXECUTABLE_SHA256[asset],
        version_dir=request.version_dir,
        previously=existing.state,
        on_progress=request.on_progress,
        local_archive=request.archive,
    )


def _preview(planned: _ManifestRepair | _InstallRequest) -> ProvisionReport:
    """Say what a run would write, touching neither the network nor the disk."""
    from ._resolve import binary_filename

    if isinstance(planned, _ManifestRepair):
        return replace(
            planned.settled,
            message=(
                "Verified install already present; nothing would be "
                "downloaded. Its manifest is missing or does not describe it, "
                "and a real run would write it again."
            ),
        )
    local = planned.local_archive
    origin = f"download {planned.asset} from {planned.url}"
    if local is not None:
        origin = f"read {planned.asset} from the local archive {local}"
    return ProvisionReport(
        action=ProvisionAction.DRY_RUN,
        asset=planned.asset,
        url="" if local is not None else planned.url,
        binary=planned.version_dir / binary_filename(),
        sha256=planned.archive_sha256,
        message=(
            f"Would {origin}, verify SHA256 {planned.archive_sha256}, and "
            f"install to {planned.version_dir}."
        ),
    )


def _abandoned_staging(request: _ProvisionRequest) -> list[Path]:
    """Return the working files in the version dir, less the caller's own file.

    A file is a working file by its name alone, so an archive the caller
    passed is never counted as one, wherever it is kept and whatever it is
    called: the run that was handed an operator's file must not be the run
    that deletes it.
    """
    try:
        found = list(request.version_dir.glob(f".*{_STAGING_SUFFIX}"))
    except OSError:
        return []
    if request.archive is None:
        return found
    spared = request.archive.resolve()
    return [path for path in found if path.resolve() != spared]


def _sweep_abandoned_staging(request: _ProvisionRequest) -> None:
    """Remove working files a killed run left behind.

    Called only while holding the provisioning lock. Every run that creates a
    staging file holds that lock for as long as the file exists, so one found
    now belongs to a run that is gone.
    """
    _discard(_abandoned_staging(request))


@contextmanager
def _lock_held(descriptor: int) -> Generator[None]:
    """Keep the provisioning lock, named for a waiter, for the block."""
    from .._anchor_claim import record_claim_owner, release_anchor_claim

    try:
        # The record only lets a waiter name this process. The OS claim is
        # what excludes, so a record that cannot be written costs a waiter
        # the name and nothing else.
        with contextlib.suppress(OSError):
            record_claim_owner(descriptor)
        yield
    finally:
        release_anchor_claim(descriptor, pid_record=True)


def _sweep_if_unclaimed(request: _ProvisionRequest, lock_path: Path) -> None:
    """Remove abandoned working files on behalf of a run that installs nothing.

    A run with nothing to install has no reason to wait for the provisioning
    lock, but a killed run's working files would otherwise sit there until
    the next install, and an install may never come. So the lock is tried
    once, without waiting. Held, the files are no longer anyone's and are
    removed. Refused, a run is using them, or nothing can show that none is,
    and they are left alone.
    """
    from .._anchor_claim import claim_anchor

    if not _abandoned_staging(request):
        return
    claim = claim_anchor(lock_path, pid_record=True)
    if claim.descriptor is None:
        return
    with _lock_held(claim.descriptor):
        _sweep_abandoned_staging(request)


def _run_exclusively(
    lock_path: Path,
    work: Callable[[], ProvisionReport],
    *,
    wait_seconds: float,
    on_progress: Callable[[str], None],
) -> ProvisionReport:
    """Run *work* while this process alone holds the provisioning lock.

    Two starts that both find no binary would otherwise download and install
    at once. The lock is an OS claim on a file beside the version dirs: it is
    exclusive across processes and across threads of one process, and it is
    released when its holder dies however it dies, so a crashed run strands
    nothing. This is deliberately not the machine's service singleton, which
    a running daemon holds for its whole life.

    A contender waits, saying once whom it waits for, and gives up after
    *wait_seconds* with a failed report naming the holder. A lock that cannot
    be attempted at all is not waited on: that fault is reported at once.
    """
    from .._anchor_claim import claim_anchor

    started = time.monotonic()
    announced = False
    while True:
        claim = claim_anchor(lock_path, pid_record=True, create_parent=True)
        if claim.descriptor is not None:
            break
        if claim.fault is not None:
            return ProvisionReport(
                action=ProvisionAction.FAILED,
                message=(
                    f"Could not take the Qdrant provisioning lock at {lock_path}: "
                    f"{claim.fault}. "
                    + _managed_directory_remedy(
                        lock_path.parent, f"`{_INSTALL_COMMAND}`"
                    )
                ),
            )
        holder = (
            f"process {claim.holder_pid}" if claim.holder_pid else "another process"
        )
        remaining = wait_seconds - (time.monotonic() - started)
        if remaining <= 0:
            return ProvisionReport(
                action=ProvisionAction.FAILED,
                message=(
                    f"{holder[0].upper()}{holder[1:]} was still provisioning the "
                    f"Qdrant server after {wait_seconds:g} seconds. Wait for it "
                    f"to finish, then run `{_INSTALL_COMMAND}`."
                ),
            )
        if not announced:
            announced = True
            logger.info(
                "process %d is waiting for %s to release %s",
                os.getpid(),
                holder,
                lock_path,
            )
            on_progress(
                f"Waiting for {holder} to finish provisioning the Qdrant server..."
            )
        time.sleep(min(_LOCK_POLL_SECONDS, remaining))
    with _lock_held(claim.descriptor):
        return work()


def provision(
    *,
    upgrade: bool = False,
    dry_run: bool = False,
    archive: Path | None = None,
    on_progress: Callable[[str], None] = no_progress,
) -> ProvisionReport:
    """Provision the pinned qdrant server binary into the managed dir.

    Idempotent, and decided by the executable alone. One that hashes to a
    committed digest of the pinned release is healthy whatever its manifest
    says or lacks: the run downloads nothing, reports ``unchanged``, or
    ``updated`` when it had to write the manifest again. One that hashes to
    anything else requires ``upgrade=True`` to be replaced and reports
    ``failed`` otherwise, so a manual modification is never silently
    overwritten and never silently trusted. One that cannot be read reports
    ``failed`` as unreadable, without proposing to replace a file that may be
    perfectly good.

    The managed directory holds the pinned release and nothing else. A binary
    of the operator's own is not installed here: it is named through the
    operator binary settings and never copied.

    Every failed report says what to do, naming whole commands. The command
    that led here may not be the install verb, so no remedy says to repeat a
    command or to add a flag to one.

    Args:
        upgrade: Install the pinned release over an executable that is not
            it, or that cannot be read.
        dry_run: Report what would happen without touching the network
            or the filesystem.
        archive: A local copy of the official release archive to install from
            instead of downloading it, for a host with no route to a release
            source. It changes only where the archive comes from: the file is
            identified by its digest alone, whatever it is named, and goes
            through the same archive and executable digest checks, staging
            and replace as a download. No request is made, and the file is
            never copied, moved or removed.
        on_progress: Sink for stage and byte-progress lines during a real
            install. Reporting only: it observes the download, verify, and
            extract sequence and never alters it. Defaults to silence.

    Returns:
        A :class:`ProvisionReport` in the sync vocabulary.
    """
    from ._resolve import qdrant_bin_dir

    request = _ProvisionRequest(
        version_dir=qdrant_bin_dir(),
        upgrade=upgrade,
        archive=archive,
        on_progress=on_progress,
    )
    planned = _plan(request)
    lock_path = request.version_dir.parent / _LOCK_FILENAME
    if isinstance(planned, ProvisionReport):
        if not dry_run:
            _sweep_if_unclaimed(request, lock_path)
        return planned
    if dry_run:
        return _preview(planned)

    def act_now() -> ProvisionReport:
        _sweep_abandoned_staging(request)
        # Another run may have finished this very install while this one
        # waited, so what to do is decided again now that nothing else can
        # change it.
        current = _plan(request)
        if isinstance(current, ProvisionReport):
            return current
        if isinstance(current, _ManifestRepair):
            return _repair_manifest(current)
        return _install(current)

    return _run_exclusively(
        lock_path,
        act_now,
        wait_seconds=_LOCK_WAIT_SECONDS,
        on_progress=on_progress,
    )


def provisioned_versions() -> list[dict[str, object]]:
    """Enumerate provisioned versions in the managed bin dir (bounded).

    An entry says what its executable is only after hashing it. ``verified``
    is true when the executable matched a committed digest of the pinned
    release in this call. Only then does ``source`` say how the install
    arrived: its manifest's record when the manifest describes it, and
    ``"unrecorded"`` when no manifest does. For anything else ``source`` is
    ``"unverified"`` and ``problem`` is the whole refusal, with its remedy, so
    a listing never repeats a claim nothing vouches for. Only the pinned
    version can verify: no digest is committed for any other.

    Returns:
        One entry per version dir that contains a qdrant binary, newest
        version string first, capped at 10 entries. Reading a listing never
        raises for an executable that cannot be read.
    """
    from ._resolve import binary_filename, qdrant_bin_dir, read_manifest

    base = qdrant_bin_dir().parent
    if not base.is_dir():
        return []
    entries: list[dict[str, object]] = []
    for child in sorted(base.iterdir(), reverse=True):
        if not child.is_dir():
            continue
        binary = child / binary_filename()
        if not binary.is_file():
            continue
        current = child.name == QDRANT_SERVER_VERSION
        source = "unverified"
        verified = False
        problem = (
            f"it is not the pinned version {QDRANT_SERVER_VERSION}, and no "
            "digest is committed for any other"
        )
        if current:
            existing = classify_managed_binary(binary)
            verified = existing.state is InstallState.HEALTHY
            problem = existing.refusal
            if verified:
                source = _recorded_source(existing) or MANIFEST_SOURCE_UNRECORDED
        entries.append(
            {
                "version": child.name,
                "binary": str(binary),
                "source": source,
                "provisioned_at": (read_manifest(child) or {}).get(
                    "provisioned_at", ""
                ),
                "current": current,
                "verified": verified,
                "problem": problem,
            }
        )
        if len(entries) >= 10:
            break
    return entries


def clean_provisioned(*, keep_current: bool = False) -> list[str]:
    """Delete provisioned version dirs from the managed bin dir.

    Args:
        keep_current: Preserve the dir matching the pinned version.

    Returns:
        The version strings removed.
    """
    from ._resolve import qdrant_bin_dir

    base = qdrant_bin_dir().parent
    if not base.is_dir():
        return []
    removed: list[str] = []
    for child in sorted(base.iterdir()):
        # Never recurse through a symlink/Windows junction: is_dir() is True for
        # a reparse point and rmtree would delete the *target's* contents.
        if child.is_symlink() or not child.is_dir():
            continue
        if keep_current and child.name == QDRANT_SERVER_VERSION:
            continue
        remove_tree(child)
        removed.append(child.name)
    return removed
