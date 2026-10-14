"""Which platform a native artifact is built for, and what it is named there.

One vocabulary for the Rust-style target triples this product ships native
executables for, and for the two things a triple decides: whether an
executable carries an extension, and which archive format holds it. Both the
running installation and the release tooling ask here, so a digest recorded
for a target under one name is never looked up under another.

Stdlib-only and free of service configuration, like the rest of this package.
"""

from __future__ import annotations

import platform
from typing import Final

__all__ = [
    "UnsupportedTargetError",
    "archive_suffix",
    "executable_filename",
    "host_target",
    "is_windows_target",
]

#: How a machine name reports on each architecture native artifacts exist for.
_ARCHITECTURES: Final[dict[str, str]] = {
    "amd64": "x86_64",
    "x86_64": "x86_64",
    "arm64": "aarch64",
    "aarch64": "aarch64",
}

#: The triple suffix each operating system's artifacts carry.
_SYSTEMS: Final[dict[str, str]] = {
    "Windows": "pc-windows-msvc",
    "Linux": "unknown-linux-gnu",
    "Darwin": "apple-darwin",
}


class UnsupportedTargetError(RuntimeError):
    """This platform and architecture pair has no native target triple.

    Its own type so a caller can report an unsupported host as an outcome
    instead of a crash, and is never handed another architecture's artifact.
    """


def host_target() -> str:
    """Return the target triple of the platform this is running on.

    Derived from the interpreter's own view of the machine, so it costs
    nothing and needs no compiler.

    Raises:
        UnsupportedTargetError: When no triple covers this platform and
            architecture pair.
    """
    machine = platform.machine().lower()
    system = platform.system()
    architecture = _ARCHITECTURES.get(machine)
    suffix = _SYSTEMS.get(system)
    if architecture is None or suffix is None:
        raise UnsupportedTargetError(
            f"No native target triple covers system={system!r} machine={machine!r}."
        )
    return f"{architecture}-{suffix}"


def is_windows_target(target: str) -> bool:
    """Return whether *target* is a Windows MSVC target triple."""
    return target.endswith("windows-msvc")


def executable_filename(name: str, target: str) -> str:
    """Return the filename an executable called *name* has on *target*."""
    return f"{name}{'.exe' if is_windows_target(target) else ''}"


def archive_suffix(target: str) -> str:
    """Return the archive extension native artifacts for *target* ship in."""
    return ".zip" if is_windows_target(target) else ".tar.gz"
