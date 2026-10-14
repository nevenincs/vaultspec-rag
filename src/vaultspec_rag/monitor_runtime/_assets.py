"""What the monitor's release artifacts are called, for one release and target.

The release pipeline packs each finalized monitor into an archive of its own,
one per target, and records a digest for that archive and for the executable
inside it. An installation later fetches the archive and extracts that one
member. Both ends have to agree on the two names, so both read them here: the
pipeline when it packs and publishes, the installation when it fetches and
unpacks.

The archive carries only the monitor. It is a provisioning unit, not a
channel install unit: it is not what a package manager points at.
"""

from __future__ import annotations

from typing import Final

from ..native_binary._targets import archive_suffix, executable_filename

__all__ = [
    "MONITOR_PROGRAM",
    "monitor_archive_name",
    "monitor_executable_name",
]

#: The monitor's program name, as it is installed and as it is published.
MONITOR_PROGRAM: Final[str] = "vaultspec-rag-monitor"


def monitor_executable_name(target: str) -> str:
    """Return the monitor executable's filename on *target*.

    This is both the name the archive's one member carries and the name the
    executable is installed under, so an extraction matches on exactly what
    it will write.
    """
    return executable_filename(MONITOR_PROGRAM, target)


def monitor_archive_name(version: str, target: str) -> str:
    """Return the monitor-only archive's filename for *version* on *target*.

    Args:
        version: The release version the monitor was built for, without a
            tag prefix.
        target: The target triple the monitor was compiled for.
    """
    return f"{MONITOR_PROGRAM}-v{version}-{target}{archive_suffix(target)}"
