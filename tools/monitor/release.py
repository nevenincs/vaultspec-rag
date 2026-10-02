"""Shared release admission for the canonical wheel and native monitor evidence."""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path
from typing import cast

from tools.binaries.build_pyapp import sole_wheel, validate_project_wheel
from tools.binaries.native import host_target_triple
from tools.monitor.smoke import installed_browser, probe
from tools.packaging.bundles import SMOKE_NAME, BundleError, BundleSpec, verify_bundle
from tools.packaging.checksums import read_checksums, require
from tools.packaging.products import MONITOR_EXECUTABLE, VAULTSPEC_RAG
from vaultspec_rag.qdrant_runtime._provision import file_sha256

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


def native_smoke(tag: str, revision: str, target: str, raw: Path) -> None:
    if target != host_target_triple():
        raise BundleError("Monitor evidence requires the native declared target")
    name = VAULTSPEC_RAG.asset_name(MONITOR_EXECUTABLE, target)
    binary = raw / name
    digest = require(read_checksums(binary.with_name(name + ".sha256")), name)
    report = probe(
        binary,
        digest,
        {
            "command": MONITOR_EXECUTABLE.name,
            "version": VAULTSPEC_RAG.version_from_tag(tag),
            "source_revision": revision,
            "development": False,
        },
        installed_browser(),
    )
    (raw / SMOKE_NAME).write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


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
    parser.add_argument("operation", choices=("wheel", "native-smoke", "verify-set"))
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-revision")
    parser.add_argument("--target")
    parser.add_argument("--frontend-sha256")
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    if args.operation == "wheel":
        verify_release_wheel(
            sole_wheel(args.directory),
            VAULTSPEC_RAG.version_from_tag(args.tag),
            ROOT / "src",
        )
    else:
        if not args.source_revision:
            parser.error("Native release checks require --source-revision")
        if args.operation == "native-smoke":
            if not args.target:
                parser.error("Native smoke requires --target")
            native_smoke(args.tag, args.source_revision, args.target, args.directory)
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
