"""Committed release pins and a candidate-only handoff for independent review."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

from tools.monitor.release import verify_release_set
from tools.packaging.bundles import BundleError, BundleSpec, verify_bundle
from tools.packaging.products import MONITOR_EXECUTABLE, VAULTSPEC_RAG
from vaultspec_rag.qdrant_runtime._provision import file_sha256

SCHEMA = "vaultspec.monitor.release-pins.v1"
CATALOG = "tools/monitor/release-pins.json"
ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class TargetPins:
    archive_sha256: str
    monitor_sha256: str


@dataclass(frozen=True)
class ReleasePins:
    source_revision: str
    lock_sha256: str
    frontend_sha256: str
    targets: dict[str, TargetPins]


class PinError(BundleError):
    """The committed review authority does not admit these release bytes."""


def parse_catalog(payload: object) -> dict[str, ReleasePins]:
    if not isinstance(payload, dict) or set(payload) != {"schema", "releases"}:
        raise PinError("Invalid release pin catalog")
    if payload["schema"] != SCHEMA or not isinstance(payload["releases"], dict):
        raise PinError("Invalid release pin catalog schema")
    result: dict[str, ReleasePins] = {}
    for tag, entry in payload["releases"].items():
        if not isinstance(tag, str) or not re.fullmatch(
            r"vaultspec-rag-v\d+\.\d+\.\d+(?:[-.][0-9A-Za-z.]+)?", tag
        ):
            raise PinError("Invalid pinned release tag")
        if not isinstance(entry, dict) or set(entry) != {
            "source_revision",
            "lock_sha256",
            "frontend_sha256",
            "targets",
        }:
            raise PinError("Invalid pinned release identity")
        for key, length in (
            ("source_revision", 40),
            ("lock_sha256", 64),
            ("frontend_sha256", 64),
        ):
            if not isinstance(entry[key], str) or not re.fullmatch(
                rf"[0-9a-f]{{{length}}}", entry[key]
            ):
                raise PinError(f"Invalid pinned {key}")
        targets = entry["targets"]
        if not isinstance(targets, dict) or set(targets) != set(
            VAULTSPEC_RAG.supported_targets
        ):
            raise PinError("Release pins must cover every supported native target")
        pins: dict[str, TargetPins] = {}
        for target, hashes in targets.items():
            if not isinstance(hashes, dict) or set(hashes) != {
                "archive_sha256",
                "monitor_sha256",
            }:
                raise PinError("Invalid target release pins")
            if not all(
                isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
                for value in hashes.values()
            ):
                raise PinError("Invalid target release digest")
            pins[target] = TargetPins(**hashes)
        result[tag] = ReleasePins(
            entry["source_revision"],
            entry["lock_sha256"],
            entry["frontend_sha256"],
            pins,
        )
    return result


def catalog_at_commit(
    repo: Path, revision: str | None = None
) -> tuple[str, dict[str, ReleasePins]]:
    if revision is None:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            text=True,
            capture_output=True,
            check=True,
            timeout=15,
        ).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise PinError("Catalog authority requires a full committed revision")
    blob = subprocess.run(
        ["git", "show", f"{revision}:{CATALOG}"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
        timeout=15,
    )
    return revision, parse_catalog(json.loads(blob.stdout))


def require_release(
    catalog: dict[str, ReleasePins], tag: str, producer: str | None
) -> ReleasePins:
    entry = catalog.get(tag)
    if entry is None:
        raise PinError(f"No independently reviewed committed pins for {tag}")
    if producer is not None and entry.source_revision != producer:
        raise PinError("Requested producer differs from the committed release pins")
    return entry


def validate_release(directory: Path, tag: str, pins: ReleasePins) -> None:
    version = VAULTSPEC_RAG.version_from_tag(tag)
    # Verify approved archive hashes before reading or extracting archive contents.
    for target, hashes in pins.targets.items():
        path = directory / VAULTSPEC_RAG.bundle_name(version, target)
        if (
            path.is_symlink()
            or not path.is_file()
            or file_sha256(path) != hashes.archive_sha256
        ):
            raise PinError(f"Reviewed archive digest mismatch: {path.name}")
    verify_release_set(
        directory, tag, pins.source_revision, pins.lock_sha256, pins.frontend_sha256
    )
    for target, hashes in pins.targets.items():
        spec = BundleSpec(VAULTSPEC_RAG, version, target)
        manifest = verify_bundle(directory / spec.archive_name, spec)
        files = cast("list[dict[str, object]]", manifest["files"])
        monitor = VAULTSPEC_RAG.executable_name(MONITOR_EXECUTABLE, target)
        digest = next(item["sha256"] for item in files if item["name"] == monitor)
        if digest != hashes.monitor_sha256:
            raise PinError("Reviewed monitor digest mismatch")


def proposal(
    directory: Path, tag: str, producer: str, frontend: str
) -> dict[str, object]:
    lock = file_sha256(ROOT / "package-lock.json")
    verify_release_set(directory, tag, producer, lock, frontend)
    targets: dict[str, TargetPins] = {}
    version = VAULTSPEC_RAG.version_from_tag(tag)
    for target in VAULTSPEC_RAG.supported_targets:
        spec = BundleSpec(VAULTSPEC_RAG, version, target)
        archive = directory / spec.archive_name
        manifest = verify_bundle(archive, spec)
        components = cast("dict[str, dict[str, object]]", manifest["components"])
        monitor = VAULTSPEC_RAG.executable_name(MONITOR_EXECUTABLE, target)
        proof = cast("dict[str, str]", components[monitor]["verification"])
        targets[target] = TargetPins(file_sha256(archive), proof["sha256"])
    return {
        "schema": SCHEMA,
        "releases": {tag: asdict(ReleasePins(producer, lock, frontend, targets))},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("propose", "validate"))
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--catalog-revision")
    parser.add_argument("--frontend-sha256")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.operation == "propose":
        if not args.frontend_sha256 or args.output is None:
            parser.error("Pin proposals require --frontend-sha256 and --output")
        if args.output.resolve() == ROOT / CATALOG:
            parser.error("A proposal cannot overwrite the authoritative catalog")
        payload = proposal(
            args.directory, args.tag, args.source_revision, args.frontend_sha256
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(
            "Candidate only: independently review and commit the catalog "
            "before publication."
        )
    else:
        authority, catalog = catalog_at_commit(ROOT, args.catalog_revision)
        validate_release(
            args.directory,
            args.tag,
            require_release(catalog, args.tag, args.source_revision),
        )
        print(f"Release admitted by committed catalog {authority}")


if __name__ == "__main__":
    main()
