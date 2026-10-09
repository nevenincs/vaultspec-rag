"""Public archive admission requires authenticated exact-source provenance."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest

from tools.monitor import provenance
from tools.monitor.acquire import extract_delivery
from tools.monitor.provenance import (
    DeliveryProof,
    ProvenanceError,
    TargetProof,
    admit_archive,
    release_commit,
    validate_release,
)
from tools.packaging.bundles import BundleSpec, build_bundle, verify_bundle
from tools.packaging.checksums import ChecksumError, parse_checksums
from tools.packaging.products import MONITOR_EXECUTABLE, VAULTSPEC_RAG, WINDOWS_X86_64
from tools.packaging.tests.test_bundles import REVISION, VERSION, _raw_outputs

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _archive(tmp_path: Path, target: str = WINDOWS_X86_64) -> tuple[Path, BundleSpec]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    (repo / "LICENSE").write_text("license\n", encoding="utf-8")
    raw = _raw_outputs(tmp_path, target)
    spec = BundleSpec(VAULTSPEC_RAG, VERSION, target)
    return build_bundle(spec, raw, tmp_path / "bundles", repo, REVISION), spec


def test_attestation_failure_refuses_manifest_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation proof: removing return-code admission hit the manifest tripwire
    (exit 1); restoring the exact source passed (exit 0).
    """
    archive = tmp_path / VAULTSPEC_RAG.bundle_name(VERSION, WINDOWS_X86_64)
    archive.write_bytes(b"untrusted bytes with a matching live checksum")

    def refused(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 1, "", "certificate source mismatch")

    def untrusted_manifest(*_args: object, **_kwargs: object) -> None:
        pytest.fail("untrusted archive reached manifest inspection")

    monkeypatch.setattr(provenance.subprocess, "run", refused)
    monkeypatch.setattr(provenance, "verify_bundle", untrusted_manifest)
    with pytest.raises(ProvenanceError, match="Release attestation refused"):
        admit_archive(
            archive, BundleSpec(VAULTSPEC_RAG, VERSION, WINDOWS_X86_64), REVISION
        )


def test_admission_binds_certificate_to_repository_workflow_tag_and_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation proof: renaming source-digest failed the exact flag assertion
    (exit 1); restoring it passed (exit 0).
    """
    archive, spec = _archive(tmp_path)
    captured: list[list[str]] = []

    def verified(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        captured.append(command)
        return subprocess.CompletedProcess(command, 0, "verified", "")

    monkeypatch.setattr(provenance.subprocess, "run", verified)
    proof = admit_archive(archive, spec, REVISION)
    command = captured[0]
    assert command[:4] == ["gh", "attestation", "verify", str(archive)]
    flags = dict(zip(command[4::2], command[5::2], strict=True))
    tag = VAULTSPEC_RAG.tag_for(VERSION)
    assert flags == {
        "--repo": "nevenincs/vaultspec-rag",
        "--signer-workflow": "nevenincs/vaultspec-rag/.github/workflows/binaries.yml",
        "--cert-identity": f"https://github.com/nevenincs/vaultspec-rag/.github/workflows/binaries.yml@refs/tags/{tag}",
        "--source-ref": f"refs/tags/{tag}",
        "--source-digest": REVISION,
        "--signer-digest": REVISION,
    }
    assert proof.source_revision == REVISION
    assert (
        proof.targets[spec.target].archive_sha256
        == hashlib.sha256(archive.read_bytes()).hexdigest()
    )
    destination = tmp_path / "extracted"
    digests = extract_delivery(archive, spec, proof, destination)
    name = VAULTSPEC_RAG.executable_name(MONITOR_EXECUTABLE, spec.target)
    assert digests[name] == proof.targets[spec.target].monitor_sha256


def test_archive_mutation_during_attestation_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation proof: removing the second digest comparison failed with
    DID NOT RAISE (exit 1); restoring it passed (exit 0).
    """
    archive, spec = _archive(tmp_path)

    def changed(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        archive.write_bytes(archive.read_bytes() + b"changed after verification")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(provenance.subprocess, "run", changed)
    with pytest.raises(ProvenanceError, match="changed during attestation"):
        admit_archive(archive, spec, REVISION)


def test_authenticated_manifest_cannot_claim_a_different_producer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive, spec = _archive(tmp_path)
    monkeypatch.setattr(
        provenance.subprocess,
        "run",
        lambda *_a, **_kw: subprocess.CompletedProcess([], 0, "", ""),
    )
    with pytest.raises(ProvenanceError, match="producer differs"):
        admit_archive(archive, spec, "b" * 40)


def test_public_extraction_checks_producer_and_digest_before_writing(
    tmp_path: Path,
) -> None:
    archive, spec = _archive(tmp_path)
    manifest = verify_bundle(archive, spec)
    components = cast("dict[str, dict[str, object]]", manifest["components"])
    name = VAULTSPEC_RAG.executable_name(MONITOR_EXECUTABLE, spec.target)
    proof = cast("dict[str, str]", components[name]["verification"])
    pins = DeliveryProof(
        REVISION,
        proof["lock_sha256"],
        proof["frontend_sha256"],
        {
            spec.target: TargetProof(
                hashlib.sha256(archive.read_bytes()).hexdigest(), proof["sha256"]
            ),
        },
    )
    destination = tmp_path / "refused"
    with pytest.raises(ProvenanceError, match="identity mismatch before extraction"):
        extract_delivery(
            archive, spec, replace(pins, source_revision="b" * 40), destination
        )
    assert not destination.exists()
    with pytest.raises(ProvenanceError, match="digest mismatch before extraction"):
        extract_delivery(
            archive,
            spec,
            replace(
                pins, targets={spec.target: TargetProof("0" * 64, proof["sha256"])}
            ),
            destination,
        )
    assert not destination.exists()


def test_release_admission_requires_every_native_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "bundles"
    for target in VAULTSPEC_RAG.supported_targets:
        archive, _spec = _archive(tmp_path / target, target)
        directory.mkdir(exist_ok=True)
        (directory / archive.name).write_bytes(archive.read_bytes())
    monkeypatch.setattr(
        provenance.subprocess,
        "run",
        lambda *_a, **_kw: subprocess.CompletedProcess([], 0, "", ""),
    )
    tag = VAULTSPEC_RAG.tag_for(VERSION)
    validate_release(directory, tag, REVISION)
    (directory / VAULTSPEC_RAG.bundle_name(VERSION, WINDOWS_X86_64)).unlink()
    with pytest.raises(ProvenanceError, match="regular native release archive"):
        validate_release(directory, tag, REVISION)


def test_annotated_tag_is_peeled_and_tag_input_cannot_escape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tag = VAULTSPEC_RAG.tag_for(VERSION)
    refs = f"{'b' * 40}\trefs/tags/{tag}\n{REVISION}\trefs/tags/{tag}^{{}}\n"
    monkeypatch.setattr(
        provenance.subprocess,
        "run",
        lambda *_a, **_kw: subprocess.CompletedProcess([], 0, refs, ""),
    )
    assert release_commit(tag) == REVISION
    with pytest.raises(ProvenanceError, match="canonical release tag"):
        release_commit("../unexpected")


def test_live_checksum_duplicates_are_not_acquisition_authority() -> None:
    with pytest.raises(ChecksumError, match="twice"):
        parse_checksums(("a" * 64 + "  archive.zip\n") * 2, require_unique=True)
