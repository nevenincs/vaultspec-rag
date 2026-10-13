"""Which monitor executable this installation runs, and what it is held to.

Resolution order, and nothing else is consulted:

1. An operator executable: ``VAULTSPEC_RAG_MONITOR_BINARY`` names the file and
   ``VAULTSPEC_RAG_MONITOR_BINARY_SHA256`` declares its digest, both from the
   process environment and both required together. It exists for an operator
   running a build of their own; it is never required, and nothing suggests
   it. Half the pair, or a path that names anything else, is an error and
   never a reason to fall through: an operator who named an executable must
   not be handed another.
2. The monitor beside this installation's own programs, and only when its
   content is the executable this release pins for this target. That is how a
   bundle install uses the monitor it shipped with. One that is anything else
   is not this release's and is passed over in silence - it is not an error,
   because the managed install serves that case.
3. The managed install for this release and target, which host ``server
   start`` provisions when it is absent.

``PATH`` is not searched. A bare program name is looked for in the working
directory before anywhere else on Windows, and commands here run from inside
project checkouts, so a lookup there decides what runs from wherever the
service happened to be started. Nothing needs it either: the managed install
covers every case it used to serve, with no action from anyone.

The managed directory holds this release's monitor and nothing else, and no
operator file is ever copied into it. An executable there that is not the
pinned one is therefore not a modification anyone made on purpose: it is
reported as absent so the provisioner replaces it, which is what keeps the
whole path automatic. One that cannot be read is a different answer, because
replacing it is not the remedy and it is usually readable a moment later.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from .._program_lookup import Where, find_program
from ..config._settings import managed_status_dir
from ..config._types import EnvVar, OperatorBinaryPairError
from ..native_binary._hold import held_executable
from ..native_binary._targets import UnsupportedTargetError, host_target
from ._errors import MonitorError
from ._pins import MonitorPin, monitor_pin

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

__all__ = [
    "MONITOR_BINARY_BUSY",
    "MONITOR_BINARY_INVALID",
    "MONITOR_BINARY_UNVERIFIED",
    "MONITOR_NOT_INSTALLED",
    "MONITOR_TARGET_UNSUPPORTED",
    "MonitorBinaryError",
    "MonitorSource",
    "ResolvedMonitor",
    "expected_monitor_sha256",
    "managed_monitor_path",
    "managed_monitor_root",
    "monitor_for_launch",
    "monitor_target",
    "operator_monitor",
    "resolve_monitor",
    "resolve_pinned_monitor",
]

#: Machine-readable code for operator settings that cannot name an
#: executable: only half the pair is set, or the path is not an absolute path
#: to a regular, non-link file.
MONITOR_BINARY_INVALID = "monitor_binary_invalid"
#: Machine-readable code for a monitor that does not hash to the digest it is
#: held to: this release's pin, or the operator's declaration.
MONITOR_BINARY_UNVERIFIED = "monitor_binary_unverified"
#: Machine-readable code for a monitor that could not be read, so nothing is
#: known about its content. Usually readable a moment later.
MONITOR_BINARY_BUSY = "monitor_binary_busy"
#: Machine-readable code for a platform no native target triple covers, so
#: there is nothing to look a digest up under.
MONITOR_TARGET_UNSUPPORTED = "monitor_target_unsupported"
#: Machine-readable code for a launch with no monitor to launch. The launcher
#: fetches nothing; provisioning runs before it, where progress and a failure
#: are visible.
MONITOR_NOT_INSTALLED = "monitor_not_installed"


class MonitorSource(StrEnum):
    """Where the monitor came from, which decides what it is held to.

    The values are what status surfaces and envelopes print. Every source is
    held to a digest; they differ in who states it.
    """

    #: Named by the operator settings, and held to the digest they declare.
    #: This release's pin does not apply.
    OPERATOR_SETTING = "env"
    #: Shipped beside this installation's own programs, and held to this
    #: release's pin, which is what admitted it.
    INSTALLATION_SIBLING = "installed"
    #: The managed install this release provisions, held to the same pin.
    MANAGED_INSTALL = "provisioned"


@dataclass(frozen=True)
class ResolvedMonitor:
    """A monitor executable, where it came from, and the digest it must match.

    Attributes:
        path: Absolute path to the executable.
        source: Where it was resolved from, which selects the check it must
            pass before it runs.
        sha256: The digest it must hash to immediately before it is launched.
            Never read from beside the file itself. No file hashes to an
            empty one.
        version: The release version the executable is known to be, empty for
            an operator executable, whose version nobody has established.
    """

    path: Path
    source: MonitorSource
    sha256: str
    version: str = ""


class MonitorBinaryError(MonitorError):
    """The monitor that would run is refused."""


def managed_monitor_root() -> Path:
    """Return the directory every managed monitor install lives under.

    Beside the managed Qdrant directory, under the managed service
    directory, so one isolation knob carries all provisioning state.
    """
    return managed_status_dir() / "bin" / "monitor"


def managed_monitor_path(version: str, target: str) -> Path:
    """Return where the managed monitor for *version* on *target* is installed.

    Keyed by release version and target, and by nothing else. Every
    environment of one release on this host shares it, including an ephemeral
    cache environment, and the interpreter that runs the daemon need not be
    the one that provisioned it.
    """
    from ._assets import monitor_executable_name

    return managed_monitor_root() / version / target / monitor_executable_name(target)


def monitor_target() -> str:
    """Return the target triple this installation's monitor is pinned under.

    Raises:
        MonitorBinaryError: When no triple covers this platform. Reported as
            a monitor refusal rather than the platform error underneath it,
            so one caller catches one type.
    """
    try:
        return host_target()
    except UnsupportedTargetError as exc:
        raise MonitorBinaryError(MONITOR_TARGET_UNSUPPORTED, str(exc)) from exc


def operator_monitor() -> ResolvedMonitor | None:
    """Resolve the operator's own monitor, or ``None`` when none is named.

    Raises:
        MonitorBinaryError: When only half the pair is set, or the path does
            not name an absolute regular file that is not a link.
    """
    from ..config._settings import get_config

    try:
        declared = get_config().monitor_operator_binary
    except OperatorBinaryPairError as exc:
        # Half a pair names either an executable nothing vouches for or a
        # digest with nothing to check. Neither is "no operator monitor".
        raise MonitorBinaryError(MONITOR_BINARY_INVALID, str(exc)) from exc
    if declared is None:
        return None
    candidate = Path(declared.path).expanduser()
    fault = operator_monitor_fault(candidate)
    if fault is not None:
        raise MonitorBinaryError(
            MONITOR_BINARY_INVALID,
            f"{EnvVar.MONITOR_BINARY.value} names {candidate}, which {fault}. "
            "It must name an absolute path to a regular file that is not a "
            f"link. Correct it, or unset it and "
            f"{EnvVar.MONITOR_BINARY_SHA256.value} to use the monitor this "
            "release provides.",
        )
    return ResolvedMonitor(
        path=candidate,
        source=MonitorSource.OPERATOR_SETTING,
        sha256=declared.sha256,
    )


def operator_monitor_fault(candidate: Path) -> str | None:
    """Say why *candidate* may not be the operator's monitor, or ``None``.

    Absolute, so the working directory can never choose the file. Not a link,
    so what is named is what runs and cannot be re-pointed after the fact.
    Asked at resolution and again at every launch.
    """
    if not candidate.is_absolute():
        return "is not an absolute path"
    if candidate.is_symlink():
        return "is a symbolic link"
    if not candidate.is_file():
        return "is not an existing regular file"
    return None


def _pinned_candidates(pin: MonitorPin) -> Iterator[tuple[Path, MonitorSource]]:
    """Yield the places this release's own monitor may sit, in order."""
    sibling = find_program(pin.executable_name, Where.INSTALLATION)
    if sibling is not None:
        yield Path(sibling).resolve(), MonitorSource.INSTALLATION_SIBLING
    yield managed_monitor_path(pin.version, pin.target), MonitorSource.MANAGED_INSTALL


