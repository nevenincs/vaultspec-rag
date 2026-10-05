"""The staged, atomic install of the managed Qdrant binary.

An install is built beside its destination and moved into place in one step,
so every stage before that move can fail without touching what was installed
before. These tests drive the shipped install against real archives served
over real loopback HTTPS into a temp-isolated managed dir, and assert on the
bytes left on disk: a previous install after each kind of failure, and the
absence of any working file afterwards.

The pins are arguments of the install request, so a stand-in archive is held
to its own digests exactly as a release is held to the committed ones. No
check is relaxed for the stand-in: it only has different expected values.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import sys
import tarfile
import zipfile
from dataclasses import replace
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from .._sync_vocabulary import ProvisionAction
from ..config._types import EnvVar
from ..qdrant_runtime._constants import (
    MANIFEST_FILENAME,
    QDRANT_ASSET_SHA256,
    QDRANT_SERVER_VERSION,
)
from ..qdrant_runtime._provision import (
    _download_and_install,
    _DownloadInstallRequest,
    extract_verified_archive,
    file_sha256,
    provision,
)
from ..qdrant_runtime._resolve import (
    asset_for_platform,
    binary_filename,
    qdrant_bin_dir,
)
from ._loopback_tls import (
    LOOPBACK_HOST,
    LoopbackSources,
    StandInSource,
    send_bytes,
    trusted_loopback_sources,
)
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_NEW_EXECUTABLE = b"\x7fnew stand-in server\x00" * 512
_PRIOR_EXECUTABLE = b"prior install, still runnable"
_PRIOR_MANIFEST = json.dumps({"version": QDRANT_SERVER_VERSION, "note": "prior"})

#: The two archive shapes upstream publishes, exercised on every platform.
_ARCHIVE_SHAPES = ("stand-in-asset.zip", "stand-in-asset.tar.gz")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _archive(asset: str, members: dict[str, bytes]) -> bytes:
    """Build a release-shaped archive holding *members*, in *asset*'s format."""
    buffer = io.BytesIO()
    if asset.endswith(".zip"):
        with zipfile.ZipFile(buffer, "w") as zf:
            for name, payload in members.items():
                zf.writestr(name, payload)
    else:
        with tarfile.open(fileobj=buffer, mode="w:gz") as tf:
            for name, payload in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                info.mode = 0o755
                tf.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def _release(asset: str, executable: bytes = _NEW_EXECUTABLE) -> bytes:
    """An archive laid out as a release is: the executable under a directory."""
    return _archive(asset, {f"release/{binary_filename()}": executable})


@pytest.fixture
def sources(tmp_path: Path) -> Generator[LoopbackSources]:
    with trusted_loopback_sources(tmp_path / "tls") as started:
        yield started


@pytest.fixture
def version_dir(isolated_singleton_dirs: Path) -> Path:
    """The managed version dir, relocated under the test's temp dir."""
    del isolated_singleton_dirs
    return qdrant_bin_dir()


def _seed_prior_install(version_dir: Path) -> Path:
    """Put a previous install in place and return its executable."""
    version_dir.mkdir(parents=True, exist_ok=True)
    binary = version_dir / binary_filename()
    binary.write_bytes(_PRIOR_EXECUTABLE)
    (version_dir / MANIFEST_FILENAME).write_text(_PRIOR_MANIFEST, encoding="utf-8")
    return binary


def _assert_prior_install_intact(version_dir: Path) -> None:
    """The previous executable and manifest are byte-for-byte what was seeded."""
    binary = version_dir / binary_filename()
    assert binary.is_file(), "the previous executable was removed"
    assert binary.read_bytes() == _PRIOR_EXECUTABLE
    manifest = (version_dir / MANIFEST_FILENAME).read_text(encoding="utf-8")
    assert manifest == _PRIOR_MANIFEST


def _working_files(version_dir: Path) -> list[str]:
    """Every file in *version_dir* other than an install's own two."""
    keep = {binary_filename(), MANIFEST_FILENAME}
    return sorted(p.name for p in version_dir.iterdir() if p.name not in keep)


def _request(
    source: StandInSource,
    version_dir: Path,
    *,
    asset: str,
    pinned_archive: bytes,
) -> _DownloadInstallRequest:
    """A first-install request pinned to *pinned_archive* and the new executable.

    A test that needs another pin, or a request that replaces an install,
    derives it from this one, so the difference it is about stays visible.
    """
    return _DownloadInstallRequest(
        url=source.url(f"/{asset}"),
        redirect_hosts=frozenset({LOOPBACK_HOST}),
        asset=asset,
        archive_sha256=_sha256(pinned_archive),
        executable_sha256=_sha256(_NEW_EXECUTABLE),
        version_dir=version_dir,
        previously="absent",
    )


