"""Release admission uses exact wheel owners and complete native archive proof."""

from __future__ import annotations

import hashlib
import zipfile
from typing import TYPE_CHECKING

import pytest

from tools.monitor.release import (
    OWNER_MODULES,
    verify_release_set,
    verify_release_wheel,
)
from tools.packaging.bundles import BundleError, BundleSpec, build_bundle
from tools.packaging.products import VAULTSPEC_RAG
from tools.packaging.tests.test_bundles import REVISION, VERSION, _raw_outputs

if TYPE_CHECKING:
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
    tmp_path: Path,
) -> None:
    output = tmp_path / "bundles"
    for target in VAULTSPEC_RAG.supported_targets:
        root = tmp_path / target
        repo = root / "repo"
        repo.mkdir(parents=True)
        (repo / "LICENSE").write_text("license\n", encoding="utf-8")
        build_bundle(
            BundleSpec(VAULTSPEC_RAG, VERSION, target),
            _raw_outputs(root, target),
            output,
            repo,
            REVISION,
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
