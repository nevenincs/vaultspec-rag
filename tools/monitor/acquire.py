"""Acquire approved public archives and probe only the self-contained monitor."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import cast

from tools.binaries.build_pyapp import check_platform_floor
from tools.binaries.native import host_target_triple
from tools.binaries.release_hosts import GITHUB_RELEASE_REDIRECT_HOSTS
from tools.monitor.offline import probe_offline
from tools.monitor.pins import (
    ROOT,
    PinError,
    ReleasePins,
    catalog_at_commit,
    require_release,
)
from tools.monitor.smoke import installed_browser, probe
from tools.packaging.bundles import BundleSpec, verify_bundle
from tools.packaging.checksums import parse_checksums, require
from tools.packaging.products import MONITOR_EXECUTABLE, VAULTSPEC_RAG
from vaultspec_rag.qdrant_runtime._provision import (
    download_https,
    extract_verified_archive,
    file_sha256,
    verify_native_binary,
)


def _fetch(url: str, destination: Path) -> None:
    """Download one GitHub-hosted file into this run's scratch directory.

    A source on the API host is contacted like any other: the redirect set
    bounds only where an answer may send the request on.
    """
    with destination.open("wb") as out:
        download_https(url, out, redirect_hosts=GITHUB_RELEASE_REDIRECT_HOSTS)


def extract_delivery(
    archive: Path, spec: BundleSpec, pins: ReleasePins, destination: Path
) -> dict[str, str]:
    hashes = pins.targets[spec.target]
    if archive.is_symlink() or file_sha256(archive) != hashes.archive_sha256:
        raise PinError("Reviewed archive digest mismatch before extraction")
    manifest = verify_bundle(archive, spec)
    components = cast("dict[str, dict[str, object]]", manifest["components"])
    name = spec.product.executable_name(MONITOR_EXECUTABLE, spec.target)
    proof = cast("dict[str, object]", components[name]["verification"])
    if (
        manifest["source_revision"] != pins.source_revision
        or proof["lock_sha256"] != pins.lock_sha256
        or proof["frontend_sha256"] != pins.frontend_sha256
        or proof["sha256"] != hashes.monitor_sha256
    ):
        raise PinError(
            "Reviewed monitor or producer identity mismatch before extraction"
        )
    files = cast("list[dict[str, str]]", manifest["files"])
    digests = {item["name"]: item["sha256"] for item in files}
    destination.mkdir()
    for executable in spec.product.executables:
        name = spec.product.executable_name(executable, spec.target)
        binary, _ = extract_verified_archive(
            archive, hashes.archive_sha256, destination, binary_name=name
        )
        verify_native_binary(binary, digests[name])
        check_platform_floor(binary, spec.target)
        if spec.target.endswith("linux-gnu"):
            verify_native_binary(binary, digests[name])
            result = subprocess.run(
                ["ldd", "-v", str(binary)],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode or "not found" in result.stdout + result.stderr:
                raise PinError(
                    f"The native loader refused {name}: {result.stdout}{result.stderr}"
                )
    return digests


def latest_tag(directory: Path) -> str:
    metadata = directory / "latest.json"
    _fetch(
        "https://api.github.com/repos/nevenincs/vaultspec-rag/releases/latest", metadata
    )
    if metadata.stat().st_size > 1 << 20:
        raise PinError("Latest-release metadata exceeds its bounded window")
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    tag = payload.get("tag_name")
    if not isinstance(tag, str):
        raise PinError("The public latest release has no tag identity")
    return tag


def acquire(
    tag: str | None, producer: str | None, target: str, *, os_offline: bool = False
) -> dict[str, object]:
    if target != host_target_triple():
        raise PinError("Public acquisition requires the native declared target")
    authority, catalog = catalog_at_commit(ROOT)
    browser = installed_browser()
    with tempfile.TemporaryDirectory(prefix="monitor-acquisition-") as scratch:
        directory = Path(scratch)
        tag = tag or latest_tag(directory)
        pins = require_release(catalog, tag, producer)
        version = VAULTSPEC_RAG.version_from_tag(tag)
        spec = BundleSpec(VAULTSPEC_RAG, version, target)
        archive = directory / spec.archive_name
        base = VAULTSPEC_RAG.release_base_url(version)
        sums = directory / "SHA256SUMS"
        # Live checksums add coverage; the committed catalog supplies authority.
        _fetch(base + "/SHA256SUMS", sums)
        digests = parse_checksums(
            sums.read_text(encoding="utf-8", newline=""), require_unique=True
        )
        if require(digests, archive.name) != pins.targets[target].archive_sha256:
            raise PinError("Live SHA256SUMS differs from the reviewed archive pin")
        _fetch(base + "/" + archive.name, archive)
        extracted = directory / "extracted"
        extract_delivery(archive, spec, pins, extracted)
        # Keep backend bootstrappers outside the shell-only process placement.
        # Its browser polls status; no backend bootstrap belongs to this probe.
        shell = directory / "shell-only"
        shell.mkdir()
        name = VAULTSPEC_RAG.executable_name(MONITOR_EXECUTABLE, target)
        binary = shell / name
        shutil.copy2(extracted / name, binary)
        smoke = probe_offline if os_offline else probe
        report = smoke(
            binary,
            pins.targets[target].monitor_sha256,
            {
                "command": MONITOR_EXECUTABLE.name,
                "version": version,
                "source_revision": pins.source_revision,
                "lock_sha256": pins.lock_sha256,
                "frontend_sha256": pins.frontend_sha256,
                "development": False,
            },
            browser,
        )
        return {
            **report,
            "release_tag": tag,
            "catalog_revision": authority,
            "archive_sha256": pins.targets[target].archive_sha256,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag")
    parser.add_argument("--source-revision")
    parser.add_argument("--target", required=True)
    parser.add_argument("--os-offline", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = acquire(
        args.tag or None,
        args.source_revision or None,
        args.target,
        os_offline=args.os_offline,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(report))


if __name__ == "__main__":
    main()
