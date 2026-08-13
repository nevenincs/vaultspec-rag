"""Pinned Qdrant server version, asset digests, and report types.

This module is the single source of truth for which Qdrant server
binary vaultspec-rag provisions and trusts. The version is pinned to
the same minor line as the locked ``qdrant-client`` dependency (a
regression test parses ``uv.lock`` and asserts the minors match), and
every release asset carries a committed SHA256 digest that is verified
before extraction and before first execution. Upgrades are a two-line
edit here plus ``vaultspec-rag server qdrant install --upgrade``.

The digests below were transcribed from the upstream GitHub release
JSON for the pinned tag by a maintainer; the live release JSON is
never consulted at provisioning time.
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
#: apart. Moving the pin means re-deriving every digest below: stream each
#: asset from the pinned host and hash it, and re-derive the OUTGOING version's
#: digests the same way first. Reproducing the digests already committed here
#: is what shows the method and the transport can be trusted to mint the next
#: set - without that step, a digest taken alongside the artifact attests to
#: nothing but itself.
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
#: ``ASSET_LINUX_X86_MUSL`` is pinned but no platform selects it: the resolver
#: sends x86-64 Linux to the gnu build. The digest is kept rather than dropped
#: because removing a reviewed pin is how an unpinned asset later becomes
#: reachable, but it is deliberately unreachable today and a guard asserts the
#: two lists differ only by this one entry.
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

#: Name of the provisioning manifest written next to the binary.
MANIFEST_FILENAME: Final[str] = "manifest.json"


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
        source: Resolution origin - ``"env"`` (operator env var),
            ``"provisioned"`` (the managed bin dir), or ``"path"``
            (found on ``PATH``).
        version: The provisioned version when ``source`` is
            ``"provisioned"``; empty otherwise (operator binaries are
            trusted as-is).
        sha256: The recorded binary digest from the provisioning
            manifest when available; empty otherwise.
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
