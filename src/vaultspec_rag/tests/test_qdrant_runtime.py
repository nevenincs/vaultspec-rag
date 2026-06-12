"""Unit tests for the qdrant_runtime package.

Exercises real logic only: asset resolution tables, real SHA256
verification against real archives built on disk, real provisioning
state machines against a temp-isolated managed dir, and the
pin-vs-lockfile guard parsed from the repository's actual ``uv.lock``.
No network I/O happens anywhere in this module: the idempotency path
is proven by pre-seeding a verified install (downloads are host-pinned
to upstream, so a fixture URL cannot stand in for the network leg).
"""

from __future__ import annotations

import json
import os
import re
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ..config import EnvVar, reset_config
from ..qdrant_runtime import (
    QDRANT_ASSET_SHA256,
    QDRANT_SERVER_VERSION,
    ChecksumMismatchError,
    QdrantProvisionAction,
    asset_for_platform,
    binary_filename,
    extract_verified_archive,
    file_sha256,
    provision,
    provisioned_versions,
    qdrant_bin_dir,
    resolve_binary,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _reset_config_around_each_test() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    reset_config()
    yield
    reset_config()


@pytest.fixture
def isolated_status_dir(tmp_path: Path) -> Iterator[Path]:
    """Point the managed service dir (and thus the bin dir) at tmp."""
    prev = os.environ.get(EnvVar.STATUS_DIR.value)
    os.environ[EnvVar.STATUS_DIR.value] = str(tmp_path)
    reset_config()
    try:
        yield tmp_path
    finally:
        if prev is None:
            os.environ.pop(EnvVar.STATUS_DIR.value, None)
        else:
            os.environ[EnvVar.STATUS_DIR.value] = prev
        reset_config()


class TestAssetResolution:
    @pytest.mark.parametrize(
        ("platform", "machine", "expected"),
        [
            ("win32", "AMD64", "qdrant-x86_64-pc-windows-msvc.zip"),
            ("win32", "x86_64", "qdrant-x86_64-pc-windows-msvc.zip"),
            ("darwin", "arm64", "qdrant-aarch64-apple-darwin.tar.gz"),
            ("darwin", "x86_64", "qdrant-x86_64-apple-darwin.tar.gz"),
            ("linux", "x86_64", "qdrant-x86_64-unknown-linux-gnu.tar.gz"),
            ("linux", "aarch64", "qdrant-aarch64-unknown-linux-musl.tar.gz"),
            ("linux2", "amd64", "qdrant-x86_64-unknown-linux-gnu.tar.gz"),
        ],
    )
    def test_known_platforms(self, platform: str, machine: str, expected: str) -> None:
        assert asset_for_platform(platform, machine) == expected

    @pytest.mark.parametrize(
        ("platform", "machine"),
        [
            ("win32", "arm64"),
            ("sunos5", "sparc"),
            ("linux", "riscv64"),
        ],
    )
    def test_unsupported_platforms_raise(self, platform: str, machine: str) -> None:
        with pytest.raises(RuntimeError, match="No Qdrant server release asset"):
            asset_for_platform(platform, machine)

    def test_running_platform_resolves(self) -> None:
        assert asset_for_platform() in QDRANT_ASSET_SHA256


class TestPinTable:
    def test_every_digest_is_sha256_hex(self) -> None:
        for asset, digest in QDRANT_ASSET_SHA256.items():
            assert re.fullmatch(r"[0-9a-f]{64}", digest), asset

    def test_pin_minor_matches_locked_client_minor(self) -> None:
        """The server pin must stay on the locked qdrant-client minor line.

        Parses the repository's real ``uv.lock`` rather than trusting
        installed metadata, so a lockfile bump that forgets the server
        pin fails here.
        """
        lock_path = Path(__file__).resolve().parents[3] / "uv.lock"
        text = lock_path.read_text(encoding="utf-8")
        match = re.search(
            r'name = "qdrant-client"\s*\nversion = "(\d+)\.(\d+)\.',
            text,
        )
        assert match is not None, "qdrant-client missing from uv.lock"
        client_major, client_minor = match.group(1), match.group(2)
        server_major, server_minor, _ = QDRANT_SERVER_VERSION.split(".")
        assert (server_major, server_minor) == (client_major, client_minor), (
            f"server pin {QDRANT_SERVER_VERSION} is off the locked "
            f"qdrant-client {client_major}.{client_minor}.x minor line"
        )


def _build_binary_zip(directory: Path, payload: bytes) -> Path:
    """Build a real .zip archive containing a qdrant binary member."""
    archive = directory / "qdrant-test-asset.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(binary_filename(), payload)
    return archive


class TestVerifiedExtraction:
    def test_verify_then_extract_round_trip(self, tmp_path: Path) -> None:
        payload = b"#!fake-qdrant-binary\x00" * 64
        archive = _build_binary_zip(tmp_path, payload)
        expected = file_sha256(archive)

        out_dir = tmp_path / "out"
        out_dir.mkdir()
        binary, binary_sha = extract_verified_archive(archive, expected, out_dir)

        assert binary == out_dir / binary_filename()
        assert binary.read_bytes() == payload
        assert binary_sha == file_sha256(binary)

    def test_checksum_mismatch_deletes_partial(self, tmp_path: Path) -> None:
        archive = _build_binary_zip(tmp_path, b"tampered-content")
        wrong = "0" * 64

        with pytest.raises(ChecksumMismatchError):
            extract_verified_archive(archive, wrong, tmp_path)

        assert not archive.exists(), "partial download must be deleted"
        assert not (tmp_path / binary_filename()).exists(), (
            "nothing may be extracted from an unverified archive"
        )


class TestPreExecDigestGuard:
    """A tampered provisioned binary must be refused before execution."""

    def test_corrupted_binary_refused_before_spawn(
        self, isolated_status_dir: Path
    ) -> None:
        from ..config import get_config
        from ..qdrant_runtime import start_supervised_from_config

        _ = isolated_status_dir
        version_dir = qdrant_bin_dir()
        binary = _seed_verified_install(version_dir)
        # Tamper with the binary AFTER the manifest recorded its digest:
        # the pre-execution re-hash must now mismatch and refuse to run.
        binary.write_bytes(b"tampered-after-manifest")

        os.environ[EnvVar.QDRANT_SERVER.value] = "1"
        get_config(None)
        reset_config()
        try:
            with pytest.raises(RuntimeError, match="manifest digest"):
                start_supervised_from_config()
        finally:
            os.environ.pop(EnvVar.QDRANT_SERVER.value, None)
            reset_config()


class TestDownloadGuards:
    """The host/scheme pin is the security boundary; prove it refuses."""

    def test_non_https_url_refused(self, tmp_path: Path) -> None:
        import urllib.error

        from ..qdrant_runtime import _provision

        with pytest.raises(urllib.error.URLError, match="non-HTTPS"):
            _provision._download(
                "http://github.com/qdrant/qdrant/releases/x.zip",
                tmp_path / "out.zip",
            )
        assert not (tmp_path / "out.zip").exists()

    def test_cross_host_url_refused(self, tmp_path: Path) -> None:
        import urllib.error

        from ..qdrant_runtime import _provision

        with pytest.raises(urllib.error.URLError, match="host"):
            _provision._download(
                "https://evil.example.com/qdrant.zip",
                tmp_path / "out.zip",
            )
        assert not (tmp_path / "out.zip").exists()

    def test_redirect_handler_rejects_downgrade_and_cross_host(self) -> None:
        import urllib.error
        from typing import Any, cast

        from ..qdrant_runtime import _provision

        handler = _provision._HostPinnedRedirect()
        none = cast("Any", None)  # req/fp/headers are unused before the guard
        # A redirect that downgrades to http on an allowed host must be
        # refused as firmly as a cross-host redirect.
        with pytest.raises(urllib.error.URLError, match="non-HTTPS"):
            handler.redirect_request(
                none,
                none,
                302,
                "Found",
                none,
                "http://github.com/qdrant/qdrant/x.zip",
            )
        with pytest.raises(urllib.error.URLError, match="disallowed host"):
            handler.redirect_request(
                none,
                none,
                302,
                "Found",
                none,
                "https://evil.example.com/x.zip",
            )


class TestArchiveTraversal:
    """A malicious archive member must never escape the destination dir."""

    def test_traversal_member_is_flattened(self, tmp_path: Path) -> None:
        # A zip whose binary member carries a traversal path; the
        # extractor matches on basename and writes to dest only.
        archive = tmp_path / "evil.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr(f"../../../../escape/{binary_filename()}", b"payload-x")
        expected = file_sha256(archive)

        out_dir = tmp_path / "out"
        out_dir.mkdir()
        binary, _ = extract_verified_archive(archive, expected, out_dir)

        assert binary == out_dir / binary_filename()
        assert binary.read_bytes() == b"payload-x"
        # Nothing landed outside the destination directory.
        assert not (tmp_path / "escape").exists()
        assert not (tmp_path.parent / "escape").exists()


def _seed_verified_install(version_dir: Path) -> Path:
    """Pre-seed a managed dir exactly as a verified provision leaves it."""
    version_dir.mkdir(parents=True, exist_ok=True)
    binary = version_dir / binary_filename()
    binary.write_bytes(b"preseeded-binary")
    asset = asset_for_platform()
    manifest = {
        "version": QDRANT_SERVER_VERSION,
        "asset": asset,
        "asset_sha256": QDRANT_ASSET_SHA256[asset],
        "binary_sha256": file_sha256(binary),
        "source": "download",
        "provisioned_at": "2026-06-12T00:00:00+00:00",
    }
    (version_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return binary


class TestProvision:
    def test_dry_run_writes_nothing(self, isolated_status_dir: Path) -> None:
        report = provision(dry_run=True)

        assert report.action == QdrantProvisionAction.DRY_RUN
        assert report.url.startswith("https://github.com/qdrant/qdrant/")
        assert report.sha256 == QDRANT_ASSET_SHA256[asset_for_platform()]
        assert not (isolated_status_dir / "bin").exists()

    def test_preseeded_verified_install_is_unchanged(
        self, isolated_status_dir: Path
    ) -> None:
        _ = isolated_status_dir
        version_dir = qdrant_bin_dir()
        binary = _seed_verified_install(version_dir)
        before = binary.stat().st_mtime_ns

        report = provision()

        assert report.action == QdrantProvisionAction.UNCHANGED
        assert report.binary == binary
        assert binary.stat().st_mtime_ns == before, "unchanged must not rewrite"

    def test_preseeded_verified_install_unchanged_under_upgrade(
        self, isolated_status_dir: Path
    ) -> None:
        _ = isolated_status_dir
        _seed_verified_install(qdrant_bin_dir())

        report = provision(upgrade=True)

        assert report.action == QdrantProvisionAction.UNCHANGED

    def test_stale_install_fails_without_upgrade(
        self, isolated_status_dir: Path
    ) -> None:
        _ = isolated_status_dir
        version_dir = qdrant_bin_dir()
        version_dir.mkdir(parents=True)
        (version_dir / binary_filename()).write_bytes(b"manually-placed")

        report = provision()

        assert report.action == QdrantProvisionAction.FAILED
        assert "--upgrade" in report.message

    def test_operator_binary_registers_without_network(
        self, isolated_status_dir: Path, tmp_path: Path
    ) -> None:
        _ = isolated_status_dir
        operator_binary = tmp_path / "operator-qdrant.bin"
        operator_binary.write_bytes(b"operator-supplied")

        report = provision(binary=operator_binary)

        assert report.action == QdrantProvisionAction.CREATED
        assert report.binary is not None
        assert report.binary.read_bytes() == b"operator-supplied"
        manifest = json.loads(
            (qdrant_bin_dir() / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["source"] == "operator"
        assert manifest["binary_sha256"] == file_sha256(report.binary)

    def test_missing_operator_binary_fails(
        self, isolated_status_dir: Path, tmp_path: Path
    ) -> None:
        _ = isolated_status_dir
        report = provision(binary=tmp_path / "does-not-exist")

        assert report.action == QdrantProvisionAction.FAILED


class TestResolution:
    def test_resolves_provisioned_install(self, isolated_status_dir: Path) -> None:
        _ = isolated_status_dir
        binary = _seed_verified_install(qdrant_bin_dir())

        resolved = resolve_binary()

        assert resolved is not None
        assert resolved.path == binary
        assert resolved.source == "provisioned"
        assert resolved.version == QDRANT_SERVER_VERSION
        assert resolved.sha256 == file_sha256(binary)

    def test_env_binary_wins_over_provisioned(
        self, isolated_status_dir: Path, tmp_path: Path
    ) -> None:
        _ = isolated_status_dir
        _seed_verified_install(qdrant_bin_dir())
        operator_binary = tmp_path / "env-qdrant.bin"
        operator_binary.write_bytes(b"env-binary")

        prev = os.environ.get(EnvVar.QDRANT_BINARY.value)
        os.environ[EnvVar.QDRANT_BINARY.value] = str(operator_binary)
        reset_config()
        try:
            resolved = resolve_binary()
        finally:
            if prev is None:
                os.environ.pop(EnvVar.QDRANT_BINARY.value, None)
            else:
                os.environ[EnvVar.QDRANT_BINARY.value] = prev
            reset_config()

        assert resolved is not None
        assert resolved.path == operator_binary
        assert resolved.source == "env"

    def test_binary_without_manifest_is_not_provisioned(
        self, isolated_status_dir: Path
    ) -> None:
        _ = isolated_status_dir
        version_dir = qdrant_bin_dir()
        version_dir.mkdir(parents=True)
        (version_dir / binary_filename()).write_bytes(b"no-manifest")

        resolved = resolve_binary()

        assert resolved is None or resolved.source == "path"

    def test_provisioned_versions_lists_seeded_install(
        self, isolated_status_dir: Path
    ) -> None:
        _ = isolated_status_dir
        _seed_verified_install(qdrant_bin_dir())

        versions = provisioned_versions()

        assert len(versions) == 1
        assert versions[0]["version"] == QDRANT_SERVER_VERSION
        assert versions[0]["current"] is True


class TestConfigKnobs:
    def test_defaults(self) -> None:
        from ..config import get_config

        cfg = get_config()
        assert cfg.qdrant_server is False
        assert cfg.qdrant_port == 8765
        assert cfg.qdrant_binary is None
        assert "qdrant-server" in str(cfg.qdrant_storage_dir)

    def test_env_overrides(self) -> None:
        from ..config import get_config

        previous = {
            var: os.environ.get(var.value)
            for var in (EnvVar.QDRANT_SERVER, EnvVar.QDRANT_PORT)
        }
        os.environ[EnvVar.QDRANT_SERVER.value] = "1"
        os.environ[EnvVar.QDRANT_PORT.value] = "9123"
        reset_config()
        try:
            cfg = get_config()
            assert cfg.qdrant_server is True
            assert cfg.qdrant_port == 9123
        finally:
            for var, prev in previous.items():
                if prev is None:
                    os.environ.pop(var.value, None)
                else:
                    os.environ[var.value] = prev
            reset_config()