class TestVerifiedInstall:
    @pytest.mark.parametrize("asset", _ARCHIVE_SHAPES)
    def test_a_verified_download_is_installed_and_recorded(
        self, sources: LoopbackSources, version_dir: Path, asset: str
    ) -> None:
        archive = _release(asset)
        source = sources.serve(lambda handler: send_bytes(handler, archive))

        report = _download_and_install(
            _request(source, version_dir, asset=asset, pinned_archive=archive)
        )

        assert report.action == ProvisionAction.CREATED, report.message
        binary = version_dir / binary_filename()
        assert report.binary == binary
        assert binary.read_bytes() == _NEW_EXECUTABLE
        manifest = json.loads(
            (version_dir / MANIFEST_FILENAME).read_text(encoding="utf-8")
        )
        assert manifest["version"] == QDRANT_SERVER_VERSION
        assert manifest["asset"] == asset
        assert manifest["asset_sha256"] == _sha256(archive)
        assert manifest["binary_sha256"] == _sha256(_NEW_EXECUTABLE)
        assert manifest["source"] == "download"
        assert _working_files(version_dir) == []
        if sys.platform != "win32":
            assert stat.S_IMODE(binary.stat().st_mode) == 0o700

    def test_a_verified_download_replaces_a_previous_install(
        self, sources: LoopbackSources, version_dir: Path
    ) -> None:
        asset = _ARCHIVE_SHAPES[0]
        _seed_prior_install(version_dir)
        archive = _release(asset)
        source = sources.serve(lambda handler: send_bytes(handler, archive))

        request = _request(source, version_dir, asset=asset, pinned_archive=archive)
        report = _download_and_install(replace(request, previously="stale"))

        assert report.action == ProvisionAction.UPDATED, report.message
        assert (version_dir / binary_filename()).read_bytes() == _NEW_EXECUTABLE
        assert _working_files(version_dir) == []


