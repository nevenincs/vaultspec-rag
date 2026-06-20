"""Download-on-first-use provisioning of the pinned Qdrant server binary.

The flow: resolve the release asset for the running platform, download
it over HTTPS with redirects host-pinned to the allowed set, verify
the committed SHA256 digest BEFORE extraction, extract the single
binary into the managed versioned dir, mark it executable, and write a
provisioning manifest. A repeat run against a verified install reports
``unchanged`` with zero network I/O; checksum mismatch is a hard
failure that deletes the partial download.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, TYPE_CHECKING

from ._constants import (
    ALLOWED_DOWNLOAD_HOSTS,
    MANIFEST_FILENAME,
    QDRANT_ASSET_SHA256,
    QDRANT_RELEASE_BASE_URL,
    QDRANT_SERVER_VERSION,
    ProvisionReport,
    QdrantProvisionAction,
)
from ._resolve import asset_for_platform, binary_filename, qdrant_bin_dir, read_manifest

if TYPE_CHECKING:
    from http.client import HTTPMessage
    from typing import IO, Any

logger = logging.getLogger(__name__)

__all__ = [
    "ChecksumMismatchError",
    "clean_provisioned",
    "extract_verified_archive",
    "file_sha256",
    "provision",
    "provisioned_versions",
]

_DOWNLOAD_CHUNK_BYTES = 1 << 20
_DOWNLOAD_TIMEOUT_SECONDS = 120.0
# The release archives are ~30 MB; cap the stream well above that so a
# host-pinned-but-defective response cannot fill the disk before the
# SHA256 check would reject it (defense in depth behind the host pin).
_MAX_DOWNLOAD_BYTES = 256 << 20


class ChecksumMismatchError(RuntimeError):
    """Raised when a downloaded archive fails SHA256 verification.

    The offending file has already been deleted when this is raised.
    """

    def __init__(self, path: Path, expected: str, actual: str) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"SHA256 mismatch for {path.name}: expected {expected}, got "
            f"{actual}. The partial download was deleted; the upstream "
            "artifact may have been tampered with or the pin is stale."
        )


def file_sha256(path: Path) -> str:
    """Return the hex SHA256 digest of *path*'s content."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_DOWNLOAD_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


class _HostPinnedRedirect(urllib.request.HTTPRedirectHandler):
    """Allow redirects only inside :data:`ALLOWED_DOWNLOAD_HOSTS`."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        parsed = urllib.parse.urlparse(newurl)
        # A redirect must stay HTTPS: a downgrade to http on an allowed
        # host would still strip TLS, so reject it as firmly as a
        # cross-host redirect.
        if parsed.scheme != "https":
            raise urllib.error.URLError(
                f"Redirect to non-HTTPS URL {newurl!r} rejected"
            )
        host = parsed.hostname or ""
        if host.lower() not in ALLOWED_DOWNLOAD_HOSTS:
            raise urllib.error.URLError(
                f"Redirect to disallowed host {host!r} rejected "
                f"(allowed: {sorted(ALLOWED_DOWNLOAD_HOSTS)})"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download(url: str, dest: Path) -> None:
    """Stream *url* to *dest* with host-pinned redirects.

    Raises:
        urllib.error.URLError: On connection failure, a disallowed
            redirect, or a scheme/host outside the pinned set.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise urllib.error.URLError(f"Refusing non-HTTPS download URL {url!r}")
    if (parsed.hostname or "").lower() not in ALLOWED_DOWNLOAD_HOSTS:
        raise urllib.error.URLError(
            f"Refusing download from host {parsed.hostname!r} "
            f"(allowed: {sorted(ALLOWED_DOWNLOAD_HOSTS)})"
        )
    opener = urllib.request.build_opener(_HostPinnedRedirect)
    with (
        opener.open(url, timeout=_DOWNLOAD_TIMEOUT_SECONDS) as resp,
        dest.open("wb") as out,
    ):
        written = 0
        while chunk := resp.read(_DOWNLOAD_CHUNK_BYTES):
            written += len(chunk)
            if written > _MAX_DOWNLOAD_BYTES:
                raise urllib.error.URLError(
                    f"Download exceeded the {_MAX_DOWNLOAD_BYTES} byte cap; "
                    "refusing to continue"
                )
            out.write(chunk)


