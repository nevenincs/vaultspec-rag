"""A Hugging Face model cache whose contents a test decides.

Whether the configured model repositories are cached is a fact about the host:
a developer's workstation holds all of them and a fresh runner holds none. A
test of what a command does when the models are present, or when one is
missing, would otherwise assert whichever of those the machine happened to be -
or download several gigabytes to find out.

This points the hub's cache location at a directory the test owns and seeds it
with snapshots that pass the product's own snapshot check. Only the location
is substituted: the check, the offline switch, the decision to fetch, and the
reporting all run unchanged against real files. The location has to be set on
the hub's module because the hub reads its environment once, when it is first
imported, and a test process has long since imported it.

The models seeded are stand-ins an operator might have named, not the default
ones. A default model's snapshot is accepted only when every file matches the
digest committed for it, and those files are gigabytes of weights, so no
fixture can stand in for one. That is the property under test elsewhere, not
an obstacle here: a model the operator named is checked for its files and its
weight format, which a small fixture satisfies honestly.
"""

from __future__ import annotations

import hashlib
import os
from types import MappingProxyType
from typing import TYPE_CHECKING

from ..config._settings import configured_model_repos
from ..config._types import EnvVar

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping
    from pathlib import Path

    import pytest

#: The dense and reranker repositories seeded when a test names none.
STAND_IN_DENSE = "vaultspec-test/dense"
STAND_IN_RERANKER = "vaultspec-test/reranker"

#: The files a snapshot of an operator-named model needs to pass the check: a
#: config, a tokenizer, and safetensors weights.
ORDINARY_FILES: Mapping[str, bytes] = MappingProxyType(
    {
        "config.json": b"{}",
        "tokenizer.json": b"{}",
        "model.safetensors": b"fixture",
    }
)

_DEFAULT_REVISION = "0123456789abcdef0123456789abcdef01234567"


def seed_snapshot(
    cache: Path,
    repo: str,
    revision: str,
    files: Mapping[str, bytes],
    *,
    links: bool = False,
) -> Path:
    """Write one snapshot in the hub client's cache layout and return it.

    With *links* each snapshot entry is a link to a content blob, which is
    how the client stores a snapshot where the platform allows it; otherwise
    each is a plain file, which is what it falls back to.

    Raises:
        OSError: With *links*, when this account cannot create a link.
    """
    repo_dir = cache / f"models--{repo.replace('/', '--')}"
    snapshot = repo_dir / "snapshots" / revision
    snapshot.mkdir(parents=True)
    (repo_dir / "refs").mkdir(exist_ok=True)
    (repo_dir / "refs" / "main").write_text(revision, encoding="utf-8")
    blobs = repo_dir / "blobs"
    blobs.mkdir(exist_ok=True)
    for name, content in files.items():
        entry = snapshot / name
        entry.parent.mkdir(parents=True, exist_ok=True)
        if links:
            blob = blobs / hashlib.sha256(name.encode() + content).hexdigest()
            blob.write_bytes(content)
            os.symlink(os.path.relpath(blob, entry.parent), entry)
        else:
            entry.write_bytes(content)
    return snapshot


def point_hub_cache(monkeypatch: pytest.MonkeyPatch, cache: Path) -> Path:
    """Make *cache* the directory the hub client resolves snapshots in.

    The client fixes its cache location from the environment once, when it is
    first imported, so a test process can move it only here. Nothing else is
    substituted: the probe, the check and the load read *cache* as they would
    read the real one.

    Args:
        monkeypatch: Restores the real location after the test.
        cache: A directory the test owns; created when absent.

    Returns:
        The cache directory.
    """
    import huggingface_hub.constants as hub_constants

    cache.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(hub_constants, "HF_HUB_CACHE", str(cache))
    return cache


def seed_model_cache(
    monkeypatch: pytest.MonkeyPatch,
    cache: Path,
    *,
    missing: Collection[str] = (),
) -> Path:
    """Point the hub at *cache*, name stand-in models, and seed all but *missing*.

    A model setting the test has already made is left alone, so a test that
    names its own repository gets that one. Sparse vectors are turned off
    unless the test set the switch, because the sparse model cannot be
    renamed and its default cannot be seeded.

    Args:
        monkeypatch: Restores the hub's real cache location and the model
            settings after the test.
        cache: A directory the test owns; created when absent.
        missing: Repository ids to leave out, so the check finds them absent.

    Returns:
        The cache directory.
    """
    point_hub_cache(monkeypatch, cache)
    for var, stand_in in (
        (EnvVar.EMBEDDING_MODEL, STAND_IN_DENSE),
        (EnvVar.RERANKER_MODEL, STAND_IN_RERANKER),
        (EnvVar.SPARSE_ENABLED, "0"),
    ):
        if var.value not in os.environ:
            monkeypatch.setenv(var.value, stand_in)
    for model in configured_model_repos():
        assert not model.pinned, (
            f"{model.repo} is a default model: its snapshot is held to "
            "committed digests and cannot be seeded by a fixture"
        )
        if model.repo in missing:
            continue
        seed_snapshot(
            cache, model.repo, model.revision or _DEFAULT_REVISION, ORDINARY_FILES
        )
    return cache
