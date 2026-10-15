"""Release-bundle contract tests."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
import zipfile
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from tools.binaries.bun_pins import BUN_VERSION
from tools.packaging import products
from tools.packaging.bundles import (
    SMOKE_NAME,
    BundleError,
    BundleSources,
    BundleSpec,
    build_bundle,
    build_monitor_archive,
    verify_bundle,
    verify_monitor_archive,
)
from tools.packaging.products import VAULTSPEC_RAG
from vaultspec_rag.monitor_runtime._pins import PinProvenance

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

pytestmark = pytest.mark.unit

TARGETS = (
    products.WINDOWS_X86_64,
    products.LINUX_X86_64,
    products.LINUX_ARM64,
    products.MACOS_ARM64,
)
MULTI_ARCH_PRODUCT = replace(VAULTSPEC_RAG, supported_targets=TARGETS)
VERSION = "0.4.6"
REVISION = "a" * 40


def _raw_outputs(root: Path, target: str) -> Path:
    """Create finalized-looking raw outputs for one target."""
    raw = root / "raw"
    raw.mkdir()
    for index, executable in enumerate(VAULTSPEC_RAG.executables, start=1):
        path = raw / VAULTSPEC_RAG.asset_name(executable, target)
        path.write_bytes(f"executable-{index}".encode())
    lock = root / "repo/package-lock.json"
    lock.write_text("{}\n", encoding="utf-8")
    monitor = raw / VAULTSPEC_RAG.asset_name(products.MONITOR_EXECUTABLE, target)
    (raw / SMOKE_NAME).write_text(
        json.dumps(
            {
                "schema": "vaultspec.monitor.smoke.v1",
                "command": "vaultspec-rag-monitor",
                "version": VERSION,
                "source_revision": REVISION,
                "lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
                "frontend_sha256": "c" * 64,
                "bun_version": BUN_VERSION,
                "development": False,
                "sha256": hashlib.sha256(monitor.read_bytes()).hexdigest(),
                "target": target,
                "platform": {
                    "glibc_required": "2.28" if target.endswith("linux-gnu") else None
                },
                "assets_verified": 94,
                "browser_verified": True,
                "isolated_shell": True,
                "os_offline_verified": True,
                "occupied_port_refused": True,
                "parent_eof_shutdown": True,
                "request_bounds_verified": True,
                "cancelled_request_recovered": True,
                "partial_request_shutdown": True,
            }
        ),
        encoding="utf-8",
    )
    return raw


def _sources(
    pinned_wheel: Callable[..., Path], raw: Path, repo: Path, target: str
) -> BundleSources:
    """Bind staged outputs to a wheel admitting exactly the monitor beside them.

    A release bundle is refused when its wheel admits another monitor, so
    every fixture here states which monitor its wheel admits rather than
    leaving the pair unstated.
    """
    monitor = raw / VAULTSPEC_RAG.asset_name(products.MONITOR_EXECUTABLE, target)
    digest = (
        hashlib.sha256(monitor.read_bytes()).hexdigest()
        if monitor.is_file()
        else "0" * 64
    )
    return BundleSources(
        raw, pinned_wheel(repo / "dist", VERSION, {target: digest}), repo, REVISION
    )


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


def _modes(archive: Path, target: str) -> dict[str, int]:
    """Read portable permission bits from either archive format."""
    if target.endswith("windows-msvc"):
        with zipfile.ZipFile(archive) as handle:
            return {
                info.filename: (info.external_attr >> 16) & 0o777
                for info in handle.infolist()
            }

    with tarfile.open(archive, "r:gz") as handle:
        return {member.name: member.mode & 0o777 for member in handle.getmembers()}


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
    tmp_path: Path, target: str, pinned_wheel: Callable[..., Path]
) -> None:
    """Each target archive contains stable names and hashes its members."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "LICENSE").write_text("license\n", encoding="utf-8")
    raw = _raw_outputs(tmp_path, target)
    spec = BundleSpec(MULTI_ARCH_PRODUCT, VERSION, target)

    archive = build_bundle(
        spec, _sources(pinned_wheel, raw, repo, target), tmp_path / "bundles"
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
    backend = manifest["components"][
        VAULTSPEC_RAG.executable_name(VAULTSPEC_RAG.executables[0], target)
    ]
    assert manifest["schema"] == "vaultspec.release-bundle.v2"
    assert backend["runtime"]["python"] == "3.13"
    assert backend["requirements"] == {
        "accelerator": "mps" if target.endswith("apple-darwin") else "cuda",
        "network_on_first_launch": True,
        "python_bootstrap": True,
    }
    frontend = manifest["components"][
        VAULTSPEC_RAG.executable_name(products.MONITOR_EXECUTABLE, target)
    ]
    assert frontend["requirements"]["network_on_first_launch"] is False
    assert frontend["runtime"] == {"bun": BUN_VERSION, "embedded_frontend": True}
    if target.endswith("linux-gnu"):
        assert manifest["platform"]["glibc_floor"] == "2.39"
        assert frontend["platform"]["glibc_required"] == "2.28"
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
def test_build_bundle_is_deterministic(
    tmp_path: Path, target: str, pinned_wheel: Callable[..., Path]
) -> None:
    """Host modes, mtimes, and umask do not alter the public archive bytes."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "LICENSE").write_text("license\n", encoding="utf-8")
    raw = _raw_outputs(tmp_path, target)
    output = tmp_path / "bundles"
    spec = BundleSpec(MULTI_ARCH_PRODUCT, VERSION, target)

    sources = _sources(pinned_wheel, raw, repo, target)
    previous_umask = os.umask(0o077)
    try:
        archive = build_bundle(spec, sources, output)
        first = archive.read_bytes()

        for source in (repo / "LICENSE", *raw.iterdir()):
            source.chmod(0o600)
        os.umask(0o002)
        archive = build_bundle(spec, sources, output)
    finally:
        os.umask(previous_umask)

    assert archive.read_bytes() == first


@pytest.mark.parametrize("target", TARGETS)
def test_build_bundle_writes_canonical_member_modes(
    tmp_path: Path, target: str, pinned_wheel: Callable[..., Path]
) -> None:
    """Executables are 0755 and descriptive members are 0644 in every format."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "LICENSE").write_text("license\n", encoding="utf-8")
    raw = _raw_outputs(tmp_path, target)
    archive = build_bundle(
        BundleSpec(VAULTSPEC_RAG, VERSION, target),
        _sources(pinned_wheel, raw, repo, target),
        tmp_path / "bundles",
    )

    modes = _modes(archive, target)
    executable_names = {
        VAULTSPEC_RAG.executable_name(executable, target)
        for executable in VAULTSPEC_RAG.executables
    }
    assert {modes[name] for name in executable_names} == {0o755}
    assert {mode for name, mode in modes.items() if name not in executable_names} == {
        0o644
    }


def test_verify_bundle_rejects_non_executable_unix_command(
    tmp_path: Path, pinned_wheel: Callable[..., Path]
) -> None:
    """A Unix command without its execute bits cannot cross verification.

    Mutation proof: omitting member-mode verification made this test fail with
    ``DID NOT RAISE``; the verification call was restored before the passing run.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "LICENSE").write_text("license\n", encoding="utf-8")
    target = products.LINUX_X86_64
    spec = BundleSpec(VAULTSPEC_RAG, VERSION, target)
    raw = _raw_outputs(tmp_path, target)
    archive = build_bundle(
        spec, _sources(pinned_wheel, raw, repo, target), tmp_path / "bundles"
    )
    contents = _contents(archive, target)
    modes = _modes(archive, target)
    command = VAULTSPEC_RAG.executable_name(VAULTSPEC_RAG.executables[0], target)
    modes[command] = 0o644

    with tarfile.open(archive, "w:gz") as handle:
        for name, payload in contents.items():
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            member.mode = modes[name]
            handle.addfile(member, io.BytesIO(payload))

    with pytest.raises(BundleError, match=f"bundle mode for {command}"):
        verify_bundle(archive, spec)


def test_build_bundle_rejects_a_missing_executable(
    tmp_path: Path, pinned_wheel: Callable[..., Path]
) -> None:
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
        build_bundle(
            spec,
            _sources(pinned_wheel, tmp_path / "raw", repo, TARGETS[0]),
            tmp_path / "bundles",
        )


def test_build_bundle_rejects_an_unsupported_target(
    tmp_path: Path, pinned_wheel: Callable[..., Path]
) -> None:
    """An Intel macOS archive cannot be introduced outside the support contract.

    Apple silicon IS supported and built; Intel Macs are not, and the matrix
    has no leg for one, so this is the target that must still be refused.

    Mutation proof: removing the product-support guard let a complete fixture
    build, so this assertion failed with ``DID NOT RAISE``; the guard was
    restored before the passing run.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "LICENSE").write_text("license\n", encoding="utf-8")
    raw = _raw_outputs(tmp_path, products.MACOS_X86_64)
    spec = BundleSpec(VAULTSPEC_RAG, VERSION, products.MACOS_X86_64)

    with pytest.raises(BundleError, match="does not support target"):
        build_bundle(
            spec,
            _sources(pinned_wheel, raw, repo, products.MACOS_X86_64),
            tmp_path / "bundles",
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_revision", "", "source revision"),
        ("components", {}, "components metadata"),
        ("platform", {}, "platform metadata"),
    ],
)
def test_verify_bundle_rejects_missing_contract_metadata(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
    pinned_wheel: Callable[..., Path],
) -> None:
    """All generated metadata sections are required at the release edge."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "LICENSE").write_text("license\n", encoding="utf-8")
    target = TARGETS[0]
    raw = _raw_outputs(tmp_path, target)
    spec = BundleSpec(VAULTSPEC_RAG, VERSION, target)
    archive = build_bundle(
        spec, _sources(pinned_wheel, raw, repo, target), tmp_path / "bundles"
    )
    tampered = _tampered_manifest(archive, tmp_path / "tampered", field, value)

    with pytest.raises(BundleError, match=message):
        verify_bundle(tampered, spec)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("development", True),
        ("browser_verified", False),
        ("os_offline_verified", False),
        ("sha256", "0" * 64),
        ("source_revision", "b" * 40),
        ("lock_sha256", "0" * 64),
        ("target", products.LINUX_X86_64),
        ("bun_version", "unreviewed"),
        ("platform", {"glibc_required": "2.40"}),
        ("assets_verified", True),
    ],
)
def test_bundle_refuses_unproven_monitor(
    tmp_path: Path, field: str, value: object, pinned_wheel: Callable[..., Path]
) -> None:
    """Removing OS-offline admission failed its case; restoration passed (1/0)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "LICENSE").write_text("license\n", encoding="utf-8")
    target = products.WINDOWS_X86_64
    raw = _raw_outputs(tmp_path, target)
    report_path = raw / SMOKE_NAME
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report[field] = value
    report_path.write_text(json.dumps(report), encoding="utf-8")
    # Bypassing evidence admission must fail the expected refusal assertion.
    with pytest.raises(BundleError, match="monitor"):
        build_bundle(
            BundleSpec(VAULTSPEC_RAG, VERSION, target),
            _sources(pinned_wheel, raw, repo, target),
            tmp_path / "bundles",
        )


