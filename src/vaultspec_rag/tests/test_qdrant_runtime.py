"""Unit tests for the qdrant_runtime package.

Exercises real logic only: asset resolution tables, real SHA256
verification against real archives built on disk, real provisioning
state machines against a temp-isolated managed dir, and the
pin-vs-lockfile guard parsed from the repository's actual ``uv.lock``.
No network I/O happens anywhere in this module: the idempotency path
is proven by pre-seeding a verified install, and the download leg has
its own module.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from .._sync_vocabulary import ProvisionAction
from ..config._types import EnvVar
from ..qdrant_runtime._constants import (
    QDRANT_ASSET_SHA256,
    QDRANT_EXECUTABLE_SHA256,
    QDRANT_SERVER_VERSION,
    BinarySource,
)
from ..qdrant_runtime._provision import (
    ChecksumMismatchError,
    extract_verified_archive,
    file_sha256,
    provision,
    provisioned_versions,
)
from ..qdrant_runtime._resolve import (
    QdrantBinaryError,
    UnsupportedPlatformError,
    asset_for_platform,
    binary_filename,
    expected_executable_sha256,
    has_provisioned_binary,
    operator_registration_refusal,
    qdrant_bin_dir,
    resolve_binary,
)
from ..qdrant_runtime._spawn_trust import verify_resolved_binary
from ._config_fixtures import reset_config
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.unit]


@pytest.fixture
def isolated_status_dir(
    tmp_path: Path,
    isolated_singleton_dirs: Path,
) -> Iterator[Path]:
    """Add port and operator-binary isolation to the singleton-dir relocation.

    A supervisor test binds a real Qdrant port, so the configured port must
    move off the machine default as well as the two managed directories -
    otherwise a test collides with a live server on the shared port.

    The operator binary settings are cleared too. They outrank the managed
    install, so values in the developer's own environment would decide every
    resolution here instead of the install the test seeded.
    """
    del isolated_singleton_dirs
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        isolated_port = int(probe.getsockname()[1])
    with managed_env(
        **{
            EnvVar.QDRANT_PORT.value: str(isolated_port),
            EnvVar.QDRANT_BINARY.value: None,
            EnvVar.QDRANT_BINARY_SHA256.value: None,
        }
    ):
        yield tmp_path


def _operator_binary_env(path: Path | str, sha256: str | None) -> dict[str, str | None]:
    """The two operator settings, as an operator would export them."""
    return {
        EnvVar.QDRANT_BINARY.value: str(path),
        EnvVar.QDRANT_BINARY_SHA256.value: sha256,
    }


class TestAssetResolution:
    @pytest.mark.parametrize(
        ("platform", "machine", "expected"),
        [
            ("win32", "AMD64", "qdrant-x86_64-pc-windows-msvc.zip"),
            ("win32", "x86_64", "qdrant-x86_64-pc-windows-msvc.zip"),
            ("darwin", "arm64", "qdrant-aarch64-apple-darwin.tar.gz"),
            ("darwin", "x86_64", "qdrant-x86_64-apple-darwin.tar.gz"),
            ("linux", "x86_64", "qdrant-x86_64-unknown-linux-musl.tar.gz"),
            ("linux", "aarch64", "qdrant-aarch64-unknown-linux-musl.tar.gz"),
            ("linux2", "amd64", "qdrant-x86_64-unknown-linux-musl.tar.gz"),
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
        with pytest.raises(
            UnsupportedPlatformError, match="No Qdrant server release asset"
        ):
            asset_for_platform(platform, machine)

    def test_running_platform_resolves(self) -> None:
        assert asset_for_platform() in QDRANT_ASSET_SHA256


class TestPinTable:
    def test_every_digest_is_sha256_hex(self) -> None:
        for table in (QDRANT_ASSET_SHA256, QDRANT_EXECUTABLE_SHA256):
            for asset, digest in table.items():
                assert re.fullmatch(r"[0-9a-f]{64}", digest), asset

    def test_executable_pins_cover_exactly_the_archive_pins(self) -> None:
        """Every installable asset has an executable pin, and nothing else does.

        An asset pinned only as an archive would download, verify, install,
        and then be refused at every spawn. Proven able to fail: deleting one
        entry from the executable table fails this on the equality below.
        """
        assert set(QDRANT_EXECUTABLE_SHA256) == set(QDRANT_ASSET_SHA256)

    def test_no_digest_is_pinned_twice(self) -> None:
        """An archive digest pasted into the executable table is caught here.

        The two tables hold digests of different files, so no value may
        repeat within or across them. Proven able to fail: setting one
        executable entry to its asset's archive digest fails this on the
        count below.
        """
        pinned = [*QDRANT_ASSET_SHA256.values(), *QDRANT_EXECUTABLE_SHA256.values()]
        assert len(set(pinned)) == len(pinned)


_GNU_ASSET = "qdrant-x86_64-unknown-linux-gnu.tar.gz"


class TestExpectedExecutableDigest:
    """Which digest a managed install's executable is held to.

    The manifest sits beside the binary it describes, so it may only say
    which asset of the pinned release was installed. The digest itself has to
    come from the committed table, and nothing else the manifest says is
    believed.
    """

    @pytest.mark.parametrize("source", ["download", "archive"])
    @pytest.mark.parametrize("asset", sorted(QDRANT_EXECUTABLE_SHA256))
    def test_the_pinned_release_is_held_to_the_committed_digest_of_its_asset(
        self, asset: str, source: str
    ) -> None:
        """Fetched or unpacked from a local archive, the expectation is the pin.

        Proven able to fail: returning the manifest's ``binary_sha256`` fails
        this on the equality below, for every asset and both sources.
        """
        manifest = {
            "source": source,
            "asset": asset,
            "binary_sha256": "f" * 64,
        }
        assert expected_executable_sha256(manifest) == QDRANT_EXECUTABLE_SHA256[asset]

    def test_an_install_from_the_unselected_gnu_asset_keeps_its_own_digest(
        self,
    ) -> None:
        """An install made while gnu was selected is compared to the gnu pin.

        Proven able to fail: looking the digest up by the asset the running
        platform selects, instead of the one the manifest names, fails this on
        the equality below - no platform selects gnu.
        """
        assert (
            expected_executable_sha256({"source": "download", "asset": _GNU_ASSET})
            == QDRANT_EXECUTABLE_SHA256[_GNU_ASSET]
        )

    @pytest.mark.parametrize(
        "manifest",
        [
            {"version": QDRANT_SERVER_VERSION},
            {"source": "download"},
            {"source": "download", "asset": ""},
            {"source": "download", "asset": "qdrant-riscv64-unknown-linux.tar.gz"},
            {"asset": "not-an-asset", "binary_sha256": "a" * 64},
        ],
    )
    def test_no_digest_is_established_without_a_pinned_asset(
        self, manifest: dict[str, object]
    ) -> None:
        """An asset outside the table never verifies; nothing stands in for it.

        Proven able to fail: falling back to the running platform's digest for
        an unknown asset fails this on the equality below.
        """
        assert expected_executable_sha256(manifest) == ""

    @pytest.mark.parametrize(
        "source",
        ["operator", "Operator", "registered", "manual", "", None, "downloads"],
    )
    def test_no_other_source_is_honoured_whatever_else_the_manifest_says(
        self, source: str | None
    ) -> None:
        """Only the two ways the pinned release arrives establish a digest.

        Each manifest names a pinned asset and records a digest of its own.
        Under the rule that let an operator registration vouch for itself,
        the recorded digest came back for ``operator``; under a rule that
        merely excluded that one word, every other spelling here would be
        treated as a download and get the committed digest.

        Proven able to fail: honouring the manifest's digest for an operator
        source fails the ``operator`` case on the equality below; excluding
        only that value instead of admitting only the two sources fails every
        other case.
        """
        manifest: dict[str, object] = {
            "asset": asset_for_platform(),
            "binary_sha256": "b" * 64,
        }
        if source is not None:
            manifest["source"] = source
        assert expected_executable_sha256(manifest) == ""

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
    """A managed install that does not verify is refused by a real start."""

    @staticmethod
    def _refused_start() -> QdrantBinaryError:
        from ..qdrant_runtime._supervise import start_supervised_from_config

        with (
            managed_env(**{EnvVar.QDRANT_SERVER.value: "1"}),
            pytest.raises(QdrantBinaryError) as refused,
        ):
            start_supervised_from_config()
        return refused.value

    def test_a_download_whose_executable_is_not_the_pinned_one_is_refused(
        self, isolated_status_dir: Path
    ) -> None:
        """The manifest agreeing with the file is not what lets it run.

        The seeded manifest records the seeded file's own digest, so a check
        against the manifest passes. Only the committed digest refuses it.
        """
        _ = isolated_status_dir
        binary = _seed_verified_install(qdrant_bin_dir())
        manifest = json.loads(
            (qdrant_bin_dir() / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["binary_sha256"] == file_sha256(binary)

        refused = self._refused_start()

        assert refused.error == "qdrant_binary_unverified"
        assert "the pinned digest of its release asset" in str(refused)
        assert "vaultspec-rag server qdrant install --upgrade" in str(refused)

    def test_a_manifest_that_records_no_digest_does_not_skip_the_check(
        self, isolated_status_dir: Path
    ) -> None:
        """An install with nothing to compare against never runs.

        Mutation it catches: skipping the comparison when no digest applies.
        The start then goes on to execute the seeded file, which is not a
        program, and this fails on an ``OSError`` in place of the refusal.
        """
        _ = isolated_status_dir
        version_dir = qdrant_bin_dir()
        version_dir.mkdir(parents=True)
        (version_dir / binary_filename()).write_bytes(b"no-digest-recorded")
        (version_dir / "manifest.json").write_text(
            json.dumps({"version": QDRANT_SERVER_VERSION}), encoding="utf-8"
        )
        resolved = resolve_binary()
        assert resolved is not None
        assert resolved.sha256 == ""

        assert self._refused_start().error == "qdrant_binary_unverified"

    def test_an_install_whose_manifest_claims_an_operator_put_it_there_is_refused(
        self, isolated_status_dir: Path
    ) -> None:
        """The manifest vouching for its own binary is not honoured.

        The manifest records the file's true digest, so everything it says is
        consistent - which is exactly what anyone able to write the directory
        can arrange. The start is refused as an invalid install, and the
        refusal names both routes that replace it.

        Mutation it catches: resolving such an install and holding it to the
        digest its manifest records. The file matches that digest, so the
        start then goes on to execute it and this fails on an ``OSError`` in
        place of the refusal.
        """
        _ = isolated_status_dir
        binary = _seed_operator_claiming_install(qdrant_bin_dir())

        refused = self._refused_start()

        assert refused.error == "qdrant_install_invalid"
        message = str(refused)
        assert str(binary) in message
        assert EnvVar.QDRANT_BINARY.value in message
        assert EnvVar.QDRANT_BINARY_SHA256.value in message
        assert "vaultspec-rag server qdrant install --upgrade" in message
        assert "--archive <file>" in message

    def test_an_operator_binary_that_is_not_what_was_declared_is_refused(
        self, isolated_status_dir: Path, tmp_path: Path
    ) -> None:
        """A declared digest is enforced, not recorded.

        Mutation it catches: running an operator binary without comparing it
        to its declared digest. The start then executes the file, which is
        not a program, and this fails on an ``OSError`` in place of the
        refusal.
        """
        from ..qdrant_runtime._supervise import start_supervised_from_config

        _ = isolated_status_dir
        operator_binary = tmp_path / "operator-qdrant.bin"
        operator_binary.write_bytes(b"what the operator has")
        declared = hashlib.sha256(b"what the operator declared").hexdigest()

        with (
            managed_env(**_operator_binary_env(operator_binary, declared)),
            pytest.raises(QdrantBinaryError) as refused,
        ):
            start_supervised_from_config()

        assert refused.value.error == "qdrant_binary_unverified"
        message = str(refused.value)
        assert f"declared in {EnvVar.QDRANT_BINARY_SHA256.value}" in message
        assert str(operator_binary) in message


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

        assert report.action == ProvisionAction.DRY_RUN
        assert report.url.startswith("https://github.com/qdrant/qdrant/")
        assert report.sha256 == QDRANT_ASSET_SHA256[asset_for_platform()]
        assert not (isolated_status_dir / "bin").exists()

    def test_stale_install_fails_without_upgrade(
        self, isolated_status_dir: Path
    ) -> None:
        _ = isolated_status_dir
        version_dir = qdrant_bin_dir()
        version_dir.mkdir(parents=True)
        (version_dir / binary_filename()).write_bytes(b"manually-placed")

        report = provision()

        assert report.action == ProvisionAction.FAILED
        assert "--upgrade" in report.message


def _seed_operator_claiming_install(version_dir: Path) -> Path:
    """Seed the install an operator registration used to leave behind.

    Internally consistent in every respect: the manifest names the pinned
    version and records the digest the file really has.
    """
    version_dir.mkdir(parents=True, exist_ok=True)
    binary = version_dir / binary_filename()
    binary.write_bytes(b"operator-registered")
    manifest = {
        "version": QDRANT_SERVER_VERSION,
        "asset": "",
        "asset_sha256": "",
        "binary_sha256": file_sha256(binary),
        "source": "operator",
        "provisioned_at": "2026-06-12T00:00:00+00:00",
    }
    (version_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return binary


class TestResolution:
    def test_resolves_provisioned_install(self, isolated_status_dir: Path) -> None:
        _ = isolated_status_dir
        binary = _seed_verified_install(qdrant_bin_dir())

        resolved = resolve_binary()

        assert resolved is not None
        assert resolved.path == binary
        assert resolved.source == "provisioned"
        assert resolved.version == QDRANT_SERVER_VERSION
        # The seeded file is not the real server, so the expectation it is
        # held to differs from its own hash: the digest comes from the pin
        # table, not from the manifest written beside the file.
        assert resolved.sha256 == QDRANT_EXECUTABLE_SHA256[asset_for_platform()]
        assert resolved.sha256 != file_sha256(binary)

    def test_resolves_an_install_made_from_the_gnu_asset_to_the_gnu_digest(
        self, isolated_status_dir: Path
    ) -> None:
        _ = isolated_status_dir
        version_dir = qdrant_bin_dir()
        _seed_verified_install(version_dir)
        manifest_path = version_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["asset"] = _GNU_ASSET
        manifest["asset_sha256"] = QDRANT_ASSET_SHA256[_GNU_ASSET]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        resolved = resolve_binary()

        assert resolved is not None
        assert resolved.sha256 == QDRANT_EXECUTABLE_SHA256[_GNU_ASSET]

    def test_an_install_made_from_a_local_archive_resolves_as_the_managed_install(
        self, isolated_status_dir: Path
    ) -> None:
        """An offline install is the pinned release, held to the same digest."""
        _ = isolated_status_dir
        version_dir = qdrant_bin_dir()
        _seed_verified_install(version_dir)
        manifest_path = version_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["source"] = "archive"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        resolved = resolve_binary()

        assert resolved is not None
        assert resolved.source is BinarySource.MANAGED_DOWNLOAD
        assert resolved.version == QDRANT_SERVER_VERSION
        assert resolved.sha256 == QDRANT_EXECUTABLE_SHA256[asset_for_platform()]

    def test_an_operator_claiming_install_does_not_resolve(
        self, isolated_status_dir: Path
    ) -> None:
        """It is refused at resolution, and is not a provisioned binary.

        Proven able to fail: returning such an install as resolved fails this
        on the missing ``QdrantBinaryError``.
        """
        _ = isolated_status_dir
        binary = _seed_operator_claiming_install(qdrant_bin_dir())

        with pytest.raises(QdrantBinaryError) as refused:
            resolve_binary()

        assert refused.value.error == "qdrant_install_invalid"
        assert str(refused.value) == operator_registration_refusal(binary)
        assert has_provisioned_binary() is False

    def test_an_operator_binary_is_held_to_its_declared_digest(
        self, isolated_status_dir: Path, tmp_path: Path
    ) -> None:
        """Path and digest together name the binary; it outranks the install.

        The version is unknown: the operator said which bytes, not which
        release. Proven able to fail: reporting the pinned version for every
        operator binary fails this on the empty-version assertion below.
        """
        _ = isolated_status_dir
        _seed_verified_install(qdrant_bin_dir())
        operator_binary = tmp_path / "env-qdrant.bin"
        operator_binary.write_bytes(b"env-binary")
        declared = file_sha256(operator_binary)

        # Upper case, as PowerShell prints it: the declared digest is compared
        # in the form the hash is computed in.
        with managed_env(**_operator_binary_env(operator_binary, declared.upper())):
            resolved = resolve_binary()

        assert resolved is not None
        assert resolved.path == operator_binary
        assert resolved.source is BinarySource.OPERATOR_SETTING
        assert resolved.source.operator_supplied
        assert resolved.sha256 == declared
        assert resolved.version == ""
        verify_resolved_binary(resolved)

    def test_an_operator_binary_declared_as_a_pinned_release_has_its_version(
        self, isolated_status_dir: Path, tmp_path: Path
    ) -> None:
        """A file that hashes to a pinned executable's digest is that release.

        Resolution does not hash, so the version is a claim until a spawn
        enforces the digest - and the stand-in here does not match it, so the
        same value that carries the version is refused when checked.
        """
        _ = isolated_status_dir
        operator_binary = tmp_path / "env-qdrant.bin"
        operator_binary.write_bytes(b"not the release")
        pinned = QDRANT_EXECUTABLE_SHA256[asset_for_platform()]

        with managed_env(**_operator_binary_env(operator_binary, pinned)):
            resolved = resolve_binary()

        assert resolved is not None
        assert resolved.source is BinarySource.OPERATOR_SETTING
        assert resolved.version == QDRANT_SERVER_VERSION
        with pytest.raises(QdrantBinaryError) as refused:
            verify_resolved_binary(resolved)
        assert refused.value.error == "qdrant_binary_unverified"

    def test_binary_without_manifest_is_not_provisioned(
        self, isolated_status_dir: Path
    ) -> None:
        _ = isolated_status_dir
        version_dir = qdrant_bin_dir()
        version_dir.mkdir(parents=True)
        (version_dir / binary_filename()).write_bytes(b"no-manifest")

        assert resolve_binary() is None

    def test_provisioned_versions_lists_seeded_install(
        self, isolated_status_dir: Path
    ) -> None:
        _ = isolated_status_dir
        _seed_verified_install(qdrant_bin_dir())

        versions = provisioned_versions()

        assert len(versions) == 1
        assert versions[0]["version"] == QDRANT_SERVER_VERSION
        assert versions[0]["current"] is True


class TestNoImplicitLookup:
    """The binary is never derived from ``PATH`` or the working directory."""

    def test_a_planted_qdrant_on_path_and_in_the_cwd_is_never_resolved(
        self,
        isolated_status_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A file a ``PATH`` lookup would find is not a resolution candidate.

        The plant is proven effective first: the standard lookup does return
        it, from the working directory and from ``PATH`` alike, so the final
        assertion is about resolution refusing it and not about a plant that
        missed. Proven able to fail: restoring a ``PATH`` lookup as a last
        tier fails this on the ``is None`` assertion below.
        """
        import shutil

        planted = isolated_status_dir / "planted"
        planted.mkdir()
        for name in ("qdrant", "qdrant.exe", "qdrant.cmd", "qdrant.bat"):
            candidate = planted / name
            candidate.write_bytes(b"planted")
            candidate.chmod(0o755)
        monkeypatch.chdir(planted)
        monkeypatch.setenv("PATH", f"{planted}{os.pathsep}{os.environ['PATH']}")
        found = shutil.which("qdrant")
        assert found is not None
        assert Path(found).resolve().parent == planted.resolve()

        assert resolve_binary() is None


