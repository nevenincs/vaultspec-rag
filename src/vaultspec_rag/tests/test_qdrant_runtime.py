"""Unit tests for the qdrant_runtime package.

Exercises real logic only: asset resolution tables, real SHA256
verification against real archives built on disk, real provisioning
state machines against a temp-isolated managed dir, and the
pin-vs-lockfile guard parsed from the repository's actual ``uv.lock``.
No network I/O happens anywhere in this module, so nothing here holds the
pinned release: what is seeded at the managed install's name is a stand-in
that resolution refuses, and the download leg has its own module.
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
    ResolvedBinary,
)
from ..qdrant_runtime._managed_install import (
    InstallState,
    ManagedInstall,
    classify_managed_binary,
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
    _managed_binary,
    asset_for_platform,
    binary_filename,
    has_provisioned_binary,
    qdrant_bin_dir,
    resolve_binary,
)
from ..qdrant_runtime._spawn_trust import verify_resolved_binary
from ._config_fixtures import reset_config
from ._fake_qdrant_binary import unreadable
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


#: The code each verdict that may not run is refused under.
_REFUSED_UNDER = {
    InstallState.REFUSED: "qdrant_binary_unverified",
    InstallState.UNREADABLE: "qdrant_binary_busy",
    InstallState.OBSTRUCTED: "qdrant_install_invalid",
}


class TestManagedInstallVerdict:
    """What resolution makes of each verdict on the installed name.

    No stand-in hashes to a committed digest, so a healthy verdict cannot be
    produced from a file here. The verdicts are built directly; the tests of
    the classifier produce each of them from real files, and the tests below
    this class reach every unhealthy one through a real resolution.
    """

    @pytest.mark.parametrize("asset", sorted(QDRANT_EXECUTABLE_SHA256))
    def test_a_healthy_install_resolves_held_to_the_digest_it_matched(
        self, asset: str, tmp_path: Path
    ) -> None:
        """The digest carried to every spawn is the committed one it matched.

        Run for every pinned asset, including the one no platform selects: an
        install made from it stays the pinned release.

        Mutation it catches: carrying the digest of the asset the running
        platform selects. Every other asset then fails on the equality below.
        """
        binary = tmp_path / binary_filename()
        committed = QDRANT_EXECUTABLE_SHA256[asset]

        resolved = _managed_binary(
            ManagedInstall(InstallState.HEALTHY, binary, asset=asset, sha256=committed)
        )

        assert resolved == ResolvedBinary(
            path=binary,
            source=BinarySource.MANAGED_DOWNLOAD,
            version=QDRANT_SERVER_VERSION,
            sha256=committed,
        )

    def test_an_absent_install_resolves_to_nothing(self, tmp_path: Path) -> None:
        absent = ManagedInstall(InstallState.ABSENT, tmp_path / binary_filename())

        assert _managed_binary(absent) is None

    @pytest.mark.parametrize("state", sorted(_REFUSED_UNDER))
    def test_an_unhealthy_install_is_refused_in_the_verdicts_own_words(
        self, state: InstallState, tmp_path: Path
    ) -> None:
        """Each state has its own code, and the sentence is not rewritten.

        Mutation it catches: dropping a state from the table of codes. That
        state then resolves to nothing, as if no install were there, and this
        fails on the missing ``QdrantBinaryError``.
        """
        verdict = ManagedInstall(
            state, tmp_path / binary_filename(), refusal=f"the {state} sentence"
        )

        with pytest.raises(QdrantBinaryError) as refused:
            _managed_binary(verdict)

        assert refused.value.error == _REFUSED_UNDER[state]
        assert str(refused.value) == verdict.refusal

    def test_no_verdict_is_left_without_an_outcome(self) -> None:
        """A state added to the classifier has to be given one here."""
        assert set(InstallState) == {
            InstallState.HEALTHY,
            InstallState.ABSENT,
            *_REFUSED_UNDER,
        }


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


#: What a manifest beside the installed name can say. ``download`` and
#: ``archive`` are what a provisioning run writes and ``operator`` is what an
#: operator registration used to: each names the pinned version and records
#: the digest the file really has. Nothing here is read to reach a verdict.
_MANIFEST_KINDS = ("absent", "bare", "download", "archive", "operator")


def _seed_stand_in(version_dir: Path, manifest: str = "download") -> Path:
    """Put a file that is not the pinned release at the installed name.

    The manifest beside it is as favourable as one can be made: it agrees
    with the file in every respect, which is exactly what anyone able to
    write the directory can arrange.
    """
    version_dir.mkdir(parents=True, exist_ok=True)
    binary = version_dir / binary_filename()
    binary.write_bytes(b"a stand-in for the release, " + manifest.encode())
    if manifest == "absent":
        return binary
    recorded: dict[str, object] = {"version": QDRANT_SERVER_VERSION}
    if manifest != "bare":
        asset = "" if manifest == "operator" else asset_for_platform()
        recorded.update(
            asset=asset,
            asset_sha256=QDRANT_ASSET_SHA256.get(asset, ""),
            binary_sha256=file_sha256(binary),
            source=manifest,
            provisioned_at="2026-06-12T00:00:00+00:00",
        )
    (version_dir / "manifest.json").write_text(json.dumps(recorded), encoding="utf-8")
    return binary


class TestPreExecDigestGuard:
    """A binary that does not verify is refused by a real start."""

    @staticmethod
    def _refused_start() -> QdrantBinaryError:
        from ..qdrant_runtime._supervise import start_supervised_from_config

        with (
            managed_env(**{EnvVar.QDRANT_SERVER.value: "1"}),
            pytest.raises(QdrantBinaryError) as refused,
        ):
            start_supervised_from_config()
        return refused.value

    @pytest.mark.parametrize("manifest", _MANIFEST_KINDS)
    def test_a_file_that_is_not_the_pinned_release_never_starts(
        self, manifest: str, isolated_status_dir: Path
    ) -> None:
        """What the manifest says, or lacks, does not let the file run.

        Where a manifest records a digest it is the file's true one, so a
        check against the manifest passes in every such case. Only the
        committed digests refuse it, and the refusal names what the file is
        and every way to replace it.

        Mutation it catches: resolving the file held to its own digest, as a
        manifest that vouches for its binary would have it. The start then
        goes on to execute the stand-in, which is not a program, and every
        case fails on an ``OSError`` in place of the refusal.
        """
        _ = isolated_status_dir
        binary = _seed_stand_in(qdrant_bin_dir(), manifest)

        refused = self._refused_start()

        assert refused.error == "qdrant_binary_unverified"
        message = str(refused)
        assert str(binary) in message
        assert file_sha256(binary) in message
        assert "vaultspec-rag server qdrant install --upgrade" in message
        assert "--archive <file>" in message
        assert EnvVar.QDRANT_BINARY.value in message
        assert EnvVar.QDRANT_BINARY_SHA256.value in message

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


class TestResolution:
    def test_an_empty_version_directory_resolves_to_nothing(
        self, isolated_status_dir: Path
    ) -> None:
        _ = isolated_status_dir
        qdrant_bin_dir().mkdir(parents=True)

        assert resolve_binary() is None
        assert has_provisioned_binary() is False

    @pytest.mark.parametrize("manifest", _MANIFEST_KINDS)
    def test_a_stand_in_is_refused_at_resolution_whatever_its_manifest_says(
        self, manifest: str, isolated_status_dir: Path
    ) -> None:
        """It does not resolve, it is not an install, and the words are shared.

        The sentence is the one the shared verdict on the same file carries,
        so a start and a status read cannot describe one directory two ways.

        Mutation it catches: treating a file with no manifest beside it as no
        install at all. The ``absent`` case then resolves to nothing and fails
        on the missing ``QdrantBinaryError``.
        """
        _ = isolated_status_dir
        binary = _seed_stand_in(qdrant_bin_dir(), manifest)

        with pytest.raises(QdrantBinaryError) as refused:
            resolve_binary()

        assert refused.value.error == "qdrant_binary_unverified"
        assert str(refused.value) == classify_managed_binary(binary).refusal
        assert str(binary) in str(refused.value)
        assert has_provisioned_binary() is False

    def test_a_directory_at_the_installed_name_is_refused_as_an_invalid_install(
        self, isolated_status_dir: Path
    ) -> None:
        """Nothing can be installed over it, so the remedy is to remove it."""
        _ = isolated_status_dir
        obstruction = qdrant_bin_dir() / binary_filename()
        obstruction.mkdir(parents=True)

        with pytest.raises(QdrantBinaryError) as refused:
            resolve_binary()

        assert refused.value.error == "qdrant_install_invalid"
        assert str(obstruction) in str(refused.value)
        assert "Remove it" in str(refused.value)
        assert "--upgrade" not in str(refused.value)
        assert has_provisioned_binary() is False

    def test_an_install_that_cannot_be_read_is_busy_and_not_a_failed_digest(
        self, isolated_status_dir: Path
    ) -> None:
        """Nothing is known about a file that was never read.

        The same file is refused twice: while it cannot be read, as busy with
        nothing said about replacing it, and once it can, for what it holds.

        Mutation it catches: refusing an unreadable install under the code of
        a failed digest. This fails on the first code assertion below.
        """
        _ = isolated_status_dir
        binary = _seed_stand_in(qdrant_bin_dir())

        with unreadable(binary), pytest.raises(QdrantBinaryError) as busy:
            resolve_binary()
        with pytest.raises(QdrantBinaryError) as refused:
            resolve_binary()

        assert busy.value.error == "qdrant_binary_busy"
        assert "Close whatever holds it" in str(busy.value)
        assert "--upgrade" not in str(busy.value)
        assert refused.value.error == "qdrant_binary_unverified"

    def test_an_operator_binary_is_held_to_its_declared_digest(
        self, isolated_status_dir: Path, tmp_path: Path
    ) -> None:
        """Path and digest together name the binary; it outranks the install.

        What sits at the managed install's name here would be refused if it
        were consulted, so resolving at all shows it was not.

        The version is unknown: the operator said which bytes, not which
        release. Proven able to fail: reporting the pinned version for every
        operator binary fails this on the empty-version assertion below.
        """
        _ = isolated_status_dir
        _seed_stand_in(qdrant_bin_dir())
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

    def test_provisioned_versions_lists_seeded_install(
        self, isolated_status_dir: Path
    ) -> None:
        _ = isolated_status_dir
        _seed_stand_in(qdrant_bin_dir())

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

        A file sits at the managed install's name throughout, so a silent
        fall-through would go on to judge it and refuse under another code.
        The relative case runs with the working directory holding a real file
        of that name: the working directory must not be able to choose the
        binary. Each case asserts its own fault phrase, so one check standing
        in for another does not pass.

        Proven able to fail, one mutation per branch: returning ``None``
        instead of raising fails all four on the code assertion, with the
        managed install's refusal in its place; dropping the absolute-path
        check fails ``relative``; dropping the link check fails ``link``;
        dropping the regular-file check fails ``directory`` and ``missing``.
        """
        _ = isolated_status_dir
        _seed_stand_in(qdrant_bin_dir())
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
        _seed_stand_in(qdrant_bin_dir())

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

        The path names a real, usable file and a file sits at the managed
        install's name, so both of the things a half pair could quietly become
        are available: the named file run with nothing to hold it to, or the
        managed install consulted in its place. Neither happens, and the
        refusal names both settings so the operator can see which one is
        missing.

        The settings layer refuses half a pair on its own; what resolution
        adds is that the refusal reaches a caller as the binary error every
        surface already renders, with its code. Proven able to fail: treating
        the settings refusal as "no operator binary" fails both cases, on the
        settings layer's own error escaping in place of the expected one.
        """
        _ = isolated_status_dir
        _seed_stand_in(qdrant_bin_dir())
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
        _seed_stand_in(qdrant_bin_dir())
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