def _open_extract_dest(path: Path) -> IO[bytes]:
    """Open *path* for writing without following a pre-planted symlink.

    A local attacker who can pre-create a symlink at the managed destination
    could otherwise redirect the extraction write outside the managed dir. We
    unlink any existing symlink and open with ``O_NOFOLLOW`` where available,
    owner-only.
    """
    if path.is_symlink():
        path.unlink()
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    return os.fdopen(os.open(path, flags, 0o600), "wb")


def _extract_binary_member(archive: Path, dest_dir: Path) -> Path:
    """Extract the qdrant executable from *archive* into *dest_dir*.

    Handles both the Windows ``.zip`` (single ``qdrant.exe`` entry)
    and the Unix ``.tar.gz`` (single ``qdrant`` entry) shapes. Only
    the executable member is extracted - any other entry is ignored -
    and the member name is flattened so archive paths can never
    escape *dest_dir*.

    Raises:
        RuntimeError: When no qdrant executable member exists.
    """
    target_name = binary_filename()
    out_path = dest_dir / target_name

    # The download stages the archive under an extra ``.partial``
    # suffix; strip it before sniffing the archive format.
    effective_name = archive.name.removesuffix(".partial")
    if effective_name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if Path(info.filename).name == target_name and not info.is_dir():
                    with zf.open(info) as src, _open_extract_dest(out_path) as out:
                        shutil.copyfileobj(src, out, _DOWNLOAD_CHUNK_BYTES)
                    return out_path
    else:
        with tarfile.open(archive, "r:gz") as tf:
            for member in tf:
                if Path(member.name).name == target_name and member.isfile():
                    src = tf.extractfile(member)
                    if src is None:
                        continue
                    with src, _open_extract_dest(out_path) as out:
                        shutil.copyfileobj(src, out, _DOWNLOAD_CHUNK_BYTES)
                    return out_path
    raise RuntimeError(f"Archive {archive.name} contains no {target_name} member")


def extract_verified_archive(
    archive: Path,
    expected_sha256: str,
    dest_dir: Path,
) -> tuple[Path, str]:
    """Verify *archive* against *expected_sha256*, then extract.

    Verification strictly precedes extraction; on mismatch the archive
    is deleted and :class:`ChecksumMismatchError` raised, so a
    tampered artifact is never unpacked.

    Args:
        archive: The downloaded release archive.
        expected_sha256: The committed digest to verify against.
        dest_dir: Directory to place the extracted binary in.

    Returns:
        ``(binary_path, binary_sha256)`` for the extracted executable.

    Raises:
        ChecksumMismatchError: On digest mismatch (archive deleted).
    """
    actual = file_sha256(archive)
    if actual.lower() != expected_sha256.lower():
        archive.unlink(missing_ok=True)
        raise ChecksumMismatchError(archive, expected_sha256, actual)

    binary = _extract_binary_member(archive, dest_dir)
    if sys.platform != "win32":
        # Owner-only rwx: the service runs as one user; a world-executable
        # managed binary needlessly widens who can run it on a shared host.
        binary.chmod(0o700)
    return binary, file_sha256(binary)


def _write_manifest(
    version_dir: Path,
    *,
    asset: str,
    asset_sha256: str,
    binary_sha256: str,
    source: str,
) -> None:
    """Atomically write the provisioning manifest into *version_dir*."""
    manifest: dict[str, Any] = {
        "version": QDRANT_SERVER_VERSION,
        "asset": asset,
        "asset_sha256": asset_sha256,
        "binary_sha256": binary_sha256,
        "source": source,
        "provisioned_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    path = version_dir / MANIFEST_FILENAME
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(path))


def _existing_install_state(version_dir: Path, expected_sha256: str) -> str:
    """Classify the current contents of *version_dir*.

    Returns:
        ``"verified"`` when the binary and a pin-consistent manifest
        are present, ``"stale"`` when a binary exists but the manifest
        is absent or disagrees with the pin, ``"absent"`` otherwise.
    """
    binary = version_dir / binary_filename()
    if not binary.is_file():
        return "absent"
    manifest = read_manifest(version_dir)
    if (
        manifest is not None
        and str(manifest.get("version")) == QDRANT_SERVER_VERSION
        and str(manifest.get("asset_sha256", "")).lower() == expected_sha256.lower()
    ):
        return "verified"
    return "stale"