class TestFailureLeavesThePreviousInstall:
    """No failure before the final move may touch what was installed before."""

    def test_a_failed_download(
        self, sources: LoopbackSources, version_dir: Path
    ) -> None:
        """The source refusing the asset costs the operator nothing installed.

        Mutation: made the failure branch of ``_download_and_install`` remove
        the installed executable, as the handler it replaces did. Observed
        "the previous executable was removed". Restored; passes.
        """
        asset = _ARCHIVE_SHAPES[0]
        _seed_prior_install(version_dir)
        source = sources.serve(
            lambda handler: send_bytes(
                handler, b"no such asset", status=HTTPStatus.NOT_FOUND
            )
        )

        report = _download_and_install(
            _request(source, version_dir, asset=asset, pinned_archive=_release(asset))
        )

        assert report.action == ProvisionAction.FAILED
        assert "404" in report.message
        _assert_prior_install_intact(version_dir)
        assert _working_files(version_dir) == []

    def test_an_archive_that_fails_its_digest(
        self, sources: LoopbackSources, version_dir: Path
    ) -> None:
        """A replaced asset is refused before anything is extracted from it.

        The served archive holds the very executable the request pins, beside
        one extra member, so only the archive digest stands between it and an
        install: the executable digest alone would accept it.

        Mutation: skipped the archive digest comparison in
        ``_stage_verified_executable``. Observed the action assertion fail
        (``updated`` where ``failed`` was required). Restored; passes.
        """
        asset = _ARCHIVE_SHAPES[0]
        _seed_prior_install(version_dir)
        served = _archive(
            asset,
            {binary_filename(): _NEW_EXECUTABLE, "NOTICE": b"not in the pinned asset"},
        )
        source = sources.serve(lambda handler: send_bytes(handler, served))

        request = _request(
            source, version_dir, asset=asset, pinned_archive=_release(asset)
        )
        report = _download_and_install(replace(request, previously="stale"))

        assert report.action == ProvisionAction.FAILED
        assert "SHA256 mismatch" in report.message
        assert "may have been replaced" in report.message
        # A digest mismatch is a verdict on the bytes; asking again cannot
        # change them.
        assert len(source.requests) == 1
        _assert_prior_install_intact(version_dir)
        assert _working_files(version_dir) == []

    @pytest.mark.parametrize("asset", _ARCHIVE_SHAPES)
    @pytest.mark.parametrize(
        "members",
        [
            {"README": b"no executable here"},
            {
                f"first/{binary_filename()}": b"one",
                f"second/{binary_filename()}": b"two",
            },
        ],
        ids=["no executable member", "two executable members"],
    )
    def test_an_archive_that_cannot_be_extracted(
        self,
        sources: LoopbackSources,
        version_dir: Path,
        asset: str,
        members: dict[str, bytes],
    ) -> None:
        archive = _archive(asset, members)
        _seed_prior_install(version_dir)
        source = sources.serve(lambda handler: send_bytes(handler, archive))

        report = _download_and_install(
            _request(source, version_dir, asset=asset, pinned_archive=archive)
        )

        assert report.action == ProvisionAction.FAILED
        assert "requires one regular" in report.message
        _assert_prior_install_intact(version_dir)
        assert _working_files(version_dir) == []

    @pytest.mark.parametrize("asset", _ARCHIVE_SHAPES)
    def test_bytes_that_are_not_an_archive(
        self, sources: LoopbackSources, version_dir: Path, asset: str
    ) -> None:
        garbage = b"neither a zip nor a gzip stream" * 64
        _seed_prior_install(version_dir)
        source = sources.serve(lambda handler: send_bytes(handler, garbage))

        report = _download_and_install(
            _request(source, version_dir, asset=asset, pinned_archive=garbage)
        )

        assert report.action == ProvisionAction.FAILED
        _assert_prior_install_intact(version_dir)
        assert _working_files(version_dir) == []

    def test_an_executable_that_fails_its_digest(
        self, sources: LoopbackSources, version_dir: Path
    ) -> None:
        """The staged executable is checked before it replaces anything.

        The archive passes its own digest, so this is the executable pin
        acting alone, and it must act while the candidate is still a staging
        file.

        Mutation: removed the executable digest comparison in
        ``_stage_verified_executable``. Observed the action assertion fail
        (``updated`` where ``failed`` was required). Restored; passes.
        """
        asset = _ARCHIVE_SHAPES[0]
        _seed_prior_install(version_dir)
        archive = _release(asset)
        source = sources.serve(lambda handler: send_bytes(handler, archive))

        request = _request(source, version_dir, asset=asset, pinned_archive=archive)
        report = _download_and_install(
            replace(
                request,
                executable_sha256=_sha256(b"what the pin table says it should be"),
                previously="stale",
            )
        )

        assert report.action == ProvisionAction.FAILED
        assert "SHA256 mismatch" in report.message
        assert binary_filename() in report.message
        _assert_prior_install_intact(version_dir)
        assert _working_files(version_dir) == []

    def test_a_failure_with_nothing_installed_leaves_nothing(
        self, sources: LoopbackSources, version_dir: Path
    ) -> None:
        asset = _ARCHIVE_SHAPES[0]
        archive = _release(asset)
        source = sources.serve(lambda handler: send_bytes(handler, archive))

        request = _request(source, version_dir, asset=asset, pinned_archive=archive)
        report = _download_and_install(
            replace(request, executable_sha256=_sha256(b"something else"))
        )

        assert report.action == ProvisionAction.FAILED
        assert list(version_dir.iterdir()) == []


class TestInterrupt:
    @pytest.mark.parametrize(
        "stage",
        [
            "Downloading the Qdrant server (",
            "Extracting the Qdrant server",
            "Verifying the extracted Qdrant server",
        ],
    )
    def test_an_interrupt_strands_nothing_and_keeps_the_previous_install(
        self, sources: LoopbackSources, version_dir: Path, stage: str
    ) -> None:
        """Ctrl-C at any stage removes the working files and nothing else.

        The interrupt is raised from the caller's own progress sink, which is
        where a console delivers one, at a stage each parameter names. By the
        last of them both staging files exist.

        Mutation: moved the staging cleanup in ``_download_and_install`` out
        of ``finally`` and into the failure branch. Observed the working-file
        assertion fail at every stage, listing the staging files left behind.
        Restored; passes.
        """
        asset = _ARCHIVE_SHAPES[0]
        _seed_prior_install(version_dir)
        archive = _release(asset)
        source = sources.serve(lambda handler: send_bytes(handler, archive))

        def interrupt_at_stage(line: str) -> None:
            if line.startswith(stage):
                raise KeyboardInterrupt

        request = replace(
            _request(source, version_dir, asset=asset, pinned_archive=archive),
            on_progress=interrupt_at_stage,
        )
        with pytest.raises(KeyboardInterrupt):
            _download_and_install(request)

        _assert_prior_install_intact(version_dir)
        assert _working_files(version_dir) == []


