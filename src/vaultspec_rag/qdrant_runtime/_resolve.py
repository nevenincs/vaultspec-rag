"""Platform-to-asset mapping and active-binary resolution.

Resolution order for the binary the service will execute:

1. ``VAULTSPEC_RAG_QDRANT_BINARY`` - operator-supplied path (the
   air-gapped / proxy / policy escape hatch). Trusted as-is.
2. The managed bin dir (``{status_dir}/bin/qdrant/{version}/``) when a
   provisioning manifest is present and consistent with the committed
   pin.
3. ``qdrant`` on ``PATH`` - a convenience for system-managed installs;
   version is not guaranteed and a skew warning is logged downstream.
"""

from __future__ import annotations

import json
import logging
import platform as _platform
import shutil
import sys
from pathlib import Path
from typing import Any, cast

from ..config import EnvVar, get_config
from ._constants import (
    MANIFEST_FILENAME,
    QDRANT_ASSET_SHA256,
    QDRANT_SERVER_VERSION,
    ResolvedBinary,
)

logger = logging.getLogger(__name__)

__all__ = [
    "asset_for_platform",
    "binary_filename",
    "has_provisioned_binary",
    "qdrant_bin_dir",
    "read_manifest",
    "resolve_binary",
]

_ARM_MACHINES = frozenset({"arm64", "aarch64"})
_X86_MACHINES = frozenset({"amd64", "x86_64"})


def asset_for_platform(
    platform: str | None = None,
    machine: str | None = None,
) -> str:
    """Return the release asset name for a platform/arch pair.

    Args:
        platform: ``sys.platform`` value (``win32`` / ``darwin`` /
            ``linux``). Defaults to the running platform.
        machine: ``platform.machine()`` value. Defaults to the running
            machine.

    Returns:
        The asset filename, guaranteed to be a key of
        :data:`QDRANT_ASSET_SHA256`.

    Raises:
        RuntimeError: If the platform/arch pair has no upstream
            release asset.
    """
    plat = (platform or sys.platform).lower()
    mach = (machine or _platform.machine()).lower()

    asset: str | None = None
    if plat == "win32" and mach in _X86_MACHINES:
        asset = "qdrant-x86_64-pc-windows-msvc.zip"
    elif plat == "darwin":
        if mach in _ARM_MACHINES:
            asset = "qdrant-aarch64-apple-darwin.tar.gz"
        elif mach in _X86_MACHINES:
            asset = "qdrant-x86_64-apple-darwin.tar.gz"
    elif plat.startswith("linux"):
        if mach in _X86_MACHINES:
            asset = "qdrant-x86_64-unknown-linux-gnu.tar.gz"
        elif mach in _ARM_MACHINES:
            asset = "qdrant-aarch64-unknown-linux-musl.tar.gz"

    if asset is None:
        raise RuntimeError(
            f"No Qdrant server release asset exists for platform={plat!r} "
            f"machine={mach!r}. Supply a binary via "
            f"{EnvVar.QDRANT_BINARY.value} instead."
        )
    if asset not in QDRANT_ASSET_SHA256:
        raise RuntimeError(
            f"Asset {asset!r} has no committed SHA256 digest; the pin "
            "table is incomplete."
        )
    return asset


def binary_filename(platform: str | None = None) -> str:
    """Return the qdrant executable filename for *platform*."""
    plat = (platform or sys.platform).lower()
    return "qdrant.exe" if plat == "win32" else "qdrant"


def qdrant_bin_dir(version: str = QDRANT_SERVER_VERSION) -> Path:
    """Return the managed install dir for *version*.

    Lives under the service status dir so the
    ``VAULTSPEC_RAG_STATUS_DIR`` isolation knob carries provisioning
    state along with the rest of the managed service directory.
    """
    cfg = get_config()
    return Path(str(cfg.status_dir)).expanduser() / "bin" / "qdrant" / version


def read_manifest(version_dir: Path) -> dict[str, Any] | None:
    """Read and parse the provisioning manifest in *version_dir*.

    Returns:
        The manifest dict, or ``None`` when absent or unreadable
        (logged at debug per the no-swallow rule).
    """
    path = version_dir / MANIFEST_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.debug("qdrant manifest unreadable at %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        logger.debug("qdrant manifest at %s is not a dict", path)
        return None
    return cast("dict[str, Any]", data)


def _resolve_env_binary() -> ResolvedBinary | None:
    raw = get_config().qdrant_binary
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if candidate.is_file():
        return ResolvedBinary(path=candidate, source="env")
    logger.debug(
        "%s points at %s which does not exist; ignoring",
        EnvVar.QDRANT_BINARY.value,
        candidate,
    )
    return None


def _resolve_provisioned(version: str) -> ResolvedBinary | None:
    version_dir = qdrant_bin_dir(version)
    binary = version_dir / binary_filename()
    if not binary.is_file():
        return None
    manifest = read_manifest(version_dir)
    if manifest is None:
        logger.debug(
            "provisioned qdrant binary at %s has no manifest; ignoring",
            binary,
        )
        return None
    recorded_version = str(manifest.get("version", ""))
    if recorded_version != version:
        logger.debug(
            "provisioned qdrant manifest version %s != requested %s; ignoring",
            recorded_version,
            version,
        )
        return None
    return ResolvedBinary(
        path=binary,
        source="provisioned",
        version=recorded_version,
        sha256=str(manifest.get("binary_sha256", "")),
    )


def has_provisioned_binary(version: str = QDRANT_SERVER_VERSION) -> bool:
    """Return whether a verified provisioned binary exists for *version*.

    Lets callers detect when an unpinned env/PATH binary would shadow a
    properly provisioned (pinned, digest-checked) install.
    """
    return _resolve_provisioned(version) is not None


def resolve_binary(
    version: str = QDRANT_SERVER_VERSION,
) -> ResolvedBinary | None:
    """Resolve the active qdrant binary, or ``None`` when absent.

    Resolution order: operator env var, the managed provisioned dir
    for *version*, then ``PATH``.

    Args:
        version: The provisioned version to look for in the managed
            dir (the pinned version by default).

    Returns:
        The resolved binary with its origin, or ``None`` when no
        candidate exists.
    """
    resolved = _resolve_env_binary()
    if resolved is not None:
        return resolved

    resolved = _resolve_provisioned(version)
    if resolved is not None:
        return resolved

    on_path = shutil.which("qdrant")
    if on_path:
        return ResolvedBinary(path=Path(on_path), source="path")
    return None
