"""Shared release admission for the canonical wheel and native monitor evidence."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import cast

from tools.binaries.build_pyapp import (
    sole_wheel,
    validate_project_wheel,
    write_checksum,
)
from tools.monitor.offline import probe_offline
from tools.monitor.smoke import installed_browser, probe
from tools.packaging.bundles import (
    SMOKE_NAME,
    BundleError,
    BundleSpec,
    admitted_monitor_pins,
    build_monitor_archive,
    verify_bundle,
    verify_monitor_archive,
)
from tools.packaging.checksums import read_checksums, require
from tools.packaging.products import MONITOR_EXECUTABLE, VAULTSPEC_RAG
from vaultspec_rag.native_binary._install import (
    extract_verified_archive,
    file_sha256,
    verify_native_binary,
)
from vaultspec_rag.native_binary._targets import host_target

ROOT = Path(__file__).resolve().parents[2]
OWNER_MODULES = (
    "vaultspec_rag/monitor_process.py",
    "vaultspec_rag/monitor_inventory.py",
    "vaultspec_rag/cli/_service_inventory.py",
)


def verify_release_wheel(wheel: Path, version: str, source: Path) -> None:
    """Refuse a wheel missing or diverging from the canonical installed owners."""
    validate_project_wheel(wheel, version)
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        for name in OWNER_MODULES:
            path = source / name
            if (
                names.count(name) != 1
                or not path.is_file()
                or archive.read(name) != path.read_bytes()
            ):
                raise BundleError(
                    f"Release wheel lacks the exact canonical owner: {name}"
                )


def native_smoke(
    tag: str, revision: str, target: str, raw: Path, *, os_offline: bool = False
) -> None:
    if target != host_target():
        raise BundleError("Monitor evidence requires the native declared target")
    name = VAULTSPEC_RAG.asset_name(MONITOR_EXECUTABLE, target)
    binary = raw / name
    digest = require(read_checksums(binary.with_name(name + ".sha256")), name)
    browser = installed_browser()
    smoke = probe_offline if os_offline else probe
    report = smoke(
        binary,
        digest,
        {
            "command": MONITOR_EXECUTABLE.name,
            "version": VAULTSPEC_RAG.version_from_tag(tag),
            "source_revision": revision,
            "development": False,
        },
        browser,
    )
    (raw / SMOKE_NAME).write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def monitor_archive(tag: str, target: str, raw: Path, outdir: Path) -> Path:
    """Pack this host's finalized monitor as the release's provisioning archive.

    Runs where the monitor was compiled, on the bytes finalization left
    behind, so the digest the wheel is about to carry describes exactly what
    the release publishes.

    Raises:
        BundleError: When asked for a target this host did not build.
    """
    if target != host_target():
        raise BundleError("A monitor archive is packed on its own native target")
    spec = BundleSpec(VAULTSPEC_RAG, VAULTSPEC_RAG.version_from_tag(tag), target)
    return build_monitor_archive(spec, raw, outdir)


def monitor_bytes(
    tag: str, target: str, archives: Path, wheel_dir: Path, raw: Path
) -> Path:
    """Stage the monitor the release wheel admits, verified before and after.

    The bundle build takes the monitor from the release's own provisioning
    archive rather than compiling a second one. The wheel it will carry is
    what says which bytes those may be: its pinned archive digest is checked
    before anything is extracted, and the pinned executable digest is checked
    on what comes out, before the bundle or the native proof touches it.

    Args:
        tag: The release tag naming the version.
        target: The target triple whose monitor is being staged.
        archives: Where the release's monitor archives were placed.
        wheel_dir: Where the release wheel lies.
        raw: The staging directory the bundle build and the proof read.

    Returns:
        The staged, target-qualified monitor executable.

    Raises:
        BundleError: When asked for a target this host cannot prove, or when
            the wheel admits no monitor for it.
        ChecksumMismatchError: When the archive is not the one the wheel
            admits, in which case the archive is deleted unextracted.
        NativeBinaryVerificationError: When the extracted monitor is not the
            one the wheel admits.
    """
    if target != host_target():
        raise BundleError("Monitor bytes are staged on their own native target")
    version = VAULTSPEC_RAG.version_from_tag(tag)
    spec = BundleSpec(VAULTSPEC_RAG, version, target)
    archive = archives / spec.monitor_archive
    archive_sha256, executable_sha256 = admitted_monitor_pins(
        sole_wheel(wheel_dir), spec
    )
    raw.mkdir(parents=True, exist_ok=True)
    destination = raw / VAULTSPEC_RAG.asset_name(MONITOR_EXECUTABLE, target)
    with tempfile.TemporaryDirectory(prefix="monitor-bytes-") as scratch:
        extracted, _ = extract_verified_archive(
            archive, archive_sha256, Path(scratch), binary_name=spec.monitor_member
        )
        verify_native_binary(extracted, executable_sha256)
        verify_monitor_archive(archive, spec)
        shutil.copy2(extracted, destination)
    verify_native_binary(destination, executable_sha256)
    write_checksum(destination)
    return destination


def verify_release_set(
    directory: Path, tag: str, revision: str, lock: str, frontend: str
) -> None:
    version = VAULTSPEC_RAG.version_from_tag(tag)
    expected = {
        VAULTSPEC_RAG.bundle_name(version, t) for t in VAULTSPEC_RAG.supported_targets
    }
    actual = {
        p.name
        for p in directory.glob("vaultspec-rag-v*")
        if p.suffix in {".gz", ".zip"}
    }
    if actual != expected:
        raise BundleError("Release archive set differs from the native target matrix")
    for target in VAULTSPEC_RAG.supported_targets:
        spec = BundleSpec(VAULTSPEC_RAG, version, target)
        manifest = verify_bundle(directory / spec.archive_name, spec)
        components = cast("dict[str, dict[str, object]]", manifest["components"])
        name = VAULTSPEC_RAG.executable_name(MONITOR_EXECUTABLE, target)
        proof = cast("dict[str, object]", components[name]["verification"])
        if (
            manifest["source_revision"] != revision
            or proof["lock_sha256"] != lock
            or proof["frontend_sha256"] != frontend
        ):
            raise BundleError(
                "Release archive set contains a different producer or lock"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=(
            "wheel",
            "monitor-archive",
            "monitor-bytes",
            "native-smoke",
            "verify-set",
        ),
    )
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-revision")
    parser.add_argument("--target")
    parser.add_argument("--os-offline", action="store_true")
    parser.add_argument("--frontend-sha256")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument(
        "--outdir", type=Path, help="where a packed monitor archive is written"
    )
    parser.add_argument(
        "--archive-dir", type=Path, help="where the release's monitor archives lie"
    )
    parser.add_argument(
        "--wheel-dir", type=Path, help="where the release wheel being carried lies"
    )
    args = parser.parse_args()
    if args.operation == "wheel":
        verify_release_wheel(
            sole_wheel(args.directory),
            VAULTSPEC_RAG.version_from_tag(args.tag),
            ROOT / "src",
        )
    elif args.operation == "monitor-archive":
        if not args.target or args.outdir is None:
            parser.error("Packing a monitor archive requires --target and --outdir")
        print(monitor_archive(args.tag, args.target, args.directory, args.outdir))
    elif args.operation == "monitor-bytes":
        if not args.target or args.archive_dir is None or args.wheel_dir is None:
            parser.error(
                "Staging monitor bytes requires --target, --archive-dir and --wheel-dir"
            )
        print(
            monitor_bytes(
                args.tag,
                args.target,
                args.archive_dir,
                args.wheel_dir,
                args.directory,
            )
        )
    else:
        if not args.source_revision:
            parser.error("Native release checks require --source-revision")
        if args.operation == "native-smoke":
            if not args.target:
                parser.error("Native smoke requires --target")
            native_smoke(
                args.tag,
                args.source_revision,
                args.target,
                args.directory,
                os_offline=args.os_offline,
            )
        else:
            if not args.frontend_sha256:
                parser.error("Release-set verification requires --frontend-sha256")
            verify_release_set(
                args.directory,
                args.tag,
                args.source_revision,
                file_sha256(ROOT / "package-lock.json"),
                args.frontend_sha256,
            )


if __name__ == "__main__":
    main()
