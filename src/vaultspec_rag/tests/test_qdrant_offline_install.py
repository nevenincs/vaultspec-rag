"""Installing the pinned Qdrant release from a local copy of its archive.

A host with no route to a release source is handed the official archive as a
file. That changes where the archive is read from and nothing else, so these
tests hold the local route to what the download is held to: the archive
digest before anything is extracted, the executable digest before anything is
replaced, staging and one atomic move, the manifest last. Two things are the
local route's own, and both are asserted on the operator's file itself: no
request is made for it, and it is never moved, renamed or removed.

As elsewhere, an install request carries its pins, so a stand-in archive is
held to its own digests through the shipped install; ``provision`` itself
holds a file to the committed digests, which no stand-in can satisfy, so at
that level it is the refusals that are driven.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from typing import IO, TYPE_CHECKING

import pytest

from .._sync_vocabulary import ProvisionAction
from ..config._types import EnvVar
from ..qdrant_runtime._constants import (
    MANIFEST_FILENAME,
    QDRANT_ASSET_SHA256,
    QDRANT_SERVER_VERSION,
)
from ..qdrant_runtime._provision import (
    _install,
    _open_staging,
    provision,
    provisioned_versions,
    verify_native_binary,
)
from ..qdrant_runtime._resolve import (
    asset_for_platform,
    binary_filename,
    qdrant_bin_dir,
)
from ._loopback_tls import (
    LoopbackSources,
    StandInSource,
    send_bytes,
    trusted_loopback_sources,
)
from ._stand_in_release import (
    ARCHIVE_SHAPES,
    NEW_EXECUTABLE,
    install_request,
    release_archive,
    sha256_hex,
    working_files,
)
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ..qdrant_runtime._provision import _InstallRequest

pytestmark = [pytest.mark.unit]

_PRIOR_EXECUTABLE = b"the executable installed before\x00" * 64
_STAND_IN_EXECUTABLE = b"stand-in bytes that are not the release executable"


@pytest.fixture
def sources(tmp_path: Path) -> Generator[LoopbackSources]:
    with trusted_loopback_sources(tmp_path / "tls") as started:
        yield started


@pytest.fixture
def version_dir(isolated_singleton_dirs: Path) -> Path:
    """The managed version dir, relocated under the test's temp dir."""
    del isolated_singleton_dirs
    return qdrant_bin_dir()


@pytest.fixture
def release_source(sources: LoopbackSources) -> StandInSource:
    """A source that would serve a release, and logs whether it was asked.

    Every local install here names it as where the asset is published. It
    answers any request, so an install that reached for the network would
    succeed in doing so and show up in its log.
    """
    return sources.serve(
        lambda handler: send_bytes(handler, release_archive(ARCHIVE_SHAPES[0]))
    )


def _operator_copy(
    directory: Path, asset: str, executable: bytes = NEW_EXECUTABLE
) -> Path:
    """Write a release archive as an operator would carry it: under any name."""
    directory.mkdir(parents=True, exist_ok=True)
    suffix = ".zip" if asset.endswith(".zip") else ".tgz"
    copy = directory / f"carried-over-on-a-stick{suffix}"
    copy.write_bytes(release_archive(asset, executable))
    return copy


def _local_request(
    release_source: StandInSource, version_dir: Path, copy: Path, asset: str
) -> _InstallRequest:
    """A first-install request for *asset*, read from the local *copy*."""
    return replace(
        install_request(
            release_source.url(f"/{asset}"),
            version_dir,
            asset=asset,
            pinned_archive=copy.read_bytes(),
        ),
        local_archive=copy,
    )


def _install_prior(
    release_source: StandInSource, version_dir: Path, tmp_path: Path
) -> bytes:
    """Install a previous executable for real, from a local archive."""
    asset = ARCHIVE_SHAPES[0]
    copy = _operator_copy(tmp_path / "prior", asset, _PRIOR_EXECUTABLE)
    request = replace(
        _local_request(release_source, version_dir, copy, asset),
        executable_sha256=sha256_hex(_PRIOR_EXECUTABLE),
    )
    report = _install(request)
    assert report.action == ProvisionAction.CREATED, report.message
    return (version_dir / MANIFEST_FILENAME).read_bytes()


def _assert_prior_install_verifies(version_dir: Path, manifest: bytes) -> None:
    verify_native_binary(version_dir / binary_filename(), sha256_hex(_PRIOR_EXECUTABLE))
    assert (version_dir / MANIFEST_FILENAME).read_bytes() == manifest