def _provision_operator_binary(
    binary: Path,
    version_dir: Path,
    *,
    dry_run: bool,
    previously: str,
) -> ProvisionReport:
    """Register an operator-supplied binary into the managed dir."""
    target = version_dir / binary_filename()
    if dry_run:
        return ProvisionReport(
            action=QdrantProvisionAction.DRY_RUN,
            binary=target,
            message=(
                f"Would copy operator binary {binary} to {target} and record "
                "an operator-sourced manifest (no checksum pin applies)."
            ),
        )
    if not binary.is_file():
        return ProvisionReport(
            action=QdrantProvisionAction.FAILED,
            binary=binary,
            message=f"Operator binary {binary} does not exist.",
        )
    if binary.is_symlink():
        # Copying a symlink dereferences it, so a swap between the operator's
        # intent and the copy (TOCTOU on a shared dir) could register attacker
        # content under an operator-blessed manifest. Require a regular file.
        return ProvisionReport(
            action=QdrantProvisionAction.FAILED,
            binary=binary,
            message=(
                f"Operator binary {binary} is a symlink; refusing to follow it. "
                "Provide a regular-file path."
            ),
        )
    version_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(binary, target, follow_symlinks=False)
    if sys.platform != "win32":
        target.chmod(0o700)
    digest = file_sha256(target)
    _write_manifest(
        version_dir,
        asset="",
        asset_sha256="",
        binary_sha256=digest,
        source="operator",
    )
    logger.warning(
        "Registered operator-supplied qdrant binary %s; the committed "
        "checksum pin does not apply to it",
        binary,
    )
    action = (
        QdrantProvisionAction.UPDATED
        if previously != "absent"
        else QdrantProvisionAction.CREATED
    )
    return ProvisionReport(action=action, binary=target, sha256=digest)


def _download_and_install(
    *,
    url: str,
    asset: str,
    expected_sha256: str,
    version_dir: Path,
    previously: str,
) -> ProvisionReport:
    """Download, verify, extract, and record the pinned binary."""
    version_dir.mkdir(parents=True, exist_ok=True)
    archive = version_dir / f"{asset}.partial"
    try:
        logger.info("Downloading %s", url)
        _download(url, archive)
        binary, binary_sha = extract_verified_archive(
            archive, expected_sha256, version_dir
        )
    except ChecksumMismatchError as exc:
        logger.error("qdrant provisioning failed verification: %s", exc)
        return ProvisionReport(
            action=QdrantProvisionAction.FAILED,
            asset=asset,
            url=url,
            sha256=expected_sha256,
            message=str(exc),
        )
    except (
        OSError,
        urllib.error.URLError,
        RuntimeError,
        tarfile.TarError,
        zipfile.BadZipFile,
    ) as exc:
        archive.unlink(missing_ok=True)
        # Also remove any partially-extracted binary so a failed install never
        # leaves a half-written executable behind (it would lack a manifest and
        # so never run, but it should not linger or mislead install state).
        (version_dir / binary_filename()).unlink(missing_ok=True)
        logger.error("qdrant provisioning failed: %s", exc)
        return ProvisionReport(
            action=QdrantProvisionAction.FAILED,
            asset=asset,
            url=url,
            sha256=expected_sha256,
            message=str(exc),
        )
    archive.unlink(missing_ok=True)
    _write_manifest(
        version_dir,
        asset=asset,
        asset_sha256=expected_sha256,
        binary_sha256=binary_sha,
        source="download",
    )
    action = (
        QdrantProvisionAction.UPDATED
        if previously != "absent"
        else QdrantProvisionAction.CREATED
    )
    return ProvisionReport(
        action=action,
        asset=asset,
        url=url,
        binary=binary,
        sha256=expected_sha256,
    )


