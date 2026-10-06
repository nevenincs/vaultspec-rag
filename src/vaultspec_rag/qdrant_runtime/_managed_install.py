"""What the installed name of the managed Qdrant server holds, judged by its bytes.

One question is asked of that file by everything that touches it: the
resolver deciding what may run, the spawn check deciding it again, the
provisioner deciding what to write, and a status surface describing it. They
ask it here, so they cannot disagree.

The answer is the executable's bytes and nothing else. A file that hashes to
a committed digest of the pinned release's executable is that release,
whatever a manifest beside it says or fails to say. A file that does not is
not, whatever a manifest claims for it. The manifest is a record of how an
install got there; it sits in the directory it would be vouching for, so it
is never read to reach a verdict.

What else is in the directory is a second question, asked only of an
executable that passed the first. A file beside an executable is not inert: a
library the executable asks for by name is looked for in the executable's own
directory - before the system's on Windows, and elsewhere whenever the
executable names its own directory - so a file with the right name there runs
inside the server, and the executable's digest says nothing about it. An
install writes the executable, the manifest, and working files that are gone
when it ends. Anything else was put there by something else, and the server
is not run while it is there.

Two states are kept apart from a failed verdict because the remedy differs. A
file that cannot be read right now may be perfectly good: another program is
holding it, or its permissions are wrong, and replacing it is not what that
calls for. And a name taken by something that is not a file cannot be
replaced by any install until it is removed.

Importable in an interpreter with no service configuration, like the
provisioner that calls it: the settings names are imported inside the
function that needs them.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from .._atomic_write import is_temporary_sibling
from ._constants import (
    MANIFEST_FILENAME,
    QDRANT_EXECUTABLE_SHA256,
    QDRANT_SERVER_VERSION,
    STAGING_SUFFIX,
)
from ._executable_hold import held_executable

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "InstallState",
    "ManagedInstall",
    "classify_managed_binary",
    "companions_verdict",
    "unreadable_refusal",
]

#: How many unexpected names a refusal spells out before it counts the rest.
_NAMED_COMPANIONS = 5


class InstallState(StrEnum):
    """What the installed name of a version directory holds."""

    #: Nothing is at the installed name.
    ABSENT = "absent"
    #: A regular file whose content is a pinned release executable.
    HEALTHY = "healthy"
    #: A file, or a link, that is not a pinned release executable. It is
    #: never run, and never overwritten unless that was asked for.
    REFUSED = "refused"
    #: A file that could not be read, so nothing is known about its content.
    UNREADABLE = "unreadable"
    #: Something that is not a file holds the installed name.
    OBSTRUCTED = "obstructed"
    #: A pinned release executable with something beside it that no install
    #: wrote. It is not run while that is there, and no install removes it.
    ACCOMPANIED = "accompanied"


@dataclass(frozen=True)
class ManagedInstall:
    """The verdict on one version directory.

    Attributes:
        state: What the installed name holds.
        binary: The installed name, whether or not anything is there.
        asset: The release asset whose executable a healthy install is.
        sha256: The committed digest a healthy install's executable matched.
        problem: Why an install is not healthy, as a clause.
        refusal: The whole message for an install that is not healthy: what is
            wrong and the complete commands that put it right. Empty for a
            healthy or absent one.
    """

    state: InstallState
    binary: Path
    asset: str = ""
    sha256: str = ""
    problem: str = ""
    refusal: str = ""


#: The command that installs the pinned release over whatever is installed,
#: and the same from a local copy of the release archive.
_REPLACE_COMMAND = "vaultspec-rag server qdrant install --upgrade"
_REPLACE_OFFLINE_COMMAND = f"{_REPLACE_COMMAND} --archive <file>"


def _refused(binary: Path, problem: str) -> ManagedInstall:
    """Build the verdict for content that is not the pinned release."""
    # Function-local: this module is imported where no service configuration
    # exists to import.
    from ..config._types import EnvVar

    return ManagedInstall(
        InstallState.REFUSED,
        binary,
        problem=problem,
        refusal=(
            f"The Qdrant server at {binary} is not the pinned release: "
            f"{problem}. It is not run, and it is not overwritten unasked. "
            f"To install the pinned release over it, run `{_REPLACE_COMMAND}` "
            "(on a host with no route to a release source: "
            f"`{_REPLACE_OFFLINE_COMMAND}`). To run a binary of your own "
            f"instead, set {EnvVar.QDRANT_BINARY.value} to its absolute path "
            f"and {EnvVar.QDRANT_BINARY_SHA256.value} to its SHA256."
        ),
    )


def unreadable_refusal(binary: Path, cause: OSError) -> str:
    """Say that the qdrant binary at *binary* could not be read, and what to do.

    One sentence for every place a binary is opened to be hashed and the open
    or the read fails, whoever supplied the binary. Nothing is said about
    replacing it: the file may be exactly what it should be, and what stops
    the read is usually gone a moment later.
    """
    return (
        f"The Qdrant server at {binary} cannot be read ({cause}), so it "
        "cannot be checked. Another program may be holding it open, or this "
        "user may not be permitted to read it. Close whatever holds it, or "
        "correct its permissions, then try again."
    )


def _unreadable(binary: Path, cause: OSError) -> ManagedInstall:
    """Build the verdict for a file whose content could not be read."""
    return ManagedInstall(
        InstallState.UNREADABLE,
        binary,
        problem=f"it cannot be read ({cause})",
        refusal=unreadable_refusal(binary, cause),
    )


def _obstructed(binary: Path) -> ManagedInstall:
    """Build the verdict for an installed name taken by something not a file."""
    return ManagedInstall(
        InstallState.OBSTRUCTED,
        binary,
        problem="it is not a file",
        refusal=(
            f"{binary} is where the Qdrant server executable is installed, "
            "and something that is not a file is there. No install can be "
            "written over it. Remove it, then run `vaultspec-rag server "
            "qdrant install`."
        ),
    )


def _install_writes(name: str) -> bool:
    """Return whether an install puts an entry called *name* beside the executable.

    The manifest, the temp file a manifest write passes through, and an
    install's own working files. Judged by the name alone, as the filesystem
    compares names.
    """
    name = os.path.normcase(name)
    if name == MANIFEST_FILENAME or is_temporary_sibling(name, MANIFEST_FILENAME):
        return True
    return name.startswith(".") and name.endswith(STAGING_SUFFIX)


def _unexpected_companions(binary: Path) -> list[str]:
    """Return the names beside *binary* that no install puts there, sorted.

    Nothing is opened: an entry is judged by its name, whatever it is.

    Raises:
        OSError: When the directory cannot be listed.
    """
    own = os.path.normcase(binary.name)
    return sorted(
        name
        for name in os.listdir(binary.parent)
        if os.path.normcase(name) != own and not _install_writes(name)
    )


def _accompanied(binary: Path, names: list[str]) -> ManagedInstall:
    """Build the verdict for an executable with something else beside it."""
    shown = ", ".join(names[:_NAMED_COMPANIONS])
    uncounted = len(names) - _NAMED_COMPANIONS
    if uncounted > 0:
        shown = f"{shown} and {uncounted} more"
    return ManagedInstall(
        InstallState.ACCOMPANIED,
        binary,
        problem=f"its directory holds what no install put there: {shown}",
        refusal=(
            f"The directory of the Qdrant server at {binary} holds what no "
            f"install put there: {shown}. A file beside an executable can be "
            "loaded into it as a library, which the check of the executable "
            "does not cover, so the server is not started while anything "
            f"else is there. Remove everything from {binary.parent} except "
            f"{binary.name} and {MANIFEST_FILENAME}, then try again."
        ),
    )


def companions_verdict(binary: Path) -> ManagedInstall | None:
    """Return the verdict refusing *binary* for what sits beside it, or ``None``.

    Asked of an executable already found to be the pinned release: by the
    classifier, and again by a spawn on either side of creating the process,
    because a directory that was clean a moment ago need not be clean now. A
    directory that cannot be listed is refused as unreadable: nothing is
    known about it, and it may hold nothing at all.
    """
    try:
        names = _unexpected_companions(binary)
    except OSError as exc:
        return ManagedInstall(
            InstallState.UNREADABLE,
            binary,
            problem=f"its directory cannot be listed ({exc})",
            refusal=(
                f"The directory of the Qdrant server at {binary} cannot be "
                f"listed ({exc}), so what else is in it cannot be checked. "
                "Correct its permissions, then try again."
            ),
        )
    return _accompanied(binary, names) if names else None


def classify_managed_binary(binary: Path) -> ManagedInstall:
    """Judge what *binary*, the installed name of a managed install, holds.

    The executable is hashed on every call, through a hold that reads the
    file itself and never a link's target. Nothing is cached and no manifest
    is read. The file is healthy when it hashes to the committed executable
    digest of any pinned asset: an install made from an asset no platform
    selects any more stays healthy for as long as that asset stays pinned.
    A pinned executable is then refused all the same when its directory
    holds anything an install did not write.

    Args:
        binary: Where the pinned version's executable is installed.

    Returns:
        The verdict. Never raises for anything the filesystem does.
    """
    try:
        status = os.lstat(binary)
    except (FileNotFoundError, NotADirectoryError):
        return ManagedInstall(InstallState.ABSENT, binary)
    except OSError as exc:
        return _unreadable(binary, exc)
    if stat.S_ISLNK(status.st_mode):
        # Judged before the hold, which refuses a link as an unreadable file
        # would be refused. A link is not waiting to become readable.
        return _refused(binary, "it is a symbolic link, not the executable itself")
    if not stat.S_ISREG(status.st_mode):
        return _obstructed(binary)
    return _judge_content(binary)


def _judge_content(binary: Path) -> ManagedInstall:
    """Hash the regular file at *binary* and say whether it is a pinned release."""
    try:
        with held_executable(binary) as held:
            actual = held.sha256()
    except OSError as exc:
        return _unreadable(binary, exc)
    for asset, committed in QDRANT_EXECUTABLE_SHA256.items():
        if committed == actual:
            return companions_verdict(binary) or ManagedInstall(
                InstallState.HEALTHY, binary, asset=asset, sha256=committed
            )
    return _refused(
        binary,
        f"its SHA256 is {actual}, which is not a committed digest of the "
        f"Qdrant {QDRANT_SERVER_VERSION} executable",
    )
