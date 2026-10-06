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
from tools.binaries.release_hosts import GITHUB_RELEASE_REDIRECT_HOSTS
from tools.packaging.products import executable_filename
from vaultspec_rag.qdrant_runtime._download import download_https
from vaultspec_rag.qdrant_runtime._provision import (
    extract_verified_archive,
    verify_native_binary,
)

if TYPE_CHECKING:
    from pathlib import Path


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
            with archive.open("wb") as out:
                download_https(
                    f"{BUN_RELEASE}/{asset}",
                    out,
                    redirect_hosts=GITHUB_RELEASE_REDIRECT_HOSTS,
                )
            binary, _ = extract_verified_archive(
                archive, digest, directory, binary_name=binary.name
            )
        finally:
            archive.unlink(missing_ok=True)
    verify_native_binary(binary, BUN_EXECUTABLES[target])
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
