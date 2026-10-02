"""Provision native Bun from reviewed pins using the runtime artifact boundary."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from tools.binaries.bun_pins import (
    BUN_ARCHIVES,
    BUN_EXECUTABLES,
    BUN_RELEASE,
    BUN_VERSION,
)
from tools.binaries.native import host_target_triple
from tools.packaging.products import executable_filename
from vaultspec_rag.qdrant_runtime._provision import (
    _download,
    extract_verified_archive,
    file_sha256,
)

if TYPE_CHECKING:
    from pathlib import Path


def verify_bun(binary: Path, target: str) -> None:
    """Rehash immediately before every compiler execution, including cache hits."""
    if binary.is_symlink() or file_sha256(binary) != BUN_EXECUTABLES[target]:
        raise RuntimeError(f"Bun executable pin mismatch: {binary}")


def provision_bun(cache: Path, target: str) -> Path:
    """Use native compilation so Bun cannot acquire an unreviewed cross target."""
    if target not in BUN_ARCHIVES or target != host_target_triple():
        raise ValueError(f"Bun compilation must use a supported native host: {target}")
    directory = cache.resolve() / BUN_VERSION / target
    directory.mkdir(parents=True, exist_ok=True)
    binary = directory / executable_filename("bun", target)
    if not binary.exists():
        asset, digest = BUN_ARCHIVES[target]
        archive = directory / asset
        try:
            _download(f"{BUN_RELEASE}/{asset}", archive)
            binary, _ = extract_verified_archive(
                archive, digest, directory, binary_name=binary.name
            )
        finally:
            archive.unlink(missing_ok=True)
    verify_bun(binary, target)
    result = subprocess.run(
        [str(binary), "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.stdout.strip() != BUN_VERSION:
        raise RuntimeError("The verified Bun runtime reported an unexpected version")
    return binary
