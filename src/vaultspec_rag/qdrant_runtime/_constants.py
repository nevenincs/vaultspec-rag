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
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

#: Pinned Qdrant server release. Must stay on the same minor line as
#: the locked qdrant-client (1.18.x as of this pin).
QDRANT_SERVER_VERSION: Final[str] = "1.18.2"

#: Base URL for upstream release downloads. The effective download URL
#: is ``{base}/v{version}/{asset}``.
QDRANT_RELEASE_BASE_URL: Final[str] = (
    "https://github.com/qdrant/qdrant/releases/download"
)

#: Hosts a provisioning download may touch. GitHub serves release
#: artifacts via a redirect to its object store; any redirect outside
#: this set is rejected as a potential hijack.
ALLOWED_DOWNLOAD_HOSTS: Final[frozenset[str]] = frozenset(
    {
        "github.com",
        "objects.githubusercontent.com",
    }
)

#: Committed SHA256 digests for every per-platform release asset of
#: :data:`QDRANT_SERVER_VERSION`. Verified against the downloaded
#: archive BEFORE extraction; a mismatch deletes the partial download
#: and fails the provisioning run.
QDRANT_ASSET_SHA256: Final[dict[str, str]] = {
    "qdrant-aarch64-apple-darwin.tar.gz": (
        "859f487e316ae1bda3b5d7c1e129a0a7344424d992503c188979ca6ac1b47253"
    ),
    "qdrant-aarch64-unknown-linux-musl.tar.gz": (
        "2ead5bb8206289b67c930f0eb29123228ddb43c2344551a0947cbc9046f92c6c"
    ),
    "qdrant-x86_64-apple-darwin.tar.gz": (
        "d395eb3d96c2196bbb8c611b800842928fb8b4997924b585bf42ce0ceb90fa1f"
    ),
    "qdrant-x86_64-pc-windows-msvc.zip": (
        "b2b262cba6f78cf4fa794ae78d73a8f70a221c93c76c75ac8fd6fe95d809b142"
    ),
    "qdrant-x86_64-unknown-linux-gnu.tar.gz": (
        "cd619c61d8d32dd176af88cf498714ecb765b7df9021d691862478d6ac35392c"
    ),
    "qdrant-x86_64-unknown-linux-musl.tar.gz": (
        "40a6af44f8a496560c9d2352b6b2a0ada816aa48d0781c68f602582e67b3aea0"
    ),
}

#: Name of the provisioning manifest written next to the binary.
MANIFEST_FILENAME: Final[str] = "manifest.json"


class QdrantProvisionAction(StrEnum):
    """Closed outcome vocabulary for the provisioning verb.

    Mirrors the project-wide sync vocabulary: ``created`` /
    ``updated`` / ``unchanged`` / ``skipped`` / ``failed``, plus
    ``dry_run`` for the preview path (precedent: the torch-config
    install actions).
    """

    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    SKIPPED = "skipped"
    FAILED = "failed"
    DRY_RUN = "dry_run"


@dataclass
class ProvisionReport:
    """Structured outcome of one provisioning run.

    Attributes:
        action: A :class:`QdrantProvisionAction` member naming the
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

    action: QdrantProvisionAction
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