def provision(
    *,
    upgrade: bool = False,
    dry_run: bool = False,
    binary: Path | None = None,
) -> ProvisionReport:
    """Provision the pinned qdrant server binary into the managed dir.

    Idempotent: a verified existing install reports ``unchanged`` with
    zero network I/O. A stale install (binary present but manifest
    absent or disagreeing with the pin) requires ``upgrade=True`` to
    be replaced and reports ``failed`` otherwise, so a manual
    modification is never silently overwritten.

    Args:
        upgrade: Re-fetch and replace a stale or pin-divergent
            install.
        dry_run: Report what would happen without touching the network
            or the filesystem.
        binary: Operator-supplied binary to register instead of
            downloading (no checksum pin applies; recorded in the
            manifest as operator-sourced).

    Returns:
        A :class:`ProvisionReport` in the sync vocabulary.
    """
    asset = asset_for_platform()
    expected = QDRANT_ASSET_SHA256[asset]
    url = f"{QDRANT_RELEASE_BASE_URL}/v{QDRANT_SERVER_VERSION}/{asset}"
    version_dir = qdrant_bin_dir()
    state = _existing_install_state(version_dir, expected)

    if binary is not None:
        return _provision_operator_binary(
            binary, version_dir, dry_run=dry_run, previously=state
        )

    if state == "verified" and not upgrade:
        return ProvisionReport(
            action=QdrantProvisionAction.UNCHANGED,
            asset=asset,
            url=url,
            binary=version_dir / binary_filename(),
            sha256=expected,
            message="Verified install already present; nothing to do.",
        )
    if state == "verified" and upgrade:
        # The versioned dir already matches the pin; an upgrade run
        # after a constants bump targets a new version dir, so this
        # path is also a no-op.
        return ProvisionReport(
            action=QdrantProvisionAction.UNCHANGED,
            asset=asset,
            url=url,
            binary=version_dir / binary_filename(),
            sha256=expected,
            message="Install already matches the pin; nothing to upgrade.",
        )
    if state == "stale" and not upgrade:
        return ProvisionReport(
            action=QdrantProvisionAction.FAILED,
            asset=asset,
            url=url,
            binary=version_dir / binary_filename(),
            sha256=expected,
            message=(
                f"A binary exists at {version_dir} but its manifest does not "
                "match the committed pin. Re-run with --upgrade to replace "
                "it, or remove the directory."
            ),
        )

    if dry_run:
        return ProvisionReport(
            action=QdrantProvisionAction.DRY_RUN,
            asset=asset,
            url=url,
            binary=version_dir / binary_filename(),
            sha256=expected,
            message=(
                f"Would download {asset} from {url}, verify SHA256 "
                f"{expected}, and install to {version_dir}."
            ),
        )

    return _download_and_install(
        url=url,
        asset=asset,
        expected_sha256=expected,
        version_dir=version_dir,
        previously=state,
    )


def provisioned_versions() -> list[dict[str, object]]:
    """Enumerate provisioned versions in the managed bin dir (bounded).

    Returns:
        One entry per version dir that contains a qdrant binary, newest
        version string first, capped at 10 entries.
    """
    base = qdrant_bin_dir().parent
    if not base.is_dir():
        return []
    entries: list[dict[str, object]] = []
    for child in sorted(base.iterdir(), reverse=True):
        if not child.is_dir():
            continue
        binary = child / binary_filename()
        if not binary.is_file():
            continue
        manifest = read_manifest(child) or {}
        entries.append(
            {
                "version": child.name,
                "binary": str(binary),
                "source": manifest.get("source", "unknown"),
                "provisioned_at": manifest.get("provisioned_at", ""),
                "current": child.name == QDRANT_SERVER_VERSION,
            }
        )
        if len(entries) >= 10:
            break
    return entries


def clean_provisioned(*, keep_current: bool = False) -> list[str]:
    """Delete provisioned version dirs from the managed bin dir.

    Args:
        keep_current: Preserve the dir matching the pinned version.

    Returns:
        The version strings removed.
    """
    base = qdrant_bin_dir().parent
    if not base.is_dir():
        return []
    removed: list[str] = []
    for child in sorted(base.iterdir()):
        # Never recurse through a symlink/Windows junction: is_dir() is True for
        # a reparse point and rmtree would delete the *target's* contents.
        if child.is_symlink() or not child.is_dir():
            continue
        if keep_current and child.name == QDRANT_SERVER_VERSION:
            continue
        shutil.rmtree(child, onexc=_rmtree_safe_onexc)
        removed.append(child.name)
    return removed


def _rmtree_safe_onexc(_func: object, path: str | bytes, exc: BaseException) -> None:
    """``shutil.rmtree`` error handler that unlinks a symlink rather than
    following it (defense-in-depth for a symlink/junction encountered mid-tree
    after the top-level ``is_symlink`` check)."""
    p = Path(os.fsdecode(path))
    if p.is_symlink():
        try:
            p.unlink()
        except OSError as exc_unlink:
            logger.warning("Failed to unlink symlink %s: %s", p, exc_unlink)
        return
    raise exc