class TestInstalledName:
    def test_a_link_at_the_installed_name_is_replaced_not_written_through(
        self, sources: LoopbackSources, version_dir: Path, tmp_path: Path
    ) -> None:
        asset = _ARCHIVE_SHAPES[0]
        outside = tmp_path / "outside-the-managed-dir.bin"
        outside.write_bytes(b"must not be overwritten")
        version_dir.mkdir(parents=True)
        binary = version_dir / binary_filename()
        try:
            os.symlink(outside, binary)
        except OSError:
            pytest.fail("Cannot create symlink - test requires symlink support")
        archive = _release(asset)
        source = sources.serve(lambda handler: send_bytes(handler, archive))

        report = _download_and_install(
            _request(source, version_dir, asset=asset, pinned_archive=archive)
        )

        assert report.action == ProvisionAction.CREATED, report.message
        assert outside.read_bytes() == b"must not be overwritten"
        assert not binary.is_symlink()
        assert binary.read_bytes() == _NEW_EXECUTABLE

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="only Windows refuses to replace a file a process holds open",
    )
    def test_an_executable_in_use_is_a_failed_outcome_naming_the_remedy(
        self, sources: LoopbackSources, version_dir: Path
    ) -> None:
        """A server still running from the install is reported, not raised.

        The executable is held open without delete sharing, which is the hold
        a running image places on its file.

        Mutation: removed the translation of the refused replace in
        ``_replace_executable``. Observed the message assertion fail on the
        bare access-denied text. Restored; passes.
        """
        asset = _ARCHIVE_SHAPES[0]
        binary = _seed_prior_install(version_dir)
        archive = _release(asset)
        source = sources.serve(lambda handler: send_bytes(handler, archive))

        request = _request(source, version_dir, asset=asset, pinned_archive=archive)
        with binary.open("rb"):
            report = _download_and_install(replace(request, previously="stale"))

        assert report.action == ProvisionAction.FAILED
        assert "vaultspec-rag server stop" in report.message
        _assert_prior_install_intact(version_dir)
        assert _working_files(version_dir) == []


class TestOperatorRegistration:
    def test_a_registration_replaces_a_previous_install_and_strands_nothing(
        self, version_dir: Path, tmp_path: Path
    ) -> None:
        _seed_prior_install(version_dir)
        operator_binary = tmp_path / "operator-qdrant.bin"
        operator_binary.write_bytes(b"operator-supplied server")

        report = provision(binary=operator_binary)

        assert report.action == ProvisionAction.UPDATED, report.message
        binary = version_dir / binary_filename()
        assert binary.read_bytes() == b"operator-supplied server"
        manifest = json.loads(
            (version_dir / MANIFEST_FILENAME).read_text(encoding="utf-8")
        )
        assert manifest["source"] == "operator"
        assert manifest["binary_sha256"] == file_sha256(binary)
        assert report.sha256 == manifest["binary_sha256"]
        assert _working_files(version_dir) == []

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="only Windows refuses to replace a file a process holds open",
    )
    def test_registering_over_an_executable_in_use_is_a_failed_outcome(
        self, version_dir: Path, tmp_path: Path
    ) -> None:
        binary = _seed_prior_install(version_dir)
        operator_binary = tmp_path / "operator-qdrant.bin"
        operator_binary.write_bytes(b"operator-supplied server")

        with binary.open("rb"):
            report = provision(binary=operator_binary)

        assert report.action == ProvisionAction.FAILED
        assert "vaultspec-rag server stop" in report.message
        _assert_prior_install_intact(version_dir)
        assert _working_files(version_dir) == []


class TestArchiveExtraction:
    @pytest.mark.parametrize("asset", _ARCHIVE_SHAPES)
    def test_both_archive_shapes_extract_by_basename(
        self, tmp_path: Path, asset: str
    ) -> None:
        archive = tmp_path / asset
        archive.write_bytes(_release(asset))
        dest = tmp_path / "out"
        dest.mkdir()

        binary, digest = extract_verified_archive(archive, file_sha256(archive), dest)

        assert binary == dest / binary_filename()
        assert binary.read_bytes() == _NEW_EXECUTABLE
        assert digest == _sha256(_NEW_EXECUTABLE)


