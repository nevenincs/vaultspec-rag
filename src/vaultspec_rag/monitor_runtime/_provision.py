"""Obtaining this release's monitor, with nothing asked of anyone.

The flow, which is the Qdrant server's flow over different bytes: fetch the
monitor-only archive for this release and target over HTTPS from the
configured release base, with every redirect held to HTTPS and to the
configured hosts. The archive lands in a uniquely named staging file and is
hashed against the digest generated into this package BEFORE anything is
extracted. The archive's one expected member is extracted by basename to a
second staging file, hashed against the executable digest, and only then
moved onto the installed name in one atomic replace. A failure or an
interrupt at any stage removes this run's staging files and leaves whatever
was installed before exactly as it was. A run that was killed outright could
not remove its own, so an install sweeps the staging files it finds that no
live run can still be writing before it stages any of its own.

What is installed is judged by hashing it, never by reading anything beside
it. A run that finds this release's monitor already in place fetches nothing
and touches the network not at all, which is every start after the first.

An upgrade installs into the new release's own directory and then removes the
directories of releases this installation no longer runs. They are ours to
remove: nothing but a provisioning run writes there, and no executable of
anyone else's is ever copied in.

Nothing here tells anyone to obtain, configure or point at a monitor. A
failure says what went wrong - no network on the first start of a release,
say - and that the next start tries again.

Two runs that provision at once are not serialised. Each stages under a name
of its own and installs with one atomic replace of a file both verified
against the same digest, so the loser of the race costs a wasted download and
nothing else. A lock would have to be held across a download, and the only
thing it could save is bytes.
"""

from __future__ import annotations

import logging
import shutil
import tarfile
import zipfile
import zlib
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import IO, TYPE_CHECKING

