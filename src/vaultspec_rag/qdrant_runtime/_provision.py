"""Download-on-first-use provisioning of the pinned Qdrant server binary.

The flow: resolve the release asset for the running platform and download it
over HTTPS from the configured release base, with every redirect held to HTTPS
and to the configured download hosts. The archive lands in a uniquely named
staging file and is hashed against its committed digest BEFORE anything is
extracted. The single executable member is extracted to a second staging
file, hashed against the committed executable digest for the asset, and only
then moved onto the installed name in one atomic replace; the manifest is
written last. A failure or an interrupt at any stage removes this run's
staging files and leaves a previous install exactly as it was. A repeat run
against a verified install reports ``unchanged`` with zero network I/O; a
digest mismatch is a hard failure.
"""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import logging
import os
import shutil
import stat
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, TYPE_CHECKING, cast

from .._atomic_write import (
    JsonWriteOptions,
    replace_atomically,
    write_json_atomically,
)
from .._rmtree import remove_tree
from .._sync_vocabulary import ProvisionAction
from .._units import human_bytes
from ._constants import (
    MANIFEST_FILENAME,
    MANIFEST_SOURCE_DOWNLOAD,
    MANIFEST_SOURCE_OPERATOR,
    QDRANT_ASSET_SHA256,
    QDRANT_EXECUTABLE_SHA256,
    QDRANT_SERVER_VERSION,
    ProvisionReport,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterable
    from http.client import HTTPMessage, HTTPResponse

logger = logging.getLogger(__name__)

__all__ = [
    "ChecksumMismatchError",
    "clean_provisioned",
    "download_https",
    "extract_verified_archive",
    "file_sha256",
    "provision",
    "provisioned_versions",
]

_DOWNLOAD_CHUNK_BYTES = 1 << 20
_DOWNLOAD_TIMEOUT_SECONDS = 120.0
# The release archives are ~30 MB; cap the stream well above that so a
# host-pinned-but-defective response cannot fill the disk before the
# SHA256 check would reject it (defense in depth behind the host pin).
_MAX_DOWNLOAD_BYTES = 256 << 20
# Report every few chunks rather than every chunk: the reporter prints a plain
# line per distinct activity off a terminal, so a per-megabyte tick would fill
# a piped install log with a hundred near-identical lines.
_DOWNLOAD_REPORT_BYTES = 4 << 20
# Marks a file as one run's working copy. Nothing reads a file carrying it as
# an install, so a run killed before it could clean up strands no executable.
_STAGING_SUFFIX = ".staging"

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
    http.client.HTTPException,
)


def _no_progress(_line: str) -> None:
    """Drop a progress line, for callers that asked for no reporting.

    A no-op sink rather than a ``None`` check at each call site. Provisioning
    always runs in a foreground command and never in the daemon, which only
    resolves and verifies the binary; the commands that have a console pass a
    sink of their own, and a caller with nothing to show passes none.
    """


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


@dataclass(frozen=True)
class _DownloadInstallRequest:
    url: str
    redirect_hosts: frozenset[str]
    asset: str
    archive_sha256: str
    executable_sha256: str
    version_dir: Path
    previously: str
    on_progress: Callable[[str], None] = _no_progress


def _stream_sha256(handle: IO[bytes]) -> str:
    """Return the hex SHA256 of everything in *handle*, read from its start."""
    handle.seek(0)
    digest = hashlib.sha256()
    while chunk := handle.read(_DOWNLOAD_CHUNK_BYTES):
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


class _RedirectRefusedError(urllib.error.URLError):
    """A redirect left HTTPS or the hosts the caller allowed."""