def resolve_monitor() -> ResolvedMonitor | None:
    """Resolve the monitor this installation runs, or ``None`` when there is none.

    ``None`` means no monitor is installed yet, which provisioning answers.
    It never means an unverified one may run.

    Raises:
        MonitorError: When the operator settings cannot name an executable,
            when this installation carries no digests to admit one, or when
            an installed monitor cannot be read to find out what it is.
    """
    operator = operator_monitor()
    if operator is not None:
        return operator
    return resolve_pinned_monitor(monitor_pin(monitor_target()))


def resolve_pinned_monitor(pin: MonitorPin) -> ResolvedMonitor | None:
    """Resolve the monitor *pin* admits, or ``None`` when none is installed.

    The part of resolution that is about this release's own monitor: where it
    may sit, and which content is it. Split from :func:`resolve_monitor` so
    that which digests admit a monitor is a stated input rather than an
    ambient one.

    Raises:
        MonitorBinaryError: When something is installed and cannot be read.
    """
    for candidate, source in _pinned_candidates(pin):
        content = _content_of(candidate)
        if content is None:
            continue
        if content == pin.executable_sha256:
            return ResolvedMonitor(
                path=candidate,
                source=source,
                sha256=pin.executable_sha256,
                version=pin.version,
            )
        logger.debug(
            "the monitor at %s is not the one release %s pins for %s",
            candidate,
            pin.version,
            pin.target,
        )
    return None


def _content_of(candidate: Path) -> str | None:
    """Return the SHA256 of *candidate*, or ``None`` when nothing is there.

    Raises:
        MonitorBinaryError: When something is there and cannot be read.
            Nothing is known about such a file, so it is neither run nor
            treated as absent and replaced.
    """
    try:
        with held_executable(candidate) as held:
            return held.sha256()
    except FileNotFoundError:
        return None
    except OSError as exc:
        if not candidate.exists():
            return None
        raise MonitorBinaryError(
            MONITOR_BINARY_BUSY,
            f"The monitor at {candidate} cannot be read ({exc}), so it cannot "
            "be checked. Another program may be holding it open, or this user "
            "may not be permitted to read it.",
        ) from exc


def monitor_for_launch() -> ResolvedMonitor:
    """Resolve the monitor a launch will run, refusing when there is none.

    The launcher fetches nothing: provisioning runs before it, in a command
    with a console, where a download's progress and a failure are visible.

    Raises:
        MonitorError: As :func:`resolve_monitor` does, and when no monitor is
            installed at all.
    """
    resolved = resolve_monitor()
    if resolved is None:
        raise MonitorBinaryError(
            MONITOR_NOT_INSTALLED,
            "The monitor this release provides is not installed, so the "
            "service cannot start its frontend. The next start obtains and "
            "verifies it again.",
        )
    return resolved


def expected_monitor_sha256() -> str | None:
    """Return the digest a monitor must hash to here, or ``None`` when none is.

    The digest the resolver would hold the monitor to: the operator's
    declaration when the operator settings name one, otherwise this release's
    pin for this target. ``None`` says this installation can admit no monitor
    at all, which is a source checkout whose monitor was never built here,
    and an unsupported platform.

    Raises nothing: a caller asking what the digest would be is answered, or
    told there is none.
    """
    try:
        operator = operator_monitor()
    except MonitorError:
        return None
    if operator is not None:
        return operator.sha256
    try:
        return monitor_pin(monitor_target()).executable_sha256
    except MonitorError:
        return None