@pytest.mark.parametrize(
    ("pins", "message"),
    [
        pytest.param(("admits", {"0" * 64}), "wheel admits", id="another monitor"),
        pytest.param(("provenance", None), "development", id="development pins"),
        pytest.param(("version", None), "release", id="another release"),
        pytest.param(("absent", None), "no monitor", id="no pins at all"),
        pytest.param(("target", None), "no monitor for", id="another target"),
    ],
)
def test_bundle_refuses_a_monitor_its_own_wheel_would_not_run(
    tmp_path: Path,
    pins: tuple[str, object],
    message: str,
    pinned_wheel: Callable[..., Path],
) -> None:
    """A bundle whose wheel admits other monitor bytes is a release defect.

    The bundle's own launcher checks the monitor beside it against the
    digests in the wheel it runs, so a disagreement means that installation
    would refuse the monitor it was shipped and provision another copy.

    Mutation proof: removing the ``verify_monitor_pins`` call from the bundle
    build made every case here fail with ``DID NOT RAISE``; restoring the
    call made them pass.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "LICENSE").write_text("license\n", encoding="utf-8")
    target = products.WINDOWS_X86_64
    raw = _raw_outputs(tmp_path, target)
    monitor = raw / VAULTSPEC_RAG.asset_name(products.MONITOR_EXECUTABLE, target)
    digest = hashlib.sha256(monitor.read_bytes()).hexdigest()
    kind = pins[0]
    if kind == "absent":
        wheel = tmp_path / "dist" / f"vaultspec_rag-{VERSION}-py3-none-any.whl"
        wheel.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(wheel, "w") as handle:
            handle.writestr("vaultspec_rag/__init__.py", "")
    elif kind == "admits":
        wheel = pinned_wheel(tmp_path / "dist", VERSION, {target: "0" * 64})
    elif kind == "provenance":
        wheel = pinned_wheel(
            tmp_path / "dist",
            VERSION,
            {target: digest},
            None,
            PinProvenance.DEVELOPMENT,
        )
    elif kind == "version":
        wheel = pinned_wheel(tmp_path / "dist", "9.9.9", {target: digest})
    else:
        wheel = pinned_wheel(
            tmp_path / "dist", VERSION, {products.LINUX_X86_64: digest}
        )

    with pytest.raises(BundleError, match=message):
        build_bundle(
            BundleSpec(VAULTSPEC_RAG, VERSION, target),
            BundleSources(raw, wheel, repo, REVISION),
            tmp_path / "bundles",
        )


@pytest.mark.parametrize("target", TARGETS)
def test_the_monitor_archive_carries_only_the_monitor(
    tmp_path: Path, target: str
) -> None:
    """The provisioning archive is one executable, deterministically packed.

    An installation extracts one member by basename and runs it, so anything
    else in the archive is a member it would never look at and a name it
    could be confused by. Two runs over one finalized monitor produce one
    archive, because the digest the wheel carries describes bytes, not a run.
    """
    spec = BundleSpec(MULTI_ARCH_PRODUCT, VERSION, target)
    (tmp_path / "repo").mkdir()
    raw = _raw_outputs(tmp_path, target)
    output = tmp_path / "monitor"

    archive = build_monitor_archive(spec, raw, output)
    first = archive.read_bytes()
    sidecar = archive.with_name(archive.name + ".sha256")

    assert (
        archive.name
        == f"vaultspec-rag-monitor-v{VERSION}-{target}{
            '.zip' if target.endswith('windows-msvc') else '.tar.gz'
        }"
    )
    assert set(_contents(archive, target)) == {spec.monitor_member}
    assert _modes(archive, target) == {spec.monitor_member: 0o755}
    assert sidecar.read_text(encoding="utf-8") == (
        f"{hashlib.sha256(first).hexdigest()}  {archive.name}\n"
    )

    (raw / VAULTSPEC_RAG.asset_name(products.MONITOR_EXECUTABLE, target)).chmod(0o600)
    assert build_monitor_archive(spec, raw, output).read_bytes() == first


def test_the_monitor_archive_refuses_an_absent_or_padded_archive(
    tmp_path: Path,
) -> None:
    """Refused where it happens, so no digest describes an unusable archive.

    Mutation proof: removing the member-set check from
    ``verify_monitor_archive`` made the padded case fail with ``DID NOT
    RAISE``; restoring it passed.
    """
    target = products.LINUX_X86_64
    spec = BundleSpec(VAULTSPEC_RAG, VERSION, target)
    (tmp_path / "repo").mkdir()

    with pytest.raises(BundleError, match="missing finalized monitor"):
        build_monitor_archive(spec, tmp_path / "absent", tmp_path / "monitor")

    archive = build_monitor_archive(
        spec, _raw_outputs(tmp_path, target), tmp_path / "monitor"
    )
    contents = _contents(archive, target)
    with tarfile.open(archive, "w:gz") as handle:
        for name, payload in {**contents, "NOTES.txt": b"extra\n"}.items():
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            member.mode = 0o755
            handle.addfile(member, io.BytesIO(payload))

    with pytest.raises(BundleError, match="monitor archive carries"):
        verify_monitor_archive(archive, spec)