class _HostPinnedRedirect(urllib.request.HTTPRedirectHandler):
    """Allow redirects only over HTTPS and only onto the hosts it was given.

    The request that starts a download goes to a source its caller chose. A
    redirect is chosen by whoever answered that request, so each hop is
    checked here before it is followed.
    """

    def __init__(self, allowed_hosts: frozenset[str]) -> None:
        self._allowed_hosts = allowed_hosts

    def redirect_request(  # noqa: PLR0913 - stdlib redirect callback contract
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        """Reject redirect targets outside the pinned HTTPS host set."""
        parsed = urllib.parse.urlparse(newurl)
        # A redirect must stay HTTPS: a downgrade to http on an allowed
        # host would still strip TLS, so reject it as firmly as a
        # cross-host redirect.
        if parsed.scheme != "https":
            raise _RedirectRefusedError(
                f"Redirect to non-HTTPS URL {newurl!r} rejected"
            )
        host = (parsed.hostname or "").lower()
        if host not in self._allowed_hosts:
            raise _RedirectRefusedError(
                f"Redirect to disallowed host {host!r} rejected "
                f"(allowed: {sorted(self._allowed_hosts)})"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _declared_length(headers: object) -> int:
    """Read a response's ``Content-Length``, or 0 when it declares none."""
    getter = getattr(headers, "get", None)
    if getter is None:
        return 0
    try:
        return max(0, int(getter("Content-Length") or 0))
    except (TypeError, ValueError):
        return 0


def _download_line(written: int, declared: int) -> str:
    """Render one line of download progress, with a total when one was declared."""
    if declared:
        return (
            f"Downloading the Qdrant server: "
            f"{human_bytes(written)} of {human_bytes(declared)}"
        )
    return f"Downloading the Qdrant server: {human_bytes(written)}"


def _stream_capped(
    source: IO[bytes],
    out: IO[bytes],
    *,
    declared: int,
    on_progress: Callable[[str], None],
) -> int:
    """Copy *source* into *out* under the size cap, reporting as it goes.

    Split from the request handling so the cap and the reporting cadence can
    be exercised over an ordinary binary stream rather than only over a live
    HTTPS response.

    Args:
        source: The readable stream to drain.
        out: The staging file to write into.
        declared: The size the response claimed, or 0 when it claimed none.
        on_progress: Sink for byte-progress lines.

    Returns:
        The number of bytes written.

    Raises:
        urllib.error.URLError: When the stream exceeds the download cap.
    """
    written = 0
    reported = 0
    while chunk := source.read(_DOWNLOAD_CHUNK_BYTES):
        written += len(chunk)
        if written > _MAX_DOWNLOAD_BYTES:
            raise urllib.error.URLError(
                f"Download exceeded the {_MAX_DOWNLOAD_BYTES} byte cap; "
                "refusing to continue"
            )
        out.write(chunk)
        if written - reported >= _DOWNLOAD_REPORT_BYTES:
            reported = written
            on_progress(_download_line(written, declared))
    # The final tick lands on the true size, so the last thing an operator
    # reads is the transfer completing rather than stalling near the end.
    if written != reported:
        on_progress(_download_line(written, declared))
    return written


def download_https(
    url: str,
    out: IO[bytes],
    *,
    redirect_hosts: frozenset[str],
    on_progress: Callable[[str], None] = _no_progress,
) -> None:
    """Stream *url* into the open file *out* over HTTPS with pinned redirects.

    The host *url* names is contacted whatever *redirect_hosts* says: it is
    the source the caller chose. *redirect_hosts* bounds where that source may
    redirect to, and every hop must stay HTTPS.

    The caller opens *out* and owns what happens to it afterwards, because
    that differs: the managed install streams into a staging file it created
    exclusively and discards on any failure, while a build tool streams into
    a file in a directory of its own.

    Args:
        url: The pinned release asset to fetch.
        out: The open binary file to stream into.
        redirect_hosts: Lower-cased host names a redirect may land on. It is
            a required argument so each caller states the hosts it trusts
            rather than inheriting another caller's.
        on_progress: Sink for byte-progress lines, emitted every few
            megabytes and once more on the final byte.

    Raises:
        urllib.error.URLError: On connection failure, a non-HTTPS source,
            or a redirect that leaves HTTPS or *redirect_hosts*.
    """
    if urllib.parse.urlparse(url).scheme != "https":
        raise urllib.error.URLError(f"Refusing non-HTTPS download URL {url!r}")
    opener = urllib.request.build_opener(_HostPinnedRedirect(redirect_hosts))
    # ``OpenerDirector.open`` is typed ``Any`` in typeshed (it dispatches
    # across registered handlers); an HTTPS download always resolves to an
    # ``HTTPResponse`` at runtime.
    with cast(
        "HTTPResponse", opener.open(url, timeout=_DOWNLOAD_TIMEOUT_SECONDS)
    ) as resp:
        _stream_capped(
            resp,
            out,
            declared=_declared_length(resp.headers),
            on_progress=on_progress,
        )


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
) -> Generator[IO[bytes]]:
    """Yield a reader over the one regular executable member of *archive*.

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
                yield source
        return
    with tarfile.open(fileobj=archive, mode="r:gz") as tf:
        member = _tar_member(tf, target_name)
        source = tf.extractfile(member) if member is not None else None
        if source is None:
            raise invalid_member
        with source:
            yield source


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
    on_progress: Callable[[str], None] = _no_progress,
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
                _binary_member(handle, archive.name, binary_name) as source,
                _open_destination(binary) as out,
            ):
                shutil.copyfileobj(source, out, _DOWNLOAD_CHUNK_BYTES)
    if not verified:
        # Removed only once the handle above is closed: an open file cannot
        # be unlinked on Windows.
        archive.unlink(missing_ok=True)
        raise ChecksumMismatchError(archive.name, expected_sha256, actual)
    _mark_executable(binary)
    on_progress("Verifying the extracted Qdrant server...")
    return binary, file_sha256(binary)


def _replace_executable(staged: Path, target: Path) -> None:
    """Move a verified staging file onto the installed name in one step.

    Raises:
        RuntimeError: On Windows, when a process is running from *target*.
        OSError: When the replace fails for any other reason.
    """
    _mark_executable(staged)
    try:
        replace_atomically(staged, target)
    except PermissionError as exc:
        if sys.platform != "win32" or not target.exists():
            raise
        # Windows refuses to replace a file a process is executing. That is
        # the operator's own server in every ordinary case, so say what to do
        # about it instead of surfacing an access-denied error.
        raise RuntimeError(
            f"{target} is in use and cannot be replaced; a running Qdrant "
            "server holds it open. Stop the service with "
            "`vaultspec-rag server stop`, then run the install again."
        ) from exc


def _stage_verified_executable(
    request: _DownloadInstallRequest, staged: list[Path]
) -> Path:
    """Download and verify the archive, then stage its verified executable.

    Each staging file is recorded in *staged* as it is created, so the caller
    can remove them whatever happens next. The archive handle stays open from
    the download through the hash and the extraction, so all three see the
    same file. The executable digest is the check that decides what may be
    installed: it is taken from the staged file itself, after the last byte
    was written to it.

    Raises:
        ChecksumMismatchError: When the archive or the staged executable does
            not hash to its committed digest.
    """
    from ._resolve import binary_filename

    name = binary_filename()
    on_progress = request.on_progress
    archive_path, archive = _open_staging(request.version_dir, request.asset)
    staged.append(archive_path)
    with archive:
        logger.info("Downloading %s", request.url)
        on_progress(f"Downloading the Qdrant server ({request.asset})...")
        download_https(
            request.url,
            archive,
            redirect_hosts=request.redirect_hosts,
            on_progress=on_progress,
        )
        on_progress("Verifying the Qdrant download checksum...")
        actual = _stream_sha256(archive)
        if actual.lower() != request.archive_sha256.lower():
            raise ChecksumMismatchError(request.asset, request.archive_sha256, actual)
        on_progress("Extracting the Qdrant server...")
        with _binary_member(archive, request.asset, name) as source:
            executable_path, executable = _open_staging(request.version_dir, name)
            staged.append(executable_path)
            with executable:
                shutil.copyfileobj(source, executable, _DOWNLOAD_CHUNK_BYTES)
                on_progress("Verifying the extracted Qdrant server...")
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


def _existing_install_state(version_dir: Path, expected_sha256: str) -> str:
    """Classify the current contents of *version_dir*.

    Returns:
        ``"verified"`` when the binary and a pin-consistent manifest
        are present, ``"stale"`` when a binary exists but the manifest
        is absent or disagrees with the pin, ``"absent"`` otherwise.
    """
    from ._resolve import binary_filename, read_manifest

    binary = version_dir / binary_filename()
    if not binary.is_file():
        return "absent"
    manifest = read_manifest(version_dir)
    if (
        manifest is not None
        and str(manifest.get("version")) == QDRANT_SERVER_VERSION
        and str(manifest.get("asset_sha256", "")).lower() == expected_sha256.lower()
    ):
        return "verified"
    return "stale"


def _open_without_following(path: Path) -> IO[bytes]:
    """Open *path* for reading, refusing a symlink where the platform can."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    return os.fdopen(os.open(path, flags), "rb")


def _register_operator_binary(
    binary: Path, version_dir: Path, previously: str
) -> ProvisionReport:
    """Copy an operator-supplied binary into the managed dir and record it.

    Staged and moved into place exactly as a download is, so a copy that
    fails partway, or a target a running server still holds, leaves the
    previous install as it was.
    """
    from ._resolve import binary_filename

    target = version_dir / binary_filename()
    staged: list[Path] = []
    try:
        version_dir.mkdir(parents=True, exist_ok=True)
        staging_path, staging = _open_staging(version_dir, target.name)
        staged.append(staging_path)
        # The source is opened without following a link: the caller checked
        # that it is a regular file, and a link swapped in after that check
        # must not be what gets registered.
        with staging, _open_without_following(binary) as source:
            shutil.copyfileobj(source, staging, _DOWNLOAD_CHUNK_BYTES)
            digest = _stream_sha256(staging)
        _replace_executable(staging_path, target)
        _write_manifest(
            version_dir,
            asset="",
            asset_sha256="",
            binary_sha256=digest,
            source=MANIFEST_SOURCE_OPERATOR,
        )
    except (OSError, RuntimeError) as exc:
        logger.error("registering operator qdrant binary %s failed: %s", binary, exc)
        return ProvisionReport(
            action=ProvisionAction.FAILED, binary=binary, message=str(exc)
        )
    finally:
        _discard(staged)
    logger.warning(
        "Registered operator-supplied qdrant binary %s; the committed "
        "checksum pin does not apply to it",
        binary,
    )
    action = (
        ProvisionAction.UPDATED if previously != "absent" else ProvisionAction.CREATED
    )
    return ProvisionReport(action=action, binary=target, sha256=digest)


def _provision_operator_binary(
    binary: Path,
    version_dir: Path,
    *,
    dry_run: bool,
    previously: str,
) -> ProvisionReport:
    """Register an operator-supplied binary into the managed dir."""
    from ._resolve import binary_filename

    target = version_dir / binary_filename()
    if dry_run:
        return ProvisionReport(
            action=ProvisionAction.DRY_RUN,
            binary=target,
            message=(
                f"Would copy operator binary {binary} to {target} and record "
                "an operator-sourced manifest (no checksum pin applies)."
            ),
        )
    if not binary.is_file():
        return ProvisionReport(
            action=ProvisionAction.FAILED,
            binary=binary,
            message=f"Operator binary {binary} does not exist.",
        )
    if binary.is_symlink():
        # Copying a symlink dereferences it, so a swap between the operator's
        # intent and the copy (TOCTOU on a shared dir) could register attacker
        # content under an operator-blessed manifest. Require a regular file.
        return ProvisionReport(
            action=ProvisionAction.FAILED,
            binary=binary,
            message=(
                f"Operator binary {binary} is a symlink; refusing to follow it. "
                "Provide a regular-file path."
            ),
        )
    return _register_operator_binary(binary, version_dir, previously)


def _failure_message(exc: Exception) -> str:
    """Describe a failed install, naming the setting that admits a mirror."""
    if isinstance(exc, _RedirectRefusedError):
        # Function-local: the build tools import this module in an interpreter
        # that has no service configuration to import.
        from ..config._types import EnvVar

        return (
            f"{exc.reason}. A mirror that redirects to its own storage host "
            f"needs that host listed in {EnvVar.QDRANT_DOWNLOAD_HOSTS.value}."
        )
    return str(exc)


def _download_and_install(request: _DownloadInstallRequest) -> ProvisionReport:
    """Stage, verify, and atomically install the pinned binary.

    Nothing is written at the installed name until the staged executable has
    matched its committed digest, and the manifest is written only after the
    executable is in place. A failure before the replace therefore leaves a
    previous install untouched. One after it leaves a verified executable
    whose manifest may still describe its predecessor; that install is
    refused at start until the install is run again, which fails closed.
    """
    from ._resolve import binary_filename

    target = request.version_dir / binary_filename()
    staged: list[Path] = []
    try:
        request.version_dir.mkdir(parents=True, exist_ok=True)
        executable = _stage_verified_executable(request, staged)
        _replace_executable(executable, target)
        _write_manifest(
            request.version_dir,
            asset=request.asset,
            asset_sha256=request.archive_sha256,
            binary_sha256=request.executable_sha256,
            source=MANIFEST_SOURCE_DOWNLOAD,
        )
    except _INSTALL_FAILURES as exc:
        logger.error("qdrant provisioning failed: %s", exc)
        return ProvisionReport(
            action=ProvisionAction.FAILED,
            asset=request.asset,
            url=request.url,
            sha256=request.archive_sha256,
            message=_failure_message(exc),
        )
    finally:
        # Reached by an interrupt as well as by a failure, so a run stopped
        # at the keyboard strands no working file either.
        _discard(staged)
    action = (
        ProvisionAction.UPDATED
        if request.previously != "absent"
        else ProvisionAction.CREATED
    )
    return ProvisionReport(
        action=action,
        asset=request.asset,
        url=request.url,
        binary=target,
        sha256=request.archive_sha256,
    )


def provision(
    *,
    upgrade: bool = False,
    dry_run: bool = False,
    binary: Path | None = None,
    on_progress: Callable[[str], None] = _no_progress,
) -> ProvisionReport:
    """Provision the pinned qdrant server binary into the managed dir.

    Idempotent: a verified existing install reports ``unchanged`` with
    zero network I/O. A stale install (binary present but manifest
    absent or disagreeing with the pin) requires ``upgrade=True`` to
    be replaced and reports ``failed`` otherwise, so a manual
    modification is never silently overwritten.

    Args:
        upgrade: Re-fetch and replace a stale or pin-divergent
            install.
        dry_run: Report what would happen without touching the network
            or the filesystem.
        binary: Operator-supplied binary to register instead of
            downloading (no checksum pin applies; recorded in the
            manifest as operator-sourced).
        on_progress: Sink for stage and byte-progress lines during a real
            download. Reporting only: it observes the download, verify, and
            extract sequence and never alters it. Defaults to silence.

    Returns:
        A :class:`ProvisionReport` in the sync vocabulary.
    """
    # Function-local, like the resolver below: the build tools import this
    # module in an interpreter that has no service configuration to import.
    from ..config._settings import get_config
    from ._resolve import asset_for_platform, binary_filename, qdrant_bin_dir

    asset = asset_for_platform()
    expected = QDRANT_ASSET_SHA256[asset]
    source = get_config()
    url = f"{source.qdrant_release_base_url}/v{QDRANT_SERVER_VERSION}/{asset}"
    version_dir = qdrant_bin_dir()
    state = _existing_install_state(version_dir, expected)

    if binary is not None:
        return _provision_operator_binary(
            binary, version_dir, dry_run=dry_run, previously=state
        )

    if state == "verified" and not upgrade:
        return ProvisionReport(
            action=ProvisionAction.UNCHANGED,
            asset=asset,
            url=url,
            binary=version_dir / binary_filename(),
            sha256=expected,
            message="Verified install already present; nothing to do.",
        )
    if state == "verified" and upgrade:
        # The versioned dir already matches the pin; an upgrade run
        # after a constants bump targets a new version dir, so this
        # path is also a no-op.
        return ProvisionReport(
            action=ProvisionAction.UNCHANGED,
            asset=asset,
            url=url,
            binary=version_dir / binary_filename(),
            sha256=expected,
            message="Install already matches the pin; nothing to upgrade.",
        )
    if state == "stale" and not upgrade:
        return ProvisionReport(
            action=ProvisionAction.FAILED,
            asset=asset,
            url=url,
            binary=version_dir / binary_filename(),
            sha256=expected,
            message=(
                f"A binary exists at {version_dir} but its manifest does not "
                "match the committed pin. Re-run with --upgrade to replace "
                "it, or remove the directory."
            ),
        )

    if dry_run:
        return ProvisionReport(
            action=ProvisionAction.DRY_RUN,
            asset=asset,
            url=url,
            binary=version_dir / binary_filename(),
            sha256=expected,
            message=(
                f"Would download {asset} from {url}, verify SHA256 "
                f"{expected}, and install to {version_dir}."
            ),
        )

    return _download_and_install(
        _DownloadInstallRequest(
            url=url,
            redirect_hosts=source.qdrant_download_hosts,
            asset=asset,
            archive_sha256=expected,
            executable_sha256=QDRANT_EXECUTABLE_SHA256[asset],
            version_dir=version_dir,
            previously=state,
            on_progress=on_progress,
        )
    )


def provisioned_versions() -> list[dict[str, object]]:
    """Enumerate provisioned versions in the managed bin dir (bounded).

    Returns:
        One entry per version dir that contains a qdrant binary, newest
        version string first, capped at 10 entries.
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
        manifest = read_manifest(child) or {}
        entries.append(
            {
                "version": child.name,
                "binary": str(binary),
                "source": manifest.get("source", "unknown"),
                "provisioned_at": manifest.get("provisioned_at", ""),
                "current": child.name == QDRANT_SERVER_VERSION,
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
