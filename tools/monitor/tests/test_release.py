"""Release admission uses exact wheel owners and complete native archive proof."""

from __future__ import annotations

import hashlib
import zipfile
from typing import TYPE_CHECKING

import pytest

from tools.monitor.release import (
    OWNER_MODULES,
    monitor_bytes,
    verify_release_set,
    verify_release_wheel,
)
from tools.packaging.bundles import (
    BundleError,
    BundleSpec,
    build_bundle,
    build_monitor_archive,
)
from tools.packaging.products import MONITOR_EXECUTABLE, VAULTSPEC_RAG
from tools.packaging.tests.test_bundles import (
    REVISION,
    VERSION,
    _raw_outputs,
    _sources,
)
from vaultspec_rag.native_binary._install import ChecksumMismatchError
from vaultspec_rag.native_binary._targets import host_target

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("change", ["missing", "changed", "none"])
def test_wheel_requires_canonical_monitor_owners(tmp_path: Path, change: str) -> None:
    source = tmp_path / "src"
    wheel = tmp_path / "vaultspec_rag-1.2.3-py3-none-any.whl"
    for name in OWNER_MODULES:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"canonical owner\n")
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "vaultspec_rag-1.2.3.dist-info/METADATA",
            "Name: vaultspec-rag\nVersion: 1.2.3\n",
        )
        for index, name in enumerate(OWNER_MODULES):
            if index == 0 and change == "missing":
                continue
            archive.writestr(
                name,
                b"wrong owner"
                if index == 0 and change == "changed"
                else (source / name).read_bytes(),
            )
    if change == "none":
        verify_release_wheel(wheel, "1.2.3", source)
    else:
        # Bypassing canonical-owner admission must fail this refusal assertion.
        with pytest.raises(BundleError, match="exact canonical owner"):
            verify_release_wheel(wheel, "1.2.3", source)


def test_native_archive_set_requires_common_frontend_and_all_targets(
    tmp_path: Path, pinned_wheel: Callable[..., Path]
) -> None:
    output = tmp_path / "bundles"
    for target in VAULTSPEC_RAG.supported_targets:
        root = tmp_path / target
        repo = root / "repo"
        repo.mkdir(parents=True)
        (repo / "LICENSE").write_text("license\n", encoding="utf-8")
        raw = _raw_outputs(root, target)
        build_bundle(
            BundleSpec(VAULTSPEC_RAG, VERSION, target),
            _sources(pinned_wheel, raw, repo, target),
            output,
        )
    lock = hashlib.sha256((repo / "package-lock.json").read_bytes()).hexdigest()
    tag = VAULTSPEC_RAG.tag_for(VERSION)
    verify_release_set(output, tag, REVISION, lock, "c" * 64)
    with pytest.raises(BundleError, match="different producer"):
        verify_release_set(output, tag, REVISION, lock, "d" * 64)
    (output / f"{tag}-x86_64-apple-darwin.tar.gz").write_bytes(b"unexpected archive")
    # Removing target completeness must fail this refusal assertion.
    with pytest.raises(BundleError, match="native target matrix"):
        verify_release_set(output, tag, REVISION, lock, "c" * 64)


def test_monitor_bytes_verifies_the_archive_before_and_the_monitor_after(
    tmp_path: Path, pinned_wheel: Callable[..., Path]
) -> None:
    """The bundles take the published monitor, admitted only by the wheel.

    The wheel's pinned archive digest decides whether the archive is opened
    at all, and its pinned executable digest decides whether what came out
    may be staged. Neither is read from the archive, from the release
    metadata, or from anything but the artifact that will run the monitor.

    Mutation proof: replacing ``extract_verified_archive`` with a plain
    extraction made the tampered-archive case fail with ``DID NOT RAISE`` and
    left the archive on disk; restoring it passed. Dropping the
    ``verify_native_binary`` call made the wrong-executable case fail the
    same way; restoring it passed.
    """
    target = host_target()
    (tmp_path / "repo").mkdir()
    raw = _raw_outputs(tmp_path, target)
    spec = BundleSpec(VAULTSPEC_RAG, VERSION, target)
    archives = tmp_path / "monitor"
    archive = build_monitor_archive(spec, raw, archives)
    monitor = raw / VAULTSPEC_RAG.asset_name(MONITOR_EXECUTABLE, target)
    executable = hashlib.sha256(monitor.read_bytes()).hexdigest()
    tag = VAULTSPEC_RAG.tag_for(VERSION)

    staging = tmp_path / "staged"
    wheel = pinned_wheel(
        tmp_path / "dist",
        VERSION,
        {target: executable},
        {target: hashlib.sha256(archive.read_bytes()).hexdigest()},
    )
    staged = monitor_bytes(tag, target, archives, wheel.parent, staging)
    assert staged.read_bytes() == monitor.read_bytes()
    assert (
        staged.with_name(staged.name + ".sha256")
        .read_text(encoding="utf-8")
        .startswith(executable)
    )

    refusing = tmp_path / "refused"
    wrong_executable = pinned_wheel(
        tmp_path / "wrong-executable",
        VERSION,
        {target: "0" * 64},
        {target: hashlib.sha256(archive.read_bytes()).hexdigest()},
    )
    with pytest.raises(RuntimeError, match="pin mismatch"):
        monitor_bytes(tag, target, archives, wrong_executable.parent, refusing)
    assert not (refusing / monitor.name).exists()

    wrong_archive = pinned_wheel(
        tmp_path / "wrong-archive", VERSION, {target: executable}, {target: "0" * 64}
    )
    with pytest.raises(ChecksumMismatchError):
        monitor_bytes(tag, target, archives, wrong_archive.parent, refusing)
    assert not archive.exists(), "an archive that failed its pin is not kept"