class TestInstallFromALocalArchive:
    """The local route is the download's install with a different first step."""

    @pytest.mark.parametrize("asset", ARCHIVE_SHAPES)
    def test_a_local_archive_is_installed_with_no_request_and_left_as_it_was(
        self,
        release_source: StandInSource,
        version_dir: Path,
        tmp_path: Path,
        asset: str,
    ) -> None:
        """The file is read where it lies, whatever it is called.

        The copy's name says nothing about what it is; its digest does. The
        archive format is taken from the asset the platform selects.

        Mutation: made ``_verified_archive`` ignore the local copy and take
        the download branch. Observed the request-log assertion fail: the
        asset had been fetched from the source. Restored; passes.
        """
        copy = _operator_copy(tmp_path / "carried", asset)
        before = (copy.read_bytes(), copy.stat().st_mtime_ns)

        report = _install(_local_request(release_source, version_dir, copy, asset))

        assert release_source.requests == []
        assert report.action == ProvisionAction.CREATED, report.message
        assert report.url == ""
        assert report.asset == asset
        binary = version_dir / binary_filename()
        assert report.binary == binary
        assert binary.read_bytes() == NEW_EXECUTABLE
        manifest = json.loads(
            (version_dir / MANIFEST_FILENAME).read_text(encoding="utf-8")
        )
        assert manifest["source"] == "archive"
        assert manifest["asset"] == asset
        assert manifest["asset_sha256"] == sha256_hex(before[0])
        assert manifest["binary_sha256"] == sha256_hex(NEW_EXECUTABLE)
        assert manifest["version"] == QDRANT_SERVER_VERSION
        assert (copy.read_bytes(), copy.stat().st_mtime_ns) == before
        assert working_files(version_dir) == []

    def test_a_local_archive_replaces_a_previous_install(
        self, release_source: StandInSource, version_dir: Path, tmp_path: Path
    ) -> None:
        asset = ARCHIVE_SHAPES[0]
        _install_prior(release_source, version_dir, tmp_path)
        copy = _operator_copy(tmp_path / "carried", asset)
        request = _local_request(release_source, version_dir, copy, asset)

        report = _install(replace(request, previously="verified"))

        assert report.action == ProvisionAction.UPDATED, report.message
        assert (version_dir / binary_filename()).read_bytes() == NEW_EXECUTABLE
        assert copy.is_file()
        assert release_source.requests == []

    def test_a_file_that_is_not_the_pinned_archive_is_refused_unextracted(
        self, release_source: StandInSource, version_dir: Path, tmp_path: Path
    ) -> None:
        """The archive digest is checked before anything is taken from the file.

        The copy is a well-formed archive holding the very executable the
        request pins, with one extra member, so only the archive digest
        stands between it and an install. No staging file may be opened for
        it at all.

        Mutation: skipped the digest comparison for a local copy in
        ``_verified_archive``. Observed the action assertion fail
        (``updated`` where ``failed`` was required). Restored; passes.
        """
        asset = ARCHIVE_SHAPES[0]
        prior_manifest = _install_prior(release_source, version_dir, tmp_path)
        pinned = _operator_copy(tmp_path / "pinned", asset)
        carried = tmp_path / "carried" / "almost-the-release.zip"
        carried.parent.mkdir()
        from ._stand_in_release import build_archive

        carried.write_bytes(
            build_archive(
                asset,
                {binary_filename(): NEW_EXECUTABLE, "NOTICE": b"not in the release"},
            )
        )
        before = (carried.read_bytes(), carried.stat().st_mtime_ns)
        opened: list[str] = []

        def recording(directory: Path, label: str) -> tuple[Path, IO[bytes]]:
            opened.append(label)
            return _open_staging(directory, label)

        request = replace(
            _local_request(release_source, version_dir, pinned, asset),
            local_archive=carried,
            previously="verified",
            open_staging=recording,
        )

        report = _install(request)

        assert report.action == ProvisionAction.FAILED
        assert str(carried) in report.message
        assert asset in report.message
        assert sha256_hex(pinned.read_bytes()) in report.message
        assert sha256_hex(before[0]) in report.message
        assert "Nothing was extracted" in report.message
        assert opened == []
        assert (carried.read_bytes(), carried.stat().st_mtime_ns) == before
        assert release_source.requests == []
        _assert_prior_install_verifies(version_dir, prior_manifest)
        assert working_files(version_dir) == []

    def test_an_executable_that_fails_its_digest_is_refused_before_it_replaces_anything(
        self, release_source: StandInSource, version_dir: Path, tmp_path: Path
    ) -> None:
        """The second digest applies to a local archive as to a downloaded one.

        Mutation: removed the executable digest comparison in
        ``_stage_verified_executable``. Observed the action assertion fail
        (``updated`` where ``failed`` was required). Restored; passes.
        """
        asset = ARCHIVE_SHAPES[0]
        prior_manifest = _install_prior(release_source, version_dir, tmp_path)
        copy = _operator_copy(tmp_path / "carried", asset)
        request = replace(
            _local_request(release_source, version_dir, copy, asset),
            executable_sha256=sha256_hex(b"what the pin table says it should be"),
            previously="verified",
        )

        report = _install(request)

        assert report.action == ProvisionAction.FAILED
        assert "SHA256 mismatch" in report.message
        assert binary_filename() in report.message
        assert copy.is_file()
        _assert_prior_install_verifies(version_dir, prior_manifest)
        assert working_files(version_dir) == []

    def test_bytes_that_are_not_an_archive_are_a_failed_outcome(
        self, release_source: StandInSource, version_dir: Path, tmp_path: Path
    ) -> None:
        asset = ARCHIVE_SHAPES[0]
        prior_manifest = _install_prior(release_source, version_dir, tmp_path)
        garbage = tmp_path / "carried" / "not-an-archive.zip"
        garbage.parent.mkdir()
        garbage.write_bytes(b"neither a zip nor a gzip stream" * 64)

        report = _install(
            replace(
                _local_request(release_source, version_dir, garbage, asset),
                previously="verified",
            )
        )

        assert report.action == ProvisionAction.FAILED
        assert garbage.is_file()
        _assert_prior_install_verifies(version_dir, prior_manifest)
        assert working_files(version_dir) == []

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="only Windows refuses to replace a file a process holds open",
    )
    def test_an_executable_in_use_is_a_failed_outcome_naming_the_remedy(
        self, release_source: StandInSource, version_dir: Path, tmp_path: Path
    ) -> None:
        asset = ARCHIVE_SHAPES[0]
        prior_manifest = _install_prior(release_source, version_dir, tmp_path)
        copy = _operator_copy(tmp_path / "carried", asset)
        request = _local_request(release_source, version_dir, copy, asset)

        with (version_dir / binary_filename()).open("rb"):
            report = _install(replace(request, previously="verified"))

        assert report.action == ProvisionAction.FAILED
        assert "vaultspec-rag server stop" in report.message
        _assert_prior_install_verifies(version_dir, prior_manifest)
        assert working_files(version_dir) == []