_STAND_IN_EXECUTABLE = b"stand-in bytes that are not the release executable"
_OPERATOR_EXECUTABLE = b"operator-supplied server"


def _asset_path() -> str:
    """Where a stand-in mirror is asked for this platform's pinned asset."""
    return f"/mirror/v{QDRANT_SERVER_VERSION}/{asset_for_platform()}"


def _mirror(sources: LoopbackSources) -> StandInSource:
    """A mirror that answers every request with bytes that are not a release."""
    return sources.serve(lambda handler: send_bytes(handler, b"not the release"))


def _write_install(version_dir: Path, manifest: dict[str, str] | None) -> bytes:
    """Place stand-in bytes at the installed name, beside *manifest* if given."""
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / binary_filename()).write_bytes(_STAND_IN_EXECUTABLE)
    if manifest is not None:
        (version_dir / MANIFEST_FILENAME).write_text(
            json.dumps(manifest), encoding="utf-8"
        )
    return _STAND_IN_EXECUTABLE


def _seed_self_attested_download(version_dir: Path, tmp_path: Path) -> bytes:
    """A download manifest that vouches for bytes the release never held.

    Every field agrees with the pin table and the recorded executable digest
    is the true digest of the file beside it, so nothing in the directory
    disagrees with anything else in it. Only the committed executable digest
    shows the file is not the release.
    """
    del tmp_path
    asset = asset_for_platform()
    return _write_install(
        version_dir,
        {
            "version": QDRANT_SERVER_VERSION,
            "asset": asset,
            "asset_sha256": QDRANT_ASSET_SHA256[asset],
            "binary_sha256": _sha256(_STAND_IN_EXECUTABLE),
            "source": "download",
        },
    )


def _seed_version_only_manifest(version_dir: Path, tmp_path: Path) -> bytes:
    del tmp_path
    return _write_install(version_dir, {"version": QDRANT_SERVER_VERSION})


def _seed_no_manifest(version_dir: Path, tmp_path: Path) -> bytes:
    del tmp_path
    return _write_install(version_dir, None)


def _seed_registered(version_dir: Path, tmp_path: Path) -> bytes:
    """Register an operator binary through the shipped registration."""
    operator_binary = tmp_path / "operator-qdrant.bin"
    operator_binary.write_bytes(_OPERATOR_EXECUTABLE)
    report = provision(binary=operator_binary)
    assert report.action == ProvisionAction.CREATED, report.message
    assert report.binary == version_dir / binary_filename()
    return _OPERATOR_EXECUTABLE


def _seed_registered_then_replaced(version_dir: Path, tmp_path: Path) -> bytes:
    _seed_registered(version_dir, tmp_path)
    replaced = b"swapped in after registration"
    (version_dir / binary_filename()).write_bytes(replaced)
    return replaced


#: Installs no committed or recorded digest vouches for, by how they got so.
_UNVERIFIED_SEEDS: dict[str, Callable[[Path, Path], bytes]] = {
    "download manifest over other bytes": _seed_self_attested_download,
    "manifest with only a version": _seed_version_only_manifest,
    "no manifest": _seed_no_manifest,
    "registered, then replaced": _seed_registered_then_replaced,
}


