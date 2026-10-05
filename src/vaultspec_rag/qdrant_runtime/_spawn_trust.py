"""Everything between a resolved qdrant binary and a process running it.

Resolution says which file would run and what it is held to. This module is
the only place that file is checked, and the only place a process is created
from it, so the two cannot come apart: the process is created while the file
that was just hashed is still held, from that file and not from whatever a
command line would find.

A managed install is always hashed. There is no branch that lets one run
unhashed: a digest that is missing or empty is a mismatch like any other,
because no file hashes to it. Only the operator setting runs without a digest,
and it is re-checked for the shape resolution required of it, so a file
swapped for a link or removed after resolution is refused too.
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
from ._resolve import (
    QDRANT_BINARY_UNVERIFIED,
    QdrantBinaryError,
    has_provisioned_binary,
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

_MANAGED_SOURCES = (BinarySource.MANAGED_DOWNLOAD, BinarySource.MANAGED_OPERATOR)


def _refusal(resolved: ResolvedBinary, problem: str) -> QdrantBinaryError:
    """Build the refusal for a binary that failed its check, with its remedy."""
    if resolved.source is BinarySource.MANAGED_OPERATOR:
        remedy = (
            "Register it again with: vaultspec-rag server qdrant install "
            "--binary <path>, or replace it with the pinned release: "
            "vaultspec-rag server qdrant install --upgrade"
        )
    elif resolved.source is BinarySource.MANAGED_DOWNLOAD:
        remedy = (
            "Replace it with the pinned release: "
            "vaultspec-rag server qdrant install --upgrade"
        )
    else:
        remedy = (
            f"Correct {EnvVar.QDRANT_BINARY.value}, or unset it to use the "
            "managed qdrant server."
        )
    managed = "managed " if resolved.source in _MANAGED_SOURCES else ""
    return QdrantBinaryError(
        QDRANT_BINARY_UNVERIFIED,
        f"The {managed}qdrant binary at {resolved.path} {problem}; refusing to "
        f"execute it. {remedy}",
    )


def _expected_digest(resolved: ResolvedBinary) -> str | None:
    """The digest *resolved* must hash to, or ``None`` when none applies."""
    return resolved.sha256 if resolved.source in _MANAGED_SOURCES else None


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
    elif resolved.source not in _MANAGED_SOURCES:
        raise QdrantBinaryError(
            QDRANT_BINARY_UNVERIFIED,
            f"A qdrant binary of source {resolved.source!r} is never executed.",
        )
    with ExitStack() as stack:
        # Entered apart from the block below so that a failure to open the
        # file is told from a failure raised by whoever is using the hold.
        try:
            held = stack.enter_context(held_executable(resolved.path))
        except OSError as exc:
            raise _refusal(
                resolved, f"could not be held for verification ({exc})"
            ) from exc
        expected = _expected_digest(resolved)
        if expected is not None and held.sha256() != expected:
            held_to = (
                "the digest recorded when it was registered"
                if resolved.source is BinarySource.MANAGED_OPERATOR
                else "the pinned digest of its release asset"
            )
            raise _refusal(resolved, f"does not match {held_to}")
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
        if not held.unchanged(_expected_digest(resolved)):
            proc.kill()
            proc.wait()
            if proc.stdout is not None:
                proc.stdout.close()
            raise _refusal(resolved, "changed while it was being started")
    return proc


def warn_when_operator_supplied(resolved: ResolvedBinary) -> None:
    """Log that an operator-supplied binary runs outside the committed pin.

    The setting is called out harder when it shadows a managed install - the
    case a planted setting would exploit.
    """
    if resolved.source is BinarySource.OPERATOR_SETTING:
        remedy = (
            f"It is SHADOWING a managed install; unset "
            f"{EnvVar.QDRANT_BINARY.value} to run the pinned binary."
            if has_provisioned_binary(QDRANT_SERVER_VERSION)
            else "Provision a pinned binary with: vaultspec-rag server qdrant install."
        )
        logger.warning(
            "qdrant binary named by %s (%s) runs UNVERIFIED - no pinned-digest "
            "check applies to an operator-supplied binary. %s",
            EnvVar.QDRANT_BINARY.value,
            resolved.path,
            remedy,
        )
    elif resolved.source is BinarySource.MANAGED_OPERATOR:
        logger.warning(
            "qdrant binary at %s was registered by an operator; it is held to "
            "the digest recorded at registration, not to the committed pin. "
            "Install the pinned release with: vaultspec-rag server qdrant "
            "install --upgrade",
            resolved.path,
        )