from .._atomic_write import replace_atomically
from .._rmtree import remove_tree
from .._store_writes import classify_write_error
from .._sync_vocabulary import ProvisionAction
from ..native_binary._download import (
    DownloadError,
    DownloadFailure,
    DownloadLimits,
    Progress,
    download_https,
    no_progress,
)
from ..native_binary._install import (
    ChecksumMismatchError,
    archive_member,
    discard_staging,
    mark_executable,
    open_staging,
    stream_sha256,
    sweep_abandoned_staging,
    whole_body_matches,
)
from ..native_binary._report import ProvisionReport
from ._errors import MonitorError
from ._launch import verify_monitor
from ._pins import MonitorPin, monitor_pin
from ._resolve import (
    managed_monitor_path,
    managed_monitor_root,
    monitor_target,
    operator_monitor,
    resolve_pinned_monitor,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path


logger = logging.getLogger(__name__)

__all__ = [
    "MONITOR_PROVISION_FAILED",
    "provision_monitor",
    "provision_pinned_monitor",
    "retire_superseded",
]

#: Machine-readable code for a provisioning run that did not install a
#: monitor. One code, because what a caller does about any of its causes is
#: the same: report it, and let the next start try again.
MONITOR_PROVISION_FAILED = "monitor_provision_failed"

#: What progress lines call what is being installed.
_SUBJECT = "monitor"
_COPY_CHUNK_BYTES = 1 << 20

#: How long the whole transfer may take. The archive is about three times
#: the size of the Qdrant server's, so the shared default would ask three
#: times the bandwidth of a first start that has to succeed on a slow link,
#: and there is no resume. Sized for these bytes at the floor bandwidth that
#: default assumes.
_DOWNLOAD_DEADLINE_SECONDS = 2700.0
_DOWNLOAD_LIMITS = replace(
    DownloadLimits(), deadline_seconds=_DOWNLOAD_DEADLINE_SECONDS
)

# Everything that can go wrong between creating the first staging file and
# the executable landing, and is an outcome to report rather than a defect to
# raise. An interrupt is deliberately absent: it propagates once staging is
# removed.
_INSTALL_FAILURES = (
    OSError,
    RuntimeError,
    EOFError,
    tarfile.TarError,
    zipfile.BadZipFile,
    zlib.error,
)


@dataclass(frozen=True)
class _InstallRequest:
    """One staged install: where the archive comes from and what admits it.

    Attributes:
        pin: The digests and artifact names this release admits.
        url: Where the monitor-only archive is published.
        redirect_hosts: Hosts a redirect may land on.
        target_path: The installed name the verified executable replaces.
        on_progress: Sink for the stage and byte lines of a real install.
        limits: How long, how large and how persistent the download may be.
        open_staging: Creates each staging file. The one point at which the
            install opens a file it will write a transfer or an extraction
            into.
    """

    pin: MonitorPin
    url: str
    redirect_hosts: frozenset[str]
    target_path: Path
    on_progress: Callable[[str], None] = no_progress
    limits: DownloadLimits = _DOWNLOAD_LIMITS
    open_staging: Callable[[Path, str], tuple[Path, IO[bytes]]] = open_staging


def _archive_url(base_url: str, pin: MonitorPin) -> str:
    """Return where this release published the monitor archive for one target.

    The layout a generic mirror of a release preserves, so pointing the base
    at a mirror is the whole of what an operator changes.
    """
    return f"{base_url.rstrip('/')}/{pin.tag}/{pin.archive_name}"


@contextmanager
def _verified_archive(
    request: _InstallRequest, staged: list[Path]
) -> Generator[IO[bytes]]:
    """Yield the archive, open and already matched to its generated digest.

    The handle that was hashed is the one yielded, so whatever is extracted
    from it afterwards is what the digest covered.

    Raises:
        ChecksumMismatchError: When the archive does not hash to its digest.
        DownloadError: However the transfer failed.
    """
    pin = request.pin

    archive_path, archive = request.open_staging(
        request.target_path.parent, pin.archive_name
    )
    staged.append(archive_path)
    with archive:
        logger.info("Downloading %s", request.url)
        request.on_progress(f"Downloading the {_SUBJECT} ({pin.archive_name})...")
        download_https(
            request.url,
            archive,
            redirect_hosts=request.redirect_hosts,
            progress=Progress(_SUBJECT, request.on_progress),
            limits=replace(
                request.limits, whole=whole_body_matches(pin.archive_sha256)
            ),
        )
        request.on_progress(f"Verifying the {_SUBJECT} download checksum...")
        actual = stream_sha256(archive)
        if actual.lower() != pin.archive_sha256.lower():
            raise ChecksumMismatchError(pin.archive_name, pin.archive_sha256, actual)
        yield archive


def _stage_verified_executable(request: _InstallRequest, staged: list[Path]) -> Path:
    """Obtain and verify the archive, then stage its verified executable.

    Each staging file is recorded in *staged* as it is created, so the caller
    can remove them whatever happens next. The archive handle stays open from
    the hash through the extraction, so both see the same file. The
    executable digest is the check that decides what may be installed: it is
    taken from the staged file itself, after the last byte was written to it.

    Raises:
        ChecksumMismatchError: When the archive or the staged executable does
            not hash to its generated digest.
    """
    pin = request.pin
    with _verified_archive(request, staged) as archive:
        request.on_progress(f"Extracting the {_SUBJECT}...")
        with archive_member(archive, pin.archive_name, pin.executable_name) as (
            source,
            _,
        ):
            executable_path, executable = request.open_staging(
                request.target_path.parent, pin.executable_name
            )
            staged.append(executable_path)
            with executable:
                shutil.copyfileobj(source, executable, _COPY_CHUNK_BYTES)
                request.on_progress(f"Verifying the extracted {_SUBJECT}...")
                actual = stream_sha256(executable)
    if actual.lower() != pin.executable_sha256.lower():
        raise ChecksumMismatchError(
            f"the {pin.executable_name} member of {pin.archive_name}",
            pin.executable_sha256,
            actual,
        )
    return executable_path


#: What each way a download fails is reported as. No entry asks anyone to do
#: anything: the request is made again by the next start.
_DOWNLOAD_CAUSES: dict[DownloadFailure, str] = {
    DownloadFailure.BAD_SOURCE: "the configured release source cannot be fetched",
    DownloadFailure.REDIRECT_REFUSED: (
        "the source redirected to a host that is not among the configured ones"
    ),
    DownloadFailure.BAD_REDIRECT: "the source's redirects did not end at the file",
    DownloadFailure.UNTRUSTED_CERTIFICATE: (
        "this host does not trust the certificate the source presented, and "
        "verification is never skipped"
    ),
    DownloadFailure.NOT_FOUND: "the source published no such file for this release",
    DownloadFailure.REFUSED: "the source refused the request",
    DownloadFailure.UNAVAILABLE: "the source is failing or rate-limiting requests",
    DownloadFailure.UNREACHABLE: "this host could not reach the source",
    DownloadFailure.TOO_SLOW: "the transfer was too slow to finish in time",
    DownloadFailure.TOO_LARGE: (
        "the source served far more than this release's archive holds"
    ),
    DownloadFailure.WRITE_FAILED: "what arrived could not be written",
}

#: Said after every cause, because it is what happens next in every case and
#: there is nothing for anyone to do in the meantime.
_RETRIES = "The next start tries again."


def _failure_message(exc: Exception, request: _InstallRequest) -> str:
    """Describe a failed install, and never ask anyone to repair it."""
    subject = f"The {_SUBJECT} for release {request.pin.version} was not installed"
    if isinstance(exc, DownloadError):
        tried = f" after {exc.attempts} attempts" if exc.attempts > 1 else ""
        cause = _DOWNLOAD_CAUSES[exc.kind]
        return f"{subject}{tried}: {cause} ({exc}). {_RETRIES}"
    if isinstance(exc, ChecksumMismatchError):
        return (
            f"{subject}: what the source served is not what this release "
            f"published. {exc} {_RETRIES}"
        )
    if classify_write_error(exc) == "unrecoverable":
        return (
            f"{subject}: the volume holding {request.target_path.parent} ran "
            f"out of space while it was being written ({exc}). Nothing was "
            f"left behind. {_RETRIES}"
        )
    if isinstance(exc, OSError):
        return (
            f"{subject}: {request.target_path.parent} could not be written "
            f"({exc}). {_RETRIES}"
        )
    return f"{subject}: {exc} {_RETRIES}"


def _install(request: _InstallRequest) -> ProvisionReport:
    """Stage, verify, and atomically install this release's monitor.

    Nothing is written at the installed name until the staged executable has
    matched its generated digest, so a failure before the replace leaves a
    previous install untouched.
    """
    pin = request.pin
    staged: list[Path] = []
    try:
        request.target_path.parent.mkdir(parents=True, exist_ok=True)
        # Two runs here are not serialised, so there is no lock to prove a
        # working file is nobody's. Its name carries the process that made
        # it, and no transfer outlasts the deadline this one is given, so a
        # file whose creator is gone or that is older than that is finished
        # with. An install killed at the keyboard cannot remove its own.
        sweep_abandoned_staging(
            request.target_path.parent,
            stale_after_seconds=request.limits.deadline_seconds,
        )
        executable = _stage_verified_executable(request, staged)
        mark_executable(executable)
        replace_atomically(executable, request.target_path)
    except _INSTALL_FAILURES as exc:
        logger.error("monitor provisioning failed: %s", exc)
        return ProvisionReport(
            action=ProvisionAction.FAILED,
            version=pin.version,
            asset=pin.archive_name,
            url=request.url,
            sha256=pin.archive_sha256,
            message=_failure_message(exc, request),
        )
    finally:
        # Reached by an interrupt as well as by a failure, so a run stopped
        # at the keyboard strands no working file either.
        discard_staging(staged)
    return ProvisionReport(
        action=ProvisionAction.CREATED,
        version=pin.version,
        asset=pin.archive_name,
        url=request.url,
        binary=request.target_path,
        sha256=pin.archive_sha256,
    )


def retire_superseded(version: str) -> list[str]:
    """Remove every managed monitor install that is not *version*'s.

    They are this installation's to remove: nothing but a provisioning run
    writes under the managed monitor directory, and no executable of anyone
    else's is ever copied into it.

    Returns:
        The release versions whose directories were removed.
    """
    root = managed_monitor_root()
    if not root.is_dir():
        return []
    retired: list[str] = []
    try:
        children = sorted(root.iterdir())
    except OSError as exc:
        logger.debug("managed monitor directory cannot be listed: %s", exc)
        return []
    for child in children:
        # Never recurse through a link or a Windows junction: is_dir() is
        # true for a reparse point, and removing it would delete the
        # target's contents.
        if child.is_symlink() or not child.is_dir() or child.name == version:
            continue
        try:
            remove_tree(child)
        except OSError as exc:
            logger.debug("a superseded monitor install remains at %s: %s", child, exc)
            continue
        retired.append(child.name)
    return retired


def provision_monitor(
    *,
    dry_run: bool = False,
    on_progress: Callable[[str], None] = no_progress,
) -> ProvisionReport:
    """Install the monitor this installation's own digests admit.

    The entry point every command reaches, which is why it is the one place
    that asks what those digests are. Everything else is
    :func:`provision_pinned_monitor`.

    Args:
        dry_run: Report what would happen without touching the network or
            the filesystem.
        on_progress: Sink for stage and byte-progress lines.

    Returns:
        A :class:`ProvisionReport` in the sync vocabulary, including for a
        refusal of the pins or of the platform.
    """
    try:
        operator = operator_monitor()
        if operator is not None:
            # The operator decided what runs, so this release's own digests
            # are not consulted and nothing is obtained. The file is hashed
            # here, because resolution returns it without doing so.
            verify_monitor(operator)
            return ProvisionReport(
                action=ProvisionAction.UNCHANGED,
                version="",
                binary=operator.path,
                sha256=operator.sha256,
                message=(
                    f"The {_SUBJECT} at {operator.path} is the one the "
                    "operator settings name, verified against the digest "
                    "they declare for it; nothing was obtained."
                ),
            )
        pin = monitor_pin(monitor_target())
    except MonitorError as exc:
        return ProvisionReport(
            action=ProvisionAction.FAILED,
            version="",
            message=f"{exc} {_RETRIES}",
        )
    return provision_pinned_monitor(pin, dry_run=dry_run, on_progress=on_progress)


def provision_pinned_monitor(
    pin: MonitorPin,
    *,
    dry_run: bool = False,
    on_progress: Callable[[str], None] = no_progress,
) -> ProvisionReport:
    """Install this release's monitor where it is not already installed.

    Idempotent, and decided by the installed bytes alone. An executable that
    hashes to this release's pin needs nothing: the run fetches nothing and
    reports ``unchanged``. Anything else at that name is replaced, because
    the managed directory holds this release's monitor and nothing else.

    Args:
        dry_run: Report what would happen without touching the network or
            the filesystem.
        on_progress: Sink for stage and byte-progress lines during a real
            install. Reporting only: it observes the fetch, verify, extract
            sequence and never alters it.

    Returns:
        A :class:`ProvisionReport` in the sync vocabulary. Never raises for a
        condition an operator is owed a report about: a refusal of the pins,
        of the platform, or of the install itself leaves as a ``failed``
        report whose message says what happened and that the next start
        tries again.
    """
    from ..config._settings import get_config

    target_path = managed_monitor_path(pin.version, pin.target)
    try:
        installed = resolve_pinned_monitor(pin)
    except MonitorError as exc:
        return ProvisionReport(
            action=ProvisionAction.FAILED,
            version=pin.version,
            message=f"{exc} {_RETRIES}",
        )
    if installed is not None:
        retire_superseded(pin.version)
        return ProvisionReport(
            action=ProvisionAction.UNCHANGED,
            version=pin.version,
            binary=installed.path,
            sha256=pin.executable_sha256,
            message=(
                f"The {_SUBJECT} for release {pin.version} is already "
                f"installed and verified ({installed.source.value}); nothing "
                "was fetched."
            ),
        )
    if not pin.tag:
        return ProvisionReport(
            action=ProvisionAction.FAILED,
            version=pin.version,
            message=(
                f"The {_SUBJECT} this build's digests describe was built here "
                "and published nowhere, so there is nothing to fetch."
            ),
        )
    source = get_config()
    request = _InstallRequest(
        pin=pin,
        url=_archive_url(str(source.monitor_release_base_url), pin),
        redirect_hosts=frozenset(source.monitor_download_hosts),
        target_path=target_path,
        on_progress=on_progress,
    )
    if dry_run:
        return ProvisionReport(
            action=ProvisionAction.DRY_RUN,
            version=pin.version,
            asset=pin.archive_name,
            url=request.url,
            binary=target_path,
            sha256=pin.archive_sha256,
            message=(
                f"Would fetch {pin.archive_name} from {request.url}, verify "
                f"SHA256 {pin.archive_sha256}, and install to "
                f"{target_path.parent}."
            ),
        )
    report = _install(request)
    if report.action is ProvisionAction.CREATED:
        retired = retire_superseded(pin.version)
        report.message = (
            f"The {_SUBJECT} for release {pin.version} was fetched and verified."
        ) + (f" Superseded installs removed: {', '.join(retired)}." if retired else "")
    return report
