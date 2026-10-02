"""The public launch boundary uses committed authority, never a local proposal."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, replace
from typing import TYPE_CHECKING

import pytest

from tools.monitor.acquire import extract_delivery
from tools.monitor.pins import (
    CATALOG,
    SCHEMA,
    PinError,
    ReleasePins,
    TargetPins,
    catalog_at_commit,
    parse_catalog,
    require_release,
)
from tools.packaging.bundles import BundleSpec, build_bundle
from tools.packaging.checksums import ChecksumError, parse_checksums
from tools.packaging.products import MONITOR_EXECUTABLE, VAULTSPEC_RAG, WINDOWS_X86_64
from tools.packaging.tests.test_bundles import REVISION, VERSION, _raw_outputs

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def test_uncommitted_catalog_proposal_cannot_authorize_launch(tmp_path: Path) -> None:
    path = tmp_path / CATALOG
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema": SCHEMA, "releases": {}}), encoding="utf-8")
    for args in (
        ["git", "init", "-q"],
        ["git", "add", CATALOG],
        [
            "git",
            "-c",
            "user.name=Pin tests",
            "-c",
            "user.email=pins@example.invalid",
            "commit",
            "-qm",
            "Seed committed authority",
        ],
    ):
        subprocess.run(args, cwd=tmp_path, check=True, capture_output=True)
    proposal = {
        "schema": SCHEMA,
        "releases": {
            VAULTSPEC_RAG.tag_for(VERSION): asdict(
                ReleasePins(
                    REVISION,
                    "b" * 64,
                    "c" * 64,
                    {
                        target: TargetPins("d" * 64, "e" * 64)
                        for target in VAULTSPEC_RAG.supported_targets
                    },
                )
            ),
        },
    }
    path.write_text(json.dumps(proposal), encoding="utf-8")
    authority, catalog = catalog_at_commit(tmp_path)
    assert len(authority) == 40
    assert catalog == {}
    # Reading the working file instead of the committed object fails above.
    with pytest.raises(PinError, match="No independently reviewed"):
        require_release(catalog, VAULTSPEC_RAG.tag_for(VERSION), REVISION)


def test_release_pins_require_complete_native_coverage() -> None:
    tag = VAULTSPEC_RAG.tag_for(VERSION)
    targets = {
        target: {"archive_sha256": "d" * 64, "monitor_sha256": "e" * 64}
        for target in VAULTSPEC_RAG.supported_targets
    }
    payload = {
        "schema": SCHEMA,
        "releases": {
            tag: {
                "source_revision": REVISION,
                "lock_sha256": "b" * 64,
                "frontend_sha256": "c" * 64,
                "targets": targets,
            }
        },
    }
    pins = require_release(parse_catalog(payload), tag, REVISION)
    assert set(pins.targets) == set(VAULTSPEC_RAG.supported_targets)
    del targets[WINDOWS_X86_64]
    with pytest.raises(PinError, match="every supported"):
        parse_catalog(payload)


def test_public_extraction_checks_independent_producer_before_writing(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "LICENSE").write_text("license\n", encoding="utf-8")
    raw = _raw_outputs(tmp_path, WINDOWS_X86_64)
    spec = BundleSpec(VAULTSPEC_RAG, VERSION, WINDOWS_X86_64)
    archive = build_bundle(spec, raw, tmp_path / "bundles", repo, REVISION)
    monitor = raw / VAULTSPEC_RAG.asset_name(MONITOR_EXECUTABLE, WINDOWS_X86_64)
    pins = ReleasePins(
        REVISION,
        hashlib.sha256((repo / "package-lock.json").read_bytes()).hexdigest(),
        "c" * 64,
        {
            WINDOWS_X86_64: TargetPins(
                hashlib.sha256(archive.read_bytes()).hexdigest(),
                hashlib.sha256(monitor.read_bytes()).hexdigest(),
            )
        },
    )
    destination = tmp_path / "refused"
    # Bypassing producer admission must fail this refusal before extraction.
    with pytest.raises(PinError, match="identity mismatch before extraction"):
        extract_delivery(
            archive, spec, replace(pins, source_revision="b" * 40), destination
        )
    assert not destination.exists()
    extracted = tmp_path / "extracted"
    digests = extract_delivery(archive, spec, pins, extracted)
    assert len(list(extracted.iterdir())) == 3
    assert (
        extracted / "vaultspec-rag-monitor.exe"
    ).read_bytes() == monitor.read_bytes()
    assert (
        digests["vaultspec-rag-monitor.exe"]
        == pins.targets[WINDOWS_X86_64].monitor_sha256
    )


def test_live_checksum_duplicates_are_not_acquisition_authority() -> None:
    text = ("a" * 64 + "  archive.zip\n") * 2
    # Ignoring identical duplicate entries must fail this admission assertion.
    with pytest.raises(ChecksumError, match="twice"):
        parse_checksums(text, require_unique=True)
