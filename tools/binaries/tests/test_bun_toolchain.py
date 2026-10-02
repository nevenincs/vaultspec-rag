"""Bun pins and the actual native artifact admission path."""

from __future__ import annotations

import zipfile
from typing import TYPE_CHECKING

import pytest

from tools.binaries.bun_pins import BUN_ARCHIVES, BUN_EXECUTABLES
from tools.packaging.products import VAULTSPEC_RAG
from vaultspec_rag.qdrant_runtime._provision import (
    ChecksumMismatchError,
    extract_verified_archive,
    file_sha256,
    verify_native_binary,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def test_bun_pins_cover_each_delivery_host() -> None:
    assert (
        set(BUN_ARCHIVES)
        == set(BUN_EXECUTABLES)
        == set(VAULTSPEC_RAG.supported_targets)
    )


def test_bun_archive_name_is_flattened_after_verification(tmp_path: Path) -> None:
    archive = tmp_path / "bun.zip"
    with zipfile.ZipFile(archive, "w") as source:
        source.writestr("../../outside/bun", b"native runtime")
    directory = tmp_path / "verified"
    directory.mkdir()
    binary, digest = extract_verified_archive(
        archive, file_sha256(archive), directory, binary_name="bun"
    )
    assert binary == directory / "bun"
    assert binary.read_bytes() == b"native runtime"
    assert digest == file_sha256(binary)


def test_bun_archive_mismatch_never_extracts(tmp_path: Path) -> None:
    archive = tmp_path / "bun.zip"
    with zipfile.ZipFile(archive, "w") as source:
        source.writestr("bun", b"untrusted")
    # Bypassing the archive comparison must fail the expected mismatch branch.
    with pytest.raises(ChecksumMismatchError):
        extract_verified_archive(archive, "0" * 64, tmp_path, binary_name="bun")
    assert not (tmp_path / "bun").exists()


def test_bun_executable_mismatch_is_refused(tmp_path: Path) -> None:
    binary = tmp_path / "bun"
    binary.write_bytes(b"modified cache")
    # Removing the executable digest comparison must fail this assertion.
    with pytest.raises(RuntimeError, match="Native executable pin mismatch"):
        verify_native_binary(binary, BUN_EXECUTABLES["x86_64-pc-windows-msvc"])


def test_bun_ambiguous_members_are_refused(tmp_path: Path) -> None:
    archive = tmp_path / "bun.zip"
    with zipfile.ZipFile(archive, "w") as source:
        source.writestr("first/bun", b"first")
        source.writestr("second/bun", b"second")
    # Accepting the first matching member must fail this admission assertion.
    with pytest.raises(RuntimeError, match="requires one regular bun member"):
        extract_verified_archive(
            archive, file_sha256(archive), tmp_path, binary_name="bun"
        )
