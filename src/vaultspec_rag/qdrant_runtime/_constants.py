"""Pinned Qdrant server version, asset digests, and report types.

This module is the single source of truth for which Qdrant server
binary vaultspec-rag provisions and trusts. The version is pinned to
the same minor line as the locked ``qdrant-client`` dependency (a
regression test parses ``uv.lock`` and asserts the minors match), and
every release asset carries two committed SHA256 digests: one for the
archive, verified before extraction, and one for the executable inside
it, verified before an install is replaced and before every execution.
An upgrade replaces the version and both tables here, then runs
``vaultspec-rag server qdrant install --upgrade``.

Every digest below reproduces by streaming the asset from the shipped
default release source and hashing it; the live release JSON is never
consulted at provisioning time. Where the bytes come from is a setting;
which bytes may run is decided here and cannot be configured.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path


#: Pinned Qdrant server release. Must stay on the same minor line as
#: the locked qdrant-client (1.20.x as of this pin).
#:
#: The lock tracks the newest client, so this pin is what follows it rather
#: than what holds it back, and a guard fails the suite whenever the two drift
#: apart. Moving the pin means re-deriving every digest in both tables below:
#: stream each asset from the shipped default release source - never from a
#: mirror an operator configured - and hash the archive and the executable
#: inside it, and re-derive the OUTGOING version's digests the same way first.
#: Reproducing the digests already committed here is what shows the method and
#: the transport can be trusted to mint the next set - without that step, a
#: digest taken alongside the artifact attests to nothing but itself.
QDRANT_SERVER_VERSION: Final[str] = "1.20.0"

#: The pinned Qdrant server cannot complete uploaded-snapshot recovery on
#: Windows. Archives remain portable: restore them with a supported
#: non-Windows Qdrant server.
WINDOWS_SERVER_ARCHIVE_RESTORE_UNSUPPORTED_REASON: Final[str] = (
    "windows_server_archive_restore_unsupported: "
    "restore the archive with a supported non-Windows Qdrant server"
)

#: The release asset filenames, named once.
#:
#: The platform resolver used to write these out again to pick one, so the
#: names existed twice: here as the keys the digest is looked up by, and there
#: as literals in an if/elif chain. The resolver already refused an asset with
#: no committed digest, which caught a typo in one direction - but only after
#: the mismatch, and only for the platform the mismatch was on, so it would
#: surface as a provisioning failure on one architecture rather than as a bad
#: edit. Naming them once removes the direction the check could not cover.
ASSET_MACOS_ARM: Final = "qdrant-aarch64-apple-darwin.tar.gz"
ASSET_MACOS_X86: Final = "qdrant-x86_64-apple-darwin.tar.gz"
ASSET_LINUX_ARM_MUSL: Final = "qdrant-aarch64-unknown-linux-musl.tar.gz"
ASSET_LINUX_X86_GNU: Final = "qdrant-x86_64-unknown-linux-gnu.tar.gz"
ASSET_LINUX_X86_MUSL: Final = "qdrant-x86_64-unknown-linux-musl.tar.gz"
ASSET_WINDOWS_X86: Final = "qdrant-x86_64-pc-windows-msvc.zip"

#: Committed SHA256 digests for every per-platform release asset of
#: :data:`QDRANT_SERVER_VERSION`. Verified against the downloaded
#: archive BEFORE extraction; a mismatch deletes the partial download
#: and fails the provisioning run.
#:
#: ``ASSET_LINUX_X86_GNU`` is pinned but no platform selects it: the resolver
#: sends x86-64 Linux to the static musl build, because the gnu build links
#: against a glibc floor that moves with upstream's build runner and a verified
#: install could then fail at spawn on an older host. The gnu pins are kept in
#: both tables so an install made while gnu was selected keeps verifying - its
#: manifest names the asset, and that name selects the digest to compare. A
#: guard asserts the selectable set and the pinned set differ only by this one
#: entry.
QDRANT_ASSET_SHA256: Final[dict[str, str]] = {
    ASSET_MACOS_ARM: (
        "531904e822050790bb8c1da6705f801ee48b91eb4c229d0d605ff06f6331b20a"
    ),
    ASSET_LINUX_ARM_MUSL: (
        "bd8a458b8ef8006ce2c603c5bd6d1d973e39d787f794008dd959112e747c3bb7"
    ),
    ASSET_MACOS_X86: (
        "94a2e6f6b8ef3a3b5756a11172fd66554ac753e0a71c1d8d8b5349356c084f4d"
    ),
    ASSET_WINDOWS_X86: (
        "6d13553584fd0411f00637519e293331ff0aa1fb79bd9e30db45839bb75de2be"
    ),
    ASSET_LINUX_X86_GNU: (
        "2361f3df0dedfef31f5444f9f15bd15d6b4a6cba6ad952daecc5fbe3867c5ee6"
    ),
    ASSET_LINUX_X86_MUSL: (
        "b03a64616a1f41ddab78b480a318466541765f19835318113b1821cbea8df52c"
    ),
}

#: Committed SHA256 digests of the server executable inside every asset of
#: :data:`QDRANT_ASSET_SHA256` - the single ``qdrant`` / ``qdrant.exe`` member
#: - keyed by the same asset name.
#:
#: This table, not the archive table, is what authorises execution. An archive
#: digest stops being evidence once the archive is unpacked: what runs is a
#: file in a writable directory, and a digest recorded beside that file attests
#: to nothing but itself. The staged executable is compared against this table
#: before it replaces an install, and the installed executable is compared
#: again immediately before every spawn.
#:
#: How a value is derived is part of the pin. For each asset: stream it from
#: the shipped default release source, confirm the archive hashes to its entry
#: in the table above, then hash the one executable member extracted from that
#: same archive.
#: ``tools/qdrant_pin_digests.py`` does exactly this and prints both tables, so
#: a version bump replaces both from one run. Never take a value from an
#: installed copy, a provisioning manifest, or release metadata, and never run
#: the binary to obtain it.
#:
#: The two tables have identical keys, and a guard asserts it: an asset with an
#: archive pin and no executable pin would install and then never be allowed to
#: start, and the reverse is a digest for something that cannot be fetched.
QDRANT_EXECUTABLE_SHA256: Final[dict[str, str]] = {
    ASSET_MACOS_ARM: (
        "830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3"
    ),
    ASSET_LINUX_ARM_MUSL: (
        "6aa0041aa11b9c6326e159c999ebb6b54798afbeca41cca636e32c78c347a917"
    ),
    ASSET_MACOS_X86: (
        "3c94cd2ad5a8830f58bb3ec654bc030f17c8527dd2c9116bcd1bc346e9b0069b"
    ),
    ASSET_WINDOWS_X86: (
        "3e86f79bd516097586afb5ceacf6b843bc9e32b8e4b311d94b63a3cc11432a40"
    ),
    ASSET_LINUX_X86_GNU: (
        "5081acd073ef29701415dc2d1655d98750be8c08008541febc20cf2935800f2f"
    ),
    ASSET_LINUX_X86_MUSL: (
        "d60f8c31f7c943849403997562122cce4e3883b7f06936a01187dfd2d2eb81fe"
    ),
}

#: Name of the provisioning manifest written next to the binary.
MANIFEST_FILENAME: Final[str] = "manifest.json"

#: The manifest's ``source`` values: how the pinned release reached the managed
#: directory. Fetched; unpacked from a local copy of the same official archive;
#: or not recorded, for an executable found to be the pinned release whose
#: manifest was missing or wrong and had to be written afresh.
#:
#: The manifest is a record and nothing more. No verdict reads it: an install
#: is the pinned release when its executable hashes to a committed digest, and
#: is refused when it does not, whatever a manifest beside it says.
MANIFEST_SOURCE_DOWNLOAD: Final = "download"
MANIFEST_SOURCE_ARCHIVE: Final = "archive"
MANIFEST_SOURCE_UNRECORDED: Final = "unrecorded"


class BinarySource(StrEnum):
    """Where a qdrant binary came from, which decides what it is held to.

    The values are what status surfaces and envelopes print. A source says
    what was checked before the binary ran, so two origins held to different
    evidence never share a value. Every source that can run is held to a
    digest; they differ in who states it.
    """

    #: Named by the operator binary settings: a path and the SHA256 the
    #: operator declares for it, both from the process environment. Held to
    #: that declared digest. The committed pin does not apply.
    OPERATOR_SETTING = "env"
    #: The managed install: the pinned release, however it reached the managed
    #: directory. Held to the committed executable digest its content was
    #: found to match when it was resolved.
    MANAGED_DOWNLOAD = "provisioned"
    #: A running server this process did not spawn. It names no binary and is
    #: never executable; it exists so an attached supervisor reports a source
    #: of its own instead of borrowing one.
    ATTACHED = "attached"

    @property
    def operator_supplied(self) -> bool:
        """Whether an operator, not the committed pin, vouches for the binary."""
        return self is BinarySource.OPERATOR_SETTING


@dataclass
class ResolvedBinary:
    """An executable qdrant binary plus where it came from.

    Attributes:
        path: Absolute path to the binary.
        source: Resolution origin, which selects the check the binary must
            pass before it runs.
        version: The server version the binary is known to be: the pinned
            version for the managed install, and for an operator binary only
            when the digest declared for it is a pinned release executable's,
            because a file that hashes to that digest is that release. Empty
            when unknown, which is every other operator binary.
        sha256: The digest the executable must hash to before it may run: the
            committed constant its content matched for the managed install,
            the operator's declaration for an operator binary. Never read from
            a manifest. No file hashes to an empty one.
    """

    path: Path
    source: BinarySource
    version: str = ""
    sha256: str = ""


@dataclass
class QdrantRuntimeState:
    """Service-domain snapshot of the qdrant runtime for operability
    surfaces (health payload, service-state reads, CLI status).

    Attributes:
        mode: ``"local"`` (no server), ``"server"`` (supervised
            child), or ``"remote"`` (operator-supplied URL).
        url: The server URL stores connect to, if any.
        pid: Supervised child PID, if a child is running.
        alive: Liveness of the supervised child; ``None`` when no
            child is supervised.
        port: HTTP port of the supervised child, if any.
        version: The pinned server version.
        restarts: Heartbeat-initiated restart count for the child.
    """

    mode: str = "local"
    url: str = ""
    pid: int | None = None
    alive: bool | None = None
    port: int | None = None
    version: str = QDRANT_SERVER_VERSION
    restarts: int = 0
    extra: dict[str, object] = field(default_factory=dict)

    @property
    def restart_refusal_note(self) -> str:
        """A clause saying why the latest restart started nothing, or ``""``.

        Written to follow a statement that the server is not live, so every
        surface that makes that statement gives the same cause for it.
        """
        refusal = str(self.extra.get("restart_refusal") or "")
        return f"; its restart started nothing: {refusal}" if refusal else ""

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable view of this state."""
        data: dict[str, object] = {
            "mode": self.mode,
            "url": self.url or None,
            "pid": self.pid,
            "alive": self.alive,
            "port": self.port,
            "version": self.version,
            "restarts": self.restarts,
        }
        data.update(self.extra)
        return data
