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

Every digest below reproduces by streaming the asset from the pinned
host and hashing it; the live release JSON is never consulted at
provisioning time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

    from .._sync_vocabulary import ProvisionAction

#: Pinned Qdrant server release. Must stay on the same minor line as
#: the locked qdrant-client (1.19.x as of this pin).
#:
#: The lock tracks the newest client, so this pin is what follows it rather
#: than what holds it back, and a guard fails the suite whenever the two drift
#: apart. Moving the pin means re-deriving every digest in both tables below:
#: stream each asset from the pinned host and hash the archive and the
#: executable inside it, and re-derive the OUTGOING version's digests the same
#: way first. Reproducing the digests already committed here is what shows the
#: method and the transport can be trusted to mint the next set - without that
#: step, a digest taken alongside the artifact attests to nothing but itself.
QDRANT_SERVER_VERSION: Final[str] = "1.19.0"

#: The pinned Qdrant server cannot complete uploaded-snapshot recovery on
#: Windows. Archives remain portable: restore them with a supported
#: non-Windows Qdrant server.
WINDOWS_SERVER_ARCHIVE_RESTORE_UNSUPPORTED_REASON: Final[str] = (
    "windows_server_archive_restore_unsupported: "
    "restore the archive with a supported non-Windows Qdrant server"
)

#: Base URL for upstream release downloads. The effective download URL
#: is ``{base}/v{version}/{asset}``.
QDRANT_RELEASE_BASE_URL: Final[str] = (
    "https://github.com/qdrant/qdrant/releases/download"
)

#: Hosts a provisioning download may touch. GitHub serves release
#: artifacts via a redirect to its object-store hosts (observed:
#: ``release-assets.githubusercontent.com``; historically
#: ``objects.githubusercontent.com``); any redirect outside this set
#: is rejected as a potential hijack.
ALLOWED_DOWNLOAD_HOSTS: Final[frozenset[str]] = frozenset(
    {
        "github.com",
        "api.github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
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
        "4e279a80cc1ebe73e859318ff86375af54c123887dd7ae46605c0eb6cb7c44e8"
    ),
    ASSET_LINUX_ARM_MUSL: (
        "8986afbbff9ac32d6e2dbe5cabec80565f613f777126096a461ba066573d3245"
    ),
    ASSET_MACOS_X86: (
        "e7afefcc125856157b33c6184c00ddee3f1d5b112474649070592d9fdd9a3f54"
    ),
    ASSET_WINDOWS_X86: (
        "980cb2e1ae771155cf211da8c0a8a9206b6482bd4effdc4db994d3adb707b087"
    ),
    ASSET_LINUX_X86_GNU: (
        "e4405091f67d02f96fb941695ef8a6974e677632507ff7b04a3fcbb332ad9c19"
    ),
    ASSET_LINUX_X86_MUSL: (
        "9ec667456443463eee390e43cd36988af6b730c6db807b4e39f57c303d0264a3"
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
#: the pinned host, confirm the archive hashes to its entry in the table above,
#: then hash the one executable member extracted from that same archive.
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
        "036b94e5a39f1ea8f2329c8e528fcea54f83eb9205221a7dc1623c9862acc74d"
    ),
    ASSET_LINUX_ARM_MUSL: (
        "d78155928882a6aa39cca6b79872e32d3902f7f0ae40999812f3481754d0ad09"
    ),
    ASSET_MACOS_X86: (
        "a4706c528df035ab9c8400cff1e5ebc8147d5a5f02adf383b19400e50a2b37bc"
    ),
    ASSET_WINDOWS_X86: (
        "369c562eae3d89333a13abfdb522fa209e3f587c1217a1059d817e80814ea9d4"
    ),
    ASSET_LINUX_X86_GNU: (
        "f3aa04dd54b303feca241878521e563a2e09ead71e14cbd6caef85e227498d50"
    ),
    ASSET_LINUX_X86_MUSL: (
        "abfe97e1d0225111dec2f048790428f151846c8a049eefc85328b6c9eccaf419"
    ),
}

#: Name of the provisioning manifest written next to the binary.
MANIFEST_FILENAME: Final[str] = "manifest.json"

#: The manifest's ``source`` values. A downloaded install is held to the
#: committed executable digest of the asset its manifest names; an install an
#: operator registered has no committed digest and is held to the one recorded
#: when it was registered.
MANIFEST_SOURCE_DOWNLOAD: Final = "download"
MANIFEST_SOURCE_OPERATOR: Final = "operator"


@dataclass
class ProvisionReport:
    """Structured outcome of one provisioning run.

    Attributes:
        action: A :class:`ProvisionAction` member naming the
            outcome. ``StrEnum`` members compare equal to their string
            values, so JSON consumers can filter on ``"created"``.
        version: The pinned server version the run targeted.
        asset: The release asset name for this platform.
        url: The upstream download URL (informational; empty for
            operator-supplied binaries).
        binary: Path the active binary lives at (or would live at for
            a dry run).
        sha256: The committed digest the run verified (or would
            verify).
        message: Human-readable detail, mandatory for ``skipped`` and
            ``failed``.
    """

    action: ProvisionAction
    version: str = QDRANT_SERVER_VERSION
    asset: str = ""
    url: str = ""
    binary: Path | None = None
    sha256: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable view of this report."""
        return {
            "action": str(self.action),
            "version": self.version,
            "asset": self.asset,
            "url": self.url,
            "binary": str(self.binary) if self.binary else None,
            "sha256": self.sha256,
            "message": self.message,
        }


@dataclass
class ResolvedBinary:
    """An executable qdrant binary plus where it came from.

    Attributes:
        path: Absolute path to the binary.
        source: Resolution origin - ``"env"`` (the operator binary
            setting) or ``"provisioned"`` (the managed bin dir).
        version: The provisioned version when ``source`` is
            ``"provisioned"``; empty otherwise (operator binaries are
            trusted as-is).
        sha256: The digest the executable must hash to before it may run.
            For a managed install this is never read from a downloaded
            install's own manifest; empty means no digest applies, and no
            file hashes to it.
    """

    path: Path
    source: str
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
