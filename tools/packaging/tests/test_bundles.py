"""Release-bundle contract tests."""

from __future__ import annotations

import hashlib
import json
import tarfile
import zipfile
from typing import TYPE_CHECKING

import pytest

from tools.packaging import products
from tools.packaging.bundles import (
    BundleError,
    BundleSpec,
    build_bundle,
    verify_bundle,
)
from tools.packaging.products import VAULTSPEC_RAG

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

TARGETS = (
    products.WINDOWS_X86_64,
    products.LINUX_X86_64,
    products.LINUX_ARM64,
)
VERSION = "0.4.6"
REVISION = "revision-1"


def _raw_outputs(root: Path, target: str) -> Path:
    """Create finalized-looking raw outputs for one target."""
    raw = root / "raw"
    raw.mkdir()
    for index, executable in enumerate(VAULTSPEC_RAG.executables, start=1):
        path = raw / VAULTSPEC_RAG.asset_name(executable, target)
        path.write_bytes(f"executable-{index}".encode())
    return raw


def _contents(archive: Path, target: str) -> dict[str, bytes]:
    """Read regular members from either supported public archive format."""
    if target.endswith("windows-msvc"):
        with zipfile.ZipFile(archive) as handle:
            return {name: handle.read(name) for name in handle.namelist()}

    with tarfile.open(archive, "r:gz") as handle:
        contents: dict[str, bytes] = {}
        for member in handle.getmembers():
            payload = handle.extractfile(member)
            assert payload is not None
            contents[member.name] = payload.read()
        return contents


def _tampered_manifest(archive: Path, root: Path, field: str, value: object) -> Path:
    """Return a same-named ZIP bundle with one manifest field changed."""
    with zipfile.ZipFile(archive) as source:
        contents = {name: source.read(name) for name in source.namelist()}
    manifest = json.loads(contents["manifest.json"])
    manifest[field] = value
    contents["manifest.json"] = json.dumps(manifest).encode()

    root.mkdir()
    destination = root / archive.name
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name, payload in contents.items():
            target.writestr(name, payload)
    return destination


@pytest.mark.parametrize("target", TARGETS)
def test_build_bundle_has_stable_contents_and_manifest(
    tmp_path: Path, target: str
) -> None:
    """Each target archive contains stable names and hashes its members."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "LICENSE").write_text("license\n", encoding="utf-8")
    raw = _raw_outputs(tmp_path, target)
    spec = BundleSpec(VAULTSPEC_RAG, VERSION, target)

    archive = build_bundle(
        spec,
        raw,
        tmp_path / "bundles",
        repo,
        REVISION,
    )
    contents = _contents(archive, target)

    expected = {
        "LICENSE",
        "README.txt",
        "manifest.json",
        *(
            VAULTSPEC_RAG.executable_name(executable, target)
            for executable in VAULTSPEC_RAG.executables
        ),
    }
    assert set(contents) == expected
    assert all(target not in name for name in contents if name != "manifest.json")

    manifest = json.loads(contents["manifest.json"])
    assert manifest["archive"]["name"] == archive.name
    assert manifest["archive"]["format"] == (
        "zip" if target.endswith("windows-msvc") else "tar.gz"
    )
    assert manifest["display_name"] == "Vaultspec RAG"
    assert manifest["publisher"] == "Vaultspec Project"
    assert manifest["legal_copyright"] == "Copyright (c) 2026 Vaultspec Project"
    assert manifest["target"] == target
    assert manifest["source_revision"] == REVISION
    assert manifest["runtime"]["python"] == "3.13"
    assert manifest["requirements"] == {
        "nvidia_gpu": True,
        "network_on_first_launch": True,
        "cuda_runtime_download_on_first_launch": True,
    }
    assert {entry["name"] for entry in manifest["files"]} == expected - {
        "manifest.json"
    }
    for entry in manifest["files"]:
        assert entry["sha256"] == hashlib.sha256(contents[entry["name"]]).hexdigest()

    checksum = archive.with_name(archive.name + ".sha256")
    assert checksum.read_text(encoding="utf-8") == (
        f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n"
    )
    verify_bundle(archive, spec)


@pytest.mark.parametrize("target", TARGETS)
def test_build_bundle_is_deterministic(tmp_path: Path, target: str) -> None:
    """Host mtimes do not alter the public archive bytes."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "LICENSE").write_text("license\n", encoding="utf-8")
    raw = _raw_outputs(tmp_path, target)
    output = tmp_path / "bundles"
    spec = BundleSpec(VAULTSPEC_RAG, VERSION, target)

    archive = build_bundle(spec, raw, output, repo, REVISION)
    first = archive.read_bytes()
    archive = build_bundle(spec, raw, output, repo, REVISION)

    assert archive.read_bytes() == first


def test_build_bundle_rejects_a_missing_executable(tmp_path: Path) -> None:
    """A bundle cannot silently omit one of the product's commands.

    Mutation proof: removing the ``missing finalized executable`` guard made
    this assertion fail with a later file-not-found error; the guard was
    restored before the passing run.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "LICENSE").write_text("license\n", encoding="utf-8")
    spec = BundleSpec(VAULTSPEC_RAG, VERSION, TARGETS[0])

    with pytest.raises(BundleError, match="missing finalized executable"):
        build_bundle(spec, tmp_path / "raw", tmp_path / "bundles", repo, REVISION)


def test_build_bundle_rejects_an_unsupported_target(tmp_path: Path) -> None:
    """A macOS archive cannot be introduced outside RAG's support contract.

    Mutation proof: removing the product-support guard let a complete fixture
    build, so this assertion failed with ``DID NOT RAISE``; the guard was
    restored before the passing run.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "LICENSE").write_text("license\n", encoding="utf-8")
    raw = _raw_outputs(tmp_path, products.MACOS_ARM64)
    spec = BundleSpec(VAULTSPEC_RAG, VERSION, products.MACOS_ARM64)

    with pytest.raises(BundleError, match="does not support target"):
        build_bundle(spec, raw, tmp_path / "bundles", repo, REVISION)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_revision", "", "source revision"),
        ("runtime", {}, "runtime metadata"),
        ("requirements", {}, "requirements"),
        ("platform", {}, "platform metadata"),
    ],
)
def test_verify_bundle_rejects_missing_contract_metadata(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    """All generated metadata sections are required at the release edge."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "LICENSE").write_text("license\n", encoding="utf-8")
    target = TARGETS[0]
    raw = _raw_outputs(tmp_path, target)
    spec = BundleSpec(VAULTSPEC_RAG, VERSION, target)
    archive = build_bundle(spec, raw, tmp_path / "bundles", repo, REVISION)
    tampered = _tampered_manifest(archive, tmp_path / "tampered", field, value)

    with pytest.raises(BundleError, match=message):
        verify_bundle(tampered, spec)