@pytest.fixture
def no_route(release_source: StandInSource) -> Generator[StandInSource]:
    """Point the release base at a source that logs every request it gets."""
    with managed_env(
        **{EnvVar.QDRANT_RELEASE_BASE_URL.value: release_source.url("/mirror")}
    ):
        yield release_source


class TestProvisionFromALocalArchive:
    """``provision(archive=...)`` holds the file to the committed pins."""

    def test_a_file_that_is_not_the_pinned_archive_is_refused_by_name_and_digest(
        self, no_route: StandInSource, version_dir: Path, tmp_path: Path
    ) -> None:
        """The refusal tells the operator exactly which file would be right.

        Mutation: made ``_plan`` drop the local archive from the install it
        plans. Observed the request-log assertion fail: with no local copy
        the run downloaded instead. Restored; passes.
        """
        asset = asset_for_platform()
        copy = _operator_copy(tmp_path / "carried", ARCHIVE_SHAPES[0])
        before = (copy.read_bytes(), copy.stat().st_mtime_ns)

        report = provision(archive=copy)

        assert no_route.requests == []
        assert report.action == ProvisionAction.FAILED
        assert str(copy) in report.message
        assert asset in report.message
        assert QDRANT_ASSET_SHA256[asset] in report.message
        assert sha256_hex(before[0]) in report.message
        assert report.url == ""
        assert (copy.read_bytes(), copy.stat().st_mtime_ns) == before
        assert not (version_dir / binary_filename()).exists()
        assert working_files(version_dir) == []

    @pytest.mark.parametrize("dry_run", [False, True])
    def test_a_path_that_is_not_a_file_is_a_failed_outcome(
        self, no_route: StandInSource, version_dir: Path, tmp_path: Path, dry_run: bool
    ) -> None:
        missing = tmp_path / "never-copied-over.zip"
        folder = tmp_path / "a-folder.zip"
        folder.mkdir()

        for path in (missing, folder):
            report = provision(archive=path, dry_run=dry_run)

            assert report.action == ProvisionAction.FAILED
            assert str(path) in report.message
            assert "is not an existing file" in report.message
        assert no_route.requests == []
        assert not version_dir.exists()

    def test_a_dry_run_names_the_file_and_touches_nothing(
        self, no_route: StandInSource, version_dir: Path, tmp_path: Path
    ) -> None:
        copy = _operator_copy(tmp_path / "carried", ARCHIVE_SHAPES[0])

        report = provision(archive=copy, dry_run=True)

        assert report.action == ProvisionAction.DRY_RUN
        assert str(copy) in report.message
        assert asset_for_platform() in report.message
        assert "local archive" in report.message
        assert report.url == ""
        assert no_route.requests == []
        assert not version_dir.parent.exists()

    def test_an_archive_kept_inside_the_managed_directory_is_refused_and_survives(
        self, no_route: StandInSource, version_dir: Path
    ) -> None:
        """The operator's copy must never be something an install can delete.

        The copy sits in the version directory under a name the install would
        take for a working file left by a killed run, and remove.

        Mutation: removed the managed-directory test in ``_unusable_archive``.
        Observed the existence assertion fail: the run had swept the
        operator's file away before reading it. Restored; passes.
        """
        version_dir.mkdir(parents=True)
        copy = version_dir / ".carried-over.staging"
        copy.write_bytes(release_archive(ARCHIVE_SHAPES[0]))

        report = provision(archive=copy)

        assert copy.is_file()
        assert report.action == ProvisionAction.FAILED
        assert "inside the managed directory" in report.message
        assert no_route.requests == []

    def test_an_install_nothing_vouches_for_is_not_overwritten_without_upgrade(
        self, no_route: StandInSource, version_dir: Path, tmp_path: Path
    ) -> None:
        """A local archive changes the source, not the rule about overwriting."""
        version_dir.mkdir(parents=True)
        binary = version_dir / binary_filename()
        binary.write_bytes(_STAND_IN_EXECUTABLE)
        copy = _operator_copy(tmp_path / "carried", ARCHIVE_SHAPES[0])

        plain = provision(archive=copy)
        upgraded = provision(archive=copy, upgrade=True)

        assert plain.action == ProvisionAction.FAILED
        assert "--upgrade" in plain.message
        assert "--archive <file>" in plain.message
        # With the upgrade the run goes on to the archive, which is where a
        # stand-in is refused, and the executable it found is still there.
        assert upgraded.action == ProvisionAction.FAILED
        assert "is not the pinned Qdrant release archive" in upgraded.message
        assert binary.read_bytes() == _STAND_IN_EXECUTABLE
        assert no_route.requests == []