class TestOperatorBinarySetting:
    """The operator settings name one exact file and digest, or resolution refuses."""

    #: A well-formed digest that is nobody's: these cases are refused before
    #: any file is hashed.
    _SOME_DIGEST = "c" * 64

    @staticmethod
    def _candidates(tmp_path: Path) -> dict[str, tuple[str, str]]:
        """Build every unusable shape; map a label to (setting, fault phrase)."""
        real = tmp_path / "real-qdrant.bin"
        real.write_bytes(b"operator-binary")
        (tmp_path / "relative-qdrant.bin").write_bytes(b"operator-binary")
        link = tmp_path / "linked-qdrant.bin"
        link.symlink_to(real)
        directory = tmp_path / "a-directory"
        directory.mkdir()
        return {
            "relative": ("relative-qdrant.bin", "is not an absolute path"),
            "link": (str(link), "is a symbolic link"),
            "directory": (str(directory), "is not an existing regular file"),
            "missing": (
                str(tmp_path / "does-not-exist"),
                "is not an existing regular file",
            ),
        }

    @pytest.mark.parametrize("shape", ["relative", "link", "directory", "missing"])
    def test_an_unusable_setting_is_refused_and_never_falls_through(
        self,
        shape: str,
        isolated_status_dir: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A named binary that cannot be used is an error, not a fallback.

        A managed install is present throughout, so a silent fall-through
        would return it and this would fail with no exception raised. The
        relative case runs with the working directory holding a real file of
        that name: the working directory must not be able to choose the
        binary. Each case asserts its own fault phrase, so one check standing
        in for another does not pass.

        Proven able to fail, one mutation per branch: returning ``None``
        instead of raising fails all four on the missing exception; dropping
        the absolute-path check fails ``relative``; dropping the link check
        fails ``link``; dropping the regular-file check fails ``directory``
        and ``missing``.
        """
        _ = isolated_status_dir
        _seed_verified_install(qdrant_bin_dir())
        setting, fault = self._candidates(tmp_path)[shape]
        monkeypatch.chdir(tmp_path)

        with (
            managed_env(**_operator_binary_env(setting, self._SOME_DIGEST)),
            pytest.raises(QdrantBinaryError) as refused,
        ):
            resolve_binary()

        assert refused.value.error == "qdrant_binary_invalid"
        assert fault in str(refused.value)
        assert EnvVar.QDRANT_BINARY.value in str(refused.value)

    def test_an_unusable_setting_stops_a_supervised_start(
        self, isolated_status_dir: Path, tmp_path: Path
    ) -> None:
        from ..qdrant_runtime._supervise import start_supervised_from_config

        _ = isolated_status_dir
        _seed_verified_install(qdrant_bin_dir())

        with (
            managed_env(
                **_operator_binary_env(tmp_path / "does-not-exist", self._SOME_DIGEST)
            ),
            pytest.raises(QdrantBinaryError) as refused,
        ):
            start_supervised_from_config()

        assert refused.value.error == "qdrant_binary_invalid"

    @pytest.mark.parametrize("missing_half", ["digest", "path"])
    def test_half_the_pair_is_refused_and_never_falls_through(
        self, missing_half: str, isolated_status_dir: Path, tmp_path: Path
    ) -> None:
        """A path with no digest, or a digest with no path, names no binary.

        The path names a real, usable file and a managed install is present,
        so both of the things a half pair could quietly become are available:
        the named file run with nothing to hold it to, or the managed install
        run in its place. Neither happens, and the refusal names both
        settings so the operator can see which one is missing.

        The settings layer refuses half a pair on its own; what resolution
        adds is that the refusal reaches a caller as the binary error every
        surface already renders, with its code. Proven able to fail: treating
        the settings refusal as "no operator binary" fails both cases, on the
        settings layer's own error escaping in place of the expected one.
        """
        _ = isolated_status_dir
        _seed_verified_install(qdrant_bin_dir())
        operator_binary = tmp_path / "operator-qdrant.bin"
        operator_binary.write_bytes(b"operator-binary")
        settings: dict[str, str | None] = {
            EnvVar.QDRANT_BINARY.value: str(operator_binary),
            EnvVar.QDRANT_BINARY_SHA256.value: file_sha256(operator_binary),
        }
        dropped = (
            EnvVar.QDRANT_BINARY_SHA256
            if missing_half == "digest"
            else EnvVar.QDRANT_BINARY
        )
        settings[dropped.value] = None

        with managed_env(**settings), pytest.raises(QdrantBinaryError) as refused:
            resolve_binary()

        assert refused.value.error == "qdrant_binary_invalid"
        assert EnvVar.QDRANT_BINARY.value in str(refused.value)
        assert EnvVar.QDRANT_BINARY_SHA256.value in str(refused.value)
        assert "must be set together" in str(refused.value)

    @pytest.mark.parametrize(
        ("label", "extra"),
        [
            ("a digest that is not a digest", {}),
            ("half a pair beside another bad setting", {EnvVar.PORT.value: "notaport"}),
        ],
    )
    def test_any_other_settings_refusal_stops_resolution_under_its_own_name(
        self,
        label: str,
        extra: dict[str, str],
        isolated_status_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Only the lone half pair is reported as a fault of the binary settings.

        A malformed digest, or a half pair among several unusable settings, is
        a refusal by the settings layer about more than the binary. It still
        stops resolution - no binary is returned, and the managed install
        present here is not reached - but it arrives as that layer's own
        error, so one bad port is never reported as a bad qdrant binary.

        Mutation it catches: catching every settings refusal where the lone
        half pair is caught. Both cases then arrive relabelled as a binary
        error, which is not the refusal expected here, and this fails on that
        error escaping.
        """
        _ = (isolated_status_dir, label)
        _seed_verified_install(qdrant_bin_dir())
        operator_binary = tmp_path / "operator-qdrant.bin"
        operator_binary.write_bytes(b"operator-binary")
        settings: dict[str, str | None] = {
            EnvVar.QDRANT_BINARY.value: str(operator_binary),
            EnvVar.QDRANT_BINARY_SHA256.value: None if extra else "not-a-digest",
            **extra,
        }

        with managed_env(**settings), pytest.raises(ValueError) as refused:
            resolve_binary()

        assert type(refused.value) is ValueError
        assert EnvVar.QDRANT_BINARY_SHA256.value in str(refused.value)


class TestConfigKnobs:
    def test_defaults(self) -> None:
        from ..config._settings import get_config

        cfg = get_config()
        assert cfg.qdrant_server is True
        assert cfg.qdrant_port == 8765
        assert cfg.qdrant_binary is None
        assert "qdrant-server" in str(cfg.qdrant_storage_dir)

    def test_env_overrides(self) -> None:
        from ..config._settings import get_config

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


class TestQdrantChildPath:
    """Extended-length path rendering for the qdrant child's environment."""

    def test_drive_path_gets_the_verbatim_prefix_on_windows(
        self, tmp_path: Path
    ) -> None:
        import sys

        from ..qdrant_runtime._supervise import _qdrant_child_path

        rendered = _qdrant_child_path(tmp_path / "storage")
        if sys.platform == "win32":
            assert rendered.startswith("\\\\?\\")
            assert rendered.endswith("storage")
            # Verbatim form must carry an absolute, resolved path.
            assert ":" in rendered
        else:
            assert rendered == str(tmp_path / "storage")

    def test_already_prefixed_path_is_unchanged(self) -> None:
        import sys

        from ..qdrant_runtime._supervise import _qdrant_child_path

        already = Path(r"\\?\C:\short\storage")
        rendered = _qdrant_child_path(already)
        if sys.platform == "win32":
            assert rendered == r"\\?\C:\short\storage"
        else:
            # Non-Windows platforms pass every path through untouched.
            assert rendered == str(already)

    def test_unc_path_gets_the_unc_verbatim_form(self) -> None:
        import sys

        from ..qdrant_runtime._supervise import _qdrant_child_path

        unc = Path(r"\\server\share\qdrant\storage")
        rendered = _qdrant_child_path(unc)
        if sys.platform == "win32":
            assert rendered.startswith(r"\\?\UNC\server\share")
        else:
            assert rendered == str(unc)
