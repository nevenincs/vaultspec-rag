"""Admit native release bytes through workflow-bound GitHub attestations."""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from tools.monitor.release import verify_release_set
from tools.packaging.bundles import BundleError, BundleSpec, verify_bundle
from tools.packaging.products import MONITOR_EXECUTABLE, VAULTSPEC_RAG
from vaultspec_rag.qdrant_runtime._provision import file_sha256

REPOSITORY = "nevenincs/vaultspec-rag"
SIGNER_WORKFLOW = f"{REPOSITORY}/.github/workflows/binaries.yml"


@dataclass(frozen=True)
class TargetProof:
    archive_sha256: str
    monitor_sha256: str


@dataclass(frozen=True)
class DeliveryProof:
    source_revision: str
    lock_sha256: str
    frontend_sha256: str
    targets: dict[str, TargetProof]


class ProvenanceError(BundleError):
    """The release does not carry the required authenticated build identity."""


def _version(tag: str) -> str:
    if not re.fullmatch(r"vaultspec-rag-v\d+\.\d+\.\d+(?:[-.][0-9A-Za-z.]+)?", tag):
        raise ProvenanceError("Expected a canonical release tag")
    return VAULTSPEC_RAG.version_from_tag(tag)


def release_commit(tag: str) -> str:
    """Resolve the exact public tag, including annotated tags, to a commit."""
    _version(tag)
    ref = f"refs/tags/{tag}"
    result = subprocess.run(
        [
            "git",
            "ls-remote",
            "--tags",
            f"https://github.com/{REPOSITORY}.git",
            ref,
            ref + "^{}",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    refs = dict(line.split()[::-1] for line in result.stdout.splitlines())
    producer = refs.get(ref + "^{}", refs.get(ref, ""))
    if not re.fullmatch(r"[0-9a-f]{40}", producer):
        raise ProvenanceError("The exact release tag does not resolve to a commit")
    return producer


def admit_archive(archive: Path, spec: BundleSpec, producer: str) -> DeliveryProof:
    """Authenticate the bytes before inspecting their manifest or extracting."""
    if not re.fullmatch(r"[0-9a-f]{40}", producer):
        raise ProvenanceError("Release provenance requires a full source commit")
    if (
        archive.is_symlink()
        or not archive.is_file()
        or archive.name != spec.archive_name
    ):
        raise ProvenanceError("Expected a regular native release archive")
    digest = file_sha256(archive)
    tag = spec.product.tag_for(spec.version)
    result = subprocess.run(
        [
            "gh",
            "attestation",
            "verify",
            str(archive),
            "--repo",
            REPOSITORY,
            "--signer-workflow",
            SIGNER_WORKFLOW,
            "--cert-identity",
            f"https://github.com/{SIGNER_WORKFLOW}@refs/tags/{tag}",
            "--source-ref",
            f"refs/tags/{tag}",
            "--source-digest",
            producer,
            "--signer-digest",
            producer,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if result.returncode:
        raise ProvenanceError(
            f"Release attestation refused {archive.name}: {result.stderr}"
        )
    if file_sha256(archive) != digest:
        raise ProvenanceError("Release archive changed during attestation verification")
    manifest = verify_bundle(archive, spec)
    if manifest["source_revision"] != producer:
        raise ProvenanceError(
            "Authenticated archive producer differs from the release commit"
        )
    components = cast("dict[str, dict[str, object]]", manifest["components"])
    monitor = spec.product.executable_name(MONITOR_EXECUTABLE, spec.target)
    proof = cast("dict[str, str]", components[monitor]["verification"])
    return DeliveryProof(
        producer,
        proof["lock_sha256"],
        proof["frontend_sha256"],
        {spec.target: TargetProof(digest, proof["sha256"])},
    )


def validate_release(directory: Path, tag: str, producer: str) -> None:
    """Authenticate every declared archive before the native set is inspected."""
    version = _version(tag)
    proofs: list[DeliveryProof] = []
    for target in VAULTSPEC_RAG.supported_targets:
        spec = BundleSpec(VAULTSPEC_RAG, version, target)
        proofs.append(admit_archive(directory / spec.archive_name, spec, producer))
    first = proofs[0]
    if any(
        (proof.lock_sha256, proof.frontend_sha256)
        != (first.lock_sha256, first.frontend_sha256)
        for proof in proofs
    ):
        raise ProvenanceError(
            "Authenticated targets do not share one frontend and lock"
        )
    verify_release_set(
        directory, tag, producer, first.lock_sha256, first.frontend_sha256
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    validate_release(args.directory, args.tag, args.source_revision)
    print(f"Release admitted by authenticated provenance at {args.source_revision}")


if __name__ == "__main__":
    main()