class TestListing:
    """A listing says what an executable is only after hashing it."""

    def test_an_install_nothing_vouches_for_is_listed_as_unverified_with_the_reason(
        self, version_dir: Path
    ) -> None:
        """The manifest's claim about its source is not repeated.

        Mutation: made ``provisioned_versions`` report the manifest's own
        ``source``. Observed the source assertion fail (``operator`` where
        ``unverified`` was required). Restored; passes.
        """
        version_dir.mkdir(parents=True)
        (version_dir / binary_filename()).write_bytes(_STAND_IN_EXECUTABLE)
        (version_dir / MANIFEST_FILENAME).write_text(
            json.dumps(
                {
                    "version": QDRANT_SERVER_VERSION,
                    "binary_sha256": sha256_hex(_STAND_IN_EXECUTABLE),
                    "source": "operator",
                    "provisioned_at": "2026-06-12T00:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        entries = provisioned_versions()

        assert len(entries) == 1
        entry = entries[0]
        assert entry["version"] == QDRANT_SERVER_VERSION
        assert entry["current"] is True
        assert entry["verified"] is False
        assert entry["source"] == "unverified"
        assert EnvVar.QDRANT_BINARY_SHA256.value in str(entry["problem"])

    def test_a_version_that_is_not_the_pinned_one_can_never_be_listed_as_verified(
        self, version_dir: Path
    ) -> None:
        other = version_dir.parent / "0.0.1"
        other.mkdir(parents=True)
        (other / binary_filename()).write_bytes(_STAND_IN_EXECUTABLE)
        (other / MANIFEST_FILENAME).write_text(
            json.dumps({"version": "0.0.1", "source": "download"}), encoding="utf-8"
        )

        entries = provisioned_versions()

        assert len(entries) == 1
        assert entries[0]["current"] is False
        assert entries[0]["verified"] is False
        assert entries[0]["source"] == "unverified"
        assert "not the pinned version" in str(entries[0]["problem"])
