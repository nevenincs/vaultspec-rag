"""Everything between a resolved qdrant binary and a process running it.

Resolution says which file would run and what it is held to. This module is
the only place that file is checked, and the only place a process is created
from it, so the two cannot come apart: the process is created while the file
that was just hashed is still held, from that file and not from whatever a
command line would find.

Every binary is hashed, whatever its source. There is no branch that lets one
run unhashed: a digest that is missing or empty is a mismatch like any other,
because no file hashes to it. The managed install is held to a committed
constant and an operator binary to the digest its operator declared. The
operator binary is also re-checked for the shape resolution required of it,
so a file swapped for a link or removed after resolution is refused by name.

A file that cannot be read is not a file that failed: it is refused under its
own code, with a remedy that does not ask for it to be replaced.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from contextlib import ExitStack, contextmanager
from typing import TYPE_CHECKING

from .._win32 import WIN_CREATE_NEW_PROCESS_GROUP, WIN_CREATE_NO_WINDOW
from ..config._types import EnvVar
from ._constants import QDRANT_SERVER_VERSION, BinarySource, ResolvedBinary
from ._executable_hold import HeldExecutable, held_executable
from ._managed_install import InstallState, classify_managed_binary, unreadable_refusal
from ._resolve import (
    QDRANT_BINARY_BUSY,
    QDRANT_BINARY_UNVERIFIED,
    QdrantBinaryError,
    has_provisioned_binary,
    managed_install_refusal,
    operator_binary_fault,
    operator_setting_refusal,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "spawn_verified",
    "verify_resolved_binary",
    "warn_when_operator_supplied",
]


def _refusal(resolved: ResolvedBinary, problem: str) -> QdrantBinaryError:
    """Build the refusal for a binary that failed its check, with its remedy."""
    if resolved.source is BinarySource.MANAGED_DOWNLOAD:
        subject = "managed qdrant binary"
        remedy = (
            "Replace it with the pinned release: "
            "vaultspec-rag server qdrant install --upgrade"
        )
    else:
        subject = "qdrant binary"
        remedy = (
            f"Correct {EnvVar.QDRANT_BINARY.value} or "
            f"{EnvVar.QDRANT_BINARY_SHA256.value}, or unset both to use the "
            "managed qdrant server."
        )
    return QdrantBinaryError(
        QDRANT_BINARY_UNVERIFIED,
        f"The {subject} at {resolved.path} {problem}; refusing to execute it. {remedy}",
    )


def _unreadable(resolved: ResolvedBinary, cause: OSError) -> QdrantBinaryError:
    """Build the refusal for a binary that could not be opened or read.

    Kept apart from a failed digest: nothing is known about a file that could
    not be read, it may be exactly what it should be, and telling an operator
    to replace it would be the wrong remedy for something usually gone a
    moment later.
    """
    return QdrantBinaryError(
        QDRANT_BINARY_BUSY, unreadable_refusal(resolved.path, cause)
    )


def _managed_binary_changed(
    resolved: ResolvedBinary, cause: OSError | None
) -> QdrantBinaryError:
    """Refuse a managed binary that is no longer what resolution found.

    Resolution judged the file moments or hours ago; a heartbeat restart meets
    whatever is there now. The shared judgement is asked again so the refusal
    says what a status read of the same file would say, not a second wording
    of it.

    Args:
        resolved: The managed binary as it was resolved.
        cause: Why it could not be held, or ``None`` when it was read and its
            digest did not match.
    """
    install = classify_managed_binary(resolved.path)
    refusal = managed_install_refusal(install)
    if refusal is not None:
        return refusal
    if install.state is InstallState.ABSENT:
        return _refusal(resolved, "is no longer there")
    # It is the pinned release on this second look, so what failed a moment
    # ago was the read, or a write that has since finished.
    if cause is not None:
        return _unreadable(resolved, cause)
    return _refusal(resolved, "changed while it was being checked")


@contextmanager
def _verified(resolved: ResolvedBinary) -> Generator[HeldExecutable]:
    """Hold *resolved* open, proven to be what its source holds it to.

    The file stays held for the whole block, so a process created inside it
    is created from the file that was checked.

    Raises:
        QdrantBinaryError: When the binary may not run.
    """
    if resolved.source is BinarySource.OPERATOR_SETTING:
        fault = operator_binary_fault(resolved.path)
        if fault is not None:
            raise operator_setting_refusal(resolved.path, fault)
    elif resolved.source is not BinarySource.MANAGED_DOWNLOAD:
        raise QdrantBinaryError(
            QDRANT_BINARY_UNVERIFIED,
            f"A qdrant binary of source {resolved.source!r} is never executed.",
        )
    with ExitStack() as stack:
        # Entered apart from the block below so that a failure to open the
        # file is told from a failure raised by whoever is using the hold.
        managed = resolved.source is BinarySource.MANAGED_DOWNLOAD
        try:
            held = stack.enter_context(held_executable(resolved.path))
        except OSError as exc:
            if managed:
                raise _managed_binary_changed(resolved, exc) from exc
            raise _unreadable(resolved, exc) from exc
        if held.sha256() != resolved.sha256:
            if managed:
                raise _managed_binary_changed(resolved, None)
            raise _refusal(
                resolved,
                "does not match the SHA256 declared in "
                f"{EnvVar.QDRANT_BINARY_SHA256.value}",
            )
        yield held


def verify_resolved_binary(resolved: ResolvedBinary) -> None:
    """Check *resolved* against what its source holds it to, or refuse it.

    The same check a spawn makes, for a caller that wants the answer without
    a process: a status surface, or a start that would rather fail where an
    operator can see the reason. Passing it does not authorise a later spawn;
    every spawn checks again.

    Raises:
        QdrantBinaryError: When the binary may not run. The message names the
            command that repairs a managed install.
    """
    with _verified(resolved):
        pass


def spawn_verified(
    resolved: ResolvedBinary, *, env: dict[str, str], cwd: Path
) -> subprocess.Popen[bytes]:
    """Create the qdrant process from *resolved*, verified as it is created.

    The child's combined output is a pipe the caller drains. Its working
    directory is pinned to *cwd*: the binary writes runtime markers
    (``.qdrant-initialized``) into its working directory, which must never be
    the directory the service was started from.

    Raises:
        QdrantBinaryError: When the binary may not run, or - where the
            platform cannot hold the file still - when it changed between the
            check and the process existing. That process is killed first.
        OSError: If the process cannot be created.
    """
    with _verified(resolved) as held:
        # ``executable`` names the file itself. Left to the command line, a
        # missing extensionless name is completed with ``.exe`` on Windows
        # and a sibling file runs in its place.
        if sys.platform == "win32":
            proc = subprocess.Popen(
                [str(resolved.path)],
                executable=held.launch_path,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                cwd=str(cwd),
                text=False,
                bufsize=0,
                creationflags=(WIN_CREATE_NEW_PROCESS_GROUP | WIN_CREATE_NO_WINDOW),
            )
        else:
            proc = subprocess.Popen(
                [str(resolved.path)],
                executable=held.launch_path,
                pass_fds=held.inherited,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                cwd=str(cwd),
                text=False,
                bufsize=0,
                start_new_session=True,
            )
        if not held.unchanged(resolved.sha256):
            proc.kill()
            proc.wait()
            if proc.stdout is not None:
                proc.stdout.close()
            raise _refusal(resolved, "changed while it was being started")
    return proc


def warn_when_operator_supplied(resolved: ResolvedBinary) -> None:
    """Log that an operator-supplied binary runs outside the committed pin.

    It is verified, but against a digest the operator declared: the service
    knows the file is the one that was named, not that it is a release anyone
    reviewed. The setting is called out harder when it shadows a managed
    install - the case a planted environment would exploit.
    """
    if resolved.source is not BinarySource.OPERATOR_SETTING:
        return
    remedy = (
        f"It is SHADOWING a managed install; unset {EnvVar.QDRANT_BINARY.value} "
        f"and {EnvVar.QDRANT_BINARY_SHA256.value} to run the pinned binary."
        if has_provisioned_binary(QDRANT_SERVER_VERSION)
        else "Provision the pinned binary with: vaultspec-rag server qdrant install."
    )
    logger.warning(
        "qdrant binary named by %s (%s) is operator-supplied: it is held to the "
        "digest declared in %s, not to the committed pin. %s",
        EnvVar.QDRANT_BINARY.value,
        resolved.path,
        EnvVar.QDRANT_BINARY_SHA256.value,
        remedy,
    )