class TestInstallState:
    """An install is called healthy only when its executable hashes right."""

    def test_a_registered_install_is_unchanged_with_no_network(
        self, sources: LoopbackSources, version_dir: Path, tmp_path: Path
    ) -> None:
        """An operator-registered install is a healthy state of its own.

        It carries no committed pin, so it is not called verified, and it
        matches the digest recorded at registration, so it is not called
        stale: a plain run leaves it alone.

        Mutation: classed a registered install with the unverified ones in
        ``_settled_report``. Observed the action assertion fail (``failed``
        where ``unchanged`` was required). Restored; passes.
        """
        _seed_registered(version_dir, tmp_path)
        binary = version_dir / binary_filename()
        before = binary.stat().st_mtime_ns
        mirror = _mirror(sources)

        with managed_env(
            **{EnvVar.QDRANT_RELEASE_BASE_URL.value: mirror.url("/mirror")}
        ):
            report = provision()

        assert report.action == ProvisionAction.UNCHANGED, report.message
        assert "operator-registered" in report.message
        assert report.sha256 == _sha256(_OPERATOR_EXECUTABLE)
        assert mirror.requests == []
        assert binary.stat().st_mtime_ns == before

    @pytest.mark.parametrize("seed", _UNVERIFIED_SEEDS.values(), ids=_UNVERIFIED_SEEDS)
    def test_an_install_that_does_not_verify_fails_and_names_the_upgrade(
        self,
        sources: LoopbackSources,
        version_dir: Path,
        tmp_path: Path,
        seed: Callable[[Path, Path], bytes],
    ) -> None:
        """A plain run neither trusts nor overwrites an unverified executable.

        The first seed is the one a manifest-only check cannot see: its
        manifest agrees with the pin table and with the file beside it.

        Mutation: made ``_existing_install`` skip hashing the executable.
        Observed the first and last seeds fail on the action (``unchanged``
        where ``failed`` was required); the other two carry no digest to
        compare and stayed refused. Restored; passes.
        """
        installed = seed(version_dir, tmp_path)
        mirror = _mirror(sources)

        with managed_env(
            **{EnvVar.QDRANT_RELEASE_BASE_URL.value: mirror.url("/mirror")}
        ):
            report = provision()

        assert report.action == ProvisionAction.FAILED
        assert "--upgrade" in report.message
        assert mirror.requests == []
        assert (version_dir / binary_filename()).read_bytes() == installed

    @pytest.mark.parametrize("seed", _UNVERIFIED_SEEDS.values(), ids=_UNVERIFIED_SEEDS)
    def test_an_upgrade_re_downloads_an_install_that_does_not_verify(
        self,
        sources: LoopbackSources,
        version_dir: Path,
        tmp_path: Path,
        seed: Callable[[Path, Path], bytes],
    ) -> None:
        """The remedy a failed start names reaches the download.

        The stand-in mirror cannot serve the pinned release, so the run then
        stops on the committed archive digest and must leave the executable
        it found exactly as it was. The other half of the repair - a verified
        download replacing a previous executable - is proven at the install
        itself, against an archive held to its own digests.

        Mutation: made ``_existing_install`` skip hashing the executable.
        Observed the first seed fail on the request log (``[]`` where the
        asset path was required): the upgrade did nothing. Restored; passes.
        """
        installed = seed(version_dir, tmp_path)
        mirror = _mirror(sources)

        with managed_env(
            **{EnvVar.QDRANT_RELEASE_BASE_URL.value: mirror.url("/mirror")}
        ):
            report = provision(upgrade=True)

        assert mirror.requests == [_asset_path()]
        assert report.action == ProvisionAction.FAILED
        assert "SHA256 mismatch" in report.message
        assert (version_dir / binary_filename()).read_bytes() == installed
        assert _working_files(version_dir) == []

    def test_an_upgrade_replaces_a_registered_install_with_the_pinned_release(
        self, sources: LoopbackSources, version_dir: Path, tmp_path: Path
    ) -> None:
        installed = _seed_registered(version_dir, tmp_path)
        mirror = _mirror(sources)

        with managed_env(
            **{EnvVar.QDRANT_RELEASE_BASE_URL.value: mirror.url("/mirror")}
        ):
            attempted = provision(upgrade=True)
            afterwards = provision()

        assert mirror.requests == [_asset_path()]
        assert attempted.action == ProvisionAction.FAILED
        # The download could not be verified, so the registered install is
        # still there and still healthy.
        assert (version_dir / binary_filename()).read_bytes() == installed
        assert afterwards.action == ProvisionAction.UNCHANGED

    @pytest.mark.parametrize(
        ("field", "value", "problem"),
        [
            ("asset", "qdrant-not-a-release.zip", "names no pinned release asset"),
            ("version", "0.0.1", "records version 0.0.1"),
        ],
    )
    def test_a_manifest_the_pin_table_does_not_cover_never_verifies(
        self, version_dir: Path, field: str, value: str, problem: str
    ) -> None:
        """The manifest only selects a committed digest; it supplies none."""
        asset = asset_for_platform()
        manifest = {
            "version": QDRANT_SERVER_VERSION,
            "asset": asset,
            "asset_sha256": QDRANT_ASSET_SHA256[asset],
            "binary_sha256": _sha256(_STAND_IN_EXECUTABLE),
            "source": "download",
        }
        _write_install(version_dir, {**manifest, field: value})

        report = provision()

        assert report.action == ProvisionAction.FAILED
        assert problem in report.message
        assert "--upgrade" in report.message
